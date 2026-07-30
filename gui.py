#!/Users/xeross/Desktop/camera_capture/.venv/bin/python
"""Aplikacja desktopowa z live preview — UI 1:1 z projektu Claude Design.

Natywne okno (pywebview / WKWebView) z systemowym paskiem tytułu — prawdziwe
traffic lights macOS (działają też w fullscreen). Backend (src/webui.py)
serwuje UI + MJPEG na 127.0.0.1 tylko dla tego okna.

Uruchomienie:
    source .venv/bin/activate
    python3 gui.py
    python3 gui.py --name foo --no-upload
    python3 gui.py --browser        # fallback: zwykla przegladarka zamiast okna
"""

import argparse
import threading
import webbrowser
from pathlib import Path

from src.config import (
    AUTO_CENTER,
    AUTO_ZOOM,
    AUTOMAT_UPLOAD_ENABLED,
    DEFAULT_LOGO,
    DEFAULT_OUTPUT_DIR,
    LOGO_ENABLED,
    LOGO_POSITION,
)
from src.image_processing import LOGO_POSITIONS
from src.webui import WebUI


def main() -> None:
    parser = argparse.ArgumentParser(description="Live preview + capture (aplikacja okienkowa).")
    parser.add_argument("--name", type=str, help="Nazwa sesji zdjęciowej (= podfolder w photos/).")
    parser.add_argument("--logo", type=Path, default=DEFAULT_LOGO)
    parser.add_argument("--no-logo", dest="add_logo", action="store_false")
    parser.set_defaults(add_logo=LOGO_ENABLED)
    parser.add_argument("--logo-position", choices=LOGO_POSITIONS, default=LOGO_POSITION)
    parser.add_argument("--no-auto-center", dest="auto_center", action="store_false")
    parser.set_defaults(auto_center=AUTO_CENTER)
    parser.add_argument("--no-auto-zoom", dest="auto_zoom", action="store_false")
    parser.set_defaults(auto_zoom=AUTO_ZOOM)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--no-upload", dest="upload", action="store_false")
    parser.set_defaults(upload=AUTOMAT_UPLOAD_ENABLED)
    parser.add_argument("--port", type=int, default=0,
                        help="Port serwera (domyślnie losowy efemeryczny).")
    parser.add_argument("--browser", action="store_true",
                        help="Otwórz w przeglądarce zamiast natywnego okna.")
    args = parser.parse_args()

    ui = WebUI(
        logo=args.logo,
        base_output=args.output_dir,
        upload=args.upload,
        add_logo=args.add_logo,
        logo_position=args.logo_position,
        auto_center=args.auto_center,
        auto_zoom=args.auto_zoom,
        name=args.name,
        port=args.port,
    )

    try:
        import webview
    except ImportError:
        webview = None

    if args.browser or webview is None:
        if webview is None and not args.browser:
            print("pywebview niezainstalowany (pip install pywebview) — otwieram przeglądarkę.")
        url = ui.start()
        print(f"Camera Capture: {url}")
        webbrowser.open(url)
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
        finally:
            ui.stop()
        return

    url = ui.start()
    webview.create_window(
        "Camera Capture — Canon EOS M50 II", url,
        width=1440, height=900, min_size=(1080, 700),
        background_color="#1a1a1c",
    )
    webview.start()
    ui.stop()


if __name__ == "__main__":
    main()
