import subprocess
import sys
import threading
import time
from pathlib import Path

import gphoto2 as gp

from .config import CAMERA_IMAGE_FORMAT

GP_ERROR_UNSPECIFIED = -1
GP_ERROR_IO_IN_PROGRESS = -110
GP_ERROR_NOT_SUPPORTED = -6

_RETRYABLE_CAPTURE_ERRORS = (GP_ERROR_UNSPECIFIED, GP_ERROR_IO_IN_PROGRESS, GP_ERROR_NOT_SUPPORTED)

_CONFIG_NAMES = ("imageformat", "imagequality", "imagesize")
_AUTO_ROTATE_NAMES = ("autorotation", "autorotate", "auto-rotate")
_AUTO_ROTATE_OFF_VALUES = ("None", "Off", "off", "Disable", "Disabled", "0")


def _find_widget(config, names):
    for name in names:
        try:
            return name, config.get_child_by_name(name)
        except gp.GPhoto2Error:
            continue
    return None, None


def list_image_formats(camera) -> dict[str, list[str]]:
    config = camera.get_config()
    out: dict[str, list[str]] = {}
    for name in _CONFIG_NAMES:
        try:
            widget = config.get_child_by_name(name)
        except gp.GPhoto2Error:
            continue
        out[name] = [widget.get_choice(i) for i in range(widget.count_choices())]
    return out


def _apply_image_format(camera, target: str) -> None:
    config = camera.get_config()
    name, widget = _find_widget(config, _CONFIG_NAMES)
    if widget is None:
        print(f"Uwaga: aparat nie eksponuje {_CONFIG_NAMES}, pomijam zmiane formatu.")
        return

    choices = [widget.get_choice(i) for i in range(widget.count_choices())]
    if target in choices:
        chosen = target
    else:
        chosen = next((c for c in choices if target.lower() in c.lower()), None)
    if chosen is None:
        print(
            f"Uwaga: '{target}' niedostepny w {name}. "
            f"Dostepne: {choices}. Zostawiam bez zmian."
        )
        return

    if widget.get_value() == chosen:
        return
    widget.set_value(chosen)
    camera.set_config(config)


def _disable_autorotation(camera) -> None:
    config = camera.get_config()
    name, widget = _find_widget(config, _AUTO_ROTATE_NAMES)
    if widget is None:
        return
    try:
        choices = [widget.get_choice(i) for i in range(widget.count_choices())]
    except gp.GPhoto2Error:
        choices = []
    if not choices:
        return
    target = next((c for c in _AUTO_ROTATE_OFF_VALUES if c in choices), None)
    if target is None:
        target = next(
            (c for c in choices if any(v.lower() in c.lower() for v in ("off", "none", "disable"))),
            None,
        )
    if target is None:
        print(f"Uwaga: '{name}' nie ma wartosci 'Off'. Dostepne: {choices}")
        return
    if widget.get_value() == target:
        return
    widget.set_value(target)
    camera.set_config(config)
    print(f"  {name}: {target}")


def _drain_events(camera, timeout_ms: int = 2000) -> None:
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        event_type, _ = camera.wait_for_event(200)
        if event_type == gp.GP_EVENT_TIMEOUT:
            return


