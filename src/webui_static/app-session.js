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
          <div id="warmup-overlay" style="position: absolute; inset: 0; display: ${st.warmup != null ? "flex" : "none"}; align-items: center; justify-content: center; background: rgba(10,10,12,.72); z-index: 3;">
            <div style="display: flex; flex-direction: column; align-items: center; gap: 10px; background: #1d1d20; border: 1px solid #3c3c44; border-radius: 8px; padding: 18px 26px; max-width: 78%; text-align: center;">
              <span class="spinner" style="width: 18px; height: 18px;"></span>
              <div style="font-size: 13.5px; font-weight: 600; color: #eaeaee;">Przygotowuję silnik czyszczenia tła… <span id="warmup-s">${st.warmup != null ? st.warmup : 0}</span> s</div>
              <div style="${mono} font-size: 11px; color: #9d9da3; line-height: 1.5;">Pierwsze uruchomienie na GPU kompiluje shadery — do ~2 min.<br>Zdjęcia można robić: poczekają w kolejce i obrobią się po rozgrzewce.</div>
            </div>
          </div>
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
        <div id="filmstrip" style="${stripBox}">${filmstrip()}</div>
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
              <span id="ev-minus" class="ev-btn${cam.ev && !S.evPending ? "" : " off"}" onclick="stepEv(-1)" style="padding: 5px 11px; color: #d0d0d6; opacity: ${cam.ev && !S.evPending ? 1 : .35};">−</span>
              <span id="ev-value" style="min-width: 44px; padding: 5px 0; text-align: center; color: #eaeaee; border-left: 1px solid #3d3d44; border-right: 1px solid #3d3d44;">${S.evPending ? '<span class="spinner"></span>' : cam.ev ? evLabel(cam.ev.current) : "—"}</span>
              <span id="ev-plus" class="ev-btn${cam.ev && !S.evPending ? "" : " off"}" onclick="stepEv(1)" style="padding: 5px 11px; color: #d0d0d6; opacity: ${cam.ev && !S.evPending ? 1 : .35};">+</span>
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
                           ${post_.logoPositions.map(p => `<option value="${p}" ${p === post_.logoPosition ? "selected" : ""}>${LOGO_POS_PL[p] || p}</option>`).join("")}
                         </select>
                       </div>`)}
          ${optionRow("zoom", post_.zoom, "Przybliżanie",
                      "Kadr dociąga się do produktu — bez tego zostaje naturalna skala z klatki.")}
          ${optionRow("center", post_.center, "Centrowanie",
                      "Produkt ląduje na środku kadru zamiast tam, gdzie wypadł na stole.")}
          ${optionRow("cleanbg", post_.cleanBg, "Wyrównanie tła do bieli",
                      "Tło dociągane do czystej bieli, cienie pod produktem wygaszane.")}
        </div>

        ${robotCard()}

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
  // Zamiast optymistycznego echa: spinner i zablokowane przyciski, aż aparat
  // ODDA nową wartość (poll EV co 2 s). Źródłem prawdy jest aparat — gdy
  // odrzuci wartość, timeout w evReconcile() przywraca kontrolkę ze starą
  // (powód ląduje w logu z _do_set_ev).
  S.evPending = { target: hit.n, since: performance.now() };
  evReconcile(S.state);
  post({ action: "set_ev", value: next });
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
    if (!val.querySelector(".spinner")) val.innerHTML = '<span class="spinner"></span>';
  } else {
    val.textContent = ev ? evLabel(ev.current) : "—";
  }
  const hint = $("ev-hint");
  if (hint) hint.textContent = evHint(st);
  const active = !!ev && !S.evPending;
  ["ev-minus", "ev-plus"].forEach(id => {
    const b = $(id);
    if (!b) return;
    b.style.opacity = active ? 1 : .35;
    b.classList.toggle("off", !active);
  });
}

const bgStatus = st => (st.connected && BG_LABEL[st.camera.bgStatus]) ? st.camera.bgStatus : "unknown";
const histLabel = st => BG_LABEL[bgStatus(st)];
const histColor = st => BG_COLOR[bgStatus(st)];
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
      <div id="review-strip" style="${stripBox}">${filmstrip()}</div>
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

// ---------- filmstrip ----------

// Pas ma STAŁĄ wysokość: kafelek (72 + 4 + 12 podpisu = 88) + 8 na poziomy
// scrollbar, który pojawia się przy przepełnieniu. Bez tego pusty stan
// („brak zdjęć") był niższy niż kafelki i całe menu pod spodem podskakiwało
// przy pierwszym zdjęciu — a potem drugi raz, gdy wjeżdżał scrollbar.
const stripBox = "height: 96px; display: flex; align-items: flex-start; gap: 8px; overflow-x: auto; overflow-y: hidden;";

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
      <div style="${mono} font-size: 9.5px; line-height: 12px; color: #6c6c74; margin-top: 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${s.file}</div>
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
      <div style="${mono} font-size: 9.5px; line-height: 12px; color: #6c6c74; margin-top: 4px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${st.processing}</div>
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
  return items.join("") || `<div style="${mono} font-size: 10.5px; color: #6c6c74; align-self: center;">(brak zdjęć w tej sesji)</div>`;
}
