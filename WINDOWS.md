# Camera Capture na Windowsie

Aplikacja okienkowa (`gui.py`) działa na Windowsie. Jedyna realna różnica
względem macOS: **libgphoto2 nie istnieje na Windowsie**, więc aparatem steruje
jeden z dwóch backendów Windows:

1. **Canon EDSDK** (`src/camera_edsdk.py`) — **zalecany**: aplikacja rozmawia
   z aparatem bezpośrednio po USB przez oficjalne SDK Canona (ctypes),
   bez żadnego procesu obok. Wybierany automatycznie, gdy obok aplikacji
   leży `EDSDK.dll` (patrz niżej).
2. **digiCamControl** (`src/camera_digicam.py`) — fallback przez webserver
   HTTP dCC, gdy EDSDK.dll nie ma.

Cała reszta — live view, strzały, czyszczenie tła, upload do Automatu —
działa identycznie na obu.

## Canon EDSDK (zalecany backend)

1. Zarejestruj się (za darmo) w programie deweloperskim Canona i pobierz
   **EDSDK dla Windows**: [developers.canon-europe.com](https://developers.canon-europe.com/)
   (zatwierdzenie wniosku trwa zwykle 1–3 dni robocze).
2. Z paczki SDK weź wersję **x64** (64-bit) plików **`EDSDK.dll`** i
   **`EdsImage.dll`** i połóż je obok aplikacji (katalog projektu lub katalog
   z `.exe`; można też w podkatalogu `edsdk\` albo wskazać ścieżkę przez
   `EDSDK_DLL` w `.env`). DLL-ki nie są w repo — licencja Canona nie pozwala
   ich redystrybuować. Wersja 32-bit (np. z instalacji digiCamControl) **nie
   zadziała** z 64-bitowym Pythonem — aplikacja powie to wprost przy starcie.
3. Podepnij aparat po USB (tryb M/Av/Tv/P, nie odtwarzanie) i uruchom
   aplikację — backend wybierze się sam.

## Wymagania

1. **Windows 10/11** z [WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/)
   (Windows 11 ma go domyślnie; potrzebny dla okna pywebview).
2. **Python 3.11+** (przy uruchamianiu z kodu lub budowaniu .exe).
3. **[digiCamControl](https://digicamcontrol.com)** (darmowy) — **tylko gdy
   nie używasz backendu EDSDK**:
   - zainstaluj i uruchom, podepnij Canona po USB (aparat w trybie M/Av/Tv/P),
   - włącz webserver: **Settings → Webserver → Enable** (port `5513`),
   - zrestartuj digiCamControl po włączeniu webservera,
   - sprawdź w przeglądarce: `http://127.0.0.1:5513` powinno odpowiadać.

   Po tej jednorazowej konfiguracji **nie musisz go już uruchamiać ręcznie** —
   nasza aplikacja sama startuje CameraControl.exe (typowe ścieżki instalatora;
   inne miejsce wskaż przez `DIGICAMCONTROL_EXE` w `.env`), otwiera live view
   i minimalizuje jego okna. dCC działa w tle jako "sterownik" USB aparatu
   przez cały czas pracy aplikacji.

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
CAMERA_BACKEND=auto            # auto = edsdk gdy jest EDSDK.dll, inaczej digicamcontrol; można wymusić: edsdk / digicamcontrol / gphoto2
EDSDK_DLL=                     # ścieżka do EDSDK.dll lub jej katalogu (domyślnie szukana obok aplikacji)
DIGICAMCONTROL_URL=http://127.0.0.1:5513
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
`src/version.py`, commit, `git tag vX.Y.Z`, `git push --tags` — CI zbuduje
`.exe` i opublikuje release z paczką.

## Ograniczenia backendu EDSDK

- Ekspozycję (ISO/przysłona/czas/WB/AF) ustawia się na aparacie —
  `get_settings()` zwraca pustą listę jak w backendzie digiCamControl.
- Strzał używa AF (`PressShutterButton Completely`) — gdy AF nie złapie
  ostrości, dostaniesz czytelny błąd; przełącz obiektyw na MF albo popraw kadr.
- Zdjęcia lecą prosto do aplikacji (`SaveTo=Host`) — nic nie zapisuje się na
  karcie SD aparatu.

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
