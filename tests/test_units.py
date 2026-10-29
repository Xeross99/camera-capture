"""Czesci bez aparatu i bez okna: obrobka zdjecia, nazwy, kosz, wersje."""

import io
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from conftest import FIXTURES
from src import config
from src.image_processing import LOGO_POSITIONS, overlay_logo, process
from src.naming import sanitize_name
from src.session_store import (TRASH_STAMP, _ev_text, edit_base, finals, find_raw, load_review,
                               purge_originals, purge_trash, remote_filename, save_review, shot_entries,
                               shot_metadata)
from src.version import parse_version
from src.webui import _ev_number


# ---------- nazwy ----------

@pytest.mark.parametrize("raw, want", [
    ("left switch r72", "left switch r72"),
    ("  Zwrotnica  ", "Zwrotnica"),
    ("a/b\\c", "a_b_c"),               # sesja nie moze wyjsc z katalogu photos/
    ("../../etc", "_.._etc"),
    ("", "default"),
    ("...", "default"),
])
def test_sanitize_name(raw, want):
    assert sanitize_name(raw) == want


def test_remote_filename_stays_inside_session():
    assert remote_filename({"id": 7, "filename": "../../x.jpg"}) == "x.jpg"
    assert remote_filename({"id": 7, "filename": "notatki.txt"}) == "photo_7.jpg"
    assert remote_filename({"id": 7, "filename": ".hidden.jpg"}) == "photo_7.jpg"


# ---------- kompensacja ekspozycji ----------

@pytest.mark.parametrize("text, want", [
    ("0", 0.0), ("+1/3", 1 / 3), ("-2/3", -2 / 3), ("+2 2/3", 2 + 2 / 3),
    ("+3.0", 3.0), ("−1", -1.0), ("", None), ("abc", None),
])
def test_ev_number(text, want):
    got = _ev_number(text)
    assert got == pytest.approx(want) if want is not None else got is None


# ---------- wersje (aktualizacje) ----------

def test_parse_version():
    assert parse_version("v2.3.1") == (2, 3, 1)
    assert parse_version("2.10.0") > parse_version("2.9.9")
    assert parse_version("nie-wersja") is None


def test_is_newer(monkeypatch):
    from src import updater
    monkeypatch.setattr(updater, "APP_VERSION", "2.3.1")
    assert updater.is_newer("2.3.2")
    assert updater.is_newer("2.10.0")
    assert not updater.is_newer("2.3.1")
    assert not updater.is_newer("2.2.9")


# ---------- obrobka zdjecia ----------

@pytest.fixture(scope="module")
def processed(tmp_path_factory):
    """Jedna pelna obrobka (rembg trwa) — wspolna dla testow ponizej."""
    out_dir = tmp_path_factory.mktemp("session")
    out = process(FIXTURES / "product_raw.jpg", config.LOGOS["kids"]["file"], out_dir,
                  clean_bg=True, add_logo=True, logo_position="bottom-right",
                  auto_center=True, auto_zoom=True, out_name="photo_1.jpg",
                  base_out=out_dir / ".nologo" / "photo_1.jpg")
    return out_dir, out


def test_process_makes_square_3000(processed):
    _, out = processed
    with Image.open(out) as im:
        assert im.size == (config.OUTPUT_SIZE, config.OUTPUT_SIZE) == (3000, 3000)


def test_process_keeps_raw_and_nologo(processed):
    out_dir, out = processed
    assert (out_dir / "photo_1_raw.jpg").read_bytes() == (FIXTURES / "product_raw.jpg").read_bytes()
    assert (out_dir / ".nologo" / "photo_1.jpg").exists()


def test_process_background_is_white(processed):
    _, out = processed
    arr = np.asarray(Image.open(out).convert("L"))
    corners = [arr[:150, :150], arr[:150, -150:], arr[-150:, :150]]
    for c in corners:
        assert c.mean() > 245, "tlo w rogach ma byc biale"


def test_process_centers_and_zooms_product(processed):
    out_dir, _ = processed
    # wersja bez logo — logo w rogu nie zaburza pomiaru
    arr = np.asarray(Image.open(out_dir / ".nologo" / "photo_1.jpg").convert("L"))
    ys, xs = np.nonzero(arr < 200)
    h, w = arr.shape
    cx, cy = xs.mean() / w, ys.mean() / h
    assert abs(cx - 0.5) < 0.08 and abs(cy - 0.5) < 0.08, "produkt na srodku kadru"
    span = max(xs.max() - xs.min(), ys.max() - ys.min()) / w
    assert span > 0.6, "produkt przyblizony, wypelnia wiekszosc kadru"


