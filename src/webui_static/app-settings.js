"use strict";
// Zakladka Ustawienia + akcje sprawdzania/instalacji aktualizacji.

function ustawieniaScreen() {
  const st = S.state, cfg = st.settings, u = st.update || {current: "?", status: ""};
  // Backend ustawia `checking` już w handlerze akcji, ale poll ma 500 ms —
  // `S.checkStartedAt` trzyma spinner od razu po kliknięciu (i minimum ~600 ms,
  // żeby szybka odpowiedź nie mignęła bez śladu).
  const checking = u.checking || (S.checkStartedAt && Date.now() - S.checkStartedAt < 600);
  const card = `display: flex; flex-direction: column; gap: 12px; background: var(--bg-2); border: 1px solid var(--line-2); border-radius: 6px; padding: 16px 18px;`;
  return `
    <div style="${card}">
      <div style="${head}">Pliki i katalogi</div>
      <div style="display: grid; grid-template-columns: 120px 1fr auto; gap: 8px 10px; align-items: center;">
        <div style="color: var(--fg-2);">Katalog zdjęć</div>
        <input value="${cfg.photosDir}" onchange="post({action:'set_app', key:'photos_dir', value:this.value})" style="${inp}" />
        <button style="${btnGray} height: 26px; padding: 0 10px; font-size: 11.5px;">Wybierz</button>
        <div style="color: var(--fg-2);">Plik logo</div>
        <input value="${cfg.logoPath}" onchange="post({action:'set_app', key:'logo_path', value:this.value})" style="${inp}" />
        <button style="${btnGray} height: 26px; padding: 0 10px; font-size: 11.5px;">Wybierz</button>
        <div style="color: var(--fg-2);">Wzór nazwy</div>
        <input value="${cfg.namePattern}" onchange="post({action:'set_app', key:'name_pattern', value:this.value})" style="${inp}" />
        <div></div>
      </div>
      <label style="${label}"><input type="checkbox" ${cfg.keepRaw ? "checked" : ""} onchange="post({action:'set_app', key:'keep_raw', value:this.checked})" style="${chk}" />Zachowaj oryginały w podkatalogu /raw</label>
    </div>

    <div style="${card}">
      <div style="${head}">Automat (aplikacja web)</div>
      <div style="display: grid; grid-template-columns: 120px 1fr; gap: 8px 10px; align-items: center;">
        <div style="color: var(--fg-2);">Adres API</div>
        <input value="${cfg.automatUrl}" onchange="post({action:'set_app', key:'automat_url', value:this.value})" style="${inp}" />
        <div style="color: var(--fg-2);">Token</div>
        <input value="${cfg.tokenMasked}" onchange="post({action:'set_app', key:'automat_token', value:this.value})" style="${inp}" />
      </div>
      <div style="display: flex; align-items: center; gap: 10px;">
        <button onclick="post({action:'test_connection'})" style="${btnGray} font-size: 11.5px;">Testuj połączenie</button>
        <span style="${mono} font-size: 10.5px; color: ${cfg.testResult.startsWith("✓") ? "var(--ok)" : "var(--warn)"};">${cfg.testResult}</span>
      </div>
    </div>

    <div style="${card}">
      <div style="${head}">Podgląd i obróbka</div>
      <div style="display: grid; grid-template-columns: 120px 1fr; gap: 8px 10px; align-items: center;">
        <div style="color: var(--fg-2);">FPS podglądu</div>
        <select onchange="post({action:'set_app', key:'preview_fps', value:this.value})" style="${sel}">
          ${[10, 15, 20, 25, 30].map(f => `<option ${f === cfg.previewFps ? "selected" : ""}>${f}</option>`).join("")}
        </select>
      </div>
      <label style="${label}"><input type="checkbox" ${cfg.cleanBgGpu ? "checked" : ""} onchange="post({action:'set_app', key:'clean_bg_gpu', value:this.checked})" style="${chk}" />Obróbka tła na GPU (DirectML)</label>
      <div style="${mono} font-size: 10.5px; color: var(--fg-4);">Wyłącz przy problemach ze sterownikami — obróbka pójdzie na CPU (wolniej, ale zawsze działa). Zmiana obowiązuje od następnego zdjęcia; po włączeniu pierwsza obróbka kompiluje shadery (~2 min).</div>
    </div>

    <div style="${card}">
      <div style="${head}">Wygląd</div>
      <div style="display: grid; grid-template-columns: 120px 1fr; gap: 8px 10px; align-items: center;">
        <div style="color: var(--fg-2);">Motyw</div>
        <div style="display: inline-flex; gap: 6px;">${themeButton("dark", "Ciemny", cfg.uiTheme)}${themeButton("light", "Jasny", cfg.uiTheme)}</div>
      </div>
      <div style="${mono} font-size: 10.5px; color: var(--fg-4);">Wybór zapisuje się w .env i przeżywa restart aplikacji.</div>
    </div>

    ${robotSetupCard(card)}

    <div style="${card}">
      <div style="${head}">Aktualizacje</div>
      <div style="display: grid; grid-template-columns: 120px 1fr; gap: 8px 10px; align-items: center;">
        <div style="color: var(--fg-2);">Wersja</div>
        <div style="${mono} font-size: 11.5px; color: var(--fg-1);">${u.current}</div>
      </div>
      <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">
        <button onclick="checkUpdate()" ${checking ? "disabled" : ""} style="${btnGray} font-size: 11.5px; display: inline-flex; align-items: center; gap: 7px; ${checking ? "opacity: .7;" : ""}">${checking ? `<span class="spinner"></span>Sprawdzam…` : "Sprawdź aktualizacje"}</button>
        ${u.available && u.canApply ? `<button onclick="applyUpdate()" ${u.busy ? "disabled" : ""} style="height: 26px; padding: 0 12px; ${btnBlue} border-radius: 4px; font-size: 11.5px; font-weight: 600; display: inline-flex; align-items: center; gap: 7px; ${u.busy ? "opacity: .6;" : ""}">${u.busy ? `<span class="spinner"></span>Aktualizuję…` : `Zainstaluj ${u.available}`}</button>` : ""}
        <span style="${mono} font-size: 10.5px; color: ${checking ? "var(--fg-3)" : u.status.startsWith("✗") ? "var(--err)" : u.available ? "var(--warn)" : "var(--ok)"};">${checking ? "Pytam GitHuba o najnowsze wydanie…" : u.status}</span>
      </div>
      ${u.available && !u.canApply ? `<div style="${mono} font-size: 10.5px; color: var(--fg-4);">Uruchomienie ze źródeł — aktualizacja przez <b>git pull</b>. Automatyczna podmiana działa tylko dla .exe na Windowsie.</div>` : ""}
      ${u.available && u.notes ? `<div style="${mono} font-size: 10.5px; color: var(--fg-4); white-space: pre-wrap; max-height: 96px; overflow: auto;">${u.notes}</div>` : ""}
    </div>

    <div style="display: flex; flex-direction: column; gap: 10px; background: var(--bg-2); border: 1px solid var(--line-2); border-radius: 6px; padding: 16px 18px;">
      <div style="${head}">Skróty klawiszowe</div>
      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 6px 18px; ${mono} font-size: 11px; color: var(--fg-2);">
        <div>ENTER — zdjęcie</div><div>P — podgląd on/off</div>
        <div>SPACJA — podgląd zdjęć na live view</div><div>← → — zmiana zdjęcia / nawigacja</div>
        <div>BACKSPACE — usuń oglądane zdjęcie</div><div>ESC — zamknij podgląd</div>
      </div>
    </div>`;
}

