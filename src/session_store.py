"""Magazyn sesji na dysku (photos/<sesja>) — helpery wydzielone z webui.py:
stan recenzji (.review.json), lista finalnych JPEG-ow, kosz (photos/.trash),
okladki ekranu startowego (photos/.covers) i mapowanie zdalnych nazw na
lokalne pliki. Czysta warstwa plikowa — zero HTTP i zero stanu WebUI."""

import json
import os
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image

from .config import TRASH_RETENTION_DAYS
from .i18n import EN, tr

EN.update({
    "kosz: nie mogę założyć katalogu na usunięte pliki": "trash: cannot create a folder for deleted files",
})

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
    data.setdefault("frame", {})    # plik -> kadr z obrobki (dopasowanie do nakladki)
    data.setdefault("logo", {})     # plik -> {label, pos} — panel „Informacje" w podgladzie
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


NOLOGO_DIR = ".nologo"
GHOSTS_DIR = ".ghosts"   # zmniejszone oryginały do nakładki na live view
FRAMES_DIR = ".frames"   # odciski kształtu produktu (korekta obrotu do nakładki)


def save_frame(session_dir: Path, filename: str, review: dict, frame: dict) -> None:
    """Kadr zdjęcia do `review["frame"]`, a odcisk kształtu (obraz) obok,
    w `.frames/<plik>.png` — w JSON-ie byłby za ciężki dla każdego pollu."""
    frame = dict(frame)
    shape = frame.pop("shape", None)
    if shape is not None:
        (session_dir / FRAMES_DIR).mkdir(exist_ok=True)
        shape.save(session_dir / FRAMES_DIR / f"{filename}.png")
    review["frame"][filename] = frame


def load_frame(session_dir: Path, filename: str, review: dict) -> dict | None:
    """Kadr zdjęcia z nakładki razem z odciskiem kształtu (jeśli jest)."""
    frame = review["frame"].get(filename)
    if not frame:
        return None
    frame = dict(frame)
    path = session_dir / FRAMES_DIR / f"{filename}.png"
    if path.exists():
        with Image.open(path) as im:
            frame["shape"] = im.convert("L")
    return frame


def edit_base(session_dir: Path, final_name: str, review: dict) -> Path | None:
    """Zdjecie bez logo, na ktore edycja naklada logo od nowa: kopia z
    `.nologo/` (zapisywana przy obrobce od wersji z edycja) albo sam gotowy
    plik, gdy wiadomo, ze robiono go bez logo (meta w .review.json)."""
    cand = session_dir / NOLOGO_DIR / final_name
    if cand.exists():
        return cand
    meta = review.get("meta", {}).get(final_name)
    if meta is not None and "logo" not in meta.split(" · "):
        return session_dir / final_name
    return None


def _frame_box(frame: dict | None) -> list[float] | None:
    if not frame or not frame.get("bbox") or not frame.get("src"):
        return None
    (l, t, r, b), (w, h) = frame["bbox"], frame["src"]
    return [l / w, t / h, r / w, b / h]


