import math
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

if getattr(sys, "frozen", False):
    # PyInstaller: __file__ wskazuje na rozpakowane _internal/_MEIPASS —
    # .env i photos/ maja zyc obok .exe, nie w katalogu tymczasowym.
    PROJECT_DIR = Path(sys.executable).resolve().parent
    # macOS: plik wykonywalny siedzi w „Camera Capture.app/Contents/MacOS".
    # Do wnetrza paczki .app nie wolno pisac (i nikt tam nie zajrzy), wiec
    # .env, photos/ i EDSDK.framework leza OBOK Camera Capture.app.
    if sys.platform == "darwin" and PROJECT_DIR.name == "MacOS" \
            and PROJECT_DIR.parent.parent.suffix == ".app":
        PROJECT_DIR = PROJECT_DIR.parent.parent.parent
else:
    PROJECT_DIR = Path(__file__).resolve().parent.parent

APP_NAME = "Trixbrix - Camera Capture"
APP_AUTHOR = "Michał Krzysteczko"

load_dotenv(PROJECT_DIR / ".env")
# Zasoby (logo) sa bundlowane przez PyInstaller do _internal (_MEIPASS) —
# inny korzen niz .env/photos, ktore zyja obok .exe.
if getattr(sys, "frozen", False):
    DEFAULT_ASSETS_DIR = Path(getattr(sys, "_MEIPASS", PROJECT_DIR)) / "assets"
else:
    DEFAULT_ASSETS_DIR = PROJECT_DIR / "assets"
# Logo do wyboru w Postprocessingu. Kazde ma wlasny rozmiar i krycie, bo pliki
# sa rozne: czarne TRIXBRIX.eu przyciemnia sie kryciem, szare KIDS jest juz
# w docelowym kolorze (#8f8f8f) i kryje w 100% (tak wyglada wzorzec).
# Wybor zapisuje sie w .env jako LOGO.
LOGOS = {
    "trixbrix": {"label": "TRIXBRIX.eu", "file": DEFAULT_ASSETS_DIR / "logos" / "trixbrix_eu.webp",
                 "height": 0.06, "opacity": 0.5},
    "kids": {"label": "TRIXBRIX.eu KIDS", "file": DEFAULT_ASSETS_DIR / "logos" / "trixbrix_kids.webp",
             "height": 0.10, "opacity": 1.0},
}
LOGO_CHOICE = os.environ.get("LOGO", "kids").strip().lower()
if LOGO_CHOICE not in LOGOS:
    LOGO_CHOICE = "kids"
DEFAULT_LOGO = LOGOS[LOGO_CHOICE]["file"]
DEFAULT_OUTPUT_DIR = PROJECT_DIR / "photos"

ASPECT_W, ASPECT_H = 1, 1
OUTPUT_SIZE = 3000
LOGO_ENABLED = True
LOGO_POSITION = "bottom-right"  # bottom-right / bottom-left / top-right / top-left
# Rozmiar i krycie pliku spoza LOGOS (wlasny plik z Ustawien albo --logo)
LOGO_HEIGHT_RATIO = 0.06
LOGO_MARGIN_RATIO = 0.04
LOGO_OPACITY = 0.5  # stale krycie watermarku — celowo bez mozliwosci zmiany w UI
JPEG_QUALITY = 95

# Canon EDSDK (jedyny sterownik aparatu): sciezka do EDSDK.dll albo katalogu
# z nia; bez tego szukana obok aplikacji (PROJECT_DIR i PROJECT_DIR/edsdk).
EDSDK_DLL = os.environ.get("EDSDK_DLL", "").strip() or None
# EDSDK w osobnym procesie (src/camera_proc.py): zawieszke w DLL-u Canona
# konczy zabicie dziecka i swiezy EdsInitializeSDK, zamiast martwej aplikacji.
# false = stary tryb, SDK w procesie aplikacji.
CAMERA_EDSDK_ISOLATION = os.environ.get("CAMERA_EDSDK_ISOLATION", "true").lower() in ("1", "true", "yes", "on")

