import sys

from .i18n import EN, tr

EN.update({
    "BRAK EDSDK.framework w katalogu aplikacji": "EDSDK.framework MISSING from the app folder",
    "BRAK EDSDK.dll obok aplikacji — połóż EDSDK.dll + EdsImage.dll (x64) obok .exe, patrz README":
        "EDSDK.dll MISSING next to the app — put EDSDK.dll + EdsImage.dll (x64) next to the .exe, "
        "see README",
    "znaleziono {dll}": "found {dll}",
    "; SDK w osobnym procesie": "; SDK in a separate process",
})

# Bledy aparatu: EdsdkError dziedziczy po RuntimeError, a proces-dziecko
# (camera_proc) zglasza zawieszke tez jako RuntimeError.
CAMERA_ERRORS: tuple = (RuntimeError, OSError)


def make_camera_session():
    """Aparat obsluguje WYLACZNIE Canon EDSDK (od 2.3; gphoto2, tryb
    terminalowy i backend digiCamControl usuniete). Brak SDK konczy sie
    czytelnym bledem z EdsdkSession.open() i karta „Brak sterownika aparatu
    Canon" w UI.
    Zwracany obiekt ma interfejs open/preview_frame/capture_to/get_settings/
    set_setting/close oraz `backend_info` — TEKST z powodem wyboru, ktory
    webui wypisuje do logu przy starcie."""
    from .camera_edsdk import find_edsdk_dll
    from .config import CAMERA_EDSDK_ISOLATION
    dll = find_edsdk_dll()
    missing = (tr("BRAK EDSDK.framework w katalogu aplikacji") if sys.platform == "darwin"
               else tr("BRAK EDSDK.dll obok aplikacji — połóż EDSDK.dll "
                       "+ EdsImage.dll (x64) obok .exe, patrz README"))
    reason = tr("znaleziono {dll}", dll=dll) if dll else missing
    if CAMERA_EDSDK_ISOLATION:
        # SDK w osobnym procesie: zawieszka w DLL-u = kill dziecka +
        # swiezy EdsInitializeSDK, nie martwa aplikacja (patrz camera_proc)
        from .camera_proc import EdsdkProxy
        session = EdsdkProxy()
        reason += tr("; SDK w osobnym procesie")
    else:
        from .camera_edsdk import EdsdkSession
        session = EdsdkSession()
    session.backend_info = f"edsdk ({reason})"
    return session
