"""Logika aplikacji (WebUI) na atrapie aparatu: strzal, odmowy migawki,
kasowanie do kosza, recenzja, ostrosc, kompensacja, edycja logo, ustawienia,
dostep do serwera tylko z tokenem."""

import io
from pathlib import Path
import json
import urllib.error
import urllib.request

import numpy as np
import pytest
from PIL import Image

from conftest import log_texts, shoot_and_wait, wait_for
from src import config
from src.session_store import load_review, shot_entries


def open_session(app, name="sesja testowa"):
    res = app.action({"action": "set_session", "name": name})
    assert res["ok"], res
    return app.base_output / name


# ---------- strzal ----------

def test_enter_takes_photo_into_session(app, camera):
    sdir = open_session(app)
    f = shoot_and_wait(app)
    assert camera.captures == 1
    assert (sdir / f).exists()
    assert (sdir / "raw" / f.replace(".jpg", "_raw.jpg")).exists(), "oryginal z aparatu w raw/"
    with Image.open(sdir / f) as im:
        assert im.size == (3000, 3000)
    st = app.state()
    assert st["session"]["count"] == 1
    assert st["busy"] == "" and st["processing"] is None
    assert any(t.startswith(f"Zapisano {f}") for t in log_texts(app))


def test_two_photos_in_the_same_second_are_both_kept(app, camera):
    sdir = open_session(app)
    app.action({"action": "shoot"})
    app.action({"action": "shoot"})
    wait_for(lambda: sum(t.startswith("Zapisano ") for t in log_texts(app)) == 2, 120,
             "obrobka obu zdjec")
    assert len(app.state()["shots"]) == 2, "drugie zdjecie nie moze nadpisac pierwszego"


def test_photo_meta_describes_processing(app):
    sdir = open_session(app)
    f = shoot_and_wait(app)
    assert load_review(sdir)["meta"][f] == "logo · zoom · 3000×3000"


def test_shutter_refused_without_session(app, camera):
    res = app.action({"action": "shoot"})
    assert res == {"ok": False, "error": "najpierw ustaw nazwę sesji"}
    assert camera.captures == 0
    assert "Migawka: najpierw ustaw nazwę sesji." in log_texts(app)


def test_shutter_refused_when_camera_disconnected(make_app):
    app = make_app(start=False)
    open_session(app)
    assert app.action({"action": "shoot"})["error"] == "aparat nie jest połączony"


def test_shutter_refused_during_update(app, camera):
    open_session(app)
    app.update_busy = True
    assert app.action({"action": "shoot"})["error"] == "trwa aktualizacja"
    assert camera.captures == 0


def test_capture_retries_once_after_camera_error(app, camera):
    sdir = open_session(app)
    camera.fail_capture = 1
    f = shoot_and_wait(app)
    assert (sdir / f).exists()
    assert "Zdjęcie wyszło za drugim podejściem." in log_texts(app)


def test_capture_failing_twice_frees_shutter(app, camera):
    open_session(app)
    camera.fail_capture = 2
    assert app.action({"action": "shoot"})["ok"]
    wait_for(lambda: any("także po ponownym połączeniu" in t for t in log_texts(app)),
             20, "blad drugiej proby")
    wait_for(lambda: app.state()["busy"] == "", 5, "przycisk migawki znow wolny")
    assert app.state()["shots"] == []


# ---------- kasowanie i recenzja ----------

def test_backspace_moves_photo_and_raw_to_trash(app):
    sdir = open_session(app)
    f = shoot_and_wait(app)
    app.action({"action": "delete", "session": sdir.name, "files": [f]})
    wait_for(lambda: not (sdir / f).exists(), 10, "zdjecie zniknelo z sesji")
    trash = list((app.base_output / ".trash").glob(f"*_{sdir.name}"))
    assert len(trash) == 1
    names = sorted(p.name for p in trash[0].iterdir())
    assert names == sorted([f, f.replace(".jpg", "_raw.jpg")]), "do kosza idzie zdjecie i oryginal"
    assert app.state()["session"]["count"] == 0


