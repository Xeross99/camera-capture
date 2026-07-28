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
from rich.prompt import Prompt

from src.automat_uploader import AutomatUploader
from src.camera import list_image_formats
from src.config import (
    AUTO_CENTER,
    AUTO_ZOOM,
    AUTOMAT_API_TOKEN,
    AUTOMAT_UPLOAD_ENABLED,
    DEFAULT_LOGO,
    DEFAULT_OUTPUT_DIR,
    LOGO_ENABLED,
    LOGO_POSITION,
)
from src.image_processing import LOGO_POSITIONS, process
from src.tui import CaptureTUI, sanitize_name

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
    parser.add_argument("--name", type=str, help="Nazwa sesji zdjęciowej (= podfolder w photos/).")
    parser.add_argument("--logo", type=Path, default=DEFAULT_LOGO)
    parser.add_argument(
        "--no-logo",
        dest="add_logo",
        action="store_false",
        help="Nie nakladaj logo na finalny JPEG.",
    )
    parser.set_defaults(add_logo=LOGO_ENABLED)
    parser.add_argument(
        "--logo-position",
        choices=LOGO_POSITIONS,
        default=LOGO_POSITION,
        help=f"Rog, w ktorym laduje logo (domyslnie {LOGO_POSITION}).",
    )
    parser.add_argument(
        "--no-auto-center",
        dest="auto_center",
        action="store_false",
        help="Nie centruj produktu (zostaje w pozycji z kadru).",
    )
    parser.set_defaults(auto_center=AUTO_CENTER)
    parser.add_argument(
        "--no-auto-zoom",
        dest="auto_zoom",
        action="store_false",
        help="Nie przyblizaj produktu (naturalna skala z kadru).",
    )
    parser.set_defaults(auto_zoom=AUTO_ZOOM)
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
