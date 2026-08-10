"use strict";
const ACCENT = "#4a8cff";
const S = {           // stan klienta
  screen: "sesja", logOpen: false, state: null,
  selShot: -1,
  grid: 0, reviewMode: false, lastLogLen: -1,
  pendingNew: null,   // {name, match} — wpisana nazwa koliduje z istniejącą sesją Automatu
  updateDismissed: "",// wersja, dla której operator kliknął „Później"
  checkStartedAt: 0,  // klik w „Sprawdź aktualizacje" — minimalny czas spinnera
  dayFocus: "",       // podświetlony dzień na osi ekranu startowego
};
const $ = id => document.getElementById(id);
const post = (payload) => fetch("/api/action", { method: "POST", body: JSON.stringify(payload) });
const mono = "font-family: 'IBM Plex Mono', monospace;";
const sel = `height: 24px; background: #1a1a1d; border: 1px solid #3d3d44; border-radius: 4px; color: #eaeaee; ${mono} font-size: 11.5px; padding: 0 6px;`;
const inp = `height: 26px; background: #1a1a1d; border: 1px solid #3d3d44; border-radius: 4px; color: #eaeaee; padding: 0 8px; ${mono} font-size: 11px;`;
const btnGray = `height: 26px; padding: 0 12px; background: linear-gradient(#3f3f45, #35353a); border: 1px solid #4c4c54; border-radius: 4px; color: #eaeaee; font-size: 12px; font-family: inherit;`;
const btnBlue = `background: linear-gradient(#4a8cff, #2f72e8); border: 1px solid #2a63c9; color: #fff; font-family: inherit;`;
const chk = `accent-color: ${ACCENT}; width: 14px; height: 14px;`;
const label = `display: flex; align-items: center; gap: 8px; color: #dcdce1;`;
const head = `font-size: 11px; font-weight: 600; color: #8f8f97; letter-spacing: .06em; text-transform: uppercase;`;

// Wiersz opcji w sidebarze: checkbox, tytul i opis pod spodem, wiersze rozdzielone
// hairline'em. Sam checkbox z jednym slowem nie mowil, co wlasciwie robi.
// `extra` (np. wybor rogu logo) siedzi POZA <label>, inaczej klik w select
// przelaczalby checkbox.
const optionRow = (key, checked, title, desc, extra = "") => `
  <div class="opt-row">
    <label style="display: flex; align-items: flex-start; gap: 9px;">
      <input type="checkbox" ${checked ? "checked" : ""} onchange="toggle('${key}', this.checked)" style="${chk} margin-top: 1px; flex-shrink: 0;" />
      <span style="flex: 1; min-width: 0;">
        <span style="display: block; font-size: 12.5px; color: #eaeaee;">${title}</span>
        <span style="display: block; margin-top: 3px; font-size: 11.5px; line-height: 1.5; color: #85858e;">${desc}</span>
      </span>
    </label>
    ${extra ? `<div style="padding-left: 23px;">${extra}</div>` : ""}
  </div>`;
// Siatka kadrowania jak w aparacie (M50 II: 3×3 / 6×4). Domyślnie 6×4 — to
// samo, co operator widzi na ekranie aparatu. Klik w badge cykluje.
const GRIDS = [
  { cols: 6, rows: 4, label: "SIATKA 6×4" },
  { cols: 3, rows: 3, label: "SIATKA 3×3" },
  { cols: 0, rows: 0, label: "SIATKA OFF" },
];

/** Linie siatki jako gradienty CSS — ciemne, bo produktówka jest na bieli
 *  (poprzednia biała siatka na białym tle była po prostu niewidoczna).
 *
 *  Twarde stopy ±1px (linia 2px), nie rampa przez ułamek piksela: rampa
 *  transparent→kolor→transparent na szerokości 1px przy pozycjach
 *  ułamkowych (33.333% w 3×3) miała szczyt między fizycznymi pikselami
 *  i przeglądarka interpolowała ją do niewidzialności — poziome linie
 *  3×3 po prostu znikały. Twarda 2px linia zawsze pokrywa piksel. */
function gridBackground(cols, rows) {
  const line = "rgba(0, 0, 0, .3)";
  const parts = [];
  for (let i = 1; i < cols; i++) {
    const p = (100 * i / cols).toFixed(3);
    parts.push(`linear-gradient(to right, transparent calc(${p}% - 1px), ${line} calc(${p}% - 1px), ${line} calc(${p}% + 1px), transparent calc(${p}% + 1px))`);
  }
  for (let i = 1; i < rows; i++) {
    const p = (100 * i / rows).toFixed(3);
    parts.push(`linear-gradient(to bottom, transparent calc(${p}% - 1px), ${line} calc(${p}% - 1px), ${line} calc(${p}% + 1px), transparent calc(${p}% + 1px))`);
  }
  return parts.join(", ");
}

const MARKS = {
  ok:   { mark: "✓", color: "#9fe0a8", border: "#3a3a42" },
  bad:  { mark: "✕", color: "#e07a7a", border: "#5a3a3a" },
  cur:  { mark: "●", color: ACCENT,   border: ACCENT },
  wait: { mark: "…", color: "#e0b96a", border: "#3a3a42" },
};

// Baner aktualizacji nad zakladkami. Widoczny dopiero gdy backend znajdzie
// nowszy release; „Później" chowa go do konca uruchomienia (per wersja).
function updateBanner() {
  const u = S.state && S.state.update;
  if (!u || !u.available || S.updateDismissed === u.available) return "";
  const right = u.canApply
    ? `<button onclick="applyUpdate()" ${u.busy ? "disabled" : ""} style="height: 24px; padding: 0 12px; ${btnBlue} border-radius: 4px; font-size: 11.5px; font-weight: 600; display: inline-flex; align-items: center; gap: 7px; ${u.busy ? "opacity: .6;" : ""}">${u.busy ? `<span class="spinner"></span>Aktualizuję…` : "Zaktualizuj i uruchom ponownie"}</button>
       <button onclick="S.updateDismissed = '${u.available}'; renderShell(true)" style="${btnGray} height: 24px; padding: 0 10px; font-size: 11.5px; opacity: .75;">Później</button>`
    : `<span style="${mono} font-size: 11px; color: #d8c39a;">uruchomienie ze źródeł — zaktualizuj przez <b>git pull</b></span>
       <button onclick="S.updateDismissed = '${u.available}'; renderShell(true)" style="${btnGray} height: 24px; padding: 0 10px; font-size: 11.5px; opacity: .75;">Ukryj</button>`;
  return `
  <div style="flex: 0 0 auto; background: #2e2921; border-bottom: 1px solid #4d4126; display: flex; align-items: center; gap: 12px; padding: 7px 14px;">
    <span style="font-size: 12.5px; color: #f0e2c2;">Dostępna aktualizacja <b>${u.available}</b> <span style="${mono} font-size: 11px; color: #b9a888;">(masz ${u.current})</span></span>
    <span id="update-progress" style="${mono} font-size: 11px; color: #b9a888;">${u.busy && u.progress ? u.progress + "%" : ""}</span>
    <span style="margin-left: auto; display: flex; align-items: center; gap: 8px;">${right}</span>
  </div>`;
}

