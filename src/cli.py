"""Wspolne flagi CLI dla obu wejsc aplikacji: main.py (TUI) i gui.py (okno)."""

import argparse
from pathlib import Path

from .config import (
    AUTO_CENTER,
    AUTO_ZOOM,
    AUTOMAT_UPLOAD_ENABLED,
    DEFAULT_LOGO,
    DEFAULT_OUTPUT_DIR,
    LOGO_ENABLED,
    LOGO_POSITION,
)
from .image_processing import LOGO_POSITIONS


def add_capture_args(parser: argparse.ArgumentParser) -> None:
    """Sesja, logo, zoom/centrowanie, katalog wyjsciowy, upload do Automatu."""
    parser.add_argument(
        "--name", type=str, help="Nazwa sesji zdjęciowej (= podfolder w photos/)."
    )
    parser.add_argument("--logo", type=Path, default=DEFAULT_LOGO)
    parser.add_argument(
        "--no-logo",
        dest="add_logo",
        action="store_false",
        help="Nie nakladaj logo na finalny JPEG.",
    )
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
    parser.add_argument(
        "--no-auto-zoom",
        dest="auto_zoom",
        action="store_false",
        help="Nie przyblizaj produktu (naturalna skala z kadru).",
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--no-upload",
        dest="upload",
        action="store_false",
        help="Nie wgrywaj do Automatu (domyslnie ON gdy AUTOMAT_TOKEN ustawiony).",
    )
    parser.set_defaults(
        add_logo=LOGO_ENABLED,
        auto_center=AUTO_CENTER,
        auto_zoom=AUTO_ZOOM,
        upload=AUTOMAT_UPLOAD_ENABLED,
    )
