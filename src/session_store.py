"""Magazyn sesji na dysku (photos/<sesja>) — helpery wydzielone z webui.py:
stan recenzji (.review.json), lista finalnych JPEG-ow, kosz (photos/.trash),
okladki ekranu startowego (photos/.covers) i mapowanie zdalnych nazw na
lokalne pliki. Czysta warstwa plikowa — zero HTTP i zero stanu WebUI."""

import json
import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image

from .config import TRASH_RETENTION_DAYS

TRASH_DIR = ".trash"        # photos/.trash/<data>-<godzina>_<sesja>/
TRASH_STAMP = "%Y%m%d-%H%M%S"
COVERS_DIR = ".covers"      # photos/.covers/<id sesji>.jpg — okladki ekranu startowego
COVER_SIZE = 420


# ---------- stan recenzji (.review.json) ----------


def review_path(session_dir: Path) -> Path:
    return session_dir / ".review.json"


def load_review(session_dir: Path) -> dict:
    try:
        data = json.loads(review_path(session_dir).read_text())
    except (OSError, ValueError):
        data = {}
    data.setdefault("rejected", [])
    data.setdefault("uploaded", [])
    data.setdefault("meta", {})
    data.setdefault("automat", {})  # plik -> id zdjecia w Automacie (do DELETE)
    return data


def save_review(session_dir: Path, data: dict) -> None:
    # tmp + rename: review pisza dwa watki (worker i sync), a czyta m.in.
    # poll stanu — load w trakcie golego write_text widzialby uciety JSON,
    # load_review polknalby ValueError i oddal PUSTA recenzje
    session_dir.mkdir(parents=True, exist_ok=True)
    tmp = review_path(session_dir).with_suffix(".json.part")
    tmp.write_text(json.dumps(data, indent=1))
    os.replace(tmp, review_path(session_dir))


def finals(session_dir: Path) -> list[str]:
    if not session_dir.is_dir():
        return []
    return sorted(
        p.name for p in session_dir.glob("*.jpg") if not p.stem.endswith("_raw")
    )


def find_raw(session_dir: Path, final_name: str) -> Path | None:
    stem = Path(final_name).stem
    for cand in (session_dir / "raw" / f"{stem}_raw.jpg",
                 session_dir / f"{stem}_raw.jpg"):
        if cand.exists():
            return cand
    return None


def shot_entries(session_dir: Path | None, review: dict) -> list[dict]:
    """Wpisy zdjec dla frontu (filmstrip sesji)."""
    return [
        {
            "file": f,
            "status": "rejected" if f in review["rejected"] else "ok",
            "uploaded": f in review["uploaded"],
        }
        for f in (finals(session_dir) if session_dir else [])
    ]


def remote_filename(photo: dict) -> str:
    """Nazwa pliku dla zdjecia z Automatu — sam basename (zdalna nazwa nie moze
    uciec z katalogu sesji), a przy jej braku `photo_<id>.jpg`."""
    fname = Path(str(photo.get("filename") or "").strip()).name
    if not fname.lower().endswith(".jpg") or fname.startswith("."):
        fname = f"photo_{photo['id']}.jpg"
    return fname


# ---------- kosz (photos/.trash) ----------


def trash_batch(base_output: Path, session: str) -> Path:
    """Nowy katalog w koszu: `photos/.trash/<data>-<godzina>_<sesja>`.

    Data siedzi w NAZWIE, nie w mtime — mtime katalogu potrafi się zmienić
    (kopiowanie/synchronizacja `photos/`) i kosz czyściłby się losowo."""
    root = base_output / TRASH_DIR
    stamp = datetime.now().strftime(TRASH_STAMP)
    for n in range(1000):
        cand = root / (f"{stamp}_{session}" + (f"-{n}" if n else ""))
        if not cand.exists():
            cand.mkdir(parents=True)
            return cand
    raise RuntimeError("kosz: nie mogę założyć katalogu na usunięte pliki")


def move_into(batch: Path, path: Path) -> None:
    target = batch / path.name
    n = 1
    while target.exists():
        target = batch / f"{path.stem}-{n}{path.suffix}"
        n += 1
    shutil.move(str(path), str(target))


def purge_trash(base_output: Path, days: int = TRASH_RETENTION_DAYS) -> int:
    """Kasuje NAPRAWDĘ wpisy kosza starsze niż `days` dni. Zwraca ile poszło."""
    root = base_output / TRASH_DIR
    if days <= 0 or not root.is_dir():
        return 0
    cutoff = datetime.now() - timedelta(days=days)
    removed = 0
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        try:
            when = datetime.strptime(entry.name.split("_", 1)[0], TRASH_STAMP)
        except ValueError:
            when = datetime.fromtimestamp(entry.stat().st_mtime)
        if when < cutoff:
            shutil.rmtree(entry, ignore_errors=True)
            removed += 1
    return removed


# ---------- okladki sesji (photos/.covers) ----------


def cover_path(base_output: Path, session_id: int) -> Path:
    return base_output / COVERS_DIR / f"{int(session_id)}.jpg"


def make_cover(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    img = Image.open(src)
    img.thumbnail((COVER_SIZE, COVER_SIZE))
    img.convert("RGB").save(dest, "JPEG", quality=82)
