"use strict";
Object.assign(I18N_EN, {
  "Edytuj sesję": "Edit session",
  "Akcje sesji": "Session actions",
  "Zmień logo na zdjęciach…": "Change the logo on photos…",
  "Pokaż folder sesji": "Show the session folder",
  "Wróć do listy sesji": "Back to the session list",
  "Edycja sesji": "Session edit",
  "Wróć do sesji": "Back to session",
  "Zaznacz wszystkie": "Select all",
  "Odznacz wszystkie": "Deselect all",
  "Zaznaczone: {n} z {all}": "Selected: {n} of {all}",
  "Zastosuj do {n}": "Apply to {n}",
  "Zmieniam logo… {done} z {total}": "Changing the logo… {done} of {total}",
  "Logo zmieni się na wszystkich zaznaczonych zdjęciach. Zdjęcia w API zostaną podmienione.": "The logo changes on all selected photos. The photos in the API are replaced.",
  "bez oryginału - nie da się zmienić logo": "no original - the logo cannot be changed",
  "Zaznacz zdjęcia, na których zmienić logo.": "Select the photos to change the logo on.",
  "Pominięto {n} bez oryginału.": "Skipped {n} without an original.",
  "Brak oryginału": "No original",
  "Kolejka": "Queued",
  "W kolejce": "Queued",
  "Zmieniam logo…": "Changing the logo…",
  "Zapisuję…": "Saving…",
  "Nakładanie logo": "Applying logo",
  "Gotowe": "Done",
  "Gotowe - zmieniono {n}": "Done - changed {n}",
});

// ---------- edycja sesji: logo na wielu zdjęciach naraz ----------
// Okno na całą aplikację, poza keyowanym renderem (jak modal wyjścia), więc
// pollowe przebudowy go nie niszczą. S.sedit = {sel: Set plików, logo, pos,
// error}. Postęp przychodzi ze stanu (st.batchEdit) i jest łatany w miejscu.

const seditShots = () => (S.state && S.state.shots) || [];
const seditEditable = s => !!s.edit;

function openSessionEdit() {
  if ($("sedit") || !S.state || !S.state.session.name) return;
  const post_ = S.state.post;
  S.sedit = {
    sel: new Set(seditShots().filter(seditEditable).map(s => s.file)),
    logo: post_.logo ? post_.logoChoice : "",
    pos: post_.logoPosition,
    error: "",
    sig: "",
  };
  const el = document.createElement("div");
  el.id = "sedit";
  el.className = "ui sedit";
  el.setAttribute("role", "dialog");
  el.setAttribute("aria-modal", "true");
  el.setAttribute("aria-label", t("Edycja sesji"));
  document.body.appendChild(el);
  renderSessionEdit();
  // dwie klatki: pierwsza nakłada stan początkowy, dopiero potem przejście
  requestAnimationFrame(() => requestAnimationFrame(() => el.classList.add("open")));
}

function closeSessionEdit() {
  const el = $("sedit");
  S.sedit = null;
  if (!el) return;
  el.classList.remove("open");
  setTimeout(() => el.remove(), 260);
}

// Stan kafelka w trakcie edycji sesji: pierwszy plik z kolejki (worker bierze
// je po kolei, alfabetycznie) jest „w obróbce", reszta „w kolejce", a te,
// które właśnie zeszły z kolejki, dostają animację gotowego zdjęcia.
function seditTileState(file) {
  const be = S.state.batchEdit;
  const pending = (be && be.pending) || [];
  if (pending[0] === file) return " busy active";
  if (pending.includes(file)) return " busy queued";
  return S.sedit && S.sedit.fresh && S.sedit.fresh.has(file) ? " fresh" : "";
}

function seditTilesHtml() {
  return seditShots().map(s => {
    const ok = seditEditable(s);
    const on = ok && S.sedit.sel.has(s.file);
    return `
      <button type="button" class="sedit-tile${on ? " on" : ""}${ok ? "" : " off"}${seditTileState(s.file)}" data-sfile="${s.file}"
        role="checkbox" aria-checked="${on}" ${ok ? "" : `aria-disabled="true" title="${t("bez oryginału - nie da się zmienić logo")}"`}
        onclick="seditToggle('${s.file}', event)">
        <img src="${shotUrl(s, true)}" alt="" loading="lazy" draggable="false" />
        <span class="sedit-check">${icon("check", 14, 2.4)}</span>
        ${ok ? "" : `<span class="sedit-badge">${t("Brak oryginału")}</span>`}
        <span class="sedit-load"><span class="sedit-load-label"><span class="spinner"></span>${t("Zmieniam logo…")}</span></span>
        <span class="sedit-queued">${t("W kolejce")}</span>
      </button>`;
  }).join("");
}