def test_overlay_on_live_view_is_the_camera_original(app):
    """Nakladka na live view: zmniejszony ORYGINAL z aparatu (ten sam kadr co
    podglad), nie przyciety 3000x3000 — i znika razem ze zdjeciem."""
    sdir = open_session(app)
    f = shoot_and_wait(app)
    shot = app.state()["shots"][0]
    assert shot["ghost"] == "raw"
    data = app.image_bytes(sdir.name, f, thumb=False, ghost=True)
    with Image.open(sdir / "raw" / f.replace(".jpg", "_raw.jpg")) as raw, Image.open(io.BytesIO(data)) as im:
        assert abs(im.width / im.height - raw.width / raw.height) < 0.01, "proporcje oryginalu"
        assert max(im.size) <= 1600
    app.action({"action": "delete", "session": sdir.name, "files": [f]})
    wait_for(lambda: not (sdir / f).exists(), 10, "zdjecie zniknelo z sesji")
    assert not (sdir / ".ghosts" / f).exists()
    assert app.image_bytes(sdir.name, f, thumb=False, ghost=True) is None


def test_overlay_without_original_falls_back_to_final(app):
    sdir = open_session(app)
    f = shoot_and_wait(app)
    (sdir / "raw" / f.replace(".jpg", "_raw.jpg")).unlink()
    assert shot_entries(sdir, load_review(sdir))[0]["ghost"] == "final"
    with Image.open(io.BytesIO(app.image_bytes(sdir.name, f, thumb=False, ghost=True))) as im:
        assert im.width == im.height, "gotowe zdjecie 1:1"


def test_shot_with_overlay_remembers_frame_and_aligns(app):
    sdir = open_session(app)
    first = shoot_and_wait(app)
    frame = load_review(sdir)["frame"][first]
    assert set(frame) == {"window", "bbox", "src"}
    app.action({"action": "shoot", "align": first})
    wait_for(lambda: sum(t.startswith("Zapisano ") for t in log_texts(app)) == 2, 120, "drugie zdjecie")
    second = [f for f in load_review(sdir)["frame"] if f != first]
    assert second, "kadr drugiego zdjecia tez zapisany"


def test_overlay_photo_without_frame_gets_one_from_original(app):
    """Zdjecie sprzed zapisywania kadrow: kadr liczony raz z oryginalu,
    zeby kontur na live view i korekta dzialaly tez z nim."""
    from src.session_store import save_review
    sdir = open_session(app)
    f = shoot_and_wait(app)
    review = load_review(sdir)
    review["frame"].pop(f)
    save_review(sdir, review)
    app.action({"action": "ghost_frame", "file": f})
    wait_for(lambda: load_review(sdir)["frame"].get(f), 60, "kadr policzony z oryginalu")
    assert shot_entries(sdir, load_review(sdir))[0]["box"]


def test_reject_and_accept(app):
    sdir = open_session(app)
    f = shoot_and_wait(app)
    app.action({"action": "review", "session": sdir.name, "file": f, "verdict": "rejected"})
    assert app.state()["session"]["rejected"] == 1
    app.action({"action": "review", "session": sdir.name, "file": f, "verdict": "accepted"})
    assert app.state()["session"]["rejected"] == 0


# ---------- ostrosc w kliknietym punkcie ----------

def test_click_focuses_at_point(app, camera):
    res = app.action({"action": "focus_at", "x": 0.25, "y": 0.75})
    assert res["ok"]
    focus = wait_for(lambda: app.state()["focus"], 5, "wynik ostrzenia")
    assert camera.focus_calls == [(0.25, 0.75)]
    assert focus["ok"] and focus["at"] == [0.25, 0.75] and focus["seq"] == res["seq"]
    assert app.state()["focusSupported"]


