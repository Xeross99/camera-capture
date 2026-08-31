"""Czyszczenie tla + auto-center/auto-zoom (pelny opis pipeline'u w CLAUDE.md).

Przeplyw `clean_background`:
    rembg (inference w malej rozdzielczosci) -> maska/alpha na full-res
    (`_product_alpha`) -> lifting cieni w przeswitach -> wybor okna cropu
    (`_select_crop_window`) -> kompozycja na bialej canvie
    (`_compose_on_canvas`).
"""

import time
from functools import lru_cache

import numpy as np
from PIL import Image, ImageFilter
from scipy import ndimage

from .config import (
    AUTO_CENTER,
    AUTO_ZOOM,
    BLEED_FIT_MARGIN,
    CLEAN_BG_ALPHA_CEILING,
    CLEAN_BG_ALPHA_FLOOR,
    CLEAN_BG_COLOR,
    CLEAN_BG_EDGE_BLUR,
    CLEAN_BG_GPU,
    CLEAN_BG_INFERENCE_SIZE,
    CLEAN_BG_MASK_THRESHOLD,
    CLEAN_BG_MODEL,
    PRODUCT_MARGIN,
    SHADOW_RADIUS_RATIO,
    SHADOW_STRENGTH,
    SHARPEN_PERCENT,
)

Bbox = tuple[int, int, int, int]  # (left, top, right, bottom)
Window = tuple[int, int, int, int]  # okno cropu w pikselach source (sl, st, sr, sb)


# Biezacy stan przelacznika GPU — startuje z .env, ale UI moze go przestawic
# w locie (Ustawienia). Osobna zmienna, bo CLEAN_BG_GPU to stala z importu.
_GPU_ENABLED = CLEAN_BG_GPU


def set_gpu(enabled: bool) -> None:
    """Runtime kill-switch obrobki na GPU (checkbox w Ustawieniach).

    Czysci cache sesji rembg, wiec nastepna obrobka zbuduje ja od nowa z
    wlasciwymi providerami — bez restartu aplikacji. Po WLACZENIU pierwsza
    inferencja na DirectML znow kompiluje shadery (patrz warmup_clean_bg)."""
    global _GPU_ENABLED
    if _GPU_ENABLED == bool(enabled):
        return
    _GPU_ENABLED = bool(enabled)
    _session.cache_clear()


def _gpu_providers() -> list[str] | None:
    """Lista providerow onnxruntime z GPU na czele, albo None (= sam CPU).

    rembg sam z siebie wykrywa tylko CUDA/ROCm — DirectML (paczka
    onnxruntime-directml, Windows: kazde GPU przez DirectX 12, bez CUDA)
    trzeba wskazac jawnie."""
    if not _GPU_ENABLED:
        return None
    try:
        import onnxruntime as ort
        available = ort.get_available_providers()
    except Exception:
        return None
    for gpu in ("DmlExecutionProvider", "CUDAExecutionProvider"):
        if gpu in available:
            return [gpu, "CPUExecutionProvider"]
    return None


def gpu_active() -> bool:
    """Czy inferencja rembg pojdzie na GPU: przelacznik ON i onnxruntime ma
    provider GPU. Od tego zalezy, czy rozgrzewka ma sens (patrz warmup_clean_bg)."""
    return _gpu_providers() is not None


@lru_cache(maxsize=1)
def _session(model_name: str):
    from rembg import new_session

    providers = _gpu_providers()
    if providers:
        try:
            session = new_session(model_name, providers=providers)
            print(f"rembg: inferencja na GPU ({providers[0]})")
            return session
        except Exception as e:
            # DirectML potrafi polec na starych sterownikach — CPU zawsze dziala
            print(f"rembg: GPU nie wstało ({e}) — liczę na CPU")
    return new_session(model_name)


def warmup_clean_bg() -> None:
    """Rozgrzewka silnika czyszczenia tla: sesja rembg + jedna miniaturowa
    inferencja.

    Pierwsza inferencja placi jednorazowe koszty procesu: pobranie/zaladowanie
    modelu, a na DirectML takze kompilacje shaderow pod konkretne GPU —
    u operatora zmierzone ~110 s, ktore bez rozgrzewki obrywalo PIERWSZE
    zdjecie sesji. Wolane z workera przy starcie aplikacji, gdy operator
    dopiero wybiera sesje. Rozmiar wejscia bez znaczenia: rembg i tak skaluje
    kazda klatke do stalego wejscia modelu, wiec mala kompiluje to samo.

    Wolana TYLKO gdy gpu_active(): na CPU pierwsza inferencja to ulamek
    sekundy na zaladowanie modelu, a rozgrzewka z overlayem „przygotowuje
    silnik" wygladalaby jak przygotowywanie GPU, ktorego operator wylaczyl."""
    from rembg import remove

    img = Image.new("RGBA", (64, 64), (255, 255, 255, 255))
    remove(img, session=_session(CLEAN_BG_MODEL))


