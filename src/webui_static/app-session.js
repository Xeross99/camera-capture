"use strict";
// Zakladka Sesja: live view z siatka i badge'ami, kontrolka EV, filmstrip,
// overlay podgladu zdjec (SPACJA) i kasowanie (BACKSPACE).

function sesjaScreen() {
  const st = S.state, post_ = st.post, cam = st.camera;
  // Sam <img> musi zniknąć przy rozłączeniu: MJPEG zostawia ostatnią odebraną
  // klatkę na ekranie, więc backend może przestać nadawać, a obraz i tak wisi
  // — status mówiłby „rozłączony" nad żywo wyglądającym podglądem.
  const liveOn = st.previewOn && st.connected;
  const grid = GRIDS[S.grid % GRIDS.length];
  const evActive = !!(st.connected && cam.ev);
  const match = sessionMatch(st);
  // Pasek zdjęć i log idą pod CAŁYM oknem (pod live view i panelem), tak samo
  // jak w podglądzie zdjęcia — przy wejściu w podgląd nie zmieniają ani
  // szerokości, ani miejsca.
  return `
    <div style="flex: 1; min-width: 0; display: flex; flex-direction: column;">
    <div style="flex: 1; min-height: 0; display: flex;">
    <main style="flex: 1; min-width: 0; display: flex; flex-direction: column;">
      <section aria-label="Podgląd z aparatu" style="flex: 1; min-height: 0; display: flex; align-items: center; justify-content: center; padding: 16px; background: var(--live-bg);">
        <div style="position: relative; height: 100%; max-width: 100%; aspect-ratio: 3 / 2; border-radius: 12px; overflow: hidden; background: repeating-linear-gradient(135deg, var(--stripe-a) 0 10px, var(--stripe-b) 10px 20px); box-shadow: 0 1px 3px rgba(0,0,0,.08), 0 0 0 1px var(--border); display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 8px;">
          ${liveEmptyHtml(st)}
          <!-- obraz PO karcie: pierwsza klatka zawsze ją przykrywa (przed nią
               <img> MJPEG jest przezroczysty i karta jest widoczna) -->
          ${liveOn ? `<img id="live" src="/stream" alt="Podgląd na żywo" style="position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain;" />` : ""}
          <div id="grid-overlay" style="position: absolute; inset: 0; display: ${grid.cols && liveOn ? "block" : "none"}; background: ${gridBackground(grid.cols, grid.rows)};"></div>

          <div id="grid-seg" class="overlay-seg" role="group" aria-label="Siatka kadrowania" style="left: 14px; top: 14px;">
            <span class="overlay-pill"></span>
            ${[2, 1, 0].map(i => `<button type="button" data-grid="${i}" class="${S.grid === i ? "on" : ""}" aria-pressed="${S.grid === i}" onclick="setGrid(${i})">${GRIDS[i].cols ? `${GRIDS[i].cols}×${GRIDS[i].rows}` : "bez siatki"}</button>`).join("")}
          </div>
          ${liveOn ? `
          <div class="overlay-box mono" style="right: 14px; top: 14px; font-size: 11.5px;">
            <span style="width: 8px; height: 8px; border-radius: 50%; background: #f04438; animation: livePulse 1.6s ease-in-out infinite;"></span>LIVE · <span id="live-fps">${st.fps}</span> fps
          </div>` : ""}
          <div id="hist-badge" class="overlay-box" title="${histTitle(st)}" style="left: 14px; bottom: 14px;">
            <span id="hist-dot" class="dot ${histDot(st)}"></span><span id="hist-text">${histLabel(st)}</span>
          </div>
          <div id="ev-overlay" class="overlay-box mono" style="right: 14px; bottom: 14px; font-size: 11.5px; display: ${cam.ev && st.connected ? "flex" : "none"};">EV ${cam.ev ? evLabel(cam.ev.current) : ""}</div>

          <div id="warmup-overlay" class="warmup-overlay" style="display: ${st.warmup != null ? "flex" : "none"};">
            <div class="live-empty warm">
              <div class="live-empty-art">${WARMUP_SVG}</div>
              <div class="live-empty-title">Przygotowuję silnik czyszczenia tła</div>
              <div class="live-empty-text">Karta graficzna kompiluje model do usuwania tła. Zdjęcia można robić już teraz: poczekają w kolejce.</div>
              <div class="warm-progress"><span id="warmup-bar" style="width: ${warmupPct(st)}%;"></span></div>
              <div id="warmup-text" class="warm-meta">${warmupText(st)}</div>
            </div>
          </div>
          <div id="flash" style="position: absolute; inset: 0; background: #fff; opacity: 0; pointer-events: none; z-index: 4;"></div>
        </div>
      </section>
    </main>

    <aside class="session-side" aria-label="Ustawienia zdjęcia">
      <div class="session-side-scroll">

        <div style="display: flex; flex-direction: column; gap: 8px; min-width: 0;">
          <div style="display: flex; align-items: center; gap: 10px; min-width: 0;">
            <h1 title="${st.session.name}" style="flex: 1; min-width: 0; margin: 0; font-size: 20px; font-weight: 700; letter-spacing: -.015em; color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${st.session.name}</h1>
            <button type="button" class="btn btn-sm" onclick="showLeaveConfirm()" title="Wróć do listy sesji (ESC)">${icon("arrowLeft", 14, 1.9)}Sesje</button>
          </div>
          <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
            ${match && match.product ? `<span style="display: flex; align-items: center; gap: 6px; height: 24px; padding: 0 9px; border-radius: 12px; background: var(--ok-soft); color: var(--ok-fg); font-size: 12px; font-weight: 500;"><span style="width: 6px; height: 6px; border-radius: 50%; background: var(--ok-fg);"></span>${match.product.name}</span>` : `<span style="font-size: 12px; color: var(--muted-2);">Sesja luźna</span>`}
            <span style="font-size: 12px; color: var(--muted-2);">${plPhotos(st.session.count)}${st.session.rejected ? ` · odrzucone ${st.session.rejected}` : ""}</span>
          </div>
        </div>

        <section class="side-card">
          <h2 class="eyebrow" style="margin-bottom: 12px;">Aparat</h2>
          <div id="ev-row" style="display: ${evActive ? "flex" : "none"}; align-items: center; gap: 12px;">
            <div style="flex: 1; min-width: 0;">
              <div class="row-title">Kompensacja ekspozycji</div>
              <div id="ev-hint" class="row-desc">Jaśniej, gdy tło wychodzi szare.</div>
            </div>
            <div class="ev-stepper">
              <button type="button" class="ev-step" aria-label="Ciemniej" onclick="stepEv(-1)">−</button>
              <span id="ev-value" class="mono">${evValueHtml(cam.ev)}</span>
              <button type="button" class="ev-step" aria-label="Jaśniej" onclick="stepEv(1)">+</button>
            </div>
          </div>
          <div id="ev-off" class="cam-off" style="display: ${evActive ? "none" : "flex"};">${camOffHtml(st)}</div>
        </section>

        <section class="side-card" style="padding: 4px 14px;">
          <h2 class="eyebrow" style="margin: 10px 0 4px;">Obróbka po zdjęciu</h2>
          ${optRow("cleanbg", post_.cleanBg, "Białe tło", "Tło do czystej bieli, cienie wygaszone")}
          ${optRow("zoom", post_.zoom, "Przybliżanie", "Kadr dociąga się do produktu")}
          ${optRow("center", post_.center, "Centrowanie", "Produkt na środku kadru")}
          <div style="padding: 10px 0 14px; display: flex; flex-direction: column; gap: 10px;">
            <div style="display: flex; align-items: center; gap: 12px;">
              <div style="flex: 1;" class="row-title">Logo w rogu</div>
              ${switchHtml(post_.logo, "toggle('logo', switchOn(this))", "Logo w rogu")}
            </div>
            ${logoPicker(post_)}
          </div>
        </section>

        ${robotCard()}
      </div>

      <div class="shutter-bar">
        <button type="button" class="shutter" onclick="shoot()"><span id="shoot-spin" class="spinner" style="flex: 0 0 auto; border-color: rgba(255,255,255,.35); border-top-color: #fff; display: ${shootBusy(st) ? "inline-block" : "none"};"></span>${icon("camera", 20, 1.8)}<span id="shoot-label">${st.busy || "Zrób zdjęcie"}</span><span class="kbd">ENTER</span></button>
      </div>
    </aside>
    </div>
    ${stripPanel("filmstrip")}
    ${logBar("log")}
    </div>

    <div id="review-slot">${reviewOverlay()}</div>`;
}

