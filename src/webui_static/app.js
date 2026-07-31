"use strict";
const ACCENT = "#4a8cff";
const S = {           // stan klienta
  screen: "sesja", logOpen: false, state: null,
  selShot: -1, selGal: -1, galFilter: "all",
  gridOn: true, kadrOn: true, reviewMode: false, lastLogLen: -1,
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
const CAM_FIELDS = [["iso", "ISO"], ["aperture", "Przysłona"], ["shutterspeed", "Czas"],
                    ["whitebalance", "Balans bieli"], ["afmode", "Tryb AF"]];

function shell() {
  const st = S.state;
  const conn = st && st.connected;
  const tab = k => S.screen === k ? "#f2f2f5" : "#9d9da3";
  const bar = k => S.screen === k ? ACCENT : "transparent";
  return `
<div style="width: 100%; height: 100%; background: #232326; overflow: hidden; display: flex; flex-direction: column; font-family: -apple-system, 'Helvetica Neue', Helvetica, sans-serif; color: #e8e8ea; font-size: 13px;">

  <div style="height: 34px; flex: 0 0 34px; background: #2a2a2d; border-bottom: 1px solid #17171a; display: flex; align-items: stretch; padding: 0 10px; gap: 2px;">
    <div onclick="go('sesja')" style="display: flex; align-items: center; padding: 0 18px; font-size: 12.5px; font-weight: 500; cursor: default; color: ${tab("sesja")}; border-bottom: 2px solid ${bar("sesja")};">Sesja</div>
    <div onclick="go('galeria')" style="display: flex; align-items: center; padding: 0 18px; font-size: 12.5px; font-weight: 500; cursor: default; color: ${tab("galeria")}; border-bottom: 2px solid ${bar("galeria")};">Galeria</div>
    <div onclick="go('ustawienia')" style="display: flex; align-items: center; padding: 0 18px; font-size: 12.5px; font-weight: 500; cursor: default; color: ${tab("ustawienia")}; border-bottom: 2px solid ${bar("ustawienia")};">Ustawienia</div>
    <div style="margin-left: auto; display: flex; align-items: center; gap: 14px; ${mono} font-size: 11px; color: #7e7e85;">
      <div>sesja: <span style="color: #c9c9cf;" id="stat-name">—</span></div>
      <div>zdjęć: <span style="color: #c9c9cf;" id="stat-count">0</span></div>
      <div>odrzuconych: <span style="color: #c9c9cf;" id="stat-rejected">0</span></div>
      <div style="display: flex; align-items: center; gap: 7px; font-family: -apple-system, 'Helvetica Neue', Helvetica, sans-serif; font-size: 11.5px; color: #9d9da3;">
        <div style="width: 7px; height: 7px; border-radius: 50%; background: ${conn ? "#34c759" : "#e05a5a"};"></div><span id="conn-label">${conn ? `Aparat połączony · ${st.fps} fps` : "Aparat rozłączony"}</span>
      </div>
    </div>
  </div>

  <div id="screen-sesja" style="flex: 1; display: ${S.screen === "sesja" ? "flex" : "none"}; min-height: 0;"></div>
  <div id="screen-galeria" style="flex: 1; display: ${S.screen === "galeria" ? "flex" : "none"}; flex-direction: column; min-height: 0; background: #1d1d20;"></div>
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
    <div onclick='post({action: "set_session", name: ${JSON.stringify(s.name)}})' style="background: #232326; border: 1px solid #2f2f35; border-radius: 6px; padding: 14px 16px; display: flex; flex-direction: column; gap: 7px; cursor: default;"
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
  return `
  <div style="flex: 1; overflow: auto; background: #1d1d20; padding: 26px 32px; display: flex; flex-direction: column; gap: 18px; min-width: 0;">
    <div style="display: flex; flex-direction: column; gap: 8px;">
      <div style="${head}">Nowa sesja zdjęciowa</div>
      <div style="display: flex; gap: 8px; max-width: 560px;">
        <input id="new-session-input" placeholder="nazwa produktu…" style="flex: 1; ${inp} font-size: 12px; height: 32px;" />
        <button onclick="commitNewSession()" style="height: 32px; padding: 0 18px; ${btnBlue} border-radius: 5px; font-size: 12.5px; font-weight: 600;">Utwórz i otwórz</button>
      </div>
      <div style="${mono} font-size: 10.5px; color: #77777f;">nazwa = folder w photos/ i sesja w Automacie (dopasowanie do produktu po nazwie)</div>
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
  if (v) post({ action: "set_session", name: v });
}

function sesjaScreen() {
  const st = S.state, post_ = st.post, cam = st.camera;
  const bgColor = cam.bgOk ? "#9fe0a8" : "#e0b96a";
  const histText = cam.bgOk ? "HISTOGRAM OK" : "HISTOGRAM !";
  const camSelects = CAM_FIELDS.map(([key, lab]) => {
    const w = cam.settings[key];
    const opts = w ? w.choices.map(c => `<option ${c === w.current ? "selected" : ""}>${c}</option>`).join("") : "<option>—</option>";
    return `<div style="color: #b4b4bb;">${lab}</div>
      <select data-cam="${key}" ${w ? "" : "disabled"} style="${sel}">${opts}</select>`;
  }).join("");
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
            <div>SPACJA podgląd</div><div>← → wybór</div><div>A akceptuj</div><div>X odrzuć</div>
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
          <div style="${head}">Sesja zdjęciowa</div>
          <div style="display: flex; gap: 8px;">
            <input id="session-input" value="${st.session.name}" placeholder="nazwa produktu…" style="flex: 1; ${inp} font-size: 11.5px;" />
            <button onclick="commitName()" style="height: 26px; padding: 0 14px; background: linear-gradient(#4a4a50, #3d3d43); border: 1px solid #55555d; border-radius: 4px; color: #eaeaee; font-size: 12px; font-family: inherit;">Ustaw</button>
          </div>
          <div style="${mono} font-size: 10.5px; color: #77777f; word-break: break-all;">${st.session.dir || "(bez nazwy nie da się strzelić)"}</div>
          <div onclick="post({action: 'clear_session'})" style="${mono} font-size: 10.5px; color: #6aa6ff;">‹ lista sesji</div>
        </div>

        <div style="display: flex; flex-direction: column; gap: 10px;">
          <div style="${head}">Aparat</div>
          <div style="display: grid; grid-template-columns: 84px 1fr; gap: 8px 10px; align-items: center;">${camSelects}</div>
          <div style="display: flex; align-items: center; justify-content: space-between; background: #1c1c1f; border: 1px solid #303036; border-radius: 4px; padding: 7px 10px; ${mono} font-size: 10.5px; color: #8b8b93;">
            <span>ekspozycja ${cam.exposure || "—"} EV</span><span id="bg-span" style="color: ${bgColor};">tło ${cam.bg}</span>
          </div>
        </div>

        <div style="display: flex; flex-direction: column; gap: 9px;">
          <div style="${head}">Postprocessing</div>
          <label style="${label}"><input type="checkbox" ${post_.logo ? "checked" : ""} onchange="toggle('logo', this.checked)" style="${chk}" />Nakładanie logo</label>
          <div style="display: grid; grid-template-columns: 84px 1fr; gap: 8px 10px; align-items: center; padding-left: 22px;">
            <div style="color: #b4b4bb;">Pozycja</div>
            <select onchange="post({action:'set_post', key:'logo_position', value:this.value})" style="${sel}">
              ${post_.logoPositions.map(p => `<option ${p === post_.logoPosition ? "selected" : ""}>${p}</option>`).join("")}
            </select>
            <div style="color: #b4b4bb;">Krycie</div>
            <div style="display: flex; align-items: center; gap: 8px;">
              <div id="opacity-track" style="flex: 1; height: 3px; background: #3a3a41; border-radius: 2px; position: relative; cursor: default; padding: 6px 0; background-clip: content-box;">
                <div id="opacity-fill" style="position: absolute; left: 0; top: 6px; height: 3px; width: ${post_.opacity}%; background: ${ACCENT}; border-radius: 2px;"></div>
                <div id="opacity-knob" style="position: absolute; left: ${post_.opacity}%; top: 2px; width: 11px; height: 11px; margin-left: -5px; border-radius: 50%; background: #dcdce1;"></div>
              </div>
              <span id="opacity-label" style="${mono} font-size: 10.5px; color: #8b8b93;">${post_.opacity}%</span>
            </div>
          </div>
          <label style="${label}"><input type="checkbox" ${post_.zoom ? "checked" : ""} onchange="toggle('zoom', this.checked)" style="${chk}" />Przybliżanie (zoom do produktu)</label>
          <label style="${label}"><input type="checkbox" ${post_.center ? "checked" : ""} onchange="toggle('center', this.checked)" style="${chk}" />Centrowanie</label>
          <label style="${label}"><input type="checkbox" ${post_.cleanBg ? "checked" : ""} onchange="toggle('cleanbg', this.checked)" style="${chk}" />Wyrównanie tła do bieli</label>
          <label style="${label}"><input type="checkbox" ${post_.upload ? "checked" : ""} onchange="toggle('upload', this.checked)" style="${chk}" />Upload do Automatu (aplikacja web)</label>
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
  return `PODGLĄD ${shot.i + 1}/${S.state.shots.length} — ${shot.file} · ← → zmiana · ESC usuwa · SPACJA wraca do live`;
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
    img.style.transform = `translateX(${dir * 14}px)`;
    requestAnimationFrame(() => requestAnimationFrame(() => {
      img.style.transition = "transform .12s ease-out";
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
  return items.join("") || `<div style="${mono} font-size: 10.5px; color: #6c6c74; padding: 26px 0;">(brak zdjęć w tej sesji)</div>`;
}

function logMark(kind) {
  if (kind === "ok") return `<span style="color: #9fe0a8;">✓</span> `;
  if (kind === "warn") return `<span style="color: #e0b96a;">!</span> `;
  if (kind === "err") return `<span style="color: #e07a7a;">✗</span> `;
  return "";
}

function lastLogLine() {
  const log = S.state.log;
  const last = log[log.length - 1];
  if (!last) return `<span style="flex: 1;"></span>`;
  return `${logMark(last.kind)}<span style="flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${last.text}</span>`;
}

function logLines() {
  return S.state.log.map(l => `<div>${logMark(l.kind)}${l.t} · ${l.text}</div>`).join("");
}

function galFiltered() {
  const files = S.state.gallery.files;
  if (S.galFilter === "ok") return files.filter(f => f.status !== "rejected");
  if (S.galFilter === "bad") return files.filter(f => f.status === "rejected");
  return files;
}

function galeriaScreen() {
  const g = S.state.gallery;
  const nAll = g.files.length;
  const nOk = g.files.filter(f => f.status !== "rejected").length;
  const nBad = nAll - nOk;
  const nSend = g.files.filter(f => f.status !== "rejected" && !f.uploaded).length;
  const seg = (key, text) => {
    const on = S.galFilter === key;
    return `<div onclick="S.galFilter='${key}'; S.selGal=-1; renderScreens()" style="padding: 5px 12px; background: ${on ? ACCENT : "#1a1a1d"}; color: ${on ? "#fff" : "#b4b4bb"}; font-size: 11.5px; ${key !== "all" ? "border-left: 1px solid #3d3d44;" : ""}">${text}</div>`;
  };
  const tiles = galFiltered().map((f, i) => {
    const m = i === S.selGal ? MARKS.cur : (f.status === "rejected" ? MARKS.bad : (f.uploaded ? MARKS.ok : MARKS.ok));
    return `
    <div onclick="S.selGal = ${i}; renderScreens()" ondblclick="openFull('${g.session}', '${f.file}')" style="border: 1px solid ${m.border}; background: #232329;">
      <div style="aspect-ratio: 3 / 2; ${tileBg(g.session, f.file)} display: flex; align-items: flex-end; justify-content: space-between; padding: 6px;">
        <span style="${mono} font-size: 10px; color: #fff; text-shadow: 0 1px 2px #000;">#${i + 1}</span>
        <span style="${mono} font-size: 10px; color: ${m.color}; text-shadow: 0 1px 2px #000;">${f.status === "rejected" ? MARKS.bad.mark : (i === S.selGal ? MARKS.cur.mark : MARKS.ok.mark)}</span>
      </div>
      <div style="padding: 6px 7px 7px; display: flex; flex-direction: column; gap: 3px;">
        <div style="${mono} font-size: 9.5px; color: #9a9aa2; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${f.file}</div>
        <div style="${mono} font-size: 9px; color: #6c6c74;">${f.meta || "&nbsp;"}</div>
      </div>
    </div>`;
  }).join("");
  return `
    <div style="flex: 0 0 auto; display: flex; align-items: center; gap: 10px; padding: 12px 16px; border-bottom: 1px solid #2c2c31;">
      <select onchange="post({action:'gallery_session', name:this.value}); S.selGal=-1;" style="${sel} height: 26px; padding: 0 8px;">
        ${g.sessions.map(s => `<option ${s === g.session ? "selected" : ""}>${s}</option>`).join("") || "<option>—</option>"}
      </select>
      <div style="display: flex; border: 1px solid #3d3d44; border-radius: 4px; overflow: hidden;">
        ${seg("all", `Wszystkie ${nAll}`)}${seg("ok", `Zaakceptowane ${nOk}`)}${seg("bad", `Odrzucone ${nBad}`)}
      </div>
      <div style="margin-left: auto; display: flex; gap: 8px;">
        <button onclick="reprocess()" style="${btnGray}">Przetwórz ponownie</button>
        <button onclick="post({action:'batch_upload', session:'${g.session}'})" style="height: 26px; padding: 0 12px; ${btnBlue} border-radius: 4px; font-size: 12px;">Wyślij do Automatu (${nSend})</button>
      </div>
    </div>
    <div id="gal-grid" style="flex: 1; overflow: auto; padding: 16px; display: grid; grid-template-columns: repeat(6, 1fr); gap: 12px; align-content: start;">
      ${tiles || `<div style="${mono} font-size: 11px; color: #6c6c74;">(pusto)</div>`}
    </div>
    <div style="flex: 0 0 auto; border-top: 1px solid #2c2c31; padding: 8px 16px; display: flex; gap: 16px; ${mono} font-size: 10.5px; color: #7e7e85;">
      <div>ENTER pełny ekran</div><div>A akceptuj</div><div>X odrzuć</div><div>⌫ usuń plik</div><div>⌘R przetwórz ponownie</div>
    </div>`;
}

function ustawieniaScreen() {
  const st = S.state, cfg = st.settings, cam = st.camera.settings;
  const card = `display: flex; flex-direction: column; gap: 12px; background: #232326; border: 1px solid #2f2f35; border-radius: 6px; padding: 16px 18px;`;
  const defSel = (key) => {
    const w = cam[key];
    const cur = cfg.defaults[key] || (w ? w.current : "");
    const opts = w ? w.choices.map(c => `<option ${c === cur ? "selected" : ""}>${c}</option>`).join("") : `<option>${cur || "—"}</option>`;
    return `<select onchange="post({action:'set_app', key:'default_${key}', value:this.value})" ${w ? "" : "disabled"} style="${sel}">${opts}</select>`;
  };
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
      <label style="${label}"><input type="checkbox" ${cfg.autoUploadAfterAccept ? "checked" : ""} onchange="post({action:'set_app', key:'auto_upload_after_accept', value:this.checked})" style="${chk}" />Wysyłaj automatycznie po akceptacji</label>
      <div style="display: flex; align-items: center; gap: 10px;">
        <button onclick="post({action:'test_connection'})" style="${btnGray} font-size: 11.5px;">Testuj połączenie</button>
        <span style="${mono} font-size: 10.5px; color: ${cfg.testResult.startsWith("✓") ? "#9fe0a8" : "#e0b96a"};">${cfg.testResult}</span>
      </div>
    </div>

    <div style="${card}">
      <div style="${head}">Domyślne ustawienia aparatu</div>
      <div style="display: grid; grid-template-columns: 120px 1fr; gap: 8px 10px; align-items: center;">
        <div style="color: #b4b4bb;">ISO</div>${defSel("iso")}
        <div style="color: #b4b4bb;">Przysłona</div>${defSel("aperture")}
        <div style="color: #b4b4bb;">Czas</div>${defSel("shutterspeed")}
        <div style="color: #b4b4bb;">FPS podglądu</div>
        <select onchange="post({action:'set_app', key:'preview_fps', value:this.value})" style="${sel}">
          ${[10, 15, 20, 25, 30].map(f => `<option ${f === cfg.previewFps ? "selected" : ""}>${f}</option>`).join("")}
        </select>
      </div>
      <label style="${label}"><input type="checkbox" ${cfg.loadFromCamera ? "checked" : ""} onchange="post({action:'set_app', key:'load_from_camera', value:this.checked})" style="${chk}" />Wczytaj ustawienia z aparatu przy starcie</label>
    </div>

    <div style="display: flex; flex-direction: column; gap: 10px; background: #232326; border: 1px solid #2f2f35; border-radius: 6px; padding: 16px 18px;">
      <div style="${head}">Skróty klawiszowe</div>
      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 6px 18px; ${mono} font-size: 11px; color: #a8a8af;">
        <div>ENTER — zdjęcie</div><div>P — podgląd on/off</div>
        <div>SPACJA — podgląd zdjęć na live view</div><div>← → — zmiana zdjęcia / nawigacja</div>
        <div>A — akceptuj</div><div>X — odrzuć</div>
        <div>⌘R — przetwórz ponownie</div><div>⌘U — wyślij do Automatu</div>
      </div>
    </div>`;
}

// ---------- rendering ----------

let lastShellKey = "", lastSesja = "", lastGaleria = "", lastUstawienia = "";

const sesjaKey = st => JSON.stringify([st.session.name, st.session.dir, st.shots,
  st.processing, st.camera.settings, st.post, st.previewOn, S.selShot, S.logOpen,
  S.gridOn, S.kadrOn, S.reviewMode]);

function renderShell(force) {
  const st = S.state;
  const key = JSON.stringify([S.screen, st.connected]);
  if (force || key !== lastShellKey) {
    lastShellKey = key;
    const focused = document.activeElement && document.activeElement.id;
    $("app").innerHTML = shell();
    lastSesja = lastGaleria = lastUstawienia = "";
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
  const bg = $("bg-span");
  if (bg) {
    bg.textContent = `tło ${st.camera.bg}`;
    bg.style.color = bgColor;
  }
  const sl = $("shoot-label");
  if (sl) sl.textContent = st.busy || "Zrób zdjęcie";
  if (st.log.length !== S.lastLogLen) {
    S.lastLogLen = st.log.length;
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
  $("stat-rejected").textContent = st.session.rejected;
  updateVolatile(st);

  if (S.screen === "sesja" && !st.session.name) {
    const key = JSON.stringify(["start", st.automat]);
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
      S.lastLogLen = st.log.length;
      const el = document.activeElement;
      const editing = el && (el.id === "session-input") && el.value !== st.session.name;
      const keep = editing ? el.value : null;
      $("screen-sesja").innerHTML = sesjaScreen();
      if (keep !== null) { const i = $("session-input"); i.value = keep; i.focus(); }
      const strip = $("filmstrip");
      if (strip) strip.scrollLeft = strip.scrollWidth;
      const lp = $("log-panel");
      if (lp) lp.scrollTop = lp.scrollHeight;
      bindOpacity();
      document.querySelectorAll("[data-cam]").forEach(s =>
        s.onchange = () => post({ action: "set_camera", key: s.dataset.cam, value: s.value }));
    }
  } else if (S.screen === "galeria") {
    const key = JSON.stringify([st.gallery, S.selGal, S.galFilter]);
    if (force || key !== lastGaleria) {
      lastGaleria = key;
      $("screen-galeria").innerHTML = galeriaScreen();
    }
  } else {
    const key = JSON.stringify([st.settings, Object.keys(st.camera.settings)]);
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

function reprocess() {
  const g = S.state.gallery;
  const files = S.selGal >= 0 ? [galFiltered()[S.selGal].file] : galFiltered().filter(f => f.status !== "rejected").map(f => f.file);
  if (files.length) post({ action: "reprocess", session: g.session, files });
}

function openFull(sess, file) {
  $("fullscreen-img").src = `/img?s=${encodeURIComponent(sess)}&f=${encodeURIComponent(file)}`;
  $("fullscreen").style.display = "flex";
}

$("fullscreen").onclick = () => $("fullscreen").style.display = "none";

function bindOpacity() {
  const track = $("opacity-track");
  if (!track) return;
  let dragging = false;
  const apply = (e, send) => {
    const r = track.getBoundingClientRect();
    const pct = Math.max(0, Math.min(100, Math.round((e.clientX - r.left) / r.width * 100)));
    $("opacity-fill").style.width = pct + "%";
    $("opacity-knob").style.left = pct + "%";
    $("opacity-label").textContent = pct + "%";
    if (send) post({ action: "set_post", key: "opacity", value: pct });
  };
  track.onpointerdown = e => { dragging = true; track.setPointerCapture(e.pointerId); apply(e, false); };
  track.onpointermove = e => { if (dragging) apply(e, false); };
  track.onpointerup = e => { dragging = false; apply(e, true); };
}

// ---------- klawiatura ----------

document.addEventListener("keydown", e => {
  if ($("fullscreen").style.display !== "none") {
    if (e.key === "Escape" || e.key === "Enter" || e.key === " ") {
      $("fullscreen").style.display = "none";
      e.preventDefault();
    }
    return;
  }
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
  const meta = e.metaKey || e.ctrlKey;
  if (meta && e.key.toLowerCase() === "r") { e.preventDefault(); if (S.screen === "galeria") reprocess(); return; }
  if (meta && e.key.toLowerCase() === "u") { e.preventDefault(); post({ action: "batch_upload", session: S.state.gallery.session }); return; }
  if (meta) return;

  const inGal = S.screen === "galeria";
  const list = inGal ? galFiltered() : S.state.shots;
  const selKey = inGal ? "selGal" : "selShot";
  // preventDefault na wszystkim co obslugujemy — bez tego WKWebView puszcza
  // klawisz w gore responder chain i macOS robi systemowy beep
  if (["Enter", " ", "Escape", "ArrowLeft", "ArrowRight", "Backspace",
       "p", "P", "a", "A", "x", "X"].includes(e.key)) {
    e.preventDefault();
  }
  switch (e.key) {
    case "Enter":
      if (inGal) {
        const f = list[S.selGal];
        if (f) openFull(S.state.gallery.session, f.file);
      } else {
        e.preventDefault();
        shoot();
      }
      break;
    case " ":
      e.preventDefault();
      if (!inGal) toggleReview();
      break;
    case "Escape":
      if (!inGal && S.reviewMode) deleteReviewed();
      break;
    case "p": case "P": toggle("preview", !S.state.previewOn); break;
    case "ArrowLeft":
      if (inGal) {
        if (list.length) { S.selGal = Math.max(0, (S.selGal < 0 ? list.length : S.selGal) - 1); renderScreens(); }
      } else {
        navShot(-1);
      }
      break;
    case "ArrowRight":
      if (inGal) {
        if (list.length) { S.selGal = Math.min(list.length - 1, S.selGal + 1); renderScreens(); }
      } else {
        navShot(1);
      }
      break;
    case "a": case "A": reviewSelected("accepted"); break;
    case "x": case "X":
      if (S[selKey] >= 0) reviewSelected("rejected");
      else if (!inGal) post({ action: "reject_last" });
      break;
    case "Backspace": {
      const f = list[S[selKey]];
      if (inGal && f && confirm(`Usunąć ${f.file} (final + raw)?`)) {
        post({ action: "delete", session: S.state.gallery.session, files: [f.file] });
        S.selGal = -1;
      }
      break;
    }
  }
});

function reviewSelected(verdict) {
  const inGal = S.screen === "galeria";
  const list = inGal ? galFiltered() : S.state.shots;
  const idx = inGal ? S.selGal : S.selShot;
  const f = list[idx];
  if (!f) return;
  post({
    action: "review", verdict,
    session: inGal ? S.state.gallery.session : S.state.session.name,
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