@pytest.mark.parametrize("point, error", [
    ({"x": 1.2, "y": 0.5}, "punkt poza kadrem"),
    ({"x": "a", "y": 0.5}, "zły punkt"),
    ({}, "zły punkt"),
])
def test_focus_rejects_bad_points(app, camera, point, error):
    assert app.action({"action": "focus_at", **point})["error"] == error
    assert camera.focus_calls == []


def test_focus_failure_explains_af_mode(app, camera):
    camera.fail_focus = "DoEvfAf: AF NG"
    app.action({"action": "focus_at", "x": 0.5, "y": 0.5})
    focus = wait_for(lambda: app.state()["focus"], 5, "wynik ostrzenia")
    assert not focus["ok"]
    assert any("Ostrość w punkcie" in t and "AF z wybieranym punktem" in t for t in log_texts(app))


def test_focus_failure_without_af_hint_for_other_errors(app, camera):
    camera.fail_focus = "proces sterownika nie odpowiada"
    app.action({"action": "focus_at", "x": 0.5, "y": 0.5})
    wait_for(lambda: app.state()["focus"], 5, "wynik ostrzenia")
    line = next(t for t in log_texts(app) if "Ostrość w punkcie" in t)
    assert "AF z wybieranym punktem" not in line


# ---------- kompensacja ekspozycji ----------

def test_ev_change_reaches_camera(app, camera):
    wait_for(lambda: app.state()["camera"]["ev"], 5, "odczyt kompensacji")
    assert app.action({"action": "set_ev", "value": "+1/3"})["ok"]
    wait_for(lambda: (app.state()["camera"]["ev"] or {}).get("current") == "+1/3", 5, "nowa kompensacja")
    assert camera.ev == "+1/3"


def test_ev_rejected_by_camera_is_reported(app, camera):
    camera.reject_ev = True
    app.action({"action": "set_ev", "value": "+1"})
    wait_for(lambda: any("Aparat nie przyjął kompensacji +1" in t for t in log_texts(app)),
             5, "komunikat o odrzuceniu")


# ---------- edycja logo na gotowym zdjeciu ----------

def test_edit_logo_moves_and_removes_logo(app):
    sdir = open_session(app)
    f = shoot_and_wait(app)
    app.action({"action": "edit_save", "file": f, "logo": "kids", "position": "top-left"})
    wait_for(lambda: app.state()["editSaving"] is None and "Zmieniono" in " ".join(log_texts(app)),
             20, "zmiana logo")
    assert load_review(sdir)["meta"][f].startswith("logo")
    app.action({"action": "edit_save", "file": f, "logo": "", "position": "bottom-right"})
    wait_for(lambda: "bez logo" in " ".join(log_texts(app)), 20, "zdjecie bez logo")
    assert "logo" not in load_review(sdir)["meta"][f].split(" · ")
    nologo = np.asarray(Image.open(sdir / ".nologo" / f).convert("L").resize((64, 64)), dtype=int)
    now = np.asarray(Image.open(sdir / f).convert("L").resize((64, 64)), dtype=int)
    assert np.abs(now - nologo).max() <= 6, "bez logo = wersja z .nologo"


def test_photo_info_names_logo_and_follows_logo_edit(app):
    open_session(app)
    f = shoot_and_wait(app)
    info = app.shot_info("sesja testowa", f)
    assert info["logo"] is True and info["logoInfo"]["pos"] == "bottom-right"
    assert info["raw"]["size"], "oryginal z aparatu lezy w raw/"
    app.action({"action": "edit_save", "file": f, "logo": "kids", "position": "top-left"})
    wait_for(lambda: (app.shot_info("sesja testowa", f)["logoInfo"] or {}).get("pos") == "top-left",
             20, "nowy rog logo w metadanych")
    assert app.shot_info("sesja testowa", f)["logoInfo"]["label"] == "TRIXBRIX.eu KIDS"
    app.action({"action": "edit_save", "file": f, "logo": "", "position": "bottom-right"})
    wait_for(lambda: app.shot_info("sesja testowa", f)["logo"] is False, 20, "bez logo")
    assert app.shot_info("sesja testowa", f)["logoInfo"] is None
    assert app.shot_info("sesja testowa", "../../etc/passwd") is None