function renderSessionEdit() {
  const el = $("sedit"), ed = S.sedit;
  if (!el || !ed) return;
  const post_ = S.state.post;
  el.innerHTML = `
    <div class="sedit-main">
      <div class="viewer-bar">
        <button type="button" class="vbtn" onclick="closeSessionEdit()">${icon("arrowLeft", 16, 1.8)}${t("Wróć do sesji")}<span class="kbd">ESC</span></button>
        <div style="display: flex; align-items: baseline; gap: 10px; min-width: 0;">
          <span style="font-size: 15px; font-weight: 700;">${t("Edycja sesji")}</span>
          <span style="font-size: 13px; color: var(--viewer-fg-2); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${S.state.session.name}</span>
        </div>
        <div style="flex: 1;"></div>
        <button type="button" id="sedit-all" class="vbtn" onclick="seditAll()"><span id="sedit-all-label"></span><span id="sedit-count" class="kbd"></span></button>
      </div>
      <div class="sedit-grid" id="sedit-grid" onpointerdown="seditDragStart(event)">${seditTilesHtml()}</div>
    </div>
    <aside class="edit-panel sedit-panel" aria-label="${t("Edycja sesji")}">
      ${drawerHead(t("Logo"), t("Logo zmieni się na wszystkich zaznaczonych zdjęciach. Zdjęcia w API zostaną podmienione."), t("Wróć do sesji"), "closeSessionEdit()")}
      <section class="drawer-sec">
        ${logoTiles(post_.logos, ed.logo, "seditPickLogo", "data-blogo")}
      </section>
      <section class="drawer-sec">
        <h3>${t("Położenie")}</h3>
        <div id="sedit-corner" class="drawer-list drawer-pad" style="${ed.logo ? "" : "opacity: .4; pointer-events: none;"}">
          ${cornerRow(post_.logoPositions, ed.pos, "seditPickPos", "data-bcorner", "sedit-corner-seg")}
        </div>
      </section>
      <div style="flex: 1;"></div>
      <div id="sedit-progress" class="sedit-progress" role="status" hidden>
        <p id="sedit-progress-text" class="sedit-progress-title"></p>
        <div aria-hidden="true">
          <div class="sedit-bar"><span id="sedit-bar-fill"></span></div>
          <div class="sedit-steps">
            <div data-step="0">${t("Kolejka")}</div>
            <div data-step="1">${t("Nakładanie logo")}</div>
            <div data-step="2">${t("Gotowe")}</div>
          </div>
        </div>
      </div>
      <p id="sedit-error" class="field-err"></p>
      <div class="drawer-actions">
        <button type="button" id="sedit-apply" class="btn btn-primary" onclick="seditApply()"></button>
        <button type="button" class="btn" onclick="closeSessionEdit()">${t("Anuluj")}</button>
      </div>
    </aside>`;
  ed.sig = seditSig();
  placeSegPill($("sedit-corner-seg"), false);
  seditReconcile();
}

const seditSig = () => seditShots().map(s => `${s.file}@${s.v}@${s.edit}`).join("|");

