"use strict";
// Wyszukiwarka sesji pod ⌘K / Ctrl+K — z każdego ekranu (lista, sesja,
// podgląd, Ustawienia). Układ jak command palette z Tailwind Plus: okno przy
// górnej krawędzi, pole z lupą, wyniki z okładką, tytułem i opisem, stan
// „brak wyników". Bez Tailwind Elements z CDN: aplikacja działa offline,
// więc dialog, filtrowanie i klawiatura są tutaj.
//
// Okno żyje w <body>, poza renderem #app (jak modal wyjścia z sesji), więc
// przebudowy ekranu go nie zamykają. Klawisze obsługuje samo pole wyszukiwania;
// globalny listener w app-main.js tylko otwiera/zamyka i nie strzela zza okna.

Object.assign(I18N_EN, {
  "Szukaj sesji": "Search sessions",
  "Szukaj sesji lub produktu…": "Search sessions or products…",
  "Ostatnie sesje": "Recent sessions",
  "Wyniki": "Results",
  "Nowa sesja „{name}”": "New session “{name}”",
  "Utwórz sesję o tej nazwie": "Create a session with this name",
  "Brak wyników": "No results",
  "Żadna sesja ani produkt nie pasuje do „{q}”.": "No session or product matches “{q}”.",
  "Brak sesji z API. Sprawdź token w Ustawieniach.": "No sessions from the API. Check the token in Settings.",
  "otwarta": "open",
  "wybór": "select",
  "otwórz": "open",
  "zamknij": "close",
  "wyszukiwarka sesji (wszędzie)": "search sessions (anywhere)",
});


const PALETTE_MAX = 50;
const foldText = s => String(s || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/ł/g, "l");

function paletteItems(q) {
  const all = ((S.state && S.state.automat && S.state.automat.sessions) || []).slice()
    .sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || "")));
  const f = foldText(q.trim());
  // Najpierw trafność, potem data (sort stabilny, lista już jest od najnowszych):
  // nazwa równa wpisanej > nazwa zaczyna się od niej > słowo w nazwie się od
  // niej zaczyna > gdzieś w nazwie > tylko w nazwie produktu. Do tego im
  // większą część nazwy pokrywa wpis, tym wyżej („duplo" przed „proste duplo").
  const score = s => {
    const name = foldText(s.name);
    if (name === f) return 100;
    let base = name.startsWith(f) ? 80 : new RegExp(`(^|[^a-z0-9])${f.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`).test(name) ? 60
      : name.includes(f) ? 40 : foldText(s.product && s.product.name).includes(f) ? 10 : 0;
    return base ? base + Math.round(f.length / Math.max(name.length, 1) * 10) : 0;
  };
  const found = f
    ? all.map(s => [score(s), s]).filter(([sc]) => sc > 0).sort((a, b) => b[0] - a[0]).map(([, s]) => s)
    : all.slice(0, 8);
  const items = found.slice(0, PALETTE_MAX).map(s => ({ kind: "session", s }));
  // wpisana nazwa bez dokładnego odpowiednika = można od razu założyć sesję
  const typed = q.trim();
  if (typed && !all.some(s => foldText(s.name) === f)) items.push({ kind: "new", name: typed });
  return items;
}

function paletteItemHtml(it, i) {
  const on = i === S.paletteIdx ? " on" : "";
  if (it.kind === "new") {
    return `
      <div class="pal-item${on}" data-i="${i}" role="option" aria-selected="${!!on}" onmousemove="paletteHover(${i})" onclick="palettePick(${i})">
        <div class="pal-thumb pal-thumb-new">${icon("pencil", 20, 1.6)}</div>
        <div class="pal-text">
          <div class="pal-title">${t("Nowa sesja „{name}”", { name: escapeHtml(it.name) })}</div>
          <div class="pal-sub">${t("Utwórz sesję o tej nazwie")}</div>
        </div>
      </div>`;
  }
  const s = it.s;
  // po numerze w API, nie po nazwie: ta sama nazwa wraca co dzień jako nowa sesja
  const cur = S.state.session || {};
  const current = cur.name && (cur.apiId ? cur.apiId === s.id : foldText(cur.name) === foldText(s.name));
  const d = new Date(s.created_at);
  const q = ($("pal-input") || {}).value || "";
  const bits = [s.product ? markMatch(s.product.name, q) : t("Sesja luźna"), plPhotos(s.photos_count || 0)];
  if (!isNaN(d)) bits.push(plDay(d));
  return `
    <div class="pal-item${on}" data-i="${i}" role="option" aria-selected="${!!on}" onmousemove="paletteHover(${i})" onclick="palettePick(${i})">
      <div class="pal-thumb">${s.photos_count ? `<img src="/img?cover=${s.id}" alt="" loading="lazy" onerror="this.remove()" />` : ""}${icon("camera", 20, 1.6)}</div>
      <div class="pal-text">
        <div class="pal-title">${markMatch(s.name, q)}${current ? ` <span class="pal-tag">${t("otwarta")}</span>` : ""}</div>
        <div class="pal-sub">${bits.join(" · ")}</div>
      </div>
    </div>`;
}

