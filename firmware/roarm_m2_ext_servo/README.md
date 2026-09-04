# Firmware RoArm-M2-S z obsługą piątej osi (serwo pochylenia kamery)

Fabryczny firmware ramienia zna wyłącznie serwa o ID 11–15 (podstawa, dwa
barku, łokieć, chwytak/nadgarstek). Dodatkowe serwo ST3215 dopięte do
magistrali za osią 4 — w Camera Capture pochylenie kamery, oś 5 — nie ma
w nim żadnej komendy, którą dałoby się nim ruszyć ani je odczytać. Ten
katalog to **gotowy do wgrania sketch Arduino**: oficjalne źródła Waveshare
plus minimalna łatka dodająca cztery komendy JSON.

| Komenda | Co robi | Odpowiedź |
|---|---|---|
| `{"T":130,"id":16,"angle":30.0,"spd":1200,"acc":40}` | ruch na kąt (°, 0 = środek zakresu serwa, −180…180); `spd` w krokach/s, `acc` w krokach — **surowe** argumenty `WritePosEx` | — |
| `{"T":131,"id":16}` | odczyt serwa | `{"T":1131,"id":16,"ok":1,"angle":30.1,"pos":2389,"load":12,"volt":12.1,"temp":31}` albo `{"T":1131,"id":16,"ok":0}` |
| `{"T":132,"id":16,"cmd":0}` | moment jednego serwa (0 puść / 1 trzymaj); `id` 254 = wszystkie. Aplikacja puszcza serwa **tą** komendą, bo fabryczna `210 cmd:0` w tej wersji firmware najpierw parkuje ramię (`Move_to_location()`) i czeka na dojazd — trzymane ramię blokuje to na zawsze | — |
| `{"T":134,"raw":1,"new":16}` | zmiana ID — bezpieczna dla **każdego** `raw` (fabryczna `501` indeksuje tablicę feedbacku `raw − 11`, więc dla nowego serwa z ID 1 pisze poza nią) | `{"T":1134,"raw":1,"new":16,"ok":1}` |

Nic z fabrycznego zachowania nie jest zmienione: komendy 100–605 działają
jak dotąd, `210` (moment, broadcast) obejmuje także nowe serwo. Na OLED
ramienia druga linia pokazuje `version: 0.84 +ext` — po tym poznasz, że
wgrana jest ta wersja (aplikacja podpowiada to w logu, gdy oś 5 milczy).

## Co jest w katalogu

- `RoArm-M2_example/` — **cały sketch**, otwierasz `RoArm-M2_example.ino`
  i wgrywasz. To źródła z wiki Waveshare
  (`https://files.waveshare.com/wiki/RoArm-M2-S/RoArm-M2_example260630.zip`,
  wersja z 30.06.2026 — nowsza niż repo GitHub: kolejka komend na FreeRTOS,
  pomiar baterii INA219) z dopisanym `ext_servo.h` i małymi zmianami:
  `json_cmd.h` (numery komend), `uart_ctrl.h` (dispatch),
  `RoArm-M2_example.ino` (`#include` i napis wersji na OLED) oraz
  `esp_now_ctrl.h` (callback wysyłania ESP‑NOW ma w esp32 core ≥ 3.3 inną
  sygnaturę — poprawka jest pod `#if`, więc sketch kompiluje się i na
  starszym rdzeniu).
- `ext_servo.patch` — te same zmiany jako diff (`patch -p1`) na wypadek
  nakładania na własną kopię źródeł.

Upstream jest na licencji AGPL‑3.0 (Waveshare) — dotyczy też tego katalogu
jako pracy pochodnej.

## Wgranie krok po kroku (Arduino IDE)

Zgodnie z wiki „RoArm-M2-S Secondary Development Tool Usage":

1. **Arduino IDE 2.x** — `https://www.arduino.cc/en/software`.
2. **Płytki ESP32**: otwórz ustawienia IDE (macOS: menu **Arduino IDE →
   Settings…**, ⌘,; Windows/Linux: File → Preferences) i w polu
   „Additional boards manager URLs" na dole okna wklej
   `https://dl.espressif.com/dl/package_esp32_index.json`, potem
   Tools → Board → Boards Manager → zainstaluj **esp32 by Espressif Systems**.
   Sprawdzone z **3.3.11** (kompiluje się; wiki Waveshare wspomina 2.0.11,
   ta wersja też powinna działać dzięki `#if` w `esp_now_ctrl.h`).