def test_process_without_logo_and_clean_bg_is_plain_crop(tmp_path):
    out = process(FIXTURES / "product_raw.jpg", config.LOGOS["kids"]["file"], tmp_path,
                  clean_bg=False, add_logo=False, out_name="p.jpg")
    with Image.open(out) as im:
        assert im.size == (3000, 3000)
    assert not (tmp_path / ".nologo").exists()


def _logo_box(img: Image.Image) -> tuple[float, float]:
    """Srodek obszaru, gdzie obraz z logo rozni sie od bialego tla."""
    arr = np.asarray(img.convert("L")).astype(int)
    ys, xs = np.nonzero(arr < 250)
    return xs.mean() / arr.shape[1], ys.mean() / arr.shape[0]


@pytest.mark.parametrize("logo", list(config.LOGOS))
@pytest.mark.parametrize("position", LOGO_POSITIONS)
def test_logo_lands_in_chosen_corner(logo, position):
    blank = Image.new("RGB", (1000, 1000), "white")
    out = overlay_logo(blank, config.LOGOS[logo]["file"], position)
    x, y = _logo_box(out)
    assert (x < 0.5) == ("left" in position)
    assert (y < 0.5) == ("top" in position)


def test_logo_sizes_differ_between_logos():
    blank = Image.new("RGB", (1000, 1000), "white")
    heights = {}
    for key, spec in config.LOGOS.items():
        arr = np.asarray(overlay_logo(blank, spec["file"], "bottom-right").convert("L"))
        ys, _ = np.nonzero(arr < 250)
        heights[key] = (ys.max() - ys.min()) / 1000
    # KIDS jest wieksze (0.10 kadru) niz TRIXBRIX.eu (0.06)
    assert heights["kids"] > heights["trixbrix"]
    assert heights["kids"] <= config.LOGOS["kids"]["height"] + 0.01


def test_missing_logo_file_leaves_image_untouched(tmp_path):
    img = Image.new("RGB", (100, 100), "white")
    assert overlay_logo(img, tmp_path / "brak.webp") is img


# ---------- sesja na dysku ----------

def test_review_roundtrip_and_finals(tmp_path):
    for name in ("photo_2.jpg", "photo_1.jpg", "photo_1_raw.jpg"):
        Image.new("RGB", (10, 10)).save(tmp_path / name)
    assert finals(tmp_path) == ["photo_1.jpg", "photo_2.jpg"], "raw nie jest zdjeciem sesji"
    review = load_review(tmp_path)
    assert review == {"rejected": [], "uploaded": [], "meta": {}, "automat": {}, "frame": {}, "logo": {}}
    review["rejected"].append("photo_2.jpg")
    save_review(tmp_path, review)
    entries = {e["file"]: e for e in shot_entries(tmp_path, load_review(tmp_path))}
    assert entries["photo_2.jpg"]["status"] == "rejected"
    assert entries["photo_1.jpg"]["status"] == "ok"
    assert entries["photo_1.jpg"]["size"] == [10, 10]
    assert find_raw(tmp_path, "photo_1.jpg") == tmp_path / "photo_1_raw.jpg"


def test_shot_metadata_reads_camera_exif_from_original(tmp_path):
    exif = Image.Exif()
    exif[0x010F], exif[0x0110] = "Canon", "Canon EOS M50m2"
    exif[0x8298] = "Example Studio, all rights reserved"
    exif[0x013B] = "Jan Example"
    sub = exif.get_ifd(0x8769)
    sub.update({0x829A: 0.5, 0x829D: 22.0, 0x8827: 800, 0x9204: 2 / 3, 0x920A: 15.0,
                0xA434: "EF-M15-45mm f/3.5-6.3 IS STM", 0x9003: "2026:09:10 14:06:39"})
    (tmp_path / "raw").mkdir()
    Image.new("RGB", (60, 40)).save(tmp_path / "raw" / "p_raw.jpg", exif=exif)
    Image.new("RGB", (30, 30)).save(tmp_path / "p.jpg")
    Image.new("RGB", (30, 30)).save(tmp_path / "q.jpg")
    review = load_review(tmp_path)
    review["meta"]["p.jpg"] = "logo · zoom · 3000×3000"
    review["logo"]["p.jpg"] = {"label": "TRIXBRIX.eu KIDS", "pos": "top-left"}
    info = shot_metadata(tmp_path, "p.jpg", review)
    assert info["size"] == [30, 30] and info["logo"] and info["zoom"]
    assert info["logoInfo"] == {"label": "TRIXBRIX.eu KIDS", "pos": "top-left"}
    raw = info["raw"]
    assert raw["camera"] == "Canon EOS M50m2", "producent nie dublowany przed modelem"
    assert raw["lens"] == "EF-M15-45mm f/3.5-6.3 IS STM"
    assert (raw["shutter"], raw["aperture"], raw["iso"], raw["ev"], raw["focal"]) == \
        ("1/2 s", "f/22", 800, "+2/3", "15 mm")
    assert raw["taken"] == "2026-09-10 14:06:39" and raw["size"] == [60, 40]
    assert raw["copyright"] == "Example Studio, all rights reserved"
    assert raw["artist"] == "Jan Example"
    # bez oryginalu (zdjecie z Automatu): sam plik, logo nieznane
    bare = shot_metadata(tmp_path, "q.jpg", review)
    assert bare["raw"] is None and bare["logo"] is None
    assert shot_metadata(tmp_path, "brak.jpg", review) is None


