"""Wspolne narzedzia nazewnictwa — bez zaleznosci od TUI (termios jest
unix-only, wiec webui/gui na Windowsie nie moga importowac src.tui)."""

import re


def sanitize_name(name: str) -> str:
    name = name.strip()
    name = re.sub(r"[^A-Za-z0-9_\-. ]+", "_", name)
    return name.strip(" .") or "default"
