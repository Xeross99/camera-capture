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
from contextlib import contextmanager
from pathlib import Path

from .config import EDSDK_DLL, PROJECT_DIR

# --- stale EDSDK (EDSDK.h, SDK 13.x) ---
_EDS_ERR_OK = 0
_EDS_ERR_INTERNAL_ERROR = 0x0002
_EDS_ERR_DEVICE_BUSY = 0x0081
_EDS_ERR_OBJECT_NOTREADY = 0xA102
_EDS_ERR_TAKE_PICTURE_AF_NG = 0x8D01

_PROP_SAVE_TO = 0x000B
_PROP_EVF_MODE = 0x0501
_PROP_EVF_OUTPUT_DEVICE = 0x0500
_PROP_EXPOSURE_COMP = 0x0407      # kEdsPropID_ExposureCompensation
_SAVE_TO_HOST = 2
_EVF_OUTPUT_TFT = 1               # ekran aparatu
_EVF_OUTPUT_PC = 2                # strumien EVF do komputera; maska bitowa — 3 = oba

# Kompensacja ekspozycji: kody Canona (bajt ze znakiem w uzupelnieniu do dwoch,
# krok 1/3 EV to 0x03/0x05/0x08 na kolejna 1/3) -> etykieta dla UI. Tabela ma
# tez wartosci polowkowe, bo aparat przestawiony na kroki 1/2 EV zwroci wlasnie
# je i chcemy je UMIEC POKAZAC, nawet jesli sami proponujemy tylko trzecie.
_EV_CODES = {
    0x18: "+3", 0x15: "+2 2/3", 0x14: "+2 1/2", 0x13: "+2 1/3", 0x10: "+2",
    0x0D: "+1 2/3", 0x0C: "+1 1/2", 0x0B: "+1 1/3", 0x08: "+1",
    0x05: "+2/3", 0x04: "+1/2", 0x03: "+1/3", 0x00: "0",
    0xFD: "-1/3", 0xFC: "-1/2", 0xFB: "-2/3", 0xF8: "-1",
    0xF5: "-1 1/3", 0xF4: "-1 1/2", 0xF3: "-1 2/3", 0xF0: "-2",
    0xED: "-2 1/3", 0xEC: "-2 1/2", 0xEB: "-2 2/3", 0xE8: "-3",
}
# Do wyboru w UI tylko kroki 1/3 EV — tak stoi M50 II fabrycznie. Kolejnosc od
# najciemniejszej do najjasniejszej, bo UI przesuwa sie po indeksie.
_EV_THIRDS = [0xE8, 0xEB, 0xED, 0xF0, 0xF3, 0xF5, 0xF8, 0xFB, 0xFD,
              0x00, 0x03, 0x05, 0x08, 0x0B, 0x0D, 0x10, 0x13, 0x15, 0x18]
_EV_LABEL_TO_CODE = {label: code for code, label in _EV_CODES.items()}
_EV_UNKNOWN = 0xFFFFFFFF          # aparat w trybie, ktory nie ma kompensacji

_CMD_PRESS_SHUTTER = 0x0004
_SHUTTER_OFF = 0
_SHUTTER_COMPLETELY = 3

_OBJECT_EVENT_ALL = 0x0200
_OBJECT_EVENT_DIR_ITEM_REQUEST_TRANSFER = 0x0208
# Zdarzenia, przy ktorych dostajemy uchwyt do POBRANIA pliku. `RequestTransfer`
# przychodzi przy SaveTo=Host, `DirItemCreated` gdy zdjecie wyladowalo na karcie
# (SaveTo nie zaskoczylo) — sciagnac da sie w obu przypadkach, wiec bierzemy oba
# zamiast czekac w nieskonczonosc na ten jeden wlasciwy.
_OBJECT_EVENTS_WITH_ITEM = (
    0x0208,   # kEdsObjectEvent_DirItemRequestTransfer
    0x0209,   # kEdsObjectEvent_DirItemRequestTransferDT
    0x0204,   # kEdsObjectEvent_DirItemCreated  (plik na karcie)
)