def test_ev_text_uses_camera_notation():
    assert [_ev_text(v) for v in (0, 1 / 3, 1, 5 / 3, -2 / 3, -2)] == \
        ["±0", "+1/3", "+1", "+1 2/3", "−2/3", "−2"]


def test_edit_base_prefers_nologo_copy(tmp_path):
    (tmp_path / ".nologo").mkdir()
    Image.new("RGB", (10, 10)).save(tmp_path / ".nologo" / "a.jpg")
    assert edit_base(tmp_path, "a.jpg", {"meta": {}}) == tmp_path / ".nologo" / "a.jpg"
    # zdjecie robione bez logo jest samo swoja baza
    assert edit_base(tmp_path, "b.jpg", {"meta": {"b.jpg": "zoom · 3000×3000"}}) == tmp_path / "b.jpg"
    assert edit_base(tmp_path, "c.jpg", {"meta": {"c.jpg": "logo · 3000×3000"}}) is None


def test_purge_trash_respects_retention(tmp_path):
    root = tmp_path / ".trash"
    old = root / ((datetime.now() - timedelta(days=31)).strftime(TRASH_STAMP) + "_stara")
    fresh = root / ((datetime.now() - timedelta(days=29)).strftime(TRASH_STAMP) + "_nowa")
    old.mkdir(parents=True)
    fresh.mkdir(parents=True)
    # data jest w NAZWIE — swiezy mtime starego wpisu nic nie zmienia
    os.utime(old, (time.time(), time.time()))
    assert purge_trash(tmp_path, days=30) == 1
    assert not old.exists() and fresh.exists()
    assert purge_trash(tmp_path, days=0) == 0, "0 dni = kosz wylaczony, nic nie kasuje"


def test_purge_originals_drops_old_raw_and_nologo_only(tmp_path):
    sess = tmp_path / "sesja"
    (sess / "raw").mkdir(parents=True)
    (sess / ".nologo").mkdir()
    old_t = time.time() - 40 * 86400
    for name, t in (("old", old_t), ("new", time.time())):
        Image.new("RGB", (10, 10)).save(sess / f"{name}.jpg")
        Image.new("RGB", (10, 10)).save(sess / ".nologo" / f"{name}.jpg")
        raw = sess / "raw" / f"{name}_raw.jpg"
        Image.new("RGB", (10, 10)).save(raw)
        os.utime(raw, (t, t))
    assert purge_originals(tmp_path, days=0) == 0, "0 = oryginały zostają zawsze"
    assert purge_originals(tmp_path, days=30) == 1
    assert not (sess / "raw" / "old_raw.jpg").exists() and not (sess / ".nologo" / "old.jpg").exists()
    assert (sess / "old.jpg").exists(), "gotowe zdjęcie zostaje"
    assert (sess / "raw" / "new_raw.jpg").exists() and (sess / ".nologo" / "new.jpg").exists()
    entries = {e["file"]: e for e in shot_entries(sess, load_review(sess))}
    assert entries["old.jpg"]["edit"] == "", "bez oryginału i kopii bez logo edycji logo nie ma"
    assert entries["new.jpg"]["edit"] == "ready"


# ---------- lekkie dopasowanie do nakladki ----------

