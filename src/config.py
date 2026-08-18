import math
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

if getattr(sys, "frozen", False):
    # PyInstaller: __file__ wskazuje na rozpakowane _internal/_MEIPASS —
    # .env i photos/ maja zyc obok .exe, nie w katalogu tymczasowym.
    PROJECT_DIR = Path(sys.executable).resolve().parent
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
DEFAULT_LOGO = DEFAULT_ASSETS_DIR / "logos" / "trixbrix_eu.webp"
DEFAULT_OUTPUT_DIR = PROJECT_DIR / "photos"

ASPECT_W, ASPECT_H = 1, 1
OUTPUT_SIZE = 3000
LOGO_ENABLED = True
LOGO_POSITION = "bottom-right"  # bottom-right / bottom-left / top-right / top-left
LOGO_HEIGHT_RATIO = 0.06
LOGO_MARGIN_RATIO = 0.04
LOGO_OPACITY = 0.5  # stale krycie watermarku — celowo bez mozliwosci zmiany w UI
JPEG_QUALITY = 95

CAMERA_IMAGE_FORMAT: str | None = "L"

# Backend aparatu: "auto" (gphoto2 jesli dostepne; na Windows edsdk),
# "gphoto2" lub "edsdk". Backend digiCamControl usuniety (1.1.0).
CAMERA_BACKEND = os.environ.get("CAMERA_BACKEND", "auto").strip().lower()
# Canon EDSDK (jedyny backend Windows): sciezka do EDSDK.dll albo katalogu
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

# ---------- ramie RoArm-M2-S (src/robot.py) ----------
# Ujecie to ZAPISANE KATY PRZEGUBOW, nie punkt w przestrzeni. Sterowanie
# wspolrzednymi (`pose_ctrl`) liczy kinematyke odwrotna: dojezdza „gdzies
# blisko" (stad wpisy „dojechal z odchylka N mm") i dla tego samego punktu
# potrafi ulozyc ramie inaczej, zaleznie od tego, skad jechalo. Sterowanie
# katami nie ma zadnego z tych problemow — cel jest ta sama liczba za kazdym
# razem, wiec kadr jest powtarzalny. Cena: odleglosc i kat nie sa regulowane
# osobno, ujecie jest jedna pozycja i tyle.
#
# Ramienia zwykle nie ma na maszynie deweloperskiej, wiec brak portu/paczki to
# stan „rozlaczony" w UI, a nie blad startu.
ROBOT_ENABLED = os.environ.get("ROBOT_ENABLED", "true").lower() in ("1", "true", "yes", "on")
ROBOT_TYPE = os.environ.get("ROBOT_TYPE", "roarm_m2")
# Pusty = autodetekcja portu po VID plytki (patrz find_robot_port).
ROBOT_PORT = os.environ.get("ROBOT_PORT", "").strip() or None
ROBOT_BAUD = int(os.environ.get("ROBOT_BAUD", "115200"))

ROBOT_MOVE_TIMEOUT = float(os.environ.get("ROBOT_MOVE_TIMEOUT", "20"))
# Z jaka tolerancja uznajemy, ze przegub dojechal (stopnie). To NIE jest
# tolerancja pozycji: cel jest zawsze ten sam kat, wiec ugiecie pod ciezarem
# aparatu jest takie samo za kazdym razem i kadr sie nie rozjezdza.
ROBOT_JOINT_TOL = float(os.environ.get("ROBOT_JOINT_TOL", "3"))

# Predkosc i przyspieszenie ruchu (spd 1..4096, acc 1..254). Osobno dla calego
# ramienia i dla osi 4: tam obraca sie sama glowica z kamera, wiec nie ma czego
# rozhustac i moze chodzic szybciej niz wysieg, ktory przenosi szarpniecie na
# stol.
ROBOT_MOVE_SPEED = int(os.environ.get("ROBOT_MOVE_SPEED", "200"))
ROBOT_MOVE_ACC = int(os.environ.get("ROBOT_MOVE_ACC", "10"))
ROBOT_JOINT_SPEED = int(os.environ.get("ROBOT_JOINT_SPEED", "1200"))
ROBOT_JOINT_ACC = int(os.environ.get("ROBOT_JOINT_ACC", "40"))
# Korekta pozycji przyciskami w Ustawieniach (stopnie): maly krok do
# wykonczenia kadru i duzy do zgrubnego dojechania. Reka nie da sie ustawic
# ramienia z dokladnoscia do stopnia, a od tego zalezy kadr.
ROBOT_NUDGE_STEP = float(os.environ.get("ROBOT_NUDGE_STEP", "1"))
ROBOT_NUDGE_BIG = float(os.environ.get("ROBOT_NUDGE_BIG", "5"))

# Os 4 (EoAT) ma na M2-S dwa tryby: chwytak (135 stopni) albo NADGARSTEK (270).
# Z kamera na koncu chcemy nadgarstka — inaczej ta sama os zaciska szczeki
# zamiast obracac glowice.
ROBOT_WRIST_MODE = os.environ.get("ROBOT_WRIST_MODE", "true").lower() in ("1", "true", "yes", "on")
# Przejazd do pozycji domowej (`move_init`) po polaczeniu. Przy sterowaniu
# katami nie jest do niczego potrzebny (cel jest bezwzgledny), wiec domyslnie
# OFF — ramie z aparatem nie ma ruszac samo zaraz po starcie aplikacji.
ROBOT_HOME_ON_CONNECT = os.environ.get("ROBOT_HOME_ON_CONNECT", "false").lower() in ("1", "true", "yes", "on")


def _robot_joints(key: str) -> list[float] | None:
    """Ujecie z .env: cztery katy przegubow w stopniach, "j1,j2,j3,j4".

    Wypisuje je `tools/roarm_teach.py`: puszcza serwa, operator ustawia ramie
    recznie w docelowym ujeciu, skrypt odczytuje katy. Brak wpisu = ujecie
    nieustawione; UI mowi to wprost, zamiast wysylac ramie w przypadkowe
    miejsce z wartosci domyslnych."""
    raw = os.environ.get(key, "").strip()
    if not raw:
        return None
    parts = [p for p in raw.replace(";", ",").split(",") if p.strip()]
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        print(f"⚠ {key}='{raw}' nie jest listą czterech kątów — ujęcie pominięte")
        return None
    if len(nums) != 4:
        print(f"⚠ {key}='{raw}' ma {len(nums)} liczb zamiast 4 — ujęcie pominięte")
        return None
    return nums


ROBOT_JOINTS_ENV = {"top90": "ROBOT_JOINTS_TOP90", "a45": "ROBOT_JOINTS_A45"}
ROBOT_JOINTS = {name: _robot_joints(key) for name, key in ROBOT_JOINTS_ENV.items()}

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
