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

import sys

if len(sys.argv) > 2 and sys.argv[1] == "--apply-update":
    # Tryb aktualizatora: ten .exe lezy w rozpakowanej NOWEJ paczce i podmienia
    # pliki dzialajacej instalacji (katalog w argv[2], pid starej aplikacji w
    # argv[3]) — patrz src/updater.py. Musi byc PRZED reszta importow: nie
    # potrzebuje ani UI, ani aparatu, a wchodzi tu .exe, ktory dopiero ma sie
    # okazac sprawny.
    from src.updater import run_apply_update

    raise SystemExit(run_apply_update(sys.argv[2:]))

import argparse
import os
import threading
import webbrowser

from src.cli import add_capture_args
from src.config import APP_AUTHOR, APP_NAME
from src.webui import WebUI

__author__ = APP_AUTHOR


def main() -> None:
    parser = argparse.ArgumentParser(description="Live preview + capture (aplikacja okienkowa).")
    parser.add_argument("--port", type=int, default=0,
                        help="Port serwera (domyślnie losowy efemeryczny).")
    parser.add_argument("--browser", action="store_true",
                        help="Otwórz w przeglądarce zamiast natywnego okna.")
    add_capture_args(parser)
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
            os._exit(0)

    url = ui.start()
    webview.create_window(
        APP_NAME, url,
        width=1440, height=900, min_size=(1080, 700),
        background_color="#1a1a1c",
    )
    webview.start()
    # Uporzadkowane zamkniecie sesji aparatu, potem twarde wyjscie —
    # lingering watki C (libusb/onnxruntime/Cocoa) potrafia zawiesic
    # normalna finalizacje interpretera przy zamykaniu okna.
    ui.stop()
    os._exit(0)


if __name__ == "__main__":
    main()