def test_align_nudges_window_towards_reference_but_only_slightly():
    from src.background import ALIGN_MAX_SHIFT, _align_to_reference
    src = (6000, 4000)
    # referencja: produkt 2000..4000 x 1000..3000, okno wokol niego
    ref = {"src": list(src), "bbox": [2000, 1000, 4000, 3000], "window": [1500, 500, 4500, 3500]}
    # ten sam produkt przesuniety o 100 px w prawo, kadr wycentrowany na nim
    bbox = (2100, 1000, 4100, 3000)
    window = (1600, 500, 4600, 3500)
    new, info = _align_to_reference(window, bbox, ref, src)
    assert info is None and new == window, "z centrowaniem produkt i tak stoi tam, gdzie w referencji"
    # bez centrowania: stale okno, produkt uciekl o 150 px — kadr idzie za nim, ale max 2 %
    bbox = (2150, 1000, 4150, 3000)
    new, info = _align_to_reference((1500, 500, 4500, 3500), bbox, ref, src)
    assert info is not None
    assert new[0] - 1500 == round(ALIGN_MAX_SHIFT * src[0]), "przesuniecie przyciete do limitu"


def test_align_leaves_differently_placed_product_alone():
    from src.background import _align_to_reference
    src = (6000, 4000)
    ref = {"src": list(src), "bbox": [2000, 1000, 4000, 3000], "window": [1500, 500, 4500, 3500]}
    window = (500, 500, 3500, 3500)
    new, info = _align_to_reference(window, (1000, 1000, 3000, 3000), ref, src)
    assert info is None and new == window, "maly overlap = swiadomie inaczej, bez pomocy"
    new, info = _align_to_reference(window, (2000, 1000, 4000, 3000), {**ref, "src": [3000, 2000]}, src)
    assert info is None, "inna rozdzielczosc zrodla = nie porownujemy"


def test_align_never_cuts_the_product():
    from src.background import _align_to_reference
    src = (6000, 4000)
    ref = {"src": list(src), "bbox": [2000, 1000, 4000, 3000], "window": [2000, 1000, 4000, 3000]}
    # okno ciasno na produkcie; referencja kaze zmniejszyc okno — produkt by wypadl
    window = (1990, 990, 4010, 3010)
    new, info = _align_to_reference(window, (2000, 1000, 4000, 3000), ref, src)
    assert new[0] <= 2000 and new[2] >= 4000 and new[1] <= 1000 and new[3] >= 3000