def test_logo_editor_adds_logo_used_on_next_photo(app):
    import base64
    buf = io.BytesIO()
    Image.new("RGBA", (300, 100), (220, 20, 20, 255)).save(buf, "PNG")
    data = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
    res = app.action({"action": "logo_add", "label": "Czerwone", "height": 0.1, "opacity": 1, "data": data})
    assert res["ok"], res
    key = res["key"]
    assert any(l["key"] == key for l in app.state()["post"]["logos"])
    open_session(app)
    app.action({"action": "set_post", "key": "logo", "value": key})
    f = shoot_and_wait(app)
    assert app.shot_info("sesja testowa", f)["logoInfo"]["label"] == "Czerwone"
    # usuniecie wybranego logo przelacza na pierwsze z listy
    assert app.action({"action": "logo_delete", "key": key})["ok"]
    assert app.state()["post"]["logoChoice"] == next(iter(config.LOGOS))
    assert app.action({"action": "logo_add", "label": "zle", "data": "data:image/png;base64,AAAA"})["ok"] is False


def test_session_edit_changes_logo_on_many_photos(app):
    sdir = open_session(app)
    files = [shoot_and_wait(app) for _ in range(3)]
    # zdjecie bez wersji bez logo i bez oryginalu nie da sie edytowac — pomijane
    (sdir / ".nologo" / files[2]).unlink()
    for raw in (sdir / "raw").glob(f"{Path(files[2]).stem}_raw.jpg"):
        raw.unlink()
    res = app.action({"action": "edit_batch", "files": files, "logo": "kids", "position": "top-left"})
    assert res["ok"] and res["queued"] == 2 and res["skipped"] == 1, res
    assert app.action({"action": "edit_batch", "files": files, "logo": "kids"})["ok"] is False, \
        "druga edycja sesji nie startuje, zanim pierwsza sie skonczy"
    wait_for(lambda: app.state()["batchEdit"] is None, 30, "koniec edycji sesji")
    for f in files[:2]:
        assert app.shot_info("sesja testowa", f)["logoInfo"] == {"label": "TRIXBRIX.eu KIDS", "pos": "top-left"}
    assert app.shot_info("sesja testowa", files[2])["logoInfo"]["pos"] == "bottom-right", "pominiete bez zmian"
    assert any("Edycja sesji: 2 zdjęcia" in t for t in log_texts(app))
    assert app.action({"action": "edit_batch", "files": [files[2]], "logo": "kids"})["ok"] is False


def test_session_menu_reveals_session_folder(app, monkeypatch):
    from src import webui
    opened = []
    monkeypatch.setattr(webui, "_open_folder", opened.append)
    assert app.action({"action": "reveal_session"})["ok"] is False      # bez sesji
    sdir = open_session(app)
    assert not sdir.exists() or not any(sdir.iterdir())
    assert app.action({"action": "reveal_session"})["ok"], "sesja bez zdjec: pusty folder zalozony i otwarty"
    assert sdir.is_dir() and opened == [sdir]


def test_edit_refuses_unknown_logo_and_position(app):
    open_session(app)
    assert app.action({"action": "edit_save", "file": "x.jpg", "logo": "inne"})["error"] == "nieznane logo"
    assert app.action({"action": "edit_save", "file": "x.jpg", "logo": "kids",
                       "position": "srodek"})["error"] == "nieznana pozycja"


# ---------- ustawienia ----------