def shot_entries(session_dir: Path | None, review: dict) -> list[dict]:
    """Wpisy zdjec dla frontu (filmstrip sesji). `v` (mtime) idzie w adres
    obrazka: adres zmienia sie tylko ze zmiana pliku, wiec przegladarka moze
    trzymac obrazek w cache na stale (patrz `_serve_img`)."""
    def version(f: str) -> int:
        try:
            return int((session_dir / f).stat().st_mtime)
        except OSError:
            return 0

    def dims(f: str) -> list[int]:
        # sam nagłówek JPEG-a (PIL nie dekoduje obrazu) — podgląd pokazuje
        # zmniejszoną wersję, więc prawdziwy rozmiar pliku musi przyjść stąd
        try:
            with Image.open(session_dir / f) as im:
                return list(im.size)
        except OSError:
            return [0, 0]

    return [
        {
            "file": f,
            "status": "rejected" if f in review["rejected"] else "ok",
            "uploaded": f in review["uploaded"],
            "v": version(f),
            "size": dims(f),
            # edycja logo: "ready" = jest wersja bez logo, "raw" = trzeba ja
            # najpierw zrobic z oryginalu z aparatu, "" = nie da sie
            "edit": ("ready" if edit_base(session_dir, f, review)
                     else "raw" if find_raw(session_dir, f) else ""),
            # nakładka na live view: "raw" = oryginał z aparatu (ten sam kadr
            # co podgląd), "final" = brak oryginału, nakładamy gotowe zdjęcie
            # — przycięte i przybliżone, więc pozycja tylko orientacyjna
            "ghost": "raw" if find_raw(session_dir, f) else "final",
            # kadr lekko dociągnięty do nakładki — front animuje korektę na live view
            "aligned": (review.get("frame", {}).get(f) or {}).get("aligned"),
            # obrys produktu jako ułamki kadru — live view pokazuje, czy korekta zadziała
            "box": _frame_box(review.get("frame", {}).get(f)),
        }
        for f in (finals(session_dir) if session_dir else [])
    ]


# ---------- metadane zdjecia (panel w podgladzie) ----------

_EXIF_IFD = 0x8769


def _shutter(t: float) -> str:
    if t >= 1:
        return f"{t:g} s"
    return f"1/{round(1 / t)} s"


def _ev_text(ev: float) -> str:
    """Kompensacja w notacji aparatu: 0.333 → +1/3, 1.667 → +1 2/3."""
    thirds = round(ev * 3)
    if not thirds:
        return "±0"
    sign = "+" if thirds > 0 else "−"
    whole, rest = divmod(abs(thirds), 3)
    frac = f"{rest}/3" if rest else ""
    return sign + " ".join(p for p in (str(whole) if whole else "", frac) if p)


def _camera_exif(path: Path) -> dict:
    """EXIF z oryginalu z aparatu (sam naglowek, obraz nie jest dekodowany).
    Gotowe zdjecie EXIF-u nie ma — obrobka zapisuje czysty JPEG."""
    try:
        with Image.open(path) as im:
            ex = im.getexif()
            size = list(im.size)
    except OSError:
        return {}
    sub = ex.get_ifd(_EXIF_IFD)

    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError, ZeroDivisionError):
            return None

    out: dict = {"size": size}
    model = str(ex.get(0x0110) or "").strip()
    make = str(ex.get(0x010F) or "").strip()
    if model:
        out["camera"] = model if not make or model.startswith(make) else f"{make} {model}"
    # autor i prawa autorskie wpisane w menu aparatu (dopisuje je do kazdego zdjecia)
    for tag, key in ((0x013B, "artist"), (0x8298, "copyright")):
        if (text := str(ex.get(tag) or "").strip(" \x00")):
            out[key] = text
    if sub.get(0xA434):
        out["lens"] = str(sub[0xA434]).strip()
    taken = str(sub.get(0x9003) or ex.get(0x0132) or "").strip()
    if taken:
        # „2026:09:10 14:06:39" → „2026-09-10 14:06:39"
        out["taken"] = taken[:10].replace(":", "-") + taken[10:]
    if (t := num(sub.get(0x829A))):
        out["shutter"] = _shutter(t)
    if (f := num(sub.get(0x829D))):
        out["aperture"] = f"f/{f:g}"
    iso = sub.get(0x8827)
    if isinstance(iso, tuple):
        iso = iso[0] if iso else None
    if iso:
        out["iso"] = int(iso)
    if (ev := num(sub.get(0x9204))) is not None:
        out["ev"] = _ev_text(ev)
    if (fl := num(sub.get(0x920A))):
        out["focal"] = f"{fl:g} mm"
    return out


