"use strict";
// Ekran startowy: lista sesji photo_studio z Automatu, układ jak Photo Studio
// (lewa oś dni + kafelki grupowane nagłówkami dat) i pole „Rozpocznij sesję".

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

const PL_WEEKDAYS = ["niedziela", "poniedziałek", "wtorek", "środa", "czwartek", "piątek", "sobota"];
const PL_MONTHS_SHORT = ["sty", "lut", "mar", "kwi", "maj", "cze", "lip", "sie", "wrz", "paź", "lis", "gru"];
const PL_MONTHS_NOM = ["Styczeń", "Luty", "Marzec", "Kwiecień", "Maj", "Czerwiec",
  "Lipiec", "Sierpień", "Wrzesień", "Październik", "Listopad", "Grudzień"];

// Nagłówek dnia w liście: „Dziś" / „Wczoraj" / data, obok dzień tygodnia.
function dayHeading(g) {
  if (isNaN(g.date)) return { title: "Bez daty", sub: plSessions(g.items.length) };
  const t = new Date(), y = new Date(t.getFullYear(), t.getMonth(), t.getDate() - 1);
  const same = (a, b) => a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
  const wd = PL_WEEKDAYS[g.date.getDay()];
  const title = same(g.date, t) ? "Dziś" : same(g.date, y) ? "Wczoraj" : plDay(g.date);
  const sub = title === plDay(g.date) ? `${wd} · ${plSessions(g.items.length)}`
    : `${wd}, ${g.date.getDate()} ${PL_MONTHS[g.date.getMonth()]} · ${plSessions(g.items.length)}`;
  return { title, sub };
}

function sessionCard(s, idx) {
  // okładkę robi backend (photos/.covers) — dopóki jej nie ma, kafelek pokazuje
  // szkielet i wypełni się sam przy kolejnym poll-u
  const cover = s.cover
    ? `<img src="/img?cover=${s.id}" alt="" style="position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain;" />`
    : `<div class="${s.photos_count ? "skeleton" : ""}" style="position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; ${mono} font-size: 11px; color: var(--muted-2); background-color: var(--surface-2);">${s.photos_count ? "" : "bez zdjęć"}</div>`;
  const product = s.product ? s.product.name : "Sesja luźna";
  const pColor = s.product ? "var(--ok-fg)" : "var(--muted-2)";
  const d = new Date(s.created_at);
  // podswietlenie (hover i zaznaczenie klawiatura) idzie JEDNYM stanem:
  // S.pickIdx + paintPick() — dwie osobne mechaniki gryzly sie o ramke
  return `
  <div data-pick="${idx}" class="session-card${idx === S.pickIdx ? " picked" : ""}" onclick='pickSession(${s.id}, ${JSON.stringify(s.name)})' onmouseover="pickTo(${idx})">
    <div class="cover">
      ${cover}
      ${s.photos_count ? `<span class="cover-badge">${s.photos_count} zdj.</span>` : ""}
    </div>
    <div style="padding: 10px 12px 12px; display: flex; flex-direction: column; gap: 4px; min-width: 0;">
      <div style="font-size: 13.5px; font-weight: 600; line-height: 1.3; color: var(--text); overflow-wrap: anywhere;">${s.name}</div>
      <div style="display: flex; align-items: baseline; gap: 6px; font-size: 12px; line-height: 1.35; color: ${pColor};">
        <span style="width: 6px; height: 6px; flex-shrink: 0; border-radius: 50%; background: ${pColor}; transform: translateY(-1px);"></span><span style="overflow-wrap: anywhere;">${product}</span>
      </div>
      <div style="${mono} font-size: 11px; color: var(--muted-2);">${isNaN(d) ? "" : hhmm(d)}</div>
    </div>
  </div>`;
}

// Lewy panel: dni pogrupowane miesiącami, przy każdym liczba sesji.
function dayRail(groups) {
  let month = "";
  return groups.map(g => {
    const m = isNaN(g.date) ? "Bez daty" : `${PL_MONTHS_NOM[g.date.getMonth()]} ${g.date.getFullYear()}`;
    const headHtml = m !== month
      ? `<div class="eyebrow" style="padding: ${month ? "16px" : "0"} 10px 8px;">${m}</div>` : "";
    month = m;
    return `${headHtml}
    <div class="day-row${S.dayFocus === g.key ? " on" : ""}" onclick="focusDay('${g.key}')">
      <span class="cal" aria-hidden="true"><span class="cal-m">${isNaN(g.date) ? "" : PL_MONTHS_SHORT[g.date.getMonth()]}</span><span class="cal-d">${isNaN(g.date) ? "—" : g.date.getDate()}</span></span>
      <span class="day-wd">${isNaN(g.date) ? "bez daty" : PL_WEEKDAYS[g.date.getDay()]}</span>
      <span class="count">${g.items.length} ${plForm(g.items.length, "sesja", "sesje", "sesji")}</span>
    </div>`;
  }).join("");
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
  // wyszukiwanie od razu zaznacza pierwszy wynik — ENTER wchodzi w niego
  // bez odrywania rak od klawiatury; zadnego aktywnego filtra = brak zaznaczenia
  S.pickIdx = anyFilter() ? 0 : -1;
  // rebuild jest tani (lista to dziesiatki kafelkow), a fokus i wartosc pola
  // przezywaja go przez mechanizm w renderScreens (jak new-session-input)
  renderScreens(true);
}

