"use strict";
// Sekcja „Robot — ustawienie ujęcia" w sidebarze Sesji: dwa ujęcia kamery i nic
// więcej. Sterowanie idzie do backendu (`robot_pose` → wątek robota w webui.py
// → src/robot.py), a prawdą o zadanym ustawieniu jest STAN Z BACKENDU —
// S.robot to tylko optymistyczne echo, żeby kliknięcie było widać zanim wróci
// poll.
//
// Suwaki „Odległość od produktu" i „Kąt kamery" zostały USUNIĘTE ŚWIADOMIE
// razem z całą mechaniką pod nimi: ujęcie to teraz zapisane kąty przegubów
// (`ROBOT_JOINTS_*`, patrz robot.py), więc nie ma czego regulować i nie ma jak
// zepsuć kadru. Każda regulacja to robiła — kadr wyjeżdżał, kąt głowicy
// rozjeżdżał się z osią patrzenia, a ta sama pozycja wychodziła inaczej po
// każdym uruchomieniu.
//
// Zmiany są łatane W MIEJSCU (robotSync), nigdy pełnym rebuildem ekranu —
// rebuild niszczy <img> streamu MJPEG (patrz anti-flicker w app-main.js).

const robotState = () => (S.state && S.state.robot) || {};

// Ramię w ruchu albo rozłączone = nie ma czym sterować.
const robotLocked = () => {
  const r = robotState();
  return !r.connected || !!r.busy;
};

// Etykiety skrótów zależą od platformy: macOS ma ⌘, Windows (WebView2) Ctrl.
// Obsługa klawiatury w app-main.js łapie metaKey I ctrlKey, więc różnią się
// tylko napisy.
const ROBOT_MAC = navigator.platform.toUpperCase().includes("MAC");
const robotKbd = k => ROBOT_MAC ? `⌘${k}` : `Ctrl+${k}`;

// Ujęcia. Klucze MUSZĄ zgadzać się z ROBOT_JOINTS w config.py — backend
// odrzuca nieznaną nazwę. `tilt` służy WYŁĄCZNIE do nachylenia kreski w ikonie:
// ujęcie to zapisane kąty przegubów, więc kąt patrzenia kamery nie jest znany
// aplikacji i nie ma czego pokazywać w tytule.
const ROBOT_POSES = {
  top90: { name: "Z góry", tilt: 90, key: robotKbd("1"), sub: "kamera pionowo nad produktem" },
  a45: { name: "Z boku", tilt: 45, key: robotKbd("2"), sub: "kamera skośnie na produkt" },
};
// Ujęcie ustawione = ma zapisane kąty w .env (ROBOT_JOINTS_*). Nieustawione
// mówi to WPROST, zamiast udawać, że ⌘1 gdzieś pojedzie — backend odmówi
// ruchu, a operator nie miałby skąd wiedzieć, czego brakuje.
const robotIsSet = p => ((robotState().set || {})[p] !== false);
const robotSub = p => robotIsSet(p) ? ROBOT_POSES[p].sub
  : "nieustawione — uruchom tools/roarm_teach.py";

const robotTileStyle = (on, locked) => `display: flex; align-items: center; gap: 12px; padding: 12px 13px; border-radius: 8px; border: 1px solid ${on ? ACCENT : "#2c2c31"}; background: ${on ? "#232a3d" : "#1f1f22"}; opacity: ${locked ? .45 : 1};`;

// Ikona ujęcia: kółko z kreską pod kątem patrzenia — pionową dla ujęcia
// z góry, nachyloną o zmierzony kąt dla skosu (kreska idzie od produktu
// w stronę kamery, więc pokazuje to samo, co tytuł kafelka).
function robotIcon(pose, on) {
  const c = on ? ACCENT : (robotIsSet(pose) ? "#6c6c74" : "#4a4a52");
  const rad = ROBOT_POSES[pose].tilt * Math.PI / 180, R = 7;
  const dx = Math.round(R * Math.cos(rad) * 10) / 10, dy = Math.round(R * Math.sin(rad) * 10) / 10;
  const line = `x1="${16 + dx}" y1="${16 - dy}" x2="${16 - dx}" y2="${16 + dy}"`;
  return `<svg width="32" height="32" viewBox="0 0 32 32" style="flex-shrink: 0; display: block;">
    <circle cx="16" cy="16" r="14" fill="none" stroke="${c}" stroke-width="1.5"/>
    <line ${line} stroke="${c}" stroke-width="2" stroke-linecap="round"/>
  </svg>`;
}

