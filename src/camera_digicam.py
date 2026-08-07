"""Backend aparatu dla Windows: digiCamControl (https://digicamcontrol.com).

libgphoto2 nie istnieje na Windows, wiec tam aparatem steruje digiCamControl
przez jego webserver HTTP (Settings -> Webserver -> Enable, port 5513):
- live view:  GET /liveview.jpg (po CMD=LiveViewWnd_Show),
- strzal:     SLC capture + set session.folder na katalog roboczy,
- plik:       digiCamControl sam sciaga zdjecie do session.folder, my pollujemy.

Interfejs 1:1 z CameraSession (open/preview_frame/capture_to/get_settings/
set_setting/close) — webui nie widzi roznicy miedzy backendami.
"""

import subprocess
import sys
import time
from pathlib import Path

import requests

from .config import DIGICAMCONTROL_EXE, DIGICAMCONTROL_URL

_CAPTURE_TIMEOUT_S = 60
_JPEG_MAGIC = b"\xff\xd8"

# Nazwa property kompensacji ekspozycji w SLC digiCamControl.
_EV_KEY = "exposurecompensation"


def _parse_list(text: str) -> list[str]:
    """Odpowiedz `slc list` bywa JSON-em, a bywa zwyklymi liniami — zaleznie od
    wersji dCC. Bierzemy oba, bo nie ma po co przywiazywac sie do jednej."""
    text = (text or "").strip()
    if text.startswith("["):
        import json
        try:
            return [str(v).strip() for v in json.loads(text) if str(v).strip()]
        except ValueError:
            pass
    return [line.strip().strip('",') for line in text.splitlines() if line.strip()]

# Typowe sciezki instalatora digiCamControl (uzywane gdy DIGICAMCONTROL_EXE
# nie jest ustawione w .env).
_DEFAULT_EXES = (
    r"C:\Program Files (x86)\digiCamControl\CameraControl.exe",
    r"C:\Program Files\digiCamControl\CameraControl.exe",
)


