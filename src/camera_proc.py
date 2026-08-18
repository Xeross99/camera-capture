"""EDSDK w osobnym PROCESIE — watchdog, ktory naprawde umie zresetowac.

Po co: na niektorych maszynach (zaobserwowane: Acer Nitro, Ryzen 5800H)
wywolania EDSDK potrafia zawisnac NA ZAWSZE wewnatrz DLL-a Canona —
`EdsDownloadEvfImage` po zdjeciu albo zaraz po polaczeniu. Zawieszonego
wywolania ctypes nie da sie przerwac z Pythona, a wypiecie kabla przez
operatora zostawia SDK zatrute w srodku procesu: `EdsTerminateSDK` +
ponowna inicjalizacja w tym samym procesie konczy sie access violation
(patrz camera_edsdk), wiec kolejne proby lecialy na martwych uchwytach
(blad 0x0061 INVALID_HANDLE) i wszystko zacinalo sie w kolko.

Proces-dziecko rozwiazuje obie rzeczy naraz:
  * zawieszony PROCES zawsze da sie zabic (TerminateProcess nie pyta DLL-a
    o zdanie) — po timeoucie RPC dziecko ginie, rodzic dostaje wyjatek z
    rodziny CAMERA_ERRORS i petla camera w webui robi normalny reconnect;
  * kazde `open()` to NOWE dziecko, czyli swiezy `EdsInitializeSDK` — po
    zabiciu nie zostaje zaden zatruty stan.
Rachunek: zacieicie zmienia sie z „aplikacja do restartu + kabel" w
kilkunastosekundowa czkawke, ktora naprawia sie sama, bez zadnych uprawnien.

Protokol: JSON po liniach na stdin/stdout dziecka. Zadanie {"id", "op", ...},
odpowiedz {"id", "ok", ...} (klatka podgladu jako base64 — ~30% narzutu przy
~100 KB klatkach to od 2 MB/s, bez znaczenia). Dziecko wysyla tez ramki
{"event": "log"/"status"} — to iga hooki on_log/on_status EdsdkSession przez
granice procesu. Wszystkie wywolania ida z JEDNEGO watku (camera w webui),
wiec rodzic czyta odpowiedzi w watku czytelnika i dopasowuje po id.

Dziecko to TEN SAM program (`gui.py --edsdk-server` / `.exe --edsdk-server`,
lapane przed cieszkimi importami jak `--apply-update`) — zero dodatkowych
plikow w paczce PyInstallera.

Wylacznik: CAMERA_EDSDK_ISOLATION=false w .env wraca do EDSDK w procesie
aplikacji (stare zachowanie, gdyby izolacja sama cos popsula).
"""

from __future__ import annotations

import base64
import json
import queue
import subprocess
import sys
import threading
from collections import deque
from pathlib import Path

from .config import PROJECT_DIR

# Ile czekamy na odpowiedz dziecka, zanim uznamy je za zawieszone i zabijemy.
# open: init SDK + konfiguracja aparatu; capture: wlasne timeouty EDSDK
# (~40 s z awaryjnym pobraniem z karty) + sciagniecie 24 MP.
_TIMEOUTS = {"open": 60.0, "preview": 12.0, "capture": 120.0,
             "get_setting": 10.0, "set_setting": 10.0,
             "get_settings": 10.0, "close": 5.0}
# Drugi, ostrzejszy limit: CISZA od dziecka. W trakcie strzalu dziecko nadaje
# co sekunde (status „Czekam na plik…", wpisy logu), wiec 15 s bez zadnej ramki
# oznacza zawieszke w DLL-u — nie ma po co czekac pelnych 120 s calkowitego
# limitu, gdy np. EdsDownload utknie przy pobieraniu pliku. Dotyczy operacji
# dlugich; krotkie (preview, ustawienia) i tak maja ciasne limity calkowite.
_QUIET_LIMITS = {"open": 30.0, "capture": 15.0}


class CameraProcError(RuntimeError):
    """Dziecko EDSDK nie odpowiada / zginelo — RuntimeError, wiec siedzi w
    CAMERA_ERRORS i petla camera w webui reaguje normalnym reconnectem."""


# ---------------------------------------------------------------- serwer

