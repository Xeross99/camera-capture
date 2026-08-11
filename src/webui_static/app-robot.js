"use strict";
// Sekcja „Robot — ustawienie ujęcia" w sidebarze Sesji — SAMO UI pod
// nadchodzące ramię robota. Stan żyje lokalnie w S.robot (backendu jeszcze
// nie ma); każde miejsce, gdzie później pójdzie komenda do robota, jest
// oznaczone komentarzem „backend:".
// Zmiany są łatane W MIEJSCU (robotSync), nigdy pełnym rebuildem ekranu —
// rebuild niszczy <img> streamu MJPEG (patrz anti-flicker w app-main.js),
// a suwak ciągnięty myszą nie przeżyłby podmiany DOM pod kursorem.

const ROBOT = {
  H_MIN: 240, H_MAX: 620, H_STEP: 10,
  H_PRESETS: [280, 420, 560],
};

// Pozycje ramienia. `sub` dostaje bieżącą wysokość — opis pozycji 90° pokazuje
// ją na żywo; odsunięcie przy 45° jest na razie stałą atrapą.
const ROBOT_POSES = {
  top90: {
    title: "Z góry — 90°", key: "⌘1",
    sub: h => `ramię pionowo nad produktem · h ${h} mm`,
  },
  a45: {
    title: "Pod kątem 45°", key: "⌘2",
    sub: () => "ramię z przodu · odsunięcie 260 mm",
  },
};

const robotTileStyle = on => `display: flex; align-items: center; gap: 12px; padding: 12px 13px; border-radius: 8px; border: 1px solid ${on ? ACCENT : "#2c2c31"}; background: ${on ? "#232a3d" : "#1f1f22"};`;
const robotPresetStyle = on => `flex: 1; height: 30px; background: ${on ? "#232a3d" : "#1a1a1d"}; border: 1px solid ${on ? ACCENT : "#3d3d44"}; border-radius: 5px; color: #eaeaee; ${mono} font-size: 11.5px; font-family: 'IBM Plex Mono', monospace;`;

// Ikona pozycji: kółko z kreską — pionową (ramię z góry) albo ukośną (45°).
function robotIcon(pose, on) {
  const c = on ? ACCENT : "#6c6c74";
  const line = pose === "top90" ? 'x1="16" y1="9" x2="16" y2="23"' : 'x1="11" y1="11" x2="21" y2="21"';
  return `<svg width="32" height="32" viewBox="0 0 32 32" style="flex-shrink: 0; display: block;">
    <circle cx="16" cy="16" r="14" fill="none" stroke="${c}" stroke-width="1.5"/>
    <line ${line} stroke="${c}" stroke-width="2" stroke-linecap="round"/>
  </svg>`;
}

// Wypełnienie przebytej części toru suwaka — WebKit nie maluje go sam
// (accent-color barwi tylko kciuk), więc tor to gradient: inline przy
// renderze i podbijany z JS przy każdej zmianie wartości.
function robotTrackBg() {
  const p = 100 * (S.robot.h - ROBOT.H_MIN) / (ROBOT.H_MAX - ROBOT.H_MIN);
  return `linear-gradient(to right, ${ACCENT} ${p}%, #3a3a41 ${p}%)`;
}

function robotPoseTile(p) {
  const pose = ROBOT_POSES[p], on = S.robot.pose === p;
  return `
  <div id="robot-pose-${p}" onclick="robotPose('${p}')" style="${robotTileStyle(on)}">
    ${robotIcon(p, on)}
    <div style="flex: 1; min-width: 0;">
      <div style="font-size: 13px; font-weight: 600; color: #eaeaee;">${pose.title}</div>
      <div id="robot-sub-${p}" style="margin-top: 2px; ${mono} font-size: 11px; color: #85858e; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${pose.sub(S.robot.h)}</div>
    </div>
    <div style="${mono} font-size: 11px; color: #6c6c74;">${pose.key}</div>
  </div>`;
}

