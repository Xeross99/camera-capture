#!/Users/xeross/Desktop/camera_capture/.venv/bin/python
"""
Capture photo from Canon EOS M50 Mark II via gphoto2,
crop to 1:1 (center), overlay logo, save to ./photos/<nazwa>/.

Aktywacja venv:
    source .venv/bin/activate

Uruchomienie:
    python3 main.py
    python3 main.py --input some.jpg --name foo
"""

import argparse
import re
import sys
import tempfile
import termios
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

from src.automat_uploader import AutomatUploader
from src.camera import capture_from_camera, list_image_formats
from src.config import (
    AUTOMAT_API_TOKEN,
    AUTOMAT_UPLOAD_ENABLED,
    DEFAULT_LOGO,
    DEFAULT_OUTPUT_DIR,
)
from src.image_processing import process

console = Console()


def make_uploader(enabled: bool, name: str) -> AutomatUploader | None:
    if not enabled or not AUTOMAT_API_TOKEN:
        return None
    try:
        u = AutomatUploader()
        u.open_session(name)
    except Exception as e:
        console.print(f"[red]Nie udalo sie otworzyc sesji w Automacie:[/] {e}")
        return None
    suffix = ""
    if u.reattached:
        suffix = f" — podlaczono do istniejacej ({u.photos_count} zdjec)"
    if u.product_found:
        console.print(f"[bold cyan]↑ Automat: sesja {u.session_id} ({name}){suffix}[/]")
    else:
        kind = "luzna" + (" (podlaczono)" if u.reattached else "")
        console.print(f"[yellow]↑ Automat: sesja {u.session_id} ({name}) — produkt nie znaleziony, sesja {kind}{suffix}[/]")
    return u


def announce_or_log(uploader: AutomatUploader | None, filename: str) -> int | None:
    if uploader is None:
        return None
    try:
        return uploader.announce_photo(filename)
    except Exception as e:
        console.print(f"[red]Announce do Automatu nie wyszedl:[/] {e}")
        return None


def upload_raw_or_log(uploader: AutomatUploader | None, out_path: Path,
                      photo_id: int | None = None) -> None:
    if uploader is None:
        return
    try:
        uploader.upload_processed(out_path, photo_id=photo_id)
    except Exception as e:
        console.print(f"[red]Upload do Automatu nie wyszedl:[/] {e}")
        return
    console.print("[bold cyan]↑ Wgrano przetworzone do Automatu[/]")


def drain_stdin() -> None:
    try:
        termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)
    except (termios.error, ValueError, OSError):
        pass


def sanitize_name(name: str) -> str:
    name = name.strip()
    name = re.sub(r"[^A-Za-z0-9_\-. ]+", "_", name)
    return name.strip(" .") or "default"


def prompt_name(current: str | None = None) -> str:
    while True:
        raw = Prompt.ask(
            "[bold cyan]Nazwa sesji zdjęciowej[/]",
            default=current,
            show_default=bool(current),
        )
        if raw:
            return sanitize_name(raw)


def show_help() -> None:
    table = Table.grid(padding=(0, 2))
    table.add_column(style="bold green", justify="right")
    table.add_column(style="white")
    table.add_row("[ENTER]", "zrob zdjecie")
    table.add_row("n", "zmień nazwę sesji zdjęciowej")
    table.add_row("u", "przelacz upload do Automatu ON/OFF")
    table.add_row("h", "pokaz pomoc")
    table.add_row("q", "wyjscie")
    console.print(Panel(table, title="[bold]Komendy", border_style="cyan", expand=False))


def session_header(name: str, count: int, base_output: Path, upload: bool) -> None:
    target = base_output / name
    body = Text()
    body.append("Folder: ", style="dim")
    body.append(str(target), style="bold yellow")
    body.append("\nZdjec w sesji: ", style="dim")
    body.append(str(count), style="bold magenta")
    body.append("\nUpload do Automatu: ", style="dim")
    body.append("ON" if upload else "OFF", style="bold green" if upload else "bold red")
    console.print(Panel(body, title=f"[bold cyan]{name}", border_style="green", expand=False))