def _binarize(mask: Image.Image, threshold: int = CLEAN_BG_MASK_THRESHOLD) -> Image.Image:
    return mask.point(lambda v: 255 if v >= threshold else 0)


def _filter_small_blobs(arr: np.ndarray, min_fraction: float = 0.03) -> np.ndarray:
    """Keep blobs >= min_fraction of largest (rembg false-positives, dust, paper edges)."""
    labels, n = ndimage.label(arr)
    if n <= 1:
        return arr
    sizes = ndimage.sum_labels(arr, labels, index=np.arange(1, n + 1))
    threshold = max(sizes.max() * min_fraction, 200.0)
    keep_ids = np.where(sizes >= threshold)[0] + 1
    return np.isin(labels, keep_ids)


def _drop_rembg_rejected_blobs(
    binary: np.ndarray, rembg_alpha: np.ndarray, min_alpha: int = 32
) -> np.ndarray:
    """Maska luminancyjna (light bg) lapie kazdy ciemniejszy punkt stolu —
    pylek, wlos, slad po pisaku. Taki smiec 2 m od produktu (w skali kadru)
    rozdmuchuje bbox i auto-center centruje okno na pustym stole zamiast
    na produkcie. rembg smiecia nie widzi (alpha ~0), produkt widzi zawsze
    (255), wiec zostawiamy tylko bloby, w ktorych szczyt alfy rembg
    przekracza `min_alpha`. Brak kryterium rozmiaru — smiec wiekszy niz
    kilka procent produktu tez odpada. Gdy rembg nie zaakceptowal ZADNEGO
    bloba, nie ruszamy nic (lepszy pelny kadr niz pusty bbox)."""
    labels, n = ndimage.label(binary)
    if n <= 1:
        return binary
    peaks = np.asarray(ndimage.maximum(rembg_alpha, labels, index=np.arange(1, n + 1)))
    keep_ids = np.where(peaks >= min_alpha)[0] + 1
    if len(keep_ids) == 0 or len(keep_ids) == n:
        return binary
    return np.isin(labels, keep_ids)


def _mask_bbox(mask: Image.Image) -> Bbox | None:
    arr = np.array(mask) > 128
    if not arr.any():
        return None
    rows = np.where(arr.any(axis=1))[0]
    cols = np.where(arr.any(axis=0))[0]
    return int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1


def _background_luminance(lum: np.ndarray, bg_mask: np.ndarray) -> float:
    """90. percentyl luminancji pikseli tla (bg_mask); gdy tla jest za malo,
    fallback na 95. percentyl calego obrazu."""
    if bg_mask.sum() > 1000:
        value = float(np.percentile(lum[bg_mask], 90))
    else:
        value = float(np.percentile(lum, 95))
    return max(value, 1.0)


def _image_bleed_edges(
    image: Image.Image, alpha: Image.Image, img_lum: np.ndarray | None = None
) -> dict:
    """Detect which raw-image edges have product bleeding off-frame.

    Looks at a 0.5%-thick strip from each edge of the source image (not the
    mask — u2netp @ 768 inference often clips thin extensions, so the mask
    underreports). Counts pixels darker than 70% of background luminance; if
    a strip has at least 50 such pixels we call that edge bleeding.

    `img_lum` to opcjonalna gotowa luminancja source'a — konwersja L pelnej
    klatki jest liczona w `_product_alpha` i szkoda robic jej drugi raz.
    """
    img_arr = np.array(image.convert("L")) if img_lum is None else img_lum
    h, w = img_arr.shape
    bg_lum = _background_luminance(img_arr, np.array(alpha) < 32)

    threshold = bg_lum * 0.7
    min_dark = 50
    sw = max(2, int(w * 0.005))
    sh = max(2, int(h * 0.005))

    return {
        "left":   int((img_arr[:, :sw] < threshold).sum())   >= min_dark,
        "right":  int((img_arr[:, -sw:] < threshold).sum())  >= min_dark,
        "top":    int((img_arr[:sh, :] < threshold).sum())   >= min_dark,
        "bottom": int((img_arr[-sh:, :] < threshold).sum())  >= min_dark,
    }


