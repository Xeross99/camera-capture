"""Interfejs w prawdziwej przegladarce (Playwright, Chromium) na atrapie
aparatu — to samo, co operator robi klawiatura i mysza."""

import re

import pytest
from playwright.sync_api import Page, expect

from conftest import wait_for

pytestmark = pytest.mark.ui


@pytest.fixture
def ui(app, page: Page):
    """Okno aplikacji: strona z serwera WebUI, bledy JS zbierane do listy."""
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: m.type == "error" and errors.append(m.text))
    page.set_viewport_size({"width": 1440, "height": 900})
    # /stream (MJPEG) nigdy sie nie konczy — nie czekamy na „load"
    page.goto(app.url, wait_until="domcontentloaded")
    page.ui_errors = errors
    yield page
    assert errors == [], f"bledy w konsoli przegladarki: {errors}"


def start_session(page: Page, name="zwrotnica test"):
    field = page.locator("#new-session-input")
    field.fill(name)
    field.press("Enter")
    expect(page.locator("#shoot-label")).to_be_visible()


def test_new_session_and_enter_takes_photo(app, ui, camera):
    start_session(ui)
    assert app.state()["session"]["name"] == "zwrotnica test"
    ui.locator("body").press("Enter")
    wait_for(lambda: app.state()["session"]["count"] == 1 and not app.state()["busy"], 120, "zdjecie")
    assert camera.captures == 1
    expect(ui.locator("#shoot-label")).to_have_text("Zrób zdjęcie")


def test_space_opens_photo_and_escape_returns(app, ui):
    start_session(ui)
    ui.keyboard.press("Enter")
    wait_for(lambda: app.state()["session"]["count"] == 1 and not app.state()["busy"], 120, "zdjecie")
    ui.wait_for_timeout(700)   # poll stanu odswieza pasek zdjec
    ui.keyboard.press(" ")
    expect(ui.locator("#review-wrap")).to_be_visible()
    expect(ui.locator("#review-img")).to_be_visible()
    ui.keyboard.press("e")
    expect(ui.locator("#edit-panel")).to_be_visible()
    ui.keyboard.press("Escape")
    expect(ui.locator("#edit-panel")).to_be_hidden()
    ui.keyboard.press("Escape")
    expect(ui.locator("#review-wrap")).to_have_count(0)


def test_o_in_preview_puts_photo_over_live_view(app, ui):
    start_session(ui)
    ui.keyboard.press("Enter")
    wait_for(lambda: app.state()["session"]["count"] == 1 and not app.state()["busy"], 120, "zdjecie")
    ui.wait_for_timeout(700)
    ui.keyboard.press(" ")
    expect(ui.locator("#review-img")).to_be_visible()
    ui.keyboard.press("o")
    expect(ui.locator("#review-wrap")).to_have_count(0)
    ghost = ui.locator("#ghost")
    expect(ghost).to_be_visible()
    expect(ghost).to_have_attribute("src", re.compile(r"ghost=1"))
    expect(ui.locator(".ghost-fly")).to_have_count(0)
    ui.wait_for_function("getComputedStyle(document.getElementById('ghost')).opacity === '0.4'")
    ui.locator(".session-side .side-card").nth(1).screenshot(path="/private/tmp/claude-501/-Users-xeross-Desktop-camera-capture/b4dc7c83-3263-4a48-96b0-c364b2a3c006/scratchpad/ghost.png")
    ui.keyboard.press("o")
    expect(ghost).to_be_hidden()


def test_ev_pill_steps_and_meter_follows(app, ui, camera):
    start_session(ui)
    expect(ui.locator("#ev-value")).to_have_text("±0")
    ui.get_by_role("button", name="Jaśniej").click()
    wait_for(lambda: camera.ev == "+1/3", 10, "EV o krok w gore")
    expect(ui.locator("#ev-value")).to_have_text("+1/3")
    width = ui.eval_on_selector("#ev-meter-fill", "e => parseFloat(e.style.width)")
    assert width > 0, "pasek odchylki od zera"
    ui.locator(".ev-row").screenshot(path="/private/tmp/claude-501/-Users-xeross-Desktop-camera-capture/b4dc7c83-3263-4a48-96b0-c364b2a3c006/scratchpad/ev.png")