// ---------- zaznaczenie kafelka (strzalki / hover / ENTER) ----------
// pickIdx to indeks w S.pickList (widoczne sesje w kolejnosci wyswietlania);
// zmiana zaznaczenia tylko przemalowuje ramki (paintPick), zero rebuildow.

function paintPick() {
  document.querySelectorAll("[data-pick]").forEach(el => {
    el.classList.toggle("picked", +el.dataset.pick === S.pickIdx);
  });
}

function pickTo(i) {
  if (i === S.pickIdx) return;
  S.pickIdx = i;
  paintPick();
}

function movePick(d) {
  const n = (S.pickList || []).length;
  if (!n) return;
  S.pickIdx = S.pickIdx < 0
    ? (d > 0 ? 0 : n - 1)
    : Math.max(0, Math.min(n - 1, S.pickIdx + d));
  paintPick();
  const el = document.querySelector(`[data-pick="${S.pickIdx}"]`);
  if (el) el.scrollIntoView({ block: "nearest" });
}

// Strzałki góra/dół: kafelek w rzędzie wyżej/niżej, najbliższy w poziomie.
// Liczone z położenia na ekranie — dni mają różną liczbę kafelków w rzędzie,
// więc „±liczba kolumn" w liście trafiałby w złe miejsce.
function movePickVertical(d) {
  const cards = [...document.querySelectorAll("[data-pick]")];
  const cur = cards.find(c => +c.dataset.pick === S.pickIdx);
  if (!cur) { movePick(d); return; }
  const r = cur.getBoundingClientRect(), cx = r.left + r.width / 2;
  const rows = cards.map(c => ({ c, b: c.getBoundingClientRect() }))
    .filter(x => d < 0 ? x.b.top < r.top - 4 : x.b.top > r.top + 4);
  if (!rows.length) return;
  // najbliższy rząd w danym kierunku, w nim kafelek najbliżej w poziomie
  const rowTop = d < 0 ? Math.max(...rows.map(x => x.b.top)) : Math.min(...rows.map(x => x.b.top));
  const best = rows.filter(x => Math.abs(x.b.top - rowTop) < 4)
    .sort((a, b) => Math.abs(a.b.left + a.b.width / 2 - cx) - Math.abs(b.b.left + b.b.width / 2 - cx))[0];
  S.pickIdx = +best.c.dataset.pick;
  paintPick();
  best.c.scrollIntoView({ block: "nearest" });
}

function openPicked() {
  const s = (S.pickList || [])[S.pickIdx];
  if (s) pickSession(s.id, s.name);
}

// ---------- „Odśwież listę" ze spinnerem ----------
// Flaga z backendu (state.automat.refreshing, ustawiana JUZ w akcji) +
// minimum ~650 ms po kliknieciu po stronie frontu — odpowiedz potrafi wrocic
// szybciej niz poll 500 ms i spinner mignalby bez sladu (wzor: checkStartedAt
// przy „Sprawdz aktualizacje"). Przycisk lata updateVolatile() po data-busy.

function refreshingNow(st) {
  // refreshStartedAt = 0 znaczy „nigdy nie kliknieto" — bez tego guardu
  // performance.now() < 650 na starcie strony zapiekalo spinner w pierwszym
  // renderze na stale (data-busy z szablonu nie zmienial sie juz nigdy)
  return !!(st && st.automat && st.automat.refreshing)
    || (S.refreshStartedAt > 0 && performance.now() - S.refreshStartedAt < 650);
}

function refreshBtnHtml() {
  return refreshingNow(S.state) ? '<span class="spinner"></span>' : icon("refresh");
}

function refreshSessions() {
  if (refreshingNow(S.state)) return;
  S.refreshStartedAt = performance.now();
  post({ action: "refresh_sessions" });
  const b = $("refresh-btn");
  if (b) {
    b.dataset.busy = "1";
    b.innerHTML = refreshBtnHtml();
  }
}

// Czy ktorykolwiek filtr listy jest aktywny (tekst / min-max zdjec / data).
const anyFilter = () => !!((S.sessionFilter || "").trim()
  || (S.photosMin || "").trim() || (S.photosMax || "").trim() || S.dateFilter);