def _lift_internal_shadows(
    img: Image.Image, alpha: Image.Image, strength: float
) -> Image.Image:
    """Podciaga do bieli cienie widoczne przez przeswity produktu (piksele
    "jasne ale przyciemnione"); szare cialo produktu nie jest ruszane."""
    if strength <= 0:
        # lift = darkness * shadow_on_bg * 0 — wynik identyczny z wejsciem,
        # a po drodze kilka macierzy float32 na pelnych 24 MP (>1 GB szczytu
        # pamieci). Na maszynach z malym RAM-em to wpychalo obrobke w swap.
        return img
    img_arr = np.array(img.convert("RGB")).astype(np.float32)
    lum = img_arr.mean(axis=2)
    bg_lum = _background_luminance(lum, np.array(alpha) < 32)
    darkness = np.clip(1.0 - lum / bg_lum, 0.0, 1.0)
    shadow_on_bg = np.clip((lum / bg_lum - 0.55) / 0.4, 0.0, 1.0)
    lift = darkness * shadow_on_bg * strength
    lifted = img_arr * (1.0 - lift[:, :, None]) + 255.0 * lift[:, :, None]
    return Image.fromarray(np.clip(lifted, 0, 255).astype(np.uint8))


def _build_shadow_layer(
    img: Image.Image, alpha: Image.Image, strength: float
) -> Image.Image:
    """Warstwa cienia strictly pod produktem: per-column bottom + exponential
    falloff w dol, gating horyzontalny do bbox + 3% marginesu."""
    img_arr = np.array(img.convert("RGB")).astype(np.float32)
    h, w, _ = img_arr.shape
    lum = img_arr.mean(axis=2)

    fg = np.array(alpha) > 128
    if not fg.any():
        return Image.fromarray(np.full_like(img_arr, 255, dtype=np.uint8))

    bg_lum = _background_luminance(lum, np.array(alpha) < 32)

    ys_idx = np.arange(h)[:, None]
    masked_ys = np.where(fg, ys_idx, -1)
    bottom_per_col = masked_ys.max(axis=0)
    fg_bottom = int(bottom_per_col.max())
    ref_y = np.where(bottom_per_col >= 0, bottom_per_col, fg_bottom).astype(np.float32)

    fg_cols = fg.any(axis=0)
    xs_with_fg = np.where(fg_cols)[0]
    fg_left, fg_right = int(xs_with_fg[0]), int(xs_with_fg[-1])
    side_margin = max(20, int(w * 0.03))
    in_zone_x = np.zeros(w, dtype=bool)
    in_zone_x[max(0, fg_left - side_margin) : min(w, fg_right + side_margin + 1)] = True

    shadow_radius_px = max(20.0, h * SHADOW_RADIUS_RATIO)
    ys_arr = np.arange(h, dtype=np.float32)[:, None]
    dy = ys_arr - ref_y[None, :]
    decay = np.exp(-3.0 * dy / shadow_radius_px)
    proximity = np.where((dy >= 0) & in_zone_x[None, :], decay, 0.0)

    darkness = np.clip(1.0 - lum / bg_lum, 0.0, 1.0)
    darkness = darkness * proximity
    factor = 1.0 - darkness * strength
    shadow = np.full_like(img_arr, 255.0)
    shadow *= factor[:, :, None]
    return Image.fromarray(np.clip(shadow, 0, 255).astype(np.uint8))


