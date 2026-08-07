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

import locale
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
UPDATE_LOG = "camera_capture_update.log"   # %TEMP%\camera_capture_update.log


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
    (bat czeka az proces zniknie, kopiuje pliki i startuje aplikacje)."""
    if not can_self_update():
        raise RuntimeError("samo-aktualizacja dziala tylko dla .exe na Windowsie")
    staging = Path(staging)
    _validate_staging(staging)
    target = PROJECT_DIR
    exe = Path(sys.executable)
    tmpdir = Path(tempfile.gettempdir())
    # .bat i log siedza POZA drzewem, ktore skrypt na koncu kasuje — inaczej
    # `rd /s /q` probowalby usunac katalog z dzialajacym skryptem (i swoim cwd)
    bat = tmpdir / UPDATER_BAT
    log = tmpdir / UPDATE_LOG
    root = next((p for p in (staging, *staging.parents)
                 if p.name.startswith("cc_update_")), staging.parent)

    # Slad po stronie Pythona ZANIM cokolwiek odpalimy — gdy .bat nie ruszy,
    # to jedyne, co zostaje operatorowi (i mnie) do diagnozy.
    with open(log, "w", encoding="utf-8", errors="replace") as fh:
        fh.write(f"[updater] wersja {APP_VERSION}, pid {os.getpid()}\n"
                 f"[updater] staging: {staging}\n"
                 f"[updater] target : {target}\n"
                 f"[updater] exe    : {exe}\n"
                 f"[updater] bat    : {bat}\n")

    script = _bat_script(_short(staging), _short(target), _short(exe),
                         _short(log), _short(root))
    try:
        bat.write_text(script, encoding="ascii")
    except UnicodeEncodeError:
        # Skrocone sciezki 8.3 sa ASCII, wiec tu trafiamy tylko gdy wolumen ma
        # wylaczone nazwy 8.3. cmd czyta .bat w codepage OEM — najblizej tego
        # jest domyslne kodowanie systemu.
        bat.write_text(script, encoding=locale.getpreferredencoding(False),
                       errors="replace")
    # Jeden string, nie lista: `cmd /c` ma wlasne, nieoczywiste reguly zdejmowania
    # cudzyslowow i lista z subprocess potrafila zrobic z tego komende, ktorej cmd
    # nie umial znalezc (okno migalo i znikalo bez zadnego efektu).
    subprocess.Popen(
        f'cmd.exe /c "{_short(bat)}"',
        cwd=str(bat.parent),
        creationflags=getattr(subprocess, "DETACHED_PROCESS", 0)
        | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        close_fds=True,
    )
    return log


def _short(path: Path) -> str:
    """Sciezka w formacie 8.3 (`C:\\Users\\MICHA~1\\...`), gdy system ja daje.

    Dwa powody: (1) `.bat` z polskimi znakami w sciezce nie da sie zapisac w
    ASCII, a cmd i tak czyta plik w codepage OEM — kazde inne kodowanie to
    loteria; (2) skrocone sciezki nie maja spacji, wiec znika cala zabawa w
    cudzyslowy. Gdy wolumen nie ma nazw 8.3, zwracamy sciezke bez zmian."""
    if sys.platform != "win32":
        return str(path)
    import ctypes

    buf = ctypes.create_unicode_buffer(1024)
    n = ctypes.windll.kernel32.GetShortPathNameW(str(path), buf, len(buf))
    return buf.value if 0 < n < len(buf) and buf.value else str(path)


def _bat_script(staging: str, target: str, exe: str, log: str, root: str) -> str:
    """`_internal` idzie /MIR (stare DLL-e z poprzedniej wersji znikaja),
    reszta /E bez kasowania — .env, photos/ i EDSDK.dll leza obok .exe.

    Zamiast pilnowac PID-u przez `tasklist` (format wyjscia zalezy od jezyka
    Windows) czekamy chwile i polegamy na retry robocopy: dopoki aplikacja
    trzyma swoje pliki, kopiowanie sie ponawia, a nie wywala."""
    opts = "/NFL /NDL /NJH /NJS /NP /R:20 /W:1"
    # UWAGA: caly skrypt musi byc czystym ASCII (bez polskich znakow i myslnikow
    # typograficznych) — cmd czyta .bat w codepage OEM, a zapis pliku leci w ASCII.
    return f"""@echo off
title Camera Capture - aktualizacja
set "LOG={log}"
echo [%DATE% %TIME%] start >> "%LOG%"

echo.
echo   Aktualizuje Camera Capture. Nie zamykaj tego okna.
echo.
echo   Czekam na zamkniecie aplikacji...
ping -n 4 127.0.0.1 >nul

echo   Podmieniam pliki...
robocopy "{staging}\\_internal" "{target}\\_internal" /MIR {opts} >> "%LOG%" 2>&1
set RC1=%ERRORLEVEL%
robocopy "{staging}" "{target}" /E /XD "{staging}\\_internal" /XF ".env" {opts} >> "%LOG%" 2>&1
set RC2=%ERRORLEVEL%
echo [%TIME%] robocopy: _internal=%RC1% reszta=%RC2% >> "%LOG%"

if %RC1% GEQ 8 goto failed
if %RC2% GEQ 8 goto failed
if not exist "{exe}" goto failed

echo   Uruchamiam nowa wersje...
echo [%TIME%] start "{exe}" >> "%LOG%"
cd /d "{target}"
start "" "{exe}"
rd /s /q "{root}" 2>nul
(goto) 2>nul & del "%~f0"

:failed
echo.
echo   AKTUALIZACJA NIE POWIODLA SIE.
echo   Log: %LOG%
echo   Uruchom aplikacje recznie i zajrzyj do logu.
echo.
pause
"""