// Plansza w ramce podglądu, gdy nie ma obrazu z aparatu: rozłączony (czerwony,
// pulsujące fale i „łączę ponownie"), podgląd wyłączony (P) albo czekanie na
// pierwsze klatki. Obraz z /stream przykrywa ją, gdy tylko przyjdzie.
// Aparat z odłączonym kablem USB: wtyczka próbuje się wpiąć i odskakuje,
// w szczelinie przy gnieździe mrugają iskierki. Rysunek własny (aplikacja
// działa offline), kolor z currentColor, ruch w CSS (.unplug-*).
const UNPLUGGED_SVG = `
  <svg class="unplugged" viewBox="0 0 132 72" width="132" height="72" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
    <g class="unplug-camera">
      <rect x="22" y="9" width="20" height="9" rx="3"/>
      <rect x="6" y="16" width="62" height="44" rx="9"/>
      <circle cx="37" cy="38" r="13"/>
      <circle cx="37" cy="38" r="6"/>
      <circle cx="58" cy="26" r="1.6" fill="currentColor" stroke="none" class="unplug-led"/>
      <rect x="68" y="34" width="4" height="10" rx="1"/>
    </g>
    <g class="unplug-sparks">
      <path d="M77 31 l3 -4"/><path d="M78 39 h4"/><path d="M77 47 l3 4"/>
    </g>
    <g class="unplug-plug">
      <rect x="86" y="35" width="5" height="8" rx="1"/>
      <rect x="91" y="32" width="15" height="14" rx="3"/>
      <path d="M106 39 C 116 39, 118 56, 128 58"/>
    </g>
  </svg>`;

// Brak Canon EDSDK (Windows): pliki są na licencji Canona, więc nie ma ich
// w paczce aplikacji — karta mówi, po co są, skąd je wziąć i gdzie położyć.
function edsdkMissingHtml() {
  return `
    <div class="live-empty sdk">
      <div class="live-empty-icon">${icon("puzzle", 26, 1.6)}</div>
      <div class="live-empty-title">Brak sterownika aparatu Canon</div>
      <div class="live-empty-text">Aplikacja steruje aparatem przez Canon EDSDK: robi zdjęcia, pobiera je po USB i pokazuje podgląd na żywo. Pliki <span class="mono">EDSDK.dll</span> i <span class="mono">EdsImage.dll</span> wymagają licencji Canona, dlatego nie ma ich w paczce aplikacji.</div>
      <div class="sdk-steps">
        <div><span class="sdk-n">1</span><span>Poproś o pliki: <span class="sdk-person"><img src="/author" alt="" /><b>Michał Krzysteczko</b></span>, ma licencję na Canon EDSDK.</span></div>
        <div><span class="sdk-n">2</span><span>Połóż oba pliki obok <span class="mono">Trixbrix - Camera Capture.exe</span>.</span></div>
        <div><span class="sdk-n">3</span><span>Uruchom aplikację ponownie.</span></div>
      </div>
      <button type="button" class="btn btn-sm" onclick="post({action:'open_url', url: 'https://github.com/Xeross99'})">${GITHUB_MARK.replace("width: 24px; height: 24px", "width: 14px; height: 14px")}Kontakt: Xeross99${icon("external", 13, 1.8)}</button>
    </div>`;
}

// Rozgrzewka silnika czyszczenia tła: zdjęcie z szarym tłem, po którym
// przesuwa się „pędzel" i zostawia za sobą biel; iskierki na końcu przejazdu.
const WARMUP_SVG = `
  <svg class="warm-art" viewBox="0 0 132 80" width="132" height="80" aria-hidden="true">
    <defs><clipPath id="warm-clip"><rect x="14" y="8" width="104" height="64" rx="8"/></clipPath></defs>
    <g clip-path="url(#warm-clip)">
      <rect x="14" y="8" width="104" height="64" fill="#c9ccd4"/>
      <rect class="warm-clean" x="14" y="8" width="104" height="64" fill="#ffffff"/>
      <g fill="none" stroke="#5e6472" stroke-width="3" stroke-linecap="round" stroke-linejoin="round">
        <rect x="44" y="30" width="44" height="26" rx="3"/>
        <path d="M44 38 h44 M44 48 h44 M56 30 v26 M76 30 v26"/>
      </g>
      <rect class="warm-brush" x="10" y="4" width="6" height="72" rx="3" fill="var(--accent)"/>
    </g>
    <rect x="14" y="8" width="104" height="64" rx="8" fill="none" stroke="currentColor" stroke-width="2.4"/>
    <path class="warm-spark" fill="var(--accent)" d="M120 10 l2 5 5 2 -5 2 -2 5 -2 -5 -5 -2 5 -2z"/>
    <path class="warm-spark s2" fill="var(--accent)" d="M8 60 l1.4 3.6 3.6 1.4 -3.6 1.4 -1.4 3.6 -1.4 -3.6 -3.6 -1.4 3.6 -1.4z"/>
  </svg>`;

// Pasek postępu liczony od szacunku z historii rozgrzewek na tym komputerze
// (warmupEta); bez historii zakładamy 2 minuty. Zatrzymany na 95%, gdy trwa dłużej.
const WARMUP_DEFAULT_S = 120;
const warmupEta = st => st.warmupEta || WARMUP_DEFAULT_S;
const warmupPct = st => st.warmup != null ? Math.min(95, Math.round(100 * st.warmup / warmupEta(st))) : 0;
const fmtSec = s => s >= 60 ? `${Math.floor(s / 60)} min${s % 60 ? ` ${s % 60} s` : ""}` : `${s} s`;
function warmupText(st) {
  const s = st.warmup || 0, eta = warmupEta(st), left = eta - s;
  return left > 0
    ? `Zwykle ok. ${fmtSec(eta)} na tym komputerze · zostało ok. <span class="mono">${fmtSec(left)}</span>`
    : `Trwa dłużej niż zwykle (ok. ${fmtSec(eta)}) · <span class="mono">${fmtSec(s)}</span>`;
}