def _product_alpha(
    image: Image.Image, rembg_alpha: Image.Image
) -> tuple[Image.Image, Image.Image, np.ndarray]:
    """Finalna alpha + binarna maska produktu z maski rembg.

    Dual-path w zaleznosci od jasnosci tla (bg_lum > 200 = light_bg,
    typowy bialy stol):
    - light bg: alpha liczona WYLACZNIE z luminancji obrazu (cubic falloff
      w [bg_lum*0.75, bg_lum*0.98]), binary to prog luminancji — rembg
      sluzy tu do pomiaru bg_lum i do ODSIANIA blobow, ktorych w ogole nie
      widzi (`_drop_rembg_rejected_blobs`: pylek na stole ma luminancje
      ponizej progu, wiec wchodzil do binary i rozdmuchiwal bbox — produkt
      ladowal przy krawedzi kadru). Dawny rozmiarowy blob-filter i
      fill-holes byly tu liczone i WYRZUCANE, wiec zostaly wyciete.
    - dark bg: alpha z rembg (region po _filter_small_blobs — ten dziala
      i zostaje) z kontrastem [FLOOR, CEILING] -> [0, 255]; fill-holes
      takze tu byl martwy (maska dziur zerowana przed uzyciem).

    Zwraca (alpha, binary, img_lum) — obrazy L w rozdzielczosci source oraz
    luminancje source'a (do reuse'u w `_image_bleed_edges`).
    """
    img_lum = np.array(image.convert("L"))
    bg_lum = _background_luminance(img_lum, np.array(rembg_alpha) < 32)
    light_bg = bg_lum > 200.0

    if light_bg:
        lo = bg_lum * 0.75
        hi = bg_lum * 0.98
        span = max(hi - lo, 1.0)
        t = np.clip((hi - img_lum.astype(np.float32)) / span, 0.0, 1.0)
        alpha_arr = t * t * t * 255.0
        binary_arr = img_lum < bg_lum * 0.90
        kept = _drop_rembg_rejected_blobs(binary_arr, np.array(rembg_alpha))
        if kept is not binary_arr:
            # Smiec wypada tez z alfy — inaczej pylek obok produktu zostalby
            # namalowany na bialym canvasie jako szara kropka.
            alpha_arr = np.where(binary_arr & ~kept, 0.0, alpha_arr)
        binary = Image.fromarray((kept.astype(np.uint8) * 255))
    else:
        filtered = _filter_small_blobs(np.array(_binarize(rembg_alpha)) > 0)
        alpha_arr = np.where(filtered, np.array(rembg_alpha), 0).astype(np.float32)
        floor = float(CLEAN_BG_ALPHA_FLOOR)
        ceiling = float(max(CLEAN_BG_ALPHA_CEILING, floor + 1.0))
        alpha_arr = np.clip((alpha_arr - floor) * (255.0 / (ceiling - floor)), 0.0, 255.0)
        binary = Image.fromarray((filtered.astype(np.uint8) * 255))

    return Image.fromarray(alpha_arr.astype(np.uint8)), binary, img_lum


# ---------- wybor okna cropu ----------
#
# Kazda funkcja _window_* zwraca okno cropu (sl, st, sr, sb) w pikselach
# source. Okno moze wystawac poza source — _compose_on_canvas dopelni
# brakujaca czesc bielem.


def _largest_window(src_w: int, src_h: int, canvas_aspect: float) -> tuple[float, float]:
    """Najwiekszy canvas-aspect prostokat mieszczacy sie w source."""
    src_aspect = src_w / max(src_h, 1)
    if src_aspect >= canvas_aspect:
        crop_h = float(src_h)
        crop_w = crop_h * canvas_aspect
    else:
        crop_w = float(src_w)
        crop_h = crop_w / canvas_aspect
    return crop_w, crop_h


def _window_double_bleed(
    bbox: Bbox, edges: dict, src_w: int, src_h: int, canvas_aspect: float
) -> Window:
    """Product bleeds on BOTH axes (e.g. a diagonal track crossing cut by all
    four source edges) — neither axis can be "fit" without exposing an
    amputated cut edge floating inside the canvas. Take the largest
    canvas-aspect window that stays fully inside the source: every bleeding
    cut edge lands at or past the canvas edge and visually continues
    off-frame."""
    l, t, r, b = bbox
    crop_w, crop_h = _largest_window(src_w, src_h, canvas_aspect)
    crop_w_int = int(round(crop_w))
    crop_h_int = int(round(crop_h))
    margin_src_x = crop_w * PRODUCT_MARGIN
    margin_src_y = crop_h * PRODUCT_MARGIN
    # Per-axis anchor: margin on the single non-bleeding side, bbox-centered
    # when both sides bleed.
    if edges["left"] and not edges["right"]:
        sl = int(round(r + margin_src_x)) - crop_w_int
    elif edges["right"] and not edges["left"]:
        sl = int(round(l - margin_src_x))
    else:
        sl = int(round((l + r) / 2.0 - crop_w / 2.0))
    if edges["top"] and not edges["bottom"]:
        st = int(round(b + margin_src_y)) - crop_h_int
    elif edges["bottom"] and not edges["top"]:
        st = int(round(t - margin_src_y))
    else:
        st = int(round((t + b) / 2.0 - crop_h / 2.0))
    # Clamp the window inside the source — white padding on a bleeding side
    # would reveal the cut edge.
    sl = max(0, min(sl, src_w - crop_w_int))
    st = max(0, min(st, src_h - crop_h_int))
    return sl, st, sl + crop_w_int, st + crop_h_int


