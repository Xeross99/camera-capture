# -*- mode: python ; coding: utf-8 -*-
# Build .exe (uruchamiac NA Windowsie — PyInstaller nie cross-kompiluje):
#   build_windows.bat        (albo recznie: pyinstaller --noconfirm CameraCapture.spec)
# Wynik: dist/CameraCapture/CameraCapture.exe (onedir; .env i photos/ zyja
# obok .exe — patrz PROJECT_DIR w src/config.py).

from PyInstaller.utils.hooks import collect_all

datas = [
    ("src/webui_static", "src/webui_static"),
    ("assets", "assets"),
]
binaries = []
hiddenimports = [
    "webview.platforms.winforms",
    "webview.platforms.edgechromium",
]

# rembg/onnxruntime maja natywne DLL-e i dane poza importami — collect_all
# jest najpewniejsze; webview dla platform backends.
for pkg in ("rembg", "onnxruntime", "webview"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ["gui.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["gphoto2", "usb", "termios", "tty"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CameraCapture",
    debug=False,
    strip=False,
    upx=False,
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="CameraCapture",
)
