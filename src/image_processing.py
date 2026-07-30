import shutil
from datetime import datetime
from pathlib import Path

from PIL import Image

from .config import (
    ASPECT_H,
    ASPECT_W,
    AUTO_CENTER,
    AUTO_ZOOM,
    JPEG_QUALITY,
    LOGO_ENABLED,
    LOGO_HEIGHT_RATIO,
    LOGO_MARGIN_RATIO,
    LOGO_OPACITY,
    LOGO_POSITION,
    OUTPUT_SIZE,
)

LOGO_POSITIONS = ("bottom-right", "bottom-left", "top-right", "top-left")


def crop_to_aspect(image: Image.Image, aspect_w: int, aspect_h: int) -> Image.Image:
    src_w, src_h = image.size
    target_ratio = aspect_w / aspect_h
    src_ratio = src_w / src_h

    if src_ratio > target_ratio:
        new_w = int(src_h * target_ratio)
        new_h = src_h
        left = (src_w - new_w) // 2
        top = 0
    else:
        new_w = src_w
        new_h = int(src_w / target_ratio)
        left = 0
        top = (src_h - new_h) // 2

    return image.crop((left, top, left + new_w, top + new_h))


def overlay_logo(
    canvas: Image.Image, logo_path: Path, position: str = LOGO_POSITION
) -> Image.Image:
    if not logo_path.exists():
        print(f"Uwaga: logo nie znalezione w {logo_path} — pomijam overlay.")
        return canvas
    if position not in LOGO_POSITIONS:
        print(f"Uwaga: nieznana pozycja logo '{position}' — używam bottom-right.")
        position = "bottom-right"

    logo = Image.open(logo_path).convert("RGBA")
    canvas_w, canvas_h = canvas.size

    target_h = int(canvas_h * LOGO_HEIGHT_RATIO)
    scale = target_h / logo.height
    target_w = int(logo.width * scale)
    logo = logo.resize((target_w, target_h), Image.LANCZOS)

    if LOGO_OPACITY < 1.0:
        r, g, b, a = logo.split()
        a = a.point(lambda v: int(v * LOGO_OPACITY))
        logo = Image.merge("RGBA", (r, g, b, a))

    margin = int(canvas_w * LOGO_MARGIN_RATIO)
    x = margin if "left" in position else canvas_w - target_w - margin
    y = margin if "top" in position else canvas_h - target_h - margin

    canvas_rgba = canvas.convert("RGBA")
    canvas_rgba.alpha_composite(logo, dest=(x, y))
    return canvas_rgba.convert("RGB")


def process(
    input_path: Path,
    logo_path: Path,
    output_dir: Path,
    clean_bg: bool = False,
    add_logo: bool = LOGO_ENABLED,
    logo_position: str = LOGO_POSITION,
    auto_center: bool = AUTO_CENTER,
    auto_zoom: bool = AUTO_ZOOM,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    raw_path = output_dir / f"photo_{timestamp}_raw.jpg"
    shutil.copy2(input_path, raw_path)

    image = Image.open(input_path)

    target = (OUTPUT_SIZE, OUTPUT_SIZE) if ASPECT_W == ASPECT_H else None

    if clean_bg:
        from .background import clean_background

        canvas_size = target or (OUTPUT_SIZE, OUTPUT_SIZE)
        image = clean_background(
            image, canvas_size, auto_center=auto_center, auto_zoom=auto_zoom
        )
    else:
        image = crop_to_aspect(image, ASPECT_W, ASPECT_H)
        if target and image.size != target:
            image = image.resize(target, Image.LANCZOS)

    if add_logo:
        image = overlay_logo(image, logo_path, logo_position)

    out_path = output_dir / f"photo_{timestamp}.jpg"
    image.save(out_path, "JPEG", quality=JPEG_QUALITY)
    return out_path
