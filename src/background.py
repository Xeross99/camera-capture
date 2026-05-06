from functools import lru_cache

import numpy as np
from PIL import Image, ImageFilter
from scipy import ndimage

from .config import (
    AUTO_CENTER,
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
    alpha = Image.fromarray(
        np.where(filtered, np.array(alpha), 0).astype(np.uint8)
    )
    binary = Image.fromarray((filtered.astype(np.uint8) * 255))

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
        target_w = bw / inner
        target_h = bh / inner
        if target_w / max(target_h, 1e-3) > canvas_aspect:
            crop_w = target_w
            crop_h = crop_w / canvas_aspect
        else:
            crop_h = target_h
            crop_w = crop_h * canvas_aspect
        cx = (l + r) / 2.0
        cy = (t + b) / 2.0
        sl = int(round(cx - crop_w / 2.0))
        st = int(round(cy - crop_h / 2.0))
        sr = int(round(cx + crop_w / 2.0))
        sb = int(round(cy + crop_h / 2.0))
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
