from functools import lru_cache

import numpy as np
from PIL import Image, ImageFilter
from scipy import ndimage

from .config import (
    AUTO_CENTER,
    BLEED_FIT_MARGIN,
    CLEAN_BG_ALPHA_CEILING,
    CLEAN_BG_ALPHA_FLOOR,
    CLEAN_BG_COLOR,
    CLEAN_BG_EDGE_BLUR,
    CLEAN_BG_INFERENCE_SIZE,
    CLEAN_BG_MASK_THRESHOLD,
    CLEAN_BG_MODEL,
    PRODUCT_MARGIN,
    SHADOW_RADIUS_RATIO,
    SHADOW_STRENGTH,
    SHARPEN_PERCENT,
)


@lru_cache(maxsize=1)
def _session(model_name: str):
    from rembg import new_session

    return new_session(model_name)


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


def _mask_bbox(mask: Image.Image):
    arr = np.array(mask) > 128
    if not arr.any():
        return None
    rows = np.where(arr.any(axis=1))[0]
    cols = np.where(arr.any(axis=0))[0]
    return int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1


def _image_bleed_edges(image: Image.Image, alpha: Image.Image) -> dict:
    """Detect which raw-image edges have product bleeding off-frame.

    Looks at a 0.5%-thick strip from each edge of the source image (not the
    mask — u2netp @ 768 inference often clips thin extensions, so the mask
    underreports). Counts pixels darker than 70% of background luminance; if
    a strip has at least 50 such pixels we call that edge bleeding.
    """
    img_arr = np.array(image.convert("L"))
    h, w = img_arr.shape

    alpha_arr = np.array(alpha)
    bg = alpha_arr < 32
    if bg.sum() > 1000:
        bg_lum = float(np.percentile(img_arr[bg], 90))
    else:
        bg_lum = float(np.percentile(img_arr, 95))
    bg_lum = max(bg_lum, 1.0)

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
    img_arr = np.array(img.convert("RGB")).astype(np.float32)
    lum = img_arr.mean(axis=2)
    bg_mask = np.array(alpha) < 32
    if bg_mask.sum() > 1000:
        bg_lum = float(np.percentile(lum[bg_mask], 90))
    else:
        bg_lum = float(np.percentile(lum, 95))
    bg_lum = max(bg_lum, 1.0)
    darkness = np.clip(1.0 - lum / bg_lum, 0.0, 1.0)
    shadow_on_bg = np.clip((lum / bg_lum - 0.55) / 0.4, 0.0, 1.0)
    lift = darkness * shadow_on_bg * strength
    lifted = img_arr * (1.0 - lift[:, :, None]) + 255.0 * lift[:, :, None]
    return Image.fromarray(np.clip(lifted, 0, 255).astype(np.uint8))


def _build_shadow_layer(
    img: Image.Image, alpha: Image.Image, strength: float
) -> Image.Image:
    img_arr = np.array(img.convert("RGB")).astype(np.float32)
    h, w, _ = img_arr.shape
    lum = img_arr.mean(axis=2)

    fg = np.array(alpha) > 128
    if not fg.any():
        return Image.fromarray(np.full_like(img_arr, 255, dtype=np.uint8))

    bg_mask = np.array(alpha) < 32
    if bg_mask.sum() > 1000:
        bg_lum = float(np.percentile(lum[bg_mask], 90))
    else:
        bg_lum = float(np.percentile(lum, 95))
    bg_lum = max(bg_lum, 1.0)

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


