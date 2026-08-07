"""Auto-aktualizacja z GitHub Releases.

Kanal wydan: publiczne repo `GITHUB_REPO`, release z tagiem `vX.Y.Z` i
zalacznikiem `CameraCapture-windows-vX.Y.Z.zip` (zawartosc `dist/CameraCapture`
spakowana z poziomu katalogu — w zipie na wierzchu leza `.exe` i `_internal/`).
Publiczne repo = `releases/latest` bez tokena, wiec .exe u operatora pyta samo.

Sama podmiana dziala TYLKO dla spakowanego .exe na Windowsie (`can_self_update`):
dzialajacego procesu nie da sie nadpisac, wiec pobrana paczka ladu je w tempie,
a robote konczy `.bat` odpalony tuz przed wyjsciem — czeka az proces zniknie,
kopiuje pliki i uruchamia aplikacje z powrotem. Kopiujemy TYLKO to, co jest w
zipie (`.exe` + `_internal/`), zeby `.env`, `photos/` i recznie dolozone
`EDSDK.dll` przezyly aktualizacje (patrz PROJECT_DIR w config.py — one zyja
obok .exe).

Uruchomienie ze zrodel (macOS/dev) tylko informuje o nowszym tagu — tam
aktualizuje sie przez `git pull`.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from .config import PROJECT_DIR
from .version import APP_VERSION, GITHUB_REPO, parse_version

RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
ASSET_HINT = "windows"
HTTP_TIMEOUT = 10
UPDATER_BAT = "camera_capture_update.bat"


def can_self_update() -> bool:
    """Podmiana plikow ma sens tylko dla spakowanego .exe na Windowsie."""
    return bool(getattr(sys, "frozen", False)) and sys.platform == "win32"


def check_for_update() -> dict | None:
    """Najnowszy release z GitHuba albo None, gdy nie ma nic nowszego.

    Zwraca {version, url, size, notes, page}; `url` puste = release bez
    zalacznika dla Windows (mozna tylko pokazac, ze cos wyszlo)."""
    import requests

    r = requests.get(
        RELEASES_API, timeout=HTTP_TIMEOUT,
        headers={"Accept": "application/vnd.github+json",
                 "User-Agent": f"camera-capture/{APP_VERSION}"},
    )
    if r.status_code == 404:
        return None  # repo bez zadnego wydania — nie ma z czym porownywac
    r.raise_for_status()
    rel = r.json()
    remote = parse_version(str(rel.get("tag_name") or ""))
    current = parse_version(APP_VERSION)
    if remote is None or current is None or remote <= current:
        return None
    asset = next(
        (a for a in rel.get("assets", [])
         if str(a.get("name", "")).lower().endswith(".zip")
         and ASSET_HINT in str(a.get("name", "")).lower()),
        None,
    )
    return {
        "version": ".".join(str(n) for n in remote),
        "url": str(asset.get("browser_download_url", "")) if asset else "",
        "size": int(asset.get("size") or 0) if asset else 0,
        "notes": str(rel.get("body") or "").strip(),
        "page": str(rel.get("html_url") or ""),
    }


def download_and_stage(url: str, progress=None) -> Path:
    """Pobiera zip do katalogu tymczasowego i rozpakowuje go obok.

    Zwraca katalog `staging` z zawartoscia paczki (na wierzchu `.exe` +
    `_internal/`). `progress` dostaje procent (0–100) pobierania."""
    import requests

    tmp = Path(tempfile.mkdtemp(prefix="cc_update_"))
    payload = tmp / "payload"
    payload.mkdir()
    zip_path = payload / "update.zip"
    try:
        with requests.get(url, stream=True, timeout=HTTP_TIMEOUT) as r:
            r.raise_for_status()
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            last = -1
            with open(zip_path, "wb") as fh:
                for chunk in r.iter_content(chunk_size=256 * 1024):
                    fh.write(chunk)
                    done += len(chunk)
                    if progress and total:
                        pct = min(99, int(done * 100 / total))
                        if pct != last:
                            last = pct
                            progress(pct)
        staging = payload / "staging"
        _extract(zip_path, staging)
        zip_path.unlink(missing_ok=True)
        if progress:
            progress(100)
        return _normalize_staging(staging)
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


def _extract(zip_path: Path, dest: Path) -> None:
    """Rozpakowanie z odsianiem sciezek uciekajacych poza `dest`
    (zip-slip — paczka jest z sieci, wiec nie ufamy nazwom w archiwum)."""
    dest.mkdir(parents=True, exist_ok=True)
    root = dest.resolve()
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.namelist():
            target = (dest / member).resolve()
            if not str(target).startswith(str(root)):
                raise ValueError(f"podejrzana sciezka w archiwum: {member!r}")
        zf.extractall(dest)


def _normalize_staging(staging: Path) -> Path:
    """CI pakuje zawartosc `dist/CameraCapture`, ale zip zrobiony recznie
    moze miec jeszcze katalog na wierzchu — wtedy schodzimy o poziom nizej."""
    if not any(p.suffix.lower() == ".exe" for p in staging.iterdir()):
        subdirs = [p for p in staging.iterdir() if p.is_dir()]
        if len(subdirs) == 1:
            return subdirs[0]
    return staging


def _validate_staging(staging: Path) -> Path:
    """Bez tego `robocopy /MIR` na pustym/dziwnym staging wyczyscilby
    `_internal` dzialajacej instalacji."""
    exe = next((p for p in staging.glob("*.exe")), None)
    if exe is None:
        raise ValueError("paczka aktualizacji nie zawiera pliku .exe")
    if not (staging / "_internal").is_dir():
        raise ValueError("paczka aktualizacji nie zawiera katalogu _internal")
    return exe


def apply_update_and_restart(staging: Path) -> None:
    """Odpala updater .bat i wraca — wywolujacy MUSI zaraz zakonczyc proces
    (bat czeka na jego zniknieciem, potem kopiuje pliki i startuje aplikacje)."""
    if not can_self_update():
        raise RuntimeError("samo-aktualizacja dziala tylko dla .exe na Windowsie")
    staging = Path(staging)
    _validate_staging(staging)
    target = PROJECT_DIR
    exe = Path(sys.executable)
    bat = staging.parent.parent / UPDATER_BAT
    bat.write_text(_bat_script(staging, target, exe), encoding="ascii")
    subprocess.Popen(
        ["cmd.exe", "/c", str(bat), str(os.getpid())],
        cwd=str(bat.parent),
        creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        close_fds=True,
    )


def _bat_script(staging: Path, target: Path, exe: Path) -> str:
    """`_internal` idzie /MIR (stare DLL-e z poprzedniej wersji znikaja),
    reszta /E bez kasowania — .env, photos/ i EDSDK.dll leza obok .exe."""
    quiet = "/NFL /NDL /NJH /NJS /NP /R:2 /W:2"
    return f"""@echo off
setlocal
set "PID=%1"

:waitloop
tasklist /FI "PID eq %PID%" 2>nul | find "%PID%" >nul
if not errorlevel 1 (
    ping -n 2 127.0.0.1 >nul
    goto waitloop
)

robocopy "{staging}\\_internal" "{target}\\_internal" /MIR {quiet} >nul
robocopy "{staging}" "{target}" /E /XD "{staging}\\_internal" /XF ".env" {quiet} >nul

cd /d "{target}"
start "" "{exe}"

rd /s /q "{staging.parent}" 2>nul
(goto) 2>nul & del "%~f0"
"""
