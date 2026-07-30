#!/Users/xeross/Desktop/camera_capture/.venv/bin/python
"""Aplikacja okienkowa z live preview (Tkinter).

Uruchomienie:
    source .venv/bin/activate
    python3 gui.py
    python3 gui.py --name foo --no-upload
"""

import argparse
from pathlib import Path

from src.config import (
    AUTO_CENTER,
    AUTO_ZOOM,
    AUTOMAT_UPLOAD_ENABLED,
    CONTRAST,
    DEFAULT_LOGO,
    DEFAULT_OUTPUT_DIR,
    LOGO_ENABLED,
    LOGO_POSITION,
)
from src.gui import CaptureGUI
from src.image_processing import LOGO_POSITIONS


def main() -> None:
    parser = argparse.ArgumentParser(description="Live preview + capture (GUI).")
    parser.add_argument("--name", type=str, help="Nazwa sesji zdjęciowej (= podfolder w photos/).")
    parser.add_argument("--logo", type=Path, default=DEFAULT_LOGO)
    parser.add_argument("--no-logo", dest="add_logo", action="store_false")
    parser.set_defaults(add_logo=LOGO_ENABLED)
    parser.add_argument("--logo-position", choices=LOGO_POSITIONS, default=LOGO_POSITION)
    parser.add_argument("--no-auto-center", dest="auto_center", action="store_false")
    parser.set_defaults(auto_center=AUTO_CENTER)
    parser.add_argument("--no-auto-zoom", dest="auto_zoom", action="store_false")
    parser.set_defaults(auto_zoom=AUTO_ZOOM)
    parser.add_argument(
        "--contrast", type=float, default=CONTRAST,
        help=f"Kontrast produktu, 1.0 = bez zmian (domyslnie {CONTRAST}).",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--no-upload", dest="upload", action="store_false")
    parser.set_defaults(upload=AUTOMAT_UPLOAD_ENABLED)
    args = parser.parse_args()

    CaptureGUI(
        logo=args.logo,
        base_output=args.output_dir,
        upload=args.upload,
        add_logo=args.add_logo,
        logo_position=args.logo_position,
        auto_center=args.auto_center,
        auto_zoom=args.auto_zoom,
        contrast=args.contrast,
        name=args.name,
    ).run()


if __name__ == "__main__":
    main()
