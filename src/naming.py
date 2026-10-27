"""Wspolne narzedzia nazewnictwa plikow i sesji."""

import re


def sanitize_name(name: str) -> str:
    name = name.strip()
    name = re.sub(r"[^A-Za-z0-9_\-. ]+", "_", name)
    return name.strip(" .") or "default"
