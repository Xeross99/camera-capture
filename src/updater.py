"""Auto-aktualizacja z GitHub Releases.

Kanal wydan: publiczne repo `GITHUB_REPO`, release z tagiem `vX.Y.Z` i
zalacznikiem `CameraCapture-windows-vX.Y.Z.zip` (zawartosc `dist/CameraCapture`
spakowana z poziomu katalogu — w zipie na wierzchu leza `.exe` i `_internal/`).
Publiczne repo = `releases/latest` bez tokena, wiec .exe u operatora pyta samo.

Sama podmiana dziala TYLKO dla spakowanego .exe na Windowsie (`can_self_update`):
dzialajacego procesu nie da sie nadpisac, wiec paczka jest rozpakowywana obok
aplikacji (`PROJECT_DIR/.update/staging`), a robote konczy **.exe z tej wlasnie
paczki** uruchomiony z flaga `--apply-update <katalog> <pid>`: czeka az stary
proces zniknie, kopiuje pliki (czysty Python, `shutil`), startuje zainstalowana
aplikacje i konczy sie.

Dlaczego nie `.bat`, jak bylo wczesniej: skrypt cmd wymagal przepchania sciezek
przez kodowanie OEM i cudzyslowy `cmd /c` (polskie znaki w profilu, spacje w
nazwie .exe, wolumeny bez nazw 8.3), a gdy cokolwiek z tego zawiodlo, `robocopy`
konczyl sie bledem w oknie, ktorego przy DETACHED_PROCESS nikt nie widzial —
objaw byl zawsze ten sam: aplikacja znika i nic sie nie dzieje. Aktualizator w
Pythonie dostaje sciezki jako liste argv (zero parsowania), pisze log obok .exe,
a przy wtopie pokazuje MessageBox i podnosi z powrotem stara wersje.

Uruchomienie ze zrodel (macOS/dev) tylko informuje o nowszym tagu — tam
aktualizuje sie przez `git pull`.
"""

import ctypes
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import datetime
from pathlib import Path

from .config import PROJECT_DIR
from .version import APP_VERSION, GITHUB_REPO, parse_version

RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
ASSET_HINT = "windows"
HTTP_TIMEOUT = 10

APPLY_FLAG = "--apply-update"      # gui.py rozpoznaje ja przed reszta importow
STAGING_DIR = ".update"            # PROJECT_DIR/.update/staging
UPDATE_LOG = "update.log"          # obok .exe — tam operator ma szukac
ERROR_MARKER = "update_error.txt"  # czyta i kasuje `cleanup_after_update()`

_DETACHED = (getattr(subprocess, "DETACHED_PROCESS", 0)
             | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))


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


# ---------------------------------------------------------------- pobranie


def _staging_root() -> Path:
    """Katalog roboczy paczki — najpierw OBOK aplikacji.

    Kopiowanie idzie wtedy w obrebie jednego wolumenu, a nieuprawniony katalog
    (np. Program Files) wysypuje sie od razu przy pobieraniu, z czytelnym
    bledem w UI — zamiast dopiero w aktualizatorze, gdzie nikt tego nie widzi.
    %TEMP% zostaje jako awaryjny."""
    last: Exception | None = None
    for base in (PROJECT_DIR / STAGING_DIR,
                 Path(tempfile.gettempdir()) / "cc_update"):
        try:
            shutil.rmtree(base, ignore_errors=True)
            base.mkdir(parents=True, exist_ok=True)
            probe = base / ".write-test"
            probe.write_bytes(b"x")
            probe.unlink()
            return base
        except OSError as e:
            last = e
    raise RuntimeError(f"nie ma gdzie rozpakowac paczki aktualizacji: {last}")


def download_and_stage(url: str, progress=None) -> Path:
    """Pobiera zip i rozpakowuje go do katalogu roboczego.

    Zwraca katalog `staging` z zawartoscia paczki (na wierzchu `.exe` +
    `_internal/`). `progress` dostaje procent (0–100) pobierania."""
    import requests

    root = _staging_root()
    zip_path = root / "update.zip"
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
        staging = root / "staging"
        _extract(zip_path, staging)
        zip_path.unlink(missing_ok=True)
        if progress:
            progress(100)
        return _normalize_staging(staging)
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
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
    """Bez tego aktualizator kopiowalby pusty/dziwny katalog na dzialajaca
    instalacje (a przy sprzataniu `_internal` wycialby jej biblioteki)."""
    exe = next((p for p in staging.glob("*.exe")), None)
    if exe is None:
        raise ValueError("paczka aktualizacji nie zawiera pliku .exe")
    if not (staging / "_internal").is_dir():
        raise ValueError("paczka aktualizacji nie zawiera katalogu _internal")
    return exe