function liveEmptyHtml(st) {
  if (st.edsdkMissing) return edsdkMissingHtml();
  const v = !st.connected
    ? { cls: "err", ic: "cameraOff", title: "Aparat rozłączony", text: "Sprawdź kabel USB i czy aparat jest włączony.", foot: `<span class="live-empty-foot"><span class="spinner"></span>Łączę ponownie…</span>` }
    : st.previewOn
      ? { cls: "wait", ic: "camera", title: "Czekam na obraz z aparatu", text: "Pierwsze klatki podglądu za chwilę.", foot: `<span class="live-empty-foot"><span class="spinner"></span>Uruchamiam podgląd…</span>` }
      : { cls: "off", ic: "eyeSlash", title: "Podgląd wyłączony", text: "Zdjęcia dalej można robić klawiszem ENTER.", foot: `<span class="live-empty-foot">Włącz klawiszem <span class="hint-key">P</span></span>` };
  const art = v.cls === "err"
    ? `<div class="live-empty-art">${UNPLUGGED_SVG}</div>`
    : `<div class="live-empty-icon"><span class="ring"></span><span class="ring r2"></span>${icon(v.ic, 26, 1.6)}</div>`;
  return `
    <div class="live-empty ${v.cls}">
      ${art}
      <div class="live-empty-title">${v.title}</div>
      <div class="live-empty-text">${v.text}</div>
      ${v.foot}
    </div>`;
}

// Sesja Automatu o tej nazwie (z listy sesji) — stad dopasowany produkt.
function sessionMatch(st) {
  const name = (st.session.name || "").trim().toLowerCase();
  return ((st.automat && st.automat.sessions) || []).find(s => (s.name || "").trim().toLowerCase() === name) || null;
}

// Wiersz obróbki: tytuł, opis i przełącznik.
const optRow = (key, on, title, desc) => `
  <div class="opt">
    <div style="flex: 1; min-width: 0;">
      <div class="row-title">${title}</div>
      <div class="row-desc">${desc}</div>
    </div>
    ${switchHtml(on, `toggle('${key}', switchOn(this))`, title)}
  </div>`;

// Badge jasności tła mówi operatorowi, co ma zrobić — nie jakie są liczby
// (te są w tooltipie). Po rozłączeniu gaśnie, zamiast udawać żywy pomiar.
const BG_LABEL = {
  ok: "Tło jasne i równe",
  dark: "Tło za ciemne · rozjaśnij w aparacie",
  unknown: "Tło —",
};
const BG_DOT = { ok: "ok", dark: "warn", unknown: "" };

// Stan, w którym nie ma czego ustawiać: rozłączony aparat albo tryb bez
// kompensacji (M). Zamiast wyszarzonych −/+ mówi wprost, co się dzieje.
function camOffHtml(st) {
  if (st.edsdkMissing) return `<span class="dot warn"></span><span><b>Brak Canon EDSDK.</b> Bez tych plików aplikacja nie połączy się z aparatem. Szczegóły w ramce podglądu.</span>`;
  if (!st.connected) return `<span class="dot err"></span><span><b>Aparat rozłączony.</b> Kompensacja wróci po połączeniu.</span>`;
  return `<span class="dot warn"></span><span><b>Kompensacja niedostępna</b> w tym trybie. Ustaw pokrętło aparatu na P, Av albo Tv.</span>`;
}

// Kompensacja z debounce: każdy klik od razu przesuwa WARTOŚĆ DOCELOWĄ
// (S.evTarget) i ją pokazuje, a do aparatu idzie jedna komenda z końcową
// wartością, gdy operator przestanie klikać na EV_DEBOUNCE_MS. Wcześniej każdy
// krok czekał na potwierdzenie z aparatu, więc „trzy w dół" = trzy razy
// klik i czekanie. Przyciski są klikalne cały czas, także w trakcie wysyłki.
const EV_DEBOUNCE_MS = 400;
let evTimer = 0;

function evOptions(ev) {
  return (ev && ev.choices || [])
    .map(c => ({ c, n: evNumber(c) }))
    .filter(o => o.n !== null)
    .sort((a, b) => a.n - b.n);   // nie ufamy kolejności z aparatu — bywa malejąca
}

function stepEv(dir) {
  const ev = S.state.connected && S.state.camera && S.state.camera.ev;
  const opts = evOptions(ev);
  if (!opts.length) return;
  // krok liczymy od wartości docelowej, jeśli trwa klikanie albo wysyłka
  const base = S.evTarget ? S.evTarget.n : (S.evPending ? S.evPending.target : evNumber(ev.current));
  const eps = 1e-6;
  let hit;
  if (base === null) hit = opts.find(o => Math.abs(o.n) < eps) || opts[0];
  else if (dir > 0) hit = opts.find(o => o.n > base + eps) || opts[opts.length - 1];
  else hit = [...opts].reverse().find(o => o.n < base - eps) || opts[0];
  if (!hit) return;
  S.evTarget = { n: hit.n, label: hit.c };
  evReconcile(S.state);
  clearTimeout(evTimer);
  evTimer = setTimeout(sendEv, EV_DEBOUNCE_MS);
}

function sendEv() {
  const t = S.evTarget;
  S.evTarget = null;
  if (!t) return;
  const ev = S.state.camera && S.state.camera.ev;
  const cur = ev ? evNumber(ev.current) : null;
  if (cur !== null && Math.abs(cur - t.n) < 0.2) { S.evPending = null; evReconcile(S.state); return; }
  // Źródłem prawdy jest aparat — gdy odrzuci wartość, limit w evReconcile()
  // przywraca kontrolkę z wartością z aparatu (powód ląduje w logu z _do_set_ev).
  S.evPending = { target: t.n, label: t.label, since: performance.now() };
  evReconcile(S.state);
  post({ action: "set_ev", value: t.label });
}

// Zawartość celi z wartością EV: docelowa (klikanie albo wysyłka) przygaszona,
// a w trakcie wysyłki ze spinnerem POZYCJONOWANYM ABSOLUTNIE nad nią
// (`.ev-spin`) — spinner w miejscu tekstu podnosił całą kartę o 2 px.
function evValueHtml(ev) {
  if (S.evTarget) return `<span style="color: var(--accent-fg);">${evLabel(S.evTarget.label)}</span>`;
  if (S.evPending)
    return `<span style="opacity: .3;">${evLabel(S.evPending.label)}</span><span class="spinner ev-spin"></span>`;
  return ev ? evLabel(ev.current) : "—";
}

