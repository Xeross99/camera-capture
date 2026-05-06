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

from src.camera import capture_from_camera, list_image_formats
from src.config import DEFAULT_LOGO, DEFAULT_OUTPUT_DIR
from src.image_processing import process

console = Console()


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
            "[bold cyan]Nazwa folderu[/]",
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
    table.add_row("n", "zmien nazwe folderu")
    table.add_row("b", "przelacz biale tlo ON/OFF")
    table.add_row("h", "pokaz pomoc")
    table.add_row("q", "wyjscie")
    console.print(Panel(table, title="[bold]Komendy", border_style="cyan", expand=False))


def session_header(name: str, count: int, base_output: Path, clean_bg: bool) -> None:
    target = base_output / name
    body = Text()
    body.append("Folder: ", style="dim")
    body.append(str(target), style="bold yellow")
    body.append("\nZdjec w sesji: ", style="dim")
    body.append(str(count), style="bold magenta")
    body.append("\nBiale tlo: ", style="dim")
    body.append("ON" if clean_bg else "OFF", style="bold green" if clean_bg else "bold red")
    console.print(Panel(body, title=f"[bold cyan]{name}", border_style="green", expand=False))


def interactive_loop(logo: Path, base_output: Path, clean_bg: bool = True) -> None:
    console.print(Panel.fit(
        "[bold]Camera Capture[/] [dim]· Canon EOS M50 II[/]",
        border_style="bright_magenta",
    ))
    name = prompt_name()
    show_help()
    count = 0
    session_header(name, count, base_output, clean_bg)

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
            session_header(name, count, base_output, clean_bg)
            continue
        if cmd == "b":
            clean_bg = not clean_bg
            console.print(f"Biale tlo: [bold {'green' if clean_bg else 'red'}]{'ON' if clean_bg else 'OFF'}[/]")
            continue
        if cmd != "":
            console.print("[red]Nieznana komenda.[/] Uzyj [bold]ENTER[/], [bold]n[/], [bold]b[/], [bold]h[/] lub [bold]q[/].")
            continue

        target_dir = base_output / name
        try:
            with tempfile.TemporaryDirectory() as td:
                with console.status("[cyan]Łączę z aparatem i wyzwalam migawkę…[/]", spinner="dots"):
                    captured = capture_from_camera(Path(td))
                status_msg = (
                    "[cyan]Czyszcze tlo / wyrownuje / centruje…[/]"
                    if clean_bg else "[cyan]Przetwarzam…[/]"
                )
                with console.status(status_msg, spinner="dots"):
                    out = process(captured, logo, target_dir, clean_bg=clean_bg)
        except SystemExit as e:
            console.print(Panel(str(e), title="[bold red]Błąd aparatu", border_style="red"))
            continue

        count += 1
        console.print(f"[bold green]✓ Zapisano[/] [yellow]{out}[/]  [dim](#{count})[/]")


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture, crop 1:1, overlay logo.")
    parser.add_argument("--input", type=Path, help="Pomiń aparat, użyj istniejącego pliku.")
    parser.add_argument("--name", type=str, help="Nazwa podfolderu w photos/ (dla --input).")
    parser.add_argument("--logo", type=Path, default=DEFAULT_LOGO)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--no-clean-bg",
        dest="clean_bg",
        action="store_false",
        help="Nie czysc tla (domyslnie czysci na biale przez rembg).",
    )
    parser.set_defaults(clean_bg=True)
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
            clean_bg=args.clean_bg,
        )
        console.print(f"[bold green]✓ Zapisano[/] [yellow]{out}[/]")
        return

    try:
        interactive_loop(
            args.logo,
            args.output_dir,
            clean_bg=args.clean_bg,
        )
    except (KeyboardInterrupt, EOFError):
        console.print("\n[dim]Przerwano.[/]")


if __name__ == "__main__":
    main()
