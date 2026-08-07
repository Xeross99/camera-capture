"use strict";
const ACCENT = "#4a8cff";
const S = {           // stan klienta
  screen: "sesja", logOpen: false, state: null,
  selShot: -1,
  gridOn: true, kadrOn: true, reviewMode: false, lastLogLen: -1,
  pendingNew: null,   // {name, match} — wpisana nazwa koliduje z istniejącą sesją Automatu
  updateDismissed: "",// wersja, dla której operator kliknął „Później"
  checkStartedAt: 0,  // klik w „Sprawdź aktualizacje" — minimalny czas spinnera
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

function startScreen() {
  const a = S.state.automat;
  const fmtDate = iso => {
    const d = new Date(iso);
    return isNaN(d) ? "" : `${String(d.getDate()).padStart(2, "0")}.${String(d.getMonth() + 1).padStart(2, "0")} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
  };
  const cards = a.sessions.map(s => {
    const chip = s.product
      ? `<span style="${mono} font-size: 9.5px; color: #9fe0a8;">✓ produkt</span>`
      : `<span style="${mono} font-size: 9.5px; color: #e0b96a;">luźna</span>`;
    return `
    <div onclick='pickSession(${s.id}, ${JSON.stringify(s.name)})' style="background: #232326; border: 1px solid #2f2f35; border-radius: 6px; padding: 14px 16px; display: flex; flex-direction: column; gap: 7px; cursor: default;"
         onmouseover="this.style.borderColor='${ACCENT}'" onmouseout="this.style.borderColor='#2f2f35'">
      <div style="font-size: 13px; font-weight: 600; color: #e8e8ea; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${s.name}</div>
      <div style="display: flex; align-items: center; gap: 10px; ${mono} font-size: 10.5px; color: #7e7e85;">
        <span>${fmtDate(s.created_at)}</span><span>zdjęć: <span style="color: #c9c9cf;">${s.photos_count}</span></span>${chip}
      </div>
    </div>`;
  }).join("");
  const info = !a.hasToken
    ? `<div style="${mono} font-size: 11px; color: #e0b96a;">Brak tokenu Automatu (.env / Ustawienia) — sesje z Automatu niedostępne, możesz utworzyć lokalną.</div>`
    : a.error
      ? `<div style="${mono} font-size: 11px; color: #e07a7a;">✗ ${a.error}</div>`
      : a.sessions.length === 0
        ? `<div style="${mono} font-size: 11px; color: #7e7e85;">Ładuję sesje z Automatu…</div>`
        : "";
  const p = S.pendingNew;
  const pend = !p ? "" : `
    <div style="max-width: 560px; background: #26231d; border: 1px solid #5a4a2a; border-radius: 6px; padding: 12px 14px; display: flex; flex-direction: column; gap: 10px;">
      <div style="font-size: 12.5px; color: #e8e8ea;">Sesja <b>${p.match.name}</b> już istnieje w Automacie (${fmtDate(p.match.created_at)}, zdjęć: ${p.match.photos_count}).</div>
      <div style="display: flex; gap: 8px;">
        <button onclick="resolvePending(true)" style="height: 28px; padding: 0 14px; ${btnBlue} border-radius: 4px; font-size: 12px; font-weight: 600;">Podłącz do istniejącej</button>
        <button onclick="resolvePending(false)" style="${btnGray} height: 28px;">Utwórz nową</button>
        <button onclick="S.pendingNew = null; renderScreens(true)" style="${btnGray} height: 28px; opacity: .7;">Anuluj</button>
      </div>
    </div>`;
  return `
  <div style="flex: 1; overflow: auto; background: #1d1d20; padding: 26px 32px; display: flex; flex-direction: column; gap: 18px; min-width: 0;">
    <div style="display: flex; flex-direction: column; gap: 8px;">
      <div style="${head}">Nowa sesja zdjęciowa</div>
      <div style="display: flex; gap: 8px; max-width: 560px;">
        <input id="new-session-input" placeholder="nazwa produktu…" style="flex: 1; ${inp} font-size: 12px; height: 32px;" />
        <button onclick="commitNewSession()" style="height: 32px; padding: 0 18px; ${btnBlue} border-radius: 5px; font-size: 12.5px; font-weight: 600;">Utwórz i otwórz</button>
      </div>
      <div style="${mono} font-size: 10.5px; color: #77777f;">nazwa = folder w photos/ i sesja w Automacie (dopasowanie do produktu po nazwie)</div>
      ${pend}
    </div>
    <div style="display: flex; align-items: center; gap: 12px; margin-top: 6px;">
      <div style="${head}">Sesje z Automatu</div>
      <button onclick="post({action: 'refresh_sessions'})" style="${btnGray} height: 24px; padding: 0 10px; font-size: 11px;">Odśwież</button>
      ${info}
    </div>
    <div style="display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; align-content: start;">
      ${cards}
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
  const bgColor = cam.bgOk ? "#9fe0a8" : "#e0b96a";
  const histText = cam.bgOk ? "HISTOGRAM OK" : "HISTOGRAM !";
  const badge = `background: rgba(0,0,0,.55); border: 1px solid #3c3c44; padding: 3px 8px; ${mono} font-size: 10.5px; color: #d0d0d6;`;
  return `
    <div style="flex: 1; display: flex; flex-direction: column; min-width: 0; background: #161618;">
      <div style="flex: 1; display: flex; align-items: center; justify-content: center; min-height: 0; position: relative; padding: 14px;">
        <div style="height: 100%; aspect-ratio: 3 / 2; background: repeating-linear-gradient(135deg, #202024 0 10px, #26262b 10px 20px); border: 1px solid #34343a; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px; position: relative;">
          <img id="live" src="/stream" style="position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain; display: ${st.previewOn ? "block" : "none"};" />
          <div style="${mono} font-size: 12px; color: #8b8b93; letter-spacing: .04em;">live view — 1024 × 683</div>
          <div style="${mono} font-size: 11px; color: #63636b;">${st.previewOn ? "czekam na klatki z aparatu…" : "podgląd wyłączony (P)"}</div>
          <div id="grid-overlay" style="position: absolute; inset: 0; display: ${S.gridOn && st.previewOn ? "block" : "none"}; background:
            linear-gradient(to right, transparent calc(33.33% - .5px), rgba(255,255,255,.13) 33.33%, transparent calc(33.33% + .5px)),
            linear-gradient(to right, transparent calc(66.66% - .5px), rgba(255,255,255,.13) 66.66%, transparent calc(66.66% + .5px)),
            linear-gradient(to bottom, transparent calc(33.33% - .5px), rgba(255,255,255,.13) 33.33%, transparent calc(33.33% + .5px)),
            linear-gradient(to bottom, transparent calc(66.66% - .5px), rgba(255,255,255,.13) 66.66%, transparent calc(66.66% + .5px));"></div>
          <div id="kadr-overlay" style="position: absolute; top: 0; bottom: 0; left: 16.67%; right: 16.67%; border: 1px dashed rgba(255,255,255,.14); display: ${S.kadrOn && st.previewOn ? "block" : "none"};"></div>
          <div style="position: absolute; left: 12px; top: 12px; display: flex; gap: 6px;">
            <div onclick="S.gridOn = !S.gridOn; renderScreens()" style="${badge} ${S.gridOn ? "" : "opacity: .45;"}">SIATKA 3×3</div>
            <div onclick="S.kadrOn = !S.kadrOn; renderScreens()" style="${badge} ${S.kadrOn ? "" : "opacity: .45;"}">KADR 1:1</div>
          </div>
          ${st.previewOn && st.connected ? `
          <div style="position: absolute; right: 12px; top: 12px; display: flex; align-items: center; gap: 6px; background: rgba(0,0,0,.55); border: 1px solid #3c3c44; padding: 3px 8px; ${mono} font-size: 10.5px; color: #d0d0d6;">
            <div style="width: 7px; height: 7px; border-radius: 50%; background: #ff4d4d; animation: livePulse 1.6s ease-in-out infinite;"></div>LIVE
          </div>` : ""}
          <div id="hist-badge" style="position: absolute; right: 12px; bottom: 12px; background: rgba(0,0,0,.55); border: 1px solid #3c3c44; padding: 3px 8px; ${mono} font-size: 10.5px; color: ${bgColor};">${histText}</div>
          <div id="review-slot" style="position: absolute; inset: 0; z-index: 2; pointer-events: none;">${reviewOverlay()}</div>
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
                <a href="#" class="crumb" onclick="S.pendingNew = null; post({action: 'clear_session'}); return false;" style="display: flex;">
                  <svg viewBox="0 0 20 20" fill="currentColor" aria-hidden="true" style="width: 15px; height: 15px; flex-shrink: 0; display: block;">
                    <path d="M9.293 2.293a1 1 0 0 1 1.414 0l7 7A1 1 0 0 1 17 11h-1v6a1 1 0 0 1-1 1h-2a1 1 0 0 1-1-1v-3a1 1 0 0 0-1-1H9a1 1 0 0 0-1 1v3a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1v-6H3a1 1 0 0 1-.707-1.707l7-7Z" clip-rule="evenodd" fill-rule="evenodd" />
                  </svg>
                  <span class="sr-only">Wszystkie sesje</span>
                </a>
              </li>
              <li style="display: flex; align-items: center; gap: 8px; min-width: 0;">
                <svg viewBox="0 0 20 20" fill="currentColor" aria-hidden="true" style="width: 15px; height: 15px; flex-shrink: 0; color: #45454d;">
                  <path d="M5.555 17.776l8-16 .894.448-8 16-.894-.448z" />
                </svg>
                <span aria-current="page" style="${mono} font-size: 11px; color: #b4b4bb; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${st.session.name}</span>
              </li>
            </ol>
          </nav>
          <div style="${head}">Sesja zdjęciowa</div>
          <div style="display: flex; gap: 8px;">
            <input id="session-input" value="${st.session.name}" placeholder="nazwa produktu…" style="flex: 1; ${inp} font-size: 11.5px;" />
            <button onclick="commitName()" style="height: 26px; padding: 0 14px; background: linear-gradient(#4a4a50, #3d3d43); border: 1px solid #55555d; border-radius: 4px; color: #eaeaee; font-size: 12px; font-family: inherit;">Ustaw</button>
          </div>
          <div style="${mono} font-size: 10.5px; color: #77777f; word-break: break-all;">${st.session.dir || "(bez nazwy nie da się strzelić)"}</div>
        </div>

        <div style="display: flex; flex-direction: column; gap: 9px;">
          <div style="${head}">Postprocessing</div>
          <label style="${label}"><input type="checkbox" ${post_.logo ? "checked" : ""} onchange="toggle('logo', this.checked)" style="${chk}" />Nakładanie logo</label>
          <div style="display: grid; grid-template-columns: 84px 1fr; gap: 8px 10px; align-items: center; padding-left: 22px;">
            <div style="color: #b4b4bb;">Pozycja</div>
            <select onchange="post({action:'set_post', key:'logo_position', value:this.value})" style="${sel}">
              ${post_.logoPositions.map(p => `<option ${p === post_.logoPosition ? "selected" : ""}>${p}</option>`).join("")}
            </select>
          </div>
          <label style="${label}"><input type="checkbox" ${post_.zoom ? "checked" : ""} onchange="toggle('zoom', this.checked)" style="${chk}" />Przybliżanie (zoom do produktu)</label>
          <label style="${label}"><input type="checkbox" ${post_.center ? "checked" : ""} onchange="toggle('center', this.checked)" style="${chk}" />Centrowanie</label>
          <label style="${label}"><input type="checkbox" ${post_.cleanBg ? "checked" : ""} onchange="toggle('cleanbg', this.checked)" style="${chk}" />Wyrównanie tła do bieli</label>
        </div>

      </div>

      <div style="flex: 0 0 auto; border-top: 1px solid #17171a; background: #26262a; padding: 12px 16px 14px; display: flex; flex-direction: column; gap: 8px;">
        <button onclick="shoot()" style="height: 44px; ${btnBlue} border-radius: 6px; font-size: 14px; font-weight: 600; display: flex; align-items: center; justify-content: center; gap: 10px;"><span id="shoot-label">${st.busy || "Zrób zdjęcie"}</span> <span style="${mono} font-size: 11px; opacity: .75;">ENTER</span></button>
        <div style="display: flex; gap: 8px;">
          <button onclick="toggle('preview', !S.state.previewOn)" style="flex: 1; height: 30px; background: linear-gradient(#3f3f45, #35353a); border: 1px solid #4c4c54; border-radius: 5px; color: #eaeaee; font-size: 12px; font-family: inherit;">Podgląd: ${st.previewOn ? "ON" : "OFF"} <span style="${mono} font-size: 10.5px; color: #9d9da3;">P</span></button>
          <button onclick="post({action:'reject_last'})" style="flex: 1; height: 30px; background: linear-gradient(#3f3f45, #35353a); border: 1px solid #4c4c54; border-radius: 5px; color: #eaeaee; font-size: 12px; font-family: inherit;">Odrzuć ostatnie <span style="${mono} font-size: 10.5px; color: #9d9da3;">X</span></button>
        </div>
      </div>
    </div>`;
}

function reviewShot() {
  const shots = S.state.shots;
  if (!shots.length) return null;
  const i = S.selShot >= 0 && S.selShot < shots.length ? S.selShot : shots.length - 1;
  return { ...shots[i], i };
}

function reviewLabelText(shot) {
  return `PODGLĄD ${shot.i + 1}/${S.state.shots.length} — ${shot.file} · ← → zmiana · BACKSPACE usuwa · ESC zamyka podgląd`;
}

function reviewOverlay() {
  const shot = S.reviewMode ? reviewShot() : null;
  if (!shot) return "";
  const sess = encodeURIComponent(S.state.session.name);
  return `
  <div id="review-wrap" style="position: absolute; inset: 0; background: #161618; pointer-events: auto; transition: opacity .2s ease, transform .2s ease;">
    <img src="/img?s=${sess}&f=${encodeURIComponent(shot.file)}" style="position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain; animation: reviewIn .2s ease-out;" />
    <div id="review-label" style="position: absolute; left: 12px; bottom: 12px; background: rgba(0,0,0,.55); border: 1px solid #3c3c44; padding: 3px 8px; ${mono} font-size: 10.5px; color: #d0d0d6;">${reviewLabelText(shot)}</div>
  </div>`;
}

function navShot(dir) {
  const list = S.state.shots;
  if (!list.length) return;
  const cur = S.selShot < 0 ? list.length : S.selShot;
  const next = Math.max(0, Math.min(list.length - 1, cur + dir));
  if (next === S.selShot) return;
  S.selShot = next;
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
    img.style.transition = "none";
    img.style.transform = `translateX(${dir * 6}px)`;
    requestAnimationFrame(() => requestAnimationFrame(() => {
      img.style.transition = "transform .22s ease-out";
      img.style.transform = "none";
    }));
    [next - 1, next + 1].forEach(i => {
      if (list[i]) new Image().src = `/img?s=${sess}&f=${encodeURIComponent(list[i].file)}`;
    });
    const strip = $("filmstrip");
    if (strip) strip.innerHTML = filmstrip();
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
    const strip = $("filmstrip");
    if (strip) strip.innerHTML = filmstrip();
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
    <div onclick="S.selShot = ${i}; S.reviewMode = true; renderScreens()" style="width: 104px; flex: 0 0 104px;">
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
  S.gridOn, S.kadrOn, S.reviewMode]);

function renderShell(force) {
  const st = S.state;
  const u = st.update || {};
  // progress pobierania NIE jest w kluczu — łata go updateVolatile(), bo
  // rebuild shella niszczy <img> streamu (miganie przy każdym procencie)
  const key = JSON.stringify([S.screen, st.connected,
    u.available, u.busy, u.canApply, S.updateDismissed]);
  if (force || key !== lastShellKey) {
    lastShellKey = key;
    const focused = document.activeElement && document.activeElement.id;
    $("app").innerHTML = shell();
    lastSesja = lastUstawienia = "";
    renderScreens(true);
    if (focused === "session-input") $("session-input").focus();
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
  const bgColor = st.camera.bgOk ? "#9fe0a8" : "#e0b96a";
  const hist = $("hist-badge");
  if (hist) {
    hist.textContent = st.camera.bgOk ? "HISTOGRAM OK" : "HISTOGRAM !";
    hist.style.color = bgColor;
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
    const key = JSON.stringify(["start", st.automat, S.pendingNew]);
    if (force || key !== lastSesja) {
      const el = document.activeElement;
      const editing = el && el.id === "new-session-input";
      const keep = editing ? el.value : null;
      lastSesja = key;
      $("screen-sesja").innerHTML = startScreen();
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
      const el = document.activeElement;
      const editing = el && (el.id === "session-input") && el.value !== st.session.name;
      const keep = editing ? el.value : null;
      $("screen-sesja").innerHTML = sesjaScreen();
      if (keep !== null) { const i = $("session-input"); i.value = keep; i.focus(); }
      const strip = $("filmstrip");
      if (strip) strip.scrollLeft = strip.scrollWidth;
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

function commitName() {
  const v = $("session-input").value.trim();
  if (v) post({ action: "set_session", name: v });
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
    if (e.key === "Enter") {
      const id = document.activeElement.id;
      if (id === "session-input") {
        commitName();
        document.activeElement.blur();
      } else if (id === "new-session-input") {
        commitNewSession();
      }
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
