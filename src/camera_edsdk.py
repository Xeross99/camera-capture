"""Backend aparatu dla Windows: Canon EDSDK (oficjalne SDK, przez ctypes).

Zero posrednikow — zadnego digiCamControl: aplikacja laduje EDSDK.dll
(+ EdsImage.dll z tego samego katalogu) i rozmawia z aparatem po USB sama.
DLL-ki NIE sa w repo (licencja Canona) — pobierz SDK x64 z programu
deweloperskiego Canona i poloz obok aplikacji (szczegoly: WINDOWS.md).

Interfejs 1:1 z CameraSession (open/preview_frame/capture_to/get_settings/
set_setting/close) — webui nie widzi roznicy miedzy backendami.

Wszystkie wywolania EDSDK musza isc z JEDNEGO watku (u nas: watek camera
w webui) — EDSDK nie jest thread-safe, a callbacki wolane sa z EdsGetEvent().
"""

import ctypes
import os
import struct
import sys
import time
from pathlib import Path

from .config import EDSDK_DLL, PROJECT_DIR

# --- stale EDSDK (EDSDK.h, SDK 13.x) ---
_EDS_ERR_OK = 0
_EDS_ERR_DEVICE_BUSY = 0x0081
_EDS_ERR_OBJECT_NOTREADY = 0xA102
_EDS_ERR_TAKE_PICTURE_AF_NG = 0x8D01

_PROP_SAVE_TO = 0x000B
_PROP_EVF_MODE = 0x0501
_PROP_EVF_OUTPUT_DEVICE = 0x0500
_SAVE_TO_HOST = 2
_EVF_OUTPUT_PC = 2

_CMD_PRESS_SHUTTER = 0x0004
_SHUTTER_OFF = 0
_SHUTTER_COMPLETELY = 3

_OBJECT_EVENT_ALL = 0x0200
_OBJECT_EVENT_DIR_ITEM_REQUEST_TRANSFER = 0x0208

_CAPTURE_TIMEOUT_S = 30
_FIRST_FRAME_TIMEOUT_S = 10
_JPEG_MAGIC = b"\xff\xd8"

_ERROR_HINTS = {
    _EDS_ERR_DEVICE_BUSY: "aparat zajety (BUSY) — odczekaj chwile lub power-cycle",
    _EDS_ERR_TAKE_PICTURE_AF_NG: "AF nie zlapal ostrosci — popraw kadr lub przelacz na MF",
    _EDS_ERR_OBJECT_NOTREADY: "obiekt jeszcze nie gotowy",
}


class _EdsCapacity(ctypes.Structure):
    _fields_ = [("numberOfFreeClusters", ctypes.c_int32),
                ("bytesPerSector", ctypes.c_int32),
                ("reset", ctypes.c_int32)]


class _EdsDirectoryItemInfo(ctypes.Structure):
    _fields_ = [("size", ctypes.c_uint64),
                ("isFolder", ctypes.c_int32),
                ("groupID", ctypes.c_uint32),
                ("option", ctypes.c_uint32),
                ("szFileName", ctypes.c_char * 256),
                ("format", ctypes.c_uint32),
                ("dateTime", ctypes.c_uint32)]


def find_edsdk_dll() -> Path | None:
    """Szuka EDSDK.dll: EDSDK_DLL z .env (plik lub katalog), potem PROJECT_DIR
    i PROJECT_DIR/edsdk. Uzywane tez przez make_camera_session() do auto-wyboru."""
    candidates = []
    if EDSDK_DLL:
        p = Path(EDSDK_DLL)
        candidates.append(p if p.suffix.lower() == ".dll" else p / "EDSDK.dll")
    candidates += [PROJECT_DIR / "EDSDK.dll", PROJECT_DIR / "edsdk" / "EDSDK.dll"]
    return next((p for p in candidates if p.is_file()), None)


def _dll_is_64bit(path: Path) -> bool:
    with open(path, "rb") as f:
        head = f.read(4096)
    pe_off = struct.unpack_from("<i", head, 60)[0]
    machine = struct.unpack_from("<H", head, pe_off + 4)[0]
    return machine == 0x8664


class EdsdkError(RuntimeError):
    def __init__(self, code: int, where: str) -> None:
        hint = _ERROR_HINTS.get(code)
        msg = f"EDSDK: {where} → blad 0x{code:04X}"
        super().__init__(f"{msg} ({hint})" if hint else msg)
        self.code = code