_CAPTURE_TIMEOUT_S = 30
_CARD_FALLBACK_S = 8          # po tylu sekundach ciszy szukamy pliku na karcie
_CARD_SCAN_DEPTH = 3          # wolumen -> DCIM -> 100CANON -> pliki
_FIRST_FRAME_TIMEOUT_S = 10
_JPEG_MAGIC = b"\xff\xd8"

_PM_REMOVE = 0x0001


class _Msg(ctypes.Structure):
    _fields_ = [("hwnd", ctypes.c_void_p),
                ("message", ctypes.c_uint32),
                ("wParam", ctypes.c_uint64),
                ("lParam", ctypes.c_int64),
                ("time", ctypes.c_uint32),
                ("pt_x", ctypes.c_int32),
                ("pt_y", ctypes.c_int32)]

_ERROR_HINTS = {
    _EDS_ERR_INTERNAL_ERROR: "blad wewnetrzny SDK — zwykle chwilowy",
    _EDS_ERR_DEVICE_BUSY: "aparat zajety (BUSY) — odczekaj chwile lub power-cycle",
    _EDS_ERR_TAKE_PICTURE_AF_NG: "AF nie zlapal ostrosci — popraw kadr lub przelacz na MF",
    _EDS_ERR_OBJECT_NOTREADY: "obiekt jeszcze nie gotowy",
}

