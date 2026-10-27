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