function shell() {
  const st = S.state;
  const conn = st && st.connected;
  const tab = k => S.screen === k ? "#f2f2f5" : "#9d9da3";
  const bar = k => S.screen === k ? ACCENT : "transparent";
  return `
<div style="width: 100%; height: 100%; background: #232326; overflow: hidden; display: flex; flex-direction: column; font-family: -apple-system, 'Helvetica Neue', Helvetica, sans-serif; color: #e8e8ea; font-size: 13px;">
  ${updateBanner()}

  <div style="height: 34px; flex: 0 0 34px; background: #2a2a2d; border-bottom: 1px solid #17171a; display: flex; align-items: stretch; padding: 0 10px; gap: 2px;">
    <div onclick="go('sesja')" style="display: flex; align-items: center; padding: 0 18px; font-size: 12.5px; font-weight: 500; cursor: default; color: ${tab("sesja")}; border-bottom: 2px solid ${bar("sesja")};">Sesja</div>
    <div onclick="go('ustawienia')" style="display: flex; align-items: center; padding: 0 18px; font-size: 12.5px; font-weight: 500; cursor: default; color: ${tab("ustawienia")}; border-bottom: 2px solid ${bar("ustawienia")};">Ustawienia</div>
    <div style="margin-left: auto; display: flex; align-items: center; gap: 14px; ${mono} font-size: 11px; color: #7e7e85;">
      <div>sesja: <span style="color: #c9c9cf;" id="stat-name">—</span></div>
      <div>zdjęć: <span style="color: #c9c9cf;" id="stat-count">0</span></div>
      <div style="display: flex; align-items: center; gap: 7px; font-family: -apple-system, 'Helvetica Neue', Helvetica, sans-serif; font-size: 11.5px; color: #9d9da3;">
        <div style="width: 7px; height: 7px; border-radius: 50%; background: ${conn ? "#34c759" : "#e05a5a"};"></div><span id="conn-label">${conn ? `Aparat połączony · ${st.fps} fps` : "Aparat rozłączony"}</span>
      </div>
    </div>
  </div>

  <div id="screen-sesja" style="flex: 1; display: ${S.screen === "sesja" ? "flex" : "none"}; min-height: 0;"></div>
  <div id="screen-ustawienia" style="flex: 1; display: ${S.screen === "ustawienia" ? "grid" : "none"}; overflow: auto; background: #1d1d20; padding: 24px 28px; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 24px; align-content: start;"></div>
</div>`;
}

// ---------- ekran startowy (lista sesji, układ jak Photo Studio w Automacie) ----------

const PL_MONTHS = ["stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca",
  "lipca", "sierpnia", "września", "października", "listopada", "grudnia"];
const plForm = (n, one, few, many) =>
  n === 1 ? one : (n % 10 >= 2 && n % 10 <= 4 && !(n % 100 >= 12 && n % 100 <= 14) ? few : many);
const plSessions = n => `${n} ${plForm(n, "sesja zdjęciowa", "sesje zdjęciowe", "sesji zdjęciowych")}`;
const plPhotos = n => `${n} ${plForm(n, "zdjęcie", "zdjęcia", "zdjęć")}`;
const plDay = d => `${d.getDate()} ${PL_MONTHS[d.getMonth()]} ${d.getFullYear()}`;
const hhmm = d => `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
const fmtDate = iso => {
  const d = new Date(iso);
  return isNaN(d) ? "" : `${String(d.getDate()).padStart(2, "0")}.${String(d.getMonth() + 1).padStart(2, "0")} ${hhmm(d)}`;
};
const CAM_ICON = `<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" style="width: 12px; height: 12px; display: block;"><path d="M12 9a3.75 3.75 0 1 0 0 7.5A3.75 3.75 0 0 0 12 9Z" /><path fill-rule="evenodd" clip-rule="evenodd" d="M9.344 3.071a49.5 49.5 0 0 1 5.312 0c.967.052 1.83.585 2.332 1.39l.821 1.317c.24.383.645.643 1.11.71.386.054.77.113 1.152.177 1.432.239 2.429 1.493 2.429 2.909V18a3 3 0 0 1-3 3h-15a3 3 0 0 1-3-3V9.574c0-1.416.997-2.67 2.429-2.909.382-.064.766-.123 1.151-.178a1.56 1.56 0 0 0 1.11-.71l.822-1.315a2.94 2.94 0 0 1 2.332-1.39ZM6.75 12.75a5.25 5.25 0 1 1 10.5 0 5.25 5.25 0 0 1-10.5 0Z" /></svg>`;