def run_edsdk_server() -> int:
    """Petla RPC w procesie-dziecku — opakowana tak, ze ZADEN wyjatek nie
    ucieka na wierzch: PyInstaller w buildzie okienkowym pokazuje wtedy
    MessageBox „Unhandled exception in script", ktory wyskakiwal operatorowi
    na pulpit, gdy osierocone dziecko probowalo pisac w martwa rure po
    zamknieciu rodzica (OSError 22)."""
    try:
        return _serve()
    except SystemExit as e:     # ciche zejscie (martwa rura do rodzica)
        return int(e.code or 0)
    except BaseException as e:  # noqa: BLE001 — dialogu nie bedzie NIGDY
        try:
            print(f"edsdk-server: {type(e).__name__}: {e}", file=sys.stderr)
        except Exception:
            pass
        return 1


def _serve() -> int:
    """Wlasciwa petla. Jednowatkowa i blokujaca Z PREMEDYTACJA:
    gdy SDK zawisnie, wisi cale dziecko — a rodzic wtedy je zabija."""
    real_out = sys.stdout.buffer
    lock = threading.Lock()

    def send(obj: dict) -> None:
        try:
            with lock:
                real_out.write(json.dumps(obj, ensure_ascii=False).encode() + b"\n")
                real_out.flush()
        except OSError:
            # rodzic zniknal (zamkniecie aplikacji przy wiszacym watku camera
            # osieroca dziecko) — nie ma dla kogo nadawac, koniec bez halasu
            raise SystemExit(0)

    # stdout to KANAL RPC — print()y z SDK/konfiguracji musza isc na stderr.
    # Podmiana PRZED importem camera_edsdk, zeby zlapac tez printy z importu.
    sys.stdout = sys.stderr
    from .camera_edsdk import EdsdkSession

    ses = EdsdkSession()
    ses.on_log = lambda text, kind="info": send({"event": "log", "text": text, "kind": kind})
    ses.on_status = lambda text: send({"event": "status", "text": text})

    ops = {
        "open": lambda req: ses.open(),
        "preview": lambda req: base64.b64encode(ses.preview_frame()).decode(),
        "capture": lambda req: str(ses.capture_to(Path(req["workdir"]))),
        "get_setting": lambda req: ses.get_setting(req["key"]),
        "set_setting": lambda req: ses.set_setting(req["key"], req["value"]),
        "get_settings": lambda req: ses.get_settings(),
        "close": lambda req: ses.close(),
    }
    while True:
        line = sys.stdin.buffer.readline()
        if not line:          # rodzic zniknal — nie ma dla kogo zyc
            break
        try:
            req = json.loads(line)
        except ValueError:
            continue
        op = req.get("op")
        try:
            result = ops[op](req)
            send({"id": req["id"], "ok": True, "result": result})
        except BaseException as e:  # noqa: BLE001 — kazdy blad wraca do rodzica
            send({"id": req["id"], "ok": False,
                  "error": f"{e}", "kind": type(e).__name__})
        if op == "close":
            break
    try:
        ses.close()
    except Exception:
        pass
    return 0


# ---------------------------------------------------------------- proxy