def interactive_loop(logo: Path, base_output: Path, upload: bool = True) -> None:
    console.print(Panel.fit(
        "[bold]Camera Capture[/] [dim]· Canon EOS M50 II[/]",
        border_style="bright_magenta",
    ))
    name = prompt_name()
    show_help()
    count = 0
    uploader = make_uploader(upload, name)
    upload_active = uploader is not None
    session_header(name, count, base_output, upload_active)

    while True:
        drain_stdin()
        cmd = Prompt.ask(f"[bold green][{name}][/]", default="", show_default=False).strip().lower()
        if cmd == "q":
            console.print("[dim]Do zobaczenia.[/]")
            return
        if cmd == "h":
            show_help()
            continue
        if cmd == "n":
            name = prompt_name(name)
            count = 0
            uploader = make_uploader(upload, name)
            upload_active = uploader is not None
            session_header(name, count, base_output, upload_active)
            continue
        if cmd == "u":
            upload = not upload
            uploader = make_uploader(upload, name) if upload else None
            upload_active = uploader is not None
            console.print(f"Upload do Automatu: [bold {'green' if upload_active else 'red'}]{'ON' if upload_active else 'OFF'}[/]")
            continue
        if cmd != "":
            console.print("[red]Nieznana komenda.[/] Uzyj [bold]ENTER[/], [bold]n[/], [bold]u[/], [bold]h[/] lub [bold]q[/].")
            continue

        target_dir = base_output / name
        try:
            with tempfile.TemporaryDirectory() as td:
                with console.status("[cyan]Łączę z aparatem i wyzwalam migawkę…[/]", spinner="dots"):
                    captured = capture_from_camera(Path(td))
                # Announce filename to Automat right after capture so the
                # browser shows a placeholder card with a spinner while we
                # do the slow local processing.
                from datetime import datetime
                announced_filename = f"photo_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jpg"
                announced_id = announce_or_log(uploader, announced_filename)
                with console.status("[cyan]Czyszcze tlo / wyrownuje / centruje…[/]", spinner="dots"):
                    out = process(captured, logo, target_dir, clean_bg=True)
        except SystemExit as e:
            console.print(Panel(str(e), title="[bold red]Błąd aparatu", border_style="red"))
            continue

        count += 1
        console.print(f"[bold green]✓ Zapisano[/] [yellow]{out}[/]  [dim](#{count})[/]")
        upload_raw_or_log(uploader, out, photo_id=announced_id)


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture, crop 1:1, overlay logo.")
    parser.add_argument("--input", type=Path, help="Pomiń aparat, użyj istniejącego pliku.")
    parser.add_argument("--name", type=str, help="Nazwa sesji zdjęciowej (= podfolder w photos/).")
    parser.add_argument("--logo", type=Path, default=DEFAULT_LOGO)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--no-upload",
        dest="upload",
        action="store_false",
        help="Nie wgrywaj raw do Automatu (domyslnie ON gdy AUTOMAT_TOKEN ustawiony).",
    )
    parser.set_defaults(upload=AUTOMAT_UPLOAD_ENABLED)
    parser.add_argument(
        "--list-formats",
        action="store_true",
        help="Wypisz dostepne formaty/rozmiary zdjec na aparacie i zakoncz.",
    )
    args = parser.parse_args()

    if args.list_formats:
        import gphoto2 as gp

        cam = gp.Camera()
        cam.init()
        try:
            for name, choices in list_image_formats(cam).items():
                console.print(f"[bold cyan]{name}[/]: {choices}")
        finally:
            cam.exit()
        return

    if args.input:
        name = sanitize_name(args.name) if args.name else prompt_name()
        out = process(
            args.input,
            args.logo,
            args.output_dir / name,
            clean_bg=True,
        )
        console.print(f"[bold green]✓ Zapisano[/] [yellow]{out}[/]")
        uploader = make_uploader(args.upload, name)
        upload_raw_or_log(uploader, out)
        return

    try:
        interactive_loop(
            args.logo,
            args.output_dir,
            upload=args.upload,
        )
    except (KeyboardInterrupt, EOFError):
        console.print("\n[dim]Przerwano.[/]")


if __name__ == "__main__":
    main()