CLEAN_BG_MODEL = "u2netp"
CLEAN_BG_INFERENCE_SIZE = 768
# Inferencja rembg na GPU, jesli onnxruntime ma odpowiedni provider
# (na Windowsie DirectML z paczki onnxruntime-directml — dziala na kazdym
# GPU przez DirectX 12, bez instalowania CUDA). `false` = wymus CPU,
# kill-switch na wypadek smiesznych sterownikow.
CLEAN_BG_GPU = os.environ.get("CLEAN_BG_GPU", "true").lower() in ("1", "true", "yes", "on")
# FPS podglądu przy starcie. Wybor z Ustawien jest zapisywany tutaj przez
# persist_env, wiec przezywa restart — na maszynach z kaprysnym USB operator
# zjezdza na 10 fps i ma to zostac na stale, nie do najblizszego zamkniecia.
PREVIEW_FPS = max(1, min(30, int(os.environ.get("PREVIEW_FPS", "30"))))
# Motyw UI aplikacji okienkowej: "dark" (domyslny) / "light". Trzymany w .env,
# nie w localStorage — port backendu jest losowy per uruchomienie, wiec origin
# (a z nim localStorage) zmienia sie przy kazdym starcie.
UI_THEMES = ("dark", "light")
UI_THEME = os.environ.get("UI_THEME", "dark").strip().lower()
if UI_THEME not in UI_THEMES:
    UI_THEME = "dark"
CLEAN_BG_COLOR = (255, 255, 255)
CLEAN_BG_MASK_THRESHOLD = 80
CLEAN_BG_EDGE_BLUR = 0.6
CLEAN_BG_ALPHA_FLOOR = 40
CLEAN_BG_ALPHA_CEILING = 200

AUTO_CENTER = True
AUTO_ZOOM = True
PRODUCT_MARGIN = 0.15
BLEED_FIT_MARGIN = 0.28

SHADOW_STRENGTH = 0.0
SHADOW_RADIUS_RATIO = 0.20

SHARPEN_PERCENT = 120

# Lokalny kosz (photos/.trash): zdjecia i sesje skasowane w aplikacji nie znikaja
# od razu, tylko po tylu dniach. 0 = kasowanie natychmiastowe (bez kosza).
TRASH_RETENTION_DAYS = int(os.environ.get("TRASH_RETENTION_DAYS", "30"))

# Oryginaly z aparatu (photos/<sesja>/raw) starsze niz tyle dni sa kasowane
# razem z kopia bez logo (.nologo) — potem logo na tym zdjeciu juz sie nie
# zmieni. 0 = trzymane zawsze. Domyslnie 90 dni; wybor z Ustawien zapisuje sie
# w .env i od tej pory to on obowiazuje.
RAW_RETENTION_CHOICES = (7, 30, 90, 0)
RAW_RETENTION_DAYS = int(os.environ.get("RAW_RETENTION_DAYS", "90") or 0)
if RAW_RETENTION_DAYS not in RAW_RETENTION_CHOICES:
    RAW_RETENTION_DAYS = 90

AUTOMAT_BASE_URL = os.environ.get("AUTOMAT_URL", "http://localhost:3000")
AUTOMAT_API_TOKEN = os.environ.get("AUTOMAT_TOKEN")
AUTOMAT_UPLOAD_ENABLED = os.environ.get("AUTOMAT_UPLOAD_ENABLED", "true").lower() in ("1", "true", "yes", "on")


def persist_env(key: str, value: str) -> None:
    """Zapisuje/nadpisuje klucz w PROJECT_DIR/.env (tworzy plik gdy brak) —
    wartosci wpisane w Ustawieniach GUI przezywaja restart aplikacji."""
    path = PROJECT_DIR / ".env"
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    entry = f"{key}={value}"
    for i, ln in enumerate(lines):
        if ln.split("=", 1)[0].strip() == key:
            lines[i] = entry
            break
    else:
        lines.append(entry)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
