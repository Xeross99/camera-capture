import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_DIR / ".env")
DEFAULT_ASSETS_DIR = PROJECT_DIR / "assets"
DEFAULT_LOGO = DEFAULT_ASSETS_DIR / "logos" / "trixbrix_eu.webp"
DEFAULT_OUTPUT_DIR = PROJECT_DIR / "photos"

ASPECT_W, ASPECT_H = 1, 1
OUTPUT_SIZE = 1500
LOGO_HEIGHT_RATIO = 0.06
LOGO_MARGIN_RATIO = 0.04
LOGO_OPACITY = 0.5
JPEG_QUALITY = 95

CAMERA_IMAGE_FORMAT: str | None = "L"

CLEAN_BG_MODEL = "u2netp"
CLEAN_BG_INFERENCE_SIZE = 768
CLEAN_BG_COLOR = (255, 255, 255)
CLEAN_BG_MASK_THRESHOLD = 160
CLEAN_BG_EDGE_BLUR = 0.6

AUTO_CENTER = True
PRODUCT_MARGIN = 0.15

SHADOW_STRENGTH = 0.0
SHADOW_RADIUS_RATIO = 0.20

SHARPEN_PERCENT = 120

AUTOMAT_BASE_URL = os.environ.get("AUTOMAT_URL", "http://localhost:3000")
AUTOMAT_API_TOKEN = os.environ.get("AUTOMAT_TOKEN")
AUTOMAT_UPLOAD_ENABLED = os.environ.get("AUTOMAT_UPLOAD_ENABLED", "true").lower() in ("1", "true", "yes", "on")