def _window_bleed_fit_y(bbox: Bbox, edges: dict, canvas_aspect: float) -> Window:
    """Bbox wider than canvas AND product bleeds off at least one X edge in
    source — fit Y, X overflows off-canvas.
      Bleeding side: pin source edge (or bbox edge if rembg covers the source
      edge) to the matching canvas edge so bleed shows.
      Non-bleeding side: bbox edge + PRODUCT_MARGIN of clean canvas margin —
      logo lives in bottom-right, gets covered if bbox sits flush against
      canvas edge.

    Uses BLEED_FIT_MARGIN (~25–32%) instead of PRODUCT_MARGIN (~15%) because
    the wide-bleed case visually needs more breathing room. Clamp: if
    BLEED_FIT_MARGIN would pull crop_w past bbox width, the bleeding bbox
    edge slides AWAY from canvas edge (white margin appears, bleed
    disappears). Cap crop_w at bw so the bleeding side stays anchored."""
    l, t, r, b = bbox
    bw, bh = r - l, b - t
    bleed_inner = max(1e-3, 1.0 - 2.0 * BLEED_FIT_MARGIN)
    crop_h = bh / bleed_inner
    crop_w = crop_h * canvas_aspect
    if crop_w > bw:
        crop_w = float(bw)
        crop_h = crop_w / canvas_aspect
    crop_w_int = int(round(crop_w))
    crop_h_int = int(round(crop_h))
    margin_src_x = crop_w * PRODUCT_MARGIN
    margin_src_y = crop_h * PRODUCT_MARGIN
    if edges["left"] and not edges["right"]:
        sr = int(round(r + margin_src_x))
        sl = sr - crop_w_int
    elif edges["right"] and not edges["left"]:
        sl = int(round(l - margin_src_x))
        sr = sl + crop_w_int
    else:
        cx = (l + r) / 2.0
        sl = int(round(cx - crop_w / 2.0))
        sr = sl + crop_w_int
    if edges["bottom"] and not edges["top"]:
        sb = int(round(b + margin_src_y))
        st = sb - crop_h_int
    elif edges["top"] and not edges["bottom"]:
        st = int(round(t - margin_src_y))
        sb = st + crop_h_int
    else:
        cy = (t + b) / 2.0
        st = int(round(cy - crop_h / 2.0))
        sb = st + crop_h_int
    return sl, st, sr, sb


def _window_bleed_fit_x(bbox: Bbox, edges: dict, canvas_aspect: float) -> Window:
    """Symetrycznie do _window_bleed_fit_y: tall product + Y bleed — fit X,
    Y overflows off-canvas."""
    l, t, r, b = bbox
    bw, bh = r - l, b - t
    bleed_inner = max(1e-3, 1.0 - 2.0 * BLEED_FIT_MARGIN)
    crop_w = bw / bleed_inner
    crop_h = crop_w / canvas_aspect
    if crop_h > bh:
        crop_h = float(bh)
        crop_w = crop_h * canvas_aspect
    crop_w_int = int(round(crop_w))
    crop_h_int = int(round(crop_h))
    margin_src_x = crop_w * PRODUCT_MARGIN
    margin_src_y = crop_h * PRODUCT_MARGIN
    if edges["top"] and not edges["bottom"]:
        sb = int(round(b + margin_src_y))
        st = sb - crop_h_int
    elif edges["bottom"] and not edges["top"]:
        st = int(round(t - margin_src_y))
        sb = st + crop_h_int
    else:
        cy = (t + b) / 2.0
        st = int(round(cy - crop_h / 2.0))
        sb = st + crop_h_int
    if edges["right"] and not edges["left"]:
        sl = int(round(l - margin_src_x))
        sr = sl + crop_w_int
    elif edges["left"] and not edges["right"]:
        sr = int(round(r + margin_src_x))
        sl = sr - crop_w_int
    else:
        cx = (l + r) / 2.0
        sl = int(round(cx - crop_w / 2.0))
        sr = sl + crop_w_int
    return sl, st, sr, sb