// Jedna linia stanu pod kafelkami: co robi ramię albo czemu nie robi nic.
// Znikająca sekcja nie mówiłaby operatorowi, czego szukać — panel zostaje,
// tylko wyszarzony, z powodem wprost.
function robotStatus() {
  const r = robotState();
  if (r.busy) return { text: r.busy + "…", color: "#d8c39a", spin: true };
  if (!r.connected) {
    return {
      text: r.error || "ramię rozłączone — sprawdź kabel USB i zasilanie",
      color: "#e0b96a", spin: false,
    };
  }
  return { text: "ramię gotowe", color: "#8f9a88", spin: false };
}

function robotPoseTile(p) {
  const pose = ROBOT_POSES[p], on = S.robot.pose === p;
  return `
  <div id="robot-pose-${p}" onclick="robotPose('${p}')" style="${robotTileStyle(on, robotLocked())}">
    ${robotIcon(p, on)}
    <div style="flex: 1; min-width: 0;">
      <div style="font-size: 13px; font-weight: 600; color: ${robotIsSet(p) ? "#eaeaee" : "#8a8a92"};">${pose.name}</div>
      <div id="robot-sub-${p}" style="margin-top: 2px; ${mono} font-size: 11px; color: #85858e; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${robotSub(p)}</div>
    </div>
    <div style="${mono} font-size: 11px; color: #6c6c74;">${pose.key}</div>
  </div>`;
}

function robotCard() {
  if (robotState().enabled === false) return "";   // ROBOT_ENABLED=false w .env
  const st = robotStatus();
  return `
  <div style="display: flex; flex-direction: column; gap: 8px;">
    <div style="display: flex; align-items: baseline; justify-content: space-between;">
      <div style="${head}">Robot — ustawienie ujęcia</div>
      <div style="${mono} font-size: 10.5px; color: #6c6c74;">${robotKbd("1")} … ${robotKbd("2")}</div>
    </div>

    <div id="robot-status" style="display: flex; align-items: center; gap: 7px; ${mono} font-size: 11px; color: ${st.color};">
      <span id="robot-spin" style="display: ${st.spin ? "inline-block" : "none"};" class="spinner"></span>
      <span id="robot-status-text">${st.text}</span>
    </div>

    ${robotPoseTile("top90")}
    ${robotPoseTile("a45")}
  </div>`;
}

// Dociągnięcie DOM do S.robot + stanu z backendu — wołane po każdej zmianie
// z kliknięcia, klawiatury ORAZ z updateVolatile() przy każdym pollu.
// Brak elementów (inny ekran, robot wyłączony) = nic do roboty.
function robotSync() {
  if (!$("robot-status")) return;
  const r = S.robot, locked = robotLocked(), st = robotStatus();
  Object.keys(ROBOT_POSES).forEach(p => {
    const el = $("robot-pose-" + p);
    if (!el) return;
    const on = r.pose === p;
    el.style.cssText = robotTileStyle(on, locked);
    el.querySelector("svg").outerHTML = robotIcon(p, on);
    $("robot-sub-" + p).textContent = robotSub(p);
  });
  $("robot-status").style.color = st.color;
  $("robot-status-text").textContent = st.text;
  $("robot-spin").style.display = st.spin ? "inline-block" : "none";
}

// Stan z backendu wygrywa, ale nie natychmiast po lokalnej zmianie: przez
// ~1 s po kliknięciu trzymamy własną wartość, żeby poll (500 ms) sprzed
// dotarcia POST-a nie cofał zaznaczonego kafelka.
const ROBOT_ECHO_MS = 1000;
function robotReconcile() {
  const r = robotState();
  if (r.pose != null && performance.now() - S.robot.echoAt > ROBOT_ECHO_MS) {
    S.robot.pose = r.pose;
  }
  robotSync();
}

// Odpowiedź backendu na komendę ruchu: odmowa (rozłączone ramię, trwa
// zdjęcie, pozycja poza zakresem) ma być widoczna, a nie zjedzona po cichu.
function robotPost(payload) {
  S.robot.echoAt = performance.now();
  robotSync();
  post(payload).then(r => r.json()).then(res => {
    if (res && res.ok === false) {
      S.robot.echoAt = 0;          // wracamy do prawdy z backendu przy najbliższym pollu
      const el = $("robot-status-text");
      if (el) { el.textContent = res.error; $("robot-status").style.color = "#e0b96a"; }
    }
  }).catch(() => {});
}

function robotPose(p) {
  if (!ROBOT_POSES[p] || robotLocked() || S.robot.pose === p) return;
  S.robot.pose = p;
  robotPost({ action: "robot_pose", pose: p });
}
