"""Tlumaczenia komunikatow backendu (PL / EN) — log, bledy dla frontu, tekst
przycisku migawki. Kluczem jest POLSKI szablon z kodu, wiec brak tlumaczenia
zostawia polski tekst zamiast go gubic:

    self._log(tr("Pobrano {n} {word} z API do {name}.", n=ok, word=..., name=name))

Kazdy modul dopisuje swoje teksty do EN (EN.update({...})) obok kodu, ktory
ich uzywa. Jezyk ustawia webui z UI_LANG (.env, Ustawienia → Jezyk); proces
EDSDK dziedziczy go przez zmienna srodowiskowa UI_LANG."""

import os

EN: dict[str, str] = {}
LANG = "en" if os.environ.get("UI_LANG", "pl").strip().lower() == "en" else "pl"


def set_lang(lang: str) -> None:
    global LANG
    LANG = "en" if lang == "en" else "pl"
    # proces-dziecko EDSDK startuje z tym srodowiskiem (patrz camera_proc)
    os.environ["UI_LANG"] = LANG


def tr(pl: str, **kw) -> str:
    """Tekst w biezacym jezyku; `kw` wstawiane w {nazwy} szablonu."""
    s = EN.get(pl, pl) if LANG == "en" else pl
    return s.format(**kw) if kw else s


def n_form(n: int, pl: tuple[str, str, str], en: tuple[str, str]) -> str:
    """Rzeczownik po liczbie: 1 zdjecie / 2 zdjecia / 5 zdjec — 1 photo / 2 photos."""
    if LANG == "en":
        return en[0] if n == 1 else en[1]
    if n == 1:
        return pl[0]
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return pl[1]
    return pl[2]
