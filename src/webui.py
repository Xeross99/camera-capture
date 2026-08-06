"""Backend web UI (1:1 z projektu Claude Design "Camera Capture.dc.html").

Serwer HTTP (stdlib) + trzy watki jak w poprzednim GUI:
- camera: JEDYNY wlasciciel gphoto2 (preview loop z throttlingiem do
  preview_fps, komendy: shoot / preview on-off),
- worker: obrobka (rembg) + Automat (announce/upload/delete),
- HTTP (ThreadingHTTPServer): index.html, MJPEG stream, /api/state,
  /api/action (dispatcher), /img (pliki sesji + cache miniatur).

Stan recenzji per sesja w photos/<sesja>/.review.json:
{rejected: [...], uploaded: [...], meta: {plik: "logo · zoom · 3000×3000"}}.
"""

import io
import json
import queue
import secrets
import shutil
import tempfile
import threading
import time
from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np
from PIL import Image

from .automat_uploader import AutomatUploader, describe_opened_session
from .camera import CAMERA_ERRORS, make_camera_session
from .config import (
    AUTOMAT_API_TOKEN,
    AUTOMAT_BASE_URL,
    OUTPUT_SIZE,
    PROJECT_DIR,
)
from .image_processing import LOGO_POSITIONS, process
from .naming import sanitize_name

STATIC_DIR = Path(__file__).parent / "webui_static"
STATIC_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".woff2": "font/woff2",
}
THUMB_SIZE = 360
DEFAULT_NAME_PATTERN = "photo_{data}_{godzina}.jpg"


def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _persist_env(key: str, value: str) -> None:
    """Zapisuje/nadpisuje klucz w PROJECT_DIR/.env (tworzy plik gdy brak) —
    token/URL Automatu wpisane w Ustawieniach przezywaja restart aplikacji."""
    path = PROJECT_DIR / ".env"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    entry = f"{key}={value}"
    for i, ln in enumerate(lines):
        if ln.split("=", 1)[0].strip() == key:
            lines[i] = entry
            break
    else:
        lines.append(entry)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _review_path(session_dir: Path) -> Path:
    return session_dir / ".review.json"


def _load_review(session_dir: Path) -> dict:
    try:
        data = json.loads(_review_path(session_dir).read_text())
    except (OSError, ValueError):
        data = {}
    data.setdefault("rejected", [])
    data.setdefault("uploaded", [])
    data.setdefault("meta", {})
    data.setdefault("automat", {})  # plik -> id zdjecia w Automacie (do DELETE)
    return data


def _save_review(session_dir: Path, data: dict) -> None:
    session_dir.mkdir(parents=True, exist_ok=True)
    _review_path(session_dir).write_text(json.dumps(data, indent=1))


def _finals(session_dir: Path) -> list[str]:
    if not session_dir.is_dir():
        return []
    return sorted(
        p.name for p in session_dir.glob("*.jpg") if not p.stem.endswith("_raw")
    )


def _find_raw(session_dir: Path, final_name: str) -> Path | None:
    stem = Path(final_name).stem
    for cand in (session_dir / "raw" / f"{stem}_raw.jpg",
                 session_dir / f"{stem}_raw.jpg"):
        if cand.exists():
            return cand
    return None


def _shot_entries(session_dir: Path | None, review: dict) -> list[dict]:
    """Wpisy zdjec dla frontu (filmstrip sesji)."""
    return [
        {
            "file": f,
            "status": "rejected" if f in review["rejected"] else "ok",
            "uploaded": f in review["uploaded"],
        }
        for f in (_finals(session_dir) if session_dir else [])
    ]


