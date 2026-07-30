#!/Users/xeross/Desktop/camera_capture/.venv/bin/python
"""Aplikacja desktopowa z live preview — UI 1:1 z projektu Claude Design.

Natywne okno (pywebview / WKWebView, frameless — pasek tytułu i „światełka"
rysowane w UI zgodnie z projektem, ale funkcjonalne). Backend (src/webui.py)
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


class _WindowApi:
    """Cele dla narysowanych 'swiatelek' macOS w pasku tytulu."""

    def __init__(self) -> None:
        self.window = None

    def close(self) -> None:
        if self.window:
            self.window.destroy()

    def minimize(self) -> None:
        if self.window:
            self.window.minimize()

    def zoom(self) -> None:
        if self.window:
            self.window.toggle_fullscreen()


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
    parser.add_argument("--port", type=int, default=8777)
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
    url = f"http://127.0.0.1:{args.port}"

    if args.browser:
        threading.Timer(0.8, webbrowser.open, [url]).start()
        ui.run()
        return

    try:
        import webview
    except ImportError:
        print("pywebview niezainstalowany (pip install pywebview) — otwieram przeglądarkę.")
        threading.Timer(0.8, webbrowser.open, [url]).start()
        ui.run()
        return

    threading.Thread(target=ui.run, daemon=True).start()
    api = _WindowApi()
    window = webview.create_window(
        "Camera Capture — Canon EOS M50 II", url,
        width=1440, height=900, frameless=True, easy_drag=False,
        background_color="#1a1a1c", js_api=api,
    )
    api.window = window
    webview.start()


if __name__ == "__main__":
    main()