def shot_metadata(session_dir: Path, filename: str, review: dict) -> dict | None:
    """Metadane do panelu w podgladzie: plik, obrobka i EXIF z oryginalu."""
    path = session_dir / Path(filename).name
    try:
        with Image.open(path) as im:
            size = list(im.size)
        stat = path.stat()
    except OSError:
        return None
    bits = [b for b in review.get("meta", {}).get(filename, "").split(" · ") if b]
    raw = find_raw(session_dir, filename)
    out = {
        "file": filename,
        "size": size,
        "bytes": stat.st_size,
        "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
        # meta znamy tylko dla zdjec obrobionych na tym komputerze
        "logo": ("logo" in bits) if bits else None,
        # nazwa i rog logo zapisywane od 2.7 — starsze zdjecia maja samo „logo"
        "logoInfo": review.get("logo", {}).get(filename),
        "zoom": ("zoom" in bits) if bits else None,
        "aligned": (review.get("frame", {}).get(filename) or {}).get("aligned"),
        "uploaded": filename in review.get("uploaded", []),
        "raw": None,
    }
    if raw:
        out["raw"] = {"bytes": raw.stat().st_size, **_camera_exif(raw)}
    else:
        # bez oryginalu: dane aparatu z gotowego zdjecia (przepisywane od 2.10)
        cam = {k: v for k, v in _camera_exif(path).items() if k != "size"}
        if cam:
            out["camera"] = cam
    return out


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
    raise RuntimeError(tr("kosz: nie mogę założyć katalogu na usunięte pliki"))


def retry_locked(fn, attempts: int = 20, delay: float = 0.1):
    """Windows nie pozwala przeniesc ani skasowac pliku, ktory ktos czyta —
    a podglad w oknie pobiera zdjecie (i jego miniature) dokladnie wtedy, gdy
    operator wciska BACKSPACE. Czytanie trwa ulamek sekundy, wiec ponawiamy
    krotko zamiast zostawiac zdjecie, ktore „nie chce sie usunac"."""
    for i in range(attempts):
        try:
            return fn()
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(delay)


def move_into(batch: Path, path: Path) -> None:
    target = batch / path.name
    n = 1
    while target.exists():
        target = batch / f"{path.stem}-{n}{path.suffix}"
        n += 1
    retry_locked(lambda: shutil.move(str(path), str(target)))


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


# ---------- stare oryginaly (photos/<sesja>/raw) ----------


def purge_originals(base_output: Path, days: int) -> int:
    """Kasuje oryginaly z aparatu starsze niz `days` dni (po mtime pliku)
    razem z kopia bez logo z `.nologo/` — bez obu edycja logo tego zdjecia
    nie ma juz z czego pracowac (`shot_entries` daje wtedy edit=""). Gotowe
    zdjecia zostaja. Zwraca liczbe skasowanych oryginalow; 0 dni = nic."""
    if days <= 0 or not base_output.is_dir():
        return 0
    cutoff = (datetime.now() - timedelta(days=days)).timestamp()
    removed = 0
    for session in base_output.iterdir():
        if not session.is_dir() or session.name.startswith("."):
            continue
        for raw in [*session.glob("raw/*_raw.jpg"), *session.glob("*_raw.jpg")]:
            try:
                if raw.stat().st_mtime >= cutoff:
                    continue
                raw.unlink()
            except OSError:
                continue
            removed += 1
            final = raw.name[: -len("_raw.jpg")] + ".jpg"
            (session / NOLOGO_DIR / final).unlink(missing_ok=True)
            (session / GHOSTS_DIR / final).unlink(missing_ok=True)
    return removed


# ---------- miejsce na dysku (Ustawienia → Pliki) ----------

CACHE_DIRS = (".thumbs", ".views", GHOSTS_DIR)   # odtworzą się same przy następnym podglądzie
GB = 1024 ** 3