def _shifted_shot(dx, dy, k):
    base = Image.open(FIXTURES / "product_raw.jpg").convert("RGB")
    w, h = base.size
    sc = base.resize((round(w * k), round(h * k)), Image.LANCZOS)
    im = Image.new("RGB", (w, h), base.getpixel((5, 5)))
    im.paste(sc, ((w - sc.width) // 2 + round(dx * w), (h - sc.height) // 2 + round(dy * h)))
    return im


def _product_box_in(img):
    ys, xs = np.nonzero(np.asarray(img.convert("L")) < 235)
    return np.array([xs.min(), ys.min(), xs.max(), ys.max()])


@pytest.mark.parametrize("center,zoom", [(True, True), (True, False), (False, True), (False, False)])
def test_series_with_overlay_keeps_product_in_the_same_place(center, zoom):
    """Seria przy nakladce: produkt postawiony lekko obok (przesuniety, blizej,
    dalej) w GOTOWYCH zdjeciach stoi tam, gdzie na zdjeciu wzorcowym —
    przegladane strzalkami nie skacze. Kazda kombinacja centrowania/przyblizania."""
    from src.background import clean_background
    run = lambda im, ref=None: clean_background(im, (1000, 1000), auto_center=center,
                                                auto_zoom=zoom, align_to=ref, frame_out=out)
    out = {}
    ref_box = _product_box_in(run(_shifted_shot(0, 0, 1)))
    ref = dict(out)
    for dx, dy, k in [(0.015, 0, 1), (-0.01, 0.005, 1), (0, 0, 1.02), (0.01, 0.01, 1.02), (-0.008, 0, 0.985)]:
        out = {}
        got = _product_box_in(run(_shifted_shot(dx, dy, k), ref))
        assert np.abs(got - ref_box).max() <= 3, (dx, dy, k)


def _rotation_between(img, ref_img):
    """Kat (stopnie), o ktory trzeba obrocic produkt z `img`, zeby lezal jak
    w `ref_img` — pomiar niezalezny od aplikacji (maski z progu jasnosci)."""
    from scipy import ndimage
    def mask(im):
        return (np.asarray(im.convert("L").resize((500, 500))) < 200).astype(np.float32)
    a, b = mask(ref_img), mask(img)
    ca = ndimage.center_of_mass(a)
    def cost(ang):
        r = ndimage.rotate(b, ang, reshape=False, order=1)
        cb = ndimage.center_of_mass(r)
        return np.abs(ndimage.shift(r, (ca[0] - cb[0], ca[1] - cb[1]), order=1) - a).sum()
    angles = np.arange(-3, 3.01, 0.1)
    return float(angles[int(np.argmin([cost(x) for x in angles]))])


def test_overlay_series_straightens_slightly_rotated_product():
    """Prawdziwa seria (zwrotnica R148): drugie zdjecie z produktem obroconym
    o ~1 stopien — po korekcie do nakladki gotowe zdjecie lezy jak pierwsze,
    wiec przegladane strzalkami nie skacze (dol produktu rozjezdzal sie w X)."""
    from src.background import clean_background
    a = Image.open(FIXTURES / "series_r148_a.jpg")
    b = Image.open(FIXTURES / "series_r148_b.jpg")
    ref = {}
    ref_img = clean_background(a, (1000, 1000), frame_out=ref)
    plain = clean_background(b, (1000, 1000))
    out = {}
    fixed = clean_background(b, (1000, 1000), align_to=ref, frame_out=out)
    assert abs(_rotation_between(plain, ref_img)) >= 0.8, "bez korekty produkt jest obrocony"
    assert out.get("aligned", {}).get("rot"), "korekta obrotu zadzialala"
    assert abs(_rotation_between(fixed, ref_img)) <= 0.2, "po korekcie lezy jak na zdjeciu wzorcowym"


# ---------- edytor logo (Ustawienia → Logo) ----------

def _png(color=(200, 30, 30, 255), size=(120, 40)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGBA", size, color).save(buf, "PNG")
    return buf.getvalue()


def test_logo_store_adds_edits_and_removes_logos():
    from src import logo_store
    key = logo_store.add_logo("Moja Firma", _png(), 0.5, 0.05)
    spec = config.LOGOS[key]
    assert key == "moja-firma" and spec["file"].exists()
    assert (spec["height"], spec["opacity"]) == (0.25, 0.1), "rozmiar i krycie przyciete do zakresu"
    with pytest.raises(logo_store.LogoError):
        logo_store.add_logo("moja firma", _png(), 0.06, 1)      # nazwa juz jest (wielkosc liter bez znaczenia)
    assert logo_store.add_logo("Moja-Firma", _png(), 0.06, 1) == "moja-firma-2", "klucze sie nie dubluja"
    old_file = spec["file"]
    with pytest.raises(logo_store.LogoError):
        logo_store.update_logo(key, "TRIXBRIX.eu KIDS", 0.08, 0.6)   # cudza nazwa
    logo_store.update_logo(key, "Moja Firma", 0.08, 0.6)              # wlasna nazwa wolno zostawic
    logo_store.update_logo(key, "Firma", 0.08, 0.6, _png((0, 0, 0, 255)))
    assert not old_file.exists(), "podmieniony plik nie zostaje na dysku"
    assert config.LOGOS[key]["label"] == "Firma" and config.LOGOS[key]["file"].exists()
    builtin = config.LOGOS["kids"]["file"]
    logo_store.delete_logo("kids")
    assert "kids" not in config.LOGOS and builtin.exists(), "plik wbudowanego logo zostaje w paczce"
    # lista przezywa restart: ponowne wczytanie z logos.json
    saved = dict(config.LOGOS)
    config.LOGOS.clear()
    config._load_logos()
    assert list(config.LOGOS) == list(saved)
    assert config.LOGOS[key]["height"] == 0.08


def test_logo_store_rejects_bad_input():
    from src import logo_store
    with pytest.raises(logo_store.LogoError):
        logo_store.add_logo("x", b"to nie obraz", 0.06, 1)
    with pytest.raises(logo_store.LogoError):
        logo_store.add_logo("   ", _png(), 0.06, 1)
    with pytest.raises(logo_store.LogoError):
        logo_store.add_logo("bez pliku", None, 0.06, 1)
    with pytest.raises(logo_store.LogoError):
        logo_store.delete_logo("nie-ma")


def test_builtin_logos_migrate_into_the_editor_once():
    from src import logo_store
    old = {k: v["file"] for k, v in config.LOGOS.items()}
    moved = logo_store.migrate_builtin()
    assert set(moved) == set(old.values()), "wybrane logo w WebUI przepinane na kopie"
    for key, spec in config.LOGOS.items():
        assert spec["file"].parent == config.LOGOS_DIR and spec["file"].exists()
        assert spec["file"].read_bytes() == old[key].read_bytes()
        assert not spec["ref"].startswith("builtin:")
    assert config.LOGOS["kids"]["height"] == 0.10 and config.LOGOS["trixbrix"]["opacity"] == 0.5
    assert config.LOGOS_FILE.exists()
    assert logo_store.migrate_builtin() == {}, "drugi start niczego nie przenosi"


def test_finished_photo_keeps_camera_exif_without_private_tags(tmp_path):
    from src.image_processing import process
    exif = Image.Exif()
    exif[0x010F], exif[0x0110], exif[0x0112] = "Canon", "Canon EOS M50m2", 6
    exif[0x013B], exif[0x8298] = "Jan Example", "Example Studio"
    sub = exif.get_ifd(0x8769)
    sub.update({0x829A: 0.5, 0x829D: 22.0, 0x8827: 800, 0xA434: "EF-M15-45mm",
                0xA431: "213052009657", 0xA435: "00000135cc", 0x9003: "2026:09:10 14:06:39"})
    exif.get_ifd(0x8825)[1] = "N"          # GPS
    src = tmp_path / "in.jpg"
    Image.new("RGB", (600, 400), "white").save(src, exif=exif)
    out = process(src, config.LOGOS["kids"]["file"], tmp_path / "out", clean_bg=False, add_logo=True,
                  out_name="p.jpg", base_out=tmp_path / "out" / ".nologo" / "p.jpg")
    for f in (out, tmp_path / "out" / ".nologo" / "p.jpg"):
        with Image.open(f) as im:
            ex = im.getexif()
            got = ex.get_ifd(0x8769)
        assert ex[0x0110] == "Canon EOS M50m2" and ex[0x8298] == "Example Studio" and ex[0x013B] == "Jan Example"
        assert got[0xA434] == "EF-M15-45mm" and int(got[0x8827]) == 800
        assert 0x0112 not in ex, "orientacji swiadomie nie przenosimy"
        assert 0xA431 not in got and 0xA435 not in got, "bez numerow seryjnych"
        assert not ex.get_ifd(0x8825), "bez GPS"
    # bez oryginalu panel informacji czyta dane aparatu z gotowego zdjecia
    sdir = tmp_path / "out"
    info = shot_metadata(sdir, "p.jpg", load_review(sdir))
    if info["raw"] is None:
        assert info["camera"]["camera"] == "Canon EOS M50m2" and info["camera"]["iso"] == 800
    (sdir / "p_raw.jpg").unlink(missing_ok=True)
    info = shot_metadata(sdir, "p.jpg", load_review(sdir))
    assert info["raw"] is None and info["camera"]["shutter"] == "1/2 s"


def test_storage_usage_and_limit_free_space_in_order(tmp_path):
    from src.session_store import enforce_storage_limit, storage_usage
    mb = 1024 * 1024

    def put(rel, size):
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"x" * size)
        return f

    put("s/a.jpg", 3 * mb)                         # gotowe
    raw_old = put("s/raw/a_raw.jpg", 2 * mb)       # oryginal (starszy)
    put("s/.nologo/a.jpg", 1 * mb)                 # kopia bez logo = oryginaly
    raw_new = put("s/raw/b_raw.jpg", 2 * mb)
    os.utime(raw_old, (1, 1))
    put("s/.thumbs/a.jpg", 1 * mb)                 # podreczne
    put(".trash/20260101-000000_s/x.jpg", 1 * mb)  # kosz
    u = storage_usage(tmp_path)
    assert (u["finals"], u["originals"], u["cache"], u["trash"]) == (3 * mb, 5 * mb, 1 * mb, 1 * mb)
    assert u["total"] == 10 * mb and u["free"] > 0
    # limit 7 MB: kosz, podreczne, potem NAJSTARSZY oryginal z kopia bez logo
    freed = enforce_storage_limit(tmp_path, 7 * mb)
    assert freed["trash"] == 1 and freed["cache"] == 1 and freed["originals"] == 1
    assert not raw_old.exists() and not (tmp_path / "s/.nologo/a.jpg").exists()
    assert raw_new.exists(), "zwalnia tylko tyle, ile trzeba"
    # nawet limit mniejszy niz gotowe zdjecia nie rusza gotowych
    enforce_storage_limit(tmp_path, 1 * mb)
    assert (tmp_path / "s/a.jpg").exists()
    assert storage_usage(tmp_path)["finals"] == 3 * mb