// Przełącznik motywu: aktywny wariant niebieski, drugi szary. Klik przestawia
// atrybut na <html> natychmiast (applyTheme w app-main.js) i dopiero potem
// zapisuje w backendzie — inaczej zmiana byłaby widoczna dopiero po pollu.
function themeButton(value, text, current) {
  const on = (current === "light" ? "light" : "dark") === value;
  const style = on
    ? `height: 26px; padding: 0 14px; ${btnBlue} border-radius: 4px; font-size: 11.5px; font-weight: 600;`
    : `${btnGray} font-size: 11.5px;`;
  return `<button onclick="setTheme('${value}')" style="${style}">${text}</button>`;
}

function setTheme(value) {
  applyTheme(value);
  if (S.state && S.state.settings) S.state.settings.uiTheme = value;
  post({action: "set_app", key: "ui_theme", value});
  renderScreens(true);
}

// Ustawianie ujęć ramienia. Cała „kalibracja" tego robota to zapisanie
// bieżących kątów przegubów — ujęcie jest jedną pozycją, więc nie ma tu czego
// mierzyć ani liczyć (patrz sekcja „Robot" w CLAUDE.md).
//
// Przepływ jest PER UJĘCIE: operator klika kafelek („Z góry" / „Z boku"),
// ramię jedzie na zapisane ujęcie (jeśli jest) i dopiero pod kafelkiem
// pojawia się korekta przyciskami, puszczanie serw i zapis. Wcześniej wiersze
// korekty wisiały zawsze, bez związku z żadnym ujęciem — nie było widać, CO się
// właściwie poprawia ani do którego ujęcia trafi zapis.
//
// Kolejność przy ujęciu od zera jest wypisana w UI: puszczone serwa oznaczają,
// że ramię opada pod ciężarem aparatu i trzeba je TRZYMAĆ. Dopiero po złapaniu
// momentu operator ma wolne ręce, żeby sprawdzić kadr na Sesji i kliknąć zapis.
const SETUP_POSES = { top90: "Z góry", a45: "Z boku" };