class _Handler(BaseHTTPRequestHandler):
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
            self._json(self.ui.state())
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
        """MJPEG live view: ostatnia klatka z watku camera, w tempie preview_fps."""
        self.send_response(200)
        self.send_header(
            "Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.end_headers()
        try:
            while not self.ui._stop.is_set():
                frame = self.ui.latest_frame()
                if frame is not None:
                    self.wfile.write(b"--frame\r\nContent-Type: image/jpeg\r\n")
                    self.wfile.write(f"Content-Length: {len(frame)}\r\n\r\n".encode())
                    self.wfile.write(frame)
                    self.wfile.write(b"\r\n")
                time.sleep(1.0 / max(1, self.ui.preview_fps))
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def _serve_img(self, q: dict):
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


class WebUI:
    def __init__(
        self,
        logo: Path,
        base_output: Path,
        upload: bool,
        add_logo: bool,
        logo_position: str,
        auto_center: bool,
        auto_zoom: bool,
        name: str | None = None,
        port: int = 0,
    ):
        self.port = port  # 0 = efemeryczny, przydzielony przy bind
        self.token = secrets.token_urlsafe(16)
        self._server: ThreadingHTTPServer | None = None
        self._camera_thread: threading.Thread | None = None
        self._worker_thread: threading.Thread | None = None
        self.lock = threading.RLock()

        self.name: str | None = sanitize_name(name) if name else None
        self.base_output = base_output
        self.logo_path = logo

        # postprocessing (sekcja "Postprocessing" w sidebarze)
        self.add_logo = add_logo
        self.logo_position = logo_position
        self.auto_zoom = auto_zoom
        self.auto_center = auto_center
        self.clean_bg = True
        self.upload_enabled = upload and bool(AUTOMAT_API_TOKEN)

        # Ustawienia (zakladka)
        self.name_pattern = DEFAULT_NAME_PATTERN
        self.automat_url = AUTOMAT_BASE_URL
        self.automat_token = AUTOMAT_API_TOKEN or ""
        self.preview_fps = 20
        self.keep_raw = True
        self.test_result = ""

        # runtime
        self.connected = False
        self.preview_on = True
        self.busy = ""
        self.fps = 0.0
        self.bg_range: tuple[int, int] | None = None
        self.processing_file: str | None = None
        self.syncing: list[str] = []  # nazwy zdjec pobieranych wlasnie z Automatu (skeletony w filmstripie)
        self.automat_sessions: list[dict] = []
        self.automat_sessions_error = ""
        self.attach_to: dict | None = None  # {"id", "name"} — podłączenie do istniejącej sesji Automatu
        self.log: deque[dict] = deque(maxlen=500)
        self.uploader: AutomatUploader | None = None  # tylko watek worker

        self.session = make_camera_session()
        self._stop = threading.Event()
        self._frame_lock = threading.Lock()
        self._frame: bytes | None = None
        self._cam_q: queue.Queue[tuple] = queue.Queue()
        self._jobs: queue.Queue = queue.Queue()

    # ---------- log ----------

    def _log(self, text: str, kind: str = "info") -> None:
        with self.lock:
            self.log.append({"t": _now(), "kind": kind, "text": text})

    # ---------- sciezki / sesja ----------

    @property
    def session_dir(self) -> Path | None:
        return (self.base_output / self.name) if self.name else None

    def _resolve_filename(self) -> str:
        now = datetime.now()
        name = self.name_pattern.replace("{data}", now.strftime("%Y%m%d"))
        name = name.replace("{godzina}", now.strftime("%H%M%S"))
        if not name.endswith(".jpg"):
            name += ".jpg"
        return name

    # ---------- watek aparatu ----------

    def _camera_loop(self) -> None:
        """Petla zewnetrzna: laczy sie (retry co 5 s — np. gdy inna aplikacja
        trzyma aparat), po utracie polaczenia wraca do laczenia."""
        first_fail = True
        while not self._stop.is_set():
            try:
                self.session.open()
            except Exception as e:
                if first_fail:
                    self._log(f"✗ {e}", "err")
                    self._log("Ponawiam łączenie z aparatem co 5 s…", "warn")
                    first_fail = False
                if self._stop.wait(5.0):
                    return
                continue
            first_fail = True
            self._run_connected()
            self.session.close()
            with self.lock:
                self.connected = False
                self.fps = 0.0
            if self._stop.wait(2.0):
                return

    def _run_connected(self) -> None:
        with self.lock:
            self.connected = True
        self._log("Aparat połączony — live view aktywny.", "ok")
        frames = 0
        fps_frames = 0
        fps_t0 = time.monotonic()
        last_frame_t = 0.0
        try:
            while not self._stop.is_set():
                try:
                    cmd = self._cam_q.get_nowait()
                except queue.Empty:
                    cmd = None
                if cmd is not None:
                    self._handle_cam_cmd(cmd)
                    continue
                if not self.preview_on:
                    time.sleep(0.1)
                    continue
                min_dt = 1.0 / max(1, self.preview_fps)
                wait = min_dt - (time.monotonic() - last_frame_t)
                if wait > 0:
                    time.sleep(min(wait, 0.05))
                    continue
                try:
                    data = self.session.preview_frame()
                except CAMERA_ERRORS as e:
                    self._log(f"✗ Podgląd przerwany: {e}", "err")
                    with self.lock:
                        self.connected = False
                    return
                last_frame_t = time.monotonic()
                with self._frame_lock:
                    self._frame = data
                frames += 1
                fps_frames += 1
                now = time.monotonic()
                if now - fps_t0 >= 1.0:
                    with self.lock:
                        self.fps = fps_frames / (now - fps_t0)
                    fps_frames = 0
                    fps_t0 = now
                if frames % 40 == 1:
                    self._update_bg_stats(data)
        finally:
            self.session.close()

    def _handle_cam_cmd(self, cmd: tuple) -> None:
        kind, *rest = cmd
        if kind == "shoot":
            self._do_capture(rest[0])

    def _update_bg_stats(self, jpeg: bytes) -> None:
        try:
            img = Image.open(io.BytesIO(jpeg)).convert("L")
            img.thumbnail((160, 160))
            arr = np.asarray(img)
            b = max(2, arr.shape[0] // 20)
            border = np.concatenate([
                arr[:b].ravel(), arr[-b:].ravel(),
                arr[:, :b].ravel(), arr[:, -b:].ravel(),
            ])
            with self.lock:
                self.bg_range = (int(np.percentile(border, 10)),
                                 int(np.percentile(border, 90)))
        except Exception:
            pass

    def _do_capture(self, opts: dict) -> None:
        with self.lock:
            self.busy = "Wyzwalam migawkę…"
        tmpdir = Path(tempfile.mkdtemp(prefix="capture_"))
        try:
            captured = self.session.capture_to(tmpdir)
        except (SystemExit, *CAMERA_ERRORS) as e:
            self._log(f"✗ Błąd aparatu: {e}", "err")
            shutil.rmtree(tmpdir, ignore_errors=True)
            with self.lock:
                self.busy = ""
            return
        with self.lock:
            self.busy = ""
        self._jobs.put(("photo", {**opts, "tmpdir": tmpdir, "captured": captured}))

    # ---------- watek worker ----------

    def _worker_loop(self) -> None:
        while True:
            item = self._jobs.get()
            if item is None:
                return
            kind, *args = item
            try:
                self._JOBS[kind](self, *args)
            except Exception as e:
                self._log(f"✗ {kind}: {e}", "err")

    def _make_uploader(self) -> AutomatUploader:
        return AutomatUploader(base_url=self.automat_url,
                               token=self.automat_token or None)

    def _job_open_session(self, name: str) -> None:
        self.uploader = None
        with self.lock:
            attach = self.attach_to if self.attach_to and self.attach_to["name"] == name else None
            info = next((s for s in self.automat_sessions
                         if attach and s.get("id") == attach["id"]), {})
        try:
            u = self._make_uploader()
            if attach:
                u.attach_session(attach["id"], name,
                                 product_found=bool(info.get("product")),
                                 photos_count=int(info.get("photos_count", 0)))
            else:
                u.open_session(name)
        except Exception as e:
            self._log(f"✗ Nie udało się otworzyć sesji w Automacie: {e}", "err")
            return
        self._log(*describe_opened_session(u, name))
        self.uploader = u
        self._jobs.put(("sync_session", name))

    def _job_upload_off(self) -> None:
        self.uploader = None

    def _job_sync_session(self, name: str) -> None:
        """Sciaga z Automatu zdjecia sesji, ktorych nie ma lokalnie — operator
        wszedl w sesje na maszynie, ktora jej nie strzelala (inny komputer,
        wyczyszczone photos/). Raw nigdy nie szedl po sieci, wiec wraca sam
        finalny JPEG; nie odtwarzamy podkatalogu raw/."""
        u = self.uploader
        if u is None or u.session_id is None:
            return
        try:
            photos = u.session_photos()
        except Exception as e:
            self._log(f"✗ Lista zdjęć sesji z Automatu: {e}", "err")
            return
        outdir = self.base_output / name
        have = set(_finals(outdir))
        missing = []
        for p in photos:
            # `processed`/`filename` doklada dopiero nowszy Automat — na starszym
            # instancie jedziemy po samym statusie, plik i tak sprawdzi endpoint
            if p.get("status") != "processed" or p.get("processed") is False:
                continue
            # nazwa jest zdalna — bierzemy sam basename, zeby nie wyjsc
            # z katalogu sesji; brak nazwy = nazywamy po id
            fname = Path(str(p.get("filename") or "").strip()).name
            if not fname.lower().endswith(".jpg") or fname.startswith("."):
                fname = f"photo_{p['id']}.jpg"
            if fname.endswith("_raw.jpg") or fname in have:
                continue
            have.add(fname)
            missing.append((int(p["id"]), fname))
        if not missing:
            return
        self._log(f"↓ Pobieram {len(missing)} zdjęć sesji z Automatu…")
        outdir.mkdir(parents=True, exist_ok=True)
        review = _load_review(outdir)
        ok = 0
        with self.lock:
            self.syncing = [f for _, f in missing]
        try:
            for pid, fname in missing:
                try:
                    u.download_photo(pid, outdir / fname)
                except Exception as e:
                    self._log(f"✗ Pobranie {fname} z Automatu nie wyszło: {e}", "err")
                    continue
                finally:
                    # skeleton znika razem z proba, nie dopiero z sukcesem —
                    # inaczej po bledzie wisialby do konca sesji
                    with self.lock:
                        if fname in self.syncing:
                            self.syncing.remove(fname)
                review["automat"][fname] = pid
                if fname not in review["uploaded"]:
                    review["uploaded"].append(fname)
                ok += 1
        finally:
            with self.lock:
                self.syncing = []
        _save_review(outdir, review)
        if ok:
            self._log(f"↓ Pobrano {ok} zdjęć z Automatu do {name}.", "ok")

    def _job_photo(self, job: dict) -> None:
        filename = job["filename"]
        outdir: Path = job["outdir"]
        with self.lock:
            self.processing_file = filename
            self.busy = "Czyszczę tło / centruję…"
        announced_id = None
        if job["upload"] and self.uploader is not None:
            try:
                announced_id = self.uploader.announce_photo(filename)
            except Exception as e:
                self._log(f"✗ Announce do Automatu nie wyszedł: {e}", "err")
        try:
            out = process(
                job["captured"], self.logo_path, outdir,
                clean_bg=job["clean_bg"], add_logo=job["add_logo"],
                logo_position=job["logo_position"],
                auto_center=job["auto_center"], auto_zoom=job["auto_zoom"],
                out_name=filename,
            )
        except Exception as e:
            self._log(f"✗ Obróbka nie wyszła: {e}", "err")
            return
        finally:
            shutil.rmtree(job["tmpdir"], ignore_errors=True)
            with self.lock:
                self.busy = ""
                self.processing_file = None

        raw = outdir / f"{Path(filename).stem}_raw.jpg"
        if raw.exists():
            if self.keep_raw:
                (outdir / "raw").mkdir(exist_ok=True)
                raw.replace(outdir / "raw" / raw.name)
            else:
                raw.unlink()

        review = _load_review(outdir)
        bits = []
        if job["add_logo"]:
            bits.append("logo")
        if job["auto_zoom"]:
            bits.append("zoom")
        bits.append(f"{OUTPUT_SIZE}×{OUTPUT_SIZE}")
        review["meta"][out.name] = " · ".join(bits)
        n = len([f for f in _finals(outdir) if f not in review["rejected"]])
        uploaded_note = ""
        if announced_id:
            # nawet gdy upload nizej padnie, placeholder w Automacie istnieje —
            # delete musi go umiec sprzatnac
            review["automat"][out.name] = announced_id
        if job["upload"] and self.uploader is not None:
            try:
                resp = self.uploader.upload_processed(out, photo_id=announced_id)
                review["uploaded"].append(out.name)
                pid = resp.get("id") or announced_id
                if pid:
                    review["automat"][out.name] = int(pid)
                uploaded_note = " · upload do Automatu OK"
            except Exception as e:
                self._log(f"✗ Upload do Automatu nie wyszedł: {e}", "err")
        _save_review(outdir, review)
        self._log(f"Zapisano {out.name} (#{n}){uploaded_note}", "ok")

    def _job_delete(self, session: str, files: list[str]) -> None:
        outdir = self.base_output / session
        review = _load_review(outdir)
        automat_ids = []
        for f in files:
            (outdir / f).unlink(missing_ok=True)
            (outdir / ".thumbs" / f).unlink(missing_ok=True)
            raw = _find_raw(outdir, f)
            if raw is not None:
                raw.unlink(missing_ok=True)
            for key in ("rejected", "uploaded"):
                if f in review[key]:
                    review[key].remove(f)
            review["meta"].pop(f, None)
            pid = review["automat"].pop(f, None)
            if pid:
                automat_ids.append((f, int(pid)))
        _save_review(outdir, review)
        self._log(f"Usunięto {len(files)} plik(ów) z {session}.", "warn")
        if not automat_ids:
            return
        if self.uploader is None:
            self._job_open_session(session)
        if self.uploader is None:
            self._log("✗ Nie usunięto zdjęć z Automatu (brak połączenia).", "err")
            return
        for f, pid in automat_ids:
            try:
                self.uploader.delete_photo(pid)
                self._log(f"Usunięto {f} także z Automatu.", "warn")
            except Exception as e:
                self._log(f"✗ Usuwanie {f} z Automatu nie wyszło: {e}", "err")

    def _job_list_sessions(self) -> None:
        try:
            sessions = self._make_uploader().list_sessions()
        except Exception as e:
            with self.lock:
                self.automat_sessions_error = str(e)
            self._log(f"✗ Lista sesji z Automatu: {e}", "err")
            return
        with self.lock:
            self.automat_sessions = sessions
            self.automat_sessions_error = ""

    def _job_test(self) -> None:
        import requests

        t0 = time.monotonic()
        try:
            r = requests.get(self.automat_url, timeout=5)
            ms = int((time.monotonic() - t0) * 1000)
            self.test_result = f"✓ {r.status_code} {r.reason} · {ms} ms"
            self._log(f"Test Automatu: {self.test_result}", "ok")
        except Exception as e:
            self.test_result = f"✗ {e.__class__.__name__}"
            self._log(f"Test Automatu nie wyszedł: {e}", "err")

    _JOBS = {
        "photo": _job_photo,
        "open_session": _job_open_session,
        "upload_off": _job_upload_off,
        "sync_session": _job_sync_session,
        "list_sessions": _job_list_sessions,
        "delete": _job_delete,
        "test": _job_test,
    }

    # ---------- akcje z frontu ----------

    def action(self, data: dict) -> dict:
        """Dispatcher /api/action. Metoda _act_* zwraca dict bledu albo None (= ok)."""
        act = data.get("action", "")
        handler = self._ACTIONS.get(act)
        if handler is None:
            return {"ok": False, "error": f"nieznana akcja {act!r}"}
        return handler(self, data) or {"ok": True}

    def _act_set_session(self, data: dict) -> dict | None:
        name = sanitize_name(str(data.get("name", "")))
        if not name or name == "default":
            return {"ok": False, "error": "pusta nazwa"}
        sid = data.get("session_id")
        with self.lock:
            self.name = name
            self.attach_to = {"id": int(sid), "name": name} if sid else None
        self._log(f"Sesja: {name} → {self.base_output / name}")
        if self.upload_enabled:
            self._jobs.put(("open_session", name))
            self._jobs.put(("list_sessions",))
        return None

    def _act_clear_session(self, data: dict) -> None:
        with self.lock:
            self.name = None
            self.attach_to = None
        self._jobs.put(("upload_off",))
        if self.automat_token:
            self._jobs.put(("list_sessions",))

    def _act_refresh_sessions(self, data: dict) -> None:
        if self.automat_token:
            self._jobs.put(("list_sessions",))

    def _act_shoot(self, data: dict) -> dict | None:
        if not self.connected:
            return {"ok": False, "error": "aparat nie jest połączony"}
        if not self.name:
            return {"ok": False, "error": "najpierw ustaw nazwę sesji"}
        with self.lock:
            opts = dict(
                outdir=self.session_dir, filename=self._resolve_filename(),
                clean_bg=self.clean_bg, add_logo=self.add_logo,
                logo_position=self.logo_position,
                auto_center=self.auto_center, auto_zoom=self.auto_zoom,
                upload=self.upload_enabled,
            )
        self._cam_q.put(("shoot", opts))
        return None

    _TOGGLE_ATTRS = {
        "preview": "preview_on",
        "logo": "add_logo",
        "zoom": "auto_zoom",
        "center": "auto_center",
        "cleanbg": "clean_bg",
    }

    def _act_toggle(self, data: dict) -> None:
        key, val = data["key"], bool(data["value"])
        with self.lock:
            if key in self._TOGGLE_ATTRS:
                setattr(self, self._TOGGLE_ATTRS[key], val)

    def _act_set_post(self, data: dict) -> None:
        key, val = data["key"], data["value"]
        with self.lock:
            if key == "logo_position" and val in LOGO_POSITIONS:
                self.logo_position = val

    def _act_review(self, data: dict) -> None:
        self._review_mark(data["session"], data["file"], data["verdict"])

    def _act_reject_last(self, data: dict) -> None:
        if self.session_dir:
            review = _load_review(self.session_dir)
            fresh = [f for f in _finals(self.session_dir) if f not in review["rejected"]]
            if fresh:
                self._review_mark(self.name, fresh[-1], "rejected")

    def _act_delete(self, data: dict) -> None:
        self._jobs.put(("delete", data["session"], list(data["files"])))

    def _act_test_connection(self, data: dict) -> None:
        self._jobs.put(("test",))

    def _act_set_app(self, data: dict) -> None:
        self._set_app_setting(data["key"], data["value"])

    _ACTIONS = {
        "set_session": _act_set_session,
        "clear_session": _act_clear_session,
        "refresh_sessions": _act_refresh_sessions,
        "shoot": _act_shoot,
        "toggle": _act_toggle,
        "set_post": _act_set_post,
        "review": _act_review,
        "reject_last": _act_reject_last,
        "delete": _act_delete,
        "test_connection": _act_test_connection,
        "set_app": _act_set_app,
    }

    def _review_mark(self, session: str, filename: str, verdict: str) -> None:
        outdir = self.base_output / session
        review = _load_review(outdir)
        was_rejected = filename in review["rejected"]
        if verdict == "rejected":
            if not was_rejected:
                review["rejected"].append(filename)
                self._log(f"Zdjęcie {filename} odrzucone.", "warn")
        else:
            if was_rejected:
                review["rejected"].remove(filename)
                self._log(f"Zdjęcie {filename} zaakceptowane.", "ok")
        _save_review(outdir, review)

    def _set_app_setting(self, key: str, value) -> None:
        with self.lock:
            if key == "photos_dir":
                self.base_output = Path(str(value)).expanduser()
            elif key == "logo_path":
                self.logo_path = Path(str(value)).expanduser()
            elif key == "name_pattern":
                self.name_pattern = str(value) or DEFAULT_NAME_PATTERN
            elif key == "automat_url":
                self.automat_url = str(value).rstrip("/")
                self.uploader = None
                _persist_env("AUTOMAT_URL", self.automat_url)
                self._log("Adres Automatu zapisany w .env", "ok")
            elif key == "automat_token":
                if not str(value).startswith("•"):
                    self.automat_token = str(value)
                    self.uploader = None
                    self.upload_enabled = bool(self.automat_token)
                    _persist_env("AUTOMAT_TOKEN", self.automat_token)
                    self._log("Token Automatu zapisany w .env", "ok")
                    if self.upload_enabled and self.name:
                        self._jobs.put(("open_session", self.name))
            elif key == "preview_fps":
                self.preview_fps = max(1, min(30, int(value)))
            elif key == "keep_raw":
                self.keep_raw = bool(value)

    # ---------- stan dla frontu ----------

    def state(self) -> dict:
        with self.lock:
            sdir = self.session_dir
            review = _load_review(sdir) if sdir else {
                "rejected": [], "uploaded": [], "meta": {}, "automat": {}}
            shots = _shot_entries(sdir, review)
            bg = self.bg_range
            return {
                "connected": self.connected,
                "fps": round(self.fps),
                "previewOn": self.preview_on,
                "busy": self.busy,
                "processing": self.processing_file,
                "downloading": list(self.syncing),
                "session": {
                    "name": self.name or "",
                    "dir": str(sdir) if sdir else "",
                    "count": len([s for s in shots if s["status"] != "rejected"]),
                    "rejected": len([s for s in shots if s["status"] == "rejected"]),
                },
                "shots": shots,
                "camera": {
                    "bg": f"{bg[0]}–{bg[1]}" if bg else "—",
                    "bgOk": bool(bg and bg[0] >= 230 and bg[1] <= 254),
                },
                "post": {
                    "logo": self.add_logo,
                    "logoPosition": self.logo_position,
                    "logoPositions": list(LOGO_POSITIONS),
                    "zoom": self.auto_zoom,
                    "center": self.auto_center,
                    "cleanBg": self.clean_bg,
                },
                "automat": {
                    "sessions": self.automat_sessions,
                    "error": self.automat_sessions_error,
                    "hasToken": bool(self.automat_token),
                },
                "settings": {
                    "photosDir": str(self.base_output),
                    "logoPath": str(self.logo_path),
                    "namePattern": self.name_pattern,
                    "automatUrl": self.automat_url,
                    "tokenMasked": ("•" * 12 + self.automat_token[-4:]) if self.automat_token else "",
                    "previewFps": self.preview_fps,
                    "keepRaw": self.keep_raw,
                    "testResult": self.test_result,
                },
                "log": list(self.log),
            }

    # ---------- pliki ----------

    def latest_frame(self) -> bytes | None:
        with self._frame_lock:
            return self._frame

    def image_bytes(self, session: str, filename: str, thumb: bool) -> bytes | None:
        base = self.base_output.resolve()
        path = (base / sanitize_name(session) / Path(filename).name).resolve()
        if not str(path).startswith(str(base)) or not path.exists():
            return None
        if not thumb:
            return path.read_bytes()
        tdir = path.parent / ".thumbs"
        tpath = tdir / path.name
        if not tpath.exists() or tpath.stat().st_mtime < path.stat().st_mtime:
            tdir.mkdir(exist_ok=True)
            img = Image.open(path)
            img.thumbnail((THUMB_SIZE, THUMB_SIZE))
            img.save(tpath, "JPEG", quality=80)
        return tpath.read_bytes()

    # ---------- start ----------

    def start(self) -> str:
        """Startuje watki + serwer na efemerycznym porcie 127.0.0.1.
        Zwraca URL z jednorazowym tokenem — bez niego serwer odpowiada 403,
        wiec UI jest dostepne tylko dla okna aplikacji (nie da sie wejsc
        "z boku" przegladarka na goly adres)."""
        self._camera_thread = threading.Thread(target=self._camera_loop, daemon=True)
        self._worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self._camera_thread.start()
        self._worker_thread.start()
        if self.automat_token:
            self._jobs.put(("list_sessions",))

        handler = type("Handler", (_Handler,), {"ui": self})
        self._server = ThreadingHTTPServer(("127.0.0.1", self.port), handler)
        self.port = self._server.server_address[1]
        threading.Thread(target=self._server.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{self.port}/?t={self.token}"

    def stop(self) -> None:
        """Uporzadkowane zamkniecie: NAJPIERW czekamy az watek aparatu wyjdzie
        z petli i zamknie sesje gphoto2 (porzucona otwarta sesja PTP to
        zawieszki libusb przy wyjsciu procesu + BUSY przy nastepnym starcie),
        dopiero potem ubijamy serwer."""
        if self._stop.is_set():
            return
        self._stop.set()
        self._jobs.put(None)
        if self._camera_thread is not None:
            self._camera_thread.join(timeout=4.0)
        if self._worker_thread is not None:
            self._worker_thread.join(timeout=3.0)
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()

    def run(self) -> str:
        """Tryb --browser: start + blokuj do Ctrl-C."""
        url = self.start()
        print(f"Camera Capture: {url}")
        try:
            threading.Event().wait()
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()
        return url
