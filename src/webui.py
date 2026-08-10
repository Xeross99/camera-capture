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
import os
import queue
import secrets
import shutil
import tempfile
import threading
import time
from collections import deque
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np
from PIL import Image

from .automat_uploader import (AutomatNotFound, AutomatUploader,
                               describe_opened_session)
from .camera import CAMERA_ERRORS, make_camera_session
from .config import (
    AUTOMAT_API_TOKEN,
    AUTOMAT_BASE_URL,
    OUTPUT_SIZE,
    PROJECT_DIR,
    TRASH_RETENTION_DAYS,
)
from .image_processing import LOGO_POSITIONS, process
from .naming import sanitize_name
from .version import APP_VERSION

STATIC_DIR = Path(__file__).parent / "webui_static"
STATIC_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".woff2": "font/woff2",
}
THUMB_SIZE = 360
DEFAULT_NAME_PATTERN = "photo_{data}_{godzina}.jpg"
TRASH_DIR = ".trash"        # photos/.trash/<data>-<godzina>_<sesja>/
TRASH_STAMP = "%Y%m%d-%H%M%S"
COVERS_DIR = ".covers"      # photos/.covers/<id sesji>.jpg — okladki ekranu startowego
COVER_SIZE = 420


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


def _trash_batch(base_output: Path, session: str) -> Path:
    """Nowy katalog w koszu: `photos/.trash/<data>-<godzina>_<sesja>`.

    Data siedzi w NAZWIE, nie w mtime — mtime katalogu potrafi się zmienić
    (kopiowanie/synchronizacja `photos/`) i kosz czyściłby się losowo."""
    root = base_output / TRASH_DIR
    stamp = datetime.now().strftime(TRASH_STAMP)
    for n in range(1000):
        cand = root / (f"{stamp}_{session}" + (f"-{n}" if n else ""))
        if not cand.exists():
            cand.mkdir(parents=True)
            return cand
    raise RuntimeError("kosz: nie mogę założyć katalogu na usunięte pliki")


def _move_into(batch: Path, path: Path) -> None:
    target = batch / path.name
    n = 1
    while target.exists():
        target = batch / f"{path.stem}-{n}{path.suffix}"
        n += 1
    shutil.move(str(path), str(target))


def _purge_trash(base_output: Path, days: int = TRASH_RETENTION_DAYS) -> int:
    """Kasuje NAPRAWDĘ wpisy kosza starsze niż `days` dni. Zwraca ile poszło."""
    root = base_output / TRASH_DIR
    if days <= 0 or not root.is_dir():
        return 0
    cutoff = datetime.now() - timedelta(days=days)
    removed = 0
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        try:
            when = datetime.strptime(entry.name.split("_", 1)[0], TRASH_STAMP)
        except ValueError:
            when = datetime.fromtimestamp(entry.stat().st_mtime)
        if when < cutoff:
            shutil.rmtree(entry, ignore_errors=True)
            removed += 1
    return removed


def _cover_path(base_output: Path, session_id: int) -> Path:
    return base_output / COVERS_DIR / f"{int(session_id)}.jpg"


