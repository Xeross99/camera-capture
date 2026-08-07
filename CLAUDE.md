# Camera Capture

Aparat: Canon EOS M50 Mark II przez USB (gphoto2 / python-gphoto2).

Pipeline:
1. **Capture** — gphoto2, format ustawiany przez `CAMERA_IMAGE_FORMAT` (obecnie `"L"` = Large Fine JPEG, ~6000×4000).
2. **Clean BG** (zawsze ON, brak toggle w UI — celowo, bo i tak zostawiamy raw obok jako kopię) — wszystko liczone na pełnej rozdzielczości z aparatu, dopiero finalny kadr resize'owany do `OUTPUT_SIZE × OUTPUT_SIZE`:
   - rembg `u2netp` → maska → `_lift_internal_shadows` → auto-center: kwadratowy crop wokół bboxa produktu z `PRODUCT_MARGIN` → resize do canvas → `_build_shadow_layer` na canvas → kompozyt na białym tle.
3. **Overlay logo** w prawym dolnym rogu.
4. **Zapis** dwóch plików:
   - `photos/<nazwa>/photo_<timestamp>_raw.jpg` — kopia surowa z aparatu (przed obróbką).
   - `photos/<nazwa>/photo_<timestamp>.jpg` — końcowy 3000×3000.
5. **Upload do Automatu** (w GUI zawsze ON gdy `AUTOMAT_TOKEN` ustawiony; w TUI/CLI toggle `u` / `--no-upload`) — wysyłany jest **przetworzony** 3000×3000 JPEG (nie raw). Po `capture` od razu leci `announce_photo(filename)` (placeholder w UI Automatu, kafelek ze spinnerem), potem lokalny processing, potem `upload_processed(out, photo_id=announced_id)` PUT-uje plik do tego samego rekordu. Raw nie idzie po sieci, tylko leży lokalnie.

Dlaczego ta kolejność: gdy crop 1:1 idzie pierwszy (centrowany na sensorze, bez znajomości pozycji produktu), produkt odsunięty od środka traci krawędź — auto-center umie tylko skalować w obrębie już-przyciętego kadru. Robiąc rembg + auto-center na full-res i dopiero wtedy 1:1 crop wokół bboxa, mamy dostęp do całego sensora i tylko jedno przeskalowanie.

Świadomie nie prostujemy zdjęcia: produktówki często strzelane są pod kątem 3/4 i auto-level by je rotował tak, żeby krawędź podstawy była pozioma — psując zamierzoną perspektywę. Z tego samego powodu nie honorujemy EXIF Orientation (`exif_transpose` nie jest wołany); aparat ma wyłączoną autorotację (`_disable_autorotation`), więc tag i tak nie powinien się pojawić, ale jakby się pojawił — i tak go ignorujemy.

## Uruchomienie

```bash
source .venv/bin/activate
python3 main.py
```

`activate` musi być **sourcowany** (`source` lub `.`) — `./venv/bin/activate` zwraca permission denied.

Z istniejącym plikiem (bez aparatu):
```bash
python3 main.py --input plik.jpg --name foo
python3 main.py --input plik.jpg --name foo --no-upload
```

Logo (działa też w trybie interaktywnym):
```bash
python3 main.py --no-logo                      # bez logo
python3 main.py --logo-position bottom-left    # bottom-right (default) / bottom-left / top-right / top-left
```

Zoom/centrowanie (działa też w trybie interaktywnym — klawisze `z`/`c`):
```bash
python3 main.py --no-auto-zoom      # bez przybliżania (naturalna skala z kadru)
python3 main.py --no-auto-center    # bez centrowania (produkt zostaje w pozycji z kadru)
```

Wypisanie dostępnych formatów obrazu w aparacie:
```bash
python3 main.py --list-formats
```

## Windows

