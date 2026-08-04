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
from pathlib import Path

from rich.console import Console
from rich.prompt import Confirm, Prompt

from src.automat_uploader import (AutomatUploader, describe_opened_session,
                                  find_existing_session)
from src.cli import add_capture_args
from src.config import AUTOMAT_API_TOKEN
from src.image_processing import process
from src.naming import sanitize_name

console = Console()


def make_uploader(enabled: bool, name: str) -> AutomatUploader | None:
    if not enabled or not AUTOMAT_API_TOKEN:
        return None
    try:
        u = AutomatUploader()
        match = find_existing_session(u, name)
        if match is not None and Confirm.ask(
            f"[yellow]Sesja [bold]{match['name']}[/bold] juz istnieje w Automacie "
            f"({(match.get('created_at') or '')[:10]}, zdjec: {match.get('photos_count', 0)}). "
            f"Podlaczyc do niej?[/]",
            default=True,
        ):
            u.attach_session(match["id"], name,
                             product_found=bool(match.get("product")),
                             photos_count=int(match.get("photos_count", 0)))
        else:
            u.open_session(name)
    except Exception as e:
        console.print(f"[red]Nie udalo sie otworzyc sesji w Automacie:[/] {e}")
        return None
    text, level = describe_opened_session(u, name)
    style = "bold cyan" if level == "ok" else "yellow"
    console.print(f"[{style}]{text}[/]")
    return u


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


def prompt_name(current: str | None = None) -> str:
    while True:
        raw = Prompt.ask(
            "[bold cyan]Nazwa sesji zdjęciowej[/]",
            default=current,
            show_default=bool(current),
        )
        if raw:
            return sanitize_name(raw)


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture, crop 1:1, overlay logo.")
    parser.add_argument("--input", type=Path, help="Pomiń aparat, użyj istniejącego pliku.")
    parser.add_argument(
        "--list-formats",
        action="store_true",
        help="Wypisz dostepne formaty/rozmiary zdjec na aparacie i zakoncz.",
    )
    add_capture_args(parser)
    args = parser.parse_args()

    if args.list_formats:
        import gphoto2 as gp

        from src.camera import list_image_formats

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
            add_logo=args.add_logo,
            logo_position=args.logo_position,
            auto_center=args.auto_center,
            auto_zoom=args.auto_zoom,
        )
        console.print(f"[bold green]✓ Zapisano[/] [yellow]{out}[/]")
        uploader = make_uploader(args.upload, name)
        upload_raw_or_log(uploader, out)
        return

    try:
        # Import leniwy: TUI ciagnie termios/tty (unix-only) — na Windowsie
        # dziala tylko sciezka --input oraz aplikacja okienkowa (gui.py).
        from src.tui import CaptureTUI
    except ImportError:
        console.print("[red]TUI działa tylko na macOS/Linux — na Windowsie "
                      "użyj [bold]python gui.py[/bold] albo --input.[/]")
        return

    try:
        CaptureTUI(
            logo=args.logo,
            base_output=args.output_dir,
            upload=args.upload,
            add_logo=args.add_logo,
            logo_position=args.logo_position,
            auto_center=args.auto_center,
            auto_zoom=args.auto_zoom,
        ).run()
    except (KeyboardInterrupt, EOFError):
        console.print("\n[dim]Przerwano.[/]")


if __name__ == "__main__":
    main()