// Łatka wołana z każdego pollu: kafelki (nowe miniatury po zmianie logo,
// kręciołki zdjęć w kolejce), licznik, postęp i stan przycisku.
function seditReconcile() {
  const ed = S.sedit;
  if (!ed || !$("sedit")) return;
  const files = new Set(seditShots().map(s => s.file));
  ed.sel.forEach(f => { if (!files.has(f)) ed.sel.delete(f); });   // skasowane w międzyczasie
  const be = S.state.batchEdit;
  const pendingNow = new Set((be && be.pending) || []);
  // zeszły z kolejki od ostatniego pollu = gotowe → animacja nowej miniatury
  (ed.prevPending || new Set()).forEach(f => {
    if (pendingNow.has(f)) return;
    ed.fresh = ed.fresh || new Set();
    ed.fresh.add(f);
    setTimeout(() => { if (ed.fresh) ed.fresh.delete(f); }, 1200);
  });
  ed.prevPending = pendingNow;
  const sig = seditSig();
  const grid = $("sedit-grid");
  if (grid && sig !== ed.sig) {
    const sc = grid.scrollTop;
    grid.innerHTML = seditTilesHtml();
    grid.scrollTop = sc;
    ed.sig = sig;
  }
  document.querySelectorAll("#sedit [data-sfile]").forEach(b => {
    const st = seditTileState(b.dataset.sfile);
    ["busy", "active", "queued"].forEach(c => b.classList.toggle(c, st.includes(c)));
  });
  const total = seditShots().filter(seditEditable).length;
  const n = ed.sel.size;
  $("sedit-count").textContent = `${n}/${seditShots().length}`;
  $("sedit-count").title = t("Zaznaczone: {n} z {all}", { n, all: seditShots().length });
  $("sedit-all-label").textContent = n && n === total ? t("Odznacz wszystkie") : t("Zaznacz wszystkie");
  const apply = $("sedit-apply");
  apply.disabled = !!be || !n;
  apply.innerHTML = be ? `<span class="spinner" style="border-color: rgba(255,255,255,.35); border-top-color: #fff;"></span>${t("Zapisuję…")}`
    : t("Zastosuj do {n}", { n: nWord(n, ["zdjęcia", "zdjęć", "zdjęć"], ["photo", "photos"]) });
  // Pasek nie znika razem z końcem kolejki (ostatnie zdjęcia schodzą w ułamku
  // sekundy, więc mignąłby): dojeżdża do 100 %, chwilę stoi z „Gotowe" i gaśnie.
  const prog = $("sedit-progress"), fill = $("sedit-bar-fill"), txt = $("sedit-progress-text");
  if (be) {
    ed.lastTotal = be.total;
    clearTimeout(ed.doneTimer);
    ed.doneTimer = 0;
    prog.hidden = false;
    prog.classList.remove("done");
    fill.style.width = `${Math.max(4, Math.round(be.done / Math.max(be.total, 1) * 100))}%`;
    txt.textContent = t("Zmieniam logo… {done} z {total}", be);
    seditStep(1);
  } else if (ed.lastTotal && !ed.doneTimer) {
    fill.style.width = "100%";
    prog.classList.add("done");
    txt.textContent = t("Gotowe - zmieniono {n}", { n: nWord(ed.lastTotal, ["zdjęcie", "zdjęcia", "zdjęć"], ["photo", "photos"]) });
    seditStep(2);
    ed.doneTimer = setTimeout(() => {
      if (S.sedit !== ed) return;
      ed.lastTotal = 0;
      ed.doneTimer = 0;
      prog.hidden = true;
    }, 1600);
  } else if (!ed.lastTotal) {
    prog.hidden = true;
  }
  $("sedit-error").textContent = ed.error || "";
}

// etapy pod paskiem: osiągnięte świecą akcentem
function seditStep(n) {
  document.querySelectorAll("#sedit [data-step]").forEach(el => el.classList.toggle("on", +el.dataset.step <= n));
}

function seditPaint() {
  document.querySelectorAll("#sedit [data-sfile]").forEach(b => {
    const on = S.sedit.sel.has(b.dataset.sfile);
    b.classList.toggle("on", on);
    b.setAttribute("aria-checked", on);
  });
}

// Zaznaczanie jak w Finderze / Eksploratorze: klik = tylko to zdjęcie,
// ⌘/Ctrl+klik = dołóż albo odejmij, Shift+klik = zakres od ostatniego
// kliknięcia, klik w tło = odznacz wszystko, przeciągnięcie = prostokąt.
const seditMod = e => !!(e && (e.metaKey || e.ctrlKey));