# SDK jest ladowane i inicjalizowane RAZ NA PROCES i NIGDY nie dostaje
# EdsTerminateSDK. Cykl Terminate -> Initialize w tym samym procesie konczy
# sie w EDSDK access violation przy drugim podejsciu (zaobserwowane w polu:
# chwilowy blad EVF ubijal sesje, a kazda proba ponownego polaczenia padala
# na "access violation reading 0x...50" az do restartu aplikacji). System
# posprzata przy wyjsciu procesu — gui.py i tak konczy przez os._exit().
_SDK = None
_SDK_INITIALIZED = False
_HANDLER_TYPE = None
_USER32 = None


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
        self._handler_ref = None      # instancja callbacka — musi zyc tak dlugo jak sesja
        self._pending_item = None     # DirItem czekajacy na download (z callbacka)
        self._seen_events = []        # kody zdarzen obiektowych — diagnostyka
        self._downloaded = set()      # nazwy juz sciagnietych plikow (anty-duplikat)
        self._evf_out = _EVF_OUTPUT_PC  # przyjete przez aparat wyjscie live view
        self.on_status = None         # opcjonalny kanal do paska stanu w UI
        self.on_log = None            # opcjonalny kanal do logu w UI

    # --- niskopoziomowe ---

    def _load(self):
        global _SDK, _HANDLER_TYPE, _USER32
        if _SDK is not None:
            return _SDK
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
        # argtypes MUSZA byc kompletne: bez nich ctypes przepycha Pythonowy int
        # jako 32-bitowy `int`, a uchwyty EDSDK (EdsBaseRef) na x64 to wskazniki
        # powyzej 4 GB. Ucinaly sie po drodze, wiec kazde wywolanie z uchwytem
        # zlapanym w callbacku (EdsGetDirectoryItemInfo, EdsDownload, EdsRelease)
        # dostawalo smiec zamiast referencji na zdjecie.
        u32, i32, u64 = ctypes.c_uint32, ctypes.c_int32, ctypes.c_uint64
        void_p = ctypes.c_void_p
        p_void_p = ctypes.POINTER(void_p)
        _HANDLER_TYPE = ctypes.WINFUNCTYPE(u32, u32, void_p, void_p)
        sdk.EdsGetCameraList.argtypes = [p_void_p]
        sdk.EdsGetChildCount.argtypes = [void_p, ctypes.POINTER(u32)]
        sdk.EdsGetChildAtIndex.argtypes = [void_p, i32, p_void_p]
        sdk.EdsGetDirectoryItemInfo.argtypes = [void_p,
                                                ctypes.POINTER(_EdsDirectoryItemInfo)]
        sdk.EdsOpenSession.argtypes = [void_p]
        sdk.EdsCloseSession.argtypes = [void_p]
        sdk.EdsRelease.argtypes = [void_p]
        sdk.EdsSetCapacity.argtypes = [void_p, _EdsCapacity]
        sdk.EdsSendCommand.argtypes = [void_p, u32, i32]
        sdk.EdsSetObjectEventHandler.argtypes = [void_p, u32, _HANDLER_TYPE, void_p]
        sdk.EdsCreateMemoryStream.argtypes = [u64, p_void_p]
        sdk.EdsCreateEvfImageRef.argtypes = [void_p, p_void_p]
        sdk.EdsDownloadEvfImage.argtypes = [void_p, void_p]
        sdk.EdsDownload.argtypes = [void_p, u64, void_p]
        sdk.EdsDownloadComplete.argtypes = [void_p]
        sdk.EdsGetPointer.argtypes = [void_p, p_void_p]
        sdk.EdsGetLength.argtypes = [void_p, ctypes.POINTER(u64)]
        sdk.EdsSetPropertyData.argtypes = [void_p, u32, i32, u32, void_p]
        sdk.EdsGetPropertyData.argtypes = [void_p, u32, i32, u32, void_p]

        _USER32 = ctypes.WinDLL("user32")
        _USER32.PeekMessageW.argtypes = [ctypes.POINTER(_Msg), void_p, u32, u32, u32]
        _USER32.PeekMessageW.restype = ctypes.c_int
        _USER32.TranslateMessage.argtypes = [ctypes.POINTER(_Msg)]
        _USER32.DispatchMessageW.argtypes = [ctypes.POINTER(_Msg)]
        _SDK = sdk
        return sdk

    def _check(self, code: int, where: str) -> None:
        if code != _EDS_ERR_OK:
            raise EdsdkError(code, where)

    def _set_u32(self, prop: int, value: int, where: str, required: bool = True) -> None:
        val = ctypes.c_uint32(value)
        code = self._sdk.EdsSetPropertyData(self._camera, prop, 0, 4, ctypes.byref(val))
        if required:
            self._check(code, where)

    def _get_u32(self, prop: int) -> int | None:
        """None, gdy aparat nie oddaje wartosci (np. property niedostepne w
        biezacym trybie) — wolajacy ma to potraktowac jak brak, nie jak blad."""
        val = ctypes.c_uint32()
        code = self._sdk.EdsGetPropertyData(self._camera, prop, 0, 4, ctypes.byref(val))
        return val.value if code == _EDS_ERR_OK else None

    def _init_com(self) -> None:
        """COM w apartamencie jednowatkowym MUSI byc zainicjowany w tym samym
        watku, ktory wola SDK.

        Na Windowsie EDSDK dostarcza zdarzenia aparatu przez kolejke komunikatow
        COM, a `EdsGetEvent()` je z niej zbiera. Bez `CoInitializeEx` migawka
        strzela normalnie (to zwykla komenda po USB), ale zdarzenie
        `DirItemRequestTransfer` nigdy nie dolatuje — aplikacja stoi na
        „Wyzwalam migawke…", az wpadnie w timeout. Objaw myli, bo aparat
        slychac, wiec wyglada na zaciecie aplikacji, a nie na brak zdarzenia.

        RPC_E_CHANGED_MODE (0x80010106) = ktos juz zainicjowal ten watek w innym
        modelu; S_FALSE = juz zainicjowany. Oba sa nieszkodliwe. CoUninitialize
        NIE jest wolane przy zamykaniu sesji — watek camera zyje przez caly
        proces i przy reconnekcie wraca tu ten sam watek (S_FALSE), a zrywanie
        apartamentu pod zainicjalizowanym SDK to proszenie sie o klopoty."""
        try:
            ctypes.windll.ole32.CoInitializeEx(None, 0x2)  # APARTMENTTHREADED
        except OSError:
            pass

    def _pump(self) -> None:
        """`EdsGetEvent()` + przepompowanie kolejki komunikatow Windows.

        COM w apartamencie jednowatkowym dostarcza wywolania przez ukryte okno
        i jego kolejke komunikatow. Watek, ktory jej nie obsluguje, nigdy nie
        zobaczy zdarzenia z aparatu — samo `EdsGetEvent()` wystarcza w aplikacji
        konsolowej, ktora i tak stoi w petli komunikatow, ale nasz watek camera
        zadnej nie ma. Dokladnie tak wyglada objaw: migawka strzela, plik nigdy
        nie przychodzi. Limit 32 komunikatow na obrot, zeby pompa nie zjadla
        petli czekania."""
        self._sdk.EdsGetEvent()
        if _USER32 is None:
            return
        msg = _Msg()
        for _ in range(32):
            if not _USER32.PeekMessageW(ctypes.byref(msg), None, 0, 0, _PM_REMOVE):
                return
            _USER32.TranslateMessage(ctypes.byref(msg))
            _USER32.DispatchMessageW(ctypes.byref(msg))

    def _status(self, text: str) -> None:
        if self.on_status is not None:
            try:
                self.on_status(text)
            except Exception:
                pass

    def _log(self, text: str, kind: str = "info") -> None:
        """Do logu w UI, jesli backend dostal kanal; inaczej na stdout (TUI/CLI
        i tak go przechwytuje)."""
        if self.on_log is not None:
            try:
                self.on_log(text, kind)
                return
            except Exception:
                pass
        print(text)

    # --- interfejs CameraSession ---

    def open(self) -> None:
        global _SDK_INITIALIZED
        if sys.platform != "win32":
            raise RuntimeError("backend edsdk dziala tylko na Windows")
        self._init_com()
        self._sdk = self._load()
        if not _SDK_INITIALIZED:
            self._check(self._sdk.EdsInitializeSDK(), "EdsInitializeSDK")
            _SDK_INITIALIZED = True

        cam_list = ctypes.c_void_p()
        self._check(self._sdk.EdsGetCameraList(ctypes.byref(cam_list)), "EdsGetCameraList")
        try:
            # c_uint32, nie c_ulong: argtypes deklaruja POINTER(c_uint32), a ctypes
            # odrzuca byref innej klasy, nawet o tym samym rozmiarze
            count = ctypes.c_uint32()
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

        def _on_object(event, obj, _ctx):
            # Kazde zdarzenie zapamietujemy: gdy zdjecie nie dojdzie, to jedyny
            # slad, czy aparat w ogole cos przyslal, czy nic do nas nie dociera.
            if event not in self._seen_events:
                self._seen_events.append(event)
            if event in _OBJECT_EVENTS_WITH_ITEM and self._pending_item is None:
                self._pending_item = obj
            elif obj:
                self._sdk.EdsRelease(obj)
            return _EDS_ERR_OK

        self._handler_ref = _HANDLER_TYPE(_on_object)
        self._check(self._sdk.EdsSetObjectEventHandler(
            self._camera, _OBJECT_EVENT_ALL, self._handler_ref, None),
            "EdsSetObjectEventHandler")

        # live view na PC ORAZ na ekranie aparatu (TFT|PC) — operator kadruje
        # takze patrzac na aparat. Wyjscie to maska bitowa; czesc modeli
        # kombinacje odrzuca albo po cichu przycina, wiec czytamy wartosc
        # z powrotem i w razie czego wracamy do samego PC (bez tego live view
        # w ogole by nie ruszyl). Evf_Mode nie istnieje na czesci modeli.
        self._set_u32(_PROP_EVF_MODE, 1, "Evf_Mode", required=False)
        both = _EVF_OUTPUT_TFT | _EVF_OUTPUT_PC
        self._set_u32(_PROP_EVF_OUTPUT_DEVICE, both,
                      "Evf_OutputDevice=TFT+PC", required=False)
        got = self._get_u32(_PROP_EVF_OUTPUT_DEVICE)
        if got is not None and (got & _EVF_OUTPUT_PC) and (got & _EVF_OUTPUT_TFT):
            self._evf_out = got
        else:
            self._set_u32(_PROP_EVF_OUTPUT_DEVICE, _EVF_OUTPUT_PC,
                          "Evf_OutputDevice=PC")
            self._evf_out = _EVF_OUTPUT_PC
            self._log("Aparat nie przyjął podglądu równolegle na PC i LCD — "
                      "ekran aparatu zostaje wygaszony.", "warn")

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
        # Chwilowy blad EVF (INTERNAL_ERROR przy zapisie/AF, NOTREADY) nie
        # moze ubijac polaczenia: webui na kazdy wyjatek podgladu odpowiada
        # pelnym close/open sesji, a to gruba operacja. Dwie dodatkowe proby
        # w miejscu zalatwiaja czkawke; blad trwaly i tak wyleci trzecim razem.
        last: EdsdkError | None = None
        for attempt in range(3):
            if attempt:
                time.sleep(0.15)
            try:
                return self._preview_frame_once()
            except EdsdkError as exc:
                if exc.code not in (_EDS_ERR_INTERNAL_ERROR,
                                    _EDS_ERR_OBJECT_NOTREADY,
                                    _EDS_ERR_DEVICE_BUSY):
                    raise
                last = exc
        raise last

    def _preview_frame_once(self) -> bytes:
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
        try:
            return self._capture_to_inner(workdir)
        finally:
            # Zaobserwowane w polu (Ryzen 5800H + RTX 3080; identyczny .exe na
            # innym laptopie dziala): PIERWSZE EdsDownloadEvfImage tuz po
            # zdjeciu wisi na zawsze wewnatrz DLL-a — watchdog pokazywal
            # „pobieranie klatki podgladu, stoi na tym 108 s", a uwalnialo
            # dopiero wypiecie kabla USB. Po strzale dajemy wiec aparatowi
            # dokonczyc przejscie stanu (pompowanie zdarzen ~0,6 s) i
            # restartujemy potok EVF przez ponowne ustawienie wyjscia — ten sam
            # zabieg, ktorym _evf_paused wskrzesza podglad po skanie karty.
            self._settle_after_capture()

    def _settle_after_capture(self) -> None:
        deadline = time.monotonic() + 0.6
        while time.monotonic() < deadline:
            self._pump()
            time.sleep(0.05)
        self._set_u32(_PROP_EVF_OUTPUT_DEVICE, self._evf_out,
                      "Evf restart po zdjęciu", required=False)

    def _capture_to_inner(self, workdir: Path) -> Path:
        if self._pending_item is not None:
            self._sdk.EdsRelease(self._pending_item)   # spozniony uchwyt z poprzedniego strzalu
        self._pending_item = None
        self._seen_events = []
        # Pojemnosc hosta odswiezana PRZED kazdym strzalem: aparat odejmuje sobie
        # zadeklarowane miejsce po kazdym zdjeciu i po kilku ujeciach uznaje, ze
        # nie ma gdzie odeslac pliku — przestaje go wtedy oddawac bez zadnego bledu.
        self._sdk.EdsSetCapacity(self._camera, _EdsCapacity(0x7FFFFFFF, 0x1000, 1))
        code = self._sdk.EdsSendCommand(self._camera, _CMD_PRESS_SHUTTER,
                                        _SHUTTER_COMPLETELY)
        self._sdk.EdsSendCommand(self._camera, _CMD_PRESS_SHUTTER, _SHUTTER_OFF)
        self._check(code, "PressShutterButton")

        started = time.monotonic()
        deadline = started + _CAPTURE_TIMEOUT_S
        card_at = started + _CARD_FALLBACK_S
        last_evf = 0.0
        last_status = 0.0
        while self._pending_item is None:
            now = time.monotonic()
            # Aparat mial swoja szanse zglosic plik sam. Skoro milczy, szukamy
            # zdjecia tam, gdzie i tak wyladowalo — na karcie. To ratuje ujecie
            # zamiast konczyc bledem po 30 s ciszy.
            if now >= card_at:
                card_at = float("inf")
                self._status("Aparat nie zglosil pliku — szukam na karcie…")
                found = self._download_newest_from_card(workdir)
                if found is not None:
                    self._log(f"Aparat nie zglosil pliku po USB — zdjęcie pobrane "
                              f"z karty ({found.name}).", "warn")
                    return found
            if now >= deadline:
                # ostatnia szansa: przy pierwszym skanie (8 s) plik mogl sie
                # jeszcze zapisywac na wolnej karcie
                found = self._download_newest_from_card(workdir)
                if found is not None:
                    self._log(f"Aparat nie zglosil pliku po USB — zdjęcie pobrane "
                              f"z karty ({found.name}).", "warn")
                    return found
                seen = ", ".join(f"0x{e:04X}" for e in self._seen_events) or "ZADNYCH"
                save_to = self._get_u32(_PROP_SAVE_TO)
                raise RuntimeError(
                    f"EDSDK: migawka zadzialala, ale aparat nie oddal pliku w "
                    f"{_CAPTURE_TIMEOUT_S} s (na karcie tez nic nowego nie "
                    f"znalazlem). Zdarzenia od aparatu: {seen}; "
                    f"SaveTo={save_to} (2 = do komputera). "
                    "Sprobuj wypiac i wpiac kabel USB."
                )
            if now - last_status >= 1.0:
                last_status = now
                self._status(f"Czekam na plik z aparatu… {int(now - started)} s")
            self._pump()
            # Podglad jest ciagniety dalej, mimo ze klatki lecą do kosza. W GUI
            # Canona petla EVF chodzi przez caly czas robienia zdjecia i to ona
            # jest wzorcem; przy bezlusterkowcu przerwanie odbioru EVF potrafi
            # zatrzymac aparat w polowie transakcji. Bledy sa tu bez znaczenia —
            # w trakcie zapisu EVF ma prawo nie odpowiadac.
            if now - last_evf >= 0.2:
                last_evf = now
                try:
                    self.preview_frame()
                except Exception:
                    pass
            time.sleep(0.05)

        item = self._pending_item
        self._pending_item = None
        self._status("Pobieram zdjecie z aparatu…")
        try:
            return self._download_item(item, workdir)
        finally:
            self._sdk.EdsRelease(item)

    def _download_item(self, item, workdir: Path) -> Path:
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
        name = info.szFileName.decode("ascii", "replace") or "capture.jpg"
        self._downloaded.add(name)
        target = workdir / name
        target.write_bytes(data)
        return target

    # --- awaryjne pobranie z karty ---

    @contextmanager
    def _evf_paused(self):
        """Listowanie karty przy wlaczonym live view aparat potrafi zignorowac —
        gasimy podglad na czas skanowania. Jesli nie uda sie go wskrzesic, watek
        camera w webui i tak sam wykryje martwy podglad i przelaczy sesje."""
        self._set_u32(_PROP_EVF_OUTPUT_DEVICE, 0, "Evf off", required=False)
        try:
            yield
        finally:
            self._set_u32(_PROP_EVF_OUTPUT_DEVICE, self._evf_out,
                          "Evf on", required=False)

    def _download_newest_from_card(self, workdir: Path) -> Path | None:
        """Najnowszy plik z karty, ktorego jeszcze nie sciagnelismy w tej sesji.

        Anty-duplikat opiera sie na nazwach juz pobranych plikow: gdy zdjecie
        mimo wszystko nie powstalo, jedyny kandydat to poprzednie ujecie, ktore
        jest wtedy na liscie i zostaje odrzucone. Zdjecia sprzed uruchomienia
        aplikacji sa nieznane, wiec pierwszy strzal jest tu ryzykiem — dlatego
        pobranie z karty ZAWSZE zostawia slad w logu."""
        item = None
        try:
            with self._evf_paused():
                item, _name, _stamp = self._scan_children(self._camera,
                                                          (None, None, -1), 0)
                if item is None:
                    return None
                return self._download_item(item, workdir)
        except (EdsdkError, OSError) as exc:
            self._log(f"✗ Nie udało się pobrać zdjęcia z karty: {exc}", "err")
            return None
        finally:
            if item is not None:
                self._sdk.EdsRelease(item)

    def _scan_children(self, parent, best: tuple, depth: int) -> tuple:
        """Rekurencyjnie: wolumen -> DCIM -> 100CANON -> pliki. Zwraca krotke
        (uchwyt, nazwa, dateTime) najnowszego pliku; uchwyt zwalnia wolajacy."""
        count = ctypes.c_uint32()
        if self._sdk.EdsGetChildCount(parent, ctypes.byref(count)) != _EDS_ERR_OK:
            return best
        for i in range(count.value):
            child = ctypes.c_void_p()
            if self._sdk.EdsGetChildAtIndex(parent, i, ctypes.byref(child)) != _EDS_ERR_OK:
                continue
            info = _EdsDirectoryItemInfo()
            # Dzieci aparatu to WOLUMENY, nie pliki — nie ma po co pytac ich
            # o DirItemInfo (odpowiedz bywa smieciem), od razu schodzimy nizej.
            if depth == 0 or self._sdk.EdsGetDirectoryItemInfo(
                    child, ctypes.byref(info)) != _EDS_ERR_OK:
                if depth < _CARD_SCAN_DEPTH:
                    best = self._scan_children(child, best, depth + 1)
                self._sdk.EdsRelease(child)
                continue
            if info.isFolder:
                if depth < _CARD_SCAN_DEPTH:
                    best = self._scan_children(child, best, depth + 1)
                self._sdk.EdsRelease(child)
                continue
            name = info.szFileName.decode("ascii", "replace")
            # `<`, nie `<=`: przy rownym stemplu (niektore aparaty oddaja
            # dateTime=0 dla wszystkiego) wygrywa ostatni z enumeracji, a DCIM
            # enumeruje rosnaco po numerze pliku — ostatni = najnowszy
            if name in self._downloaded or info.dateTime < best[2]:
                self._sdk.EdsRelease(child)
                continue
            if best[0] is not None:
                self._sdk.EdsRelease(best[0])
            best = (child, name, info.dateTime)
        return best

    def _stream_bytes(self, stream) -> bytes:
        length = ctypes.c_uint64()
        self._check(self._sdk.EdsGetLength(stream, ctypes.byref(length)), "EdsGetLength")
        ptr = ctypes.c_void_p()
        self._check(self._sdk.EdsGetPointer(stream, ctypes.byref(ptr)), "EdsGetPointer")
        return ctypes.string_at(ptr, length.value)

    def get_settings(self) -> dict:
        """Tylko kompensacja ekspozycji — reszte (ISO, czas, przyslona) ustawia
        sie na aparacie. Pusty slownik, gdy aparat jej teraz nie oddaje: tak
        jest np. w trybie w pelni recznym, gdzie ta sama skala na ekranie
        aparatu jest juz tylko swiatlomierzem."""
        if self._camera is None:
            return {}
        raw = self._get_u32(_PROP_EXPOSURE_COMP)
        if raw is None or raw == _EV_UNKNOWN:
            return {}
        label = _EV_CODES.get(raw & 0xFF)
        if label is None:
            return {}
        return {"exposurecompensation": {
            "current": label,
            "choices": [_EV_CODES[c] for c in _EV_THIRDS],
        }}

    def get_setting(self, key: str) -> dict | None:
        """Odpowiednik CameraSession.get_setting — tu get_settings() i tak
        czyta jedna wlasciwosc, wiec bez osobnej szybkiej sciezki."""
        return self.get_settings().get(key)

    def set_setting(self, key: str, value: str) -> None:
        if key != "exposurecompensation":
            raise RuntimeError(
                f"zmiana '{key}' niedostepna przez backend edsdk — ustaw na aparacie")
        code = _EV_LABEL_TO_CODE.get(str(value).strip())
        if code is None:
            raise RuntimeError(f"nieznana kompensacja ekspozycji: {value!r}")
        # Aparat odrzuca wartosc spoza swojego zakresu/kroku (np. 1/3 EV, gdy
        # ustawiony jest krok 1/2) — niech to wyjdzie jako czytelny blad,
        # zamiast cicho nie zrobic nic.
        self._set_u32(_PROP_EXPOSURE_COMP, code, "ExposureCompensation")

    def describe_contrast(self) -> dict | None:
        return None

    def set_contrast(self, value) -> str:
        raise RuntimeError("kontrast niedostepny przez backend edsdk")

    def close(self) -> None:
        """Zamyka SESJE aparatu — SDK i COM zostaja zainicjalizowane na stale.

        EdsTerminateSDK tu NIE pada swiadomie: cykl Terminate -> Initialize
        w tym samym procesie konczy sie access violation przy kolejnym
        otwarciu (patrz komentarz przy _SDK) — a close/open to normalna
        droga petli reconnectu w webui po kazdym potknieciu podgladu."""
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
        self._handler_ref = None
        self._pending_item = None
        self._sdk = None