function robotSetupCard(card) {
  const r = (S.state && S.state.robot) || {};
  if (r.enabled === false) return "";
  const set = r.set || {};
  const line = `${mono} font-size: 10.5px; color: var(--fg-4);`;
  const sel = S.setupPose && SETUP_POSES[S.setupPose] ? S.setupPose : null;
  const tile = (p, name) => {
    const on = sel === p;
    const st = on
      ? `border: 1px solid ${ACCENT}; background: var(--accent-bg);`
      : `border: 1px solid var(--line); background: var(--card);`;
    return `
      <div onclick="robotSetupSelect('${p}')" style="display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 9px 12px; border-radius: 6px; cursor: default; ${st} ${r.connected ? "" : "opacity: .55;"}">
        <div style="font-size: 12.5px; font-weight: 600; color: var(--fg-0);">${name}</div>
        <div style="${mono} font-size: 11px; color: ${set[p] ? "var(--ok)" : "var(--warn)"};">${set[p] ? "ustawione" : "nieustawione"}</div>
      </div>`;
  };
  return `
    <div style="${card}">
      <div style="${head}">Robot — ujęcia</div>
      ${r.connected ? "" : `<div style="${line} color: var(--warn);">ramię rozłączone — sprawdź kabel USB i zasilanie</div>`}
      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 8px;">
        ${tile("top90", SETUP_POSES.top90)}
        ${tile("a45", SETUP_POSES.a45)}
      </div>
      ${sel ? robotSetupPanel(sel, r, line) : `<div style="${line}">Kliknij ujęcie, żeby je ustawić albo poprawić — ramię pojedzie na nie i pojawi się korekta.</div>`}
      <div id="robot-setup-msg" style="${mono} font-size: 10.5px; color: var(--err);">${S.setupMsg || ""}</div>
    </div>`;
}

// Panel pod wybranym ujęciem: korekta osi + puszczanie serw + zapis.
function robotSetupPanel(pose, r, line) {
  const set = (r.set || {})[pose];
  const dis = r.connected ? "" : "disabled";
  const off = r.connected ? "" : "opacity: .5;";
  const busy = r.busy ? `<div style="display: flex; align-items: center; gap: 7px; ${line} color: var(--warn-fg-2);"><span class="spinner"></span>${r.busy}…</div>` : "";
  const hint = set
    ? `Ramię stoi na ujęciu <b>${SETUP_POSES[pose]}</b>. Popraw przyciskami patrząc na podgląd na zakładce Sesja i kliknij <b>Zapisz</b>. Zgrubna zmiana: <b>Puść serwa</b> (PRZYTRZYMAJ ramię — z aparatem opada samo), ustaw z ręki, <b>Złap pozycję</b>.`
    : `Ujęcie <b>${SETUP_POSES[pose]}</b> nie jest jeszcze ustawione: <b>Puść serwa</b> i PRZYTRZYMAJ ramię (z aparatem opada samo), ustaw z ręki, <b>Złap pozycję</b>, dostrój przyciskami i kliknij <b>Zapisz</b>.`;
  return `
    ${busy}
    ${robotNudgeRows()}
    <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">
      <button onclick="robotSetupPost({action:'robot_torque', on:${r.loose ? "true" : "false"}})" ${dis} style="${btnGray} font-size: 11.5px; ${off}">${r.loose ? "Złap pozycję" : "Puść serwa"}</button>
      <button onclick="robotTeach('${pose}')" ${dis || (r.loose ? "disabled" : "")} style="height: 26px; padding: 0 14px; ${btnBlue} border-radius: 4px; font-size: 11.5px; font-weight: 600; ${off} ${r.loose ? "opacity: .5;" : ""}">Zapisz jako „${SETUP_POSES[pose]}”</button>
      <button onclick="robotSetupSelect(null)" style="${btnGray} font-size: 11.5px;">Zamknij</button>
    </div>
    <div style="${line}">${hint}</div>`;
}

// Klik w kafelek: wybór ujęcia + przejazd ramienia na nie (gdy jest zapisane).
// Ten sam klik drugi raz zamyka panel. Przejazd idzie zwykłą akcją
// `robot_pose`, więc odmowa (trwa zdjęcie, rozłączone) ląduje w komunikacie
// pod kartą jak każda inna.
function robotSetupSelect(pose) {
  if (pose === S.setupPose) pose = null;
  S.setupPose = pose;
  const r = (S.state && S.state.robot) || {};
  if (pose && (r.set || {})[pose] && r.connected) {
    S.robot.pose = pose;
    S.robot.echoAt = performance.now();
    robotSetupPost({ action: "robot_pose", pose: pose });
  }
  renderScreens(true);
}

