"""Handler HTTP aplikacji okienkowej — wydzielony z webui.py.

Sam transport: index.html + statyki (whitelist rozszerzen, bez podkatalogow),
MJPEG stream live view (/stream), /api/state, /api/action i /img (pliki sesji
+ okladki). Cala logika stanu zyje w WebUI — handler tylko dispatchuje do
`self.ui`, wstrzykiwanego subklasa w WebUI.start()."""

import json
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlparse

if TYPE_CHECKING:
    from .webui import WebUI

STATIC_DIR = Path(__file__).parent / "webui_static"
STATIC_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".woff2": "font/woff2",
}


class Handler(BaseHTTPRequestHandler):
    """Handler HTTP (instancja per request). Atrybut klasowy `ui` wstrzykiwany
    w WebUI.start() przez subklase — jeden serwer = jedno WebUI."""

    ui: "WebUI"

    def log_message(self, *_a):
        pass

    def _json(self, payload, code=200):
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authed(self) -> bool:
        q = parse_qs(urlparse(self.path).query)
        if q.get("t", [""])[0] == self.ui.token:
            return True
        return f"t={self.ui.token}" in self.headers.get("Cookie", "")

    def do_GET(self):
        if not self._authed():
            self.send_error(403)
            return
        url = urlparse(self.path)
        if url.path == "/":
            self._serve_index()
        elif url.path.startswith("/static/"):
            self._serve_static(url.path)
        elif url.path == "/api/state":
            q = parse_qs(url.query)
            try:
                since = int(q.get("since", ["0"])[0])
            except ValueError:
                since = 0
            self._json(self.ui.state(log_since=since))
        elif url.path == "/stream":
            self._serve_stream()
        elif url.path == "/img":
            self._serve_img(parse_qs(url.query))
        else:
            self.send_error(404)

    def _serve_index(self):
        body = (STATIC_DIR / "index.html").read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header(
            "Set-Cookie", f"t={self.ui.token}; HttpOnly; SameSite=Strict")
        self.end_headers()
        self.wfile.write(body)

    def _serve_static(self, path: str):
        """Statyki frontendu (style.css / app.js) z webui_static — tylko
        rozszerzenia z STATIC_TYPES, sama nazwa pliku (bez podkatalogow)."""
        name = Path(path).name
        ctype = STATIC_TYPES.get(Path(name).suffix)
        target = STATIC_DIR / name
        if ctype is None or not target.is_file():
            self.send_error(404)
            return
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_stream(self):
        """MJPEG live view: wysylamy TYLKO nowe klatki (next_frame czeka na
        Condition w WebUI). Poprzedni wariant spal 1/preview_fps i pchal te
        sama klatke w kolko, gdy aparat oddawal ich mniej — throttling do
        preview_fps robi juz petla watku camera, ktora klatki produkuje."""
        self.send_response(200)
        self.send_header(
            "Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.end_headers()
        last = 0
        try:
            while not self.ui._stop.is_set():
                frame, last = self.ui.next_frame(last, timeout=1.0)
                if frame is None:
                    continue
                self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n")
                self.wfile.write(f"Content-Length: {len(frame)}\r\n\r\n".encode())
                self.wfile.write(frame)
                self.wfile.write(b"\r\n")
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def _serve_img(self, q: dict):
        cover = q.get("cover", [""])[0]
        if cover:
            data = self.ui.cover_bytes(cover)
        else:
            data = self.ui.image_bytes(
                q.get("s", [""])[0], q.get("f", [""])[0],
                thumb=q.get("thumb", ["0"])[0] == "1",
            )
        if data is None:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if not self._authed():
            self.send_error(403)
            return
        if urlparse(self.path).path != "/api/action":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length", "0"))
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
            self._json(self.ui.action(data))
        except Exception as e:
            self._json({"ok": False, "error": str(e)}, 500)