// Łatka kontrolki EV wołana z updateVolatile() przy każdym pollu (kontrolka
// jest ŚWIADOMIE łatana po id, nie keyowana — rebuild zabiłby <img> streamu,
// a kompensacja zmienia się też z pokrętła na aparacie). Limit czekania musi
// przeżyć: zapis + odczyt w wątku camera i jeden pełny cykl pollu EV (2 s)
// z zapasem na zajętą kolejkę aparatu.
const EV_PENDING_MAX_MS = 8000;

function evReconcile(st) {
  const val = $("ev-value");
  if (!val) return;
  const ev = st.connected && st.camera ? st.camera.ev : null;
  if (S.evPending) {
    // tolerancja 0.2: zapisy potrafią się różnić notacją („+2 2/3" vs „+2.6"
    // to ta sama wartość, ale liczbowo 0.067 różnicy), a sąsiednie kroki
    // dzieli ≥0.3 — więc 0.2 łapie tę samą wartość, nie łapiąc sąsiada
    const cur = ev ? evNumber(ev.current) : null;
    const done = cur !== null && Math.abs(cur - S.evPending.target) < 0.2;
    const expired = !ev || performance.now() - S.evPending.since > EV_PENDING_MAX_MS;
    if (done || expired) S.evPending = null;
  }
  if (!ev) { S.evTarget = null; clearTimeout(evTimer); }
  const html = evValueHtml(ev);
  if (val.dataset.html !== html) { val.innerHTML = html; val.dataset.html = html; }
  const row = $("ev-row"), off = $("ev-off");
  if (row) row.style.display = ev ? "flex" : "none";
  if (off) {
    off.style.display = ev ? "none" : "flex";
    const offHtml = camOffHtml(st);
    if (!ev && off.dataset.html !== offHtml) { off.innerHTML = offHtml; off.dataset.html = offHtml; }
  }
  const ov = $("ev-overlay");
  if (ov) {
    ov.style.display = ev ? "flex" : "none";
    if (ev) ov.textContent = `EV ${evLabel(S.evTarget ? S.evTarget.label : S.evPending ? S.evPending.label : ev.current)}`;
  }
}

// Spinner w przycisku migawki: krecy sie przez caly czas, gdy przycisk nie
// zrobi zdjecia od reki — strzal/obrobka (st.busy niesie tekst fazy) albo
// przejazd ramienia. Sam tekst faz byl statyczny i wygladal na zawieszke.
const shootBusy = st => !!(st.busy || (st.robot && st.robot.busy));

const bgStatus = st => (st.connected && BG_LABEL[st.camera.bgStatus]) ? st.camera.bgStatus : "unknown";
const histLabel = st => BG_LABEL[bgStatus(st)];
const histDot = st => BG_DOT[bgStatus(st)];
const histTitle = st => bgStatus(st) === "unknown"
  ? "Jasność tła — czekam na klatkę z aparatu."
  : `Zmierzona jasność tła: ${st.camera.bg} ze skali 0–255 (im bliżej 255, tym bielszy stół; poniżej 230 robi się szaro).`;

// ---------- podglad zdjec (overlay) ----------

function reviewShot() {
  const shots = S.state.shots;
  if (!shots.length) return null;
  const i = S.selShot >= 0 && S.selShot < shots.length ? S.selShot : shots.length - 1;
  return { ...shots[i], i };
}

// Stan zdjęcia w Automacie (chip w pasku podglądu i kropka na kafelku).
function shotState(shot) {
  if (shot.status === "rejected") return { cls: "err", text: "odrzucone" };
  if (shot.uploaded) return { cls: "ok", text: "w Automacie" };
  if (S.state.automat && S.state.automat.hasToken) return { cls: "warn", text: "czeka na wysyłkę" };
  return { cls: "", text: "" };
}

const VIEWER_CHIP = {
  ok: "background: var(--ok-soft); color: var(--ok-fg);",
  warn: "background: var(--warn-soft); color: var(--warn-fg-3);",
  err: "background: var(--err-soft); color: var(--err-fg);",
};

function reviewStatusHtml(shot) {
  const s = shotState(shot);
  if (!s.text) return "";
  return `<span style="display: flex; align-items: center; gap: 6px; font-size: 12px; padding: 3px 9px; border-radius: 6px; ${VIEWER_CHIP[s.cls]}"><span class="dot ${s.cls}" style="width: 6px; height: 6px;"></span>${s.text}</span>`;
}

// Pasek u góry podglądu łatany w miejscu przy każdej zmianie zdjęcia.
function updateReviewHeader(shot) {
  const n = S.state.shots.length;
  const c = $("review-count");
  if (c) c.textContent = `${shot.i + 1} z ${n}`;
  const f = $("review-file");
  if (f) f.textContent = shot.file;
  const s = $("review-status");
  if (s) s.innerHTML = reviewStatusHtml(shot);
  reviewSize();
  const prev = $("review-prev"), next = $("review-next");
  if (prev) prev.disabled = shot.i <= 0;
  if (next) next.disabled = shot.i >= n - 1;
}

// Podgląd ładuje najpierw wersję 1800 px (szybkie przełączanie strzałkami się
// nie zacina), a gdy operator zatrzyma się na zdjęciu (FULL_AFTER_MS), w tle
// dociąga pełny plik i podmienia go po cichu, kiedy już się wczyta. Przejście
// do innego zdjęcia w tym czasie unieważnia dociąganie.
const FULL_AFTER_MS = 450;
let fullTimer = 0;
function reviewLoaded(img) {
  reviewSize();
  clearTimeout(fullTimer);
  if (!img.src.includes("&view=1") || S.edit) return;
  const shot = reviewShot();
  if (!shot) return;
  const viewSrc = img.src;
  fullTimer = setTimeout(() => {
    const full = new Image();
    full.onload = () => {
      // dalej to samo zdjęcie i nikt nie otworzył edycji — podmieniamy
      if (img.src === viewSrc && !S.edit && $("review-img") === img) {
        img.onload = null;
        img.src = full.src;
      }
    };
    full.src = shotUrl(shot);
  }, FULL_AFTER_MS);
}

// Rozmiar gotowego pliku z listy zdjęć (podgląd pokazuje wersję 1800 px,
// więc wymiary samego obrazka nie są wymiarami pliku).
function reviewSize() {
  const el = $("review-size"), shot = reviewShot();
  if (!el || !shot || !shot.size || !shot.size[0]) return;
  el.textContent = `${shot.size[0]} × ${shot.size[1]}`;
  el.style.display = "";
}

