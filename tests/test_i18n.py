"""Język interfejsu: PL domyślnie, EN po przełączeniu — bez polskich napisów."""

import re

import pytest
from playwright.sync_api import Page, expect

from conftest import log_texts, shoot_and_wait, wait_for
from src import i18n

PL_CHARS = re.compile(r"[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]")


@pytest.fixture(autouse=True)
def back_to_polish():
    yield
    i18n.set_lang("pl")


def polish_leftovers(page: Page) -> list[str]:
    """Widoczne linie tekstu z polskimi znakami, poza logiem (wpisy sprzed
    przełączenia zostają w starym języku) i danymi użytkownika."""
    text = page.evaluate("""() => {
        const skip = el => el.closest('.log-panel, .statusbar-line, .author, [data-user-text]');
        const out = [];
        const walk = document.createTreeWalker(document.getElementById('app'), NodeFilter.SHOW_TEXT);
        while (walk.nextNode()) {
            const n = walk.currentNode, el = n.parentElement;
            if (!el || skip(el) || !n.textContent.trim()) continue;
            const r = el.getBoundingClientRect(), cs = getComputedStyle(el);
            if (!r.width || !r.height || cs.visibility === 'hidden') continue;
            out.push(n.textContent.trim());
        }
        document.querySelectorAll('#app [title], #app [aria-label], #app [placeholder]').forEach(el => {
            if (skip(el)) return;
            ['title', 'aria-label', 'placeholder'].forEach(a => el.getAttribute(a) && out.push(el.getAttribute(a)));
        });
        return out;
    }""")
    return sorted({line for line in text if PL_CHARS.search(line)})


def test_tr_and_plurals():
    i18n.EN["Zapisano {f}"] = "Saved {f}"
    i18n.set_lang("pl")
    assert i18n.tr("Zapisano {f}", f="a.jpg") == "Zapisano a.jpg"
    assert i18n.n_form(5, ("zdjęcie", "zdjęcia", "zdjęć"), ("photo", "photos")) == "zdjęć"
    assert i18n.n_form(22, ("zdjęcie", "zdjęcia", "zdjęć"), ("photo", "photos")) == "zdjęcia"
    i18n.set_lang("en")
    assert i18n.tr("Zapisano {f}", f="a.jpg") == "Saved a.jpg"
    assert i18n.tr("Brak tłumaczenia {x}", x=1) == "Brak tłumaczenia 1", "brak tłumaczenia = polski tekst"
    assert i18n.n_form(1, ("zdjęcie", "zdjęcia", "zdjęć"), ("photo", "photos")) == "photo"
    assert i18n.n_form(5, ("zdjęcie", "zdjęcia", "zdjęć"), ("photo", "photos")) == "photos"


def test_language_is_saved_and_switches_backend_messages(app, env_store):
    app.action({"action": "set_app", "key": "ui_lang", "value": "en"})
    assert app.state()["settings"]["uiLang"] == "en"
    assert env_store["UI_LANG"] == "en"
    assert app.action({"action": "shoot"})["error"] != "najpierw ustaw nazwę sesji", \
        "błąd migawki po angielsku"
    app.action({"action": "set_app", "key": "ui_lang", "value": "de"})
    assert app.state()["settings"]["uiLang"] == "en", "tylko pl / en"


@pytest.mark.ui
def test_english_ui_has_no_polish_text(app, page: Page):
    page.set_viewport_size({"width": 1440, "height": 900})
    page.goto(app.url, wait_until="domcontentloaded")
    page.locator("#new-session-input").fill("switch test")
    page.locator("#new-session-input").press("Enter")
    expect(page.locator("#shoot-label")).to_be_visible()
    page.keyboard.press("Enter")
    wait_for(lambda: app.state()["session"]["count"] == 1 and not app.state()["busy"], 120, "zdjecie")
    # strona dowiaduje się o końcu obróbki z pollu (co 0,5 s) — do tego czasu
    # przycisk migawki pokazuje tekst fazy nadany przez backend jeszcze po polsku
    expect(page.locator("#shoot-label")).to_have_text("Zrób zdjęcie", timeout=10000)

    page.evaluate("setLang('en')")
    wait_for(lambda: app.state()["settings"]["uiLang"] == "en", 5, "język zapisany")
    page.wait_for_timeout(800)
    expect(page.locator("html")).to_have_attribute("lang", "en")
    leftovers = {"sesja": polish_leftovers(page)}

    page.keyboard.press(" ")
    expect(page.locator("#review-img")).to_be_visible()
    page.keyboard.press("e")
    expect(page.locator("#edit-panel")).to_be_visible()
    page.wait_for_timeout(500)
    leftovers["podgląd i edycja"] = polish_leftovers(page)
    page.keyboard.press("Escape")          # zamyka edycję
    expect(page.locator("#edit-panel")).to_be_hidden()
    page.keyboard.press("Escape")          # zamyka podgląd (animacja ~180 ms)
    expect(page.locator("#review-wrap")).to_have_count(0)
    page.keyboard.press("Escape")          # pyta o wyjście z sesji
    expect(page.locator("#leave-confirm")).to_be_visible()
    leftovers["okno wyjścia"] = polish_leftovers(page) + [
        line for line in [page.locator("#leave-confirm").inner_text()] if PL_CHARS.search(line)]
    page.keyboard.press("Enter")
    expect(page.locator("#new-session-input")).to_be_visible()
    page.wait_for_timeout(500)
    leftovers["lista sesji"] = polish_leftovers(page)

    page.locator("#tab-ustawienia").click()
    page.wait_for_timeout(800)
    leftovers["ustawienia"] = polish_leftovers(page)

    assert {k: v for k, v in leftovers.items() if v} == {}, "polskie napisy w angielskim interfejsie"
    assert any("Saved" in t or "Zapisano" in t for t in log_texts(app))