def _window_small_product(
    bbox: Bbox, src_w: int, src_h: int, canvas_aspect: float
) -> Window:
    """Preserve natural source framing — crop a canvas-aspect window of the
    source's "natural" size (= biggest canvas-aspect rect that fits inside
    source). Product retains its source-frame size relative to canvas; no
    aggressive zoom-in."""
    l, t, r, b = bbox
    crop_w, crop_h = _largest_window(src_w, src_h, canvas_aspect)
    cx = (l + r) / 2.0
    cy = (t + b) / 2.0
    sl = int(round(cx - crop_w / 2.0))
    st = int(round(cy - crop_h / 2.0))
    sr = int(round(cx + crop_w / 2.0))
    sb = int(round(cy + crop_h / 2.0))
    return sl, st, sr, sb


def _window_fit_both(
    bbox: Bbox, edges: dict, src_w: int, src_h: int, canvas_aspect: float
) -> Window:
    """Standardowy fit-both: wiekszy wymiar bboxa dyktuje skale, produkt
    z PRODUCT_MARGIN ze wszystkich stron.

    A square-ish bbox with edge bleed lands here (the wide/tall gates miss
    it, ±5% tolerance). Anchor the crop window to the bleeding source edge so
    the raw cut lands exactly on the canvas edge and the product visually
    continues off-frame — centering instead would float the amputated cut
    edge above a white margin. Non-bleeding sides keep the regular
    centering."""
    l, t, r, b = bbox
    bw, bh = r - l, b - t
    inner = max(1e-3, 1.0 - 2.0 * PRODUCT_MARGIN)
    target_w = bw / inner
    target_h = bh / inner
    if target_w / max(target_h, 1e-3) > canvas_aspect:
        crop_w = target_w
        crop_h = crop_w / canvas_aspect
    else:
        crop_h = target_h
        crop_w = crop_h * canvas_aspect
    if edges["top"] and edges["bottom"] and crop_h > src_h:
        crop_h = float(src_h)
        crop_w = crop_h * canvas_aspect
    if edges["left"] and edges["right"] and crop_w > src_w:
        crop_w = float(src_w)
        crop_h = crop_w / canvas_aspect
    cx = (l + r) / 2.0
    cy = (t + b) / 2.0
    crop_w_int = int(round(crop_w))
    crop_h_int = int(round(crop_h))
    if edges["left"] and not edges["right"]:
        sl = 0
    elif edges["right"] and not edges["left"]:
        sl = src_w - crop_w_int
    else:
        sl = int(round(cx - crop_w / 2.0))
        if edges["left"] and edges["right"]:
            sl = max(0, min(sl, src_w - crop_w_int))
    if edges["top"] and not edges["bottom"]:
        st = 0
    elif edges["bottom"] and not edges["top"]:
        st = src_h - crop_h_int
    else:
        st = int(round(cy - crop_h / 2.0))
        if edges["top"] and edges["bottom"]:
            st = max(0, min(st, src_h - crop_h_int))
    return sl, st, sl + crop_w_int, st + crop_h_int


def _window_zoom_only(
    bbox: Bbox, src_w: int, src_h: int, canvas_aspect: float
) -> Window:
    """Zoom bez centrowania: okno cropu zoomowane do bboxa (jak fit-both),
    ale kotwiczone proporcjonalnie do pozycji produktu w source — produkt
    odsuniety od srodka kadru zostaje odsuniety w canvy."""
    l, t, r, b = bbox
    bw, bh = r - l, b - t
    inner = max(1e-3, 1.0 - 2.0 * PRODUCT_MARGIN)
    target_w = bw / inner
    target_h = bh / inner
    if target_w / max(target_h, 1e-3) > canvas_aspect:
        crop_w = target_w
        crop_h = crop_w / canvas_aspect
    else:
        crop_h = target_h
        crop_w = crop_h * canvas_aspect
    if crop_w > src_w or crop_h > src_h:
        shrink = min(src_w / crop_w, src_h / crop_h)
        crop_w *= shrink
        crop_h *= shrink
    crop_w_int = int(round(crop_w))
    crop_h_int = int(round(crop_h))
    cx = (l + r) / 2.0
    cy = (t + b) / 2.0
    sl = int(round(cx * (1.0 - crop_w / src_w)))
    st = int(round(cy * (1.0 - crop_h / src_h)))
    # Okno musi objac caly bbox (crop >= bbox, wiec zawsze mozliwe) —
    # inaczej produkt przy krawedzi kadru zostalby uciety.
    sl = max(min(sl, l), r - crop_w_int)
    st = max(min(st, t), b - crop_h_int)
    sl = max(0, min(sl, src_w - crop_w_int))
    st = max(0, min(st, src_h - crop_h_int))
    return sl, st, sl + crop_w_int, st + crop_h_int