// Podglad zdjecia zajmuje CALE okno (position: fixed nad zakladkami i sidebarem),
// a pasek zdjec sesji siedzi u jego dolu. Tlo idzie za motywem (jasne w jasnym,
// ciemne w ciemnym) — tokeny --viewer* w style.css.
function reviewOverlay() {
  const shot = S.reviewMode ? reviewShot() : null;
  if (!shot) return "";
  const n = S.state.shots.length;
  return `
  <div id="review-wrap" class="ui" style="position: fixed; inset: 0; z-index: 60; display: flex; flex-direction: column;">
    <div id="review-main" style="flex: 1; min-height: 0; display: flex; flex-direction: column; background: var(--viewer); transition: opacity .24s cubic-bezier(0.32, 0.72, 0, 1);">
      <div class="viewer-bar">
        <button type="button" class="vbtn" onclick="closeReview()">${icon("arrowLeft", 16, 1.8)}Wróć do sesji<span class="kbd">ESC</span></button>
        <div style="display: flex; align-items: baseline; gap: 10px;">
          <span id="review-count" style="font-size: 15px; font-weight: 700;">${shot.i + 1} z ${n}</span>
          <span id="review-file" class="mono" style="font-size: 12.5px; color: var(--viewer-fg-2);">${shot.file}</span>
        </div>
        <span id="review-size" class="vtag" style="display: none;"></span>
        <span id="review-status">${reviewStatusHtml(shot)}</span>
        <div style="flex: 1;"></div>
        <button type="button" id="edit-btn" class="vbtn" onclick="toggleEdit()">${icon("pencil", 16, 1.8)}Edytuj<span class="kbd">E</span></button>
        <button type="button" class="vbtn vbtn-danger" onclick="deleteReviewed()">${icon("trash", 16, 1.8)}Usuń<span class="kbd">BACKSPACE</span></button>
      </div>
      <div style="flex: 1; min-height: 0; display: flex;">
      <div style="flex: 1; min-width: 0; position: relative;">
        <img id="review-img" src="${shotUrl(shot, "view")}" alt="" onload="reviewLoaded(this)" style="position: absolute; left: 88px; right: 88px; top: 20px; bottom: 20px; width: calc(100% - 176px); height: calc(100% - 40px); object-fit: contain; animation: reviewIn .32s cubic-bezier(0.32, 0.72, 0, 1);" />
        <button type="button" id="review-prev" class="vnav" aria-label="Poprzednie zdjęcie" onclick="navShot(-1)" style="left: 20px;" ${shot.i <= 0 ? "disabled" : ""}>${icon("chevL", 20, 2)}</button>
        <button type="button" id="review-next" class="vnav" aria-label="Następne zdjęcie" onclick="navShot(1)" style="right: 20px;" ${shot.i >= n - 1 ? "disabled" : ""}>${icon("chevR", 20, 2)}</button>
      </div>
      <aside id="edit-panel" class="edit-panel ui" aria-label="Edycja zdjęcia" hidden></aside>
      </div>
    </div>
    ${stripPanel("review-strip")}
    ${logBar("review-log")}
  </div>`;
}

// ---------- edycja logo na gotowym zdjeciu ----------
// Panel z boku podgladu: bez logo / TRIXBRIX.eu / KIDS i rog kadru. Zdjecie
// obok pokazuje PRAWDZIWY wynik (/edit_preview renderuje go z wersji bez logo),
// „Zapisz" podmienia plik i to samo zdjecie w Automacie.

const editShot = () => S.edit && S.state.shots.find(s => s.file === S.edit.file);

function editPanelHtml() {
  const shot = editShot();
  const post_ = S.state.post;
  const status = !shot ? "" : shot.edit === "ready" ? "ready"
    : (shot.edit === "raw" ? "preparing" : "none");
  const head = `
    <div style="display: flex; align-items: center; gap: 10px;">
      <h2 class="panel-title" style="flex: 1;">Edycja zdjęcia</h2>
      <button type="button" class="icon-btn" aria-label="Zamknij edycję" onclick="closeEdit()" style="width: 28px; height: 28px; font-size: 16px;">×</button>
    </div>
    <div class="row-desc mono" style="margin-top: -6px;">${S.edit.file}</div>`;
  if (status === "preparing") {
    return `${head}
      <div style="display: flex; align-items: center; gap: 10px; padding: 12px; border-radius: 10px; background: var(--accent-soft); color: var(--accent-fg); font-size: 13px;">
        <span class="spinner"></span><span>Przygotowuję wersję bez logo z oryginału z aparatu…</span>
      </div>
      <div class="row-desc">Robię to raz dla tego zdjęcia, z bieżącymi ustawieniami obróbki.</div>`;
  }
  if (status !== "ready") {
    return `${head}
      <div style="padding: 12px; border-radius: 10px; background: var(--warn-soft); color: var(--warn-fg-3); font-size: 13px; line-height: 1.45;">To zdjęcie nie ma ani wersji bez logo, ani oryginału z aparatu, więc nie da się zmienić logo.</div>
      <div class="row-desc">Logo da się zmieniać na zdjęciach robionych od tej wersji aplikacji i na tych, których oryginał leży w /raw.</div>`;
  }
  return `${head}
    <div style="display: flex; flex-direction: column; gap: 8px;">
      <div class="eyebrow">Logo</div>
      ${logoTiles(post_.logos, S.edit.logo, "editPickLogo", "data-elogo", true)}
    </div>
    <div id="edit-corner" style="${S.edit.logo ? "" : "opacity: .4; pointer-events: none;"}">
      ${cornerRow(post_.logoPositions, S.edit.pos, "editPickPos", "data-ecorner", "edit-pos-text")}
    </div>
    <div class="row-desc">Podgląd obok pokazuje zdjęcie dokładnie tak, jak zostanie zapisane.</div>
    <div style="flex: 1;"></div>
    <div style="display: flex; gap: 8px;">
      <button type="button" class="btn" onclick="closeEdit()" style="flex: 1;">Anuluj</button>
      <button type="button" class="btn btn-primary" onclick="saveEdit()" style="flex: 2;">Zapisz zdjęcie</button>
    </div>
    <div class="row-desc" style="text-align: center;">Zmiana trafi też do Automatu.</div>`;
}

function renderEditPanel() {
  const panel = $("edit-panel");
  if (!panel || !S.edit) return;
  const shot = editShot();
  panel.dataset.status = shot ? shot.edit : "";
  panel.innerHTML = editPanelHtml();
  panel.hidden = false;
  const btn = $("edit-btn");
  if (btn) btn.classList.add("on");
  editPreview();
}

// Podgląd edycji: obraz z serwera (wersja bez logo + wybrane logo).
function editPreview() {
  const img = $("review-img"), shot = editShot();
  if (!img || !shot || shot.edit !== "ready") return;
  clearTimeout(fullTimer);
  const q = new URLSearchParams({ s: S.state.session.name, f: shot.file, logo: S.edit.logo, pos: S.edit.pos, n: Date.now() });
  img.src = `/edit_preview?${q}`;
}

function openEdit() {
  const shot = reviewShot();
  if (!shot) return;
  const post_ = S.state.post;
  S.edit = { file: shot.file, logo: post_.logoChoice || (post_.logos[0] || {}).key || "", pos: post_.logoPosition };
  if (shot.edit === "raw" && S.state.editPreparing !== shot.file) post({ action: "edit_prepare", file: shot.file });
  renderEditPanel();
}

function closeEdit() {
  if (!S.edit) return;
  S.edit = null;
  const panel = $("edit-panel");
  if (panel) { panel.hidden = true; panel.innerHTML = ""; }
  const btn = $("edit-btn");
  if (btn) btn.classList.remove("on");
  const img = $("review-img"), shot = reviewShot();
  if (img && shot) {
    img.onload = () => reviewLoaded(img);
    img.src = shotUrl(shot, "view");
  }
}

