"""Wersja aplikacji — JEDNO zrodlo prawdy.

Czytane przez:
- `src/updater.py` (porownanie z najnowszym tagiem na GitHubie),
- `CameraCapture.spec` (generuje z tego zasob VS_VERSION_INFO dla .exe),
- workflow CI (sprawdza, czy tag `vX.Y.Z` zgadza sie z ta stala).

Bez importow — spec PyInstallera czyta ten plik zanim cokolwiek innego
zdazy sie zaimportowac.
"""

APP_VERSION = "1.1.1"

GITHUB_REPO = "Xeross99/camera-capture"


def parse_version(text: str) -> tuple[int, int, int] | None:
    """"v1.2.3" / "1.2.3-beta" -> (1, 2, 3). None gdy nie da sie sparsowac."""
    core = str(text).strip().lstrip("vV").split("-", 1)[0].split("+", 1)[0]
    parts = [p for p in core.split(".") if p != ""]
    if not parts:
        return None
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return None
    nums = (nums + [0, 0, 0])[:3]
    return (nums[0], nums[1], nums[2])