class EdsdkSession:
    def __init__(self) -> None:
        self._sdk = None
        self._camera = None
        self._initialized = False
        self._handler_ref = None      # WINFUNCTYPE — musi zyc tak dlugo jak sesja
        self._pending_item = None     # DirItem czekajacy na download (z callbacka)

    # --- niskopoziomowe ---

    def _load(self):
        dll = find_edsdk_dll()
        if dll is None:
            raise RuntimeError(
                "Nie znaleziono EDSDK.dll. Pobierz Canon EDSDK (x64) z programu "
                "deweloperskiego Canona i poloz EDSDK.dll + EdsImage.dll obok "
                "aplikacji (albo ustaw EDSDK_DLL w .env). Szczegoly: WINDOWS.md."
            )
        if not _dll_is_64bit(dll):
            raise RuntimeError(
                f"{dll} jest 32-bitowa — 64-bitowy Python jej nie zaladuje. "
                "Potrzebna wersja x64 z oficjalnego SDK Canona (paczka zawiera obie)."
            )
        os.add_dll_directory(str(dll.parent))
        try:
            sdk = ctypes.WinDLL(str(dll))
        except OSError as exc:
            raise RuntimeError(
                f"Nie udalo sie zaladowac {dll}: {exc}. Sprawdz, czy obok lezy "
                "EdsImage.dll z tej samej paczki SDK."
            ) from exc
        u64 = ctypes.c_uint64
        void_p = ctypes.c_void_p
        sdk.EdsCreateMemoryStream.argtypes = [u64, ctypes.POINTER(void_p)]
        sdk.EdsDownload.argtypes = [void_p, u64, void_p]
        sdk.EdsGetLength.argtypes = [void_p, ctypes.POINTER(u64)]
        sdk.EdsSetPropertyData.argtypes = [void_p, ctypes.c_uint32, ctypes.c_int32,
                                           ctypes.c_uint32, void_p]
        return sdk

    def _check(self, code: int, where: str) -> None:
        if code != _EDS_ERR_OK:
            raise EdsdkError(code, where)

    def _set_u32(self, prop: int, value: int, where: str, required: bool = True) -> None:
        val = ctypes.c_uint32(value)
        code = self._sdk.EdsSetPropertyData(self._camera, prop, 0, 4, ctypes.byref(val))
        if required:
            self._check(code, where)

    def _pump(self) -> None:
        self._sdk.EdsGetEvent()

    # --- interfejs CameraSession ---

    def open(self) -> None:
        if sys.platform != "win32":
            raise RuntimeError("backend edsdk dziala tylko na Windows")
        self._sdk = self._load()
        self._check(self._sdk.EdsInitializeSDK(), "EdsInitializeSDK")
        self._initialized = True

        cam_list = ctypes.c_void_p()
        self._check(self._sdk.EdsGetCameraList(ctypes.byref(cam_list)), "EdsGetCameraList")
        try:
            count = ctypes.c_ulong()
            self._check(self._sdk.EdsGetChildCount(cam_list, ctypes.byref(count)),
                        "EdsGetChildCount")
            if count.value == 0:
                raise RuntimeError(
                    "EDSDK nie widzi zadnego aparatu — sprawdz kabel USB i czy "
                    "aparat jest wlaczony (nie w trybie odtwarzania)."
                )
            camera = ctypes.c_void_p()
            self._check(self._sdk.EdsGetChildAtIndex(cam_list, 0, ctypes.byref(camera)),
                        "EdsGetChildAtIndex")
            self._camera = camera
        finally:
            self._sdk.EdsRelease(cam_list)

        self._check(self._sdk.EdsOpenSession(self._camera), "EdsOpenSession")

        # zdjecia ida prosto do nas, nie na karte
        self._set_u32(_PROP_SAVE_TO, _SAVE_TO_HOST, "SaveTo=Host")
        cap = _EdsCapacity(0x7FFFFFFF, 0x1000, 1)
        self._check(self._sdk.EdsSetCapacity(self._camera, cap), "EdsSetCapacity")

        handler_t = ctypes.WINFUNCTYPE(ctypes.c_uint32, ctypes.c_uint32,
                                       ctypes.c_void_p, ctypes.c_void_p)

        def _on_object(event, obj, _ctx):
            if event == _OBJECT_EVENT_DIR_ITEM_REQUEST_TRANSFER:
                self._pending_item = obj
            elif obj:
                self._sdk.EdsRelease(obj)
            return _EDS_ERR_OK

        self._handler_ref = handler_t(_on_object)
        self._check(self._sdk.EdsSetObjectEventHandler(
            self._camera, _OBJECT_EVENT_ALL, self._handler_ref, None),
            "EdsSetObjectEventHandler")

        # live view na PC; Evf_Mode nie istnieje na czesci modeli — nie wymagamy
        self._set_u32(_PROP_EVF_MODE, 1, "Evf_Mode", required=False)
        self._set_u32(_PROP_EVF_OUTPUT_DEVICE, _EVF_OUTPUT_PC, "Evf_OutputDevice=PC")

        # pierwsza klatka potwierdza, ze aparat naprawde streamuje
        deadline = time.monotonic() + _FIRST_FRAME_TIMEOUT_S
        while True:
            try:
                self.preview_frame()
                return
            except EdsdkError as exc:
                if exc.code != _EDS_ERR_OBJECT_NOTREADY or time.monotonic() >= deadline:
                    raise
                time.sleep(0.2)

    def preview_frame(self) -> bytes:
        stream = ctypes.c_void_p()
        self._check(self._sdk.EdsCreateMemoryStream(0, ctypes.byref(stream)),
                    "EdsCreateMemoryStream")
        evf = ctypes.c_void_p()
        try:
            self._check(self._sdk.EdsCreateEvfImageRef(stream, ctypes.byref(evf)),
                        "EdsCreateEvfImageRef")
            self._pump()
            self._check(self._sdk.EdsDownloadEvfImage(self._camera, evf),
                        "EdsDownloadEvfImage")
            data = self._stream_bytes(stream)
        finally:
            if evf.value:
                self._sdk.EdsRelease(evf)
            self._sdk.EdsRelease(stream)
        if not data.startswith(_JPEG_MAGIC):
            raise RuntimeError("EDSDK: klatka live view nie jest JPEG-iem")
        return data

    def capture_to(self, workdir: Path) -> Path:
        self._pending_item = None
        code = self._sdk.EdsSendCommand(self._camera, _CMD_PRESS_SHUTTER,
                                        _SHUTTER_COMPLETELY)
        self._sdk.EdsSendCommand(self._camera, _CMD_PRESS_SHUTTER, _SHUTTER_OFF)
        self._check(code, "PressShutterButton")

        deadline = time.monotonic() + _CAPTURE_TIMEOUT_S
        while self._pending_item is None:
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"EDSDK: aparat nie oddal zdjecia w {_CAPTURE_TIMEOUT_S} s "
                    "(transfer nie doszedl?)"
                )
            self._pump()
            time.sleep(0.05)

        item = self._pending_item
        self._pending_item = None
        try:
            info = _EdsDirectoryItemInfo()
            self._check(self._sdk.EdsGetDirectoryItemInfo(item, ctypes.byref(info)),
                        "EdsGetDirectoryItemInfo")
            stream = ctypes.c_void_p()
            self._check(self._sdk.EdsCreateMemoryStream(0, ctypes.byref(stream)),
                        "EdsCreateMemoryStream")
            try:
                self._check(self._sdk.EdsDownload(item, info.size, stream), "EdsDownload")
                self._check(self._sdk.EdsDownloadComplete(item), "EdsDownloadComplete")
                data = self._stream_bytes(stream)
            finally:
                self._sdk.EdsRelease(stream)
        finally:
            self._sdk.EdsRelease(item)

        name = info.szFileName.decode("ascii", "replace") or "capture.jpg"
        target = workdir / name
        target.write_bytes(data)
        return target

    def _stream_bytes(self, stream) -> bytes:
        length = ctypes.c_uint64()
        self._check(self._sdk.EdsGetLength(stream, ctypes.byref(length)), "EdsGetLength")
        ptr = ctypes.c_void_p()
        self._check(self._sdk.EdsGetPointer(stream, ctypes.byref(ptr)), "EdsGetPointer")
        return ctypes.string_at(ptr, length.value)

    def get_settings(self) -> dict:
        # ekspozycje ustawia sie na aparacie — jak w backendzie digiCamControl
        return {}

    def set_setting(self, key: str, value: str) -> None:
        raise RuntimeError("zmiana ustawien aparatu niedostepna przez backend edsdk — "
                           "ustaw na aparacie")

    def describe_contrast(self) -> dict | None:
        return None

    def set_contrast(self, value) -> str:
        raise RuntimeError("kontrast niedostepny przez backend edsdk")

    def close(self) -> None:
        if self._sdk is None:
            return
        if self._camera is not None:
            try:
                self._set_u32(_PROP_EVF_OUTPUT_DEVICE, 0, "Evf off", required=False)
                self._sdk.EdsCloseSession(self._camera)
                self._sdk.EdsRelease(self._camera)
            except OSError:
                pass
            self._camera = None
        if self._initialized:
            try:
                self._sdk.EdsTerminateSDK()
            except OSError:
                pass
            self._initialized = False
        self._sdk = None
