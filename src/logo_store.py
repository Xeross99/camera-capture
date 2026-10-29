"""Edytor logo z Ustawien: dodawanie, zmiana i usuwanie logo z listy LOGOS.

Lista zapisuje sie w `logos.json` (config.LOGOS_FILE), wgrane pliki w `logos/`
obok niego — oba obok `.env`, wiec przezywaja aktualizacje. Logo wbudowane
(assets/logos z paczki) maja w pliku wpis „builtin:<nazwa>": da sie je
przemianowac, zmienic im rozmiar i krycie albo usunac z listy, ale ich plik
zostaje w paczce. LOGOS jest zmieniany W MIEJSCU — webui i image_processing
trzymaja referencje do tego samego slownika."""

import io
import json
import os
import re
import shutil
import time
from pathlib import Path

from PIL import Image

from . import config
from .config import LOGOS, logo_file
from .i18n import EN, tr

EN.update({
    "podaj nazwę logo": "enter a logo name",
    "nie znam takiego logo": "unknown logo",
    "to nie jest obraz (PNG, WEBP albo JPG)": "this is not an image (PNG, WEBP or JPG)",
    "dodaj plik z logo": "add a logo file",
    "plik jest za duży (max 10 MB)": "the file is too big (max 10 MB)",
    "logo o tej nazwie już jest": "a logo with this name already exists",
})

HEIGHT_RANGE = (0.02, 0.25)     # wysokosc logo / wysokosc kadru
OPACITY_RANGE = (0.1, 1.0)
MAX_BYTES = 10 * 1024 * 1024
MAX_SIDE = 2000                 # wieksze pliki zmniejszamy — logo i tak ma ≤25 % kadru


class LogoError(ValueError):
    pass


def _clamp(v, lo, hi) -> float:
    return round(min(max(float(v), lo), hi), 3)


def _save() -> None:
    items = [{"key": k, "label": v["label"], "file": v["ref"],
              "height": v["height"], "opacity": v["opacity"]} for k, v in LOGOS.items()]
    path = config.LOGOS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.part")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2))
    os.replace(tmp, path)


def _store_image(key: str, data: bytes) -> str:
    """Wgrany plik → PNG w logos/ (przezroczystosc zostaje). Nazwa z czasem,
    bo podmiana pliku ma dac nowy adres podgladu w UI."""
    if len(data) > MAX_BYTES:
        raise LogoError(tr("plik jest za duży (max 10 MB)"))
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception as e:      # noqa: BLE001 — PIL rzuca rozne typy
        raise LogoError(tr("to nie jest obraz (PNG, WEBP albo JPG)")) from e
    im = im.convert("RGBA")
    im.thumbnail((MAX_SIDE, MAX_SIDE))
    name = f"{key}-{int(time.time() * 1000)}.png"
    config.LOGOS_DIR.mkdir(parents=True, exist_ok=True)
    im.save(config.LOGOS_DIR / name, "PNG")
    return name


def _drop_file(ref: str) -> None:
    if not ref.startswith("builtin:"):
        logo_file(ref).unlink(missing_ok=True)


def _slug(label: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-") or "logo"
    key, n = base, 2
    while key in LOGOS:
        key, n = f"{base}-{n}", n + 1
    return key


def _label(label, key: str = "") -> str:
    """Nazwa wymagana i unikalna (bez rozrozniania wielkosci liter) — inaczej
    dwa logo o tej samej nazwie w wyborze i w panelu informacji."""
    label = str(label or "").strip()[:40]
    if not label:
        raise LogoError(tr("podaj nazwę logo"))
    if any(k != key and v["label"].casefold() == label.casefold() for k, v in LOGOS.items()):
        raise LogoError(tr("logo o tej nazwie już jest"))
    return label


def add_logo(label: str, data: bytes | None, height: float, opacity: float) -> str:
    label = _label(label)
    if not data:
        raise LogoError(tr("dodaj plik z logo"))
    key = _slug(label)
    ref = _store_image(key, data)
    LOGOS[key] = {"label": label, "file": logo_file(ref), "ref": ref,
                  "height": _clamp(height, *HEIGHT_RANGE), "opacity": _clamp(opacity, *OPACITY_RANGE)}
    _save()
    return key


def update_logo(key: str, label: str, height: float, opacity: float, data: bytes | None = None) -> None:
    spec = LOGOS.get(key)
    if spec is None:
        raise LogoError(tr("nie znam takiego logo"))
    label = _label(label, key)
    if data:
        ref = _store_image(key, data)
        _drop_file(spec["ref"])
        spec.update(ref=ref, file=logo_file(ref))
    spec.update(label=label, height=_clamp(height, *HEIGHT_RANGE), opacity=_clamp(opacity, *OPACITY_RANGE))
    _save()


def delete_logo(key: str) -> None:
    spec = LOGOS.pop(key, None)
    if spec is None:
        raise LogoError(tr("nie znam takiego logo"))
    _drop_file(spec["ref"])
    _save()


def migrate_builtin() -> dict:
    """Pierwsze uruchomienie z edytorem: logo, ktore dotad byly na sztywno
    w paczce (TRIXBRIX.eu, KIDS), staja sie zwyklymi pozycjami listy — pliki
    kopiowane do logos/, lista zapisana w logos.json z dotychczasowym
    rozmiarem i kryciem. Zwraca mape stara sciezka → nowa (wybrane logo
    w WebUI trzeba przepiac). Juz istniejacy logos.json = nic do zrobienia;
    katalog tylko do odczytu = zostaja wpisy „builtin:", jak dotad."""
    if config.LOGOS_FILE.exists():
        return {}
    moved = {}
    try:
        config.LOGOS_DIR.mkdir(parents=True, exist_ok=True)
        for key, spec in LOGOS.items():
            if not spec["ref"].startswith("builtin:"):
                continue
            ref = f"{key}{spec['file'].suffix}"
            shutil.copy2(spec["file"], config.LOGOS_DIR / ref)
            moved[spec["file"]] = logo_file(ref)
            spec.update(ref=ref, file=logo_file(ref))
        _save()
    except OSError:
        return {}
    return moved


def logo_version(spec: dict) -> int:
    """Wersja pliku do adresu podgladu (/logo?k=…&v=…)."""
    try:
        return int(Path(spec["file"]).stat().st_mtime)
    except OSError:
        return 0