def _kind(rel: Path) -> str:
    """Do której kategorii paska należy plik (ścieżka względem photos/)."""
    top = rel.parts[0]
    if top == TRASH_DIR:
        return "trash"
    if top == COVERS_DIR or (len(rel.parts) > 2 and rel.parts[1] in CACHE_DIRS):
        return "cache"
    if len(rel.parts) > 2 and rel.parts[1] in ("raw", NOLOGO_DIR):
        return "originals"
    if len(rel.parts) == 2 and rel.suffix.lower() == ".jpg":
        return "originals" if rel.stem.endswith("_raw") else "finals"
    return "other"


def storage_usage(base_output: Path) -> dict:
    """Ile zajmuje katalog zdjęć, z podziałem: gotowe zdjęcia, oryginały
    z aparatu (+ kopie bez logo), kosz, pliki podręczne, reszta (kadry,
    recenzje). Do tego wolne miejsce na dysku."""
    usage = dict.fromkeys(("finals", "originals", "trash", "cache", "other"), 0)
    if base_output.is_dir():
        for root, _dirs, files in os.walk(base_output):
            for name in files:
                path = Path(root) / name
                try:
                    size = path.stat().st_size
                except OSError:
                    continue
                usage[_kind(path.relative_to(base_output))] += size
    usage["total"] = sum(usage.values())
    probe = base_output if base_output.exists() else base_output.parent
    try:
        usage["free"] = shutil.disk_usage(probe).free
    except OSError:
        usage["free"] = None
    return usage


def enforce_storage_limit(base_output: Path, limit_bytes: int) -> dict:
    """Zwalnia miejsce, aż katalog zdjęć zmieści się w limicie — od tego, czego
    najmniej szkoda: kosz (najstarsze wpisy), pliki podręczne, najstarsze
    oryginały z aparatu (razem z kopią bez logo). GOTOWYCH ZDJĘĆ NIE RUSZA:
    jeśli same przekraczają limit, zostaje ostrzeżenie w UI. Zwraca, ile
    i czego skasowano."""
    freed = {"trash": 0, "cache": 0, "originals": 0, "bytes": 0}
    total = storage_usage(base_output)["total"]
    if limit_bytes <= 0 or total <= limit_bytes:
        return freed

    def drop(path: Path, kind: str) -> None:
        nonlocal total
        try:
            size = sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) if path.is_dir() \
                else path.stat().st_size
            shutil.rmtree(path) if path.is_dir() else path.unlink()
        except OSError:
            return
        total -= size
        freed["bytes"] += size
        freed[kind] += 1

    trash = base_output / TRASH_DIR
    for entry in sorted(trash.iterdir()) if trash.is_dir() else []:
        if total <= limit_bytes:
            return freed
        drop(entry, "trash")
    sessions = [d for d in base_output.iterdir() if d.is_dir() and not d.name.startswith(".")]
    cache = [f for d in sessions for c in CACHE_DIRS for f in (d / c).glob("*") if f.is_file()]
    for f in sorted(cache, key=lambda f: f.stat().st_mtime):
        if total <= limit_bytes:
            return freed
        drop(f, "cache")
    raws = [r for d in sessions for r in (*d.glob("raw/*_raw.jpg"), *d.glob("*_raw.jpg"))]
    for raw in sorted(raws, key=lambda f: f.stat().st_mtime):
        if total <= limit_bytes:
            return freed
        final = raw.name[: -len("_raw.jpg")] + ".jpg"
        session = raw.parent.parent if raw.parent.name == "raw" else raw.parent
        drop(raw, "originals")
        for extra in (session / NOLOGO_DIR / final, session / GHOSTS_DIR / final):
            if extra.exists():
                size = extra.stat().st_size
                extra.unlink(missing_ok=True)
                total -= size
                freed["bytes"] += size
    return freed


# ---------- okladki sesji (photos/.covers) ----------


def cover_path(base_output: Path, session_id: int) -> Path:
    return base_output / COVERS_DIR / f"{int(session_id)}.jpg"


def make_cover(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    img = Image.open(src)
    img.thumbnail((COVER_SIZE, COVER_SIZE))
    img.convert("RGB").save(dest, "JPEG", quality=82)
