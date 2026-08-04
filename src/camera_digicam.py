"""Backend aparatu dla Windows: digiCamControl (https://digicamcontrol.com).

libgphoto2 nie istnieje na Windows, wiec tam aparatem steruje digiCamControl
przez jego webserver HTTP (Settings -> Webserver -> Enable, port 5513):
- live view:  GET /liveview.jpg (po CMD=LiveViewWnd_Show),
- strzal:     SLC capture + set session.folder na katalog roboczy,
- plik:       digiCamControl sam sciaga zdjecie do session.folder, my pollujemy.

Interfejs 1:1 z CameraSession (open/preview_frame/capture_to/get_settings/
set_setting/close) — webui nie widzi roznicy miedzy backendami.
"""

import time
from pathlib import Path

import requests

from .config import DIGICAMCONTROL_URL

_CAPTURE_TIMEOUT_S = 60
_JPEG_MAGIC = b"\xff\xd8"


class DigiCamControlSession:
    def __init__(self) -> None:
        self.base = DIGICAMCONTROL_URL
        self._http = requests.Session()

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

    def open(self) -> None:
        try:
            self._get("/session.json", timeout=3)
        except requests.RequestException as e:
            raise RuntimeError(
                f"Brak połączenia z digiCamControl ({self.base}). "
                "Uruchom digiCamControl, włącz webserver "
                "(Settings → Webserver → Enable) i podepnij aparat."
            ) from e
        # /liveview.jpg zwraca klatki dopiero gdy okno live view jest otwarte.
        try:
            self._get("/", timeout=5, CMD="LiveViewWnd_Show")
        except requests.RequestException:
            pass
        # Pierwsza klatka potwierdza, ze aparat faktycznie jest podpiety —
        # sam webserver odpowiada takze bez aparatu.
        deadline = time.monotonic() + 10
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
        # Webserver digiCamControl nie eksponuje list wyboru ISO/przyslony itd.
        # — sekcja "Aparat" w UI zostaje pusta; ustawienia zmienia sie w oknie
        # digiCamControl albo na aparacie.
        return {}

    def set_setting(self, key: str, value: str) -> None:
        raise RuntimeError(
            "zmiana ustawień aparatu niedostępna przez digiCamControl — "
            "ustaw w oknie digiCamControl lub na aparacie"
        )

    def describe_contrast(self) -> dict | None:
        return None

    def set_contrast(self, value) -> str:
        raise RuntimeError("kontrast niedostępny przez digiCamControl")

    def close(self) -> None:
        try:
            self._get("/", timeout=3, CMD="LiveViewWnd_Hide")
        except requests.RequestException:
            pass