def clean_background(image: Image.Image, canvas_size: tuple[int, int]) -> Image.Image:
    from rembg import remove

    canvas_w, canvas_h = canvas_size
    src_w, src_h = image.size

    if max(src_w, src_h) > CLEAN_BG_INFERENCE_SIZE:
        infer_img = image.resize(
            (CLEAN_BG_INFERENCE_SIZE, CLEAN_BG_INFERENCE_SIZE), Image.LANCZOS
        )
    else:
        infer_img = image

    rgba = remove(infer_img.convert("RGBA"), session=_session(CLEAN_BG_MODEL))
    small_alpha = rgba.split()[3]
    alpha = small_alpha.resize((src_w, src_h), Image.LANCZOS)
    binary = _binarize(alpha)

    binary_arr = np.array(binary) > 0
    filtered = _filter_small_blobs(binary_arr)
    img_lum = np.array(image.convert("L"))
    bg_mask_for_lum = np.array(alpha) < 32
    if bg_mask_for_lum.sum() > 1000:
        bg_lum = float(np.percentile(img_lum[bg_mask_for_lum], 90))
    else:
        bg_lum = float(np.percentile(img_lum, 95))
    bg_lum = max(bg_lum, 1.0)
    # Luminance gate — only apply when bg is clearly light (typical
    # white-tabletop product photography). For dark/colored bg we'd be
    # inverting product/bg polarity (e.g., white LEGO tile on dark surface
    # has white product pixels which are FAR from dark bg_lum but the
    # naive "img_lum > bg_lum*0.75" check would still drop them, blowing
    # away the product). bg_lum > 200 is a safe gate threshold.
    light_bg = bg_lum > 200.0
    pre_lum_filtered = filtered
    if light_bg:
        bg_like = img_lum > bg_lum * 0.95
        filtered = filtered & ~bg_like
    fully_filled = ndimage.binary_fill_holes(filtered)
    candidate_holes = fully_filled & ~filtered
    if light_bg:
        fill_holes_mask = candidate_holes & (img_lum < bg_lum * 0.6)
    else:
        fill_holes_mask = np.zeros_like(candidate_holes)
    filled = filtered | fill_holes_mask
    alpha_raw = np.array(alpha)
    if light_bg:
        # Luminance-based alpha: dark pixels → opaque, bright → transparent.
        # rembg is only used for product region detection (dilated), not alpha.
        lo = bg_lum * 0.75
        hi = bg_lum * 0.98
        span = max(hi - lo, 1.0)
        t = np.clip((hi - img_lum.astype(np.float32)) / span, 0.0, 1.0)
        alpha_arr = (t * t * t * 255.0).astype(np.float32)
        binary = Image.fromarray(((img_lum < bg_lum * 0.90).astype(np.uint8) * 255))
    else:
        alpha_arr = np.where(filtered, alpha_raw, 0).astype(np.float32)
        alpha_arr = np.where(fill_holes_mask, 255.0, alpha_arr)
        floor = float(CLEAN_BG_ALPHA_FLOOR)
        ceiling = float(max(CLEAN_BG_ALPHA_CEILING, floor + 1.0))
        alpha_arr = np.clip((alpha_arr - floor) * (255.0 / (ceiling - floor)), 0.0, 255.0)
        binary = Image.fromarray((filled.astype(np.uint8) * 255))
    alpha = Image.fromarray(alpha_arr.astype(np.uint8))

    img = _lift_internal_shadows(image.convert("RGB"), alpha, SHADOW_STRENGTH)

    canvas_white = Image.new("RGB", canvas_size, CLEAN_BG_COLOR)
    bbox = _mask_bbox(binary)
    if bbox is None:
        return canvas_white

    img_w, img_h = img.size
    canvas_aspect = canvas_w / canvas_h

    if AUTO_CENTER:
        l, t, r, b = bbox
        bw, bh = r - l, b - t
        inner = max(1e-3, 1.0 - 2.0 * PRODUCT_MARGIN)
        bleed_inner = max(1e-3, 1.0 - 2.0 * BLEED_FIT_MARGIN)
        edges = _image_bleed_edges(image, alpha)
        any_x_bleed = edges["left"] or edges["right"]
        any_y_bleed = edges["top"] or edges["bottom"]
        bbox_aspect = bw / max(bh, 1)
        wide_product = bbox_aspect > canvas_aspect * 1.05
        tall_product = bbox_aspect < canvas_aspect / 1.05
        # "Small product" = bbox occupies < 30% of either source dimension.
        # Operator deliberately framed it small, so preserve natural source
        # composition instead of aggressively scaling bbox to 70% canvas
        # (current auto-center). Small LEGO 2x2 tile would otherwise be
        # upscaled ~1.75× and look like a giant tile.
        product_fill_ratio = max(bw / src_w, bh / src_h)
        small_product = product_fill_ratio < 0.30

        if any_x_bleed and any_y_bleed and not small_product:
            # Product bleeds on BOTH axes (e.g. a diagonal track crossing
            # cut by all four source edges) — neither axis can be "fit"
            # without exposing an amputated cut edge floating inside the
            # canvas. Take the largest canvas-aspect window that stays
            # fully inside the source: every bleeding cut edge lands at or
            # past the canvas edge and visually continues off-frame.
            src_aspect = src_w / max(src_h, 1)
            if src_aspect >= canvas_aspect:
                crop_h = float(src_h)
                crop_w = crop_h * canvas_aspect
            else:
                crop_w = float(src_w)
                crop_h = crop_w / canvas_aspect
            crop_w_int = int(round(crop_w))
            crop_h_int = int(round(crop_h))
            margin_src_x = crop_w * PRODUCT_MARGIN
            margin_src_y = crop_h * PRODUCT_MARGIN
            # Per-axis anchor: margin on the single non-bleeding side,
            # bbox-centered when both sides bleed.
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
            # Clamp the window inside the source — white padding on a
            # bleeding side would reveal the cut edge.
            sl = max(0, min(sl, src_w - crop_w_int))
            st = max(0, min(st, src_h - crop_h_int))
            sr = sl + crop_w_int
            sb = st + crop_h_int
        elif wide_product and any_x_bleed and not small_product:
            # Bbox wider than canvas AND product bleeds off at least one X
            # edge in source — fit Y, X overflows off-canvas.
            #   Bleeding side: pin source edge (or bbox edge if rembg covers
            #   the source edge) to the matching canvas edge so bleed shows.
            #   Non-bleeding side: pin bbox edge to canvas edge (no fixed
            #   margin — natural source bg above bbox fills the rest).
            #
            # Uses BLEED_FIT_MARGIN (~25–32%) instead of PRODUCT_MARGIN
            # (~15%) because the wide-bleed case visually needs more
            # breathing room. Clamp: if BLEED_FIT_MARGIN would pull crop_w
            # past bbox width, the bleeding bbox edge slides AWAY from
            # canvas edge (white margin appears, bleed disappears). Cap
            # crop_w at bw so the bleeding side stays anchored.
            crop_h = bh / bleed_inner
            crop_w = crop_h * canvas_aspect
            if crop_w > bw:
                crop_w = float(bw)
                crop_h = crop_w / canvas_aspect
            crop_w_int = int(round(crop_w))
            crop_h_int = int(round(crop_h))
            margin_src_x = crop_w * PRODUCT_MARGIN
            margin_src_y = crop_h * PRODUCT_MARGIN
            # Anchor non-bleeding bbox edge with PRODUCT_MARGIN of clean
            # canvas margin — logo lives in bottom-right, gets covered if
            # bbox sits flush against canvas edge.
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
        elif tall_product and any_y_bleed and not small_product:
            # Symmetric: fit X, Y overflows.
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
        elif small_product:
            # Preserve natural source framing — crop a canvas-aspect window
            # of the source's "natural" size (= biggest canvas-aspect rect
            # that fits inside source). Product retains its source-frame
            # size relative to canvas; no aggressive zoom-in.
            src_aspect = src_w / max(src_h, 1)
            if src_aspect >= canvas_aspect:
                crop_h = float(src_h)
                crop_w = crop_h * canvas_aspect
            else:
                crop_w = float(src_w)
                crop_h = crop_w / canvas_aspect
            cx = (l + r) / 2.0
            cy = (t + b) / 2.0
            sl = int(round(cx - crop_w / 2.0))
            st = int(round(cy - crop_h / 2.0))
            sr = int(round(cx + crop_w / 2.0))
            sb = int(round(cy + crop_h / 2.0))
        else:
            target_w = bw / inner
            target_h = bh / inner
            if target_w / max(target_h, 1e-3) > canvas_aspect:
                crop_w = target_w
                crop_h = crop_w / canvas_aspect
            else:
                crop_h = target_h
                crop_w = crop_h * canvas_aspect
            # A square-ish bbox with edge bleed lands here (the wide/tall
            # gates miss it, ±5% tolerance). Anchor the crop window to the
            # bleeding source edge so the raw cut lands exactly on the
            # canvas edge and the product visually continues off-frame —
            # centering instead would float the amputated cut edge above a
            # white margin. Non-bleeding sides keep the regular centering.
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
            sr = sl + crop_w_int
            sb = st + crop_h_int
    else:
        if img_w / img_h > canvas_aspect:
            crop_h = img_h
            crop_w = int(round(img_h * canvas_aspect))
        else:
            crop_w = img_w
            crop_h = int(round(img_w / canvas_aspect))
        sl = (img_w - crop_w) // 2
        st = (img_h - crop_h) // 2
        sr = sl + crop_w
        sb = st + crop_h

    crop_w = sr - sl
    crop_h = sb - st
    csl = max(0, sl)
    cst = max(0, st)
    csr = min(img_w, sr)
    csb = min(img_h, sb)

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