/** Sesje z Automatu (posortowane od najnowszej) → grupy po dniu. */
function groupByDay(sessions) {
  const groups = [];
  const byKey = {};
  sessions.forEach(s => {
    const d = new Date(s.created_at);
    const key = isNaN(d) ? "brak-daty"
      : `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    if (!byKey[key]) {
      byKey[key] = { key, date: d, items: [] };
      groups.push(byKey[key]);
    }
    byKey[key].items.push(s);
  });
  return groups;
}

function sessionCard(s) {
  // okładkę robi backend (photos/.covers) — dopóki jej nie ma, kafelek pokazuje
  // szkielet i wypełni się sam przy kolejnym poll-u
  const cover = s.cover
    ? `<img src="/img?cover=${s.id}" style="position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain;" />`
    : `<div class="${s.photos_count ? "skeleton" : ""}" style="position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; ${mono} font-size: 10px; color: #9a9aa2;">${s.photos_count ? "" : "bez zdjęć"}</div>`;
  const sub = s.product
    ? `<span style="color: #9fe0a8;">${s.product.name}</span>`
    : `<span style="color: #8f8f97;">Sesja luźna</span>`;
  const d = new Date(s.created_at);
  return `
  <div onclick='pickSession(${s.id}, ${JSON.stringify(s.name)})' style="background: #232326; border: 1px solid #2f2f35; border-radius: 8px; overflow: hidden; cursor: default; display: flex; flex-direction: column;"
       onmouseover="this.style.borderColor='${ACCENT}'" onmouseout="this.style.borderColor='#2f2f35'">
    <div style="position: relative; aspect-ratio: 4 / 3; background: #f4f4f6;">${cover}</div>
    <div style="padding: 9px 12px 11px; display: flex; flex-direction: column; gap: 3px; min-width: 0;">
      <div style="font-size: 13px; font-weight: 600; color: #e8e8ea; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${s.name}</div>
      <div style="font-size: 11.5px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${sub}</div>
      <div style="${mono} font-size: 10.5px; color: #6c6c74;">${plPhotos(s.photos_count)}${isNaN(d) ? "" : ` · ${hhmm(d)}`}</div>
    </div>
  </div>`;
}

function dayRail(groups) {
  const items = groups.map(g => {
    const on = S.dayFocus === g.key;
    return `
    <div onclick="focusDay('${g.key}')" style="display: flex; align-items: center; gap: 10px; padding: 5px 6px; border-radius: 6px; position: relative; cursor: default;">
      <div style="width: 22px; height: 22px; flex: 0 0 22px; border-radius: 50%; display: flex; align-items: center; justify-content: center; z-index: 1; color: ${on ? "#fff" : "#8f8f97"}; background: ${on ? ACCENT : "#2b2b31"}; border: 1px solid ${on ? ACCENT : "#3a3a42"};">${CAM_ICON}</div>
      <div style="min-width: 0;">
        <div style="font-size: 12px; color: ${on ? ACCENT : "#c9c9cf"}; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;">${isNaN(g.date) ? "bez daty" : plDay(g.date)}</div>
        <div style="${mono} font-size: 10px; color: #77777f; white-space: nowrap;">${plSessions(g.items.length)}</div>
      </div>
    </div>`;
  }).join("");
  return `
  <div style="position: relative; display: flex; flex-direction: column; gap: 2px;">
    <div style="position: absolute; left: 17px; top: 16px; bottom: 16px; width: 1px; background: #2f2f35;"></div>
    ${items}
  </div>`;
}

function focusDay(key) {
  S.dayFocus = key;
  // NAJPIERW rebuild (podświetlenie dnia), dopiero potem scroll — odwrotna
  // kolejność gubi przewinięcie: rebuild odtwarza zapamiętaną pozycję
  // przewijania `#start-scroll` i cofa to, co przed chwilą zrobił scrollIntoView
  renderScreens(true);
  const el = $(`day-${key}`);
  if (el) el.scrollIntoView({ behavior: "smooth", block: "start" });
}

function startScreen() {
  const a = S.state.automat;
  const groups = groupByDay(a.sessions);
  const feed = groups.map(g => `
    <div id="day-${g.key}" style="display: flex; flex-direction: column; gap: 12px; scroll-margin-top: 6px;">
      <div style="display: flex; align-items: baseline; gap: 8px;">
        <div style="font-size: 13px; font-weight: 600; color: #d6d6db;">${isNaN(g.date) ? "bez daty" : plDay(g.date)}</div>
        <div style="${mono} font-size: 10.5px; color: #77777f;">· ${plSessions(g.items.length)}</div>
      </div>
      <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 14px; align-content: start;">
        ${g.items.map(sessionCard).join("")}
      </div>
    </div>`).join("");
  const info = !a.hasToken
    ? `<div style="${mono} font-size: 11px; color: #e0b96a;">Brak tokenu Automatu (.env / Ustawienia) — sesje z Automatu niedostępne, możesz utworzyć lokalną.</div>`
    : a.error
      ? `<div style="${mono} font-size: 11px; color: #e07a7a;">✗ ${a.error}</div>`
      : a.sessions.length === 0
        ? `<div style="${mono} font-size: 11px; color: #7e7e85;">Ładuję sesje z Automatu…</div>`
        : "";
  const p = S.pendingNew;
  const pend = !p ? "" : `
    <div style="background: #26231d; border: 1px solid #5a4a2a; border-radius: 6px; padding: 12px 14px; display: flex; flex-direction: column; gap: 10px;">
      <div style="font-size: 12.5px; color: #e8e8ea;">Sesja <b>${p.match.name}</b> już istnieje w Automacie (${fmtDate(p.match.created_at)}, zdjęć: ${p.match.photos_count}).</div>
      <div style="display: flex; gap: 8px; flex-wrap: wrap;">
        <button onclick="resolvePending(true)" style="height: 28px; padding: 0 14px; ${btnBlue} border-radius: 4px; font-size: 12px; font-weight: 600;">Podłącz do istniejącej</button>
        <button onclick="resolvePending(false)" style="${btnGray} height: 28px;">Utwórz nową</button>
        <button onclick="S.pendingNew = null; renderScreens(true)" style="${btnGray} height: 28px; opacity: .7;">Anuluj</button>
      </div>
    </div>`;
  return `
  <div style="flex: 1; display: flex; min-width: 0; background: #1d1d20;">

    <div style="flex: 0 0 216px; border-right: 1px solid #26262b; padding: 22px 12px 22px 18px; overflow: auto;">
      <div style="${head} padding: 0 6px 10px;">Dni zdjęciowe</div>
      ${dayRail(groups)}
    </div>

    <div id="start-scroll" style="flex: 1; overflow: auto; padding: 22px 26px 28px; display: flex; flex-direction: column; gap: 20px; min-width: 0;">
      <div style="display: flex; flex-direction: column; gap: 8px;">
        <div style="display: flex; align-items: center; gap: 10px;">
          <div style="${head}">Nowa sesja zdjęciowa</div>
          <button onclick="post({action: 'refresh_sessions'})" style="${btnGray} height: 22px; padding: 0 10px; font-size: 11px;">Odśwież listę</button>
          ${info}
        </div>
        <div style="display: flex; gap: 8px; max-width: 560px;">
          <input id="new-session-input" placeholder="nazwa produktu…" style="flex: 1; ${inp} font-size: 12px; height: 32px;" />
          <button onclick="commitNewSession()" style="height: 32px; padding: 0 18px; ${btnBlue} border-radius: 5px; font-size: 12.5px; font-weight: 600;">Utwórz i otwórz</button>
        </div>
        <div style="${mono} font-size: 10.5px; color: #77777f;">nazwa = folder w photos/ i sesja w Automacie (dopasowanie do produktu po nazwie)</div>
        ${pend}
      </div>
      ${feed}
    </div>
  </div>`;
}

function commitNewSession() {
  const el = $("new-session-input");
  const v = el && el.value.trim();
  if (!v) return;
  const clean = v.replace(/[^A-Za-z0-9_\-. ]/g, "").trim().toLowerCase();  // jak sanitize_name() w backendzie
  const match = (S.state.automat.sessions || [])
    .filter(s => (s.name || "").trim().toLowerCase() === clean)
    .sort((a, b) => new Date(b.created_at) - new Date(a.created_at))[0];
  if (match) {
    S.pendingNew = { name: v, match };
    renderScreens(true);
    return;
  }
  post({ action: "set_session", name: v });
}

function pickSession(id, name) {
  S.pendingNew = null;
  post({ action: "set_session", name, session_id: id });
}

function resolvePending(attach) {
  const p = S.pendingNew;
  S.pendingNew = null;
  if (!p) return;
  if (attach) post({ action: "set_session", name: p.match.name, session_id: p.match.id });
  else post({ action: "set_session", name: p.name });
}

function sesjaScreen() {
  const st = S.state, post_ = st.post, cam = st.camera;
  // Sam <img> musi zniknąć przy rozłączeniu: MJPEG zostawia ostatnią odebraną
  // klatkę na ekranie, więc backend może przestać nadawać, a obraz i tak wisi
  // — status mówiłby „rozłączony" nad żywo wyglądającym podglądem.
  const liveOn = st.previewOn && st.connected;
  const grid = GRIDS[S.grid % GRIDS.length];
  const bgColor = histColor(st);
  const histText = histLabel(st);
  const badge = `background: rgba(0,0,0,.55); border: 1px solid #3c3c44; padding: 3px 8px; ${mono} font-size: 10.5px; color: #d0d0d6;`;
  return `
    <div style="flex: 1; display: flex; flex-direction: column; min-width: 0; background: #161618;">
      <div style="flex: 1; display: flex; align-items: center; justify-content: center; min-height: 0; position: relative; padding: 14px;">
        <div style="height: 100%; aspect-ratio: 3 / 2; background: repeating-linear-gradient(135deg, #202024 0 10px, #26262b 10px 20px); border: 1px solid #34343a; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px; position: relative;">
          ${liveOn ? `<img id="live" src="/stream" style="position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain;" />` : ""}
          <div style="${mono} font-size: 12px; color: ${st.connected ? "#8b8b93" : "#e07a7a"}; letter-spacing: .04em;">${st.connected ? "live view — 1024 × 683" : "aparat rozłączony"}</div>
          <div style="${mono} font-size: 11px; color: #63636b;">${!st.connected ? "sprawdź kabel i tryb aparatu — łączę ponownie…" : st.previewOn ? "czekam na klatki z aparatu…" : "podgląd wyłączony (P)"}</div>
          <div id="grid-overlay" style="position: absolute; inset: 0; display: ${grid.cols && liveOn ? "block" : "none"}; background: ${gridBackground(grid.cols, grid.rows)};"></div>
          <div style="position: absolute; left: 12px; top: 12px; display: flex; gap: 6px;">
            <div onclick="cycleGrid()" style="${badge} ${grid.cols ? "" : "opacity: .45;"}">${grid.label}</div>
          </div>
          ${st.previewOn && st.connected ? `
          <div style="position: absolute; right: 12px; top: 12px; display: flex; align-items: center; gap: 6px; background: rgba(0,0,0,.55); border: 1px solid #3c3c44; padding: 3px 8px; ${mono} font-size: 10.5px; color: #d0d0d6;">
            <div style="width: 7px; height: 7px; border-radius: 50%; background: #ff4d4d; animation: livePulse 1.6s ease-in-out infinite;"></div>LIVE
          </div>` : ""}
          <div id="hist-badge" title="${histTitle(st)}" style="position: absolute; right: 12px; bottom: 12px; background: rgba(0,0,0,.55); border: 1px solid #3c3c44; padding: 3px 8px; ${mono} font-size: 10.5px; color: ${bgColor};">${histText}</div>
          <div id="flash" style="position: absolute; inset: 0; background: #fff; opacity: 0; pointer-events: none; z-index: 4;"></div>
        </div>
      </div>

      <div style="flex: 0 0 auto; border-top: 1px solid #2c2c31; background: #1d1d20; padding: 10px 14px 12px;">
        <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
          <div style="font-size: 11.5px; font-weight: 600; color: #b6b6bd; letter-spacing: .03em; text-transform: uppercase;">Zdjęcia w sesji</div>
          <div style="display: flex; gap: 14px; ${mono} font-size: 10.5px; color: #7e7e85;">
            <div>SPACJA podgląd</div><div>← → wybór</div><div>BACKSPACE usuń</div><div>ESC zamknij</div>
          </div>
        </div>
        <div id="filmstrip" style="display: flex; gap: 8px; overflow-x: auto; overflow-y: hidden;">${filmstrip()}</div>
      </div>

      <div style="flex: 0 0 auto; border-top: 1px solid #2c2c31; background: #191a1c;">
        <div onclick="S.logOpen = !S.logOpen; renderScreens()" style="display: flex; align-items: center; gap: 10px; padding: 8px 14px; ${mono} font-size: 11px; color: #a8a8af;">
          <span style="color: #6a6a72;">${S.logOpen ? "▾" : "▸"}</span>
          <span id="log-line" style="flex: 1; display: flex; gap: 10px; align-items: center; overflow: hidden;">${lastLogLine()}</span>
          <span style="color: #6a6a72;">log</span>
        </div>
        <div id="log-panel" style="display: ${S.logOpen ? "block" : "none"}; border-top: 1px solid #2c2c31; background: #101012; padding: 10px 14px; ${mono} font-size: 11px; line-height: 1.7; color: #b9b9c0; max-height: 128px; overflow: auto;">${logLines()}</div>
      </div>
    </div>

    <div style="flex: 0 0 380px; background: #232326; border-left: 1px solid #17171a; display: flex; flex-direction: column; min-height: 0;">
      <div style="flex: 1; overflow: auto; padding: 16px 16px 8px; display: flex; flex-direction: column; gap: 18px;">

        <div style="display: flex; flex-direction: column; gap: 8px;">
          <nav aria-label="Breadcrumb" style="display: flex;">
            <ol role="list" style="display: flex; align-items: center; gap: 8px; margin: 0; padding: 0; list-style: none;">
              <li style="display: flex;">
                <a href="#" class="crumb" onclick="leaveSession(); return false;" style="${mono} font-size: 11px;">Camera Capture</a>
              </li>
              <li style="display: flex; align-items: center; gap: 8px; min-width: 0;">
                <svg viewBox="0 0 20 20" fill="currentColor" aria-hidden="true" style="width: 15px; height: 15px; flex-shrink: 0; color: #45454d;">
                  <path d="M5.555 17.776l8-16 .894.448-8 16-.894-.448z" />
                </svg>
                <span aria-current="page" style="${mono} font-size: 11px; color: #b4b4bb; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${st.session.name}</span>
              </li>
            </ol>
          </nav>
          <div style="display: flex; align-items: center; gap: 12px;">
            <h2 style="flex: 1; min-width: 0; margin: 0; font-size: 19px; font-weight: 600; color: #eaeaee; letter-spacing: -.01em; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${st.session.name}</h2>
            <button onclick="leaveSession()" style="flex-shrink: 0; height: 28px; padding: 0 12px; background: linear-gradient(#4a4a50, #3d3d43); border: 1px solid #55555d; border-radius: 4px; color: #eaeaee; font-size: 12px; font-family: inherit;">Wróć</button>
          </div>
          <div style="margin-top: 6px; border-top: 1px solid #2f2f35;"></div>
        </div>

        <div class="card">
          <div class="card-title">Ekspozycja</div>
          <div class="card-desc">Jasność zdjęcia, ustawiana zanim ono powstanie.</div>
          <div class="card-rule"></div>
          <div class="opt-row" style="display: flex; align-items: flex-start; gap: 12px;">
            <div style="flex: 1; min-width: 0;">
              <div style="font-size: 12.5px; color: #eaeaee;">Kompensacja ekspozycji</div>
              <div id="ev-hint" style="margin-top: 3px; font-size: 11.5px; line-height: 1.5; color: #85858e;">${evHint(st)}</div>
            </div>
            <div style="flex-shrink: 0; display: flex; align-items: center; background: #17171a; border: 1px solid #3d3d44; border-radius: 5px; overflow: hidden; ${mono} font-size: 12px;">
              <span id="ev-minus" onclick="stepEv(-1)" style="padding: 5px 11px; color: #d0d0d6; opacity: ${cam.ev ? 1 : .35};">−</span>
              <span id="ev-value" style="min-width: 44px; padding: 5px 0; text-align: center; color: #eaeaee; border-left: 1px solid #3d3d44; border-right: 1px solid #3d3d44;">${cam.ev ? evLabel(cam.ev.current) : "—"}</span>
              <span id="ev-plus" onclick="stepEv(1)" style="padding: 5px 11px; color: #d0d0d6; opacity: ${cam.ev ? 1 : .35};">+</span>
            </div>
          </div>
        </div>

        <div class="card">
          <div class="card-title">Postprocessing</div>
          <div class="card-desc">Każde zdjęcie przechodzi przez zaznaczone kroki zaraz po zrobieniu.</div>
          <div class="card-rule"></div>
          ${optionRow("logo", post_.logo, "Nakładanie logo",
                      "Znak wodny TRIXBRIX.eu w rogu kadru.",
                      `<div style="display: flex; align-items: center; gap: 10px; margin-top: 8px;">
                         <span style="font-size: 11.5px; color: #b4b4bb;">Pozycja</span>
                         <select onchange="post({action:'set_post', key:'logo_position', value:this.value})" style="${sel}">
                           ${post_.logoPositions.map(p => `<option ${p === post_.logoPosition ? "selected" : ""}>${p}</option>`).join("")}
                         </select>
                       </div>`)}
          ${optionRow("zoom", post_.zoom, "Przybliżanie",
                      "Kadr dociąga się do produktu — bez tego zostaje naturalna skala z klatki.")}
          ${optionRow("center", post_.center, "Centrowanie",
                      "Produkt ląduje na środku kadru zamiast tam, gdzie wypadł na stole.")}
          ${optionRow("cleanbg", post_.cleanBg, "Wyrównanie tła do bieli",
                      "Tło dociągane do czystej bieli, cienie pod produktem wygaszane.")}
        </div>

      </div>

      <div style="flex: 0 0 auto; border-top: 1px solid #17171a; background: #26262a; padding: 12px 16px 14px;">
        <button onclick="shoot()" style="width: 100%; height: 44px; ${btnBlue} border-radius: 6px; font-size: 14px; font-weight: 600; display: flex; align-items: center; justify-content: center; gap: 10px;"><span id="shoot-label">${st.busy || "Zrób zdjęcie"}</span> <span style="${mono} font-size: 11px; opacity: .75;">ENTER</span></button>
      </div>
    </div>

    <div id="review-slot">${reviewOverlay()}</div>`;
}

// Badge jasności tła: percentyle 10/90 z pasków przy krawędziach klatki.
// Zakres 230–254 = biel jest biała, ale jeszcze nie przepalona. Liczby są
// pokazywane wprost — samo „HISTOGRAM !" nie mówiło, co właściwie jest nie tak.
// Po rozłączeniu nie ma z czego liczyć: badge musi zgasnąć, a nie zostać
// z ostatnim odczytem, bo wygląda wtedy jak żywy pomiar.
// Badge jasnosci tla mowi operatorowi, co ma zrobic — nie jakie sa liczby.
// Wczesniej stalo tam „TŁO 255–255 · celuj w 230–254": zrozumiale dla kogos,
// kto wie, ze to poziomy bieli, i dla nikogo wiecej. Zmierzone wartosci
// zostaly w tooltipie.
const BG_LABEL = {
  ok: "TŁO OK",
  dark: "TŁO ZA CIEMNE · rozjaśnij w aparacie",
  unknown: "TŁO —",
};
const BG_COLOR = { ok: "#9fe0a8", dark: "#e0b96a", unknown: "#6c6c74" };

// Kompensacja ekspozycji. Backendy mówią różnymi słowami: „+2 2/3" (EDSDK),
// „+3.0" (digiCamControl), „0.3" (gphoto2) — a bywa, że odczyt bieżącej
// wartości i lista kroków są w RÓŻNYCH zapisach w obrębie jednego aparatu.
// Dlatego liczymy na liczbach, a nie na tekście: `+` idzie do najbliższej
// wartości WIĘKSZEJ, `−` do najbliższej mniejszej. Poprzednia wersja szukała
// bieżącej wartości w liście przez `indexOf` i przy niedopasowanym zapisie
// dostawała -1, czyli „zacznij od początku listy" — stąd `+` z +3.0 lądujące
// na +2 2/3, czyli przycisk plus zmniejszający ekspozycję.
function evNumber(v) {
  let s = String(v == null ? "" : v).trim().replace(/−/g, "-").replace(/^\+/, "");
  if (!s) return null;
  let sign = 1;
  if (s[0] === "-") { sign = -1; s = s.slice(1).trim(); }
  let total = 0, seen = false;
  for (const part of s.split(/\s+/)) {
    const frac = part.match(/^(\d+)\/(\d+)$/);
    if (frac && +frac[2] !== 0) { total += (+frac[1]) / (+frac[2]); seen = true; continue; }
    if (/^\d+(\.\d+)?$/.test(part)) { total += parseFloat(part); seen = true; continue; }
    return null;   // nieznany zapis — lepiej nie zgadywać niż zgadnąć źle
  }
  return seen ? sign * total : null;
}

function evLabel(v) {
  const s = String(v == null ? "" : v).trim();
  if (!s) return "—";
  if (s === "0" || s === "0.0" || s === "±0") return "±0";
  return /^[-+−]/.test(s) ? s : "+" + s;
}

// Kontrolka jest widoczna ZAWSZE, tylko wyszarzona gdy nie ma czego ustawiać, a
// powód stoi wprost pod nią. Znikająca kontrolka nie mówi operatorowi, czego
// szukać ani dlaczego jej nie ma — a tooltip trzeba najpierw znaleźć myszą.
function evHint(st) {
  if (!st.connected) return "Aparat rozłączony.";
  if (!(st.camera && st.camera.ev))
    return "Niedostępna w tym trybie aparatu — ustaw pokrętło na P, Av albo Tv.";
  return "Plus rozjaśnia zdjęcia, minus przyciemnia.";
}

function stepEv(dir) {
  const ev = S.state.camera && S.state.camera.ev;
  if (!ev || !ev.choices || !ev.choices.length) return;
  // sortujemy po wartości, nie ufamy kolejności listy z aparatu — bywa malejąca
  const opts = ev.choices
    .map(c => ({ c, n: evNumber(c) }))
    .filter(o => o.n !== null)
    .sort((a, b) => a.n - b.n);
  if (!opts.length) return;
  const cur = evNumber(ev.current);
  const eps = 1e-6;
  let hit;
  if (cur === null) hit = opts.find(o => Math.abs(o.n) < eps) || opts[0];
  else if (dir > 0) hit = opts.find(o => o.n > cur + eps) || opts[opts.length - 1];
  else hit = [...opts].reverse().find(o => o.n < cur - eps) || opts[0];
  const next = hit && hit.c;
  if (!next || next === ev.current) return;
  // Pokazujemy nową wartość od razu, ale źródłem prawdy jest aparat: jeśli
  // odrzuci wartość, najbliższe odpytanie (2 s) wróci ze starą.
  ev.current = next;
  const val = $("ev-value");
  if (val) val.textContent = evLabel(next);
  post({ action: "set_ev", value: next });
}

const bgStatus = st => (st.connected && BG_LABEL[st.camera.bgStatus]) ? st.camera.bgStatus : "unknown";
const histLabel = st => BG_LABEL[bgStatus(st)];
const histColor = st => BG_COLOR[bgStatus(st)];
const histTitle = st => bgStatus(st) === "unknown"
  ? "Jasność tła — czekam na klatkę z aparatu."
  : `Zmierzona jasność tła: ${st.camera.bg} ze skali 0–255 (im bliżej 255, tym bielszy stół; poniżej 230 robi się szaro).`;

function reviewShot() {
  const shots = S.state.shots;
  if (!shots.length) return null;
  const i = S.selShot >= 0 && S.selShot < shots.length ? S.selShot : shots.length - 1;
  return { ...shots[i], i };
}

function reviewLabelText(shot) {
  return `PODGLĄD ${shot.i + 1}/${S.state.shots.length} — ${shot.file} · ← → zmiana · BACKSPACE usuwa · ESC zamyka podgląd`;
}

// Podglad zdjecia zajmuje CALE okno (position: fixed nad zakladkami i sidebarem),
// a pasek zdjec sesji siedzi u jego dolu. Wczesniej overlay mieszkal w ramce live
// view, wiec zdjecie ogladalo sie w okienku wielkosci podgladu z aparatu.
function reviewOverlay() {
  const shot = S.reviewMode ? reviewShot() : null;
  if (!shot) return "";
  const sess = encodeURIComponent(S.state.session.name);
  return `
  <div id="review-wrap" style="position: fixed; inset: 0; z-index: 60; background: #131315; display: flex; flex-direction: column; transition: opacity .2s ease, transform .2s ease;">
    <div style="flex: 1; position: relative; min-height: 0;">
      <img src="/img?s=${sess}&f=${encodeURIComponent(shot.file)}" style="position: absolute; inset: 14px; width: calc(100% - 28px); height: calc(100% - 28px); object-fit: contain; animation: reviewIn .26s cubic-bezier(0.8, -0.4, 0.5, 1);" />
      <div id="review-label" style="position: absolute; left: 14px; bottom: 14px; background: rgba(0,0,0,.55); border: 1px solid #3c3c44; padding: 3px 8px; ${mono} font-size: 10.5px; color: #d0d0d6;">${reviewLabelText(shot)}</div>
      <div onclick="closeReview()" style="position: absolute; right: 14px; top: 14px; background: rgba(0,0,0,.55); border: 1px solid #3c3c44; padding: 3px 10px; ${mono} font-size: 10.5px; color: #d0d0d6;">ZAMKNIJ ESC</div>
    </div>
    <div style="flex: 0 0 auto; border-top: 1px solid #2c2c31; background: #1d1d20; padding: 10px 14px 12px;">
      <div id="review-strip" style="display: flex; gap: 8px; overflow-x: auto; overflow-y: hidden;">${filmstrip()}</div>
    </div>
  </div>`;
}

// Pasek zdjec wisi w dwoch miejscach (ekran sesji i podglad), oba trzeba odswiezyc
// po zmianie zaznaczenia. Aktywny kafelek jest przy okazji doprowadzany do widoku —
// przy kilkunastu zdjeciach zaznaczenie potrafi wyjechac poza pasek.
function refreshStrips() {
  ["filmstrip", "review-strip"].forEach(id => {
    const strip = $(id);
    if (!strip) return;
    strip.innerHTML = filmstrip();
    const tile = strip.querySelector(`[data-shot="${S.selShot}"]`);
    if (tile) tile.scrollIntoView({ block: "nearest", inline: "center" });
  });
}

function navShot(dir) {
  const list = S.state.shots;
  if (!list.length) return;
  const cur = S.selShot < 0 ? list.length : S.selShot;
  showShot(Math.max(0, Math.min(list.length - 1, cur + dir)), dir);
}

// Klik w kafelek paska: w podgladzie podmienia zdjecie W MIEJSCU (pelny rebuild
// zabilby overlay i powtorzyl animacje wejscia), poza podgladem otwiera podglad.
function openShot(i) {
  if (!S.reviewMode) {
    S.selShot = i;
    S.reviewMode = true;
    renderScreens();
    return;
  }
  showShot(i, i > S.selShot ? 1 : -1);
}

function showShot(next, dir) {
  const list = S.state.shots;
  if (!list.length || next === S.selShot) return;
  S.selShot = next;
  dir = dir < 0 ? -1 : 1;
  const wrap = $("review-wrap");
  if (S.reviewMode && wrap) {
    // Wrap zostaje w DOM (zawsze nieprzezroczysty — zadnych przebitek live
    // view), podmieniamy tylko src: stare zdjecie wisi az nowe sie zdekoduje.
    // Animacja = minimalny nudge transformem, bez opacity.
    const shot = reviewShot();
    const sess = encodeURIComponent(S.state.session.name);
    const img = wrap.querySelector("img");
    img.src = `/img?s=${sess}&f=${encodeURIComponent(shot.file)}`;
    const label = $("review-label");
    if (label) label.textContent = reviewLabelText(shot);
    // Skok musi byc WIDOCZNY, inaczej krzywa easingu nie ma czego pokazac —
    // przy poprzednich 6 px kazdy easing wygladal identycznie.
    img.style.transition = "none";
    img.style.transform = `translateX(${dir * 56}px)`;
    img.style.opacity = "0.45";
    requestAnimationFrame(() => requestAnimationFrame(() => {
      img.style.transition = "transform .5s cubic-bezier(0.16, 1, 0.3, 1), opacity .32s cubic-bezier(0.16, 1, 0.3, 1)";
      img.style.transform = "none";
      img.style.opacity = "1";
    }));
    [next - 1, next + 1].forEach(i => {
      if (list[i]) new Image().src = `/img?s=${sess}&f=${encodeURIComponent(list[i].file)}`;
    });
    refreshStrips();
    lastSesja = sesjaKey(S.state);
  } else {
    renderScreens();
  }
}

function deleteReviewed() {
  const shot = reviewShot();
  if (!shot) return;
  const sess = S.state.session.name;
  post({ action: "delete", session: sess, files: [shot.file] });
  const list = S.state.shots;
  list.splice(shot.i, 1);
  const wrap = $("review-wrap");
  const img = wrap && wrap.querySelector("img");

  if (!list.length) {
    // ostatnie zdjecie — powrot do live (tu przejscie w przezroczystosc
    // jest zamierzone, odslania podglad z aparatu)
    S.selShot = -1;
    S.reviewMode = false;
    if (wrap) {
      wrap.style.opacity = "0";
      wrap.style.transform = "scale(.96)";
      setTimeout(() => renderScreens(true), 190);
    } else {
      renderScreens(true);
    }
    return;
  }

  S.selShot = Math.min(shot.i, list.length - 1);
  if (!img) {
    renderScreens(true);
    return;
  }
  // Wrap zostaje kryjacy — animuje sie TYLKO obrazek na ciemnym tle,
  // wiec live view nie przebija. Nastepne zdjecie podmieniamy w miejscu
  // (zadnego pelnego rebuildu z powtorka animacji wejscia).
  const nextShot = reviewShot();
  const enc = encodeURIComponent(sess);
  img.style.transition = "transform .16s ease-in, opacity .16s ease-in";
  img.style.transform = "scale(.85) translateY(36px)";
  img.style.opacity = "0";
  setTimeout(() => {
    const label = $("review-label");
    if (label) label.textContent = reviewLabelText(nextShot);
    img.style.transition = "none";
    img.style.transform = "scale(.96)";
    const show = () => {
      img.onload = null;
      img.style.transition = "transform .15s ease-out, opacity .15s ease-out";
      img.style.transform = "none";
      img.style.opacity = "1";
    };
    img.onload = show;
    img.src = `/img?s=${enc}&f=${encodeURIComponent(nextShot.file)}`;
    setTimeout(show, 250);
    refreshStrips();
    lastSesja = sesjaKey(S.state);
  }, 170);
}

function closeReview() {
  const w = $("review-wrap");
  if (!w) { S.reviewMode = false; renderScreens(); return; }
  w.style.opacity = "0";
  w.style.transform = "scale(.96)";
  setTimeout(() => { S.reviewMode = false; renderScreens(); }, 180);
}

function flashNow() {
  const el = $("flash");
  if (!el) return;
  el.style.transition = "none";
  el.style.opacity = "0.85";
  requestAnimationFrame(() => requestAnimationFrame(() => {
    el.style.transition = "opacity .45s ease-out";
    el.style.opacity = "0";
  }));
}

function tileBg(sess, file) {
  return `background: #202024 url('/img?s=${encodeURIComponent(sess)}&f=${encodeURIComponent(file)}&thumb=1') center / cover;`;
}

function filmstrip() {
  const st = S.state;
  const items = st.shots.map((s, i) => {
    const m = i === S.selShot ? MARKS.cur : (s.status === "rejected" ? MARKS.bad : MARKS.ok);
    return `
    <div data-shot="${i}" onclick="openShot(${i})" style="width: 104px; flex: 0 0 104px;">
      <div style="height: 72px; ${tileBg(st.session.name, s.file)} border: 1px solid ${m.border}; display: flex; align-items: flex-end; justify-content: space-between; padding: 4px; box-sizing: border-box;">
        <span style="${mono} font-size: 10px; color: #fff; text-shadow: 0 1px 2px #000;">#${i + 1}</span>
        <span style="${mono} font-size: 10px; color: ${m.color}; text-shadow: 0 1px 2px #000;">${m.mark}</span>
      </div>
      <div style="${mono} font-size: 9.5px; color: #6c6c74; margin-top: 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${s.file}</div>
    </div>`;
  });
  if (st.processing) {
    const m = MARKS.wait;
    items.push(`
    <div style="width: 104px; flex: 0 0 104px;">
      <div style="height: 72px; background: repeating-linear-gradient(135deg, #23232a 0 8px, #2a2a32 8px 16px); border: 1px solid ${m.border}; display: flex; align-items: flex-end; justify-content: space-between; padding: 4px; box-sizing: border-box;">
        <span style="${mono} font-size: 10px; color: #8b8b93;">#${st.shots.length + 1}</span>
        <span style="${mono} font-size: 10px; color: ${m.color};">${m.mark}</span>
      </div>
      <div style="${mono} font-size: 9.5px; color: #6c6c74; margin-top: 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${st.processing}</div>
    </div>`);
  }
  // pobieranie zdjec sesji z Automatu — kafelek-skeleton az plik wyladuje na dysku
  (st.downloading || []).forEach(() => {
    items.push(`
    <div style="width: 104px; flex: 0 0 104px;">
      <div class="skeleton" style="height: 72px; border: 1px solid #3a3a44; display: flex; align-items: flex-end; justify-content: space-between; padding: 4px; box-sizing: border-box;">
        <span style="${mono} font-size: 10px; color: #8b8b93;">↓</span>
      </div>
      <div class="skeleton" style="height: 9px; margin-top: 6px;"></div>
    </div>`);
  });
  return items.join("") || `<div style="${mono} font-size: 10.5px; color: #6c6c74; padding: 26px 0;">(brak zdjęć w tej sesji)</div>`;
}

function logMark(kind) {
  if (kind === "ok") return `<span style="color: #9fe0a8;">✓</span> `;
  if (kind === "warn") return `<span style="color: #e0b96a;">!</span> `;
  if (kind === "err") return `<span style="color: #e07a7a;">✗</span> `;
  return "";
}

// Powtórzony wpis nie jest dopisywany drugi raz (patrz WebUI._log) — backend
// podbija licznik, my doklejamy „×N".
const logCount = l => (l.n > 1 ? ` <span style="color: #7e7e85;">×${l.n}</span>` : "");

// Sygnatura logu dla updateVolatile(): sama długość nie wystarczy, bo powtórki
// rosną licznikiem w OSTATNIM wpisie, nie nowym elementem.
function logSig(st) {
  const last = st.log[st.log.length - 1];
  return `${st.log.length}:${last ? last.n : 0}`;
}

function lastLogLine() {
  const log = S.state.log;
  const last = log[log.length - 1];
  if (!last) return `<span style="flex: 1;"></span>`;
  return `${logMark(last.kind)}<span style="flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${last.text}${logCount(last)}</span>`;
}

function logLines() {
  return S.state.log.map(l => `<div>${logMark(l.kind)}${l.t} · ${l.text}${logCount(l)}</div>`).join("");
}

function ustawieniaScreen() {
  const st = S.state, cfg = st.settings, u = st.update || {current: "?", status: ""};
  // Backend ustawia `checking` już w handlerze akcji, ale poll ma 500 ms —
  // `S.checkStartedAt` trzyma spinner od razu po kliknięciu (i minimum ~600 ms,
  // żeby szybka odpowiedź nie mignęła bez śladu).
  const checking = u.checking || (S.checkStartedAt && Date.now() - S.checkStartedAt < 600);
  const card = `display: flex; flex-direction: column; gap: 12px; background: #232326; border: 1px solid #2f2f35; border-radius: 6px; padding: 16px 18px;`;
  return `
    <div style="${card}">
      <div style="${head}">Pliki i katalogi</div>
      <div style="display: grid; grid-template-columns: 120px 1fr auto; gap: 8px 10px; align-items: center;">
        <div style="color: #b4b4bb;">Katalog zdjęć</div>
        <input value="${cfg.photosDir}" onchange="post({action:'set_app', key:'photos_dir', value:this.value})" style="${inp}" />
        <button style="${btnGray} height: 26px; padding: 0 10px; font-size: 11.5px;">Wybierz</button>
        <div style="color: #b4b4bb;">Plik logo</div>
        <input value="${cfg.logoPath}" onchange="post({action:'set_app', key:'logo_path', value:this.value})" style="${inp}" />
        <button style="${btnGray} height: 26px; padding: 0 10px; font-size: 11.5px;">Wybierz</button>
        <div style="color: #b4b4bb;">Wzór nazwy</div>
        <input value="${cfg.namePattern}" onchange="post({action:'set_app', key:'name_pattern', value:this.value})" style="${inp}" />
        <div></div>
      </div>
      <label style="${label}"><input type="checkbox" ${cfg.keepRaw ? "checked" : ""} onchange="post({action:'set_app', key:'keep_raw', value:this.checked})" style="${chk}" />Zachowaj oryginały w podkatalogu /raw</label>
    </div>

    <div style="${card}">
      <div style="${head}">Automat (aplikacja web)</div>
      <div style="display: grid; grid-template-columns: 120px 1fr; gap: 8px 10px; align-items: center;">
        <div style="color: #b4b4bb;">Adres API</div>
        <input value="${cfg.automatUrl}" onchange="post({action:'set_app', key:'automat_url', value:this.value})" style="${inp}" />
        <div style="color: #b4b4bb;">Token</div>
        <input value="${cfg.tokenMasked}" onchange="post({action:'set_app', key:'automat_token', value:this.value})" style="${inp}" />
      </div>
      <div style="display: flex; align-items: center; gap: 10px;">
        <button onclick="post({action:'test_connection'})" style="${btnGray} font-size: 11.5px;">Testuj połączenie</button>
        <span style="${mono} font-size: 10.5px; color: ${cfg.testResult.startsWith("✓") ? "#9fe0a8" : "#e0b96a"};">${cfg.testResult}</span>
      </div>
    </div>

    <div style="${card}">
      <div style="${head}">Podgląd</div>
      <div style="display: grid; grid-template-columns: 120px 1fr; gap: 8px 10px; align-items: center;">
        <div style="color: #b4b4bb;">FPS podglądu</div>
        <select onchange="post({action:'set_app', key:'preview_fps', value:this.value})" style="${sel}">
          ${[10, 15, 20, 25, 30].map(f => `<option ${f === cfg.previewFps ? "selected" : ""}>${f}</option>`).join("")}
        </select>
      </div>
    </div>

    <div style="${card}">
      <div style="${head}">Aktualizacje</div>
      <div style="display: grid; grid-template-columns: 120px 1fr; gap: 8px 10px; align-items: center;">
        <div style="color: #b4b4bb;">Wersja</div>
        <div style="${mono} font-size: 11.5px; color: #c9c9cf;">${u.current}</div>
      </div>
      <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">
        <button onclick="checkUpdate()" ${checking ? "disabled" : ""} style="${btnGray} font-size: 11.5px; display: inline-flex; align-items: center; gap: 7px; ${checking ? "opacity: .7;" : ""}">${checking ? `<span class="spinner"></span>Sprawdzam…` : "Sprawdź aktualizacje"}</button>
        ${u.available && u.canApply ? `<button onclick="applyUpdate()" ${u.busy ? "disabled" : ""} style="height: 26px; padding: 0 12px; ${btnBlue} border-radius: 4px; font-size: 11.5px; font-weight: 600; display: inline-flex; align-items: center; gap: 7px; ${u.busy ? "opacity: .6;" : ""}">${u.busy ? `<span class="spinner"></span>Aktualizuję…` : `Zainstaluj ${u.available}`}</button>` : ""}
        <span style="${mono} font-size: 10.5px; color: ${checking ? "#9d9da3" : u.status.startsWith("✗") ? "#e07a7a" : u.available ? "#e0b96a" : "#9fe0a8"};">${checking ? "Pytam GitHuba o najnowsze wydanie…" : u.status}</span>
      </div>
      ${u.available && !u.canApply ? `<div style="${mono} font-size: 10.5px; color: #77777f;">Uruchomienie ze źródeł — aktualizacja przez <b>git pull</b>. Automatyczna podmiana działa tylko dla .exe na Windowsie.</div>` : ""}
      ${u.available && u.notes ? `<div style="${mono} font-size: 10.5px; color: #8f8f97; white-space: pre-wrap; max-height: 96px; overflow: auto;">${u.notes}</div>` : ""}
    </div>

    <div style="display: flex; flex-direction: column; gap: 10px; background: #232326; border: 1px solid #2f2f35; border-radius: 6px; padding: 16px 18px;">
      <div style="${head}">Skróty klawiszowe</div>
      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 6px 18px; ${mono} font-size: 11px; color: #a8a8af;">
        <div>ENTER — zdjęcie</div><div>P — podgląd on/off</div>
        <div>SPACJA — podgląd zdjęć na live view</div><div>← → — zmiana zdjęcia / nawigacja</div>
        <div>BACKSPACE — usuń oglądane zdjęcie</div><div>ESC — zamknij podgląd</div>
      </div>
    </div>`;
}

// ---------- rendering ----------

let lastShellKey = "", lastSesja = "", lastUstawienia = "";

const sesjaKey = st => JSON.stringify([st.session.name, st.session.dir, st.shots,
  st.processing, st.downloading, st.post, st.previewOn, S.selShot, S.logOpen,
  S.grid, S.reviewMode]);

function renderShell(force) {
  const st = S.state;
  const u = st.update || {};
  // progress pobierania NIE jest w kluczu — łata go updateVolatile(), bo
  // rebuild shella niszczy <img> streamu (miganie przy każdym procencie)
  const key = JSON.stringify([S.screen, st.connected,
    u.available, u.busy, u.canApply, S.updateDismissed]);
  if (force || key !== lastShellKey) {
    lastShellKey = key;
    $("app").innerHTML = shell();
    lastSesja = lastUstawienia = "";
    renderScreens(true);
    return;
  }
  renderScreens(false);
}

// Zmienne drobiazgi (fps, badge histogramu, log, busy) aktualizowane
// punktowo po id — pelny rebuild ekranu niszczylby <img> streamu
// i podgladu (miganie co kazda zmiane stanu).
function updateVolatile(st) {
  const conn = $("conn-label");
  if (conn) conn.textContent = st.connected ? `Aparat połączony · ${st.fps} fps` : "Aparat rozłączony";
  const hist = $("hist-badge");
  if (hist) {
    hist.textContent = histLabel(st);
    hist.style.color = histColor(st);
    hist.title = histTitle(st);
  }
  // EV jest ŚWIADOMIE łatane, nie keyowane: rebuild ekranu niszczy <img>
  // streamu MJPEG, a kompensacja zmienia się też z pokrętła na aparacie
  const evVal = $("ev-value");
  if (evVal) {
    const ev = st.camera && st.camera.ev;
    evVal.textContent = ev ? evLabel(ev.current) : "—";
    const hint = $("ev-hint");
    if (hint) hint.textContent = evHint(st);
    ["ev-minus", "ev-plus"].forEach(id => {
      const b = $(id);
      if (b) b.style.opacity = ev ? 1 : .35;
    });
  }
  const sl = $("shoot-label");
  if (sl) sl.textContent = st.busy || "Zrób zdjęcie";
  const up = $("update-progress");
  if (up) {
    const u = st.update || {};
    up.textContent = u.busy && u.progress ? `${u.progress}%` : "";
  }
  const sig = logSig(st);
  if (sig !== S.lastLogLen) {
    S.lastLogLen = sig;
    const line = $("log-line");
    if (line) line.innerHTML = lastLogLine();
    const lp = $("log-panel");
    if (lp) {
      lp.innerHTML = logLines();
      lp.scrollTop = lp.scrollHeight;
    }
  }
}

function renderScreens(force) {
  const st = S.state;
  $("stat-name").textContent = st.session.name || "—";
  $("stat-count").textContent = st.session.count;
  updateVolatile(st);

  if (S.screen === "sesja" && !st.session.name) {
    const key = JSON.stringify(["start", st.automat, S.pendingNew, S.dayFocus]);
    if (force || key !== lastSesja) {
      const el = document.activeElement;
      const editing = el && el.id === "new-session-input";
      const keep = editing ? el.value : null;
      // okładki dolatują po kolei, każda = rebuild — bez tego lista skakałaby
      // na górę operatorowi w trakcie przeglądania
      const scroll = $("start-scroll") ? $("start-scroll").scrollTop : 0;
      lastSesja = key;
      $("screen-sesja").innerHTML = startScreen();
      if ($("start-scroll")) $("start-scroll").scrollTop = scroll;
      if (keep !== null) {
        const i = $("new-session-input");
        i.value = keep;
        i.focus();
      }
    }
  } else if (S.screen === "sesja") {
    const key = sesjaKey(st);
    if (force || key !== lastSesja) {
      lastSesja = key;
      S.lastLogLen = logSig(st);
      $("screen-sesja").innerHTML = sesjaScreen();
      // najnowsze zdjecie na wierzchu; w podgladzie zamiast tego dojezdzamy do
      // zaznaczonego kafelka, zeby bylo widac, ktore zdjecie sie oglada
      ["filmstrip", "review-strip"].forEach(id => {
        const strip = $(id);
        if (!strip) return;
        const tile = S.reviewMode && strip.querySelector(`[data-shot="${S.selShot}"]`);
        if (tile) tile.scrollIntoView({ block: "nearest", inline: "center" });
        else strip.scrollLeft = strip.scrollWidth;
      });
      const lp = $("log-panel");
      if (lp) lp.scrollTop = lp.scrollHeight;
    }
  } else {
    const key = JSON.stringify([st.settings, st.update]);
    if (force || key !== lastUstawienia) {
      if (document.activeElement && document.activeElement.tagName === "INPUT") return;
      lastUstawienia = key;
      $("screen-ustawienia").innerHTML = ustawieniaScreen();
    }
  }
}

function go(screen) {
  S.screen = screen;
  renderShell(true);
}


// ---------- akcje ----------

// Wyjscie z sesji = powrot na ekran startowy z lista sesji. Zmiana nazwy idzie
// wlasnie tamtedy (pole "Utworz i otworz"), wiec sidebar nie ma juz inputa.
function leaveSession() {
  S.pendingNew = null;
  post({ action: "clear_session" });
}

function shoot() {
  if (!S.state.connected || !S.state.session.name) return;
  flashNow();
  post({ action: "shoot" });
}

function toggleReview() {
  if (!S.state.shots.length) { S.reviewMode = false; return; }
  if (S.reviewMode) {
    closeReview();
    return;
  }
  S.reviewMode = true;
  if (S.selShot < 0) S.selShot = S.state.shots.length - 1;
  renderScreens();
}
function toggle(key, value) { post({ action: "toggle", key, value }); }

function cycleGrid() {
  S.grid = (S.grid + 1) % GRIDS.length;
  renderScreens();
}

function checkUpdate() {
  S.checkStartedAt = Date.now();
  post({ action: "check_update" });
  renderScreens(true);
  // pod koniec minimalnego czasu spinnera przemaluj — poll mógł w tym czasie
  // przynieść już gotowy wynik, a klucz ekranu się wtedy nie zmienił
  setTimeout(() => { S.checkStartedAt = 0; renderScreens(true); }, 650);
}

// Backend pobiera paczke, zamyka aplikacje i odpala updater .bat, ktory
// podmienia pliki i uruchamia .exe z powrotem — okno zniknie samo.
function applyUpdate() {
  const u = S.state.update || {};
  if (!u.canApply || u.busy) return;
  post({ action: "apply_update" });
}

// ---------- klawiatura ----------

document.addEventListener("keydown", e => {
  const tag = document.activeElement ? document.activeElement.tagName : "";
  if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") {
    if (e.key === "Enter" && document.activeElement.id === "new-session-input") {
      commitNewSession();
    }
    return;
  }
  if (e.metaKey || e.ctrlKey) return;

  // preventDefault na wszystkim co obslugujemy — bez tego WKWebView puszcza
  // klawisz w gore responder chain i macOS robi systemowy beep
  if (["Enter", " ", "Escape", "Backspace", "ArrowLeft", "ArrowRight",
       "p", "P", "a", "A", "x", "X"].includes(e.key)) {
    e.preventDefault();
  }
  switch (e.key) {
    case "Enter": shoot(); break;
    case " ": toggleReview(); break;
    case "Escape":
      if (S.reviewMode) closeReview();
      break;
    case "Backspace":
      if (S.reviewMode) deleteReviewed();
      break;
    case "p": case "P": toggle("preview", !S.state.previewOn); break;
    case "ArrowLeft": navShot(-1); break;
    case "ArrowRight": navShot(1); break;
    case "a": case "A": reviewSelected("accepted"); break;
    case "x": case "X":
      if (S.selShot >= 0) reviewSelected("rejected");
      else post({ action: "reject_last" });
      break;
  }
});

function reviewSelected(verdict) {
  const f = S.state.shots[S.selShot];
  if (!f) return;
  post({
    action: "review", verdict,
    session: S.state.session.name,
    file: f.file,
  });
}

// ---------- petla stanu ----------

async function tick() {
  try {
    const r = await fetch("/api/state");
    S.state = await r.json();
    if (!lastShellKey) renderShell(true);
    else renderShell(false);
  } catch (e) {
    const el = $("conn-label");
    if (el) el.textContent = "brak połączenia z backendem";
  }
  setTimeout(tick, 500);
}
tick();