def test_logo_tiles_and_corner_pill(app, ui):
    start_session(ui)
    ui.get_by_role("radio", name="Bez logo").first.click()
    wait_for(lambda: app.add_logo is False, 10, "logo wylaczone")
    expect(ui.locator("#logo-corner")).to_have_css("pointer-events", "none")
    ui.locator('[data-logo="kids"]').click()
    wait_for(lambda: app.add_logo is True and app.state()["post"]["logoChoice"] == "kids", 10, "logo KIDS")
    ui.locator('[data-corner="top-left"]').click()
    wait_for(lambda: app.logo_position == "top-left", 10, "rog")
    pill = ui.locator("#logo-corner-seg .seg-pill")
    btn = ui.locator('[data-corner="top-left"]')
    ui.wait_for_timeout(450)   # przejazd tla .32 s
    assert abs(pill.bounding_box()["x"] - btn.bounding_box()["x"]) < 1
    ui.locator(".session-side .side-card").last.screenshot(path="/private/tmp/claude-501/-Users-xeross-Desktop-camera-capture/b4dc7c83-3263-4a48-96b0-c364b2a3c006/scratchpad/logo.png")


def test_align_correction_is_animated_on_live_view(app, ui):
    start_session(ui)
    ui.keyboard.press("Enter")
    wait_for(lambda: app.state()["session"]["count"] == 1 and not app.state()["busy"], 120, "zdjecie")
    ui.wait_for_function("S.state.shots.length === 1")
    ui.keyboard.press("o")
    anim = ui.locator("#align-anim")
    ui.evaluate("""() => playAlignAnim(S.state, {...S.state.shots[0],
        aligned: {fx: 0.02, fy: -0.01, ox: 0.5, oy: 0.5, scale: 1.03}})""")
    expect(anim).to_be_visible()
    expect(anim).to_be_hidden(timeout=4000)


def test_overlay_stays_on_its_photo_after_next_shot(app, ui):
    start_session(ui)
    ui.keyboard.press("Enter")
    wait_for(lambda: app.state()["session"]["count"] == 1 and not app.state()["busy"], 120, "zdjecie")
    ui.wait_for_function("S.state.shots.length === 1")
    ui.keyboard.press("o")
    ghost = ui.locator("#ghost")
    expect(ghost).to_be_visible()
    first = ghost.get_attribute("src")
    ui.keyboard.press("Enter")
    wait_for(lambda: app.state()["session"]["count"] == 2 and not app.state()["busy"], 120, "drugie zdjecie")
    ui.wait_for_function("S.state.shots.length === 2")
    ui.wait_for_timeout(700)
    assert ghost.get_attribute("src") == first, "nakladka zostaje na swoim zdjeciu"


def test_overlay_shows_live_alignment_guide(app, ui):
    start_session(ui)
    ui.keyboard.press("Enter")
    wait_for(lambda: app.state()["session"]["count"] == 1 and not app.state()["busy"], 120, "zdjecie")
    ui.wait_for_function("S.state.shots.length === 1 && !!S.state.shots[0].box")
    ui.keyboard.press("o")
    guide = ui.locator("#align-guide")
    expect(guide).to_be_visible()
    expect(ui.locator("#align-guide-label")).to_have_text(re.compile("korekta|za daleko"))
    ui.locator("#live").locator("..").screenshot(path="/private/tmp/claude-501/-Users-xeross-Desktop-camera-capture/b4dc7c83-3263-4a48-96b0-c364b2a3c006/scratchpad/guide.png")


def test_backspace_in_preview_deletes_photo(app, ui):
    start_session(ui)
    ui.keyboard.press("Enter")
    wait_for(lambda: app.state()["session"]["count"] == 1 and not app.state()["busy"], 120, "zdjecie")
    ui.wait_for_timeout(700)
    ui.keyboard.press(" ")
    expect(ui.locator("#review-img")).to_be_visible()
    ui.keyboard.press("Backspace")
    wait_for(lambda: app.state()["session"]["count"] == 0, 10, "zdjecie skasowane")


def test_escape_asks_before_leaving_session(app, ui):
    start_session(ui)
    ui.keyboard.press("Escape")
    expect(ui.locator("#leave-confirm")).to_be_visible()
    ui.keyboard.press("Enter")            # przy otwartym modalu ENTER = wyjdz, nie zdjecie
    wait_for(lambda: app.state()["session"]["name"] == "", 5, "wyjscie z sesji")
    expect(ui.locator("#new-session-input")).to_be_visible()


def test_escape_twice_cancels_leaving(app, ui, camera):
    start_session(ui)
    ui.keyboard.press("Escape")
    expect(ui.locator("#leave-confirm")).to_be_visible()
    ui.keyboard.press("Escape")
    expect(ui.locator("#leave-confirm")).to_have_count(0)
    assert app.state()["session"]["name"] == "zwrotnica test"
    assert camera.captures == 0