function toggleEdit() { S.edit ? closeEdit() : openEdit(); }

function editPickLogo(key) {
  if (!S.edit) return;
  S.edit.logo = key;
  document.querySelectorAll("[data-elogo]").forEach(b => {
    const on = b.dataset.elogo === key;
    b.classList.toggle("on", on);
    b.setAttribute("aria-checked", on);
  });
  const c = $("edit-corner");
  if (c) c.style.cssText = key ? "" : "opacity: .4; pointer-events: none;";
  editPreview();
}

function editPickPos(pos) {
  if (!S.edit) return;
  S.edit.pos = pos;
  document.querySelectorAll("[data-ecorner]").forEach(b => {
    const on = b.dataset.ecorner === pos;
    b.classList.toggle("on", on);
    b.setAttribute("aria-checked", on);
  });
  const t = $("edit-pos-text");
  if (t) t.textContent = cap(LOGO_POS_PL[pos] || pos);
  editPreview();
}

function saveEdit() {
  if (!S.edit) return;
  const e = S.edit;
  const shot = editShot();
  // kafelek w pasku kręci się, aż przyjdzie nowa wersja pliku (inne `v`),
  // a potem „wyskakuje" z poświatą — patrz filmstrip()
  S.editSaved = { file: e.file, v: shot ? shot.v : 0, since: performance.now() };
  post({ action: "edit_save", file: e.file, logo: e.logo, position: e.pos });
  refreshStrips();
  // podgląd z nowym logo zostaje na ekranie; plik i miniatura podmienią się,
  // gdy backend skończy (nowa wersja pliku = nowy adres miniatury)
  S.edit = null;
  const panel = $("edit-panel");
  if (panel) { panel.hidden = true; panel.innerHTML = ""; }
  const btn = $("edit-btn");
  if (btn) btn.classList.remove("on");
}

// Z pollu: wersja bez logo dojechała (raw → ready) — panel i podgląd od nowa.
function editReconcile(st) {
  // zapis padł albo nic nie zmienił — po limicie kafelek przestaje się kręcić
  const es = S.editSaved;
  if (es && st.editSaving !== es.file && performance.now() - es.since > 4000) refreshStrips();
  const panel = $("edit-panel");
  if (!S.edit || !panel || panel.hidden) return;
  const shot = editShot();
  if (shot && panel.dataset.status !== shot.edit) renderEditPanel();
}

// Pasek zdjec z naglowkiem i pasek logu sa w podgladzie te same co na ekranie
// sesji: bez nich miniatury przy wejsciu w podglad zjezdzaly w dol o wysokosc
// logu i naglowka, co klulo w oczy.
function stripPanel(id) {
  const hints = id === "review-strip"
    ? `<span>${kHint("← →")}zmiana zdjęcia</span><span>${kHint("E")}edytuj</span><span>${kHint("BACKSPACE")}usuń</span>`
    : `<span>${kHint("SPACJA")}podgląd</span><span>${kHint("← →")}wybór</span><span>${kHint("BACKSPACE")}usuń</span>`;
  return `
    <section aria-label="Zdjęcia w sesji" class="strip-panel">
      <div style="display: flex; align-items: center; gap: 14px; margin-bottom: 10px;">
        <div id="${id}-legend" style="display: flex; align-items: center; gap: 14px;">${stripLegend()}</div>
        <div style="flex: 1;"></div>
        <span class="hints">${hints}</span>
      </div>
      <div id="${id}" class="strip-box" data-sig='${stripContentSig().replace(/'/g, "&#39;")}' style="${stripBox}">${filmstrip()}</div>
    </section>`;
}

function stripLegend() {
  const st = S.state, shots = st.shots;
  const up = shots.filter(s => s.uploaded && s.status !== "rejected").length;
  const wait = st.automat && st.automat.hasToken
    ? shots.filter(s => !s.uploaded && s.status !== "rejected").length : 0;
  const rej = shots.filter(s => s.status === "rejected").length;
  const item = (cls, text) => `<span class="legend"><span class="dot ${cls}"></span>${text}</span>`;
  return `<h2 style="margin: 0; font-size: 13px; font-weight: 700; color: var(--text);">Zdjęcia w sesji <span style="font-weight: 500; color: var(--muted-2);">· ${shots.length}</span></h2>
    ${up ? item("ok", `w Automacie ${up}`) : ""}
    ${wait ? item("warn", `wysyłanie ${wait}`) : ""}
    ${rej ? item("err", `odrzucone ${rej}`) : ""}
    ${st.processing ? `<span class="legend"><span class="dot" style="background: var(--accent);"></span>obróbka 1</span>` : ""}`;
}

// `prefix` rozroznia dwa egzemplarze (ekran sesji i podglad) — oba sa w DOM
// naraz, a odswiezanie w `app-main.js` szuka ich po id. Panel logu otwiera
// sie NAD linia statusu.
function logBar(prefix) {
  return `
    <div class="statusbar">
      <div id="${prefix}-panel" class="log-panel" style="display: ${S.logOpen ? "block" : "none"};">${logLines()}</div>
      <div class="statusbar-line">
        <span id="${prefix}-line" style="flex: 1; min-width: 0; display: flex; gap: 10px; align-items: center; overflow: hidden;">${lastLogLine()}</span>
        <button type="button" class="btn btn-sm log-toggle" onclick="toggleLog()" style="height: 24px; font-size: 11.5px;">${S.logOpen ? "Ukryj log" : "Pokaż log"}</button>
      </div>
    </div>`;
}

// Wybor logo: dwa kafelki z prawdziwym plikiem logo (na bieli, jak na zdjeciu —
// czarne TRIXBRIX.eu znikneloby na ciemnym motywie) i obok wybor rogu kadru na
// malym kwadracie. Zmiana latana W MIEJSCU, bez rebuildu ekranu (ten zrywa
// stream live view).
const LOGO_CORNERS = { "top-left": "left: 5px; top: 5px;", "top-right": "right: 5px; top: 5px;",
  "bottom-left": "left: 5px; bottom: 5px;", "bottom-right": "right: 5px; bottom: 5px;" };

function logoTiles(logos, cur, onPick, attr = "data-logo", withNone = false) {
  const tile = (key, inner, labelText) => `<button type="button" role="radio" ${attr}="${key}" aria-checked="${key === cur}" aria-label="${labelText}" title="${labelText}" class="logo-tile${key === cur ? " on" : ""}" onclick="${onPick}('${key}')">${inner}</button>`;
  const n = logos.length + (withNone ? 1 : 0);
  return `
    <div role="radiogroup" aria-label="Logo" style="display: grid; grid-template-columns: repeat(${n}, minmax(0, 1fr)); gap: 8px;">
      ${withNone ? tile("", `<span style="font-size: 12.5px; font-weight: 500; color: #5e5e66;">Bez logo</span>`, "Bez logo") : ""}
      ${logos.map(l => tile(l.key, `<img src="/logo?k=${l.key}" alt="" />`, l.label)).join("")}
    </div>`;
}

