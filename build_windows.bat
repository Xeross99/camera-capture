@echo off
rem Buduje CameraCapture.exe (uruchamiac na Windowsie, z katalogu projektu).
setlocal

if not exist .venv-win (
    python -m venv .venv-win || goto :err
)
call .venv-win\Scripts\activate.bat || goto :err

python -m pip install --upgrade pip || goto :err
pip install -r requirements-windows.txt pyinstaller || goto :err

pyinstaller --noconfirm CameraCapture.spec || goto :err

echo.
echo Gotowe: dist\CameraCapture\"Trixbrix - Camera Capture.exe"
echo Skopiuj .env (na bazie .env.example) obok pliku .exe.
exit /b 0

:err
echo.
echo Build nie powiodl sie.
exit /b 1
