"use strict";
// Zakladka Ustawienia + akcje sprawdzania/instalacji aktualizacji.

// Sekcje Ustawień: nawigacja po lewej przewija do karty, a podświetlenie
// idzie za przewijaniem (settingsScrolled).
const SETTINGS_SECTIONS = [
  { id: "aktualizacje", label: "Aktualizacje", icon: "download" },
  { id: "automat", label: "API", icon: "cloud" },
  { id: "pliki", label: "Pliki", icon: "folder" },
  { id: "obrobka", label: "Podgląd i obróbka", icon: "sparkles" },
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
  const keys = [["ENTER", "zrób zdjęcie"], ["P", "podgląd z aparatu"], ["SPACJA", "podgląd zdjęć"], ["← →", "poprzednie / następne"],
                ["E", "edytuj zdjęcie"], ["BACKSPACE", "usuń zdjęcie"], ["ESC", "zamknij podgląd"], [modKey("F"), "szukaj sesji"], [modKey("N"), "nowa sesja"]];
  const navMeta = { aktualizacje: uv, automat: av };
  const nav = SETTINGS_SECTIONS.map(x => {
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
             <button type="button" class="mono" onclick="post({action:'open_url', url: 'https://github.com/${u.repo}'})" style="padding: 0; border: none; background: none; font-size: 12.5px; color: var(--text); cursor: pointer;">${(u.repo || "").replace("/", "/<b style='font-weight: 600;'>")}</b></button>`,
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
          ${cardHead(icon("cloud", 22), "background: rgba(37, 99, 235, .14); color: #2563eb;", "API",
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
          ${apiEndpoints()}
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
  ? `<div class="row-desc" style="grid-column: 1 / -1; margin: 0;">Bez tokenu nie widać sesji z API i zdjęcia się nie wysyłają. Token wygenerujesz w ustawieniach konta po stronie API.</div>` : "";

// Endpointy API, z których korzysta aplikacja (src/automat_uploader.py).
// Lista statyczna — zmiana klienta HTTP = zmiana tej tabeli.
const API_ENDPOINTS = [
  ["GET", "/sessions", "Lista sesji na ekranie startowym"],
  ["POST", "/sessions", "Nowa sesja (albo istniejąca o tej nazwie)"],
  ["GET", "/sessions/:id", "Zdjęcia sesji do pobrania przy wejściu"],
  ["GET", "/sessions/:id/photos/:photo_id/file", "Pobranie zdjęcia na dysk"],
  ["POST", "/sessions/:id/photos", "Zapowiedź zdjęcia zaraz po migawce, potem plik"],
  ["PUT", "/sessions/:id/photos/:photo_id", "Gotowy JPEG do zapowiedzianego zdjęcia"],
  ["DELETE", "/sessions/:id/photos/:photo_id", "Usunięcie zdjęcia (BACKSPACE)"],
];
const API_METHOD_STYLE = {
  GET: "color: var(--ok-fg); background: var(--ok-soft, rgba(34, 197, 94, .14));",
  POST: "color: #2563eb; background: rgba(37, 99, 235, .14);",
  PUT: "color: #a855f7; background: rgba(168, 85, 247, .14);",
  DELETE: "color: var(--err); background: rgba(239, 68, 68, .14);",
};

function apiEndpoints() {
  const rows = API_ENDPOINTS.map(([m, path, what]) => `
    <div style="display: contents;">
      <span class="mono" style="justify-self: start; padding: 2px 7px; border-radius: 5px; font-size: 10.5px; font-weight: 600; letter-spacing: .03em; ${API_METHOD_STYLE[m]}">${m}</span>
      <span class="mono" style="font-size: 12px; color: var(--text); overflow-wrap: anywhere;">${path}</span>
      <span style="font-size: 12.5px; color: var(--muted);">${what}</span>
    </div>`).join("");
  return `
    <div style="padding: 14px 20px 18px; border-top: 1px solid var(--hair); display: flex; flex-direction: column; gap: 10px;">
      <div class="row-title">Endpointy <span class="mono" style="font-weight: 400; font-size: 12px; color: var(--muted);">/api/photo_studio</span></div>
      <div style="display: grid; grid-template-columns: auto minmax(0, 1fr) minmax(0, 1.1fr); gap: 8px 14px; align-items: center;">${rows}</div>
    </div>`;
}

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