function seditToggle(file, ev) {
  const ed = S.sedit, s = seditShots().find(x => x.file === file);
  if (!ed || !s || !seditEditable(s) || S.state.batchEdit) return;
  if (ed.dragged) { ed.dragged = false; return; }    // koniec przeciągania, nie klik
  const list = seditShots();
  if (ev && ev.shiftKey && ed.anchor && list.some(x => x.file === ed.anchor)) {
    const a = list.findIndex(x => x.file === ed.anchor), b = list.findIndex(x => x.file === file);
    if (!seditMod(ev)) ed.sel.clear();
    list.slice(Math.min(a, b), Math.max(a, b) + 1).filter(seditEditable).forEach(x => ed.sel.add(x.file));
  } else if (seditMod(ev) || (ev && ev.detail === 0)) {
    // ⌘/Ctrl+klik — albo ENTER/SPACJA na kafelku z klawiatury — przełącza jedno
    ed.sel.has(file) ? ed.sel.delete(file) : ed.sel.add(file);
    ed.anchor = file;
  } else {
    ed.sel = new Set([file]);
    ed.anchor = file;
  }
  seditPaint();
  ed.error = "";
  seditReconcile();
}

// Przeciąganie: prostokąt zaznacza kafelki, które przecina. Jak w Finderze:
// z ⌘/Ctrl ODWRACA ich zaznaczenie (zaznaczone się odznaczają), z Shift
// dokłada do zaznaczenia sprzed przeciągania. Klik w puste tło bez
// przeciągania odznacza wszystko.
function seditDragStart(e) {
  const ed = S.sedit, grid = $("sedit-grid");
  if (!ed || !grid || e.button !== 0 || S.state.batchEdit) return;
  const r0 = grid.getBoundingClientRect();
  const at = (cx, cy) => ({ x: cx - r0.left + grid.scrollLeft, y: cy - r0.top + grid.scrollTop });
  const start = at(e.clientX, e.clientY);
  const onTile = !!e.target.closest("[data-sfile]");
  const invert = seditMod(e), keep = invert || e.shiftKey;
  const before = keep ? new Set(ed.sel) : new Set();
  let box = null;
  ed.dragged = false;
  const move = ev => {
    const p = at(ev.clientX, ev.clientY);
    if (!box) {
      if (Math.hypot(p.x - start.x, p.y - start.y) < 6) return;
      box = document.createElement("div");
      box.className = "sedit-marquee";
      grid.appendChild(box);
      ed.dragged = true;
    }
    const l = Math.min(p.x, start.x), tp = Math.min(p.y, start.y);
    const w = Math.abs(p.x - start.x), h = Math.abs(p.y - start.y);
    Object.assign(box.style, { left: `${l}px`, top: `${tp}px`, width: `${w}px`, height: `${h}px` });
    ed.sel = new Set(before);
    grid.querySelectorAll("[data-sfile]").forEach(b => {
      if (b.classList.contains("off")) return;
      const tl = b.offsetLeft, tt = b.offsetTop;
      if (!(tl < l + w && tl + b.offsetWidth > l && tt < tp + h && tt + b.offsetHeight > tp)) return;
      const f = b.dataset.sfile;
      if (invert && before.has(f)) ed.sel.delete(f);
      else ed.sel.add(f);
    });
    seditPaint();
    seditReconcile();
    const r = grid.getBoundingClientRect();     // przy krawędzi siatka sama się przewija
    if (ev.clientY > r.bottom - 30) grid.scrollTop += 12;
    else if (ev.clientY < r.top + 30) grid.scrollTop -= 12;
  };
  const up = () => {
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", up);
    if (box) box.remove();
    else if (!onTile && !keep) {               // klik obok kafelków = odznacz wszystko
      ed.sel.clear();
      seditPaint();
      seditReconcile();
    }
    if (ed.dragged) setTimeout(() => { ed.dragged = false; }, 0);
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", up);
}

function seditSelectAll() {
  const ed = S.sedit;
  if (!ed || S.state.batchEdit) return;
  ed.sel = new Set(seditShots().filter(seditEditable).map(s => s.file));
  seditPaint();
  seditReconcile();
}

function seditAll() {
  const ed = S.sedit;
  if (!ed || S.state.batchEdit) return;
  const editable = seditShots().filter(seditEditable).map(s => s.file);
  const all = ed.sel.size === editable.length;
  ed.sel = new Set(all ? [] : editable);
  seditPaint();
  seditReconcile();
}

function seditPickLogo(key) {
  const ed = S.sedit;
  if (!ed) return;
  ed.logo = key;
  document.querySelectorAll("[data-blogo]").forEach(b => {
    const on = b.dataset.blogo === key;
    b.classList.toggle("on", on);
    b.classList.toggle("picked", on);
    b.setAttribute("aria-checked", on);
  });
  const c = $("sedit-corner");
  if (c) c.style.cssText = key ? "" : "opacity: .4; pointer-events: none;";
}

function seditPickPos(pos) {
  if (!S.sedit) return;
  S.sedit.pos = pos;
  markCorner("data-bcorner", "sedit-corner-seg", pos);
}

async function seditApply() {
  const ed = S.sedit;
  if (!ed || S.state.batchEdit) return;
  if (!ed.sel.size) { ed.error = t("Zaznacz zdjęcia, na których zmienić logo."); seditReconcile(); return; }
  ed.error = "";
  let res = null;
  try {
    res = await (await post({ action: "edit_batch", files: [...ed.sel], logo: ed.logo, position: ed.pos })).json();
  } catch (e) { res = { ok: false, error: String(e) }; }
  if (S.sedit !== ed) return;
  if (!res || !res.ok) ed.error = (res && res.error) || "";
  else {
    // od razu kręciołki na kafelkach — poll potwierdzi kolejkę
    S.state.batchEdit = { total: res.queued, done: 0, pending: [...ed.sel].sort() };   // kolejność workera
    if (res.skipped) ed.error = t("Pominięto {n} bez oryginału.", { n: res.skipped });
  }
  seditReconcile();
}

// ---------- menu nazwy sesji (górny pasek) ----------
// Nazwa sesji w ścieżce otwiera menu akcji całej sesji (projekt w Claude
// Design, wariant A). Stan w S.sessMenu — przebudowa shella rysuje je od nowa.
// „Wróć do listy sesji" wychodzi od razu (to świadomy wybór z menu); samo ESC
// dalej pyta, czy na pewno.

function sessionMenuHtml(st) {
  const n = (st.shots || []).length;
  const open = !!S.sessMenu;
  return `
    <div class="sess-menu${open ? " open" : ""}" id="sess-menu">
      <button type="button" class="sess-menu-btn" aria-haspopup="menu" aria-expanded="${open}" aria-current="page" onclick="toggleSessionMenu()" title="${t("Akcje sesji")}">
        <span class="sess-menu-name">${st.session.name}</span>${icon("chevDown", 14, 2.2)}
      </button>
      <div class="sess-menu-list" role="menu" ${open ? "" : "hidden"}>
        <button type="button" role="menuitem" id="sess-menu-edit" onclick="toggleSessionMenu(false); openSessionEdit()" ${n ? "" : "disabled"}>${icon("pencil", 16, 1.8)}<span>${t("Zmień logo na zdjęciach…")}</span><span class="sess-menu-meta" id="sess-menu-n">${n}</span></button>
        <button type="button" role="menuitem" onclick="toggleSessionMenu(false); post({ action: 'reveal_session' })">${icon("folder", 16, 1.8)}<span>${t("Pokaż folder sesji")}</span></button>
        <div class="sess-menu-sep" role="separator"></div>
        <button type="button" role="menuitem" onclick="toggleSessionMenu(false); leaveSession()">${icon("arrowLeft", 16, 1.8)}<span>${t("Wróć do listy sesji")}</span></button>
      </div>
    </div>`;
}

function toggleSessionMenu(open) {
  S.sessMenu = open === undefined ? !S.sessMenu : open;
  const root = $("sess-menu");
  if (!root) return;
  root.classList.toggle("open", S.sessMenu);
  root.querySelector(".sess-menu-list").hidden = !S.sessMenu;
  root.querySelector(".sess-menu-btn").setAttribute("aria-expanded", S.sessMenu);
  // górny pasek przebudowuje się rzadko — liczba zdjęć świeża przy każdym otwarciu
  const n = ((S.state && S.state.shots) || []).length;
  $("sess-menu-n").textContent = n;
  $("sess-menu-edit").disabled = !n;
}

document.addEventListener("click", e => {
  const root = $("sess-menu");
  if (S.sessMenu && root && !root.contains(e.target)) toggleSessionMenu(false);
});