// Pasujący fragment w lekkim podświetleniu. foldText zachowuje długość
// (ą→a, ł→l: jeden znak na jeden), więc indeks z tekstu bez ogonków trafia
// w ten sam fragment oryginału.
function markMatch(text, q) {
  const raw = String(text == null ? "" : text), f = foldText(q.trim());
  const at = f ? foldText(raw).indexOf(f) : -1;
  if (at < 0) return escapeHtml(raw);
  return escapeHtml(raw.slice(0, at)) + `<mark class="pal-mark">${escapeHtml(raw.slice(at, at + f.length))}</mark>` + escapeHtml(raw.slice(at + f.length));
}

const escapeHtml = s => String(s == null ? "" : s).replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

function paletteRender() {
  const box = $("pal-results");
  if (!box) return;
  const q = $("pal-input").value;
  S.paletteList = paletteItems(q);
  if (S.paletteIdx >= S.paletteList.length) S.paletteIdx = S.paletteList.length - 1;
  if (S.paletteIdx < 0 && S.paletteList.length) S.paletteIdx = 0;
  const hasToken = S.state.automat && S.state.automat.hasToken;
  if (!S.paletteList.length) {
    box.innerHTML = `
      <div class="pal-empty">
        ${icon("search", 24, 1.5)}
        <p class="pal-empty-title">${t("Brak wyników")}</p>
        <p class="pal-empty-text">${q.trim() ? t("Żadna sesja ani produkt nie pasuje do „{q}”.", { q: escapeHtml(q.trim()) })
          : (hasToken ? "" : t("Brak sesji z API. Sprawdź token w Ustawieniach."))}</p>
      </div>`;
    return;
  }
  box.innerHTML = `<div class="pal-head">${q.trim() ? t("Wyniki") : t("Ostatnie sesje")}</div>`
    + S.paletteList.map(paletteItemHtml).join("");
}

function paletteHover(i) {
  if (i === S.paletteIdx) return;
  S.paletteIdx = i;
  document.querySelectorAll("#pal-results .pal-item").forEach(el => {
    const on = +el.dataset.i === i;
    el.classList.toggle("on", on);
    el.setAttribute("aria-selected", on);
  });
}

function paletteMove(d) {
  const n = (S.paletteList || []).length;
  if (!n) return;
  paletteHover((S.paletteIdx + d + n) % n);
  const el = document.querySelector(`#pal-results .pal-item[data-i="${S.paletteIdx}"]`);
  if (el) el.scrollIntoView({ block: "nearest" });
}

function palettePick(i) {
  const it = (S.paletteList || [])[i];
  if (!it) return;
  hidePalette();
  if (S.leaveConfirm) hideLeaveConfirm();
  if (S.reviewMode) closeReview();
  S.pendingNew = null;
  S.sessionFilter = S.photosMin = S.photosMax = S.dateFilter = "";
  if (it.kind === "new") post({ action: "set_session", name: it.name });
  else post({ action: "set_session", name: it.s.name, session_id: it.s.id });
  if (S.screen !== "sesja") go("sesja");
}

function paletteKey(e) {
  if (e.key === "ArrowDown") { e.preventDefault(); paletteMove(1); }
  else if (e.key === "ArrowUp") { e.preventDefault(); paletteMove(-1); }
  else if (e.key === "Enter") { e.preventDefault(); palettePick(S.paletteIdx); }
  else if (e.key === "Escape") { e.preventDefault(); hidePalette(); }
}

function showPalette() {
  if ($("palette")) return;
  S.palette = true;
  S.paletteIdx = 0;
  const el = document.createElement("div");
  el.id = "palette";
  el.className = "ui modal-root palette-root";
  el.setAttribute("role", "dialog");
  el.setAttribute("aria-modal", "true");
  el.setAttribute("aria-label", t("Szukaj sesji"));
  el.innerHTML = `
    <div class="modal-panel palette-panel">
      <div class="pal-search">
        ${icon("search", 20, 1.7)}
        <input id="pal-input" type="text" autocomplete="off" spellcheck="false" placeholder="${t("Szukaj sesji lub produktu…")}"
               oninput="S.paletteIdx = 0; paletteRender()" onkeydown="paletteKey(event)" />
        <span class="kbd">ESC</span>
      </div>
      <div id="pal-results" class="pal-results" role="listbox"></div>
      <div class="pal-foot">
        <span><span class="kbd">↑</span><span class="kbd">↓</span> ${t("wybór")}</span>
        <span><span class="kbd">ENTER</span> ${t("otwórz")}</span>
        <span><span class="kbd">ESC</span> ${t("zamknij")}</span>
      </div>
    </div>`;
  // klik w przyciemnione tło = zamknij
  el.addEventListener("mousedown", ev => { if (ev.target === el) hidePalette(); });
  document.body.appendChild(el);
  paletteRender();
  $("pal-input").focus();
  requestAnimationFrame(() => requestAnimationFrame(() => el.classList.add("open")));
}

function hidePalette() {
  S.palette = false;
  const el = $("palette");
  if (!el) return;
  el.classList.remove("open");
  el.classList.add("closing");
  setTimeout(() => el.remove(), 130);
}

function togglePalette() { S.palette ? hidePalette() : showPalette(); }