3. **Biblioteki** — dwa źródła, bo paczka Waveshare jest niekompletna:
   - `https://files.waveshare.com/wiki/RoArm-M2-S/Libraries.zip` — rozpakuj
     **całe katalogi** do `~/Documents/Arduino/libraries/` (Windows:
     `Dokumenty\Arduino\libraries\`). Potrzebne stąd: `SCServo` (serwa —
     tylko stąd, nie ma go w Library Managerze), `Adafruit_SSD1306`,
     `Adafruit_GFX_Library`, `Adafruit_BusIO`, `Adafruit_NeoPixel`, `INA219_WE`.
     Katalog `ArduinoJson` z tej paczki **usuń** — to 6.19, a sketch używa
     typu `JsonDocument` z wersji 7.
   - Library Manager (ikona książek z lewej): zainstaluj **ArduinoJson**
     (7.x, Benoit Blanchon), **ESP Async WebServer** (ESP32Async) i
     **Async TCP** (ESP32Async) — IDE zaproponuje Async TCP jako zależność.
     Bez nich: `ESPAsyncWebServer.h: No such file` /
     `JsonDocument::JsonDocument() is protected`.
4. Skopiuj katalog `RoArm-M2_example/` z tego folderu w dowolne miejsce
   (np. `~/Documents/Arduino/RoArm-M2_example/`) i otwórz
   `RoArm-M2_example.ino`. Wszystkie pliki `.h` muszą leżeć obok.
5. **Zamknij Camera Capture** (trzyma port ramienia). Podłącz ramię kablem
   USB‑C — ten sam port, którym gada aplikacja (lewy port USB‑C płytki).
   Zasilanie 12 V może być podpięte.
6. Tools:
   - Board: **ESP32 Dev Module**
   - Port: nowy port po podpięciu (macOS `/dev/cu.wchusbserial…`, Windows `COMx`)
   - Partition Scheme: **Huge APP (3MB No OTA/1MB SPIFFS)**
   - PSRAM: **Enabled**
   - reszta domyślna (Upload Speed 921600, Flash 4MB).
7. **Upload** (strzałka w prawo). Z terminala to samo robi `arduino-cli`
   wbudowane w IDE (macOS: `/Applications/Arduino IDE.app/Contents/Resources/app/lib/backend/resources/arduino-cli`):
   ```
   arduino-cli compile -b esp32:esp32:esp32:PartitionScheme=huge_app,PSRAM=enabled RoArm-M2_example
   arduino-cli upload  -b esp32:esp32:esp32:PartitionScheme=huge_app,PSRAM=enabled -p /dev/cu.usbserial-10 RoArm-M2_example
   ``` Kompilacja trwa kilka minut za pierwszym
   razem. Jeśli wgrywanie stoi na `Connecting...`, przytrzymaj przycisk
   **BOOT** na płytce, aż ruszy.
8. Po restarcie OLED: druga linia `version: 0.84 +ext`. W logu startowym
   pojawia się `quad_psram: PSRAM ID read error` — płytka ramienia nie ma
   PSRAM, wpis jest nieszkodliwy (wiki każe włączyć PSRAM; z „Disabled"
   też działa).

**Sprawdzone 2026‑09‑03**: skompilowane i wgrane z `arduino-cli` (esp32 core
3.3.11, ArduinoJson 7.4.3, ESP Async WebServer 3.12.0, Async TCP 3.5.0,
reszta z `Libraries.zip`); po restarcie ramię odpowiada na 105 jak dotąd,
131 zwraca `ok:1` dla nowego serwa, 134 zmieniło mu ID 1 → 16, 130 rusza
osią 5. Płytka tego egzemplarza zgłasza się jako **CP2102N (Silicon Labs)**,
nie CH343 — port `/dev/cu.usbserial-*`. Każde otwarcie portu (DTR) resetuje
ESP32, a firmware przy starcie jedzie do pozycji początkowej. Firmware przy
   starcie wykonuje fabryczne `moveInit()` — ramię **jedzie do pozycji
   początkowej** zaraz po włączeniu, jak dotąd. Trzymaj aparat.


## Po wgraniu

1. Podłącz nowe serwo do magistrali (fabrycznie ma ID 1) i nadaj mu ID
   z `ROBOT_EXT_SERVO_ID` (domyślnie 16):
   `python3 tools/roarm_ext_servo_id.py` (`--probe` = tylko sprawdź, czy odpowiada).
2. Ustaw ujęcia od nowa — wpisy `ROBOT_JOINTS_*` z czterema kątami są
   pomijane, bo geometria końca ramienia jest inna: Ustawienia → „Robot —
   ujęcia" albo `tools/roarm_teach.py`. Ujęcie ma teraz pięć kątów.

## Jednostki — czemu surowe kroki

Komendy 121/122 przyjmują `spd`/`acc` w °/s i przeliczają je na kroki serwa,
a SDK Pythona przed wysłaniem skaluje je jeszcze raz (`×180/2048`); przy
`acc` kończy się to obcięciem do zera w typie `u8`. Dla nowego serwa
przyjmujemy dokładnie to, co idzie do `WritePosEx` — klient wysyła
`ROBOT_JOINT_SPEED`/`ROBOT_JOINT_ACC` bez żadnego przeliczania i ta sama
liczba znaczy to samo w `.env`, w kablu i w serwie.