Aplikacja okienkowa (`gui.py`) działa też na Windowsie — pełna instrukcja w `WINDOWS.md`. libgphoto2 nie istnieje na tej platformie, więc aparatem sterują dwa backendy do wyboru przez `make_camera_session()` / `CAMERA_BACKEND=auto`: **Canon EDSDK** (`src/camera_edsdk.py`, preferowany — bezpośrednio po USB przez ctypes, bez procesu obok; wybierany gdy obok aplikacji leży `EDSDK.dll` x64 z programu deweloperskiego Canona — DLL-ek nie commitujemy, licencja) oraz fallback **digiCamControl** przez jego webserver HTTP (backend `src/camera_digicam.py`; dCC jest auto-startowany i minimalizowany przez backend — operator go nie dotyka, wymagana tylko jednorazowa instalacja z włączonym webserverem). Instalacja: `pip install -r requirements-windows.txt` (bez gphoto2/pyusb). Build `.exe`: `build_windows.bat` → PyInstaller z `CameraCapture.spec` (onedir, `dist\CameraCapture\Trixbrix - Camera Capture.exe`; ikona `assets/icons/trixbrix.ico`, metadane [autor: Michał Krzysteczko] generowane przez spec z `src/version.py` do `build/version_info.txt` — plik nie jest już trzymany w repo, żeby wersja miała jedno źródło prawdy; `.env` i `photos/` żyją obok `.exe`). CI: `.github/workflows/build-windows.yml` buduje artefakt `CameraCapture-windows` przy każdym pushu na main, a przy tagu `vX.Y.Z` dodatkowo publikuje GitHub Release z paczką `CameraCapture-windows-vX.Y.Z.zip` (patrz sekcja „Aktualizacje"). TUI pozostaje macOS/Linux-only (termios); na Windowsie działa `gui.py` i `main.py --input`.

## Aplikacja okienkowa z live preview (`gui.py`, `src/webui.py`, `src/webui_static/`)

UI odwzorowane 1:1 z projektu Claude Design („Camera Capture.dc.html", projekt `a9cf1855-e687-4e6c-9b44-9d9066305f0a`). Natywne okno przez **pywebview** (WKWebView) z **systemowym paskiem tytułu** — prawdziwe traffic lights macOS (rysowane atrapy z mockupu wyleciały: nie działały w fullscreen). Start 1440×900, min 1080×700, layout flexowy wypełnia okno przy każdym rozmiarze (bez skalowania transformem). Status „● Aparat połączony · N fps" siedzi w pasku zakładek. Nazwa „Python" w menu bar zniknie dopiero po spakowaniu do .app (PyInstaller — niezrobione). Backend to lokalny serwer HTTP (stdlib, tylko 127.0.0.1, **losowy efemeryczny port + per-launch token** — request bez tokenu dostaje 403, więc UI nie jest osiągalne przeglądarką „z boku"; token idzie w URL przy pierwszym ładowaniu, potem HttpOnly cookie) serwujący `index.html` + statyki (`/static/style.css`, `/static/app.js` — whitelist rozszerzeń, bez podkatalogów), MJPEG stream live view (`/stream`), `/api/state` (poll 500 ms) i `/api/action` (dispatcher). `--browser` otwiera to samo w przeglądarce (fallback też gdy brak pywebview), `--port` przypina stały port.

```bash
python3 gui.py
python3 gui.py --name foo --no-upload --port 9000    # flagi jak main.py + --port/--browser
```

**Ekran startowy**: dopóki sesja nie jest ustawiona, zakładka Sesja pokazuje listę sesji photo_studio z Automatu (`GET /api/photo_studio/sessions` → `[{id, name, product, created_at, photos_count}]`, `AutomatUploader.list_sessions()`) — **układ odwzorowuje Photo Studio w Automacie**: lewa oś dni (`dayRail()`, klik przewija do grupy) + kafelki z okładką pogrupowane nagłówkami dat (`groupByDay()`, polska odmiana przez `plForm/plSessions/plPhotos`). Na kafelku: okładka, nazwa, nazwa produktu albo „Sesja luźna", liczba zdjęć i godzina. Do tego przycisk Odśwież i pole „Utwórz i otwórz".

**Okładki sesji** (`_job_session_covers`, `photos/.covers/<id>.jpg`): lista z Automatu nie zawiera miniatur (`serialize_session` bez `with_photos` to same liczniki), więc robimy je u siebie z najnowszego zdjęcia sesji — **najpierw z lokalnego folderu** (`_local_cover_source()`, zero sieci; typowo tak powstaje większość), a dopiero dla sesji bez plików na dysku `GET /sessions/:id` + pobranie jednego zdjęcia (`download_photo(..., session_id=sid)` — uploader okładek nie ma otwartej sesji, więc id musi iść jawnie). Miniatura 420 px zostaje na stałe (~13 KB/sesja), więc kolejne wejścia nic nie ściągają. Job leci po `list_sessions` i **tylko przy zamkniętej sesji** — ekran startowy nie jest wtedy widoczny, a worker nie może opóźniać obróbki zdjęć. Błąd okładki nie przerywa listy, ale pierwszy jest logowany (cicha literówka w wywołaniu API zostawałaby w kodzie na zawsze). W UI kafelek bez okładki pokazuje skeleton i wypełnia się sam przy kolejnym poll-u; `#start-scroll` zachowuje pozycję przewijania między rebuildami, bo każda dolatująca okładka to rebuild ekranu. Klik w sesję = `set_session` z jej nazwą **i `session_id`** — klient podłącza się do istniejącej sesji Automatu po id (`AutomatUploader.attach_session()`, bez POST-a; Rails deduplikuje tylko per produkt+dzień, więc bez id klik w starą sesję zakładałby nową na dziś). Wpisanie w „Utwórz i otwórz" nazwy, która już istnieje na liście (case-insensitive, po sanityzacji), pokazuje dialog „Podłącz do istniejącej / Utwórz nową / Anuluj" (`S.pendingNew` w `app.js`; „Utwórz nową" = `set_session` bez id → POST, na inny dzień robi nową sesję, tego samego dnia Rails i tak zwróci istniejącą). `attach_to` w `WebUI` pamięta wybrane id — toggle uploadu OFF→ON re-attachuje zamiast otwierać nową; przy 404 (sesja zniknęła z Rails) `_reopen()` otwiera nową po nazwie jak dotąd. W sidebarze breadcrumb 🏠 `/ <nazwa sesji>` — domek to `clear_session` (czyści też `attach_to`) i wraca do tego widoku (osobny link „‹ lista sesji" usunięty, robił dokładnie to samo).

**Sync zdjęć z Automatem (dwustronny)**: po każdym udanym `open_session` job wrzuca do kolejki `sync_session` (`_job_sync_session` w `webui.py`) — pobiera `GET /api/photo_studio/sessions/:id` i zrównuje filmstrip z sesją po drugiej stronie. **Automat jest źródłem prawdy**: czego nie ma lokalnie → ściągamy (`AutomatUploader.session_photos()` + `download_photo()` → `GET .../photos/:id/file`), czego nie ma już zdalnie → kasujemy lokalnie (`_prune_local()`).

Pobieranie: wejście w starą sesję na maszynie, która jej nie strzelała (inny komputer, wyczyszczone `photos/`), pokazuje jej zdjęcia w filmstripie zamiast pustki. Zapisywane są też `review["automat"]` (BACKSPACE kasuje wtedy zdjęcie i w Automacie) oraz `review["uploaded"]`. Raw nigdy nie szedł po sieci, więc wraca sam finalny JPEG — `raw/` nie jest odtwarzane. Nazwa pliku bierze się ze zdalnego `filename` (sam basename — zdalna nazwa nie może uciec z katalogu sesji, `_remote_filename()`), a przy jego braku z `photo_<id>.jpg`. Zdjęcia w statusie innym niż `processed` (placeholdery po announce) nie są pobierane.

Kasowanie (`_prune_local`) — operator odsiał zdjęcia w UI Automatu i filmstrip ma to odzwierciedlić. Pliki (finał + raw) idą do **kosza**, nie na śmietnik — patrz sekcja niżej. Dwa świadome zabezpieczenia, bo prune leci **automatycznie** przy wejściu w sesję:
- **Pusta lista zdalna = nie ruszamy nic.** Rails deduplikuje sesje per produkt + dzień, więc otwarcie wczorajszej sesji po samej nazwie zakłada nową, pustą — bez tego guardu prune wyczyściłby cały lokalny folder.
- Do prune liczą się **wszystkie statusy** zdjęć zdalnych (nie tylko `processed`) — placeholder po announce, w locie, też „istnieje" po drugiej stronie.

Gdy `GET /sessions/:id` zwróci **404** (całej sesji nie ma już w Automacie), `_job_sync_session` nie loguje błędu, tylko woła `_trash_session()`: lokalny folder ląduje w koszu, `name`/`attach_to` są czyszczone i UI wraca na ekran startowy — bez tego operator siedziałby w sesji, do której nic już nie doleci. 404 jest rozpoznawalny, bo `AutomatUploader._err()` rzuca dla niego `AutomatNotFound` (podklasa `RuntimeError`, więc stare `except Exception` łapią jak dotąd). **Nie** wnioskujemy o skasowanej sesji z listy `list_sessions()` — Rails oddaje tam tylko 20 najnowszych, więc wszystko starsze wyglądałoby na usunięte.

## Kosz (`photos/.trash`, retencja `TRASH_RETENTION_DAYS`)

Nic, co aplikacja usuwa lokalnie, nie znika od razu — pliki lądują w `photos/.trash/<data>-<godzina>_<sesja>/` i dopiero `_job_purge_trash` (raz przy starcie, `_purge_trash()`) kasuje wpisy starsze niż `TRASH_RETENTION_DAYS` (domyślnie 30). Odzyskanie = przeniesienie plików z powrotem do `photos/<sesja>/` (raw wraca obok finału, nie do `raw/` — kosz jest płaski).

Przez kosz idą obie ścieżki kasowania, wspólną metodą `_discard_files()`: **prune** przy synchronizacji i **świadome kasowanie** (BACKSPACE / „Odrzuć ostatnie" → `_job_delete`), a przez `_trash_session()` także cały folder sesji skasowanej w Automacie. Zabierany jest finalny JPEG **i jego raw**; miniatura z `.thumbs/` leci od razu na stałe (to cache, odtworzy się sama).

Data wieku wpisu siedzi w **nazwie** katalogu, nie w mtime — mtime zmienia się przy kopiowaniu/synchronizacji `photos/` i kosz czyściłby się losowo. `TRASH_RETENTION_DAYS=0` wyłącza kosz (kasowanie natychmiastowe, zachowanie sprzed tej zmiany).

Po stronie **Automatu kasowanie zostaje natychmiastowe** (`DELETE /photos/:photo_id` przy BACKSPACE) — soft delete rekordów to zmiana w trix-automat, świadomie nierobiona tutaj. TUI nie ma kasowania ani synchronizacji zdjęć, więc kosza nie dotyka. Sync jest idempotentny — istniejące pliki nie są nadpisywane, więc kolejne otwarcia sesji nic nie ściągają. W UI pobieranie widać jako **kafelki-skeletony w filmstripie** (`WebUI.syncing` → `state["downloading"]` → klasa `.skeleton` w `style.css`, shimmer na tle i na pasku podpisu): tyle skeletonów, ile plików zostało do pobrania, każdy znika gdy jego plik wyląduje na dysku i zastąpi go prawdziwa miniatura. Skeleton znika też po **nieudanym** pobraniu (`finally`) — inaczej wisiałby do końca sesji. `st.downloading` jest w `sesjaKey`, czyli obsługiwane rebuildem jak `st.processing`, nie patchem w `updateVolatile()`. **TUI tego nie robi świadomie**: nie ma filmstripa ani przeglądania, więc ściąganie megabajtów przy `attach_session` byłoby kosztem bez efektu (`session_photos`/`download_photo` siedzą w `automat_uploader.py`, gdyby kiedyś było potrzebne).

Dwie zakładki (Galeria usunięta ŚWIADOMIE — zdjęcia żyją tylko w Sesji, upload jest zawsze automatyczny):
- **Sesja** — live view z siatką 3×3 i ramką kadru 1:1 (badge'y klikane), pulsujący badge LIVE (prawy górny róg, tylko gdy preview ON + aparat połączony), badge HISTOGRAM OK/! + „tło A–B" (percentyle 10/90 z pasków brzegowych klatki, OK gdy 230–254); filmstrip zdjęć sesji; zwijany log; sidebar: nazwa sesji + „‹ lista sesji", sekcja **Postprocessing** (logo + pozycja, zoom, centrowanie, „Wyrównanie tła do bieli" = clean_bg); przyciski „Zrób zdjęcie [ENTER]", „Podgląd [P]", „Odrzuć ostatnie [X]".

  Klawisze na Sesji: **ENTER = strzał** (z animacją białego flasha na podglądzie), **SPACJA = tryb przeglądania** — overlay ze zdjęciami sesji na miejscu live view (`←`/`→` zmiana z subtelnym nudge 6 px / .22 s, **BACKSPACE = usuwa oglądane zdjęcie** [final+raw, bez potwierdzenia! — lokalnie do kosza (`photos/.trash`, odzyskiwalne przez `TRASH_RETENTION_DAYS` dni), w Automacie od razu przez `DELETE /photos/:id`, id z `review["automat"]`] z animacją wypadnięcia, **ESC lub SPACJA wraca do live**), klik w miniaturę filmstripa otwiera ją w overlayu. Klawisze `A`/`X` (akceptuj/odrzuć do `.review.json`) nadal działają, ale są UKRYTE — napisy „A akceptuj"/„X odrzuć" i licznik „odrzuconych" w pasku zakładek usunięte ŚWIADOMIE z UI. Wszystkie obsługiwane klawisze mają `preventDefault` (bez tego WKWebView puszcza event w responder chain i macOS beepi).

  Anti-flicker (ważne przy zmianach w `app.js`): render jest keyowany — pełny rebuild ekranu tylko przy zmianie struktury (`sesjaKey`: shots/toggles/selShot/reviewMode itd., BEZ liczników sesji, busy, logu i statystyk tła); zmienne drobiazgi (fps, HISTOGRAM, „tło A–B", tekst przycisku migawki, log) są patchowane po `id` w `updateVolatile()`. Rebuild niszczy `<img>` streamu MJPEG i overlay podglądu — każdy nowy rebuild-trigger w kluczu = miganie. Overlay podglądu (`#review-wrap`) jest ZAWSZE nieprzezroczysty (animacje tylko na wewnętrznym `<img>`, na ciemnym tle), nawigacja/kasowanie podmienia `src` w miejscu (stare zdjęcie wisi aż nowe się zdekoduje) + preload sąsiadów — pełny rebuild przy nav powodował prześwity live view między zdjęciami.
- **Ustawienia** — katalogi/logo/wzór nazwy (`photo_{data}_{godzina}.jpg`), „Zachowaj oryginały w podkatalogu /raw" (OFF = raw kasowany!), Automat (URL/token — wpisanie zapisuje je od razu do `PROJECT_DIR/.env` przez `_persist_env()`, więc przeżywają restart; wpisanie tokena włącza też upload i otwiera sesję; test połączenia), FPS podglądu (throttle pętli preview), **Aktualizacje** (wersja aplikacji, „Sprawdź aktualizacje", przycisk instalacji — patrz sekcja „Aktualizacje").

  Upload do Automatu jest ZAWSZE ON gdy jest token — toggle „Upload", „Wysyłaj automatycznie po akceptacji", batch „Wyślij do Automatu (n)" i „Przetwórz ponownie" usunięte ŚWIADOMIE razem z Galerią (CLI `--no-upload` zostało jako narzędzie deweloperskie). Sekcje sterowania aparatem (ISO/Przysłona/Czas/WB/AF w sidebarze Sesji + „Domyślne ustawienia aparatu") zostały ŚWIADOMIE usunięte z UI — ekspozycję ustawia się na aparacie (`CameraSession.get_settings()/set_setting()` w `camera.py` zostały jako API, ale GUI ich nie woła).

Stan recenzji per sesja: `photos/<sesja>/.review.json` (`rejected`/`uploaded`/`meta`/`automat` = mapa plik→id zdjęcia w Automacie, zapisywana po announce/upload i zużywana przy delete). Licznik w pasku zakładek: `zdjęć` = finalne minus odrzucone (licznik `odrzuconych` usunięty z UI). Rails: API ma `DELETE /api/photo_studio/sessions/:id/photos/:photo_id` (dodane w trix-automat razem z tą zmianą).

Wątki (gphoto2 nie jest thread-safe — aparat ma JEDNEGO właściciela):
- **camera** — `CameraSession` + pętla preview z throttlingiem do `preview_fps`; komendy przez `_cam_q` (shoot / set_camera); auto-reconnect co 5 s gdy init się nie uda lub podgląd padnie (np. inna aplikacja trzyma aparat). **Backoff przy „flapping"**: gdy połączenie pada szybciej niż `_HEALTHY_AFTER` (5 s) — typowo urządzenie PTP bez live view albo aparat w trybie odtwarzania — przerwa rośnie `RECONNECT_MIN`→`RECONNECT_MAX` (2 → 30 s), a cykl przechodzi w tryb cichy (`_run_connected(quiet=True)`): jedna linia ostrzeżenia zamiast pary „połączony"/„podgląd przerwany" co obrót. Wpis „Aparat połączony" wraca dopiero, gdy klatki polecą dłużej niż `_HEALTHY_AFTER`. Bez tego każdy obrót przechodził przez `_configure_camera()`, więc terminal zalewały setki linii „aparat nie eksponuje ('imageformat', …)" — te ostrzeżenia z `camera.py` idą teraz przez `_warn_once()` (raz na proces, per komunikat). `WebUI._log()` dodatkowo zwija powtórzony pod rząd wpis w licznik `n` (front dokleja „×N"), więc log w UI też nie puchnie.
- **worker** — `_jobs`: obróbka (announce → `process(out_name=...)` → przeniesienie raw do `raw/` → upload), batch, reprocess, delete, test. Strzały kolejkują się, preview nie zamiera.
- **HTTP** — ThreadingHTTPServer; stan pod RLock.

Zamykanie (`WebUI.stop()`, wołane po powrocie `webview.start()`): flaga stop → join wątku camera (timeout 4 s — wątek domyka sesję gphoto2; porzucona otwarta sesja PTP = zawieszka libusb przy finalizacji procesu + BUSY przy następnym starcie) → join workera → shutdown serwera → `os._exit(0)` w `gui.py` (wiszące wątki C: libusb/onnxruntime/Cocoa potrafią zablokować normalną finalizację interpretera).

`CameraSession` (w `src/camera.py`): trwała sesja aparatu — `open()` (init z reaperem + `_configure_camera`), `preview_frame()` (JPEG ~960×640, to co LCD aparatu), `capture_to()` (pełny strzał przez współdzielone `_capture_with_retry` — retry 5× + reset USB; po recovery obiekt `camera` może być NOWY), `get_settings()/set_setting()` (widgety ekspozycji), `describe_contrast()/set_contrast()`, `close()`. TUI dalej używa `capture_from_camera()` (init per strzał) — bez zmian w zachowaniu.

## UI (fullscreen TUI, `src/tui.py`)

Rich `Live(screen=True)` (alternate screen), układ od góry: **sticky header** (nazwa sesji, licznik, folder, chipy stanów Upload/Logo/Zoom/Centrowanie, hint) → opcjonalnie **menu** lub **panel wpisywania nazwy** → linia statusu (spinner podczas capture/processing) → **przewijany log** (ostatnie linie z deque 300; zapisy zdjęć, komunikaty Automatu, przechwycone print()y z `camera.py`). Header nigdy nie odjeżdża — log wypełnia resztę ekranu i przycina się od góry.

Klawisze (raw cbreak, `_KeyReader` dekoduje sekwencje strzałek):
- `ENTER` — strzał
- `↓` lub `h` — otwiera menu; w menu `↑`/`↓` nawigacja, `ENTER` zatwierdza, `ESC` zamyka
- skróty działają też bez otwierania menu: `n` (nazwa sesji — inline input w TUI, ESC anuluje), `u` (upload ON/OFF), `l` (logo ON/OFF), `p` (róg logo cyklicznie), `z` (zoom ON/OFF), `c` (centrowanie ON/OFF)
- `q` — wyjście

Start = od razu panel wpisywania nazwy (bez nazwy nie da się strzelić). Po zatwierdzeniu nazwy (i przy `u` ON), jeśli w Automacie istnieje już sesja o tej nazwie (`find_existing_session()` — najnowsza, case-insensitive), TUI pokazuje żółty panel „Istniejaca sesja w Automacie": `ENTER`/`p` podłącza po id (`attach_session`), `n` otwiera nową (POST po nazwie), `ESC` zostawia upload OFF. Decyzja pamiętana per nazwa (`attach_to`) — toggle `u` OFF→ON nie pyta drugi raz; zmiana nazwy sesji pyta od nowa. Ten sam wybór w ścieżce `--input` (`make_uploader` w `main.py`, rich `Confirm.ask`). Czyszczenie tła nie ma toggle — zawsze ON. Raw jest i tak zapisywany obok finalnego JPEG-a, więc operator ma kopię „surową" gdyby clean_bg coś zepsuł na konkretnym ujęciu.

Szczegóły implementacyjne:
- `Console(file=sys.stdout)` wiąże realny stdout na sztywno — podczas strzału `redirect_stdout(_LogWriter)` przechwytuje print()y z `camera.py`/`process()` do logu TUI i NIE może porwać renderingu Live (Live pisze przez związany `console.file`).
- Spinner animuje się w wątku refresh Live (12 fps) mimo że capture blokuje główny wątek.
- `log()` rozbija wielolinijkowe wpisy po `\n` — deque trzyma POJEDYNCZE linie. Docinanie ogona logu do wysokości panelu liczy wpisy, więc wpis wielolinijkowy (np. błąd aparatu z checklistą) rozjechałby rachunek: panel przycina nadmiar od dołu i najnowsze linie znikałyby z ekranu. Każda linia ma `no_wrap + ellipsis` z tego samego powodu (zawijanie też psuje rachunek wysokości).
- `keys.drain()` (`termios.tcflush`) po strzale — ENTERy wciśnięte podczas obróbki nie wyzwalają drugiego strzału.

## Aktualizacje (GitHub Releases → samo-aktualizacja .exe)

Kanał wydań to **GitHub Releases** publicznego repo `Xeross99/camera-capture` (`GITHUB_REPO` w `src/version.py`). Artefakty CI się nie nadają — wymagają logowania i wygasają po 90 dniach.

**Wypuszczenie wersji**: podbij `APP_VERSION` w `src/version.py` → commit → `git tag vX.Y.Z && git push --tags`. Workflow buduje `.exe`, sprawdza że tag == `APP_VERSION` (rozjazd = fail builda, żeby aplikacja nie kłamała o swojej wersji) i publikuje release z paczką `CameraCapture-windows-vX.Y.Z.zip`. Zip jest pakowany **z poziomu katalogu** `dist/CameraCapture` — na wierzchu leżą `.exe` i `_internal/`, bez katalogu-opakowania.

**Sprawdzanie** (`check_for_update()`): `GET /repos/<repo>/releases/latest`, porównanie `tag_name` z `APP_VERSION` przez `parse_version()`. Bez tokena (repo publiczne), limit 60 req/h na IP w zupełności starcza — pytamy raz przy starcie (job `check_update` w kolejce workera) i na żądanie z Ustawień. Repo bez żadnego wydania zwraca 404 — traktowane jak „brak nowszej wersji", nie jak błąd.

**Instalacja** działa TYLKO dla spakowanego `.exe` na Windowsie (`can_self_update()` = `sys.frozen` + `win32`) — działającego procesu nie da się nadpisać:
1. `download_and_stage()` — zip do `%TEMP%\cc_update_*\payload`, rozpakowanie z odsianiem ścieżek uciekających poza katalog (zip-slip — paczka jest z sieci), progress w `state["update"]["progress"]`.
2. `_validate_staging()` — paczka MUSI mieć `.exe` i `_internal/`, inaczej stop. Bez tego `robocopy /MIR` na pustym staging wyczyściłby `_internal` działającej instalacji.
3. `apply_update_and_restart()` — pisze `.bat` w tempie i odpala go odłączonego, po czym `WebUI._restart_into()` robi `stop()` (domknięcie sesji aparatu — porzucone PTP = BUSY po restarcie) i `os._exit(0)`.
4. `.bat` czeka aż PID zniknie (`tasklist`), robi `robocopy _internal /MIR` (stare DLL-e z poprzedniej wersji znikają) + `robocopy /E` reszty **bez kasowania** (`.env`, `photos/`, ręcznie dołożony `EDSDK.dll` zostają — one żyją obok `.exe`, patrz `PROJECT_DIR`), startuje `.exe` i kasuje sam siebie.

**UI**: baner nad zakładkami (`updateBanner()` w `app.js`) — „Dostępna aktualizacja X.Y.Z" + „Zaktualizuj i uruchom ponownie" + „Później" (chowa do końca uruchomienia, per wersja). Aktualizacja jest odmawiana w trakcie zdjęcia/obróbki (`busy`/`processing`), a w drugą stronę — gdy `update_busy`, `_act_shoot` blokuje migawkę (zdjęcie zrobione tuż przed restartem zginęłoby razem z workerem, bo job nie doczekałby się obróbki). Progress pobierania jest ŚWIADOMIE poza kluczem shella (patchowany po `id` w `updateVolatile()`) — rebuild shella niszczy `<img>` streamu MJPEG, więc każdy procent oznaczałby miganie live view. Karta „Aktualizacje" w Ustawieniach ma wersję, „Sprawdź aktualizacje" i notatki z release'a. Sprawdzanie i pobieranie pokazują spinner (`.spinner` w `style.css`): `update.checking` jest ustawiane już w `_act_check_update` (jeszcze przed odpowiedzią na POST, więc łapie je pierwszy poll nawet gdy worker jest zajęty), a front trzyma go dodatkowo przez ~650 ms od kliknięcia (`S.checkStartedAt`) — odpowiedź z GitHuba potrafi wrócić w ~150 ms, czyli szybciej niż 500 ms poll, i spinner mignąłby bez śladu.

**Uruchomienie ze źródeł** (macOS/dev, TUI): `canApply=false` — UI tylko informuje, że jest nowszy tag i że aktualizuje się przez `git pull`. TUI robi to samo jedną linijką w logu z wątku w tle (`_check_update_bg`), bez blokowania startu.

Uwaga: `.exe` jest niepodpisany, więc SmartScreen może marudzić przy pierwszym uruchomieniu nowej wersji.

## Struktura

- `main.py` — parsowanie argv, ścieżka `--input` (bez aparatu, klasyczne printy), `--list-formats`; tryb interaktywny deleguje do `CaptureTUI`.
- `gui.py` — launcher aplikacji okienkowej (pywebview, natywny pasek tytułu; po zamknięciu okna `ui.stop()` + `os._exit(0)`; `--browser` = fallback w przeglądarce).
- `src/cli.py` — `add_capture_args()`: flagi CLI wspólne dla `main.py` i `gui.py` (name/logo/zoom/centrowanie/output-dir/upload); flagi specyficzne (`--input`, `--list-formats`, `--port`, `--browser`) zostają w plikach wejściowych.
- `src/webui.py` — `WebUI`: backend aplikacji (serwer HTTP, wątki camera/worker, review store) — patrz sekcja „Aplikacja okienkowa". Handler HTTP to modułowa klasa `_Handler` (`ui` wstrzykiwane subklasą w `start()`); akcje z frontu i joby workera dispatchowane przez słowniki `_ACTIONS` / `_JOBS` (metody `_act_*` / `_job_*`).
- `src/webui_static/` — frontend 1:1 z projektu Claude Design: `index.html` (szkielet strony), `style.css` (globalne style + `@font-face`; większość stylowania to inline style w template stringach JS — tak było w projekcie), `app.js` (cała logika: stan `S`, render keyowany, klawiatura, poll `/api/state`), `plex-mono-*.woff2` (IBM Plex Mono 400/500, latin + latin-ext — font bundlowany lokalnie, UI działa offline; zero zewnętrznych zależności sieciowych).
- `src/tui.py` — `CaptureTUI`: fullscreen TUI (patrz sekcja „UI"), `_KeyReader` (cbreak + strzałki), `_LogWriter` (przechwycenie stdout do logu). Unix-only (termios/tty) — na Windowsie importowany leniwie w `main.py`, z komunikatem „użyj gui.py".
- `src/naming.py` — `sanitize_name()` (wspólne dla `main.py`/`tui.py`/`webui.py`; wydzielone z `tui.py`, żeby webui nie ciągnął termios na Windowsie).
- `src/camera.py` — `capture_from_camera()`: init z retry (5 prób, wydzielony `_init_camera()`), `_PtpCameradReaper` ubija `ptpcamerad`/`PTPCamera` SIGKILL-em co 30 ms przez cały czas trwania `init()` (patrz sekcja „Znane problemy"). `_apply_image_format()` ustawia `CAMERA_IMAGE_FORMAT` przez gphoto2 widget, `_disable_autorotation()` ustawia `autorotation` widget na `Off`/`None` (żeby aparat nie zapisywał EXIF Orientation tagu). Retry capture na `-1 Unspecified error`, `-110 I/O in progress` i `-6 Unsupported operation` (`_RETRYABLE_CAPTURE_ERRORS`). Przy trzecim z rzędu `-110` (BUSY) `_reconnect_after_usb_reset()`: exit sesji → `_reset_usb_device()` (pyusb, port reset urządzenia Canon = software'owe wypięcie kabla, czyści zawieszoną sesję PTP) → re-init z reaperem; raz na capture. Jak i to nie pomoże — exit z instrukcją power-cycle/wyjęcia baterii (BUSY firmware'u nie da się odwiesić z hosta). `list_image_formats()` dla `--list-formats`. Retry+download wydzielone do `_capture_with_retry()`/`_download_capture()` — współdzielone przez `capture_from_camera()` (init per strzał, TUI/CLI) i `CameraSession` (trwała sesja dla GUI: `open()`/`preview_frame()`/`capture_to()`/`close()`). Import gphoto2 jest opcjonalny (`gp = None` gdy brak — np. Windows); eksporty cross-platformowe: `GPhoto2Error` (placeholder gdy brak gphoto2), `CAMERA_ERRORS` (wspólna tupla błędów obu backendów — webui łapie ją zamiast `gp.GPhoto2Error`), `make_camera_session()` (fabryka wg `CAMERA_BACKEND`: auto → gphoto2 jeśli importowalne, na win32 digiCamControl). Reaper ptpcamerad i `killall` są za guardem `sys.platform == "darwin"`.
- `src/camera_edsdk.py` — `EdsdkSession`: backend aparatu dla Windows przez Canon EDSDK (ctypes, `EDSDK.dll` + `EdsImage.dll` x64 obok aplikacji lub `EDSDK_DLL` z .env; `find_edsdk_dll()` używane też przez fabrykę do auto-wyboru). Live view = EVF memory stream (`EdsDownloadEvfImage`, retry na `OBJECT_NOTREADY`), strzał = `PressShutterButton` + `SaveTo=Host` (plik leci do nas przez pamięć, nie na kartę SD; czekanie na `DirItemRequestTransfer` pompowane `EdsGetEvent`). Wszystkie wywołania z jednego wątku (camera w webui). `get_settings()` zwraca `{}` jak dCC. 32-bitowa DLL (np. z instalacji dCC) jest wykrywana po nagłówku PE i odrzucana z czytelnym błędem.
- `src/camera_digicam.py` — `DigiCamControlSession`: backend aparatu dla Windows przez webserver HTTP digiCamControl (port 5513; live view = `GET /liveview.jpg` po `CMD=LiveViewWnd_Show`, strzał = SLC `capture` z `session.folder` przestawionym na katalog roboczy + poll aż plik się pojawi i rozmiar się ustabilizuje). Gdy webserver nie odpowiada, `open()` sam startuje `CameraControl.exe` (ścieżki instalatora lub `DIGICAMCONTROL_EXE` z .env, raz na życie sesji) i czeka do 30 s; po pierwszej klatce chowa okna dCC przez `CMD=All_Minimize` (z fallbackiem: gdy po minimalizacji live view padnie, okno wraca i flaga `_minimize_ok` blokuje kolejne próby). Interfejs 1:1 z `CameraSession`; `get_settings()` zwraca `{}`, `set_setting()` rzuca. Szczegóły setupu: `WINDOWS.md`.
- `src/image_processing.py` — `crop_to_aspect()`, `overlay_logo()`, `process()`. `process()` zapisuje raw kopię (`shutil.copy2`) przed obróbką, potem `clean_background(image, canvas_size)`, potem overlay logo. Parametr `clean_bg` w sygnaturze jeszcze jest, ale w prod jest hardcoded na `True` — gałąź `crop_to_aspect+resize` to martwy kod (nie wywoływany przez UI/CLI). EXIF Orientation świadomie nie jest honorowany.
- `src/background.py` — `clean_background(image, canvas_size)` to krótki orkiestrator: rembg → `_product_alpha` (maska+alpha, dual-path niżej) → `_lift_internal_shadows` → `_select_crop_window` (dispatcher; każdy przypadek auto-center/zoom to osobna funkcja `_window_*` zwracająca okno cropu `(sl, st, sr, sb)` w pikselach source) → `_compose_on_canvas` (crop/resize/sharpen/cień/kompozyt). Pipeline na full-res: rembg inference w `CLEAN_BG_INFERENCE_SIZE` (domyślnie 768) → maska upscale do full-res → `_filter_small_blobs` (odsiewa rembg false-positives) → **dual-path w zależności od jasności tła** (`bg_lum > 200` = `light_bg`):
  - **Light bg** (typowy biały stół): luminance gate odsiewa piksele jaśniejsze niż `bg_lum * 0.95` z maski produktu (cienie, halo). Selektywne hole-fill: wypełnia tylko dziury z `img_lum < bg_lum * 0.6` (ciemny materiał pominięty przez rembg). **Alpha liczona z luminancji obrazu** (nie z rembg): cubic falloff w zakresie `[bg_lum*0.75, bg_lum*0.98]` — ciemne piksele → opaque, jasne → transparent. rembg służy tylko do wykrycia regionu produktu (dilation), nie do alfy.
  - **Dark bg** (nietypowe tło): rembg alpha z kontrastem `[FLOOR, CEILING] → [0, 255]`, brak luminance gate, brak hole-fill.
  - Wspólne: `_lift_internal_shadows()` → `_image_bleed_edges()` decyduje czy bleed-fit → bbox crop (Y-fit-only przy wide_product+x_bleed, X-fit-only przy tall_product+y_bleed, fit-both inaczej) → resize do `canvas_size` → `_build_shadow_layer()` (no-op gdy `SHADOW_STRENGTH=0`) → kompozyt. `_session()` ma LRU cache 1.
- `src/config.py` — wszystkie stałe konfiguracyjne. Ładuje `.env` przez `python-dotenv` (PROJECT_DIR/.env). Pod PyInstallerem (`sys.frozen`) `PROJECT_DIR` = katalog `.exe` (żeby `.env`/`photos/` nie lądowały w tempie `_MEIPASS`).
- `src/automat_uploader.py` — `AutomatUploader`: `open_session(product_name)` → POST `/api/photo_studio/sessions` (zwraca `id`, `product_found`, `reattached`, `photos_count`); `announce_photo(filename)` → POST z `data={filename}` rejestrujący placeholder; `upload_processed(path, photo_id=...)` → PUT na `/photos/:id` (lub POST jeśli brak photo_id); `session_photos()` → GET `/sessions/:id` (lista zdjęć sesji) i `download_photo(id, dest)` → GET `/sessions/:id/photos/:photo_id/file` (zapis przez `.part` + rename, żeby przerwane pobieranie nie zostawiło obciętego JPEG-a w filmstripie). Auth: `Bearer <AUTOMAT_TOKEN>`. Sesja deduplikowana po stronie Rails per produkt + dzień. Przy 404 z announce/upload klient automatycznie odtwarza sesję (`_reopen()`) i ponawia raz; HTML error pages z Rails dev mode są odsiewane (`_strip_body`) — w logu masz tylko status code, nie 8 KB DOCTYPE'a.
- `src/version.py` — `APP_VERSION` + `GITHUB_REPO` + `parse_version()`. JEDNO źródło prawdy o wersji: czyta je updater, `CameraCapture.spec` (generuje z niej `build/version_info.txt`) i CI (weryfikuje tag). Bez importów — spec czyta ten plik zanim cokolwiek innego się zaimportuje.
- `src/updater.py` — sprawdzanie i instalacja aktualizacji z GitHub Releases (patrz sekcja „Aktualizacje").
- `assets/logos/trixbrix_eu.webp` — domyślne logo (RGBA, czarne `TRIXBRIX.eu`).

## Auto-center

Liczę bbox z maski binarnej, skaluję obraz tak żeby produkt mieścił się z `PRODUCT_MARGIN` z każdej strony, i przesuwam tak żeby środek bbox = środek kadru. Kompozytuję `image.paste(img, (paste_x, paste_y), mask=soft_mask)` — `soft_mask` to alpha z rembg z lekkim blurem (`CLEAN_BG_EDGE_BLUR=0.6`).

**Zoom i centrowanie to dwa niezależne toggle** (`auto_zoom` / `auto_center`, UI: `z` / `c`, CLI: `--no-auto-zoom` / `--no-auto-center`). Cztery kombinacje w `clean_background`:
- **zoom ON + center ON** — pełna maszyneria opisana niżej (bleed-fit, small_product itd.).
- **zoom ON + center OFF** — okno cropu zoomowane do bboxa (fit-both z `PRODUCT_MARGIN`), ale kotwiczone proporcjonalnie do pozycji produktu w source (produkt odsunięty od środka kadru zostaje odsunięty w canvy). Okno clampowane tak, żeby zawsze objęło cały bbox — produkt przy krawędzi kadru nie jest ucinany, ląduje przy krawędzi canvy.
- **zoom OFF + center ON** — naturalne okno (największy canvas-aspect prostokąt w source, jak small_product) wycentrowane na bboxie, clamp do granic source.
- **zoom OFF + center OFF** — centralny crop sensora bez patrzenia na produkt (produkt mocno poza środkiem może być ucięty krawędzią cropu — to świadome „nie ruszaj nic").

Bleed-fit i small_product działają tylko przy obu ON.

**Wyjątek — bleed off-frame**: `_image_bleed_edges()` zwraca dict `{left, right, top, bottom: bool}`. Pasek 0.5% szerokości od każdej krawędzi sprawdzany na surowym obrazie (nie na masce — u2netp @ 768 inference potrafi obciąć cienkie wystające fragmenty np. szynę sięgającą krawędzi, więc bbox by pudłował). Próg `bg_lum * 0.7` z `bg_mask` (alpha < 32) — fallback 95-percentyl jeśli tła za mało; min 50 ciemnych pikseli na pasek żeby uznać krawędź za bleedującą.

Auto-center wybiera ścieżkę po trzech sygnałach: **rozmiar produktu względem source** (`max(bw/src_w, bh/src_h)` < 0.30 = small product), **kształt bboxa względem canvy** (`bw/bh` vs `canvas_aspect`, ±5% tolerancji) oraz **bleed na choćby jednej krawędzi danej osi**:

- **any_x_bleed + any_y_bleed** (np. krzyżak torów ucięty przez wszystkie krawędzie source) — sprawdzany PRZED wide/tall. Żadnej osi nie da się „zfitować" bez pokazania amputowanej krawędzi cięcia pływającej w kadrze z białym marginesem. Crop = największe canvas-aspect okno mieszczące się W CAŁOŚCI w source (dla 1:1 z 3:2: `crop_h = src_h`, `crop_w = src_h`). Anchor per-oś: jedna strona bleeduje → bbox edge nie-bleedującej strony + `PRODUCT_MARGIN`; obie bleedują → środek bboxa. Na końcu clamp okna do granic source — biały padding po bleedującej stronie odsłoniłby cięcie. Efekt: każda ucięta krawędź ląduje na/za krawędzią canvy i produkt wizualnie kontynuuje off-frame na obu osiach.

- **small_product** (np. LEGO 2x2 w środku kadru — bbox ~600×600 z source 6000×4000 = fill_ratio 0.15) → preserve natural framing. Crop window = największy canvas-aspect prostokąt który mieści się w source (dla 1:1 canvy z 3:2 source: `crop_h = src_h, crop_w = src_h * canvas_aspect = src_h`). Scale = `canvas_h / src_h` = 0.375. Bbox w canvy zachowuje swoją source-frame proporcję — produkt nie jest agresywnie zoom'owany. Bleed-fit pomijany dla small_product, bo małe produkty nie bleedują.

- **wide_product + any_x_bleed** (bbox wyraźnie szerszy niż canvy spinanie X — np. szyna buforem wystaje poza lewą lub prawą lub obie) → fituj Y, X overflow off-canvas. `crop_h = bh / bleed_inner` (z `BLEED_FIT_MARGIN`), `crop_w = crop_h * canvas_aspect`. Po wyznaczeniu jest **clamp `crop_w ≤ bw`** żeby zbyt duży margin nie wepchnął bleedującej krawędzi bbox-a w canvy (i nie zabił bleed-effectu). Anchor:
  - **non-bleeding side X**: `bbox edge + PRODUCT_MARGIN`. Np. lewa bleed, prawa nie → `sr = bbox.r + crop_w*PRODUCT_MARGIN`, więc bbox.r jest 15% canvy od prawej krawędzi (przestrzeń pod logo). Lewa strona bbox-a wychodzi poza lewą canvy (bleed).
  - **non-bleeding side Y**: `bbox edge + PRODUCT_MARGIN`. Np. dół bleed, góra nie → `sb = bbox.b + crop_h*PRODUCT_MARGIN`, czyli bbox.b 15% nad canvas bottom. To zostawia czystą strefę dla logo (bottom-right), góra dostaje resztę crop window (zwykle białe niebo/ściana ze source nad bboxem ~30-40% canvy).
  - **bleeding side**: nie adjustowany — wynika z anchor non-bleeding (`sl = sr - crop_w` lub `st = sb - crop_h`). Bbox edge na bleedującej stronie ląduje poza canvy, produkt wizualnie kontynuuje off-frame.
  - obie strony X bleedują → cx = bbox center; analogicznie obie Y bleedują → cy = bbox center.
- **tall_product + any_y_bleed** → symetrycznie: fituj X, Y overflows.
- inne kombinacje (wąsko/wysoki produkt centrowany bez bleeda, single-edge bleed na osi prostopadłej do dominującego wymiaru itd.) → standardowy fit-both (`crop_w = bw/inner`, `crop_h = bh/inner`, większy wymiar dyktuje skalę → produkt centrowany z `PRODUCT_MARGIN` ze wszystkich stron) **z kotwiczeniem bleedu**: jeżeli któraś krawędź bleeduje (typowy przypadek: kwadratowy bbox ~1.0 wpadający w ±5% martwą strefę wide/tall + dolny bleed), okno cropu na tej osi nie jest centrowane, tylko kotwiczone do bleedującej krawędzi source (`st = src_h - crop_h` dla dolnego bleedu itd.) — cięcie z raw ląduje dokładnie na krawędzi canvy i produkt wizualnie kontynuuje off-frame, zamiast pływać nad białym marginesem. Obie krawędzie osi bleedują → crop capowany do rozmiaru source na tej osi i clamp do środka. Krawędzie bez bleedu → normalne centrowanie/margines.

Założenie: produkt szerszy niż canvy w 1:1 nie da się zmieścić w całości — fit-both go zmniejsza i zostawia pasy białego po bokach (na drugim outpucie #12). Y-fit z anchor-do-bbox-edge na nie-bleedującej stronie zachowuje skalę produktu i naturalną kompozycję źródła (np. niebo/ścianę nad produktem).

## Shadow handling

Dwie funkcje w `src/background.py`:

### `_build_shadow_layer()`
Warstwa cienia STRICTLY pod produktem (per-column bottom + horizontal bbox margin):
1. Dla każdej kolumny x liczy `ref_y[x]` = najniższy fg pixel w tej kolumnie (lub bbox bottom dla kolumn-przerw).
2. Cień rozciąga się tylko poniżej `ref_y[x]` (`dy = y - ref_y[x] >= 0`).
3. Falloff exponential: `proximity = exp(-3 * dy / shadow_radius_px)` — gładkie wygaszenie do zera, brak twardej krawędzi.
4. Gating horyzontalny: tylko kolumny w bbox produktu + 3% marginesu po bokach.
5. `darkness * SHADOW_STRENGTH * proximity` przyciemnia białe tło.

### `_lift_internal_shadows()`
Lifting cieni widocznych przez prześwity produktu (np. między elementami szyny):
1. Wykrywa piksele "jasne ale przyciemnione" (`lum/bg_lum` w przedziale `[0.55, 0.95]`) — to typowo cień na białym stole widoczny przez gap w produkcie.
2. Te piksele podciągane do bieli proporcjonalnie do darkness × strength.
3. Szare ciało produktu (`lum/bg_lum < 0.55`) NIE jest ruszane.

Aplikowane na obrazie ŹRÓDŁOWYM przed paste, dzięki czemu po `canvas.paste(img, mask=soft_mask)` prześwity wyglądają czysto.

## Pozycja logo

Domyślnie prawy dolny róg (`image_processing.py:overlay_logo`).
- `LOGO_ENABLED=True` — nakładanie logo w ogóle; CLI `--no-logo` wyłącza na czas uruchomienia.
- `LOGO_POSITION="bottom-right"` — róg logo (`bottom-right`/`bottom-left`/`top-right`/`top-left`, walidacja w `LOGO_POSITIONS`; nieznana wartość → fallback bottom-right z warningiem); CLI `--logo-position`.
- `LOGO_HEIGHT_RATIO=0.06` — wysokość logo / wysokość kadru.
- `LOGO_MARGIN_RATIO=0.04` — margines od krawędzi / szerokość kadru.
- `LOGO_OPACITY=0.5` — stałe krycie watermarku. Suwak „Krycie" w GUI usunięty ŚWIADOMIE — wartość nie jest zmienialna z UI.

Uwaga: anchory bleed-fit w auto-center (sekcja wyżej) zakładają logo w prawym dolnym rogu — zostawiają czystą strefę bottom-right. Przy zmianie `LOGO_POSITION` na inny róg bleed-fit nadal chroni bottom-right, nie nowy róg (świadome uproszczenie; regularne fit-both ma margines ze wszystkich stron, więc tam bez różnicy).

## Konfiguracja (`src/config.py`)

| Stała | Default | Co robi |
|-------|---------|---------|
| `ASPECT_W, ASPECT_H` | `1, 1` | Aspect ratio crop. |
| `OUTPUT_SIZE` | `3000` | Rozmiar finalnego JPEG (pikseli). |
| `LOGO_ENABLED` | `True` | Nakładanie logo. CLI `--no-logo` wymusza OFF. |
| `LOGO_POSITION` | `"bottom-right"` | Róg logo. CLI `--logo-position`. |
| `LOGO_HEIGHT_RATIO` | `0.06` | Wysokość logo jako ułamek kadru. |
| `LOGO_MARGIN_RATIO` | `0.04` | Margines logo. |
| `LOGO_OPACITY` | `0.5` | Stałe krycie watermarku — bez możliwości zmiany z UI (suwak usunięty ŚWIADOMIE). |
| `JPEG_QUALITY` | `95` | Quality finalnego JPEG. |
| `CAMERA_IMAGE_FORMAT` | `"L"` | Format aparatu (L = Large Fine JPEG, ~24 MP, 6000×4000). Inne na M50 II: `L`/`cL`/`M`/`cM`/`S1`/`cS1`/`S2`. RAW nie obsługiwane. |
| `CLEAN_BG_MODEL` | `"u2netp"` | Model rembg. Wybrany po benchmarku — najczystsze cienie + ~15× szybszy od BiRefNet na klockach. |
| `CLEAN_BG_INFERENCE_SIZE` | `768` | rembg inference resolution. Mniejszy = szybszy. |
| `CLEAN_BG_MASK_THRESHOLD` | `80` | Próg binaryzacji maski (dla `filtered` + bbox). 160 (wcześniej) odcinało low-confidence części produktu typu cieńszy rail przy bleedującej krawędzi gdzie rembg dawał alpha 80–150 — bbox nie obejmował ich, alpha 0 w composite, biała dziura w canvy gdzie produkt powinien bleedować. 80 łapie te masy a `_filter_small_blobs` wciąż odsiewa szum tła. |
| `CLEAN_BG_EDGE_BLUR` | `0.6` | Gaussian blur radius na alpha mask (anty-aliasing). |
| `CLEAN_BG_ALPHA_FLOOR` | `40` | Dolny próg alfy (tylko dark-bg path): wszystko < 40 → 0. Wyższe wartości (próbowano 80) zabijały też mid-confidence piksele wewnątrz produktu (np. rail, gdzie u2netp dawał 50–120) i robiły białe dziury w composite. 40 zostawia te piksele a wciąż usuwa halo z bg. Light-bg path liczy alfę z luminancji obrazu (cubic falloff), nie używa floor/ceiling. |
| `CLEAN_BG_ALPHA_CEILING` | `200` | Górny próg (tylko dark-bg path): alfa ≥ 200 → 255. Razem z floor liniowa rampa 40→200 mapowana na 0→255 — czystsze brzegi bez utraty AA (`CLEAN_BG_EDGE_BLUR=0.6` robi finalne wygładzenie). |
| `AUTO_CENTER` | `True` | Centrowanie bbox produktu w kadrze. UI `c`, CLI `--no-auto-center`. |
| `AUTO_ZOOM` | `True` | Przybliżanie produktu (skalowanie okna cropu do bboxa). UI `z`, CLI `--no-auto-zoom`. |
| `PRODUCT_MARGIN` | `0.15` | 15% pustego marginesu wokół produktu (regularny auto-center fit-both). Wartość minimum dla ochrony logo: `0.10` (`LOGO_HEIGHT_RATIO + LOGO_MARGIN_RATIO`). |
| `BLEED_FIT_MARGIN` | `0.28` | Margines używany TYLKO w bleed-fit (wide_product+x_bleed → fituj Y; tall_product+y_bleed → fituj X). Wyższy niż `PRODUCT_MARGIN` bo przy 70%-bbox produkt szeroki wygląda klaustrofobicznie — 50% bbox daje oddech nad/pod. |
| `SHADOW_STRENGTH` | `0.0` | Siła syntetycznego cienia pod produktem. 0=brak (default — reference TrixBrix nie ma cienia), 1=pełna luminancja oryginału. Przy 0 `_build_shadow_layer` jest pomijany. |
| `SHARPEN_PERCENT` | `120` | Siła unsharp mask (radius=1.5, threshold=3 hardcode). Aplikowany w `clean_background` na `sub_img` PRZED paste'em na białą canvy — białe tło wchodzi czystym `Image.new(white)`, więc USM go nie dotyka i nie ma halo na alpha-edge. 0=disable. |
| `SHADOW_RADIUS_RATIO` | `0.20` | Zasięg cienia poniżej produktu jako ułamek wysokości kadru. |
| `AUTOMAT_BASE_URL` | env `AUTOMAT_URL`, fallback `http://localhost:3000` | Adres instancji Automatu (Rails). |
| `AUTOMAT_API_TOKEN` | env `AUTOMAT_TOKEN` | Bearer token. Bez niego upload jest wyłączony (`make_uploader` zwraca `None`). |
| `TRASH_RETENTION_DAYS` | env `TRASH_RETENTION_DAYS`, default `30` | Ile dni pliki leżą w `photos/.trash` (usunięte zdjęcia i foldery sesji), zanim `_purge_trash()` skasuje je na stałe. `0` = bez kosza, kasowanie natychmiastowe. |
| `AUTOMAT_UPLOAD_ENABLED` | env `AUTOMAT_UPLOAD_ENABLED`, default `true` | Domyślny stan uploadu przy starcie (GUI: zawsze ON gdy jest token; wpisanie tokena w Ustawieniach też włącza). CLI `--no-upload` wymusza OFF (narzędzie deweloperskie). |
| `CAMERA_BACKEND` | env `CAMERA_BACKEND`, default `auto` | Backend aparatu: `auto` (gphoto2 jeśli importowalne; na win32 edsdk gdy jest EDSDK.dll, inaczej digiCamControl) / `gphoto2` / `edsdk` / `digicamcontrol`. |
| `EDSDK_DLL` | env `EDSDK_DLL`, default `None` | Ścieżka do `EDSDK.dll` (lub jej katalogu) dla backendu edsdk — bez niej szukana w `PROJECT_DIR` i `PROJECT_DIR/edsdk`. |
| `DIGICAMCONTROL_URL` | env `DIGICAMCONTROL_URL`, default `http://127.0.0.1:5513` | Adres webservera digiCamControl (backend Windows). |
| `DIGICAMCONTROL_EXE` | env `DIGICAMCONTROL_EXE`, default `None` | Ścieżka do `CameraControl.exe` dla auto-startu dCC — bez niej sprawdzane są typowe ścieżki instalatora (`Program Files (x86)`/`Program Files`). |

## Upload do Automatu (Rails)

Endpointy:
- `POST /api/photo_studio/sessions` — body `product_name=<sanitized name>`. Rails szuka produktu (case-insensitive exact). Znalazł → bindowana sesja (idempotentne per dzień + produkt). Nie znalazł → sesja luźna z labelem = wpisana nazwa, **bez 404**. Response: `{id, name, product_id, product_found, reattached, photos_count}`.
- `POST /api/photo_studio/sessions/:id/photos` z `data={filename}` — `announce_photo`, tworzy placeholder; zwraca `{id}`.
- `PUT /api/photo_studio/sessions/:id/photos/:photo_id` z multipart `file=` — `upload_processed`, podpina przetworzony JPEG do placeholdera. Bez `photo_id` leci POST na ten sam URL bez `:photo_id`.
- `GET /api/photo_studio/sessions/:id` — sesja z listą zdjęć (`photos: [{id, status, filename, processed, raw_filename, error_message}]`), źródło prawdy dla `sync_session`.
- `GET /api/photo_studio/sessions/:id/photos/:photo_id/file` — przetworzony JPEG z powrotem (`send_data`, Bearer jak reszta API — bez publicznych URL-i Active Storage). Dodane w trix-automat razem z tą zmianą; **wymaga deployu Automatu**, bo bez tego endpointu klient dostaje 404 i nic nie pobierze.

Wszystko z nagłówkiem `Authorization: Bearer <AUTOMAT_TOKEN>`. Sesja otwiera się przy starcie, przy `n` (zmiana nazwy) i przy `u` ON. Flow strzału: `capture` → `announce_photo(...)` (UI Automatu od razu pokazuje kafelek ze spinnerem) → lokalny processing → `upload_processed(..., photo_id=announced)`.

**Auto-retry przy 404**: jeżeli sesja zniknęła po stronie Rails (restart bazy, czyszczenie), zarówno `announce_photo` jak i `upload_processed` raz odtwarzają sesję przez `_reopen()` i powtarzają operację. Przy upload retry leci jako POST bez `photo_id` (stary id z poprzedniej sesji jest martwy, robimy nowy rekord).

Błędy łapane w `make_uploader` / `announce_or_log` / `upload_raw_or_log` i logowane w rich panelu — nie wywalają pętli.

`.env` (gitignored, patrz `.env.example`):
```
AUTOMAT_URL=http://localhost:3000
AUTOMAT_TOKEN=<hex>
AUTOMAT_UPLOAD_ENABLED=true
```

## Znane problemy z aparatem

- **Zwis na „Łączę z aparatem…"** — Photos.app / Image Capture / Canon EOS Utility przejmują urządzenie. Zamknij przed startem.
- **`-53 Could not claim the USB device`** — macOS Sonoma+ ma daemona `ptpcamerad` (`/usr/libexec/ptpcamerad`, dawne `PTPCamera.app`) który auto-claimuje aparat PTP. `launchd` respawnuje go w ~100 ms po SIGTERM, więc jednokrotny `killall` nie wystarczy — daemon wraca zanim `gphoto2.camera.init()` skończy. `_PtpCameradReaper` w `src/camera.py` to wątek tła ubijający `ptpcamerad`/`PTPCamera` SIGKILL-em co 30 ms przez cały czas trwania `init()`. Po sukcesie init reaper się zatrzymuje — gphoto2 trzyma już handle, więc kolejny respawn ptpcamerad i tak nie złapie urządzenia. Jeśli mimo reapera leci -53: `ps aux | grep -iE 'ptp|canon'` (jakiś inny proces?), `ioreg -p IOUSB | grep -i canon` (kernel widzi aparat?), zamknij Photos/Image Capture/Canon EOS Utility, odepnij/podepnij kabel, na koniec restart Maca czyści kernel-level claim.
- **`-110 I/O in progress`** — najczęstsze:
  1. **Brak karty SD** (M50 II domyślnie nie strzeli bez karty). Włóż kartę lub ustaw „Release shutter w/o card: ON".
  2. Aparat dopiero pisze poprzednie zdjęcie — kod retry'uje `capture` 5×.
  3. Tryb ciągły / interwałometr / RAW na wolnej karcie.
- **Aparat pokazuje ciągle „BUSY"** — zawieszona sesja PTP (np. reaper ubił `ptpcamerad` w trakcie transakcji) albo zawieszka firmware'u. Kod przy trzecim `-110` z rzędu robi reset USB przez pyusb (odpowiednik wypięcia kabla) i re-init. Jeśli BUSY zostaje mimo tego: power-cycle włącznikiem, a gdy aparat nie reaguje na włącznik — wyjęcie baterii na ~10 s (jedyny „twardy reset" M50). Częsta przyczyna chronicznego BUSY: wolna/umierająca karta SD.
- **`-6 Unsupported operation`** — najczęstsze: aparat zasnął (auto power-off), poszedł do trybu odtwarzania, lub pokrętło na Auto+ / SCN / Movie. Power-cycle aparat, ustaw na M / Av / Tv / P / Fv. Historycznie też: **telefon podpięty do Maca** — iPhone/Android w trybie PTP enumeruje się jako aparat i goły `gp.Camera().init()` łapał pierwsze urządzenie z listy (telefon bywa pierwszy); objaw: „aparat nie eksponuje ('imageformat', …)" w logu + 5× -6 przy capture. Naprawione przez `_pick_canon_addr()` w `_init_camera()`: autodetect → filtr po nazwie „canon" → `set_port_info` pinuje port; inne urządzenia PTP logowane jako pomijane. Re-detect przy każdej próbie init, bo adres USB zmienia się po resecie portu.
- **`-1 Unspecified error`** — aparat nie zrobił zdjęcia z nieznanego powodu. Najczęstsze: tryb odtwarzania (Play), AF nie złapał ostrości (spróbuj MF), obiektyw niepoprawnie zamontowany („Err" na ekranie), lub aparat wymaga power-cycle. Kod retry'uje 5×.
- **Zdjęcia "obrócone" o 90°** — aparat wykrywa orientację czujnikiem grawitacji i pisze EXIF Orientation. Pipeline wyłącza to przez gphoto2 widget `autorotation` (`_disable_autorotation`). Pipeline NIE honoruje EXIF Orientation (świadomie — przy strzałach 3/4 nie chcemy, żeby zdjęcie się rotowało). Jeśli widget nie istnieje, ręcznie: Menu aparatu → Setup → Auto Rotate → Off.
- Stałe `GP_ERROR_UNSPECIFIED=-1`, `GP_ERROR_IO_IN_PROGRESS=-110`, `GP_ERROR_NOT_SUPPORTED=-6` zdefiniowane lokalnie w `src/camera.py` (python-gphoto2 ich nie eksportuje). `_RETRYABLE_CAPTURE_ERRORS` zbiera je w tuple.

## Wydajność

- u2netp: ~4,5 MB model, ~0.5s inference @ 768×768 na CPU (Apple Silicon, onnxruntime CPU).
- Pierwsze uruchomienie pobiera model do `~/.u2net/u2netp.onnx`.

## Zależności

`.venv` / `pip` (patrz `requirements.txt`):
- `gphoto2` (python-gphoto2)
- `Pillow`
- `rich`
- `numpy`, `scipy` (mask post-processing: label, sum_labels)
- `rembg`, `onnxruntime` (lokalny mask)
- `requests`, `python-dotenv` (upload do Automatu, ładowanie `.env`)
- `pyusb` (reset USB przy zawieszce -110/BUSY; wymaga libusb — jest już jako zależność gphoto2)

## Konwencje

- **Dwa frontendy, oba zawsze działają**: TUI (`main.py`, w tym ścieżka `--input`) i aplikacja okienkowa (`gui.py`) to równorzędne wersje — każda zmiana w pipeline, uploadzie czy flow sesji musi być wprowadzona w OBU (wspólną logikę wyciągaj do `src/`, np. `find_existing_session`/`attach_session` w `automat_uploader.py`).
- **Każda zmiana podbija wersję**: przed commitem podnieś `APP_VERSION` w `src/version.py` (patch przy poprawkach i drobiazgach, minor przy nowej funkcji) i zawrzyj to w tym samym commicie. Bez tego operator nie dostanie banera aktualizacji — updater porównuje `APP_VERSION` z tagiem wydania. Po wypchnięciu na `main`: `git tag v<APP_VERSION> && git push --tags` publikuje release z paczką (szczegóły w sekcji „Aktualizacje").
  - Wyjątek: gdy bieżące `APP_VERSION` **nie zostało jeszcze wydane** (nie ma takiego tagu — sprawdź `git tag -l` / `gh release list`), nie podbijaj — kolejna zmiana wchodzi do tego samego, jeszcze nieopublikowanego wydania. Podbicie przed tagiem rozjeżdża tag z `APP_VERSION`, a wtedy build z tagiem faila (krok „Verify tag matches APP_VERSION").
  - Zmiany, które nie trafiają do `.exe` (sam `CLAUDE.md`, `README.md`, `WINDOWS.md`), wersji nie ruszają.
- Komunikaty UI po polsku (rich panels, prompty, błędy).
- Nazwy folderów sanityzowane przez `sanitize_name()` w `src/naming.py` (regex: tylko `[A-Za-z0-9_\-. ]`).
- Kod komentowany minimalnie, nazwy funkcji opisowe.
- `gitignore`: `.venv/`, `photos/`, `__pycache__/`, `.DS_Store`.