// Korekta pozycji przyciskami. Ręką nie ustawi się ramienia z dokładnością do
// stopnia, a od tego zależy, czy produkt siedzi na środku kadru — więc każda
// oś ma własny wiersz i dwa kroki: mały do wykończenia, duży do dojechania.
// Nazwy osi są opisowe, bo „j2" nic nie mówi o tym, co się ruszy. Oś 5 to
// dodatkowe serwo pochylające kamerę (ROBOT_EXT_SERVO_ID) — wiersz pojawia się
// tylko, gdy backend mówi `axes: 5`.
const ROBOT_JOINT_NAMES = ["Obrót podstawy", "Bark (wysokość)", "Łokieć (wysięg)", "Głowica (obrót)", "Kamera (pochylenie)"];

function robotNudgeRows() {
  const r = (S.state && S.state.robot) || {};
  const j = r.joints, [small, big] = r.nudge || [1, 5];
  const locked = !r.connected || r.loose || !!r.busy;
  const b = `${btnGray} height: 24px; padding: 0 8px; font-size: 11px; ${locked ? "opacity: .5;" : ""}`;
  const row = i => `
    <div style="color: var(--fg-2);">${ROBOT_JOINT_NAMES[i]}</div>
    <div style="display: flex; align-items: center; gap: 5px;">
      <button onclick="robotNudge(${i + 1}, ${-big})" ${locked ? "disabled" : ""} style="${b}">−${big}</button>
      <button onclick="robotNudge(${i + 1}, ${-small})" ${locked ? "disabled" : ""} style="${b}">−${small}</button>
      <div style="${mono} font-size: 11px; color: var(--fg-1); min-width: 62px; text-align: center;">${j ? j[i].toFixed(1) + "°" : "—"}</div>
      <button onclick="robotNudge(${i + 1}, ${small})" ${locked ? "disabled" : ""} style="${b}">+${small}</button>
      <button onclick="robotNudge(${i + 1}, ${big})" ${locked ? "disabled" : ""} style="${b}">+${big}</button>
    </div>`;
  return `
    <div style="display: grid; grid-template-columns: 120px 1fr; gap: 6px 10px; align-items: center;">
      ${Array.from({ length: r.axes || 4 }, (_, i) => i).map(row).join("")}
    </div>
    ${r.loose ? `<div style="${mono} font-size: 10.5px; color: var(--warn);">serwa puszczone — PRZYTRZYMAJ ramię; korekta przyciskami i zapis zadziałają po „Złap pozycję"</div>` : ""}`;
}

function robotNudge(joint, delta) {
  robotSetupPost({ action: "robot_nudge", joint: joint, delta: delta });
}

// Odmowa z backendu (rozłączone ramię, puszczone serwa, trwa zdjęcie) MUSI być
// widoczna. Bez tego kliknięcie, które backend odrzucił, wyglądało dokładnie
// tak samo jak zepsuta komenda: „klikam i nic się nie dzieje".
// Komunikat siedzi w S.setupMsg, nie tylko w DOM: karta rebuilduje się przy
// każdej zmianie kątów (co ~1 s przy puszczonych serwach), więc wpisany
// wprost w element znikałby, zanim operator zdążył go przeczytać.
function robotSetupPost(payload) {
  post(payload).then(r => r.json()).then(res => {
    S.setupMsg = (res && res.ok === false) ? "✗ " + res.error : "";
    const el = $("robot-setup-msg");
    if (el) el.textContent = S.setupMsg;
  }).catch(() => {});
}

function robotTeach(pose) {
  robotSetupPost({ action: "robot_teach", pose: pose });
}

function checkUpdate() {
  S.checkStartedAt = Date.now();
  post({ action: "check_update" });
  renderScreens(true);
  // pod koniec minimalnego czasu spinnera przemaluj — poll mógł w tym czasie
  // przynieść już gotowy wynik, a klucz ekranu się wtedy nie zmienił
  setTimeout(() => { S.checkStartedAt = 0; renderScreens(true); }, 650);
}

// Backend pobiera paczke, zamyka aplikacje i odpala aktualizator (.exe z
// pobranej paczki), ktory podmienia pliki i uruchamia aplikacje z powrotem —
// okno zniknie samo.
function applyUpdate() {
  const u = S.state.update || {};
  if (!u.canApply || u.busy) return;
  post({ action: "apply_update" });
}
