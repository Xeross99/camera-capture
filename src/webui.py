"""Backend web UI (1:1 z projektu Claude Design "Camera Capture.dc.html").

Serwer HTTP (stdlib) + trzy watki jak w poprzednim GUI:
- camera: JEDYNY wlasciciel gphoto2 (preview loop z throttlingiem do
  preview_fps, komendy: shoot / preview on-off),
- worker: obrobka (rembg) + Automat (announce/upload/delete),
- HTTP (ThreadingHTTPServer): index.html, MJPEG stream, /api/state,
  /api/action (dispatcher), /img (pliki sesji + cache miniatur).

Handler HTTP mieszka w webui_http.py (klasa Handler, `ui` wstrzykiwane
subklasa w start()), a helpery plikowe sesji (review store, kosz, okladki)
w session_store.py.

Stan recenzji per sesja w photos/<sesja>/.review.json:
{rejected: [...], uploaded: [...], meta: {plik: "logo · zoom · 3000×3000"}}.
"""

import contextlib
import io
import os
import sys
import queue
import secrets
import shutil
import tempfile
import threading
import time
from collections import deque
from datetime import datetime
from http.server import ThreadingHTTPServer
from pathlib import Path

import numpy as np
from PIL import Image

from .automat_uploader import (AutomatNotFound, AutomatUploader,
                               describe_opened_session)
from .camera import CAMERA_ERRORS, make_camera_session
from .config import (
    CAMERA_EDSDK_ISOLATION,
    PREVIEW_FPS,
    CLEAN_BG_GPU,
    UI_THEME,
    UI_THEMES,
    AUTOMAT_API_TOKEN,
    AUTOMAT_BASE_URL,
    OUTPUT_SIZE,
    ROBOT_AXES,
    ROBOT_ENABLED,
    ROBOT_HOME_ON_CONNECT,
    ROBOT_JOINTS,
    ROBOT_JOINTS_ENV,
    ROBOT_JOINT_TOL,
    ROBOT_NUDGE_BIG,
    ROBOT_NUDGE_STEP,
    TRASH_RETENTION_DAYS,
    persist_env,
)
from .image_processing import LOGO_POSITIONS, process
from .naming import sanitize_name
from .robot import RoArmSession, RobotRangeError
from .session_store import (
    cover_path,
    finals,
    find_raw,
    load_review,
    make_cover,
    move_into,
    purge_trash,
    remote_filename,
    review_path,
    save_review,
    shot_entries,
    trash_batch,
)
from .version import APP_VERSION
from .webui_http import Handler

THUMB_SIZE = 360
DEFAULT_NAME_PATTERN = "photo_{data}_{godzina}.jpg"


def _now() -> str:
    return datetime.now().strftime("%H:%M:%S")


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


