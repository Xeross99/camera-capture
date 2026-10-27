<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/readme/hero_dark.svg">
    <img src="assets/readme/hero.svg" width="540" alt="Camera Capture: Enter na laptopie, aparat robi zdjęcie, laptop wybiela tło">
  </picture>
</p>

<h1 align="center">Camera Capture</h1>

Aplikacja do zdjęć produktowych. Aparat stoi na statywie i jest podłączony przez USB, a operator
naciska ENTER. Zdjęcie dostaje białe tło, produkt ląduje na środku kadru, w rogu pojawia się logo, a gotowy
JPEG 3000 × 3000 trafia do sesji w API.

<table>
  <tr><th width="50%">Prosto z aparatu</th><th width="50%">Po obróbce</th></tr>
  <tr>
    <td><img src="assets/readme/before-1.jpg" width="100%" alt="Zdjęcie 1 prosto z aparatu"></td>
    <td><img src="assets/readme/after-1.jpg" width="100%" alt="Zdjęcie 1 po obróbce"></td>
  </tr>
  <tr>
    <td><img src="assets/readme/before-2.jpg" width="100%" alt="Zdjęcie 2 prosto z aparatu"></td>
    <td><img src="assets/readme/after-2.jpg" width="100%" alt="Zdjęcie 2 po obróbce"></td>
  </tr>
  <tr>
    <td><img src="assets/readme/before-3.jpg" width="100%" alt="Zdjęcie 3 prosto z aparatu"></td>
    <td><img src="assets/readme/after-3.jpg" width="100%" alt="Zdjęcie 3 po obróbce"></td>
  </tr>
</table>

Jedno zdjęcie od migawki do pliku na dysku trwa kilka sekund. Między strzałami wystarczy obrócić produkt i
nacisnąć ENTER jeszcze raz.

<img src="assets/readme/session.jpg" width="100%" alt="Sesja: podgląd z aparatu z siatką kadrowania, ustawienia obróbki i pasek zdjęć">
<sub>Zrzut zrobiony bez podłączonego aparatu: w miejscu podglądu na żywo jest jedno ze zdjęć sesji.</sub>

## Jak to działa

1. **Zdjęcie.** Aplikacja sama wyzwala migawkę i pobiera plik po USB przez Canon EDSDK, na Windowsie i na
   macOS. Nie ma programu producenta pośrodku ani obserwowanego folderu.
2. **Obróbka**, każdy krok do włączenia w panelu Postprocessing:
   - **Wyrównanie tła do bieli:** tło dociągane do czystej bieli, cienie pod produktem wygaszone.
   - **Przybliżanie i centrowanie:** kadr dociąga się do produktu i stawia go na środku, zamiast tam, gdzie
     wypadł na stole. Zdjęcie pod kątem zostaje pod kątem: niczego nie prostujemy.
   - **Logo:** TRIXBRIX.eu albo TRIXBRIX.eu KIDS, w wybranym rogu kadru.
3. **Zapis i wysyłka.** Gotowy plik leży w `photos/<sesja>/`, obok niego surowy oryginał z aparatu, a
   przetworzone zdjęcie idzie do sesji w API. Surowy oryginał zostaje tylko na dysku.

## Aplikacja

### Lista sesji

Ekran startowy pokazuje wszystkie sesje z API, pogrupowane po dniach, z okładką, dopasowanym produktem
i liczbą zdjęć. U góry zakłada się nową sesję: nazwa produktu i ENTER. Listę da się przeszukać, zawęzić do
dnia, tygodnia albo miesiąca i do liczby zdjęć, a strzałkami chodzi się po kafelkach.

<img src="assets/readme/sessions.jpg" width="100%" alt="Lista sesji pogrupowana po dniach">

### Sesja

Podgląd na żywo z aparatu z siatką kadrowania jak w aparacie (3×3 albo 6×4), znaczkiem, czy tło jest
wystarczająco jasne, i kompensacją ekspozycji. Po prawej kroki obróbki i wybór logo z rogiem kadru, na dole
pasek zdjęć sesji (zielona kropka: zdjęcie jest już w API, pomarańczowa: czeka na wysyłkę). Zdjęcia
zrobione na innym komputerze dociągają się z API same.

### Podgląd i edycja zdjęcia

SPACJA otwiera zdjęcie na całe okno, strzałki przechodzą między zdjęciami, BACKSPACE usuwa (do kosza na
dysku i z API). „Edytuj” (klawisz E) pozwala zdjąć, dodać albo przestawić logo na gotowym zdjęciu.
Podgląd obok pokazuje dokładnie to, co zostanie zapisane, a zmiana podmienia też to samo zdjęcie w API.

<img src="assets/readme/review.jpg" width="100%" alt="Podgląd zdjęcia na całe okno">

<img src="assets/readme/edit.jpg" width="100%" alt="Edycja logo na gotowym zdjęciu">

Edycja działa na zdjęciach, które mają wersję bez logo: zapisuje ją każde zdjęcie zrobione tą aplikacją.
Starsze robi się z oryginału z aparatu (`/raw`), jeśli został zachowany.

### Ustawienia

Aktualizacje z GitHub Releases, połączenie z API (wraz z listą endpointów), pliki, podgląd i obróbka oraz skróty klawiszowe.
Motyw jasny albo ciemny przełącza się ikoną w prawym górnym rogu.

<img src="assets/readme/settings.jpg" width="100%" alt="Ustawienia: aktualizacje, API z endpointami, pliki">

<img src="assets/readme/session-dark.jpg" width="100%" alt="Sesja w ciemnym motywie, aparat rozłączony">