def _window_center_only(
    bbox: Bbox, src_w: int, src_h: int, canvas_aspect: float
) -> Window:
    """Centrowanie bez zoomu: naturalne okno (najwiekszy canvas-aspect
    prostokat w source) wycentrowane na bboxie produktu, clamp do source."""
    l, t, r, b = bbox
    crop_w, crop_h = _largest_window(src_w, src_h, canvas_aspect)
    crop_w_int = int(round(crop_w))
    crop_h_int = int(round(crop_h))
    cx = (l + r) / 2.0
    cy = (t + b) / 2.0
    sl = int(round(cx - crop_w / 2.0))
    st = int(round(cy - crop_h / 2.0))
    sl = max(0, min(sl, src_w - crop_w_int))
    st = max(0, min(st, src_h - crop_h_int))
    return sl, st, sl + crop_w_int, st + crop_h_int


def _window_plain_center(src_w: int, src_h: int, canvas_aspect: float) -> Window:
    """Centralny crop sensora bez patrzenia na produkt (zoom OFF + center
    OFF = swiadome "nie ruszaj nic")."""
    if src_w / src_h > canvas_aspect:
        crop_h = src_h
        crop_w = int(round(src_h * canvas_aspect))
    else:
        crop_w = src_w
        crop_h = int(round(src_w / canvas_aspect))
    sl = (src_w - crop_w) // 2
    st = (src_h - crop_h) // 2
    return sl, st, sl + crop_w, st + crop_h


def _select_crop_window(
    image: Image.Image,
    alpha: Image.Image,
    bbox: Bbox,
    canvas_aspect: float,
    auto_center: bool,
    auto_zoom: bool,
    img_lum: np.ndarray | None = None,
) -> Window:
    """Wybiera okno cropu wg toggli zoom/center, a przy obu ON — wg sygnalow
    z kadru (bleed na krawedziach, ksztalt i rozmiar bboxa)."""
    src_w, src_h = image.size
    if not auto_center and not auto_zoom:
        return _window_plain_center(src_w, src_h, canvas_aspect)
    if auto_zoom and not auto_center:
        return _window_zoom_only(bbox, src_w, src_h, canvas_aspect)
    if auto_center and not auto_zoom:
        return _window_center_only(bbox, src_w, src_h, canvas_aspect)

    l, t, r, b = bbox
    bw, bh = r - l, b - t
    edges = _image_bleed_edges(image, alpha, img_lum)
    any_x_bleed = edges["left"] or edges["right"]
    any_y_bleed = edges["top"] or edges["bottom"]
    bbox_aspect = bw / max(bh, 1)
    wide_product = bbox_aspect > canvas_aspect * 1.05
    tall_product = bbox_aspect < canvas_aspect / 1.05
    # "Small product" = bbox occupies < 30% of either source dimension.
    # Operator deliberately framed it small, so preserve natural source
    # composition instead of aggressively scaling bbox to 70% canvas.
    # Small LEGO 2x2 tile would otherwise be upscaled ~1.75× and look like
    # a giant tile. Bleed-fit is skipped, bo male produkty nie bleeduja.
    small_product = max(bw / src_w, bh / src_h) < 0.30

    if any_x_bleed and any_y_bleed and not small_product:
        return _window_double_bleed(bbox, edges, src_w, src_h, canvas_aspect)
    if wide_product and any_x_bleed and not small_product:
        return _window_bleed_fit_y(bbox, edges, canvas_aspect)
    if tall_product and any_y_bleed and not small_product:
        return _window_bleed_fit_x(bbox, edges, canvas_aspect)
    if small_product:
        return _window_small_product(bbox, src_w, src_h, canvas_aspect)
    return _window_fit_both(bbox, edges, src_w, src_h, canvas_aspect)