def _kill_ptpcamera() -> None:
    # `PTPCamera` was the legacy macOS app; newer macOS (Sonoma+) uses
    # `ptpcamerad` daemon at /usr/libexec/ptpcamerad. Both auto-claim a
    # connected PTP camera and need to be killed before gphoto2 can init.
    # SIGKILL because launchd respawns the daemon ~50ms after SIGTERM.
    for name in ("ptpcamerad", "PTPCamera"):
        subprocess.run(
            ["killall", "-9", name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )


class _PtpCameradReaper:
    """Kills ptpcamerad in a tight loop while gphoto2 races to claim USB.

    macOS launchd respawns ptpcamerad within ~100ms of being killed, fast
    enough to reclaim the USB device before camera.init() finishes. Running
    a background reaper that SIGKILLs every 30ms guarantees the daemon stays
    dead until gphoto2 has the handle. Once init() returns, gphoto2 owns the
    device — any subsequent ptpcamerad respawn will fail to claim (-53) and
    exit harmlessly, so we can stop the reaper.
    """

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            _kill_ptpcamera()
            self._stop.wait(0.03)


def capture_from_camera(workdir: Path) -> Path:
    print("Łączę z aparatem…")
    last_err: Exception | None = None
    camera = None
    reaper = _PtpCameradReaper()
    reaper.start()
    try:
        for attempt in range(5):
            try:
                camera = gp.Camera()
                camera.init()
                break
            except gp.GPhoto2Error as e:
                last_err = e
                try:
                    if camera is not None:
                        camera.exit()
                except gp.GPhoto2Error:
                    pass
                camera = None
                time.sleep(0.2 + attempt * 0.2)
    finally:
        reaper.stop()
    if camera is None:
        sys.exit(
            f"Nie udało się połączyć z aparatem: {last_err}\n"
            "Wskazówki: sprawdź USB, zamknij Photos.app / Image Capture / Canon EOS Utility "
            "(blokują urządzenie), włącz aparat w trybie M/Av/Tv/P."
        )

    try:
        if CAMERA_IMAGE_FORMAT:
            try:
                _apply_image_format(camera, CAMERA_IMAGE_FORMAT)
            except gp.GPhoto2Error as e:
                print(f"Uwaga: nie udalo sie ustawic formatu obrazu ({e}).")

        try:
            _disable_autorotation(camera)
        except gp.GPhoto2Error as e:
            print(f"Uwaga: nie udalo sie wylaczyc auto-rotacji ({e}).")

        print("Wyzwalam migawkę…")
        _drain_events(camera, timeout_ms=1500)
        file_path = None
        last_capture_err: gp.GPhoto2Error | None = None
        for attempt in range(5):
            try:
                file_path = camera.capture(gp.GP_CAPTURE_IMAGE)
                break
            except gp.GPhoto2Error as e:
                last_capture_err = e
                if e.code not in _RETRYABLE_CAPTURE_ERRORS:
                    raise
                print(f"  Próba {attempt + 1}/5 nie powiodła się ({e}), ponawiam…")
                _drain_events(camera, timeout_ms=1500)
                time.sleep(0.5 + attempt * 0.5)
        if file_path is None:
            if last_capture_err and last_capture_err.code == GP_ERROR_NOT_SUPPORTED:
                sys.exit(
                    "Aparat odrzuca wyzwolenie migawki (-6 Unsupported operation).\n"
                    "Sprawdz po kolei:\n"
                    "  1. Pokretlo trybu na M / Av / Tv / P / Fv (nie Auto+, SCN, Movie).\n"
                    "  2. Aparat NIE jest w trybie odtwarzania — wcisnij spust do polowy zeby wybudzic.\n"
                    "  3. Wylacz i wlacz aparat (auto-off potrafi zablokowac remote).\n"
                    "  4. Zamknij Photos.app / Image Capture / Canon EOS Utility.\n"
                    "  5. Odepnij i podepnij ponownie kabel USB."
                )
            if last_capture_err and last_capture_err.code == GP_ERROR_UNSPECIFIED:
                sys.exit(
                    "Aparat zwraca [-1] Unspecified error mimo 5 prób.\n"
                    "Sprawdz po kolei:\n"
                    "  1. Aparat NIE jest w trybie odtwarzania (Play).\n"
                    "  2. AF zlapał ostrosc — spróbuj MF lub upewnij sie ze jest na czym zfocusowac.\n"
                    "  3. Obiektyw jest poprawnie zamontowany (brak 'Err' na ekranie aparatu).\n"
                    "  4. Wylacz i wlacz aparat, odepnij/podepnij USB.\n"
                    "  5. Sprawdz czy aparat strzela recznie (spust na obudowie)."
                )
            raise gp.GPhoto2Error(
                last_capture_err.code if last_capture_err else GP_ERROR_IO_IN_PROGRESS,
                f"Aparat nie zrobil zdjecia mimo ponownych prób ({last_capture_err}).",
            )
        ext = Path(file_path.name).suffix or ".jpg"
        target = workdir / f"capture{ext}"
        camera_file = camera.file_get(
            file_path.folder, file_path.name, gp.GP_FILE_TYPE_NORMAL
        )
        camera_file.save(str(target))
        _drain_events(camera)
    finally:
        try:
            camera.exit()
        except gp.GPhoto2Error:
            pass

    return target