class _LogPipe(io.TextIOBase):
    """Przekierowanie stdout do logu UI na czas obrobki zdjecia.

    TUI przechwytuje print()y z pipeline'u od zawsze; webui je gubil — a w
    spakowanym .exe bez konsoli print leci w nicosc. Przez to ani pomiar
    czasu z `clean_background`, ani ostrzezenia (np. brak pliku logo) nie
    docieraly do operatora."""

    def __init__(self, ui: "WebUI") -> None:
        self.ui = ui
        self._buf = ""

    def write(self, s: str) -> int:
        self._buf += s
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            if line.strip():
                self.ui._log(line.strip())
        return len(s)


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
        self._robot_thread: threading.Thread | None = None
        self._sync_thread: threading.Thread | None = None
        self.lock = threading.RLock()
        # .review.json ma DWOCH pisarzy (worker i watek sync) — kazdy cykl
        # load -> mutacja -> save idzie pod tym zamkiem. RLock, bo _prune_local
        # (pod zamkiem) wola _discard_files, ktore kiedys moze go tez chciec.
        self._review_lock = threading.RLock()

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
        self.preview_fps = PREVIEW_FPS
        self.ui_theme = UI_THEME
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
        # ramie RoArm-M2-S (src/robot.py). `robot_pose` to ZADANE ujecie —
        # front trzyma je tylko jako optymistyczne echo, prawda jest tutaj,
        # zeby przezyc odswiezenie okna i restart frontu. Odleglosci ani kata
        # nie ma: ujecie to zapisane katy przegubow i nic sie w nim nie
        # reguluje (patrz komentarz na gorze robot.py).
        self.robot_connected = False
        self.robot_pose = next(iter(ROBOT_JOINTS))
        self.robot_busy = ""      # niepusty = ramie w ruchu (blokuje migawke)
        self.robot_error = ""
        # Ostatni odczytany uklad przegubow — pokazywany w logu przy polaczeniu
        # i w Ustawieniach, przy zapisywaniu ujec.
        self.robot_joints: list[float] | None = None
        # Serwa puszczone (moment off) — tylko na czas ustawiania ujecia recznie.
        self.robot_loose = False
        # Co robi w tej chwili watek camera i od kiedy. Watek ma JEDNEGO
        # wlasciciela portu, wiec kazda dluga operacja (podglad, strzal, odczyt
        # kompensacji, reconnect) blokuje odbieranie komend — bez tej informacji
        # „aparat nie odebral komendy" nie mowi, GDZIE utknal.
        self._cam_phase = ("start", 0.0)
        # znacznik czasu fazy, dla ktorej juz ostrzeglismy o utknieciu —
        # jedno ostrzezenie na epizod, nie co poll
        self._cam_warned_since = 0.0
        # obrobka tla na GPU — przelaczalne z Ustawien (kill-switch na maszyny
        # z chorymi sterownikami; stan poczatkowy z .env)
        self.clean_bg_gpu = CLEAN_BG_GPU
        # Rozgrzewka silnika czyszczenia tla: liczona OD STARTU aplikacji (job
        # warmup jest ostatni w kolejce startowej, ale silnik i tak nie jest
        # gotowy, zanim sie skonczy). Front pokazuje na podgladzie overlay —
        # sam wpis w logu byl za malo widoczny, gdy kompilacja shaderow
        # DirectML trzymala obrobke ~2 min.
        self.warmup_t0 = time.monotonic()
        self.warmup_done = False
        self._robot_read_at = 0.0   # throttle odpytywania katow w bezczynnosci
        # trwa ekspozycja/pobieranie pliku z aparatu — na ten czas ramie stoi.
        # Osobno od `busy`, ktore obejmuje takze obrobke (patrz _robot_ready).
        self.capturing = False
        self.syncing: list[str] = []  # nazwy zdjec pobieranych wlasnie z Automatu (skeletony w filmstripie)
        self.automat_sessions: list[dict] = []
        self.automat_sessions_error = ""
        self.sessions_refreshing = False  # trwa odswiezanie listy (spinner w UI)
        self.attach_to: dict | None = None  # {"id", "name"} — podłączenie do istniejącej sesji Automatu
        # aktualizacje (GitHub Releases — patrz src/updater.py)
        self.update_info: dict | None = None   # {"version", "url", "notes", "page", "size"}
        self.update_status = ""                # tekst dla UI (zakładka Ustawienia)
        self.update_checking = False           # trwa odpytanie GitHuba (spinner w UI)
        self.update_busy = False
        self.update_progress = 0
        self.log: deque[dict] = deque(maxlen=500)
        # kursor logu dla /api/state?since=N: rosnie przy kazdym nowym wpisie
        # ORAZ przy podbiciu licznika ×N — front dostaje tylko ogon, nie 500
        # wpisow przy kazdym pollu (patrz _log / state / mergeLog w app.js)
        self._log_seq = 0
        # cache filmstripa dla /api/state: (klucz mtime, wpisy) — patrz _session_shots
        self._shots_cache: tuple | None = None
        self.uploader: AutomatUploader | None = None  # tylko watek worker

        self.session = make_camera_session()
        # Pierwszy wpis w logu: ktory backend i CZEMU (np. skad wzieta
        # EDSDK.dll albo ze jej brak) — diagnoza z pierwszej linii logu.
        self._log(f"Backend aparatu: {getattr(self.session, 'backend_info', '?')}")
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
        # /stream czeka na NOWA klatke (id rosnie przy kazdej), zamiast
        # wysylac w kolko ostatnia w tempie preview_fps
        self._frame_cond = threading.Condition(self._frame_lock)
        self._frame_id = 0
        self._frame: bytes | None = None
        self._cam_q: queue.Queue[tuple] = queue.Queue()
        self._jobs: queue.Queue = queue.Queue()
        # zlecenia synchronizacji sesji (name, session_id) — WLASNY watek,
        # zeby pobieranie dziesiatek zdjec nie blokowalo kolejki workera
        # (obrobka strzalu czekalaby za siecia); None = sygnal konca
        self._sync_q: queue.Queue = queue.Queue()
        self.robot = RoArmSession()
        self.robot.should_stop = self._stop.is_set
        self.robot.log = self._log
        self._robot_q: queue.Queue[tuple] = queue.Queue()

    # ---------- log ----------

    def _log(self, text: str, kind: str = "info") -> None:
        with self.lock:
            self._log_seq += 1
            last = self.log[-1] if self.log else None
            # powtorka pod rzad (petla reconnectu aparatu!) nie zalewa logu —
            # rosnie licznik przy istniejacym wpisie, front dokleja "×N".
            # `seq` idzie w gore takze tutaj (wpis ma trafic w ogon since),
            # ale `id` zostaje — po nim front poznaje, ze to update, nie nowa
            # linia.
            if last is not None and last["text"] == text and last["kind"] == kind:
                last["n"] += 1
                last["t"] = _now()
                last["seq"] = self._log_seq
                return
            self.log.append({"id": self._log_seq, "seq": self._log_seq,
                             "t": _now(), "kind": kind, "text": text, "n": 1})

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
                self._phase('łączenie z aparatem')
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
            try:
                self._run_connected(quiet=flapping)
            except Exception as e:
                # Watek camera NIE MOZE umrzec po cichu. Wczesniej lecialo tu
                # tylko to, co lapie `_run_connected` (CAMERA_ERRORS), a kazdy
                # inny wyjatek — np. OSError z ctypes w EDSDK — wynosil sie z
                # petli i zabijal watek. Objaw byl mylacy: `connected` zostawalo
                # na True, MJPEG wisial na ostatniej klatce, a komendy pietrzyly
                # sie w `_cam_q` („aparat nie odebral poprzedniej komendy").
                self._log(f"✗ Wątek aparatu przerwany ({type(e).__name__}: {e}) "
                          "— łączę ponownie…", "err")
            self.session.close()
            self._drop_preview()
            with self.lock:
                # obrobka mogla zostac przerwana w polowie: bez tego przycisk
                # migawki zostawalby na „Wyzwalam migawke…" do konca sesji
                self.busy = ""
                self.capturing = False
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
            # zakolejkowany strzal nie doczeka sie juz obslugi — bez tego
            # flaga zostawalaby ustawiona na zawsze i ramie stalo zablokowane
            self.capturing = False
        self._ev_logged = False   # po ponownym połączeniu warto wypisać raz jeszcze
        with self._frame_cond:
            self._frame = None
            self._frame_cond.notify_all()

    def _phase(self, name: str) -> None:
        """Znacznik tego, co watek camera robi teraz (patrz `_cam_phase`)."""
        self._cam_phase = (name, time.monotonic())

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
                    self._phase("gotowy")
                    continue
                # przed gałęzią podglądu, żeby kompensacja odświeżała się także
                # przy wyłączonym live view (operator wciąż kręci pokrętłem)
                if time.monotonic() - self._ev_t0 >= self._EV_POLL_S:
                    self._ev_t0 = time.monotonic()
                    self._phase('odczyt kompensacji ekspozycji')
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
                    self._phase('pobieranie klatki podglądu')
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
                with self._frame_cond:
                    self._frame = data
                    self._frame_id += 1
                    self._frame_cond.notify_all()
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
            # get_setting = jeden widget, nie cale drzewo konfiguracji —
            # pelny get_config() co 2 s zjadal klatki live view na gphoto2
            ev = self.session.get_setting("exposurecompensation")
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
        self._phase("robienie zdjęcia")
        self._set_busy("Wyzwalam migawkę…")
        tmpdir = Path(tempfile.mkdtemp(prefix="capture_"))
        t0 = time.perf_counter()
        try:
            captured = self.session.capture_to(tmpdir)
        except (SystemExit, *CAMERA_ERRORS) as e:
            # Aparat potrafi WYPASC z USB w trakcie zdjecia (patrz
            # camera_edsdk/_FATAL_LINK_CODES). Kadr sie nie zmienil — produkt
            # lezy na stole — wiec zamiast wyrzucac ujecie: polaczenie od nowa
            # (przy izolacji = swiezy proces SDK) i JEDNA ponowna proba.
            self._log(f"✗ Błąd aparatu: {e} — łączę ponownie i ponawiam "
                      "zdjęcie…", "err")
            try:
                self.session.close()
            except Exception:
                pass
            try:
                self._phase("łączenie z aparatem")
                self._set_busy("Łączę ponownie…")
                self.session.open()
                self._phase("robienie zdjęcia (2. próba)")
                self._set_busy("Ponawiam zdjęcie…")
                captured = self.session.capture_to(tmpdir)
                self._log("Zdjęcie wyszło za drugim podejściem.", "ok")
            except (SystemExit, *CAMERA_ERRORS) as e2:
                self._log(f"✗ Zdjęcie nie wyszło także po ponownym połączeniu: "
                          f"{e2}", "err")
                shutil.rmtree(tmpdir, ignore_errors=True)
                self._set_busy("")
                with self.lock:
                    self.capturing = False
                return
        # ramie moze sie znowu ruszac: kadr jest juz w pliku, dalsza obrobka
        # (rembg, upload) nie patrzy na to, gdzie stoi kamera
        with self.lock:
            self.capturing = False
        # Stan obrobki ustawiany JUZ TERAZ, przy kolejkowaniu — nie dopiero
        # gdy _job_photo wystartuje. Job potrafi czekac w kolejce (najdluzej:
        # za rozgrzewka DirectML przy pierwszym uruchomieniu) i bez tego UI
        # przez caly ten czas wygladal, jakby zdjecie przepadlo: przycisk
        # wracal do "Zrob zdjecie", filmstrip bez skeletona.
        with self.lock:
            self.busy = "Czyszczę tło / centruję…"
            self.processing_file = opts["filename"]
        self._jobs.put(("photo", {**opts, "tmpdir": tmpdir, "captured": captured,
                                  "cap_s": time.perf_counter() - t0}))

    # ---------- watek robota ----------

    ROBOT_RECONNECT_MIN = 3.0
    ROBOT_RECONNECT_MAX = 30.0

    def _robot_loop(self) -> None:
        """Wlasciciel portu szeregowego ramienia — jeden watek, jak przy
        aparacie.

        SWIADOMIE nie worker: tam siedzi rembg, wiec ⌘1 czekaloby sekundy za
        obrobka zdjecia. I swiadomie nie watek camera: gphoto2/EDSDK maja miec
        jednego wlasciciela i nic wiecej do roboty miedzy klatkami podgladu.

        Backoff 3 → 30 s jak w `_camera_loop` — ramie bywa po prostu niepodpiete
        (maszyna deweloperska), a wtedy proba co 3 s przez cale uruchomienie
        zalewalaby log."""
        backoff = self.ROBOT_RECONNECT_MIN
        announced_fail = False
        while not self._stop.is_set():
            try:
                self.robot.open()
            except Exception as e:
                with self.lock:
                    self.robot_error = str(e)
                if not announced_fail:
                    announced_fail = True
                    self._log(f"Robot: {e}", "warn")
                if self._stop.wait(backoff):
                    return
                backoff = min(self.ROBOT_RECONNECT_MAX, backoff * 2)
                continue
            announced_fail = False
            backoff = self.ROBOT_RECONNECT_MIN
            with self.lock:
                self.robot_connected = True
                self.robot_error = ""
            self._log(f"Ramię połączone: {self.robot.describe()}", "ok")
            if ROBOT_HOME_ON_CONNECT:
                # Blad pozycji domowej NIE moze wywrocic watku: ramie bywa
                # przytrzymane albo bez zasilania serw, a wtedy chcemy dzialac
                # dalej i pokazac powod, nie stracic sterowanie na cala sesje.
                try:
                    self.robot.home()
                    self._log("Robot: ustawiony w pozycji domowej", "ok")
                except RobotRangeError as e:
                    self._log(f"✗ Robot: {e}", "err")
            pose, joints = self.robot.read_pose(), self.robot.read_joints()
            if pose:
                # Punkt wyjscia do kalibracji: te liczby wklejasz do .env
                # (ROBOT_POSE_*) albo porownujesz z tym, co ustawione.
                self._log("Robot: pozycja startowa " + RoArmSession._fmt(pose))
            if joints:
                # Katy przy KAZDYM polaczeniu, bo skala osi potrafi sie
                # przesunac miedzy uruchomieniami: `middle_set` z webowego UI
                # ramienia zeruje odniesienie wszystkich serw, a tryb osi 4
                # (chwytak/nadgarstek) zmienia jej interpretacje. Ujecia sa
                # zapisanymi katami, wiec takie przesuniecie unieważnia je
                # wszystkie — bez tego wpisu „czemu dzis inaczej niz wczoraj"
                # jest nie do ustalenia.
                with self.lock:
                    self.robot_joints = joints
                self._log("Robot: kąty startowe " + RoArmSession.fmt_joints(joints))
            try:
                self._run_robot()
            except Exception as e:
                self._log(f"✗ Robot: {e}", "err")
                with self.lock:
                    self.robot_error = str(e)
            self.robot.close()
            with self.lock:
                self.robot_connected = False
                self.robot_busy = ""
            if self._stop.wait(1.0):
                return

    def _run_robot(self) -> None:
        """Petla komend. Wyjscie = zerwany link (petla wyzej reconnectuje)."""
        while not self._stop.is_set():
            try:
                cmd = self._robot_q.get(timeout=0.3)
            except queue.Empty:
                # Przy puszczonych serwach operator wlasnie ustawia ujecie reka,
                # wiec katy musza chodzic na zywo w Ustawieniach. Poza tym
                # stanem nie odpytujemy ramienia bez powodu — port ma swoja
                # przepustowosc, a przy przejazdach czeka na nim `_wait_joints`.
                now = time.time()
                if now - self._robot_read_at > (0.3 if self.robot_loose else 1.0):
                    self._robot_read_at = now
                    joints = self.robot.read_joints()
                    if joints is not None:
                        with self.lock:
                            self.robot_joints = joints
                continue
            cmd = self._coalesce_robot(cmd)
            if cmd[0] == "torque":
                self._do_torque(cmd[1])
                continue
            if cmd[0] == "teach":
                self._do_teach(cmd[1])
                continue
            if cmd[0] == "nudge":
                self._do_nudge(cmd[1], cmd[2])
                continue
            if cmd[0] != "move":
                continue
            pose = cmd[1]
            self._set_robot_busy(f"Ramię jedzie: {pose}")
            try:
                self.robot.move(pose)
            except RobotRangeError as e:
                # ujecie nieustawione / ramie nie dojechalo — polaczenie jest
                # zdrowe, wiec tylko mowimy o tym operatorowi i czekamy dalej
                self._log(f"✗ Robot: {e}", "err")
            finally:
                self._set_robot_busy("")

    def _coalesce_robot(self, cmd: tuple) -> tuple:
        """Zostaje TYLKO ostatnia zadana pozycja.

        Szybkie ⌘1/⌘2/⌘1 potrafi wrzucic kilka komend, a kazdy przejazd trwa
        sekundy — bez zwijania kolejki ramie odgrywaloby cala historie klikania
        zamiast pojechac tam, gdzie operator ostatecznie wskazal."""
        if cmd[0] != "move":
            return cmd
        while True:
            try:
                nxt = self._robot_q.get_nowait()
            except queue.Empty:
                return cmd
            if nxt[0] != "move":
                # Puszczenie momentu i zapis ujecia MUSZA sie wykonac — nie
                # wolno ich zjesc przy zwijaniu. Odkladamy zwiniety przejazd
                # na kolejny obrot petli.
                self._robot_q.put(cmd)
                return nxt
            cmd = nxt

    def _set_robot_busy(self, text: str) -> None:
        with self.lock:
            self.robot_busy = text

    def _do_torque(self, on: bool) -> None:
        """Puszcza albo lapie serwa. Wykonywane W WATKU ROBOTA, bo dotyka portu.

        Puszczone serwa = ramie opada pod ciezarem aparatu, wiec operator musi
        je trzymac. Po ustawieniu ujecia lapie sie moment i dopiero wtedy da sie
        swobodnie klikac po UI (patrz sekcja „Robot" w CLAUDE.md)."""
        try:
            self.robot.set_torque(on is not False)
        except Exception as e:
            self._log(f"✗ Robot: nie udało się {'puścić' if on is False else 'złapać'} serw ({e})", "err")
            return
        with self.lock:
            self.robot_loose = on is False
        if on is False:
            self._log("Robot: serwa puszczone — PRZYTRZYMAJ ramię i ustaw ujęcie", "warn")
        else:
            self._log("Robot: serwa trzymają pozycję", "ok")

    def _do_teach(self, pose: str) -> None:
        """Zapisuje BIEZACE katy przegubow jako ujecie (`ROBOT_JOINTS_*`).

        Cala „kalibracja" tego ramienia to wlasnie to: ustaw raz recznie i
        zapisz. Zadnych dwoch probek, osi patrzenia ani wspolczynnikow — patrz
        historia w sekcji „Robot" w CLAUDE.md."""
        joints = self.robot.read_joints()
        if joints is None:
            self._log("✗ Robot: ramię nie oddaje odczytu kątów — nie zapisuję", "err")
            return
        ROBOT_JOINTS[pose] = joints
        with self.lock:
            self.robot_joints = joints
        persist_env(ROBOT_JOINTS_ENV[pose], ",".join(f"{v:.1f}" for v in joints))
        self._log(f"✓ Zapisano ujęcie {pose}: {RoArmSession.fmt_joints(joints)}", "ok")
        # Od razu: czy silniki w ogole utrzymaja te katy? Ujecie ustawione
        # reka przy puszczonych serwach potrafi lezec poza zasiegiem serwa
        # (os 4: reka −115°, silnik konczy na ~−107°) — przy ⌘1 skonczyloby
        # sie to „nie dojechalo" bez wyjasnienia, skad sie wzielo.
        self._set_robot_busy("Sprawdzam, czy silniki utrzymają ujęcie")
        try:
            now = self.robot.verify_pose(joints)
        except RobotRangeError as e:
            self._log(f"✗ Robot: {e}", "err")
            return
        finally:
            self._set_robot_busy("")
        if now is None:
            return
        off = [(i, n - t) for i, (t, n) in enumerate(zip(joints, now))
               if abs(n - t) > ROBOT_JOINT_TOL]
        if off:
            what = ", ".join(f"oś {i + 1} stoi na {now[i]:.0f}° zamiast {joints[i]:.0f}°"
                             for i, _ in off)
            self._log(f"⚠ Robot: ujęcie {pose} poza zasięgiem silników ({what}) — "
                      "przy ⌘ nie wróci dokładnie tutaj; ustaw je bliżej środka zakresu osi",
                      "warn")
        else:
            with self.lock:
                self.robot_joints = now
            self._log(f"Robot: silniki trzymają ujęcie {pose} "
                      f"(największa odchyłka {max(abs(n - t) for t, n in zip(joints, now)):.1f}°)")

    def _do_nudge(self, joint: int, delta: float) -> None:
        """Korekta jednej osi o `delta` stopni — wykonywana w watku robota.

        Kadru nie ustawia sie reka z dokladnoscia do stopnia, a od tego zalezy,
        czy produkt siedzi na srodku. Po ruchu odswiezamy `robot_joints`, zeby
        liczby w Ustawieniach chodzily razem z ramieniem."""
        before = self.robot.read_joints()
        try:
            joints = self.robot.nudge(joint, delta)
        except RobotRangeError as e:
            self._log(f"✗ Robot: {e}", "err")
            return
        if joints is None:
            self._log("✗ Robot: brak odczytu kątów — korekta nie wyszła", "err")
            return
        with self.lock:
            self.robot_joints = joints
        # Wpis w logu przy KAZDEJ korekcie: bez niego „klikam i nic sie nie
        # dzieje" jest nie do odroznienia od „os nie przyjmuje komendy". Gdy
        # os stoi w miejscu, mowimy to wprost — to najczestszy objaw zlej
        # konwersji kata (patrz tools/roarm_j4_probe.py).
        was = before[joint - 1] if before else float("nan")
        got = joints[joint - 1]
        if before and abs(got - was) < 0.3:
            self._log(f"✗ Robot: oś {joint} nie drgnęła (stoi na {got:.1f}°, "
                      f"miała iść na {was + delta:.1f}°)", "err")
        else:
            self._log(f"Robot: oś {joint}: {was:.1f}° → {got:.1f}°")

    def _robot_move(self) -> None:
        """Kolejkuje przejazd na aktualnie zadane ujecie."""
        with self.lock:
            pose = self.robot_pose
        self._robot_q.put(("move", pose))

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
        # sync w OSOBNYM watku (nie job workera): pobieranie zdjec starej
        # sesji nie moze wstrzymywac obrobki strzalow oddanych zaraz po wejsciu
        if u.session_id is not None:
            self._sync_q.put((name, int(u.session_id)))

    def _job_upload_off(self) -> None:
        self.uploader = None

    def _discard_files(self, session: str, files: list[str], review: dict) -> dict:
        """Lokalne usunięcie zdjęć — finalny JPEG i jego raw lądują w koszu
        (`photos/.trash/<data>_<sesja>/`), nie na śmietniku od razu: dopiero
        `purge_trash()` po `TRASH_RETENTION_DAYS` kasuje je naprawdę.
        Miniatura leci od razu (to cache, odtworzy się sama). Wpisy z
        `.review.json` są czyszczone, a zdjęte mapowania na Automat wracają
        do wołającego (`_job_delete` musi jeszcze skasować rekordy zdalne).

        `TRASH_RETENTION_DAYS = 0` = stare zachowanie, kasowanie natychmiast."""
        outdir = self.base_output / session
        batch = trash_batch(self.base_output, session) if TRASH_RETENTION_DAYS > 0 else None
        automat_ids = {}
        for f in files:
            (outdir / ".thumbs" / f).unlink(missing_ok=True)
            for p in ((outdir / f), find_raw(outdir, f)):
                if p is None or not p.exists():
                    continue
                if batch is None:
                    p.unlink(missing_ok=True)
                else:
                    move_into(batch, p)
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
                batch = trash_batch(self.base_output, name)
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
        stale = [f for f in finals(outdir) if f not in remote]
        if not stale:
            return 0
        with self._review_lock:
            review = load_review(outdir)
            self._discard_files(session, stale, review)
            save_review(outdir, review)
        self._log(f"Zdjęcia nieobecne w Automacie: {len(stale)} {_trash_note()}.",
                  "warn")
        return len(stale)

    def _sync_loop(self) -> None:
        """Petla watku sync — wlasciciel pobierania zdjec sesji z Automatu.

        Osobny watek (nie worker), bo sync starej sesji to potrafi byc
        kilkadziesiat MB po sieci — jako job workera wstrzymywalby obrobke
        zdjec strzelonych zaraz po wejsciu w sesje. Zalegle zlecenia sa
        zwijane: liczy sie ostatnio otwarta sesja."""
        while not self._stop.is_set():
            item = self._sync_q.get()
            if item is None:
                return
            while True:
                try:
                    nxt = self._sync_q.get_nowait()
                except queue.Empty:
                    break
                if nxt is None:
                    return
                item = nxt
            name, sid = item
            try:
                self._sync_session(name, sid)
            except Exception as e:
                # pojedyncza wtopa nie klade watku — nastepne wejscie w sesje
                # ma miec dzialajacy sync
                self._log(f"✗ Synchronizacja sesji {name}: {e}", "err")

    def _sync_session(self, name: str, sid: int) -> None:
        """Dwustronne zrownanie filmstripa z sesja w Automacie — Automat jest
        zrodlem prawdy: czego nie ma lokalnie, sciagamy (operator wszedl w
        sesje na maszynie, ktora jej nie strzelala — inny komputer, wyczyszczone
        photos/), czego nie ma juz zdalnie, kasujemy lokalnie (odsial zdjecia w
        UI Automatu — pliki ida do kosza, nie od razu na zawsze). Raw nigdy nie
        szedl po sieci, wiec wraca sam finalny JPEG; nie odtwarzamy raw/.

        Biega w watku sync z WLASNYM uploaderem (id sesji jawnie w kazdym
        wywolaniu) — worker w tym samym czasie robi announce/upload swoim
        obiektem, a requests.Session nie jest bezpieczne dla dwoch watkow."""
        u = self._make_uploader()
        try:
            photos = u.session_photos(session_id=sid)
        except AutomatNotFound:
            # calej sesji nie ma juz po drugiej stronie — folder do kosza
            self._trash_session(name)
            return
        except Exception as e:
            self._log(f"✗ Lista zdjęć sesji z Automatu: {e}", "err")
            return
        outdir = self.base_output / name
        have = set(finals(outdir))
        remote: dict[str, int] = {}
        missing = []
        for p in photos:
            fname = remote_filename(p)
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
        ok = 0
        with self.lock:
            self.syncing = [f for _, f in missing]
        try:
            for pid, fname in missing:
                with self.lock:
                    left = self.name != name
                if left:
                    # operator wyszedl z sesji (albo wszedl w inna) — nie ma
                    # po co dociagac reszty, nastepne wejscie zrobi swoj sync
                    break
                try:
                    u.download_photo(pid, outdir / fname, session_id=sid)
                except Exception as e:
                    self._log(f"✗ Pobranie {fname} z Automatu nie wyszło: {e}", "err")
                    continue
                finally:
                    # skeleton znika razem z proba, nie dopiero z sukcesem —
                    # inaczej po bledzie wisialby do konca sesji
                    with self.lock:
                        if fname in self.syncing:
                            self.syncing.remove(fname)
                # recenzja aktualizowana per plik pod _review_lock — worker
                # rownolegle pisze swoje wpisy po strzale/uploadzie
                with self._review_lock:
                    review = load_review(outdir)
                    review["automat"][fname] = pid
                    if fname not in review["uploaded"]:
                        review["uploaded"].append(fname)
                    save_review(outdir, review)
                ok += 1
        finally:
            with self.lock:
                self.syncing = []
        if ok:
            self._log(f"↓ Pobrano {ok} {_photos_word(ok)} z Automatu do {name}.", "ok")

    def _job_photo(self, job: dict) -> None:
        filename = job["filename"]
        outdir: Path = job["outdir"]
        with self.lock:
            self.processing_file = filename
            self.busy = "Czyszczę tło / centruję…"
        # Rozbicie czasu od migawki do kafelka w filmstripie. Sama linia
        # z `clean_background` mierzy tylko siebie — a operatorowi "obróbka"
        # to wszystko: USB z aparatu, announce, dekodowanie+zapis JPEG
        # (poza tamtym pomiarem) i upload. Bez pełnego rachunku każda
        # brakująca sekunda wygląda na zamrożoną aplikację.
        steps: list[str] = []
        if "cap_s" in job:
            steps.append(f"aparat {job['cap_s']:.1f} s")
        announced_id = None
        if job["upload"] and self.uploader is not None:
            t0 = time.perf_counter()
            try:
                announced_id = self.uploader.announce_photo(filename)
                steps.append(f"announce {time.perf_counter() - t0:.1f} s")
            except Exception as e:
                self._log(f"✗ Announce do Automatu nie wyszedł: {e}", "err")
        t0 = time.perf_counter()
        try:
            with contextlib.redirect_stdout(_LogPipe(self)):
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
        steps.append(f"obróbka {time.perf_counter() - t0:.1f} s")

        raw = outdir / f"{Path(filename).stem}_raw.jpg"
        if raw.exists():
            if self.keep_raw:
                (outdir / "raw").mkdir(exist_ok=True)
                raw.replace(outdir / "raw" / raw.name)
            else:
                raw.unlink()

        bits = []
        if job["add_logo"]:
            bits.append("logo")
        if job["auto_zoom"]:
            bits.append("zoom")
        bits.append(f"{OUTPUT_SIZE}×{OUTPUT_SIZE}")
        with self._review_lock:
            review = load_review(outdir)
            review["meta"][out.name] = " · ".join(bits)
            n = len([f for f in finals(outdir) if f not in review["rejected"]])
            if announced_id:
                # nawet gdy upload pozniej padnie, placeholder w Automacie
                # istnieje — delete musi go umiec sprzatnac
                review["automat"][out.name] = announced_id
            save_review(outdir, review)
        self._log(f"Zapisano {out.name} (#{n}) · " + " · ".join(steps), "ok")
        # Upload jako OSOBNY job na koncu kolejki: przy strzelaniu seriami
        # obrobka kolejnego zdjecia nie czeka na siec (~2-3 s na strzale).
        # Ten sam watek worker, wiec zero nowej wspolbieznosci; job niesie
        # SWOJ uploader — zmiana sesji w miedzyczasie nie przekieruje
        # zdjecia do cudzej sesji Automatu.
        if job["upload"] and self.uploader is not None:
            self._jobs.put(("upload_photo", {
                "outdir": outdir, "out": out,
                "photo_id": announced_id, "uploader": self.uploader,
            }))

    def _job_upload_photo(self, job: dict) -> None:
        out: Path = job["out"]
        if not out.exists():
            # skasowane (BACKSPACE -> kosz) zanim doszlo do uploadu; PUT na
            # martwy rekord konczylby sie retry POST-em, ktory wskrzeszalby
            # zdjecie po stronie Automatu
            return
        t0 = time.perf_counter()
        try:
            resp = job["uploader"].upload_processed(out, photo_id=job["photo_id"])
        except Exception as e:
            self._log(f"✗ Upload do Automatu nie wyszedł: {e}", "err")
            return
        with self._review_lock:
            review = load_review(job["outdir"])
            review["uploaded"].append(out.name)
            pid = resp.get("id") or job["photo_id"]
            if pid:
                review["automat"][out.name] = int(pid)
            save_review(job["outdir"], review)
        self._log(f"↑ {out.name} w Automacie ({time.perf_counter() - t0:.1f} s).", "ok")

    def _job_delete(self, session: str, files: list[str]) -> None:
        """Świadome kasowanie (BACKSPACE / „Odrzuć"): lokalnie do kosza
        (odwracalne przez TRASH_RETENTION_DAYS dni), w Automacie od razu —
        rekordu po drugiej stronie i tak nie umiemy przywrócić."""
        outdir = self.base_output / session
        with self._review_lock:
            review = load_review(outdir)
            automat_ids = list(self._discard_files(session, files, review).items())
            save_review(outdir, review)
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
                self.sessions_refreshing = False
            self._log(f"✗ Lista sesji z Automatu: {e}", "err")
            return
        for s in sessions:
            s["cover"] = cover_path(self.base_output, s.get("id") or 0).exists()
        with self.lock:
            self.automat_sessions = sessions
            self.automat_sessions_error = ""
            self.sessions_refreshing = False
        self._jobs.put(("session_covers",))

    def _local_cover_source(self, name: str) -> Path | None:
        """Najnowsze zdjecie sesji lezace juz na dysku — okladka bez sieci."""
        outdir = self.base_output / sanitize_name(name or "")
        files = finals(outdir)
        return (outdir / files[-1]) if files else None

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
            dest = cover_path(self.base_output, sid)
            if dest.exists():
                continue
            tmp = dest.with_suffix(".src")
            try:
                local = self._local_cover_source(str(s.get("name") or ""))
                if local is not None:
                    make_cover(local, dest)
                else:
                    if uploader is None:
                        uploader = self._make_uploader()
                    pid = self._remote_cover_photo(uploader, sid)
                    if pid is None:
                        continue
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    # session_id jawnie — uploader okladek nie ma otwartej sesji
                    uploader.download_photo(pid, tmp, session_id=sid)
                    make_cover(tmp, dest)
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
            n = purge_trash(self.base_output)
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

    def _job_warmup(self) -> None:
        """Rozgrzewka rembg przy starcie: pierwsza inferencja płaci jednorazowe
        koszty (model, a na DirectML kompilację shaderów pod GPU — zmierzone
        ~110 s u operatora). Bez tego joba cały ten rachunek obrywało PIERWSZE
        zdjęcie sesji i wyglądało to na zawieszoną obróbkę. Worker robi joby
        po kolei, więc strzał oddany w trakcie rozgrzewki po prostu poczeka —
        tyle samo, ile czekałby bez niej. Kolejkowana TYLKO gdy inferencja
        idzie na GPU (`_queue_warmup`) — na CPU nie ma czego kompilować."""
        from .background import warmup_clean_bg  # import lazy jak w process()

        self._log("Przygotowuję silnik czyszczenia tła na GPU — przy pierwszym "
                  "uruchomieniu kompilacja shaderów może potrwać do ~2 min; "
                  "zdjęcia zrobione w tym czasie poczekają w kolejce.")
        t0 = time.perf_counter()
        try:
            with contextlib.redirect_stdout(_LogPipe(self)):
                warmup_clean_bg()
        finally:
            # overlay na podgladzie MUSI zgasnac takze po bledzie rozgrzewki —
            # inaczej wisialby do konca uruchomienia
            with self.lock:
                self.warmup_done = True
        self._log(f"Silnik czyszczenia tła gotowy ({time.perf_counter() - t0:.0f} s).", "ok")

    def _queue_warmup(self) -> bool:
        """Rozgrzewka tylko wtedy, gdy rembg faktycznie pójdzie na GPU
        (przełącznik ON i onnxruntime ma provider GPU). W trybie CPU — a na
        macOS zawsze — nie ma shaderów do kompilacji, więc ani job, ani
        overlay „Przygotowuję silnik…" na podglądzie nie mają racji bytu.

        Wołane z głównego wątku w `start()`, więc import `background` (numpy,
        scipy — natywne DLL-e) NIE MOŻE wywrócić startu: na maszynie, gdzie
        Windows (Smart App Control / WDAC) blokuje niepodpisany `.pyd`
        scipy'ego, aplikacja ma wstać i powiedzieć w logu, co jest nie tak —
        martwy proces z dialogiem PyInstallera nie mówi operatorowi nic."""
        try:
            from . import background
            active = background.gpu_active()
        except Exception as e:  # noqa: BLE001 — DLL load failed, brak paczki itp.
            self._log(f"✗ Silnik czyszczenia tła nie ładuje się ({e}) — obróbka "
                      "zdjęć nie zadziała. Jeśli komunikat mówi o zasadach "
                      "kontroli aplikacji: Windows blokuje niepodpisaną "
                      "bibliotekę z paczki — wyłącz Inteligentną kontrolę "
                      "aplikacji (Zabezpieczenia Windows → Kontrola aplikacji "
                      "i przeglądarki) albo poproś administratora o wyjątek "
                      "dla katalogu aplikacji.", "err")
            active = False
        if not active:
            with self.lock:
                self.warmup_done = True
            return False
        with self.lock:
            self.warmup_done = False
            self.warmup_t0 = time.monotonic()
        self._jobs.put(("warmup",))
        return True

    _JOBS = {
        "warmup": _job_warmup,
        "photo": _job_photo,
        "upload_photo": _job_upload_photo,
        "open_session": _job_open_session,
        "upload_off": _job_upload_off,
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
            # flaga JUZ TERAZ (nie w jobie) — łapie ją pierwszy poll nawet gdy
            # worker jest zajęty, jak update.checking w _act_check_update
            with self.lock:
                self.sessions_refreshing = True
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
        # KAZDA odmowa idzie do logu. Front tylko odpala animacje migawki i nie
        # oglada odpowiedzi, wiec bez tego odrzucone ENTER wyglada identycznie
        # jak zepsuty aparat: blysk na podgladzie i nic wiecej.
        if not self.connected:
            self._log("Migawka: aparat nie jest połączony.", "warn")
            return {"ok": False, "error": "aparat nie jest połączony"}
        if not self.name:
            self._log("Migawka: najpierw ustaw nazwę sesji.", "warn")
            return {"ok": False, "error": "najpierw ustaw nazwę sesji"}
        if self.update_busy:
            # aplikacja zaraz sie zrestartuje — zdjecie zrobione teraz
            # zgineloby razem z workerem (job by sie nie doczekal obrobki)
            self._log("Trwa aktualizacja — migawka zablokowana do restartu.", "warn")
            return {"ok": False, "error": "trwa aktualizacja"}
        if self.robot_busy:
            # zdjecie w trakcie przejazdu ramienia to gwarantowane rozmycie
            self._log("Migawka: ramię jest w ruchu — poczekaj na koniec przejazdu.", "warn")
            return {"ok": False, "error": "ramię jest w ruchu"}
        # Watek camera odbiera komendy pojedynczo. Zalegajaca kolejka znaczy, ze
        # utknal (typowo: EDSDK czeka na plik z aparatu) — bez tego wpisu ENTER
        # wyglada jak zignorowany, bo nic sie nie dzieje i nic nie tlumaczy.
        if self._cam_q.qsize():
            phase, since = self._cam_phase
            held = f", stoi na tym {time.monotonic() - since:.0f} s" if since else ""
            self._log(f"Migawka: aparat nie odebrał jeszcze poprzedniej komendy "
                      f"({self._cam_q.qsize()} w kolejce) — wątek aparatu: "
                      f"{phase}{held}.", "warn")
        # od teraz do konca pobrania pliku ramie stoi (patrz _robot_ready)
        with self.lock:
            self.capturing = True
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

    def _robot_ready(self) -> dict | None:
        """Wspolne warunki dla obu komend ramienia. None = mozna jechac."""
        if not ROBOT_ENABLED:
            return {"ok": False, "error": "sterowanie ramieniem wyłączone"}
        if not self.robot_connected:
            return {"ok": False, "error": "ramię nie jest połączone"}
        # Ruch w trakcie ekspozycji/pobierania pliku zabralby aparatowi kadr
        # spod obiektywu. SWIADOMIE tylko `capturing`, nie `busy`: `busy`
        # obejmuje takze obrobke (rembg, sekundy), a wtedy kadr jest juz w
        # pliku i blokowanie ramienia byloby czekaniem bez powodu.
        if self.capturing:
            return {"ok": False, "error": "trwa zdjęcie"}
        return None

    def _act_robot_pose(self, data: dict) -> dict | None:
        pose = str(data.get("pose") or "")
        if pose not in ROBOT_JOINTS:
            return {"ok": False, "error": "nieznane ujęcie"}
        err = self._robot_ready()
        if err:
            return err
        if self.robot_loose:
            # serwo bez momentu nie wykona komendy pozycji — czekalibysmy
            # pelny timeout na ramie, ktore nie ma prawa ruszyc
            return {"ok": False, "error": "serwa są puszczone — najpierw złap pozycję"}
        with self.lock:
            self.robot_pose = pose
        self._robot_move()
        return None

    def _act_robot_torque(self, data: dict) -> dict | None:
        """Puszczenie/zlapanie serw — do recznego ustawiania ujecia."""
        if not ROBOT_ENABLED:
            return {"ok": False, "error": "sterowanie ramieniem wyłączone"}
        if not self.robot_connected:
            return {"ok": False, "error": "ramię nie jest połączone"}
        self._robot_q.put(("torque", bool(data.get("on"))))
        return None

    def _act_robot_nudge(self, data: dict) -> dict | None:
        """Korekta osi z przyciskow w Ustawieniach: `joint` 1..ROBOT_AXES,
        `delta` w stopniach."""
        try:
            joint = int(data.get("joint"))
            delta = float(data.get("delta"))
        except (TypeError, ValueError):
            return {"ok": False, "error": "brak osi albo kroku"}
        if not 1 <= joint <= ROBOT_AXES:
            return {"ok": False, "error": "nieznana oś"}
        if not self.robot_connected:
            return {"ok": False, "error": "ramię nie jest połączone"}
        if self.robot_loose:
            return {"ok": False, "error": "serwa są puszczone — najpierw złap pozycję"}
        if self.capturing:
            return {"ok": False, "error": "trwa zdjęcie"}
        self._robot_q.put(("nudge", joint, delta))
        return None

    def _act_robot_teach(self, data: dict) -> dict | None:
        """Zapis biezacej pozycji ramienia jako ujecie."""
        pose = str(data.get("pose") or "")
        if pose not in ROBOT_JOINTS:
            return {"ok": False, "error": "nieznane ujęcie"}
        if not self.robot_connected:
            return {"ok": False, "error": "ramię nie jest połączone"}
        self._robot_q.put(("teach", pose))
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
            review = load_review(self.session_dir)
            fresh = [f for f in finals(self.session_dir) if f not in review["rejected"]]
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
        "robot_pose": _act_robot_pose,
        "robot_torque": _act_robot_torque,
        "robot_teach": _act_robot_teach,
        "robot_nudge": _act_robot_nudge,
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
        with self._review_lock:
            review = load_review(outdir)
            was_rejected = filename in review["rejected"]
            if verdict == "rejected":
                if not was_rejected:
                    review["rejected"].append(filename)
                    self._log(f"Zdjęcie {filename} odrzucone.", "warn")
            else:
                if was_rejected:
                    review["rejected"].remove(filename)
                    self._log(f"Zdjęcie {filename} zaakceptowane.", "ok")
            save_review(outdir, review)

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
                persist_env("AUTOMAT_URL", self.automat_url)
                self._log("Adres Automatu zapisany w .env", "ok")
            elif key == "automat_token":
                if not str(value).startswith("•"):
                    self.automat_token = str(value)
                    self.uploader = None
                    self.upload_enabled = bool(self.automat_token)
                    persist_env("AUTOMAT_TOKEN", self.automat_token)
                    self._log("Token Automatu zapisany w .env", "ok")
                    if self.upload_enabled and self.name:
                        self._jobs.put(("open_session", self.name))
            elif key == "preview_fps":
                self.preview_fps = max(1, min(30, int(value)))
                # do .env — wybor ma przezyc restart (patrz PREVIEW_FPS)
                persist_env("PREVIEW_FPS", str(self.preview_fps))
            elif key == "ui_theme":
                theme = str(value).strip().lower()
                if theme in UI_THEMES:
                    self.ui_theme = theme
                    persist_env("UI_THEME", theme)
            elif key == "keep_raw":
                self.keep_raw = bool(value)
            elif key == "clean_bg_gpu":
                on = bool(value)
                self.clean_bg_gpu = on
                persist_env("CLEAN_BG_GPU", "true" if on else "false")
                from . import background
                background.set_gpu(on)
                if on:
                    # kompilacja MA sie odbyc teraz, z overlayem na podgladzie —
                    # a nie dopiero przy pierwszym zdjeciu, udajac zawieszona obrobke
                    if self._queue_warmup():
                        self._log("Obróbka tła: GPU (DirectML) — kompiluję shadery "
                                  "od razu, to potrafi trwać ~2 min.", "ok")
                    else:
                        self._log("Obróbka tła: GPU włączone, ale onnxruntime nie ma "
                                  "providera GPU — liczę dalej na CPU.", "warn")
                else:
                    self._log("Obróbka tła: CPU — działa od następnego zdjęcia.", "ok")

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

    def _session_shots(self, sdir: Path | None) -> list[dict]:
        """Filmstrip bez dyskowego I/O przy kazdym pollu /api/state (500 ms):
        glob katalogu i parsowanie .review.json leca tylko, gdy zmienil sie
        mtime katalogu sesji albo pliku recenzji. Wczesniej oba szly przy
        KAZDYM pollu, w dodatku pod globalnym RLockiem — wolniejszy dysk
        przyduszal watek camera czekajacy na ten sam lock."""
        if sdir is None:
            return []

        def _mtime(p: Path) -> int:
            try:
                return p.stat().st_mtime_ns
            except OSError:
                return -1

        key = (str(sdir), _mtime(sdir), _mtime(review_path(sdir)))
        cached = self._shots_cache
        if cached is not None and cached[0] == key:
            return cached[1]
        shots = shot_entries(sdir, load_review(sdir))
        self._shots_cache = (key, shots)
        return shots

    def _log_tail(self, since: int) -> list[dict]:
        """Wpisy logu z seq > since. Tylko OSTATNI wpis moze zmienic seq
        (licznik ×N), wiec seq w deque jest niemalejace — skan od konca
        i przerwanie na pierwszym starym wpisie."""
        tail: list[dict] = []
        for entry in reversed(self.log):
            if entry["seq"] <= since:
                break
            tail.append(entry)
        tail.reverse()
        return tail

    # Po tylu sekundach w jednej fazie uznajemy, ze watek aparatu UTKNAL.
    # Prog musi przezyc najdluzsza legalna operacje: strzal z awaryjnym
    # pobraniem z karty potrafi trwac do _CAPTURE_TIMEOUT_S (~30 s).
    _CAM_STUCK_S = 45.0

    def _cam_watchdog(self) -> None:
        """Wolane z kazdego pollu /api/state — wykrywa watek aparatu
        zablokowany WEWNATRZ wywolania Canon SDK.

        Takiego wywolania nie da sie przerwac z Pythona (ctypes siedzi w
        DLL-u), wiec jedyne, co mozemy zrobic, to powiedziec operatorowi
        WPROST, co uwalnia sytuacje: odpiecie kabla USB. Zablokowana funkcja
        SDK wraca wtedy z bledem, a petla camera przechodzi w normalny
        reconnect. Bez tego wpisu jedynym sladem byl rosnacy licznik
        „N w kolejce" i aplikacja do restartu."""
        phase, since = self._cam_phase
        if not since or phase == "gotowy":
            return
        age = time.monotonic() - since
        # Strzal z awaryjnym pobraniem z karty potrafi legalnie trwac ~50 s —
        # watchdog nie ma straszyc w trakcie normalnej (powolnej) operacji.
        limit = 70.0 if phase.startswith("robienie zdjęcia") else self._CAM_STUCK_S
        if age > limit and since != self._cam_warned_since:
            self._cam_warned_since = since
            if CAMERA_EDSDK_ISOLATION and sys.platform == "win32":
                hint = ("ogranicznik czasu zaraz sam zrestartuje sterownik "
                        "Canon. Jeśli to wraca co chwilę, winne jest USB tego "
                        "komputera — BIOS/sterowniki chipsetu, kabel, port.")
            else:
                hint = ("Wywołania Canon SDK nie da się przerwać z aplikacji — "
                        "odepnij i podepnij kabel USB aparatu, wtedy połączenie "
                        "wstanie od nowa.")
            self._log(f"✗ Wątek aparatu utknął: „{phase}” trwa {age:.0f} s — "
                      f"{hint}", "err")

    def state(self, log_since: int = 0) -> dict:
        self._cam_watchdog()
        with self.lock:
            sdir = self.session_dir
        shots = self._session_shots(sdir)   # dyskowe I/O POZA lockiem
        with self.lock:
            bg = self.bg_range
            return {
                "connected": self.connected,
                "warmup": None if self.warmup_done else int(time.monotonic() - self.warmup_t0),
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
                "robot": {
                    "enabled": ROBOT_ENABLED,
                    "connected": self.robot_connected,
                    "pose": self.robot_pose,
                    "busy": self.robot_busy,
                    "error": self.robot_error,
                    # ktore ujecia sa w ogole ustawione (`ROBOT_JOINTS_*` w
                    # .env) — panel wyszarza te, ktorych nie ma, zamiast
                    # wysylac ramie w nieznane
                    "set": {p: bool(a) for p, a in ROBOT_JOINTS.items()},
                    # do sekcji „Robot — ujęcia" w Ustawieniach; `axes` = ile
                    # wierszy korekty (5 z serwem pochylenia kamery, 4 bez)
                    "axes": ROBOT_AXES,
                    "loose": self.robot_loose,
                    "joints": self.robot_joints,
                    "nudge": [ROBOT_NUDGE_STEP, ROBOT_NUDGE_BIG],
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
                    "refreshing": self.sessions_refreshing,
                },
                "settings": {
                    "photosDir": str(self.base_output),
                    "logoPath": str(self.logo_path),
                    "namePattern": self.name_pattern,
                    "automatUrl": self.automat_url,
                    "tokenMasked": ("•" * 12 + self.automat_token[-4:]) if self.automat_token else "",
                    "previewFps": self.preview_fps,
                    "uiTheme": self.ui_theme,
                    "cleanBgGpu": self.clean_bg_gpu,
                    "keepRaw": self.keep_raw,
                    "testResult": self.test_result,
                },
                "update": self._update_state(),
                "log": self._log_tail(log_since),
                "logSeq": self._log_seq,
            }

    # ---------- pliki ----------

    def next_frame(self, last_id: int, timeout: float = 1.0) -> tuple[bytes | None, int]:
        """Klatka NOWSZA niz last_id dla /stream, albo (None, last_id) po
        timeoucie. Watek camera budzi czekajacych przy kazdej nowej klatce —
        MJPEG nie wysyla juz tej samej klatki w kolko, gdy aparat oddaje ich
        mniej niz preview_fps."""
        with self._frame_cond:
            if self._frame_id == last_id:
                self._frame_cond.wait(timeout)
            if self._frame is None or self._frame_id == last_id:
                return None, last_id
            return self._frame, self._frame_id

    def cover_bytes(self, session_id: str) -> bytes | None:
        """Okladka sesji z photos/.covers — id jest liczba, wiec sciezka nie
        moze uciec z katalogu (zadnego skladania nazw z wejscia)."""
        try:
            path = cover_path(self.base_output, int(session_id))
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
            # Uciety/nieczytelny JPEG (np. plik sprzed zapisu atomowego) nie moze
            # wywracac requestu tracebackiem — 404, front sprobuje przy nastepnym
            # odswiezeniu paska. Miniatura tez idzie przez tmp + rename, zeby
            # przerwany zapis nie zostawil w cache uciętej miniatury ze swiezym
            # mtime (taka nigdy nie zostalaby przeliczona).
            ttmp = tdir / (path.name + ".part")
            try:
                img = Image.open(path)
                img.thumbnail((THUMB_SIZE, THUMB_SIZE))
                img.save(ttmp, "JPEG", quality=80)
            except OSError:
                ttmp.unlink(missing_ok=True)
                return None
            os.replace(ttmp, tpath)
        return tpath.read_bytes()

    # ---------- start ----------

    def _guarded(self, loop, what: str):
        """Owija petle watku tak, zeby jej smierc byla WIDOCZNA.

        Watek, ktory ginie na nieobsluzonym wyjatku, nie zostawia w UI zadnego
        sladu: aplikacja dziala dalej, tylko przestaje reagowac na komendy —
        i wyglada to na zepsuty sprzet, nie na blad programu."""
        def run():
            try:
                loop()
            except BaseException as e:      # noqa: BLE001 — logujemy WSZYSTKO
                self._log(f"✗ Wątek {what} zakończył się błędem "
                          f"({type(e).__name__}: {e}) — zrestartuj aplikację.", "err")
                raise
        return run

    def start(self) -> str:
        """Startuje watki + serwer na efemerycznym porcie 127.0.0.1.
        Zwraca URL z jednorazowym tokenem — bez niego serwer odpowiada 403,
        wiec UI jest dostepne tylko dla okna aplikacji (nie da sie wejsc
        "z boku" przegladarka na goly adres)."""
        self._camera_thread = threading.Thread(target=self._guarded(self._camera_loop, "aparatu"),
                                               daemon=True)
        self._worker_thread = threading.Thread(target=self._guarded(self._worker_loop, "obróbki"),
                                               daemon=True)
        self._sync_thread = threading.Thread(
            target=self._guarded(self._sync_loop, "synchronizacji"), daemon=True)
        self._camera_thread.start()
        self._worker_thread.start()
        self._sync_thread.start()
        if ROBOT_ENABLED:
            self._robot_thread = threading.Thread(target=self._guarded(self._robot_loop, "ramienia"),
                                                  daemon=True)
            self._robot_thread.start()
        if self.automat_token:
            self._jobs.put(("list_sessions",))
        self._jobs.put(("cleanup_update",))
        self._jobs.put(("check_update",))
        self._jobs.put(("purge_trash",))
        # ostatnia w kolejce startowej — szybkie joby wyżej nie mogą czekać
        # dziesiątek sekund za kompilacją shaderów DirectML; w trybie CPU
        # nie jest kolejkowana wcale
        self._queue_warmup()

        handler = type("BoundHandler", (Handler,), {"ui": self})
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
        # Proces-dziecko EDSDK ubijamy OD RAZU (bezpieczne z innego watku —
        # to operacja na procesie, nie na porcie): watek camera moze wisiec
        # w RPC i join nizej czekalby pelnego timeoutu, a osierocone dziecko
        # pokazywaloby po minutach dialog PyInstallera na pulpicie.
        terminate = getattr(self.session, "terminate", None)
        if terminate is not None:
            terminate()
        self._jobs.put(None)
        self._sync_q.put(None)
        if self._camera_thread is not None:
            self._camera_thread.join(timeout=4.0)
        if self._worker_thread is not None:
            self._worker_thread.join(timeout=3.0)
        if self._sync_thread is not None:
            # w najgorszym razie w locie jest jedno pobranie — krotki join,
            # pliki i tak pisza sie przez .part + rename
            self._sync_thread.join(timeout=2.0)
        if self._robot_thread is not None:
            # watek zwalnia port szeregowy (niezamkniety = „resource busy" przy
            # nastepnym starcie); czekanie na koniec przejazdu przerywa
            # `should_stop`, wiec nie stoimy tu pelnego ROBOT_MOVE_TIMEOUT
            self._robot_thread.join(timeout=4.0)
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