/** Filtry poza polem tekstowym (min/max zdjec, data) — zmiana = rebuild. */
function setStartFilter(key, v) {
  if (key === "min") S.photosMin = v;
  else if (key === "max") S.photosMax = v;
  else S.dateFilter = v;
  S.pickIdx = anyFilter() ? 0 : -1;
  renderScreens(true);
}

function matchesFilters(s, q, now) {
  if (q && !((s.name || "").toLowerCase().includes(q)
             || ((s.product && s.product.name) || "").toLowerCase().includes(q)))
    return false;
  const mn = parseInt(S.photosMin, 10);
  if (!isNaN(mn) && s.photos_count < mn) return false;
  const mx = parseInt(S.photosMax, 10);
  if (!isNaN(mx) && s.photos_count > mx) return false;
  if (S.dateFilter) {
    const d = new Date(s.created_at);
    if (isNaN(d)) return false;
    if (S.dateFilter === "today") {
      const t = new Date();
      if (d.getFullYear() !== t.getFullYear() || d.getMonth() !== t.getMonth()
          || d.getDate() !== t.getDate()) return false;
    } else if (now - d.getTime() > +S.dateFilter * 86400000) {
      return false;
    }
  }
  return true;
}

function startScreen() {
  const a = S.state.automat;
  const q = (S.sessionFilter || "").trim().toLowerCase();
  const now = Date.now();
  const visible = anyFilter()
    ? a.sessions.filter(s => matchesFilters(s, q, now))
    : a.sessions;
  S.pickList = visible;
  if (S.pickIdx >= visible.length) S.pickIdx = visible.length ? 0 : -1;
  const groups = groupByDay(visible);
  let pi = 0;
  const feed = groups.map(g => {
    const h = dayHeading(g);
    return `
    <section id="day-${g.key}" style="display: flex; flex-direction: column; gap: 12px; scroll-margin-top: 8px;">
      <h2 style="margin: 0; display: flex; align-items: baseline; gap: 10px; font-size: 15px; font-weight: 700; color: var(--text);">${h.title} <span style="font-size: 12.5px; font-weight: 500; color: var(--muted-2);">${h.sub}</span></h2>
      <div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(168px, 1fr)); gap: 16px; align-content: start;">
        ${g.items.map(s => sessionCard(s, pi++)).join("")}
      </div>
    </section>`;
  }).join("")
    || (anyFilter() && a.sessions.length
        ? `<div style="font-size: 13px; color: var(--muted-2);">Żadna sesja nie pasuje do filtrów.</div>`
        : "");
  const info = !a.hasToken
    ? `<div style="font-size: 12.5px; color: var(--warn-fg-3);">Brak tokenu API (.env albo Ustawienia). Sesje z API są niedostępne, możesz utworzyć lokalną.</div>`
    : a.error
      ? `<div style="font-size: 12.5px; color: var(--err-fg);">✗ ${a.error}</div>`
      : a.sessions.length === 0
        ? `<div style="font-size: 12.5px; color: var(--muted-2);">Ładuję sesje z API…</div>`
        : "";
  const p = S.pendingNew;
  const pend = !p ? "" : `
    <div style="background: var(--warn-soft); border: 1px solid var(--warn-border); border-radius: 10px; padding: 12px 14px; display: flex; flex-direction: column; gap: 10px;">
      <div style="font-size: 13px; color: var(--text);">Sesja <b>${p.match.name}</b> już istnieje w API (${fmtDate(p.match.created_at)}, zdjęć: ${p.match.photos_count}).</div>
      <div style="display: flex; gap: 8px; flex-wrap: wrap;">
        <button type="button" class="btn btn-primary btn-sm" onclick="resolvePending(true)">Podłącz do istniejącej</button>
        <button type="button" class="btn btn-sm" onclick="resolvePending(false)">Utwórz nową</button>
        <button type="button" class="btn btn-sm" onclick="S.pendingNew = null; renderScreens(true)">Anuluj</button>
      </div>
    </div>`;
  const total = visible.reduce((n, s) => n + (s.photos_count || 0), 0);
  const period = (v, text) => `<button type="button" class="seg-btn${S.dateFilter === v ? " on" : ""}" aria-pressed="${S.dateFilter === v}" onclick="segClick(this); setStartFilter('date', '${v}')" tabindex="-1">${text}</button>`;
  return `
  <div style="flex: 1; display: flex; min-width: 0; background: var(--ground);">

    <aside style="width: 232px; flex: 0 0 232px; box-sizing: border-box; padding: 20px 12px; border-right: 1px solid var(--border); background: var(--surface-2); display: flex; flex-direction: column; gap: 4px; overflow-y: auto; overflow-x: hidden;">
      ${dayRail(groups)}
    </aside>

    <div style="flex: 1; min-width: 0; display: flex; flex-direction: column;">
      <div id="start-scroll" style="flex: 1; min-height: 0; overflow-y: auto; overflow-x: hidden; padding: 24px 32px 28px; display: flex; flex-direction: column; gap: 20px;">

        <section aria-label="Nowa sesja" class="panel" style="padding: 20px 22px; display: flex; flex-direction: column; gap: 12px;">
          <div style="display: flex; align-items: flex-end; gap: 20px;">
            <div style="display: flex; flex-direction: column; gap: 4px; width: 210px; flex-shrink: 0; align-self: center;">
              <div style="font-size: 17px; font-weight: 700; letter-spacing: -.01em; color: var(--text);">Nowa sesja</div>
              <div style="font-size: 12.5px; line-height: 1.45; color: var(--muted);">Nazwa trafia do folderu i do API. Produkt dopasuje się sam.</div>
            </div>
            <div style="flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 6px;">
              <label for="new-session-input" style="font-size: 12px; font-weight: 500; color: var(--text-2);">Nazwa produktu</label>
              <input id="new-session-input" class="field" placeholder="np. right switch r148" style="height: 44px; border-radius: 10px; font-size: 14px; padding: 0 14px;" />
            </div>
            <button type="button" class="btn btn-primary" onclick="commitNewSession()" tabindex="-1" style="height: 44px; padding: 0 20px; border-radius: 10px; font-size: 14px;">Rozpocznij sesję <span class="kbd">ENTER</span></button>
          </div>
          ${info}
          ${pend}
        </section>

        <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">
          <div style="position: relative; width: 280px;">
            <span style="position: absolute; left: 11px; top: 10px; color: var(--muted-2);">${icon("search", 16, 1.8)}</span>
            <input id="session-filter" class="field" type="search" aria-label="Szukaj sesji" placeholder="Szukaj sesji lub produktu" value="${(S.sessionFilter || "").replace(/"/g, "&quot;")}" oninput="filterSessions(this.value)" style="width: 100%; padding-left: 34px; font-family: inherit; font-size: 13px;" />
          </div>
          <div id="period-seg" class="seg seg-sm has-pill" role="group" aria-label="Okres">
            <span class="seg-pill"></span>
            ${period("", "Wszystkie")}${period("today", "Dziś")}${period("7", "7 dni")}${period("30", "30 dni")}
          </div>
          <div style="display: flex; align-items: center; gap: 6px; font-size: 12.5px; color: var(--muted);">
            Zdjęć
            <input id="photos-min" class="field" inputmode="numeric" aria-label="Najmniej zdjęć" placeholder="od" value="${S.photosMin}" oninput="setStartFilter('min', this.value)" tabindex="-1" style="width: 56px; height: 34px; text-align: center; padding: 0 6px;" />
            –
            <input id="photos-max" class="field" inputmode="numeric" aria-label="Najwięcej zdjęć" placeholder="do" value="${S.photosMax}" oninput="setStartFilter('max', this.value)" tabindex="-1" style="width: 56px; height: 34px; text-align: center; padding: 0 6px;" />
          </div>
          <div style="flex: 1;"></div>
          <span style="font-size: 12px; color: var(--muted-2);">${visible.length} ${plForm(visible.length, "sesja", "sesje", "sesji")} · ${plPhotos(total)}</span>
          <button type="button" id="refresh-btn" class="icon-btn" onclick="refreshSessions()" tabindex="-1" aria-label="Odśwież listę z API" title="Odśwież listę z API" data-busy="${refreshingNow(S.state) ? "1" : ""}" style="width: 36px; height: 36px; border-color: var(--border-strong); border-radius: 9px;">${refreshBtnHtml()}</button>
        </div>

        ${feed}
      </div>

      <footer class="hints" style="flex: 0 0 auto; padding: 10px 32px 12px; border-top: 1px solid var(--border); font-size: 12px;">
        <span>${kHint("← → ↑ ↓")}wybór sesji</span>
        <span>${kHint("ENTER")}otwórz</span>
        <span>${kHint(modKey("F"))}szukaj</span>
        <span>${kHint(modKey("N"))}nowa sesja</span>
      </footer>
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
  S.sessionFilter = S.photosMin = S.photosMax = S.dateFilter = "";
  post({ action: "set_session", name: v });
}

function pickSession(id, name) {
  S.pendingNew = null;
  S.sessionFilter = S.photosMin = S.photosMax = S.dateFilter = "";
  post({ action: "set_session", name, session_id: id });
}

function resolvePending(attach) {
  const p = S.pendingNew;
  S.pendingNew = null;
  if (!p) return;
  S.sessionFilter = S.photosMin = S.photosMax = S.dateFilter = "";
  if (attach) post({ action: "set_session", name: p.match.name, session_id: p.match.id });
  else post({ action: "set_session", name: p.name });
}
