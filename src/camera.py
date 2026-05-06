import subprocess
import sys
import time
from pathlib import Path

import gphoto2 as gp

from .config import CAMERA_IMAGE_FORMAT

GP_ERROR_IO_IN_PROGRESS = -110
GP_ERROR_NOT_SUPPORTED = -6

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
    subprocess.run(
        ["killall", "PTPCamera"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )


def capture_from_camera(workdir: Path) -> Path:
    print("Łączę z aparatem…")
    last_err: Exception | None = None
    camera = None
    for attempt in range(3):
        _kill_ptpcamera()
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
            time.sleep(1.0 + attempt)
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
                if e.code not in (GP_ERROR_IO_IN_PROGRESS, GP_ERROR_NOT_SUPPORTED):
                    raise
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
            raise gp.GPhoto2Error(
                GP_ERROR_IO_IN_PROGRESS,
                "Aparat zajęty (I/O in progress) mimo ponownych prób.",
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
