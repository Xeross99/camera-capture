"use strict";
// Frontend jest podzielony na klasyczne skrypty ladowane kolejno w index.html
// (wspolny globalny scope, zadnych modulow — tak jak byl jeden app.js):
//   app-core.js     — stan S, style, wspolne helpery (ten plik)
//   app-start.js    — ekran startowy (lista sesji z Automatu)
//   app-session.js  — zakladka Sesja (live view, filmstrip, podglad zdjec)
//   app-settings.js — zakladka Ustawienia + akcje aktualizacji
//   app-main.js     — shell, render keyowany, klawiatura, petla /api/state
// Jedyny top-level kod wykonywany przy ladowaniu (tick(), listener klawiatury)
// siedzi w app-main.js, dlatego MUSI byc ostatni.
const ACCENT = "#4a8cff";
const S = {           // stan klienta
  screen: "sesja", logOpen: false, state: null,
  selShot: -1,
  grid: 0, reviewMode: false, lastLogLen: -1,
  pendingNew: null,   // {name, match} — wpisana nazwa koliduje z istniejącą sesją Automatu
  evPending: null,    // {target, label, since} — klik w −/+ czeka, aż aparat ODDA nową wartość
                      // (spinner w kontrolce EV; czyści evReconcile w app-session.js)
  updateDismissed: "",// wersja, dla której operator kliknął „Później"
  checkStartedAt: 0,  // klik w „Sprawdź aktualizacje" — minimalny czas spinnera
  dayFocus: "",       // podświetlony dzień na osi ekranu startowego
  sessionFilter: "",  // filtr listy sesji na ekranie startowym (nazwa/produkt)
  leaveConfirm: false,// modal „wrócić do menu głównego?" (ESC na ekranie Sesji)
  pickIdx: -1,        // zaznaczony kafelek na ekranie startowym (nawigacja
  pickList: null,     // strzałkami/hover, ENTER wchodzi); lista = widoczne sesje
  // ustawienie ujęcia ramienia — optymistyczne echo stanu z backendu
  // (state.robot); prawdą jest webui.py, patrz robotReconcile w app-robot.js
  robot: { pose: "top90", echoAt: 0 },
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

// Wiersz opcji w sidebarze: checkbox, tytul i opis pod spodem, wiersze rozdzielone
// hairline'em. Sam checkbox z jednym slowem nie mowil, co wlasciwie robi.
// `extra` (np. wybor rogu logo) siedzi POZA <label>, inaczej klik w select
// przelaczalby checkbox.
const optionRow = (key, checked, title, desc, extra = "") => `
  <div class="opt-row">
    <label style="display: flex; align-items: flex-start; gap: 9px;">
      <input type="checkbox" ${checked ? "checked" : ""} onchange="toggle('${key}', this.checked)" style="${chk} margin-top: 1px; flex-shrink: 0;" />
      <span style="flex: 1; min-width: 0;">
        <span style="display: block; font-size: 12.5px; color: #eaeaee;">${title}</span>
        <span style="display: block; margin-top: 3px; font-size: 11.5px; line-height: 1.5; color: #85858e;">${desc}</span>
      </span>
    </label>
    ${extra ? `<div style="padding-left: 23px;">${extra}</div>` : ""}
  </div>`;
// Siatka kadrowania jak w aparacie (M50 II: 3×3 / 6×4). Domyślnie 6×4 — to
// samo, co operator widzi na ekranie aparatu. Klik w badge cykluje.
// Etykiety pozycji logo po polsku; value w <option> zostaje angielskie —
// to identyfikatory backendu (LOGO_POSITIONS w image_processing.py).
const LOGO_POS_PL = {
  "bottom-right": "prawy dolny róg",
  "bottom-left": "lewy dolny róg",
  "top-right": "prawy górny róg",
  "top-left": "lewy górny róg",
};

const GRIDS = [
  { cols: 6, rows: 4, label: "SIATKA 6×4" },
  { cols: 3, rows: 3, label: "SIATKA 3×3" },
  { cols: 0, rows: 0, label: "SIATKA OFF" },
];

/** Linie siatki jako gradienty CSS — ciemne, bo produktówka jest na bieli
 *  (poprzednia biała siatka na białym tle była po prostu niewidoczna).
 *
 *  Twarde stopy ±1px (linia 2px), nie rampa przez ułamek piksela: rampa
 *  transparent→kolor→transparent na szerokości 1px przy pozycjach
 *  ułamkowych (33.333% w 3×3) miała szczyt między fizycznymi pikselami
 *  i przeglądarka interpolowała ją do niewidzialności — poziome linie
 *  3×3 po prostu znikały. Twarda 2px linia zawsze pokrywa piksel. */
function gridBackground(cols, rows) {
  const line = "rgba(0, 0, 0, .3)";
  const parts = [];
  for (let i = 1; i < cols; i++) {
    const p = (100 * i / cols).toFixed(3);
    parts.push(`linear-gradient(to right, transparent calc(${p}% - 1px), ${line} calc(${p}% - 1px), ${line} calc(${p}% + 1px), transparent calc(${p}% + 1px))`);
  }
  for (let i = 1; i < rows; i++) {
    const p = (100 * i / rows).toFixed(3);
    parts.push(`linear-gradient(to bottom, transparent calc(${p}% - 1px), ${line} calc(${p}% - 1px), ${line} calc(${p}% + 1px), transparent calc(${p}% + 1px))`);
  }
  return parts.join(", ");
}

const MARKS = {
  ok:   { mark: "✓", color: "#9fe0a8", border: "#3a3a42" },
  bad:  { mark: "✕", color: "#e07a7a", border: "#5a3a3a" },
  cur:  { mark: "●", color: ACCENT,   border: ACCENT },
  wait: { mark: "…", color: "#e0b96a", border: "#3a3a42" },
};

// ---------- daty / polska odmiana ----------

const PL_MONTHS = ["stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca",
  "lipca", "sierpnia", "września", "października", "listopada", "grudnia"];
const plForm = (n, one, few, many) =>
  n === 1 ? one : (n % 10 >= 2 && n % 10 <= 4 && !(n % 100 >= 12 && n % 100 <= 14) ? few : many);
const plSessions = n => `${n} ${plForm(n, "sesja zdjęciowa", "sesje zdjęciowe", "sesji zdjęciowych")}`;
const plPhotos = n => `${n} ${plForm(n, "zdjęcie", "zdjęcia", "zdjęć")}`;
const plDay = d => `${d.getDate()} ${PL_MONTHS[d.getMonth()]} ${d.getFullYear()}`;
const hhmm = d => `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
const fmtDate = iso => {
  const d = new Date(iso);
  return isNaN(d) ? "" : `${String(d.getDate()).padStart(2, "0")}.${String(d.getMonth() + 1).padStart(2, "0")} ${hhmm(d)}`;
};
const CAM_ICON = `<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" style="width: 12px; height: 12px; display: block;"><path d="M12 9a3.75 3.75 0 1 0 0 7.5A3.75 3.75 0 0 0 12 9Z" /><path fill-rule="evenodd" clip-rule="evenodd" d="M9.344 3.071a49.5 49.5 0 0 1 5.312 0c.967.052 1.83.585 2.332 1.39l.821 1.317c.24.383.645.643 1.11.71.386.054.77.113 1.152.177 1.432.239 2.429 1.493 2.429 2.909V18a3 3 0 0 1-3 3h-15a3 3 0 0 1-3-3V9.574c0-1.416.997-2.67 2.429-2.909.382-.064.766-.123 1.151-.178a1.56 1.56 0 0 0 1.11-.71l.822-1.315a2.94 2.94 0 0 1 2.332-1.39ZM6.75 12.75a5.25 5.25 0 1 1 10.5 0 5.25 5.25 0 0 1-10.5 0Z" /></svg>`;

// Ramie robota (podstawa + dwa segmenty + przeguby i glowica) — do statusu
// ramienia w pasku zakladek, w parze z CAM_ICON dla aparatu. Kreski, nie fill:
// sylwetka ramienia w 12 px czytelna jest tylko grubym strokiem.
const ROBOT_ICON = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="width: 12px; height: 12px; display: block;"><path d="M4.5 21h9" /><path d="M9 21v-5" /><path d="M9 16l6-8" /><path d="M15 8l4 2.2" /><circle cx="9" cy="16" r="1.5" fill="currentColor" stroke="none" /><circle cx="15" cy="8" r="1.5" fill="currentColor" stroke="none" /><circle cx="20.3" cy="10.9" r="1.9" fill="currentColor" stroke="none" /></svg>`;

// ---------- kompensacja ekspozycji (liczby, nie tekst) ----------

// Kompensacja ekspozycji. Backendy mówią różnymi słowami: „+2 2/3" (EDSDK),
// „+3.0" (digiCamControl), „0.3" (gphoto2) — a bywa, że odczyt bieżącej
// wartości i lista kroków są w RÓŻNYCH zapisach w obrębie jednego aparatu.
// Dlatego liczymy na liczbach, a nie na tekście: `+` idzie do najbliższej
// wartości WIĘKSZEJ, `−` do najbliższej mniejszej. Poprzednia wersja szukała
// bieżącej wartości w liście przez `indexOf` i przy niedopasowanym zapisie
// dostawała -1, czyli „zacznij od początku listy" — stąd `+` z +3.0 lądujące
// na +2 2/3, czyli przycisk plus zmniejszający ekspozycję.
function evNumber(v) {
  let s = String(v == null ? "" : v).trim().replace(/−/g, "-").replace(/^\+/, "");
  if (!s) return null;
  let sign = 1;
  if (s[0] === "-") { sign = -1; s = s.slice(1).trim(); }
  let total = 0, seen = false;
  for (const part of s.split(/\s+/)) {
    const frac = part.match(/^(\d+)\/(\d+)$/);
    if (frac && +frac[2] !== 0) { total += (+frac[1]) / (+frac[2]); seen = true; continue; }
    if (/^\d+(\.\d+)?$/.test(part)) { total += parseFloat(part); seen = true; continue; }
    return null;   // nieznany zapis — lepiej nie zgadywać niż zgadnąć źle
  }
  return seen ? sign * total : null;
}

function evLabel(v) {
  const s = String(v == null ? "" : v).trim();
  if (!s) return "—";
  if (s === "0" || s === "0.0" || s === "±0") return "±0";
  return /^[-+−]/.test(s) ? s : "+" + s;
}

// ---------- log (rendering wpisów) ----------

function logMark(kind) {
  if (kind === "ok") return `<span style="color: #9fe0a8;">✓</span> `;
  if (kind === "warn") return `<span style="color: #e0b96a;">!</span> `;
  if (kind === "err") return `<span style="color: #e07a7a;">✗</span> `;
  return "";
}

// Powtórzony wpis nie jest dopisywany drugi raz (patrz WebUI._log) — backend
// podbija licznik, my doklejamy „×N".
const logCount = l => (l.n > 1 ? ` <span style="color: #7e7e85;">×${l.n}</span>` : "");

// Sygnatura logu dla updateVolatile(): sama długość nie wystarczy, bo powtórki
// rosną licznikiem w OSTATNIM wpisie, nie nowym elementem.
function logSig(st) {
  const last = st.log[st.log.length - 1];
  return `${st.log.length}:${last ? last.n : 0}`;
}

function lastLogLine() {
  const log = S.state.log;
  const last = log[log.length - 1];
  if (!last) return `<span style="flex: 1;"></span>`;
  return `${logMark(last.kind)}<span style="flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${last.text}${logCount(last)}</span>`;
}

function logLines() {
  return S.state.log.map(l => `<div>${logMark(l.kind)}${l.t} · ${l.text}${logCount(l)}</div>`).join("");
}
