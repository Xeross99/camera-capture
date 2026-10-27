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
  const evActive = cam.ev && !S.evPending;
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
          ${liveOn ? `<img id="live" src="/stream" alt="Podgląd na żywo" style="position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain;" />` : ""}
          <div style="font-size: 14px; font-weight: 600; color: ${st.connected ? "var(--muted)" : "var(--err-fg)"};">${st.connected ? "Podgląd na żywo" : "Aparat rozłączony"}</div>
          <div style="font-size: 12.5px; color: var(--muted-2);">${!st.connected ? "Sprawdź kabel i tryb aparatu. Łączę ponownie…" : st.previewOn ? "Czekam na klatki z aparatu…" : "Podgląd wyłączony, włącz klawiszem P"}</div>
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

          <div id="warmup-overlay" style="position: absolute; inset: 0; display: ${st.warmup != null ? "flex" : "none"}; align-items: center; justify-content: center; background: rgba(10,10,12,.72); z-index: 3;">
            <div class="panel" style="display: flex; flex-direction: column; align-items: center; gap: 10px; padding: 20px 26px; max-width: 78%; text-align: center;">
              <span class="spinner" style="width: 18px; height: 18px;"></span>
              <div style="font-size: 14px; font-weight: 600; color: var(--text);">Przygotowuję silnik czyszczenia tła… <span id="warmup-s">${st.warmup != null ? st.warmup : 0}</span> s</div>
              <div style="font-size: 12.5px; line-height: 1.5; color: var(--muted);">Pierwsze uruchomienie na karcie graficznej trwa do 2 minut.<br>Zdjęcia można robić: poczekają w kolejce.</div>
            </div>
          </div>
          <div id="flash" style="position: absolute; inset: 0; background: #fff; opacity: 0; pointer-events: none; z-index: 4;"></div>
        </div>
      </section>
    </main>

    <aside aria-label="Ustawienia zdjęcia" style="width: 360px; flex: 0 0 360px; box-sizing: border-box; display: flex; flex-direction: column; min-height: 0; background: var(--surface); border-left: 1px solid var(--border);">
      <div style="flex: 1; min-height: 0; overflow-y: auto; overflow-x: hidden; padding: 18px 18px 12px; display: flex; flex-direction: column; gap: 16px;">

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
          <div style="display: flex; align-items: center; gap: 12px;">
            <div style="flex: 1; min-width: 0;">
              <div class="row-title">Kompensacja ekspozycji</div>
              <div id="ev-hint" class="row-desc">${evHint(st)}</div>
            </div>
            <div style="flex-shrink: 0; display: flex; align-items: center; border: 1px solid var(--border-strong); border-radius: 9px; overflow: hidden;">
              <span id="ev-minus" class="ev-btn${evActive ? "" : " off"}" role="button" aria-label="Ciemniej" onclick="stepEv(-1)" style="width: 36px; line-height: 36px; text-align: center; font-size: 16px; color: var(--text-2); cursor: pointer; opacity: ${evActive ? 1 : .35};">−</span>
              <span id="ev-value" class="mono" style="position: relative; width: 58px; line-height: 36px; text-align: center; font-size: 13px; font-weight: 500; color: var(--text); border-left: 1px solid var(--border); border-right: 1px solid var(--border);">${evValueHtml(cam.ev)}</span>
              <span id="ev-plus" class="ev-btn${evActive ? "" : " off"}" role="button" aria-label="Jaśniej" onclick="stepEv(1)" style="width: 36px; line-height: 36px; text-align: center; font-size: 16px; color: var(--text-2); cursor: pointer; opacity: ${evActive ? 1 : .35};">+</span>
            </div>
          </div>
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

      <div style="flex: 0 0 auto; padding: 14px 18px 16px; border-top: 1px solid var(--border);">
        <button type="button" class="shutter" onclick="shoot()"><span id="shoot-spin" class="spinner" style="flex: 0 0 auto; border-color: rgba(255,255,255,.35); border-top-color: #fff; display: ${shootBusy(st) ? "inline-block" : "none"};"></span>${icon("camera", 20, 1.8)}<span id="shoot-label">${st.busy || "Zrób zdjęcie"}</span><span class="kbd">ENTER</span></button>
      </div>
    </aside>
    </div>
    ${stripPanel("filmstrip")}
    ${logBar("log")}
    </div>

    <div id="review-slot">${reviewOverlay()}</div>`;
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

// Kontrolka jest widoczna ZAWSZE, tylko wyszarzona gdy nie ma czego ustawiać, a
// powód stoi wprost pod nią. Znikająca kontrolka nie mówi operatorowi, czego
// szukać ani dlaczego jej nie ma — a tooltip trzeba najpierw znaleźć myszą.
function evHint(st) {
  if (!st.connected) return "Aparat rozłączony.";
  if (!(st.camera && st.camera.ev))
    return "Niedostępna w tym trybie aparatu. Ustaw pokrętło na P, Av albo Tv.";
  return "Jaśniej, gdy tło wychodzi szare.";
}

function stepEv(dir) {
  const ev = S.state.camera && S.state.camera.ev;
  if (S.evPending || !ev || !ev.choices || !ev.choices.length) return;
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
  // Docelowa wartość jest widoczna od razu (przygaszona, ze spinnerem NAD nią),
  // a przyciski są zablokowane, aż aparat ODDA nową wartość (poll EV co 2 s).
  // Źródłem prawdy jest aparat — gdy odrzuci wartość, timeout w evReconcile()
  // przywraca kontrolkę ze starą (powód ląduje w logu z _do_set_ev).
  S.evPending = { target: hit.n, label: next, since: performance.now() };
  evReconcile(S.state);
  post({ action: "set_ev", value: next });
}

// Zawartość celi z wartością EV. W trakcie czekania na aparat: docelowa
// wartość przygaszona + spinner POZYCJONOWANY ABSOLUTNIE nad nią (`.ev-spin`)
// — spinner w miejscu tekstu był wyższy niż linijka tekstu i cała karta
// podskakiwała o 2 px na czas ładowania.
function evValueHtml(ev) {
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
  if (S.evPending) {
    if (!val.querySelector(".spinner")) val.innerHTML = evValueHtml(ev);
  } else {
    val.textContent = ev ? evLabel(ev.current) : "—";
  }
  const hint = $("ev-hint");
  if (hint) hint.textContent = evHint(st);
  const ov = $("ev-overlay");
  if (ov) {
    ov.style.display = ev ? "flex" : "none";
    if (ev) ov.textContent = `EV ${evLabel(ev.current)}`;
  }
  const active = !!ev && !S.evPending;
  ["ev-minus", "ev-plus"].forEach(id => {
    const b = $(id);
    if (!b) return;
    b.style.opacity = active ? 1 : .35;
    b.classList.toggle("off", !active);
  });
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
  const prev = $("review-prev"), next = $("review-next");
  if (prev) prev.disabled = shot.i <= 0;
  if (next) next.disabled = shot.i >= n - 1;
}

// Rozmiar gotowego pliku z samego obrazka (bez pytania backendu).
function reviewSize(img) {
  const el = $("review-size");
  // podgląd edycji jest zmniejszony — jego wymiary nie są wymiarami pliku
  if (el && img.naturalWidth && !img.src.includes("/edit_preview")) {
    el.textContent = `${img.naturalWidth} × ${img.naturalHeight}`;
    el.style.display = "";
  }
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
        <img id="review-img" src="${shotUrl(shot)}" alt="" onload="reviewSize(this)" style="position: absolute; left: 88px; right: 88px; top: 20px; bottom: 20px; width: calc(100% - 176px); height: calc(100% - 40px); object-fit: contain; animation: reviewIn .32s cubic-bezier(0.32, 0.72, 0, 1);" />
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
  if (img && shot) img.src = shotUrl(shot);
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
      <div id="${id}" data-sig='${stripContentSig().replace(/'/g, "&#39;")}' style="${stripBox}">${filmstrip()}</div>
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
    ${post_.logoChoice ? "" : `<div class="row-desc">Teraz: własny plik logo z Ustawień.</div>`}
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
  // modal zyje w <body>, POZA #app — klasa .ui daje mu font aplikacji
  el.className = "ui";
  el.style.cssText = "position: fixed; inset: 0; z-index: 80; display: flex; align-items: center; justify-content: center; background: rgba(20,20,24,.28); -webkit-backdrop-filter: blur(3px); backdrop-filter: blur(3px); opacity: 0; transition: opacity .18s ease;";
  el.innerHTML = `
    <div id="leave-card" class="panel" style="padding: 22px 24px; max-width: 400px; display: flex; flex-direction: column; gap: 12px; transform: scale(.94) translateY(8px); transition: transform .22s cubic-bezier(0.16, 1, 0.3, 1); box-shadow: 0 18px 50px var(--shadow);">
      <div style="font-size: 16px; font-weight: 700; color: var(--text);">Wrócić do listy sesji?</div>
      <div style="font-size: 13px; line-height: 1.5; color: var(--muted);">Sesja zostanie zamknięta. Zdjęcia są zapisane.</div>
      <div style="display: flex; gap: 8px; justify-content: flex-end; margin-top: 4px;">
        <button type="button" class="btn" onclick="hideLeaveConfirm()">Zostań <span class="kbd">ESC</span></button>
        <button type="button" class="btn btn-primary" onclick="confirmLeave()">Wróć do listy <span class="kbd">ENTER</span></button>
      </div>
    </div>`;
  // klik w przyciemnione tlo = anuluj (ten sam gest co ESC)
  el.addEventListener("click", ev => { if (ev.target === el) hideLeaveConfirm(); });
  document.body.appendChild(el);
  requestAnimationFrame(() => requestAnimationFrame(() => {
    el.style.opacity = "1";
    const card = $("leave-card");
    if (card) card.style.transform = "none";
  }));
}

function hideLeaveConfirm() {
  S.leaveConfirm = false;
  const el = $("leave-confirm");
  if (!el) return;
  el.style.opacity = "0";
  const card = $("leave-card");
  if (card) card.style.transform = "scale(.94) translateY(8px)";
  setTimeout(() => el.remove(), 200);
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
    img.src = shotUrl(shot);
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
      if (list[i]) new Image().src = shotUrl(list[i]);
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
      img.onload = () => reviewSize(img);
      img.style.transition = "transform .15s ease-out, opacity .15s ease-out";
      img.style.transform = "none";
      img.style.opacity = "1";
    };
    img.onload = () => { reviewSize(img); show(); };
    img.src = shotUrl(nextShot);
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

// Pas ma STAŁĄ wysokość: kafelek 84 + 8 na poziomy scrollbar, który pojawia
// się przy przepełnieniu. Bez tego pusty stan był niższy niż kafelki i całe
// menu pod spodem podskakiwało przy pierwszym zdjęciu.
// Padding z ujemnym marginesem: miejsce na powiekszenie kafelka na hover
// (pasek przewija sie w poziomie, wiec ucina wszystko poza swoim pudelkiem),
// a kafelki stoja tam, gdzie staly.
const stripBox = "height: 92px; padding: 6px; margin: -6px; display: flex; align-items: flex-start; gap: 10px; overflow-x: auto; overflow-y: hidden;";

// Adres zdjecia sesji z wersja pliku (`v`) — serwer pozwala go trzymac
// w cache na stale, wiec przebudowa paska nie pobiera miniatur od nowa.
function shotUrl(shot, thumb) {
  const sess = encodeURIComponent(S.state.session.name);
  return `/img?s=${sess}&f=${encodeURIComponent(shot.file)}&v=${shot.v || 0}${thumb ? "&thumb=1" : ""}`;
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
    items.push(`<div class="skeleton" style="width: 112px; height: 84px; flex: 0 0 112px; border-radius: 9px; display: flex; align-items: center; justify-content: center; font-size: 11.5px; color: var(--muted-2);">Pobieranie…</div>`);
  });
  return items.join("") || `<div style="font-size: 12.5px; color: var(--muted-2); align-self: center;">Brak zdjęć. Naciśnij ENTER, żeby zrobić pierwsze.</div>`;
}
