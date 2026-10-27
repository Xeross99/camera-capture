"""Wspolne przygotowanie testow.

Testy NIGDY nie dotykaja prawdziwego aparatu, sieci ani `.env` operatora:
- zmienne ponizej sa ustawione PRZED importem `src` (load_dotenv nie nadpisuje
  istniejacych), wiec token Automatu z `.env` nie trafia do testow i nic nie
  leci do Automatu;
- `make_camera_session` jest podmieniane na `FakeCamera` (oddaje zdjecie
  z `tests/fixtures`), EDSDK sie nie laduje;
- zapis do `.env` (`persist_env`) i `.warmup.json` ida do slownika / tmp;
- GitHub (aktualizacje) odpowiada z podstawionej funkcji.
"""

import os
import shutil
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"

os.environ.update({
    "AUTOMAT_TOKEN": "",
    # nieosiagalny adres: domyslny localhost:3000 bywa zajety przez inny serwer
    # deweloperski i test zalezalby od tego, co akurat tam dziala
    "AUTOMAT_URL": "http://127.0.0.1:9",
    "AUTOMAT_UPLOAD_ENABLED": "false",
    "CAMERA_EDSDK_ISOLATION": "false",
    "CLEAN_BG_GPU": "false",
    "TRASH_RETENTION_DAYS": "30",
    "RAW_RETENTION_DAYS": "0",
    "LOGO": "kids",
    "UI_THEME": "light",
    # testy porównują polskie komunikaty — język z .env (np. po przełączeniu
    # aplikacji na angielski) nie może ich zmieniać
    "UI_LANG": "pl",
    "PREVIEW_FPS": "10",
})
sys.path.insert(0, str(ROOT))


class FakeCamera:
    """Udawany aparat z interfejsem sesji EDSDK (open/preview_frame/capture_to/
    get_setting/set_setting/focus_at/close). Zapisuje wywolania, a `fail_*`
    pozwala zasymulowac awarie."""

    EV_CHOICES = ["-1", "-2/3", "-1/3", "0", "+1/3", "+2/3", "+1"]

    def __init__(self) -> None:
        self.backend_info = "edsdk (atrapa w testach)"
        self.opened = 0
        self.captures = 0
        self.focus_calls: list[tuple[float, float]] = []
        self.ev = "0"
        self.fail_capture = 0      # ile kolejnych strzalow ma sie wywalic
        self.fail_focus = ""       # tekst bledu ostrzenia ("" = dziala)
        self.reject_ev = False     # aparat ignoruje zmiane kompensacji
        self._preview = (FIXTURES / "preview.jpg").read_bytes()

    def open(self) -> None:
        self.opened += 1

    def close(self) -> None:
        pass

    def preview_frame(self) -> bytes:
        return self._preview

    def capture_to(self, workdir: Path) -> Path:
        if self.fail_capture:
            self.fail_capture -= 1
            raise RuntimeError("atrapa: aparat zgubil polaczenie")
        self.captures += 1
        dest = Path(workdir) / f"IMG_{self.captures:04d}.JPG"
        shutil.copy(FIXTURES / "product_raw.jpg", dest)
        return dest

    def get_setting(self, key: str) -> dict | None:
        if key != "exposurecompensation":
            return None
        return {"current": self.ev, "choices": list(self.EV_CHOICES)}

    def set_setting(self, key: str, value: str) -> str:
        if not self.reject_ev:
            self.ev = value
        return ""

    def focus_at(self, fx: float, fy: float) -> str:
        self.focus_calls.append((fx, fy))
        if self.fail_focus:
            raise RuntimeError(self.fail_focus)
        return "ok"


def wait_for(cond, timeout: float = 30.0, what: str = "warunek"):
    """Czeka, az `cond()` zwroci prawde (watki aplikacji pracuja w tle)."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        value = cond()
        if value:
            return value
        time.sleep(0.05)
    raise AssertionError(f"nie doczekalem sie: {what}")


@pytest.fixture
def env_store():
    """Co aplikacja zapisalaby do `.env`."""
    return {}


@pytest.fixture
def camera():
    return FakeCamera()


@pytest.fixture
def make_app(tmp_path, monkeypatch, camera, env_store):
    """Fabryka aplikacji (WebUI) na atrapie aparatu i katalogu tmp.
    `start=True` odpala watki i serwer HTTP, jak prawdziwe okno."""
    from src import config, updater, webui

    monkeypatch.setattr(webui, "make_camera_session", lambda: camera)
    monkeypatch.setattr(webui, "persist_env", lambda k, v: env_store.__setitem__(k, v))
    monkeypatch.setattr(config, "persist_env", lambda k, v: env_store.__setitem__(k, v))
    monkeypatch.setattr(webui, "WARMUP_FILE", tmp_path / ".warmup.json")
    monkeypatch.setattr(updater, "latest_release", lambda: None)
    monkeypatch.setattr(updater, "cleanup_after_update", lambda: None)
    # strzal ma byc szybki, a reconnect nie moze czekac w testach 5 s
    monkeypatch.setattr(webui.WebUI, "_EV_POLL_S", 0.2)

    apps = []

    def factory(start: bool = True, **kw):
        opts = dict(logo=config.DEFAULT_LOGO, base_output=tmp_path / "photos",
                    upload=False, add_logo=True, logo_position="bottom-right",
                    auto_center=True, auto_zoom=True)
        opts.update(kw)
        app = webui.WebUI(**opts)
        apps.append(app)
        if start:
            app.url = app.start()
            wait_for(lambda: app.state()["connected"], 10, "polaczenie z atrapa aparatu")
        return app

    yield factory
    for app in apps:
        # log aplikacji na stdout — pytest pokazuje go przy czerwonym tescie
        print("\n--- log aplikacji ---")
        for e in list(app.log):
            print(f"[{e.get('kind')}] {e.get('text')}")
        app._stop.set()
        app._jobs.put(None)
        app._sync_q.put(None)
        if app._server is not None:
            app._server.shutdown()
            app._server.server_close()


@pytest.fixture
def app(make_app):
    return make_app()


def log_texts(app) -> list[str]:
    return [e["text"] for e in app.state()["log"]]


def shoot_and_wait(app, timeout: float = 120.0) -> str:
    """ENTER: zdjecie + obrobka, zwraca nazwe gotowego pliku."""
    before = set(f["file"] for f in app.state()["shots"])
    res = app.action({"action": "shoot"})
    assert res["ok"], res
    def done():
        st = app.state()
        new = [s["file"] for s in st["shots"] if s["file"] not in before]
        if not new or st["busy"]:
            return None
        # plik i wolna migawka pojawiaja sie, zanim worker dopisze .review.json
        # i raw/ — koniec obrobki to dopiero wpis „Zapisano <plik>" w logu
        return new[0] if any(t.startswith(f"Zapisano {new[0]}") for t in log_texts(app)) else None
    return wait_for(done, timeout, "gotowe zdjecie w sesji")


__all__ = ["FakeCamera", "FIXTURES", "wait_for", "log_texts", "shoot_and_wait"]