class DigiCamControlSession:
    def __init__(self) -> None:
        self.base = DIGICAMCONTROL_URL
        self._http = requests.Session()
        self._launched = False       # auto-start dCC tylko raz na zycie sesji
        self._minimize_ok = True     # All_Minimize wylaczane gdy psuje live view
        self._ev_choices: list[str] | None = None   # cache listy kompensacji

    def _get(self, path: str, timeout: float = 10, **params) -> requests.Response:
        r = self._http.get(f"{self.base}{path}", params=params or None, timeout=timeout)
        r.raise_for_status()
        return r

    def _slc(self, cmd: str, param1: str = "", param2: str = "",
             timeout: float = 30) -> str:
        text = self._get("/", timeout=timeout, slc=cmd,
                         param1=param1, param2=param2).text.strip()
        if "error" in text.lower():
            raise RuntimeError(f"digiCamControl: {cmd} → {text}")
        return text

    def _server_up(self, timeout: float = 3) -> bool:
        try:
            self._get("/session.json", timeout=timeout)
            return True
        except requests.RequestException:
            return False

    def _launch_app(self) -> bool:
        """Startuje CameraControl.exe gdy webserver nie odpowiada — operator
        nie musi recznie uruchamiac digiCamControl przed nasza aplikacja."""
        if self._launched or sys.platform != "win32":
            return False
        candidates = ([DIGICAMCONTROL_EXE] if DIGICAMCONTROL_EXE else []) + list(_DEFAULT_EXES)
        exe = next((p for p in candidates if p and Path(p).exists()), None)
        if exe is None:
            return False
        subprocess.Popen([exe], close_fds=True)
        self._launched = True
        return True

    def _show_live_view(self) -> None:
        # /liveview.jpg zwraca klatki dopiero gdy okno live view jest otwarte.
        try:
            self._get("/", timeout=5, CMD="LiveViewWnd_Show")
        except requests.RequestException:
            pass

    def _first_frame(self, timeout_s: float) -> None:
        # Pierwsza klatka potwierdza, ze aparat faktycznie jest podpiety —
        # sam webserver odpowiada takze bez aparatu.
        deadline = time.monotonic() + timeout_s
        while True:
            try:
                self.preview_frame()
                return
            except (requests.RequestException, RuntimeError):
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        "digiCamControl działa, ale nie daje live view — "
                        "sprawdź czy aparat jest podłączony i wykryty."
                    )
                time.sleep(0.5)

    def open(self) -> None:
        if not self._server_up():
            if self._launch_app():
                deadline = time.monotonic() + 30
                while not self._server_up(timeout=2) and time.monotonic() < deadline:
                    time.sleep(1.0)
            if not self._server_up():
                raise RuntimeError(
                    f"Brak połączenia z digiCamControl ({self.base}). "
                    "Zainstaluj digiCamControl, włącz webserver "
                    "(Settings → Webserver → Enable) i podepnij aparat."
                )
        self._show_live_view()
        self._first_frame(10)
        # dCC to tylko sterownik w tle — chowamy jego okna. Gdy minimalizacja
        # zabija live view (rozne wersje dCC), wracamy do widocznego okna
        # i wiecej nie probujemy.
        if self._minimize_ok:
            try:
                self._get("/", timeout=5, CMD="All_Minimize")
                self._first_frame(5)
            except (requests.RequestException, RuntimeError):
                self._minimize_ok = False
                self._show_live_view()
                self._first_frame(10)

    def preview_frame(self) -> bytes:
        data = self._get("/liveview.jpg", timeout=5).content
        if not data.startswith(_JPEG_MAGIC):
            raise RuntimeError("digiCamControl: brak klatki live view")
        return data

    def capture_to(self, workdir: Path) -> Path:
        before = {p.name for p in workdir.iterdir()}
        self._slc("set", "session.folder", str(workdir))
        self._slc("set", "session.filenametemplate", "capture_[Counter 4 digit]")
        self._slc("capture", timeout=_CAPTURE_TIMEOUT_S)
        deadline = time.monotonic() + _CAPTURE_TIMEOUT_S
        target = None
        last_size = -1
        while time.monotonic() < deadline:
            if target is None:
                fresh = [p for p in workdir.iterdir()
                         if p.name not in before
                         and p.suffix.lower() in (".jpg", ".jpeg")]
                if fresh:
                    target = max(fresh, key=lambda p: p.stat().st_mtime)
            else:
                # transfer z aparatu trwa — czekamy az rozmiar sie ustabilizuje
                size = target.stat().st_size
                if size > 0 and size == last_size:
                    return target
                last_size = size
            time.sleep(0.3)
        raise RuntimeError(
            f"digiCamControl: zdjęcie nie pojawiło się w katalogu roboczym "
            f"w {_CAPTURE_TIMEOUT_S} s (transfer z aparatu nie doszedł?)"
        )

    def get_settings(self) -> dict:
        """Tylko kompensacja ekspozycji (`slc get/list exposurecompensation`).
        ISO, czas i przyslone ustawia sie na aparacie albo w oknie dCC."""
        try:
            current = self._slc("get", _EV_KEY, timeout=5)
            if self._ev_choices is None:
                # lista wyborow nie zmienia sie w trakcie sesji, a webui pyta
                # co 2 s — nie ma po co bic po HTTP dwa razy za kazdym razem
                self._ev_choices = _parse_list(self._slc("list", _EV_KEY, timeout=5))
        except (requests.RequestException, RuntimeError):
            return {}
        choices = self._ev_choices or []
        current = current.strip().strip('"')
        if not current or not choices:
            return {}   # aparat w trybie bez kompensacji
        # NIE wymagamy, zeby `current` bylo w `choices`: dCC potrafi oddac
        # biezaca wartosc innym zapisem niz elementy listy ("+3.0" vs "+2 2/3").
        # Front i tak porownuje liczbowo, wiec niedopasowany zapis mu nie wadzi.
        return {"exposurecompensation": {"current": current, "choices": choices}}

    def set_setting(self, key: str, value: str) -> str:
        """Zwraca surową odpowiedź dCC — gdy aparat nie przyjmie wartości,
        webui wkleja ją do logu; bez tego zostawało samo „wróciło na stare"."""
        if key != "exposurecompensation":
            raise RuntimeError(
                f"zmiana '{key}' niedostępna przez digiCamControl — "
                "ustaw w oknie digiCamControl lub na aparacie")
        return self._slc("set", _EV_KEY, str(value), timeout=10)

    def describe_contrast(self) -> dict | None:
        return None

    def set_contrast(self, value) -> str:
        raise RuntimeError("kontrast niedostępny przez digiCamControl")

    def close(self) -> None:
        try:
            self._get("/", timeout=3, CMD="LiveViewWnd_Hide")
        except requests.RequestException:
            pass
