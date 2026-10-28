"""Postęp zdjęcia od migawki do pliku: src/progress.py, etapy w aplikacji
i kafelek z procentem w pasku zdjęć."""

import time

from playwright.sync_api import Page, expect

from conftest import shoot_and_wait, wait_for


def test_stages_follow_the_settings():
    from src.progress import stages_for
    assert stages_for(True, True, True) == [
        "camera", "queue", "announce", "rembg", "mask", "crop", "compose", "logo", "save"]
    assert stages_for(True, False, False) == [
        "camera", "queue", "rembg", "mask", "crop", "compose", "save"]
    assert stages_for(False, True, False) == ["camera", "queue", "crop", "logo", "save"]


def test_progress_moves_forward_and_learns_this_computer(tmp_path, monkeypatch):
    from src import progress as pm
    store = tmp_path / ".stages.json"
    p = pm.PhotoProgress(lambda: store)
    clock = [100.0]
    monkeypatch.setattr(pm.time, "monotonic", lambda: clock[0])
    p.start("a.jpg", pm.stages_for(True, True, False))
    snap = p.snapshot()[0]
    assert snap["file"] == "a.jpg" and snap["index"] == 0
    assert snap["stages"][0] == ["camera", pm.STAGES["camera"]]
    clock[0] += 4.0
    p.stage("a.jpg", "queue")
    p.stage("a.jpg", "rembg")
    p.stage("a.jpg", "camera")          # wstecz — bez zmian
    p.stage("a.jpg", "nieznany")        # spoza listy — bez zmian
    assert p.snapshot()[0]["index"] == 2
    clock[0] += 3.0
    p.stage("a.jpg", "save")            # pominięte etapy liczą się jako zrobione
    assert p.snapshot()[0]["index"] == 7
    assert p.snapshot()[0]["agoMs"] == 0
    clock[0] += 1.0
    p.finish("a.jpg")
    assert p.snapshot() == []
    # aparat trwał 4 s zamiast 2 s, wycinanie 3 s zamiast 1,5 s: szacunek
    # idzie w tę stronę (średnia krocząca), kolejka się nie uczy
    learned = pm.PhotoProgress(lambda: store)._estimates()
    assert pm.STAGES["camera"] < learned["camera"] < 4.0
    assert pm.STAGES["rembg"] < learned["rembg"] < 3.0
    assert learned["queue"] == 0.0


def test_failed_photo_does_not_teach_estimates(tmp_path):
    from src import progress as pm
    store = tmp_path / ".stages.json"
    p = pm.PhotoProgress(lambda: store)
    p.start("a.jpg", ["camera", "save"])
    p.finish("a.jpg", ok=False)
    assert p.snapshot() == [] and not store.exists()


def test_broken_estimates_file_falls_back_to_defaults(tmp_path):
    from src import progress as pm
    store = tmp_path / ".stages.json"
    store.write_text("{zepsuty", encoding="utf-8")
    assert pm.PhotoProgress(lambda: store)._estimates() == pm.STAGES
    store.write_text('{"rembg": -1, "queue": 9, "inny": 3}', encoding="utf-8")
    assert pm.PhotoProgress(lambda: store)._estimates() == pm.STAGES


def slow_process(monkeypatch, seen=None, pause=0.35):
    """Prawdziwa obróbka, ale z przerwą na każdym etapie — żeby test zdążył
    zobaczyć kafelek w trakcie."""
    from src import webui
    real = webui.process

    def process(*a, on_stage=None, **kw):
        for key in ("rembg", "mask", "crop", "compose", "logo", "save"):
            on_stage(key)
            if seen is not None:
                seen.append(key)
            time.sleep(pause)
        return real(*a, **kw)
    monkeypatch.setattr(webui, "process", process)


def test_photo_reports_every_stage_until_saved(app, monkeypatch):
    from src import webui
    monkeypatch.setattr(webui, "WARMUP_FILE", app.base_output.parent / ".warmup.json")
    seen_index = []
    app.action({"action": "set_session", "name": "postep"})
    slow_process(monkeypatch, pause=0.25)
    res = app.action({"action": "shoot"})
    assert res["ok"]

    def watch():
        prog = app.state()["progress"]
        if prog:
            seen_index.append(prog[0]["index"])
            assert [s[0] for s in prog[0]["stages"]][:2] == ["camera", "queue"]
        return not prog and app.state()["shots"]
    wait_for(watch, 60, "zdjęcie zapisane")
    assert seen_index == sorted(seen_index), "etap cofnął się"
    assert len(set(seen_index)) >= 3
    assert app.state()["processing"] is None
    assert (app.base_output.parent / ".stages.json").is_file()


def test_tile_shows_percent_and_stage_and_goes_away(app, page: Page, monkeypatch):
    slow_process(monkeypatch, pause=0.5)
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(app.url, wait_until="domcontentloaded")
    field = page.locator("#new-session-input")
    field.fill("kafelek")
    field.press("Enter")
    expect(page.locator("#shoot-label")).to_be_visible()
    page.keyboard.press("Enter")
    tile = page.locator("#filmstrip .proc")
    expect(tile).to_be_visible(timeout=10000)
    expect(tile.locator(".proc-head")).to_contain_text("Obróbka")
    stages = set()
    pcts = []
    for _ in range(30):
        if not tile.count():
            break
        try:
            stages.add(tile.locator(".proc-stage").get_attribute("data-stage", timeout=500))
            pcts.append(int(tile.locator(".proc-pct").inner_text(timeout=500).rstrip("%")))
        except Exception:
            break
        page.wait_for_timeout(150)
    assert pcts == sorted(pcts), f"procent się cofnął: {pcts}"
    assert pcts[-1] > pcts[0]
    assert {"rembg", "compose"} & stages, stages
    expect(tile).to_have_count(0, timeout=30000)
    expect(page.locator("#filmstrip [data-shot]")).to_have_count(1)
