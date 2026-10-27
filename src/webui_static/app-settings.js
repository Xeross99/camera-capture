"use strict";
// Zakladka Ustawienia + akcje sprawdzania/instalacji aktualizacji.

// Sekcje Ustawień: nawigacja po lewej przewija do karty, a podświetlenie
// idzie za przewijaniem (settingsScrolled).
const SETTINGS_SECTIONS = [
  { id: "aktualizacje", label: "Aktualizacje", icon: "download" },
  { id: "automat", label: "Automat", icon: "cloud" },
  { id: "pliki", label: "Pliki", icon: "folder" },
  { id: "obrobka", label: "Podgląd i obróbka", icon: "sparkles" },
  { id: "robot", label: "Robot", icon: "robot", robot: true },
  { id: "skroty", label: "Skróty klawiszowe", icon: "terminal" },
];

// Stan aktualizacji jako jeden obiekt: znaczek (klasa + tekst) i opis.
function updateView(st) {
  const u = st.update || {};
  const checking = u.checking || (S.checkStartedAt && Date.now() - S.checkStartedAt < 600);
  if (checking) return { cls: "", chip: "Sprawdzam…", nav: "sprawdzam…", spin: true };
  if ((u.status || "").startsWith("✗")) return { cls: "err", chip: "Błąd", nav: "błąd", text: u.status.slice(1).trim() };
  if (u.available) return { cls: "warn", chip: `Dostępna ${u.available}`, nav: `dostępna ${u.available}` };
  if (u.latest) return { cls: "ok", chip: "Aktualna", nav: "aktualna" };
  return { cls: "", chip: "", nav: "" };
}

function automatView(st) {
  const a = st.automat || {};
  if (!a.hasToken) return { cls: "warn", chip: "Brak tokenu", nav: "brak tokenu" };
  if (a.error) return { cls: "err", chip: "Brak połączenia", nav: "błąd" };
  return { cls: "ok", chip: `Połączono · ${a.sessions.length} ${plForm(a.sessions.length, "sesja", "sesje", "sesji")}`, nav: "połączono" };
}

const plDate = iso => { const d = new Date(iso); return isNaN(d) ? "" : plDay(d); };
function plWhen(ms) {
  if (!ms) return "jeszcze nie";
  const d = new Date(ms), t = new Date();
  const same = d.getFullYear() === t.getFullYear() && d.getMonth() === t.getMonth() && d.getDate() === t.getDate();
  return same ? `dziś, ${hhmm(d)}` : `${plDay(d)}, ${hhmm(d)}`;
}

const STATUS_CHIP = {
  ok: "background: var(--ok-soft); color: var(--ok-fg);",
  warn: "background: var(--warn-soft); color: var(--warn-fg-3);",
  err: "background: var(--err-soft); color: var(--err-fg);",
  "": "background: var(--seg); color: var(--muted);",
};
const statusChip = (v, spin = false) => !v.chip ? "" : `
  <span style="display: flex; align-items: center; gap: 6px; height: 28px; padding: 0 11px; border-radius: 14px; font-size: 12.5px; font-weight: 600; white-space: nowrap; ${STATUS_CHIP[v.cls]}">
    ${spin ? `<span class="spinner"></span>` : v.cls === "ok" ? icon("check", 14, 2.2) : `<span class="dot ${v.cls}" style="width: 7px; height: 7px;"></span>`}${v.chip}
  </span>`;

// Nagłówek karty: kolorowa ikona, tytuł, podtytuł i znaczek stanu po prawej.
const cardHead = (iconHtml, iconStyle, title, sub, right = "") => `
  <div style="display: flex; align-items: center; gap: 14px; padding: 18px 20px;">
    <span style="width: 44px; height: 44px; flex-shrink: 0; display: flex; align-items: center; justify-content: center; border-radius: 11px; ${iconStyle}">${iconHtml}</span>
    <div style="flex: 1; min-width: 0;">
      <h2 class="panel-title" style="font-size: 16px;">${title}</h2>
      <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap; margin-top: 4px; font-size: 13px; color: var(--muted);">${sub}</div>
    </div>
    ${right}
  </div>`;

const field = (id, labelText, value, action, extra = "") => `
  <div style="display: flex; flex-direction: column; gap: 6px; min-width: 0;">
    <label for="${id}" class="row-title">${labelText}</label>
    <input id="${id}" class="field" value="${String(value).replace(/"/g, "&quot;")}" onchange="${action}" />
    ${extra}
  </div>`;