function robotCard() {
  const r = S.robot;
  const sideBtn = `flex: 0 0 30px; height: 30px; background: linear-gradient(#3f3f45, #35353a); border: 1px solid #4c4c54; border-radius: 5px; color: #eaeaee; font-size: 15px; font-family: inherit;`;
  const hint = `${mono} font-size: 10.5px; color: #6c6c74; line-height: 1.5;`;
  return `
  <div style="display: flex; flex-direction: column; gap: 8px;">
    <div style="display: flex; align-items: baseline; justify-content: space-between;">
      <div style="${head}">Robot — ustawienie ujęcia</div>
      <div style="${mono} font-size: 10.5px; color: #6c6c74;">⌘1 … ⌘2</div>
    </div>

    ${robotPoseTile("top90")}
    ${robotPoseTile("a45")}

    <div class="card" style="padding-bottom: 13px; margin-top: 4px;">
      <div style="display: flex; align-items: baseline; justify-content: space-between;">
        <div class="card-title">Wysokość nad stołem</div>
        <div style="${mono} font-size: 12.5px; color: #eaeaee;"><span id="robot-h-val">${r.h}</span> <span style="color: #7e7e85;">mm</span></div>
      </div>
      <div style="display: flex; align-items: center; gap: 10px; margin-top: 14px;">
        <button onclick="robotStep(-1)" style="${sideBtn}">−</button>
        <input id="robot-slider" class="rslider" type="range" min="${ROBOT.H_MIN}" max="${ROBOT.H_MAX}" step="${ROBOT.H_STEP}" value="${r.h}" oninput="robotSetH(+this.value)" style="background: ${robotTrackBg()};" />
        <button onclick="robotStep(1)" style="${sideBtn}">+</button>
      </div>
      <div style="display: flex; justify-content: space-between; gap: 10px; margin-top: 9px;">
        <div style="${hint}">${ROBOT.H_MIN} mm<br>bliżej</div>
        <div style="${hint} text-align: center;">⌘− oddal · ⌘= przybliż · krok ${ROBOT.H_STEP} mm</div>
        <div style="${hint} text-align: right;">${ROBOT.H_MAX} mm<br>dalej</div>
      </div>
      <div style="display: flex; gap: 8px; margin-top: 12px;">
        ${ROBOT.H_PRESETS.map(v => `<button id="robot-preset-${v}" onclick="robotSetH(${v})" style="${robotPresetStyle(r.h === v)}">${v} mm</button>`).join("")}
      </div>
    </div>
  </div>`;
}

// Dociągnięcie DOM do S.robot — wołane po każdej zmianie z kliknięcia,
// klawiatury albo suwaka. Brak elementów (inny ekran) = nic do roboty.
function robotSync() {
  const r = S.robot;
  const sl = $("robot-slider");
  if (!sl) return;
  Object.keys(ROBOT_POSES).forEach(p => {
    const el = $("robot-pose-" + p);
    if (!el) return;
    const on = r.pose === p;
    el.style.cssText = robotTileStyle(on);
    el.querySelector("svg").outerHTML = robotIcon(p, on);
    $("robot-sub-" + p).textContent = ROBOT_POSES[p].sub(r.h);
  });
  $("robot-h-val").textContent = r.h;
  sl.value = r.h;
  sl.style.background = robotTrackBg();
  ROBOT.H_PRESETS.forEach(v => {
    const b = $("robot-preset-" + v);
    if (b) b.style.cssText = robotPresetStyle(r.h === v);
  });
}

function robotPose(p) {
  if (!ROBOT_POSES[p] || S.robot.pose === p) return;
  S.robot.pose = p;
  robotSync();
  // backend: tu pójdzie komenda ustawienia pozycji ramienia,
  // np. post({ action: "robot_pose", pose: p })
}

function robotSetH(h) {
  const step = Math.round(h / ROBOT.H_STEP) * ROBOT.H_STEP;
  S.robot.h = Math.max(ROBOT.H_MIN, Math.min(ROBOT.H_MAX, step));
  robotSync();
  // backend: tu pójdzie komenda wysokości ramienia,
  // np. post({ action: "robot_height", mm: S.robot.h })
}

function robotStep(dir) {
  robotSetH(S.robot.h + dir * ROBOT.H_STEP);
}