function cornerRow(positions, cur, onPick, attr = "data-corner", textId = "logo-pos-text") {
  return `
    <div style="display: flex; align-items: center; gap: 12px;">
      <div style="flex: 1; min-width: 0;">
        <div class="row-title">Pozycja</div>
        <div id="${textId}" class="row-desc">${cap(LOGO_POS_PL[cur] || cur)}</div>
      </div>
      <div class="corner-pick" role="radiogroup" aria-label="Róg kadru">
        ${positions.map(p => `<button type="button" role="radio" ${attr}="${p}" aria-checked="${p === cur}" aria-label="${LOGO_POS_PL[p] || p}" title="${LOGO_POS_PL[p] || p}" class="${p === cur ? "on" : ""}" onclick="${onPick}('${p}')" style="${LOGO_CORNERS[p] || ""}"></button>`).join("")}
      </div>
    </div>`;
}

const cap = t => t ? t[0].toUpperCase() + t.slice(1) : t;

function logoPicker(post_) {
  return `
    ${logoTiles(post_.logos, post_.logoChoice, "pickLogo")}
    ${cornerRow(post_.logoPositions, post_.logoPosition, "setLogoPos")}`;
}

function pickLogo(key) {
  if (key === S.state.post.logoChoice) return;
  S.state.post.logoChoice = key;   // echo od razu, poll potwierdzi
  document.querySelectorAll("[data-logo]").forEach(b => {
    const on = b.dataset.logo === key;
    b.classList.toggle("on", on);
    b.setAttribute("aria-checked", on);
  });
  lastSesja = sesjaKey(S.state);
  post({ action: "set_post", key: "logo", value: key });
}

function setLogoPos(pos) {
  if (pos === S.state.post.logoPosition) return;
  S.state.post.logoPosition = pos;
  document.querySelectorAll("[data-corner]").forEach(b => {
    const on = b.dataset.corner === pos;
    b.classList.toggle("on", on);
    b.setAttribute("aria-checked", on);
  });
  const t = $("logo-pos-text");
  if (t) t.textContent = cap(LOGO_POS_PL[pos] || pos);
  lastSesja = sesjaKey(S.state);
  post({ action: "set_post", key: "logo_position", value: pos });
}

// Rozwiniecie logu W MIEJSCU — pelny rebuild w podgladzie powtorzylby
// animacje wejscia zdjecia.
function toggleLog() {
  S.logOpen = !S.logOpen;
  document.querySelectorAll(".log-toggle").forEach(b => { b.textContent = S.logOpen ? "Ukryj log" : "Pokaż log"; });
  document.querySelectorAll(".log-panel").forEach(lp => {
    lp.style.display = S.logOpen ? "block" : "none";
    lp.scrollTop = lp.scrollHeight;
  });
  lastSesja = sesjaKey(S.state);
}

// Pasek zdjec wisi w dwoch miejscach (ekran sesji i podglad), oba trzeba odswiezyc
// po zmianie zaznaczenia. Aktywny kafelek jest przy okazji doprowadzany do widoku —
// przy kilkunastu zdjeciach zaznaczenie potrafi wyjechac poza pasek.
// Sygnatura zawartości paska BEZ zaznaczenia: zmiana samego zaznaczenia
// (strzałki, klik) tylko przestawia klasę `.on` na istniejących kafelkach.
// Pełna przebudowa tworzyła kafelki od nowa, a ten pod kursorem od razu
// odpalał animację hover — przy każdej zmianie zdjęcia coś podskakiwało.
const stripContentSig = () => JSON.stringify([stripSig(S.state), S.editSaved && S.editSaved.file, S.justEdited]);

function refreshStrips() {
  const sig = stripContentSig();
  ["filmstrip", "review-strip"].forEach(id => {
    const strip = $(id);
    if (!strip) return;
    if (strip.dataset.sig === sig) {
      strip.querySelectorAll("[data-shot]").forEach(t => t.classList.toggle("on", +t.dataset.shot === S.selShot));
    } else {
      strip.innerHTML = filmstrip();
      strip.dataset.sig = sig;
    }
    const lg = $(`${id}-legend`);
    if (lg) lg.innerHTML = stripLegend();
    const tile = strip.querySelector(`[data-shot="${S.selShot}"]`);
    if (tile) {
      const a = tile.getBoundingClientRect(), b = strip.getBoundingClientRect();
      if (a.left < b.left || a.right > b.right) tile.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "smooth" });
    }
  });
}

function navShot(dir) {
  const list = S.state.shots;
  if (!list.length) return;
  const cur = S.selShot < 0 ? list.length : S.selShot;
  showShot(Math.max(0, Math.min(list.length - 1, cur + dir)), dir);
}

// ---------- potwierdzenie wyjscia z sesji (ESC na ekranie Sesji) ----------
// Modal zyje BEZPOSREDNIO w <body>, poza keyowanym renderem ekranu — rebuildy
// sesji (dolatujace zdjecia, poll) nie maja go czym zniszczyc ani odtworzyc.

function showLeaveConfirm() {
  if ($("leave-confirm")) return;
  S.leaveConfirm = true;
  const el = document.createElement("div");
  el.id = "leave-confirm";
  // modal zyje w <body>, POZA #app — klasa .ui daje mu font aplikacji.
  // Układ i animacja jak w modalu Tailwind UI (panel z opacity 0 i scale .95),
  // tylko szybciej: wejście 160 ms, zamknięcie 120 ms.
  el.className = "ui modal-root";
  el.setAttribute("role", "dialog");
  el.setAttribute("aria-modal", "true");
  el.setAttribute("aria-labelledby", "leave-title");
  el.innerHTML = `
    <div id="leave-card" class="modal-panel">
      <div style="display: flex; align-items: flex-start; gap: 16px; padding: 22px 24px 18px;">
        <div class="modal-icon">${icon("leave", 22, 1.6)}</div>
        <div style="min-width: 0; padding-top: 2px;">
          <h3 id="leave-title" style="margin: 0; font-size: 16px; font-weight: 700; color: var(--text);">Wrócić do listy sesji?</h3>
          <p style="margin: 8px 0 0; font-size: 13px; line-height: 1.5; color: var(--muted);">Sesja zostanie zamknięta. Zdjęcia są zapisane.</p>
        </div>
      </div>
      <div class="modal-foot">
        <button type="button" class="btn" onclick="hideLeaveConfirm()">Zostań <span class="kbd">ESC</span></button>
        <button type="button" class="btn btn-primary" onclick="confirmLeave()">Wróć do listy <span class="kbd">ENTER</span></button>
      </div>
    </div>`;
  // klik w przyciemnione tlo = anuluj (ten sam gest co ESC)
  el.addEventListener("click", ev => { if (ev.target === el) hideLeaveConfirm(); });
  document.body.appendChild(el);
  requestAnimationFrame(() => requestAnimationFrame(() => el.classList.add("open")));
}

