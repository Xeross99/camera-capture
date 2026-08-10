# Camera Capture na Windowsie

Aplikacja okienkowa (`gui.py`) działa na Windowsie. Jedyna realna różnica
względem macOS: **libgphoto2 nie istnieje na Windowsie**, więc aparatem steruje
**Canon EDSDK** (`src/camera_edsdk.py`) — aplikacja rozmawia z aparatem
bezpośrednio po USB przez oficjalne SDK Canona (ctypes), bez żadnego procesu
obok. (Backend digiCamControl został usunięty w 1.1.0.)

Cała reszta — live view, strzały, czyszczenie tła, upload do Automatu —
działa identycznie jak na macOS.

## Canon EDSDK

1. Zarejestruj się (za darmo) w programie deweloperskim Canona i pobierz
   **EDSDK dla Windows**: [developers.canon-europe.com](https://developers.canon-europe.com/)
   (zatwierdzenie wniosku trwa zwykle 1–3 dni robocze).
2. Z paczki SDK weź wersję **x64** (64-bit) plików **`EDSDK.dll`** i
   **`EdsImage.dll`** i połóż je obok aplikacji (katalog projektu lub katalog
   z `.exe`; można też w podkatalogu `edsdk\` albo wskazać ścieżkę przez
   `EDSDK_DLL` w `.env`). DLL-ki nie są w repo — licencja Canona nie pozwala
   ich redystrybuować. Wersja 32-bit **nie zadziała** z 64-bitowym Pythonem —
   aplikacja powie to wprost przy starcie.
3. Podepnij aparat po USB (tryb M/Av/Tv/P, nie odtwarzanie) i uruchom
   aplikację. Pierwsza linia logu mówi, skąd wzięła się DLL — albo że jej
   brakuje.

**Nowy komputer = te same dwa kroki ręczne**: skopiuj obok `.exe` parę
`EDSDK.dll` + `EdsImage.dll` oraz `.env` (token Automatu).

## Wymagania

1. **Windows 10/11** z [WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/)
   (Windows 11 ma go domyślnie; potrzebny dla okna pywebview).
2. **Python 3.11+** (przy uruchamianiu z kodu lub budowaniu .exe).

## Uruchomienie z kodu

```bat
python -m venv .venv-win
.venv-win\Scripts\activate
pip install -r requirements-windows.txt
python gui.py
```

`requirements-windows.txt` = `requirements.txt` bez `gphoto2` i `pyusb`
(niedostępne na tej platformie), z `onnxruntime-directml` zamiast
`onnxruntime` (inferencja rembg na GPU). Flagi te same co na macOS
(`--name`, `--no-upload`, `--port`, `--browser`, …).

## Konfiguracja (`.env`)

Jak na macOS (`.env.example`), plus opcjonalnie:

```
CAMERA_BACKEND=auto            # auto = edsdk na Windowsie; można wymusić: edsdk / gphoto2
EDSDK_DLL=                     # ścieżka do EDSDK.dll lub jej katalogu (domyślnie szukana obok aplikacji)
CLEAN_BG_GPU=true              # false = rembg na CPU (bez kompilacji shaderów DirectML przy starcie)
```

## Budowa .exe

Na Windowsie, w katalogu projektu:

```bat
build_windows.bat
```

Wynik: `dist\CameraCapture\Trixbrix - Camera Capture.exe` (folder onedir — do
przeniesienia w całości). Obok `.exe` połóż `.env`; tam też powstaje
katalog `photos\`. Przy pierwszym czyszczeniu tła rembg pobiera model
u2netp do `%USERPROFILE%\.u2net\` (jednorazowo potrzebny internet —
albo skopiuj tam gotowy `u2netp.onnx`).

Numer wersji bierze się z `src/version.py` — `CameraCapture.spec` generuje z
niego zasób wersji `.exe` (`build\version_info.txt`), więc nie ma czego
edytować ręcznie.

## Aktualizacje

Aplikacja przy starcie sprawdza GitHub Releases i gdy jest nowsze wydanie,
pokazuje nad zakładkami baner **„Dostępna aktualizacja X.Y.Z"** z przyciskiem
**„Zaktualizuj i uruchom ponownie"**. Klik = pobranie paczki, zamknięcie
aplikacji, podmiana plików i automatyczny restart (kilkanaście–kilkadziesiąt
sekund, zależnie od łącza). „Później" chowa baner do następnego uruchomienia.

Co przeżywa aktualizację: `.env`, `photos\`, ręcznie dołożone `EDSDK.dll` —
podmieniany jest tylko `.exe` i `_internal\`. Ręczna alternatywa: pobrać
`CameraCapture-windows-vX.Y.Z.zip` z zakładki Releases i rozpakować go
na istniejący katalog aplikacji (z zamkniętą aplikacją).

Nowa wersja jest niepodpisana, więc Windows SmartScreen może przy pierwszym
uruchomieniu pokazać ostrzeżenie („Więcej informacji" → „Uruchom mimo to").

Wydanie nowej wersji (dla dewelopera): podbij `APP_VERSION` w
`src/version.py`, commit, push na `main` — CI zbuduje `.exe` i opublikuje
release z paczką.

## Ograniczenia backendu EDSDK

- Ekspozycję (ISO/przysłona/czas/WB/AF) ustawia się na aparacie; z aplikacji
  zmienisz tylko kompensację ekspozycji.
- Strzał używa AF (`PressShutterButton Completely`) — gdy AF nie złapie
  ostrości, dostaniesz czytelny błąd; przełącz obiektyw na MF albo popraw kadr.
- Zdjęcia lecą prosto do aplikacji (`SaveTo=Host`); gdy aparat mimo to nie
  zgłosi pliku, aplikacja po 8 s sama szuka najnowszego zdjęcia na karcie.
- TUI (`main.py` bez `--input`) pozostaje macOS/Linux-only (termios);
  na Windowsie działa `gui.py` oraz `main.py --input plik.jpg`.