function ustawieniaScreen() {
  const st = S.state, cfg = st.settings, u = st.update || { current: "?", status: "" };
  const uv = updateView(st), av = automatView(st);
  const robotOn = st.robot && st.robot.enabled;
  const keys = [["ENTER", "zrób zdjęcie"], ["P", "podgląd z aparatu"], ["SPACJA", "podgląd zdjęć"], ["← →", "poprzednie / następne"],
                ["E", "edytuj zdjęcie"], ["BACKSPACE", "usuń zdjęcie"], ["ESC", "zamknij podgląd"], [modKey("F"), "szukaj sesji"], [modKey("N"), "nowa sesja"]];
  const navMeta = { aktualizacje: uv, automat: av };
  const nav = SETTINGS_SECTIONS.filter(x => !x.robot || robotOn).map(x => {
    const m = navMeta[x.id];
    const metaColor = !m ? "var(--muted-2)" : m.cls === "ok" ? "var(--ok-fg)" : m.cls === "err" ? "var(--err-fg)" : m.cls === "warn" ? "var(--warn-fg-3)" : "var(--muted-2)";
    return `
      <button type="button" class="set-nav${(S.settingsSection || "aktualizacje") === x.id ? " on" : ""}" data-sec="${x.id}" onclick="settingsGo('${x.id}')">
        <span class="set-nav-icon">${icon(x.icon, 16)}</span>
        <span style="flex: 1; text-align: left;">${x.label}</span>
        ${m && m.nav ? `<span style="font-size: 11.5px; font-weight: 500; color: ${metaColor};">${m.nav}</span>` : ""}
      </button>`;
  }).join("");
  const releaseLink = u.latestPage
    ? `<button type="button" class="btn" onclick="post({action:'open_url', url: '${u.latestPage}'})" style="border-color: transparent; background: transparent;">Wydanie na GitHubie ${icon("external", 14, 1.8)}</button>` : "";
  return `
  <div style="height: 100%; display: flex;">
    <nav aria-label="Sekcje ustawień" style="width: 248px; flex: 0 0 248px; box-sizing: border-box; padding: 24px 14px 18px; border-right: 1px solid var(--border); background: var(--surface-2); display: flex; flex-direction: column; gap: 2px;">
      <div class="eyebrow" style="padding: 0 10px 10px;">Ustawienia</div>
      ${nav}
      <div style="flex: 1;"></div>
      <div class="brand-line">
        <span class="brand-item"><span class="tbx-mark" aria-hidden="true"></span>Trixbrix</span>
        <span class="brand-item"><img class="theme-light" src="/favicon.png" alt="" /><img class="theme-dark" src="/logo-cc-dark.png" alt="" />Camera Capture <span class="mono" style="color: var(--text-2);">${u.current}</span></span>
      </div>
      <button type="button" class="author" onclick="post({action:'open_url', url: 'https://github.com/Xeross99'})" title="Profil autora na GitHubie">
        <img src="/author" alt="" />
        <span style="flex: 1; min-width: 0; text-align: left;">
          <span style="display: block; font-size: 13px; font-weight: 600; color: var(--text);">Michał Krzysteczko</span>
          <span style="display: flex; align-items: center; gap: 5px; font-size: 12px; color: var(--muted-2);">${GITHUB_MARK.replace("width: 24px; height: 24px", "width: 12px; height: 12px")}Xeross99</span>
        </span>
        ${icon("external", 14, 1.8)}
      </button>
    </nav>

    <div id="settings-scroll" onscroll="settingsScrolled()" style="flex: 1; min-width: 0; overflow-y: auto; padding: 28px 40px 40px;">
      <div style="max-width: 820px; display: flex; flex-direction: column; gap: 20px;">

        <section id="sec-aktualizacje" class="panel" style="overflow: hidden;">
          ${cardHead(GITHUB_MARK, "background: #1d1d1f; color: #fff;", "Aktualizacje",
            `z GitHub Releases
             <button type="button" class="mono" onclick="post({action:'open_url', url: 'https://github.com/${u.repo}'})" style="padding: 0; border: none; background: none; font-size: 12.5px; color: var(--text); cursor: pointer;">${(u.repo || "").replace("/", "/<b style='font-weight: 600;'>")}</b></button>
             ${u.private ? `<span style="display: flex; align-items: center; gap: 4px; padding: 1px 7px; border: 1px solid var(--border-strong); border-radius: 10px; font-size: 11px; color: var(--muted);">${icon("lock", 11, 2)}prywatne</span>` : ""}`,
            statusChip(uv, uv.spin))}
          <div style="display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); border-top: 1px solid var(--hair);">
            <div style="padding: 14px 20px; border-right: 1px solid var(--hair);">
              <div class="row-desc" style="margin: 0;">Zainstalowana</div>
              <div class="mono" style="margin-top: 4px; font-size: 18px; font-weight: 500; color: var(--text);">${u.current}</div>
            </div>
            <div style="padding: 14px 20px; border-right: 1px solid var(--hair);">
              <div class="row-desc" style="margin: 0;">Najnowsze wydanie</div>
              <div style="margin-top: 4px; display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap;">
                <span class="mono" style="font-size: 18px; font-weight: 500; color: var(--text);">${u.latest ? "v" + u.latest : "—"}</span>
                <span style="font-size: 12px; color: var(--muted-2);">${plDate(u.latestDate)}</span>
              </div>
            </div>
            <div style="padding: 14px 20px;">
              <div class="row-desc" style="margin: 0;">Ostatnie sprawdzenie</div>
              <div style="margin-top: 4px; font-size: 14px; font-weight: 500; color: var(--text);">${plWhen(u.checkedAt)}</div>
            </div>
          </div>
          ${uv.text ? `<div style="padding: 10px 20px; border-top: 1px solid var(--hair); font-size: 12.5px; color: var(--err-fg);">${uv.text}</div>` : ""}
          ${u.available && !u.canApply ? `<div style="padding: 10px 20px; border-top: 1px solid var(--hair); font-size: 12.5px; color: var(--muted);">Uruchomienie ze źródeł: zaktualizuj przez <b>git pull</b>. Automatyczna podmiana działa tylko w .exe na Windowsie.</div>` : ""}
          ${u.available && u.notes ? `<div class="mono" style="padding: 10px 20px; border-top: 1px solid var(--hair); font-size: 11px; color: var(--muted); white-space: pre-wrap; max-height: 96px; overflow: auto;">${u.notes}</div>` : ""}
          <div style="display: flex; align-items: center; gap: 10px; padding: 12px 20px; border-top: 1px solid var(--hair); background: var(--surface-2);">
            <span style="flex: 1; font-size: 12.5px; color: var(--muted);">Aplikacja sprawdza też przy każdym starcie. Nowa wersja instaluje się jednym przyciskiem.</span>
            ${releaseLink}
            ${u.available && u.canApply ? `<button type="button" class="btn btn-primary" onclick="applyUpdate()" ${u.busy ? "disabled" : ""}>${u.busy ? `<span class="spinner" style="border-color: rgba(255,255,255,.35); border-top-color: #fff;"></span>Aktualizuję…` : `Zainstaluj ${u.available}`}</button>` : ""}
            <button type="button" class="btn" onclick="checkUpdate()" ${uv.spin ? "disabled" : ""}>${uv.spin ? `<span class="spinner"></span>` : icon("refresh", 15)}Sprawdź teraz</button>
          </div>
        </section>

        <section id="sec-automat" class="panel" style="overflow: hidden;">
          ${cardHead(`<img src="/brand-mark" alt="" style="width: 24px; height: 24px; display: block;" />`, "background: #131a33;", "Automat",
            `Sesje i wysyłka zdjęć · <span class="mono" style="font-size: 12.5px; color: var(--text);">${(cfg.automatUrl || "").replace(/^https?:\/\//, "")}</span>`,
            statusChip(av))}
          <div style="display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; padding: 14px 20px 18px; border-top: 1px solid var(--hair);">
            ${field("set-url", "Adres", cfg.automatUrl, "post({action:'set_app', key:'automat_url', value:this.value})")}
            <div style="display: flex; flex-direction: column; gap: 6px; min-width: 0;">
              <label for="set-token" class="row-title">Token</label>
              <div style="display: flex; gap: 8px;">
                <input id="set-token" class="field" value="${cfg.tokenMasked}" onchange="post({action:'set_app', key:'automat_token', value:this.value})" style="flex: 1;" />
                <button type="button" class="btn" onclick="post({action:'test_connection'})">Testuj</button>
              </div>
            </div>
            ${cfg.testResult ? `<div class="row-desc" style="grid-column: 1 / -1; margin: 0; color: ${cfg.testResult.startsWith("✓") ? "var(--ok-fg)" : "var(--warn-fg-3)"};">${cfg.testResult}</div>` : ""}
            ${a_noToken(st)}
          </div>
        </section>

        <section id="sec-pliki" class="panel" style="overflow: hidden;">
          ${cardHead(icon("folder", 22), "background: var(--warn-soft); color: var(--warn-fg-3);", "Pliki", "Gdzie lądują zdjęcia i jak się nazywają")}
          <div style="display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; padding: 14px 20px 18px; border-top: 1px solid var(--hair);">
            ${field("set-photos", "Katalog zdjęć", cfg.photosDir, "post({action:'set_app', key:'photos_dir', value:this.value})")}
            ${field("set-pattern", "Nazwa pliku", cfg.namePattern, "post({action:'set_app', key:'name_pattern', value:this.value})",
              `<div class="row-desc" style="margin: 0;">Pola: <span class="mono">{data}</span>, <span class="mono">{godzina}</span></div>`)}
          </div>
          <div class="row" style="padding: 14px 20px 18px;">
            <div style="flex: 1;">
              <div class="row-title">Zachowaj oryginały z aparatu</div>
              <div class="row-desc">Surowe zdjęcie zostaje obok gotowego, w podkatalogu /raw. Bez nich nie da się zmienić logo na starszych zdjęciach.</div>
            </div>
            ${switchHtml(cfg.keepRaw, "post({action:'set_app', key:'keep_raw', value: switchOn(this)})", "Zachowaj oryginały z aparatu")}
          </div>
        </section>

        <section id="sec-obrobka" class="panel" style="overflow: hidden;">
          ${cardHead(icon("sparkles", 22), "background: rgba(168, 85, 247, .14); color: #a855f7;", "Podgląd i obróbka", "Live view z aparatu i obróbka tła")}
          <div class="row" style="padding: 14px 20px;">
            <div style="flex: 1;">
              <div class="row-title">Klatki podglądu na sekundę</div>
              <div class="row-desc">Mniej, gdy USB gubi klatki.</div>
            </div>
            <div id="fps-seg" class="seg seg-sm has-pill" role="group" aria-label="Klatki na sekundę"><span class="seg-pill"></span>${[10, 15, 20, 25, 30].map(f => `<button type="button" class="seg-btn${f === cfg.previewFps ? " on" : ""}" aria-pressed="${f === cfg.previewFps}" onclick="segClick(this); setFps(${f})" style="font-family: 'IBM Plex Mono', monospace;">${f}</button>`).join("")}</div>
          </div>
          <div class="row" style="padding: 14px 20px 18px;">
            <div style="flex: 1;">
              <div class="row-title">Obróbka tła na karcie graficznej</div>
              <div class="row-desc">Szybciej. Wyłącz przy kłopotach ze sterownikami: obróbka pójdzie wolniej, ale zawsze zadziała. Po włączeniu pierwsza obróbka trwa do 2 minut.</div>
            </div>
            ${switchHtml(cfg.cleanBgGpu, "post({action:'set_app', key:'clean_bg_gpu', value: switchOn(this)})", "Obróbka tła na karcie graficznej")}
          </div>
        </section>

        ${robotOn ? `<div id="sec-robot">${robotSetupCard("background: var(--surface); border: 1px solid var(--border); border-radius: 14px; padding: 16px 20px; display: flex; flex-direction: column; gap: 12px;")}</div>` : ""}

        <section id="sec-skroty" class="panel" style="overflow: hidden;">
          ${cardHead(icon("terminal", 22), "background: var(--seg); color: var(--text-2);", "Skróty klawiszowe", "Wszystko da się zrobić z klawiatury")}
          <div style="display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px 24px; padding: 14px 20px 18px; border-top: 1px solid var(--hair);">
            ${keys.map(([k, w]) => `<div style="display: flex; align-items: center; gap: 10px; font-size: 13px;"><span class="keycap">${k}</span><span style="color: var(--text-2);">${w}</span></div>`).join("")}
          </div>
        </section>
      </div>
    </div>
  </div>`;
}

const a_noToken = st => (st.automat && !st.automat.hasToken)
  ? `<div class="row-desc" style="grid-column: 1 / -1; margin: 0;">Bez tokenu nie widać sesji z Automatu i zdjęcia się nie wysyłają. Token jest w Automacie, w ustawieniach konta.</div>` : "";

function settingsGo(id) {
  S.settingsSection = id;
  markSettingsNav(id);
  const el = $(`sec-${id}`);
  if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
}

function markSettingsNav(id) {
  document.querySelectorAll(".set-nav").forEach(b => b.classList.toggle("on", b.dataset.sec === id));
}

// Podświetlenie w nawigacji idzie za przewijaniem: aktywna jest ostatnia
// sekcja, której górna krawędź minęła górę przewijanego obszaru.
function settingsScrolled() {
  const box = $("settings-scroll");
  if (!box) return;
  const top = box.getBoundingClientRect().top + 40;
  let cur = SETTINGS_SECTIONS[0].id;
  SETTINGS_SECTIONS.forEach(x => {
    const el = $(`sec-${x.id}`);
    if (el && el.getBoundingClientRect().top <= top) cur = x.id;
  });
  if (box.scrollTop + box.clientHeight >= box.scrollHeight - 4) {
    const last = [...SETTINGS_SECTIONS].reverse().find(x => $(`sec-${x.id}`));
    if (last) cur = last.id;
  }
  if (cur !== S.settingsSection) {
    S.settingsSection = cur;
    markSettingsNav(cur);
  }
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

// Echo od razu w stanie: poll z tą samą wartością nie przebuduje ekranu
// w trakcie animacji przełącznika.
function setFps(f) {
  if (S.state && S.state.settings) S.state.settings.previewFps = f;
  post({ action: "set_app", key: "preview_fps", value: String(f) });
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