class EdsdkProxy:
    """Interfejs CameraSession, pod spodem dziecko z prawdziwym EdsdkSession.

    Uzywany z JEDNEGO watku (camera w webui) — jak kazdy backend aparatu."""

    def __init__(self) -> None:
        self.backend_info = ""
        self.on_status = None
        self.on_log = None
        self._proc: subprocess.Popen | None = None
        self._frames: queue.Queue = queue.Queue()
        self._stderr_tail: deque[str] = deque(maxlen=30)
        self._req_id = 0

    # ---------- zycie dziecka ----------

    def _spawn(self) -> None:
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--edsdk-server"]
        else:
            cmd = [sys.executable, str(PROJECT_DIR / "gui.py"), "--edsdk-server"]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self._proc = subprocess.Popen(
            cmd, cwd=str(PROJECT_DIR), stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            creationflags=flags)
        self._frames = queue.Queue()
        threading.Thread(target=self._read_stdout, args=(self._proc,),
                         daemon=True).start()
        threading.Thread(target=self._read_stderr, args=(self._proc,),
                         daemon=True).start()

    def _read_stdout(self, proc: subprocess.Popen) -> None:
        for line in proc.stdout:
            try:
                self._frames.put(json.loads(line))
            except ValueError:
                pass
        self._frames.put(None)      # EOF = dziecko nie zyje

    def _read_stderr(self, proc: subprocess.Popen) -> None:
        # stderr dziecka to printy z SDK i tracebacki — trzymamy ogon do
        # komunikatu bledu (i zeby dziecko nie stanelo na pelnym buforze)
        for line in proc.stderr:
            text = line.decode("utf-8", "replace").rstrip()
            if text:
                self._stderr_tail.append(text)

    def _kill(self) -> None:
        proc, self._proc = self._proc, None
        if proc is None:
            return
        try:
            proc.kill()
            proc.wait(timeout=5)
        except Exception:
            pass

    # ---------- RPC ----------

    def _call(self, op: str, **kw):
        if self._proc is None or self._proc.poll() is not None:
            raise CameraProcError("proces EDSDK nie działa")
        self._req_id += 1
        req = {"id": self._req_id, "op": op, **kw}
        try:
            self._proc.stdin.write(json.dumps(req).encode() + b"\n")
            self._proc.stdin.flush()
        except OSError as e:
            self._kill()
            raise CameraProcError(f"proces EDSDK nie przyjął komendy ({e})") from e
        import time as _time
        started = _time.monotonic()
        quiet = _QUIET_LIMITS.get(op, _TIMEOUTS[op])
        last_frame = started
        while True:
            now = _time.monotonic()
            timeout = min(quiet - (now - last_frame),
                          _TIMEOUTS[op] - (now - started))
            frame = None
            if timeout > 0:
                try:
                    frame = self._frames.get(timeout=timeout)
                except queue.Empty:
                    pass
            if frame is None and self._frames.empty():
                # ZAWIESZKA w DLL-u Canona — dokladnie to, po co jest ten modul:
                # albo minal limit calkowity, albo dziecko ZAMILKLO (w trakcie
                # strzalu nadaje co sekunde, wiec cisza = wiszace wywolanie).
                # Zabijamy dziecko; wyjatek wraca do petli camera, ktora zrobi
                # reconnect i dostanie SWIEZY proces ze swiezym EdsInitializeSDK.
                self._kill()
                waited = _time.monotonic() - started
                raise CameraProcError(
                    f"aparat nie odpowiada ({op}, {waited:.0f} s bez reakcji) — "
                    "restartuję sterownik Canon i łączę od nowa")
            if frame is None:
                continue
            last_frame = _time.monotonic()
            if frame is None:
                tail = self._stderr_tail[-1] if self._stderr_tail else "brak szczegółów"
                self._kill()
                raise CameraProcError(f"proces EDSDK zakończył się ({tail})")
            if "event" in frame:
                self._dispatch_event(frame)
                continue
            if frame.get("id") != self._req_id:
                continue        # spozniona odpowiedz po timeoucie — ignoruj
            if frame.get("ok"):
                return frame.get("result")
            raise CameraProcError(frame.get("error") or "nieznany błąd EDSDK")

    def _dispatch_event(self, frame: dict) -> None:
        try:
            if frame["event"] == "log" and self.on_log is not None:
                self.on_log(frame.get("text", ""), frame.get("kind", "info"))
            elif frame["event"] == "status" and self.on_status is not None:
                self.on_status(frame.get("text", ""))
        except Exception:
            pass

    def terminate(self) -> None:
        """Twarde ubicie dziecka — wolane przy zamykaniu aplikacji (webui.stop).

        Bez tego dziecko przezywa rodzica, gdy watek camera wisi w RPC:
        po minutach jego zawieszone wywolanie wraca, proba odpowiedzi w martwa
        rure konczy sie wyjatkiem, a PyInstaller pokazuje operatorowi dialog.
        Ubicie dziecka konczy tez blokujace `_frames.get` w watku camera
        (czytelnik wrzuca sentinel EOF), wiec join watku przy stop() nie stoi
        pelnego timeoutu RPC."""
        self._kill()

    # ---------- interfejs CameraSession ----------

    def open(self) -> None:
        # kazde open = nowe dziecko: po zabiciu / bledzie nie ma czego
        # reanimowac, a swiezy proces to swiezy, niezatruty SDK
        self._kill()
        self._spawn()
        self._call("open")

    def close(self) -> None:
        if self._proc is not None and self._proc.poll() is None:
            try:
                self._call("close")
            except CameraProcError:
                pass
        self._kill()

    def preview_frame(self) -> bytes:
        return base64.b64decode(self._call("preview"))

    def capture_to(self, workdir: Path) -> Path:
        return Path(self._call("capture", workdir=str(workdir)))

    def get_setting(self, key: str):
        return self._call("get_setting", key=key)

    def set_setting(self, key: str, value: str):
        return self._call("set_setting", key=key, value=value)

    def get_settings(self) -> dict:
        return self._call("get_settings")
