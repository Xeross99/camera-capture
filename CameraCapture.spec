# -*- mode: python ; coding: utf-8 -*-
# Build .exe (uruchamiac NA Windowsie — PyInstaller nie cross-kompiluje):
#   build_windows.bat        (albo recznie: pyinstaller --noconfirm CameraCapture.spec)
# Wynik: dist/CameraCapture/CameraCapture.exe (onedir; .env i photos/ zyja
# obok .exe — patrz PROJECT_DIR w src/config.py).

import os
import sys

from PyInstaller.utils.hooks import collect_all, copy_metadata

# Wersja z src/version.py (jedno zrodlo prawdy — porownuje ja tez updater
# z tagiem na GitHubie), stad generowany zasob VS_VERSION_INFO dla .exe.
sys.path.insert(0, SPECPATH)
from src.version import APP_VERSION

_v = tuple(int(x) for x in (APP_VERSION.split(".") + ["0", "0", "0"])[:3]) + (0,)
_build = os.path.join(SPECPATH, "build")
os.makedirs(_build, exist_ok=True)
version_res = os.path.join(_build, "version_info.txt")
with open(version_res, "w", encoding="utf-8") as fh:
    fh.write(f"""# GENEROWANE przez CameraCapture.spec z src/version.py — nie edytowac recznie.
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={_v},
    prodvers={_v},
    mask=0x3F,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0),
  ),
  kids=[
    StringFileInfo([
      StringTable("040904B0", [
        StringStruct("ProductName", "Trixbrix - Camera Capture"),
        StringStruct("FileDescription", "Trixbrix - Camera Capture"),
        StringStruct("CompanyName", "TrixBrix.eu"),
        StringStruct("LegalCopyright", "Autor: Michał Krzysteczko"),
        StringStruct("FileVersion", "{APP_VERSION}"),
        StringStruct("ProductVersion", "{APP_VERSION}"),
        StringStruct("OriginalFilename", "Trixbrix - Camera Capture.exe"),
      ]),
    ]),
    VarFileInfo([VarStruct("Translation", [1045, 1200])]),
  ],
)
""")

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
# jest najpewniejsze; webview dla platform backends; pymatting czyta wlasna
# wersje z importlib.metadata przy imporcie ("No package metadata was found
# for pymatting" bez tego).
for pkg in ("rembg", "onnxruntime", "webview", "pymatting"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

# zaleznosci pymatting, tez odpytywane o wersje przez importlib.metadata
for pkg in ("numba", "llvmlite"):
    datas += copy_metadata(pkg)

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
    name="Trixbrix - Camera Capture",
    debug=False,
    strip=False,
    upx=False,
    console=False,
    icon="assets/icons/trixbrix.ico",
    version=version_res,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="CameraCapture",
)