def _make_cover(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    img = Image.open(src)
    img.thumbnail((COVER_SIZE, COVER_SIZE))
    img.convert("RGB").save(dest, "JPEG", quality=82)


def _trash_note() -> str:
    return (f"→ kosz (usuwany po {TRASH_RETENTION_DAYS} dniach)"
            if TRASH_RETENTION_DAYS > 0 else "— usunięte")


def _photos_word(n: int) -> str:
    """zdjecie / zdjecia / zdjec — polska odmiana licznika w komunikatach logu."""
    if n == 1:
        return "zdjęcie"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return "zdjęcia"
    return "zdjęć"


def _remote_filename(photo: dict) -> str:
    """Nazwa pliku dla zdjecia z Automatu — sam basename (zdalna nazwa nie moze
    uciec z katalogu sesji), a przy jej braku `photo_<id>.jpg`."""
    fname = Path(str(photo.get("filename") or "").strip()).name
    if not fname.lower().endswith(".jpg") or fname.startswith("."):
        fname = f"photo_{photo['id']}.jpg"
    return fname


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


def _ev_number(value) -> float | None:
    """Kompensacja ekspozycji na liczbe — odpowiednik `evNumber()` z app.js.

    Zapisy roznia sie miedzy backendami, a nawet w obrebie jednego aparatu
    ("+2 2/3" na liscie kroków, "+3.0" w odczycie biezacej wartosci), wiec
    porownanie tekstem daloby falszywy alarm "aparat nie przyjal"."""
    text = str(value or "").strip().replace("−", "-").lstrip("+")
    if not text:
        return None
    sign = 1
    if text.startswith("-"):
        sign, text = -1, text[1:].strip()
    total = 0.0
    seen = False
    for part in text.split():
        try:
            if "/" in part:
                num, _, den = part.partition("/")
                total += int(num) / int(den)
            else:
                total += float(part)
            seen = True
        except (ValueError, ZeroDivisionError):
            return None
    return sign * total if seen else None


BG_MIN = 230


def _bg_status(bg: tuple[int, int] | None) -> str:
    """Werdykt o jasnosci tla dla UI: `ok` / `dark` / `unknown`.

    Za ciemne tlo psuje wynik naprawde: `clean_background` liczy prog i alfe
    wzgledem `bg_lum`, wiec przy szarawym stole maska lapie cien jak produkt,
    a po wyrownaniu zostaje brudny nalot.

    Gornego progu NIE MA, choc kiedys stalo tu 254 — tlo wypalone do 255 nie
    szkodzi. Pipeline i tak dociaga je do czystej bieli, a wszystkie progi w
    `background.py` (`gate`, falloff alfy) sa liczone jako ulamek `bg_lum`,
    wiec przesuwaja sie razem z nim. Ryzykiem jest dopiero przeswietlony
    PRODUKT, a tego pomiar z paskow brzegowych klatki nie widzi — badge
    marudzil wiec na 255 przy zdjeciach, z ktorymi nie bylo nic nie tak."""
    if bg is None:
        return "unknown"
    return "dark" if bg[0] < BG_MIN else "ok"


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
        self.preview_fps = 30
        self.keep_raw = True
        self.test_result = ""

        # runtime
        self.connected = False
        self.preview_on = True
        self.busy = ""
        self.fps = 0.0
        self.bg_range: tuple[int, int] | None = None
        # {"current", "choices"} albo None, gdy aparat nie oddaje kompensacji
        # (tryb bez niej, backend jej nie umie, aparat rozłączony)
        self.ev: dict | None = None
        self._ev_t0 = 0.0
        self._ev_logged = False   # wpis diagnostyczny raz na połączenie
        self.processing_file: str | None = None
        self.syncing: list[str] = []  # nazwy zdjec pobieranych wlasnie z Automatu (skeletony w filmstripie)
        self.automat_sessions: list[dict] = []
        self.automat_sessions_error = ""
        self.attach_to: dict | None = None  # {"id", "name"} — podłączenie do istniejącej sesji Automatu
        # aktualizacje (GitHub Releases — patrz src/updater.py)
        self.update_info: dict | None = None   # {"version", "url", "notes", "page", "size"}
        self.update_status = ""                # tekst dla UI (zakładka Ustawienia)
        self.update_checking = False           # trwa odpytanie GitHuba (spinner w UI)
        self.update_busy = False
        self.update_progress = 0
        self.log: deque[dict] = deque(maxlen=500)
        self.uploader: AutomatUploader | None = None  # tylko watek worker

        self.session = make_camera_session()
        # Backend, ktory potrafi opowiadac o dlugim strzale (EDSDK czeka, az
        # aparat odda plik), dostaje kanal do paska stanu. Bez tego przycisk
        # stoi na „Wyzwalam migawkę…" i wyglada na zawieszony, choc trwa
        # normalne czekanie na aparat.
        if hasattr(self.session, "on_status"):
            self.session.on_status = self._set_busy
        if hasattr(self.session, "on_log"):
            self.session.on_log = self._log
        self._stop = threading.Event()
        self._frame_lock = threading.Lock()
        self._frame: bytes | None = None
        self._cam_q: queue.Queue[tuple] = queue.Queue()
        self._jobs: queue.Queue = queue.Queue()

    # ---------- log ----------

    def _log(self, text: str, kind: str = "info") -> None:
        with self.lock:
            last = self.log[-1] if self.log else None
            # powtorka pod rzad (petla reconnectu aparatu!) nie zalewa logu —
            # rosnie licznik przy istniejacym wpisie, front dokleja "×N"
            if last is not None and last["text"] == text and last["kind"] == kind:
                last["n"] += 1
                last["t"] = _now()
                return
            self.log.append({"t": _now(), "kind": kind, "text": text, "n": 1})

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

    RECONNECT_MIN = 2.0
    RECONNECT_MAX = 30.0
    _HEALTHY_AFTER = 5.0   # tyle sekund live view = polaczenie "zdrowe"
    _EV_POLL_S = 2.0       # co tyle odpytujemy aparat o kompensacje ekspozycji

    def _camera_loop(self) -> None:
        """Petla zewnetrzna: laczy sie (retry co 5 s — np. gdy inna aplikacja
        trzyma aparat), po utracie polaczenia wraca do laczenia.

        Polaczenie, ktore pada natychmiast (urzadzenie PTP bez live view,
        aparat w trybie odtwarzania), nie moze byc ponawiane co 2 s — kazda
        proba przechodzi przez init + `_configure_camera`, wiec terminal i log
        zalewaly setki identycznych linii. Przerwa rosnie 2 → 30 s i wraca do
        2 s dopiero po polaczeniu, ktore pozylo dluzej niz `_HEALTHY_AFTER`."""
        first_fail = True
        backoff = self.RECONNECT_MIN
        flapping = False   # polaczenie pada od razu — cykl leci po cichu
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
            started = time.monotonic()
            self._run_connected(quiet=flapping)
            self.session.close()
            self._drop_preview()
            if time.monotonic() - started >= self._HEALTHY_AFTER:
                backoff = self.RECONNECT_MIN
                flapping = False
            else:
                if not flapping:
                    flapping = True
                    self._log(
                        "Aparat rozłącza się zaraz po połączeniu — ponawiam "
                        f"coraz rzadziej (do {int(self.RECONNECT_MAX)} s), po cichu. "
                        "Sprawdź tryb aparatu (M/Av/Tv/P), kabel i czy nie trzyma "
                        "go inna aplikacja.", "warn")
                backoff = min(self.RECONNECT_MAX, backoff * 2)
            if self._stop.wait(backoff):
                return

    def _drop_preview(self) -> None:
        """Aparat odpadł — kasujemy WSZYSTKO, co pochodzi z live view.

        Bez tego ostatnia klatka wisiała w buforze: `/stream` podawał ją
        każdemu nowemu odbiorcy, a statystyki tła pokazywały nieaktualne
        wartości. Efekt był mylący — status mówił „rozłączony", a obraz
        wyglądał, jakby aparat dalej pracował."""
        with self.lock:
            self.connected = False
            self.fps = 0.0
            self.bg_range = None
            self.ev = None
        self._ev_logged = False   # po ponownym połączeniu warto wypisać raz jeszcze
        with self._frame_lock:
            self._frame = None

    def _run_connected(self, quiet: bool = False) -> None:
        """`quiet` = jesteśmy w pętli reconnectu z padającym live view: nie
        zaśmiecamy logu parą „połączony"/„podgląd przerwany" co cykl. Wpis
        „połączony" pojawi się dopiero, gdy klatki polecą dłużej niż
        `_HEALTHY_AFTER` — czyli gdy połączenie naprawdę wstało."""
        with self.lock:
            self.connected = True
        announced = not quiet
        if announced:
            self._log("Aparat połączony — live view aktywny.", "ok")
        started = time.monotonic()
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
                # przed gałęzią podglądu, żeby kompensacja odświeżała się także
                # przy wyłączonym live view (operator wciąż kręci pokrętłem)
                if time.monotonic() - self._ev_t0 >= self._EV_POLL_S:
                    self._ev_t0 = time.monotonic()
                    self._refresh_ev()
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
                    if not quiet:
                        self._log(f"✗ Podgląd przerwany: {e}", "err")
                    self._drop_preview()
                    return
                last_frame_t = time.monotonic()
                if not announced and last_frame_t - started >= self._HEALTHY_AFTER:
                    announced = True
                    self._log("Aparat połączony — live view aktywny.", "ok")
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
        elif kind == "set_ev":
            self._do_set_ev(rest[0])

    # Kompensacja ekspozycji. Wszystko leci wątkiem camera — aparat ma JEDNEGO
    # właściciela (gphoto2 nie jest thread-safe, EDSDK wymaga tego samego wątku
    # co reszta wywołań).
    def _refresh_ev(self) -> None:
        """Odpytanie aparatu o bieżącą kompensację. Operator kręci też pokrętłem
        na aparacie, więc UI musi za tym nadążać, a nie tylko pamiętać, co samo
        ustawiło."""
        try:
            ev = self.session.get_settings().get("exposurecompensation")
        except Exception:
            ev = None
        # Raz na połączenie wypisujemy, co aparat NAPRAWDĘ oddaje. Backendy mówią
        # różnymi zapisami ("+2 2/3", "+3.0", "0.3") i bez tego wpisu każdy błąd
        # kroku trzeba było zgadywać ze zrzutu ekranu.
        if ev and not self._ev_logged:
            self._ev_logged = True
            choices = ev.get("choices") or []
            self._log(f"Kompensacja ekspozycji: teraz {ev.get('current')!r}, "
                      f"{len(choices)} kroków ({', '.join(map(str, choices[:3]))}"
                      f"{' … ' + str(choices[-1]) if len(choices) > 3 else ''}).")
        with self.lock:
            self.ev = ev

    def _do_set_ev(self, value: str) -> None:
        reply = None
        try:
            reply = self.session.set_setting("exposurecompensation", value)
        except Exception as e:
            self._log(f"✗ Kompensacja ekspozycji: {e}", "err")
            return
        self._ev_t0 = time.monotonic()
        self._refresh_ev()   # źródłem prawdy jest aparat, nie to, co wysłaliśmy

        # Odrzucenie wartości było do tej pory CICHE: UI pokazywał nową wartość,
        # a po sekundzie wracała stara i wyglądało to na błąd aplikacji. Aparat
        # bywa jedyną stroną, która wie, czemu nie przyjął — trzeba to powiedzieć.
        now = (self.ev or {}).get("current")
        want, got = _ev_number(value), _ev_number(now)
        if want is not None and got is not None and abs(want - got) < 0.01:
            return
        detail = f" Odpowiedź sterownika: {reply}." if reply else ""
        self._log(
            f"✗ Aparat nie przyjął kompensacji {value} — zostało {now}. "
            f"Sprawdź tryb: kompensacja działa w P/Av/Tv, a w M z ręcznym ISO "
            f"aparat ją ignoruje.{detail}", "err")

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

    def _set_busy(self, text: str) -> None:
        with self.lock:
            self.busy = text

    def _do_capture(self, opts: dict) -> None:
        self._set_busy("Wyzwalam migawkę…")
        tmpdir = Path(tempfile.mkdtemp(prefix="capture_"))
        try:
            captured = self.session.capture_to(tmpdir)
        except (SystemExit, *CAMERA_ERRORS) as e:
            self._log(f"✗ Błąd aparatu: {e}", "err")
            shutil.rmtree(tmpdir, ignore_errors=True)
            self._set_busy("")
            return
        self._set_busy("")
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

    def _discard_files(self, session: str, files: list[str], review: dict) -> dict:
        """Lokalne usunięcie zdjęć — finalny JPEG i jego raw lądują w koszu
        (`photos/.trash/<data>_<sesja>/`), nie na śmietniku od razu: dopiero
        `_purge_trash()` po `TRASH_RETENTION_DAYS` kasuje je naprawdę.
        Miniatura leci od razu (to cache, odtworzy się sama). Wpisy z
        `.review.json` są czyszczone, a zdjęte mapowania na Automat wracają
        do wołającego (`_job_delete` musi jeszcze skasować rekordy zdalne).

        `TRASH_RETENTION_DAYS = 0` = stare zachowanie, kasowanie natychmiast."""
        outdir = self.base_output / session
        batch = _trash_batch(self.base_output, session) if TRASH_RETENTION_DAYS > 0 else None
        automat_ids = {}
        for f in files:
            (outdir / ".thumbs" / f).unlink(missing_ok=True)
            for p in ((outdir / f), _find_raw(outdir, f)):
                if p is None or not p.exists():
                    continue
                if batch is None:
                    p.unlink(missing_ok=True)
                else:
                    _move_into(batch, p)
            for key in ("rejected", "uploaded"):
                if f in review[key]:
                    review[key].remove(f)
            review["meta"].pop(f, None)
            pid = review["automat"].pop(f, None)
            if pid:
                automat_ids[f] = int(pid)
        return automat_ids

    def _trash_session(self, name: str) -> None:
        """Sesja zniknęła z Automatu (404 przy sync) — lokalny folder idzie do
        kosza i wracamy na ekran startowy. Bez tego operator siedziałby w sesji,
        do której nic już nie doleci."""
        outdir = self.base_output / name
        if outdir.is_dir():
            if TRASH_RETENTION_DAYS > 0:
                batch = _trash_batch(self.base_output, name)
                for item in list(outdir.iterdir()):
                    shutil.move(str(item), str(batch / item.name))
                outdir.rmdir()
            else:
                shutil.rmtree(outdir, ignore_errors=True)
            self._log(f"Sesja {name} nie istnieje już w Automacie — "
                      f"lokalny folder {_trash_note()}.", "warn")
        else:
            self._log(f"Sesja {name} nie istnieje już w Automacie.", "warn")
        with self.lock:
            if self.name == name:
                self.name = None
                self.attach_to = None
        self.uploader = None

    def _prune_local(self, session: str, remote: dict[str, int]) -> int:
        """Zdejmuje z filmstripa lokalne finalne JPEG-i, ktorych nie ma juz w
        sesji Automatu (operator odsial zdjecia w UI Automatu) — ma pokazywac
        to samo, co sesja po drugiej stronie.

        Pliki ida do kosza (`_discard_files`), wiec prune jest odwracalny przez
        TRASH_RETENTION_DAYS dni — wazne, bo leci automatycznie przy wejsciu w
        sesje: nieudany upload sprzed chwili nie kasuje jedynego oryginalu.

        Pusta lista zdalna = nie ruszamy NIC: to zwykle nowa sesja zalozona na
        dzis (Rails deduplikuje per produkt+dzien), a nie "wszystko odsiane"."""
        if not remote:
            return 0
        outdir = self.base_output / session
        stale = [f for f in _finals(outdir) if f not in remote]
        if not stale:
            return 0
        review = _load_review(outdir)
        self._discard_files(session, stale, review)
        _save_review(outdir, review)
        self._log(f"Zdjęcia nieobecne w Automacie: {len(stale)} {_trash_note()}.",
                  "warn")
        return len(stale)

    def _job_sync_session(self, name: str) -> None:
        """Dwustronne zrownanie filmstripa z sesja w Automacie — Automat jest
        zrodlem prawdy: czego nie ma lokalnie, sciagamy (operator wszedl w
        sesje na maszynie, ktora jej nie strzelala — inny komputer, wyczyszczone
        photos/), czego nie ma juz zdalnie, kasujemy lokalnie (odsial zdjecia w
        UI Automatu — pliki ida do kosza, nie od razu na zawsze). Raw nigdy nie
        szedl po sieci, wiec wraca sam finalny JPEG; nie odtwarzamy raw/."""
        u = self.uploader
        if u is None or u.session_id is None:
            return
        try:
            photos = u.session_photos()
        except AutomatNotFound:
            # calej sesji nie ma juz po drugiej stronie — folder do kosza
            self._trash_session(name)
            return
        except Exception as e:
            self._log(f"✗ Lista zdjęć sesji z Automatu: {e}", "err")
            return
        outdir = self.base_output / name
        have = set(_finals(outdir))
        remote: dict[str, int] = {}
        missing = []
        for p in photos:
            fname = _remote_filename(p)
            if fname.endswith("_raw.jpg"):
                continue
            # do prune licza sie WSZYSTKIE statusy — placeholder po announce
            # (jeszcze nieprzetworzony) tez "istnieje" po drugiej stronie
            remote[fname] = int(p["id"])
            # `processed`/`filename` doklada dopiero nowszy Automat — na starszym
            # instancie jedziemy po samym statusie, plik i tak sprawdzi endpoint
            if p.get("status") != "processed" or p.get("processed") is False:
                continue
            if fname in have:
                continue
            have.add(fname)
            missing.append((int(p["id"]), fname))
        self._prune_local(name, remote)
        if not missing:
            return
        self._log(f"↓ Pobieram {len(missing)} {_photos_word(len(missing))} "
                  "sesji z Automatu…")
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
            self._log(f"↓ Pobrano {ok} {_photos_word(ok)} z Automatu do {name}.", "ok")

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
        """Świadome kasowanie (BACKSPACE / „Odrzuć"): lokalnie do kosza
        (odwracalne przez TRASH_RETENTION_DAYS dni), w Automacie od razu —
        rekordu po drugiej stronie i tak nie umiemy przywrócić."""
        outdir = self.base_output / session
        review = _load_review(outdir)
        automat_ids = list(self._discard_files(session, files, review).items())
        _save_review(outdir, review)
        self._log(f"{len(files)} {_photos_word(len(files))} z {session} "
                  f"{_trash_note()}.", "warn")
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
        for s in sessions:
            s["cover"] = _cover_path(self.base_output, s.get("id") or 0).exists()
        with self.lock:
            self.automat_sessions = sessions
            self.automat_sessions_error = ""
        self._jobs.put(("session_covers",))

    def _local_cover_source(self, name: str) -> Path | None:
        """Najnowsze zdjecie sesji lezace juz na dysku — okladka bez sieci."""
        outdir = self.base_output / sanitize_name(name or "")
        finals = _finals(outdir)
        return (outdir / finals[-1]) if finals else None

    @staticmethod
    def _remote_cover_photo(uploader: AutomatUploader, session_id: int) -> int | None:
        """Id najnowszego przetworzonego zdjecia sesji (kandydat na okladke)."""
        for p in reversed(uploader.session_photos(session_id)):
            if p.get("status") == "processed" and p.get("processed") is not False:
                return int(p["id"])
        return None

    def _job_session_covers(self) -> None:
        """Okladki kafelkow na ekranie startowym.

        Automat nie oddaje miniatury w liscie sesji (`GET /sessions` to same
        liczniki), wiec bierzemy najnowsze zdjecie sesji: najpierw z LOKALNEGO
        folderu (zero sieci), a dopiero gdy go nie ma — `GET /sessions/:id` +
        pobranie pliku. Wynik ladu je w photos/.covers/<id>.jpg i zostaje na
        stale, wiec kolejne wejscia na ekran startowy juz nic nie sciagaja.

        Robimy to tylko przy zamknietej sesji: ekran startowy nie jest wtedy
        widoczny, a job workera nie moze opozniac obrobki zdjec."""
        with self.lock:
            sessions = list(self.automat_sessions)
            in_session = self.name
        if in_session:
            return
        uploader = None
        made = 0
        failed = 0
        for s in sessions:
            if self._stop.is_set():
                return
            sid = int(s.get("id") or 0)
            if not sid or not int(s.get("photos_count") or 0):
                continue
            dest = _cover_path(self.base_output, sid)
            if dest.exists():
                continue
            tmp = dest.with_suffix(".src")
            try:
                local = self._local_cover_source(str(s.get("name") or ""))
                if local is not None:
                    _make_cover(local, dest)
                else:
                    if uploader is None:
                        uploader = self._make_uploader()
                    pid = self._remote_cover_photo(uploader, sid)
                    if pid is None:
                        continue
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    # session_id jawnie — uploader okladek nie ma otwartej sesji
                    uploader.download_photo(pid, tmp, session_id=sid)
                    _make_cover(tmp, dest)
                    made += 1
            except Exception as e:
                # brak okladki to kosmetyka, wiec nie przerywamy listy — ale
                # pierwszy blad musi byc widoczny, inaczej cicha literowka
                # w wywolaniu API zostaje w kodzie na zawsze
                if not failed:
                    self._log(f"✗ Okładka sesji {s.get('name')!r}: {e}", "warn")
                failed += 1
                continue
            finally:
                tmp.unlink(missing_ok=True)
            with self.lock:
                for entry in self.automat_sessions:
                    if int(entry.get("id") or 0) == sid:
                        entry["cover"] = True
        if made:
            self._log(f"↓ Pobrano {made} {_photos_word(made)} na okładki sesji.")

    def _job_purge_trash(self) -> None:
        """Dopiero TU pliki znikaja naprawde — wpisy kosza starsze niz
        TRASH_RETENTION_DAYS. Odpalane raz przy starcie aplikacji."""
        try:
            n = _purge_trash(self.base_output)
        except Exception as e:
            self._log(f"✗ Czyszczenie kosza: {e}", "err")
            return
        if n:
            self._log(f"Kosz: skasowano {n} wpis(ów) starszych niż "
                      f"{TRASH_RETENTION_DAYS} dni.")

    def _job_cleanup_update(self) -> None:
        """Po restarcie w nowa wersje: kasuje katalog roboczy aktualizatora i
        wypisuje blad, jesli poprzednia proba nie doszla do skutku (inaczej
        nieudana aktualizacja wygladalaby jak jej brak)."""
        from . import updater

        try:
            err = updater.cleanup_after_update()
        except Exception:
            return
        if err:
            self._log(f"✗ Poprzednia aktualizacja nie doszła do skutku: {err}", "err")

    def _job_check_update(self, manual: bool = False) -> None:
        from . import updater

        with self.lock:
            self.update_checking = True
            self.update_status = "Sprawdzam…"
        try:
            info = updater.check_for_update()
        except Exception as e:
            with self.lock:
                self.update_status = f"✗ {e}"
            if manual:
                self._log(f"✗ Sprawdzenie aktualizacji: {e}", "err")
            return
        finally:
            with self.lock:
                self.update_checking = False
        with self.lock:
            self.update_info = info
            self.update_status = (f"Dostępna wersja {info['version']}" if info
                                  else f"Masz najnowszą wersję ({APP_VERSION})")
        if info is None:
            if manual:
                self._log(f"Aktualizacje: masz najnowszą wersję ({APP_VERSION}).", "ok")
            return
        self._log(f"Dostępna aktualizacja {info['version']} (masz {APP_VERSION}).", "warn")
        if not updater.can_self_update():
            self._log("Uruchomienie ze źródeł — zaktualizuj przez `git pull`.", "warn")

    def _job_apply_update(self) -> None:
        """Pobiera paczke, po czym zamyka aplikacje — reszte (podmiana plikow
        i restart) robi .exe z pobranej paczki, patrz src/updater.py."""
        from . import updater

        with self.lock:
            info = self.update_info
            busy = self.busy or self.processing_file
        if not info or not info.get("url"):
            self._log("✗ Brak paczki aktualizacji do pobrania.", "err")
            return
        if not updater.can_self_update():
            self._log("✗ Samo-aktualizacja działa tylko dla .exe (Windows).", "err")
            return
        if busy:
            self._log("✗ Trwa zdjęcie/obróbka — spróbuj aktualizacji za chwilę.", "err")
            return
        with self.lock:
            self.update_busy = True
            self.update_progress = 0
            self.update_status = "Pobieram aktualizację…"
        self._log(f"↓ Pobieram aktualizację {info['version']}…")

        def progress(pct: int) -> None:
            with self.lock:
                self.update_progress = pct

        try:
            staging = updater.download_and_stage(info["url"], progress)
        except Exception as e:
            with self.lock:
                self.update_busy = False
                self.update_status = f"✗ {e}"
            self._log(f"✗ Pobranie aktualizacji nie wyszło: {e}", "err")
            return
        with self.lock:
            self.update_status = "Restartuję aplikację…"
        self._log("Aktualizacja pobrana — zamykam i uruchamiam ponownie.", "ok")
        # osobny watek: _restart_into() czeka na zamkniecie workera w stop()
        threading.Thread(target=self._restart_into, args=(staging,),
                         daemon=True).start()

    def _restart_into(self, staging) -> None:
        """Odpala aktualizator i dopiero WTEDY zamyka aplikacje.

        Kolejnosc jest istotna: gdy aktualizator nie wystartuje (nowy .exe nie
        wstaje, brak uprawnien), aplikacja MUSI zostac otwarta z czytelnym
        bledem. Wczesniej `os._exit(0)` siedzial w `finally` i kazda wtopa
        aktualizatora wygladala identycznie — program znikal, nic sie nie
        zmienialo, nie bylo sladu."""
        from . import updater

        time.sleep(0.6)  # niech front zdazy pokazac status przed zniknieciem okna
        try:
            log = updater.apply_update_and_restart(staging)
        except Exception as e:
            self._log(f"✗ Nie udało się uruchomić aktualizatora: {e}", "err")
            self._log("Aplikacja działa dalej — zaktualizuj ręcznie z GitHub Releases.",
                      "warn")
            with self.lock:
                self.update_busy = False
                self.update_status = f"✗ {e}"
            return
        self._log(f"Aktualizator wystartował (log: {log}).", "ok")
        self.stop()   # domkniecie sesji aparatu — porzucone PTP = BUSY po restarcie
        os._exit(0)

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
        "session_covers": _job_session_covers,
        "delete": _job_delete,
        "test": _job_test,
        "check_update": _job_check_update,
        "apply_update": _job_apply_update,
        "cleanup_update": _job_cleanup_update,
        "purge_trash": _job_purge_trash,
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

    def _act_set_ev(self, data: dict) -> dict | None:
        """Kompensacja ekspozycji: żądanie tylko kolejkujemy — wykona je wątek
        camera, a stan i tak przyjdzie z aparatu przy najbliższym odpytaniu."""
        if not self.connected:
            return {"ok": False, "error": "aparat nie jest połączony"}
        value = str(data.get("value") or "").strip()
        if not value:
            return {"ok": False, "error": "brak wartości"}
        self._cam_q.put(("set_ev", value))
        return None

    def _act_shoot(self, data: dict) -> dict | None:
        if not self.connected:
            return {"ok": False, "error": "aparat nie jest połączony"}
        if not self.name:
            return {"ok": False, "error": "najpierw ustaw nazwę sesji"}
        if self.update_busy:
            # aplikacja zaraz sie zrestartuje — zdjecie zrobione teraz
            # zgineloby razem z workerem (job by sie nie doczekal obrobki)
            self._log("Trwa aktualizacja — migawka zablokowana do restartu.", "warn")
            return {"ok": False, "error": "trwa aktualizacja"}
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

    def _act_check_update(self, data: dict) -> None:
        # flaga ustawiana TU, jeszcze przed odpowiedzią na POST — worker może
        # być zajęty innym jobem, a spinner ma ruszyć od razu po kliknięciu
        with self.lock:
            self.update_checking = True
            self.update_status = "Sprawdzam…"
        self._jobs.put(("check_update", True))

    def _act_apply_update(self, data: dict) -> dict | None:
        with self.lock:
            if self.update_busy:
                return {"ok": False, "error": "aktualizacja już trwa"}
        self._jobs.put(("apply_update",))
        return None

    _ACTIONS = {
        "set_session": _act_set_session,
        "clear_session": _act_clear_session,
        "refresh_sessions": _act_refresh_sessions,
        "shoot": _act_shoot,
        "set_ev": _act_set_ev,
        "toggle": _act_toggle,
        "set_post": _act_set_post,
        "review": _act_review,
        "reject_last": _act_reject_last,
        "delete": _act_delete,
        "test_connection": _act_test_connection,
        "set_app": _act_set_app,
        "check_update": _act_check_update,
        "apply_update": _act_apply_update,
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

    def _update_state(self) -> dict:
        from . import updater

        info = self.update_info or {}
        return {
            "current": APP_VERSION,
            "available": info.get("version", ""),
            "notes": info.get("notes", "")[:400],
            "page": info.get("page", ""),
            "canApply": bool(info.get("url")) and updater.can_self_update(),
            "checking": self.update_checking,
            "busy": self.update_busy,
            "progress": self.update_progress,
            "status": self.update_status,
        }

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
                    "bgStatus": _bg_status(bg),
                    "ev": self.ev,
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
                "update": self._update_state(),
                "log": list(self.log),
            }

    # ---------- pliki ----------

    def latest_frame(self) -> bytes | None:
        with self._frame_lock:
            return self._frame

    def cover_bytes(self, session_id: str) -> bytes | None:
        """Okladka sesji z photos/.covers — id jest liczba, wiec sciezka nie
        moze uciec z katalogu (zadnego skladania nazw z wejscia)."""
        try:
            path = _cover_path(self.base_output, int(session_id))
        except (TypeError, ValueError):
            return None
        return path.read_bytes() if path.is_file() else None

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
        self._jobs.put(("cleanup_update",))
        self._jobs.put(("check_update",))
        self._jobs.put(("purge_trash",))

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