def test_settings_are_saved_to_env(app, env_store):
    app.action({"action": "set_app", "key": "ui_theme", "value": "dark"})
    app.action({"action": "set_app", "key": "preview_fps", "value": 99})
    app.action({"action": "set_post", "key": "logo", "value": "trixbrix"})
    st = app.state()
    assert st["settings"]["uiTheme"] == "dark"
    assert st["settings"]["previewFps"] == 30, "FPS podgladu przyciety do 1–30"
    assert st["post"]["logoChoice"] == "trixbrix"
    assert env_store == {"UI_THEME": "dark", "PREVIEW_FPS": "30", "LOGO": "trixbrix"}


def test_unknown_theme_is_ignored(app, env_store):
    app.action({"action": "set_app", "key": "ui_theme", "value": "fioletowy"})
    assert app.state()["settings"]["uiTheme"] == "light"
    assert "UI_THEME" not in env_store


def test_toggles_and_logo_position(app):
    app.action({"action": "toggle", "key": "zoom", "value": False})
    app.action({"action": "set_post", "key": "logo_position", "value": "top-left"})
    app.action({"action": "set_post", "key": "logo_position", "value": "srodek"})
    post = app.state()["post"]
    assert post["zoom"] is False and post["logoPosition"] == "top-left"


def test_unknown_action(app):
    assert app.action({"action": "robot_pose"}) == {"ok": False, "error": "nieznana akcja 'robot_pose'"}


# ---------- serwer ----------

def test_server_requires_token(app):
    base = app.url.split("?")[0]
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(base + "api/state")
    assert e.value.code == 403
    with urllib.request.urlopen(f"{base}api/state?t={app.token}") as r:
        assert json.load(r)["connected"] is True


def test_api_favicon_is_fetched_once_and_cached(app, monkeypatch):
    from src import webui
    calls = []
    monkeypatch.setattr(webui, "_fetch_favicon", lambda base: calls.append(base) or (b"ico", "image/png"))
    app.automat_url = "https://api.example.com/"
    assert app.api_favicon() == (b"ico", "image/png")
    assert app.api_favicon() == (b"ico", "image/png")
    assert calls == ["https://api.example.com"], "drugie wejście w Ustawienia nie puka do serwera"


def test_api_favicon_needs_http_address(app, monkeypatch):
    from src import webui
    monkeypatch.setattr(webui, "_fetch_favicon", lambda base: pytest.fail("nie powinno pobierać"))
    app.automat_url = "automat.local"
    assert app.api_favicon() is None


def test_raw_retention_setting_is_saved_and_purges(app, env_store, monkeypatch):
    from src import webui
    calls = []
    monkeypatch.setattr(webui, "purge_originals", lambda base, days: calls.append(days) or 0)
    app.action({"action": "set_app", "key": "raw_retention_days", "value": 30})
    assert app.state()["settings"]["rawRetentionDays"] == 30
    assert env_store["RAW_RETENTION_DAYS"] == "30"
    wait_for(lambda: 30 in calls, 10, "kasowanie starych oryginałów po zmianie")
    app.action({"action": "set_app", "key": "raw_retention_days", "value": 13})
    assert app.state()["settings"]["rawRetentionDays"] == 30, "tylko 7/30/90/0"


def test_static_serves_stylesheets_but_nothing_outside(app):
    """Manifest stylów i każdy importowany plik są dostępne; ścieżka
    wychodząca poza webui_static to 404, a nie plik z dysku."""
    import re as _re
    base = app.url.split("?")[0]
    with urllib.request.urlopen(f"{base}static/assets/stylesheets/application.css?t={app.token}") as r:
        manifest = r.read().decode()
    imports = _re.findall(r'@import url\("([^"]+)"\)', manifest)
    assert len(imports) >= 10
    for imp in imports:
        with urllib.request.urlopen(f"{base}static/assets/stylesheets/{imp}?t={app.token}") as r:
            assert r.headers["Content-Type"].startswith("text/css")
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(f"{base}static/assets/../../webui.py?t={app.token}")
    assert e.value.code == 404
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(f"{base}static/%2e%2e/%2e%2e/version.py?t={app.token}")
    assert e.value.code == 404