# ---------------------------------------------------------------- log


def _log_path(target: Path) -> Path:
    """Log obok .exe (operator ma go pod reka), z awaryjnym %TEMP%."""
    try:
        target.mkdir(parents=True, exist_ok=True)
        path = target / UPDATE_LOG
        with open(path, "a", encoding="utf-8"):
            pass
        return path
    except OSError:
        return Path(tempfile.gettempdir()) / "camera_capture_update.log"


def _logger(path: Path):
    def say(msg: str) -> None:
        try:
            with open(path, "a", encoding="utf-8", errors="replace") as fh:
                fh.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}\n")
        except OSError:
            pass
    return say


# ---------------------------------------------------------------- start aktualizatora


def apply_update_and_restart(staging) -> Path:
    """Odpala aktualizator (.exe z paczki) i wraca — wywolujacy MUSI zaraz
    zakonczyc proces, bo aktualizator czeka wlasnie na jego zniknieciu.

    Zwraca sciezke logu aktualizacji."""
    if not can_self_update():
        raise RuntimeError("samo-aktualizacja dziala tylko dla .exe na Windowsie")
    staging = Path(staging)
    helper = _validate_staging(staging)
    target = PROJECT_DIR
    log = _log_path(target)
    say = _logger(log)
    say(f"start: wersja {APP_VERSION}, pid {os.getpid()}")
    say(f"  staging: {staging}")
    say(f"  target : {target}")
    say(f"  helper : {helper}")

    try:
        (target / ERROR_MARKER).unlink(missing_ok=True)
    except OSError:
        pass

    proc = subprocess.Popen(
        [str(helper), APPLY_FLAG, str(target), str(os.getpid())],
        cwd=str(staging), creationflags=_DETACHED, close_fds=True,
    )
    # Aktualizator ma teraz czekac na nas — jesli zdazyl umrzec, to znaczy, ze
    # nowy .exe nie wstaje (brakujaca biblioteka, blokada antywirusa). Lepiej
    # zostac w starej wersji z bledem w logu niz zamknac sie w nicosc.
    time.sleep(2.0)
    rc = proc.poll()
    if rc is not None:
        say(f"BLAD: aktualizator zakonczyl sie natychmiast (kod {rc})")
        raise RuntimeError(f"aktualizator nie wystartowal (kod {rc}) — log: {log}")
    say("aktualizator dziala, zamykam aplikacje")
    return log


# ---------------------------------------------------------------- tryb aktualizatora


def run_apply_update(argv: list[str]) -> int:
    """Tryb `--apply-update <katalog instalacji> [pid starej aplikacji]`.

    Uruchamiany z ROZPAKOWANEJ nowej paczki (patrz naglowek modulu). Nie wolno
    tu uzywac `PROJECT_DIR` — dla tego procesu wskazuje katalog paczki, nie
    instalacji."""
    if not argv:
        return 2
    target = Path(argv[0]).resolve()
    pid = int(argv[1]) if len(argv) > 1 and argv[1].isdigit() else 0
    staging = Path(sys.executable).resolve().parent
    log = _log_path(target)
    say = _logger(log)
    say(f"aktualizator: nowa wersja {APP_VERSION}, staging {staging}, pid {os.getpid()}")

    try:
        helper = _validate_staging(staging)
        _wait_for_old_app(pid, target, say)
        copied = _install(staging, target, say)
        target_exe = target / helper.name
        if not target_exe.is_file():
            raise RuntimeError(f"po kopiowaniu brak {target_exe}")
        say(f"skopiowano {copied} plikow, uruchamiam {target_exe}")
        _spawn(target_exe, say)
        say("gotowe")
        return 0
    except Exception as e:
        say(f"BLAD: {e!r}")
        try:
            (target / ERROR_MARKER).write_text(
                f"{e}\nLog: {log}\n", encoding="utf-8", errors="replace")
        except OSError:
            pass
        _message_box(
            "Aktualizacja Camera Capture nie powiodła się.\n\n"
            f"{e}\n\nSzczegóły: {log}\n\n"
            "Uruchamiam poprzednią wersję — aktualizację można pobrać ręcznie "
            "z GitHub Releases.")
        fallback = next((p for p in target.glob("*.exe")), None)
        if fallback is not None:
            _spawn(fallback, say)
        return 1