def test_click_on_live_view_focuses_there(app, ui, camera):
    start_session(ui)
    live = ui.locator("#live")
    expect(live).to_be_visible()
    box = live.bounding_box()
    live.click(position={"x": box["width"] / 2, "y": box["height"] / 2})
    wait_for(lambda: camera.focus_calls, 5, "ostrzenie w punkcie")
    fx, fy = camera.focus_calls[0]
    assert 0 <= fx <= 1 and 0 <= fy <= 1
    expect(ui.locator("#af-box")).to_be_visible()


def test_settings_tab_has_no_robot(ui):
    ui.locator("#tab-ustawienia").click()
    expect(ui.locator("#sec-aktualizacje")).to_be_visible()
    for sec in ("automat", "pliki", "obrobka", "skroty"):
        expect(ui.locator(f"#sec-{sec}")).to_be_attached()
    expect(ui.get_by_text(re.compile("Robot"))).to_have_count(0)


def test_theme_toggle_switches_and_is_saved(app, ui, env_store):
    html = ui.locator("html")
    expect(html).to_have_attribute("data-theme", "light")
    ui.locator("#theme-toggle").click()
    expect(html).to_have_attribute("data-theme", "dark")
    wait_for(lambda: env_store.get("UI_THEME") == "dark", 5, "motyw zapisany w .env")


def test_missing_edsdk_shows_driver_card(make_app, page: Page, monkeypatch):
    from src import webui
    monkeypatch.setattr(webui, "_edsdk_missing", lambda: True)
    app = make_app()
    page.goto(app.url, wait_until="domcontentloaded")
    start_session(page)
    expect(page.get_by_text("Brak sterownika aparatu Canon")).to_be_visible()


def test_new_photo_does_not_rebuild_session_screen(app, make_app, page: Page, monkeypatch):
    """Nowe zdjęcie (strzał albo dociągnięte z API) łata pasek i licznik, ale
    nie przebudowuje ekranu: karta na podglądzie (tu: brak SDK) zostaje tym
    samym elementem i nie odgrywa drugi raz animacji wejścia."""
    from src import webui
    monkeypatch.setattr(webui, "_edsdk_missing", lambda: True)
    page.goto(app.url, wait_until="domcontentloaded")
    start_session(page)
    expect(page.locator(".live-empty.sdk")).to_be_visible()
    page.wait_for_timeout(600)   # animacja wejścia (.45 s) już się skończyła
    page.evaluate("document.querySelector('.live-empty.sdk').dataset.marker = '1'")
    page.keyboard.press("Enter")
    wait_for(lambda: app.state()["session"]["count"] == 1 and not app.state()["busy"], 120, "zdjecie")
    expect(page.locator("#filmstrip [data-shot]")).to_have_count(1)
    expect(page.locator("#sess-count")).to_have_text("1 zdjęcie")
    assert page.evaluate("document.querySelector('.live-empty.sdk').dataset.marker") == "1", \
        "ekran sesji przebudował się po nowym zdjęciu"
    running = page.evaluate("""document.querySelector('.live-empty.sdk').getAnimations()
        .filter(a => a.animationName === 'liveEmptyIn' && a.playState === 'running').length""")
    assert running == 0, "animacja wejścia karty odpaliła się drugi raz"


def test_ctrl_k_opens_session_search_everywhere(app, ui):
    """⌘K / Ctrl+K otwiera wyszukiwarkę z każdego ekranu; wpisana nazwa bez
    pasującej sesji daje „Nowa sesja”, ENTER ją zakłada, ESC zamyka okno."""
    ui.locator("#tab-ustawienia").click()
    ui.keyboard.press("Control+k")
    expect(ui.locator("#palette")).to_be_visible()
    expect(ui.locator("#pal-input")).to_be_focused()
    ui.keyboard.press("Escape")
    expect(ui.locator("#palette")).to_have_count(0)
    ui.keyboard.press("Control+k")
    ui.locator("#pal-input").fill("paleta test")
    expect(ui.locator("#pal-results .pal-item")).to_have_count(1)
    ui.keyboard.press("Enter")
    expect(ui.locator("#palette")).to_have_count(0)
    wait_for(lambda: app.state()["session"]["name"] == "paleta test", 5, "sesja z wyszukiwarki")
    expect(ui.locator("#shoot-label")).to_be_visible()
    # otwarta wyszukiwarka połyka ENTER — nie może zrobić zdjęcia zza okna
    ui.keyboard.press("Control+k")
    ui.keyboard.press("Enter")
    ui.wait_for_timeout(300)
    assert app.state()["session"]["count"] == 0