<sub>Ciemny motyw. Gdy aparat jest odłączony, w ramce podglądu animowana wtyczka próbuje się wpiąć, a aplikacja co kilka sekund łączy się ponownie.</sub>

### Klawiatura

| Klawisz | Co robi |
|---|---|
| **ENTER** | robi zdjęcie (na liście sesji: otwiera zaznaczoną) |
| **SPACJA** | otwiera podgląd zdjęć na całe okno |
| **← →** | przechodzi między zdjęciami |
| **E** | edytuje logo na oglądanym zdjęciu |
| **BACKSPACE** | usuwa zdjęcie: trafia do kosza na dysku i znika z API |
| **ESC** | zamyka podgląd albo wychodzi z sesji |
| **P** | włącza i wyłącza podgląd z aparatu |
| **⌘F / Ctrl+F** | szuka sesji |
| **⌘N / Ctrl+N** | zakłada nową sesję |

## API

Aplikacja rozmawia z serwerem przez `/api/photo_studio` (adres i token w Ustawieniach albo w `.env`: `AUTOMAT_URL`, `AUTOMAT_TOKEN`):

| Metoda | Endpoint | Do czego |
|---|---|---|
| `GET` | `/sessions` | lista sesji na ekranie startowym |
| `POST` | `/sessions` | nowa sesja (albo istniejąca o tej nazwie) |
| `GET` | `/sessions/:id` | zdjęcia sesji do pobrania przy wejściu |
| `GET` | `/sessions/:id/photos/:photo_id/file` | pobranie zdjęcia na dysk |
| `POST` | `/sessions/:id/photos` | zapowiedź zdjęcia zaraz po migawce, potem plik |
| `PUT` | `/sessions/:id/photos/:photo_id` | gotowy JPEG do zapowiedzianego zdjęcia |
| `DELETE` | `/sessions/:id/photos/:photo_id` | usunięcie zdjęcia (BACKSPACE) |

## Instalacja na Windowsie

1. Pobierz `CameraCapture-windows-vX.Y.Z.zip` z ostatniego wydania i rozpakuj w dowolnym katalogu.
2. Dołóż obok `.exe` pliki `EDSDK.dll` i `EdsImage.dll` (x64) z Canon EDSDK. Nie ma ich w repozytorium,
   bo nie pozwala na to licencja Canona.
3. Skopiuj `.env.example` jako `.env` i wpisz token API (`AUTOMAT_TOKEN`).

Szczegóły, w tym ustawienia aparatu i rozwiązywanie problemów: [WINDOWS.md](WINDOWS.md).

## Instalacja na macOS

1. Pobierz `CameraCapture-macos-vX.Y.Z.zip` z ostatniego wydania (Mac z procesorem Apple, M1 i nowsze)
   i rozpakuj. Powstanie katalog `Camera Capture` z aplikacją `Camera Capture.app`.
2. Dołóż do tego katalogu, obok `Camera Capture.app`, `EDSDK.framework` z Canon EDSDK dla macOS.
3. Skopiuj `.env.example` jako `.env` i wpisz token API (`AUTOMAT_TOKEN`). Zdjęcia trafią do `photos/`
   w tym samym katalogu.
4. Aplikacja nie jest podpisana przez Apple, więc przy pierwszym uruchomieniu kliknij ją prawym przyciskiem
   i wybierz **Otwórz** albo zdejmij kwarantannę:
   `xattr -dr com.apple.quarantine "Camera Capture.app" EDSDK.framework`.

Na macOS aplikacja tylko informuje o nowej wersji. Nową paczkę rozpakowuje się ręcznie w miejsce starej `Camera Capture.app`.

## Aktualizacje

Aplikacja sama sprawdza przy starcie, czy jest nowsza wersja, a w Ustawieniach można sprawdzić to ręcznie.
Jeden przycisk pobiera paczkę, podmienia pliki i uruchamia aplikację ponownie. `.env`, `photos/` i pliki
EDSDK zostają nietknięte.

Nowa wersja wychodzi sama: wystarczy podbić `APP_VERSION` w `src/version.py` i wypchnąć to na `main`.
GitHub Actions uruchomi testy, zbuduje `.exe` i opublikuje wydanie w tym repozytorium
(publicznym), skąd aplikacja sama pobiera aktualizacje.

## Uruchomienie z kodu (macOS)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 gui.py              # okno aplikacji
python3 gui.py --browser    # to samo w przeglądarce
```

Na macOS aparat działa wyłącznie przez Canon EDSDK: `EDSDK.framework` (z paczki Canona dla macOS, poza repozytorium) musi leżeć w katalogu aplikacji. Framework pobrany przez przeglądarkę trzeba zwolnić z kwarantanny: `xattr -dr com.apple.quarantine EDSDK.framework`. Kliknięcie w podgląd ustawia ostrość w tym miejscu.

## Testy

```bash
pip install -r requirements-dev.txt
python -m playwright install chromium
python -m pytest -q
```

Testy działają bez aparatu (atrapa w `tests/conftest.py`) i bez sieci. CI uruchamia je na Windowsie przed każdym buildem — gdy nie przejdą, nowa wersja się nie buduje.

## Dokumentacja

Wszystko techniczne, czyli jak działa obróbka, kolejka zdjęć, połączenie z aparatem, aktualizator i
konfiguracja w `.env`, jest opisane w [CLAUDE.md](CLAUDE.md).

## Autor

<a href="https://github.com/Xeross99"><img src="assets/readme/author.png" width="48" alt="" align="left"></a>
**Michał Krzysteczko**<br>
[@Xeross99](https://github.com/Xeross99)
<br clear="left">

## Licencja

MIT, szczegóły w [LICENSE](LICENSE).