def _wait_for_old_app(pid: int, target: Path, say) -> None:
    """Czekanie na zniknieciu starego procesu — najpierw uchwytem (pewne i bez
    zalezosci od jezyka Windows, w przeciwienstwie do `tasklist`), potem proba
    otwarcia .exe do zapisu, bo system potrafi trzymac plik jeszcze chwile."""
    if pid and sys.platform == "win32":
        SYNCHRONIZE = 0x00100000
        handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
        if handle:
            say(f"czekam na zamkniecie pid {pid}")
            ctypes.windll.kernel32.WaitForSingleObject(handle, 60_000)
            ctypes.windll.kernel32.CloseHandle(handle)
        else:
            say(f"pid {pid} juz nie zyje")
    deadline = time.monotonic() + 30
    for exe in target.glob("*.exe"):
        while time.monotonic() < deadline:
            try:
                with open(exe, "r+b"):
                    break
            except PermissionError:
                time.sleep(0.5)
            except OSError:
                break
        else:
            say(f"UWAGA: {exe.name} wciaz zablokowany po 30 s — probuje mimo to")


def _install(staging: Path, target: Path, say) -> int:
    """Kopiuje paczke na instalacje i usuwa z `_internal` to, czego nowa wersja
    juz nie ma (stare biblioteki). Reszta katalogu zostaje nietknieta — `.env`,
    `photos/` i recznie dolozony `EDSDK.dll` zyja obok .exe."""
    copied = 0
    for src in sorted(staging.rglob("*")):
        rel = src.relative_to(staging)
        dst = target / rel
        if src.is_dir():
            dst.mkdir(parents=True, exist_ok=True)
            continue
        if rel.name == ".env":
            continue
        _copy(src, dst)
        copied += 1
    _prune_internal(staging / "_internal", target / "_internal", say)
    return copied


def _copy(src: Path, dst: Path, attempts: int = 20) -> None:
    """Retry na PermissionError — aplikacja mogla jeszcze nie puscic pliku."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    for i in range(attempts):
        try:
            shutil.copy2(src, dst)
            return
        except PermissionError:
            if i == attempts - 1:
                raise
            time.sleep(1)


def _prune_internal(new_internal: Path, old_internal: Path, say) -> None:
    """Blad sprzatania nie przerywa aktualizacji — zostawiony smiec jest
    nieszkodliwy, przerwana podmiana plikow juz nie."""
    if not old_internal.is_dir() or not new_internal.is_dir():
        return
    removed = 0
    for path in sorted(old_internal.rglob("*"), reverse=True):
        rel = path.relative_to(old_internal)
        if (new_internal / rel).exists():
            continue
        try:
            if path.is_dir():
                path.rmdir()
            else:
                path.unlink()
            removed += 1
        except OSError as e:
            say(f"nie usunieto {rel}: {e}")
    if removed:
        say(f"usunieto {removed} plikow z poprzedniej wersji")


def _spawn(exe: Path, say) -> None:
    try:
        subprocess.Popen([str(exe)], cwd=str(exe.parent),
                         creationflags=_DETACHED, close_fds=True)
    except OSError as e:
        say(f"nie udalo sie uruchomic {exe}: {e}")


def _message_box(text: str) -> None:
    """Jedyny widoczny slad, gdy aktualizacja padnie — aktualizator jest
    procesem okienkowym bez konsoli, wiec inaczej znika bez slowa."""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.user32.MessageBoxW(
            None, text, "Camera Capture — aktualizacja", 0x10)
    except Exception:
        pass


# ---------------------------------------------------------------- sprzatanie


def cleanup_after_update() -> str | None:
    """Wolane przy starcie aplikacji: kasuje katalogi robocze aktualizatora i
    zwraca tresc markera bledu (albo None). Marker jest czyszczony."""
    err = None
    marker = PROJECT_DIR / ERROR_MARKER
    try:
        if marker.is_file():
            err = marker.read_text(encoding="utf-8", errors="replace").strip()
            marker.unlink()
    except OSError:
        pass
    stale = [PROJECT_DIR / STAGING_DIR,
             Path(tempfile.gettempdir()) / "cc_update"]
    # katalogi po poprzedniej wersji aktualizatora (mechanizm z .bat)
    stale += list(Path(tempfile.gettempdir()).glob("cc_update_*"))
    for path in stale:
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)
    return err