function hideLeaveConfirm() {
  S.leaveConfirm = false;
  const el = $("leave-confirm");
  if (!el) return;
  el.classList.remove("open");
  el.classList.add("closing");
  setTimeout(() => el.remove(), 130);
}

function confirmLeave() {
  hideLeaveConfirm();
  leaveSession();
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
  if (S.edit) closeEdit();
  S.selShot = next;
  dir = dir < 0 ? -1 : 1;
  const img = $("review-img");
  if (S.reviewMode && img) {
    // Overlay zostaje w DOM (zawsze nieprzezroczysty — zadnych przebitek live
    // view), podmieniamy tylko src: stare zdjecie wisi az nowe sie zdekoduje.
    const shot = reviewShot();
    clearTimeout(fullTimer);
    img.onload = () => reviewLoaded(img);
    img.src = shotUrl(shot, "view");
    updateReviewHeader(shot);
    // Skok musi byc WIDOCZNY, inaczej krzywa easingu nie ma czego pokazac —
    // przy poprzednich 6 px kazdy easing wygladal identycznie.
    img.style.transition = "none";
    img.style.transform = `translateX(${dir * 32}px)`;
    img.style.opacity = "0.35";
    requestAnimationFrame(() => requestAnimationFrame(() => {
      img.style.transition = "transform .34s cubic-bezier(0.32, 0.72, 0, 1), opacity .24s cubic-bezier(0.32, 0.72, 0, 1)";
      img.style.transform = "none";
      img.style.opacity = "1";
    }));
    [next - 1, next + 1].forEach(i => {
      if (list[i]) new Image().src = shotUrl(list[i], "view");
    });
    refreshStrips();
    lastSesja = sesjaKey(S.state);
  } else {
    // poza podglądem strzałki tylko przestawiają zaznaczenie w pasku —
    // przebudowa ekranu zrywała stream live view i odpalała animacje
    refreshStrips();
    lastSesja = sesjaKey(S.state);
  }
}

function deleteReviewed() {
  if (S.edit) return;   // w trakcie edycji BACKSPACE niczego nie kasuje
  const shot = reviewShot();
  if (!shot) return;
  const sess = S.state.session.name;
  post({ action: "delete", session: sess, files: [shot.file] });
  const list = S.state.shots;
  list.splice(shot.i, 1);
  const img = $("review-img");

  if (!list.length) {
    // ostatnie zdjecie — powrot do live (tu przejscie w przezroczystosc
    // jest zamierzone, odslania podglad z aparatu)
    S.selShot = -1;
    S.reviewMode = false;
    const main = $("review-main");
    if (main) {
      main.style.opacity = "0";
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
  // Overlay zostaje kryjacy — animuje sie TYLKO obrazek na ciemnym tle,
  // wiec live view nie przebija. Nastepne zdjecie podmieniamy w miejscu
  // (zadnego pelnego rebuildu z powtorka animacji wejscia).
  const nextShot = reviewShot();
  img.style.transition = "transform .16s ease-in, opacity .16s ease-in";
  img.style.transform = "scale(.85) translateY(36px)";
  img.style.opacity = "0";
  setTimeout(() => {
    updateReviewHeader(nextShot);
    img.style.transition = "none";
    img.style.transform = "scale(.96)";
    const show = () => {
      img.onload = () => reviewLoaded(img);
      img.style.transition = "transform .15s ease-out, opacity .15s ease-out";
      img.style.transform = "none";
      img.style.opacity = "1";
    };
    img.onload = () => { reviewLoaded(img); show(); };
    img.src = shotUrl(nextShot, "view");
    setTimeout(show, 250);
    refreshStrips();
    lastSesja = sesjaKey(S.state);
  }, 170);
}

// Zamkniecie wygasza TYLKO gorna czesc (zdjecie) — pasek zdjec i log stoja
// w miejscu, bo pod spodem na ekranie sesji sa dokladnie w tym samym miejscu.
// Wczesniej caly podglad malal do .96 razem z paskiem i miniatury podskakiwaly.
function closeReview() {
  S.edit = null;
  clearTimeout(fullTimer);
  const main = $("review-main");
  if (!main) { S.reviewMode = false; renderScreens(); return; }
  main.style.opacity = "0";
  const img = $("review-img");
  if (img) {
    img.style.transition = "transform .24s cubic-bezier(0.32, 0.72, 0, 1)";
    img.style.transform = "scale(.96)";
  }
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

// ---------- filmstrip ----------

// Wymiary pasa i kafelków są w style.css (.strip-box, .shot) — na niskim
// ekranie kurczą się w media query.
const stripBox = "";

// Adres zdjecia sesji z wersja pliku (`v`) — serwer pozwala go trzymac
// w cache na stale, wiec przebudowa paska nie pobiera miniatur od nowa.
// `kind`: true / "thumb" = miniatura paska, "view" = podgląd na całe okno
// (1800 px), brak = oryginał.
function shotUrl(shot, kind) {
  const sess = encodeURIComponent(S.state.session.name);
  const k = kind === "view" ? "&view=1" : kind ? "&thumb=1" : "";
  return `/img?s=${sess}&f=${encodeURIComponent(shot.file)}&v=${shot.v || 0}${k}`;
}

function filmstrip() {
  const st = S.state;
  const es = S.editSaved;
  const items = st.shots.map((s, i) => {
    const ss = shotState(s);
    let fx = "";
    if (es && es.file === s.file) {
      if (s.v !== es.v) {
        // nowa wersja dojechała — jednorazowa animacja, potem flaga znika
        S.editSaved = null;
        S.justEdited = s.file;
        setTimeout(() => { if (S.justEdited === s.file) S.justEdited = null; }, 900);
      } else if (st.editSaving === s.file || performance.now() - es.since < 4000) {
        fx = " saving";
      } else {
        S.editSaved = null;   // zapis padł (powód w logu) — kafelek wraca do normy
      }
    }
    if (S.justEdited === s.file) fx = " edited";
    const cls = `shot${i === S.selShot ? " on" : ""}${s.status === "rejected" ? " rejected" : ""}${fx}`;
    return `
    <button type="button" data-shot="${i}" class="${cls}" title="${s.file}${ss.text ? ` · ${ss.text}` : ""}" aria-label="Zdjęcie ${i + 1}" onclick="openShot(${i})" style="background-image: url('${shotUrl(s, true)}');">
      <span class="shot-n">#${i + 1}</span>
      ${ss.cls ? `<span class="dot ${ss.cls}"></span>` : ""}
    </button>`;
  });
  if (st.processing) {
    items.push(`<div class="shot-wait" title="${st.processing}">Obróbka…<span class="indet"></span></div>`);
  }
  // pobieranie zdjec sesji z Automatu — kafelek-skeleton az plik wyladuje na dysku
  (st.downloading || []).forEach(() => {
    items.push(`<div class="skeleton shot-skel">Pobieranie…</div>`);
  });
  return items.join("") || `<div style="font-size: 12.5px; color: var(--muted-2); align-self: center;">Brak zdjęć. Naciśnij ENTER, żeby zrobić pierwsze.</div>`;
}
