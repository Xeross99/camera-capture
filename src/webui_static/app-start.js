"use strict";
// Ekran startowy: lista sesji photo_studio z Automatu, układ jak Photo Studio
// (lewa oś dni + kafelki grupowane nagłówkami dat) i pole „Utwórz i otwórz".

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
    <div style="position: relative; aspect-ratio: 1 / 1; background: #fff;">${cover}</div>
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

/** Filtr listy sesji (male pole po prawej): nazwa sesji albo nazwa produktu. */
function filterSessions(v) {
  S.sessionFilter = v;
  // rebuild jest tani (lista to dziesiatki kafelkow), a fokus i wartosc pola
  // przezywaja go przez mechanizm w renderScreens (jak new-session-input)
  renderScreens(true);
}

function startScreen() {
  const a = S.state.automat;
  const q = (S.sessionFilter || "").trim().toLowerCase();
  const visible = !q ? a.sessions : a.sessions.filter(s =>
    (s.name || "").toLowerCase().includes(q)
    || ((s.product && s.product.name) || "").toLowerCase().includes(q));
  const groups = groupByDay(visible);
  const feed = groups.map(g => `
    <div id="day-${g.key}" style="display: flex; flex-direction: column; gap: 12px; scroll-margin-top: 6px;">
      <div style="display: flex; align-items: baseline; gap: 8px;">
        <div style="font-size: 13px; font-weight: 600; color: #d6d6db;">${isNaN(g.date) ? "bez daty" : plDay(g.date)}</div>
        <div style="${mono} font-size: 10.5px; color: #77777f;">· ${plSessions(g.items.length)}</div>
      </div>
      <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(190px, 1fr)); gap: 14px; align-content: start;">
        ${g.items.map(sessionCard).join("")}
      </div>
    </div>`).join("")
    || (q && a.sessions.length
        ? `<div style="${mono} font-size: 11px; color: #7e7e85;">Żadna sesja nie pasuje do „${S.sessionFilter.trim()}".</div>`
        : "");
  const info = !a.hasToken
    ? `<div style="${mono} font-size: 11px; color: #e0b96a;">Brak tokenu Automatu (.env / Ustawienia) — sesje z Automatu niedostępne, możesz utworzyć lokalną.</div>`
    : a.error
      ? `<div style="${mono} font-size: 11px; color: #e07a7a;">✗ ${a.error}</div>`
      : a.sessions.length === 0
        ? `<div style="${mono} font-size: 11px; color: #7e7e85;">Ładuję sesje z Automatu…</div>`
        : "";
  const p = S.pendingNew;
  const pend = !p ? "" : `
    <div style="background: #26231d; border: 1px solid #5a4a2a; border-radius: 6px; padding: 12px 14px; display: flex; flex-direction: column; gap: 10px; width: 100%; max-width: 660px; box-sizing: border-box;">
      <div style="font-size: 12.5px; color: #e8e8ea;">Sesja <b>${p.match.name}</b> już istnieje w Automacie (${fmtDate(p.match.created_at)}, zdjęć: ${p.match.photos_count}).</div>
      <div style="display: flex; gap: 8px; flex-wrap: wrap;">
        <button onclick="resolvePending(true)" style="height: 28px; padding: 0 14px; ${btnBlue} border-radius: 4px; font-size: 12px; font-weight: 600;">Podłącz do istniejącej</button>
        <button onclick="resolvePending(false)" style="${btnGray} height: 28px;">Utwórz nową</button>
        <button onclick="S.pendingNew = null; renderScreens(true)" style="${btnGray} height: 28px; opacity: .7;">Anuluj</button>
      </div>
    </div>`;
  return `
  <div style="flex: 1; display: flex; min-width: 0; background: #1d1d20;">

    <div style="flex: 0 0 216px; border-right: 1px solid #26262b; padding: 22px 12px 22px 18px; overflow-y: scroll; overflow-x: hidden;">
      <div style="${head} padding: 0 6px 10px;">Dni zdjęciowe</div>
      ${dayRail(groups)}
    </div>

    <div id="start-scroll" style="flex: 1; overflow-y: scroll; overflow-x: hidden; padding: 22px 26px 28px; display: flex; flex-direction: column; gap: 20px; min-width: 0;">
      <div style="display: flex; flex-direction: column; gap: 10px;">
        <div style="display: flex; flex-direction: column; align-items: center; gap: 10px; padding: 14px 0 2px;">
          <div style="${head}">Nowa sesja zdjęciowa</div>
          <div style="display: flex; gap: 10px; width: 100%; max-width: 660px;">
            <input id="new-session-input" placeholder="nazwa produktu…" style="flex: 1; min-width: 0; ${inp} height: 42px; font-size: 14.5px; padding: 0 14px; border-radius: 6px;" />
            <button onclick="commitNewSession()" style="flex-shrink: 0; height: 42px; padding: 0 24px; ${btnBlue} border-radius: 6px; font-size: 13.5px; font-weight: 600;">Utwórz i otwórz</button>
          </div>
          <div style="${mono} font-size: 10.5px; color: #77777f; text-align: center;">nazwa = folder w photos/ i sesja w Automacie (dopasowanie do produktu po nazwie)</div>
          ${info}
          ${pend}
        </div>
        <div style="display: flex; align-items: center; justify-content: flex-end; gap: 8px;">
          <button onclick="post({action: 'refresh_sessions'})" style="${btnGray} height: 26px; padding: 0 10px; font-size: 11px;">Odśwież listę</button>
          <input id="session-filter" placeholder="filtruj sesje…" value="${(S.sessionFilter || "").replace(/"/g, "&quot;")}" oninput="filterSessions(this.value)" style="${inp} width: 210px;" />
        </div>
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