def _compose_on_canvas(
    img: Image.Image,
    alpha: Image.Image,
    window: Window,
    canvas_size: tuple[int, int],
) -> Image.Image:
    """Wycina okno z source (czesc poza source = biale dopelnienie), skaluje
    do canvas, sharpen na sub-obrazie PRZED paste'em (biale tlo zostaje
    czyste, bez halo na alpha-edge), opcjonalny cien, kompozyt przez
    zblurowana alfe."""
    sl, st, sr, sb = window
    canvas_w, canvas_h = canvas_size
    img_w, img_h = img.size

    crop_w = sr - sl
    crop_h = sb - st
    csl = max(0, sl)
    cst = max(0, st)
    csr = min(img_w, sr)
    csb = min(img_h, sb)

    canvas_white = Image.new("RGB", canvas_size, CLEAN_BG_COLOR)
    img_canvas = Image.new("RGB", canvas_size, CLEAN_BG_COLOR)
    alpha_canvas = Image.new("L", canvas_size, 0)
    if csr > csl and csb > cst:
        scale_x = canvas_w / crop_w
        scale_y = canvas_h / crop_h
        dst_l = int(round((csl - sl) * scale_x))
        dst_t = int(round((cst - st) * scale_y))
        dst_r = int(round((csr - sl) * scale_x))
        dst_b = int(round((csb - st) * scale_y))
        dst_w = max(1, dst_r - dst_l)
        dst_h = max(1, dst_b - dst_t)
        sub_img = img.resize((dst_w, dst_h), Image.LANCZOS, box=(csl, cst, csr, csb))
        sub_alpha = alpha.resize((dst_w, dst_h), Image.LANCZOS, box=(csl, cst, csr, csb))
        if SHARPEN_PERCENT > 0:
            sub_img = sub_img.filter(
                ImageFilter.UnsharpMask(radius=1.5, percent=SHARPEN_PERCENT, threshold=3)
            )
        img_canvas.paste(sub_img, (dst_l, dst_t))
        alpha_canvas.paste(sub_alpha, (dst_l, dst_t))

    soft_mask = alpha_canvas
    if CLEAN_BG_EDGE_BLUR > 0:
        soft_mask = soft_mask.filter(ImageFilter.GaussianBlur(CLEAN_BG_EDGE_BLUR))

    if SHADOW_STRENGTH > 0:
        shadow_layer = _build_shadow_layer(img_canvas, alpha_canvas, SHADOW_STRENGTH)
        canvas_white.paste(shadow_layer, (0, 0))
    canvas_white.paste(img_canvas, (0, 0), mask=soft_mask)
    return canvas_white


def clean_background(
    image: Image.Image,
    canvas_size: tuple[int, int],
    auto_center: bool = AUTO_CENTER,
    auto_zoom: bool = AUTO_ZOOM,
) -> Image.Image:
    from rembg import remove

    canvas_w, canvas_h = canvas_size
    src_w, src_h = image.size

    # Pomiar per etap idzie do logu — "czemu obrobka trwa" ma byc do
    # odczytania z jednej linii, a nie do zgadywania (na maszynie operatora
    # rozklad potrafi wygladac zupelnie inaczej niz na maszynie dev).
    times: list[tuple[str, float]] = []
    t0 = time.perf_counter()

    def _mark(label: str) -> None:
        nonlocal t0
        now = time.perf_counter()
        times.append((label, now - t0))
        t0 = now

    if max(src_w, src_h) > CLEAN_BG_INFERENCE_SIZE:
        infer_img = image.resize(
            (CLEAN_BG_INFERENCE_SIZE, CLEAN_BG_INFERENCE_SIZE), Image.LANCZOS
        )
    else:
        infer_img = image
    rgba = remove(infer_img.convert("RGBA"), session=_session(CLEAN_BG_MODEL))
    rembg_alpha = rgba.split()[3].resize((src_w, src_h), Image.LANCZOS)
    _mark("rembg")

    alpha, binary, img_lum = _product_alpha(image, rembg_alpha)
    _mark("maska")
    img = _lift_internal_shadows(image.convert("RGB"), alpha, SHADOW_STRENGTH)

    bbox = _mask_bbox(binary)
    if bbox is None:
        return Image.new("RGB", canvas_size, CLEAN_BG_COLOR)

    window = _select_crop_window(
        image, alpha, bbox, canvas_w / canvas_h, auto_center, auto_zoom, img_lum
    )
    _mark("kadr")
    result = _compose_on_canvas(img, alpha, window, canvas_size)
    _mark("kompozyt")
    total = sum(dt for _, dt in times)
    detail = ", ".join(f"{label} {dt:.1f} s" for label, dt in times)
    print(f"Czyszczenie tła: {total:.1f} s ({detail})")
    return result
