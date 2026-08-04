# Camera Capture na Windowsie

Aplikacja okienkowa (`gui.py`) działa na Windowsie. Jedyna realna różnica
względem macOS: **libgphoto2 nie istnieje na Windowsie**, więc aparatem
steruje **digiCamControl** przez jego lokalny webserver HTTP
(backend `src/camera_digicam.py`, wybierany automatycznie na Windowsie).
Cała reszta — live view, strzały, czyszczenie tła, galeria, upload do
Automatu — działa identycznie.

## Wymagania

1. **Windows 10/11** z [WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/)
   (Windows 11 ma go domyślnie; potrzebny dla okna pywebview).
2. **Python 3.11+** (przy uruchamianiu z kodu lub budowaniu .exe).
3. **[digiCamControl](https://digicamcontrol.com)** (darmowy):
   - zainstaluj i uruchom, podepnij Canona po USB (aparat w trybie M/Av/Tv/P),
   - włącz webserver: **Settings → Webserver → Enable** (port `5513`),
   - zrestartuj digiCamControl po włączeniu webservera,
   - sprawdź w przeglądarce: `http://127.0.0.1:5513` powinno odpowiadać.

   digiCamControl musi być **uruchomiony przez cały czas pracy aplikacji**
   (to on trzyma USB aparatu). Nasza aplikacja łączy się z nim po HTTP,
   sama otwiera live view i ściąga zdjęcia do katalogu sesji.

## Uruchomienie z kodu

```bat
python -m venv .venv-win
.venv-win\Scripts\activate
pip install -r requirements-windows.txt
python gui.py
```

`requirements-windows.txt` = `requirements.txt` bez `gphoto2` i `pyusb`
(niedostępne na tej platformie). Flagi te same co na macOS
(`--name`, `--no-upload`, `--port`, `--browser`, …).

## Konfiguracja (`.env`)

Jak na macOS (`.env.example`), plus opcjonalnie:

```
CAMERA_BACKEND=auto            # auto = na Windows digiCamControl; można wymusić: gphoto2 / digicamcontrol
DIGICAMCONTROL_URL=http://127.0.0.1:5513
```

## Budowa .exe

Na Windowsie, w katalogu projektu:

```bat
build_windows.bat
```

Wynik: `dist\CameraCapture\CameraCapture.exe` (folder onedir — do
przeniesienia w całości). Obok `.exe` połóż `.env`; tam też powstaje
katalog `photos\`. Przy pierwszym czyszczeniu tła rembg pobiera model
u2netp do `%USERPROFILE%\.u2net\` (jednorazowo potrzebny internet —
albo skopiuj tam gotowy `u2netp.onnx`).

## Ograniczenia backendu digiCamControl

- Sekcja **Aparat** (ISO/przysłona/czas/WB/AF) w sidebarze jest pusta —
  webserver digiCamControl nie eksponuje list wyboru; ustawienia zmieniaj
  w oknie digiCamControl albo na aparacie.
- Live view wymaga otwartego okna live view w digiCamControl — aplikacja
  otwiera je sama (`CMD=LiveViewWnd_Show`) przy łączeniu.
- Strzał: aplikacja ustawia `session.folder` digiCamControl na swój katalog
  roboczy i czeka aż zdjęcie się tam pojawi (timeout 60 s).
- TUI (`main.py` bez `--input`) pozostaje macOS/Linux-only (termios);
  na Windowsie działa `gui.py` oraz `main.py --input plik.jpg`.
