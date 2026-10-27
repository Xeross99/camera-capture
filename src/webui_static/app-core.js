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
  evTarget: null,    // {n, label} — wartość wyklikana w −/+, jeszcze niewysłana (debounce)
  evPending: null,    // {target, label, since} — wysłana, czeka, aż aparat ODDA nową wartość
                      // (spinner w kontrolce EV; czyści evReconcile w app-session.js)
  updateDismissed: "",// wersja, dla której operator kliknął „Później"
  checkStartedAt: 0,  // klik w „Sprawdź aktualizacje" — minimalny czas spinnera
  refreshStartedAt: 0,// klik w „Odśwież listę" — minimalny czas spinnera
  dayFocus: "",       // podświetlony dzień na osi ekranu startowego
  sessionFilter: "",  // filtr listy sesji na ekranie startowym (nazwa/produkt)
  photosMin: "",      // filtr ilości zdjęć: minimum (puste = brak)
  photosMax: "",      // filtr ilości zdjęć: maksimum (puste = brak)
  dateFilter: "",     // filtr daty: "" / "today" / "7" / "30" (dni wstecz)
  leaveConfirm: false,// modal „wrócić do menu głównego?" (ESC na ekranie Sesji)
  pickIdx: -1,        // zaznaczony kafelek na ekranie startowym (nawigacja
  pickList: null,     // strzałkami/hover, ENTER wchodzi); lista = widoczne sesje
  edit: null,         // edycja logo w podglądzie: {file, logo, pos} — logo "" = bez logo
};
const $ = id => document.getElementById(id);
const post = (payload) => fetch("/api/action", { method: "POST", body: JSON.stringify(payload) });
const mono = "font-family: 'IBM Plex Mono', monospace;";
const sel = `height: 24px; background: var(--input-bg); border: 1px solid var(--line-3); border-radius: 4px; color: var(--fg-0); ${mono} font-size: 11.5px; padding: 0 6px;`;
const inp = `height: 26px; background: var(--input-bg); border: 1px solid var(--line-3); border-radius: 4px; color: var(--fg-0); padding: 0 8px; ${mono} font-size: 11px;`;
const btnGray = `height: 26px; padding: 0 12px; background: linear-gradient(var(--btn-top), var(--btn-bot)); border: 1px solid var(--btn-border); border-radius: 4px; color: var(--fg-0); font-size: 12px; font-family: inherit;`;
const btnBlue = `background: linear-gradient(#4a8cff, #2f72e8); border: 1px solid #2a63c9; color: #fff; font-family: inherit;`;
const chk = `accent-color: ${ACCENT}; width: 14px; height: 14px;`;
const label = `display: flex; align-items: center; gap: 8px; color: var(--fg-1);`;
const head = `font-size: 11px; font-weight: 600; color: var(--fg-4); letter-spacing: .06em; text-transform: uppercase;`;

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

// Ikony nowego UI — Heroicons outline (24 × 24, stroke). Kolor z currentColor,
// rozmiar z CSS rodzica (.icon-btn svg) albo z `px`.
const ICON_PATHS = {
  camera: '<path d="M6.827 6.175A2.31 2.31 0 0 1 5.186 7.23c-.38.054-.757.112-1.134.175C2.999 7.58 2.25 8.507 2.25 9.574V18a2.25 2.25 0 0 0 2.25 2.25h15A2.25 2.25 0 0 0 21.75 18V9.574c0-1.067-.75-1.994-1.802-2.169a47.865 47.865 0 0 0-1.134-.175 2.31 2.31 0 0 1-1.64-1.055l-.822-1.316a2.192 2.192 0 0 0-1.736-1.039 48.774 48.774 0 0 0-5.232 0 2.192 2.192 0 0 0-1.736 1.039l-.821 1.316Z"/><path d="M16.5 12.75a4.5 4.5 0 1 1-9 0 4.5 4.5 0 0 1 9 0Z"/>',
  sliders: '<path d="M10.5 6h9.75M10.5 6a1.5 1.5 0 1 1-3 0m3 0a1.5 1.5 0 1 0-3 0M3.75 6H7.5m3 12h9.75m-9.75 0a1.5 1.5 0 0 1-3 0m3 0a1.5 1.5 0 0 0-3 0m-3.75 0H7.5m9-6h3.75m-3.75 0a1.5 1.5 0 0 1-3 0m3 0a1.5 1.5 0 0 0-3 0m-9.75 0h9.75"/>',
  moon: '<path d="M21.752 15.002A9.72 9.72 0 0 1 18 15.75c-5.385 0-9.75-4.365-9.75-9.75 0-1.33.266-2.597.748-3.752A9.753 9.753 0 0 0 3 11.25C3 16.635 7.365 21 12.75 21a9.753 9.753 0 0 0 9.002-5.998Z"/>',
  sun: '<path d="M12 3v2.25m6.364.386-1.591 1.591M21 12h-2.25m-.386 6.364-1.591-1.591M12 18.75V21m-4.773-4.227-1.591 1.591M5.25 12H3m4.227-4.773L5.636 5.636M15.75 12a3.75 3.75 0 1 1-7.5 0 3.75 3.75 0 0 1 7.5 0Z"/>',
  search: '<path d="m21 21-5.197-5.197m0 0A7.5 7.5 0 1 0 5.196 5.196a7.5 7.5 0 0 0 10.607 10.607Z"/>',
  refresh: '<path d="M16.023 9.348h4.992v-.001M2.985 19.644v-4.992m0 0h4.992m-4.993 0 3.181 3.183a8.25 8.25 0 0 0 13.803-3.7M4.031 9.865a8.25 8.25 0 0 1 13.803-3.7l3.181 3.182m0-4.991v4.99"/>',
  arrowLeft: '<path d="M10.5 19.5 3 12m0 0 7.5-7.5M3 12h18"/>',
  chevL: '<path d="M15.75 19.5 8.25 12l7.5-7.5"/>',
  chevR: '<path d="m8.25 4.5 7.5 7.5-7.5 7.5"/>',
  trash: '<path d="m14.74 9-.346 9m-4.788 0L9.26 9m9.968-3.21c.342.052.682.107 1.022.166m-1.022-.165L18.16 19.673a2.25 2.25 0 0 1-2.244 2.077H8.084a2.25 2.25 0 0 1-2.244-2.077L4.772 5.79m14.456 0a48.108 48.108 0 0 0-3.478-.397m-12 .562c.34-.059.68-.114 1.022-.165m0 0a48.11 48.11 0 0 1 3.478-.397m7.5 0v-.916c0-1.18-.91-2.164-2.09-2.201a51.964 51.964 0 0 0-3.32 0c-1.18.037-2.09 1.022-2.09 2.201v.916m7.5 0a48.667 48.667 0 0 0-7.5 0"/>',
  check: '<path d="m4.5 12.75 6 6 9-13.5"/>',
  download: '<path d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5M16.5 12 12 16.5m0 0L7.5 12m4.5 4.5V3"/>',
  cloud: '<path d="M12 16.5V9.75m0 0 3 3m-3-3-3 3M6.75 19.5a4.5 4.5 0 0 1-1.41-8.775 5.25 5.25 0 0 1 10.233-2.33 3 3 0 0 1 3.758 3.848A3.752 3.752 0 0 1 18 19.5H6.75Z"/>',
  folder: '<path d="M2.25 12.75V12A2.25 2.25 0 0 1 4.5 9.75h15A2.25 2.25 0 0 1 21.75 12v.75m-8.69-6.44-2.12-2.12a1.5 1.5 0 0 0-1.061-.44H4.5A2.25 2.25 0 0 0 2.25 6v12a2.25 2.25 0 0 0 2.25 2.25h15A2.25 2.25 0 0 0 21.75 18V9a2.25 2.25 0 0 0-2.25-2.25h-5.379a1.5 1.5 0 0 1-1.06-.44Z"/>',
  sparkles: '<path d="M9.813 15.904 9 18.75l-.813-2.846a4.5 4.5 0 0 0-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 0 0 3.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 0 0 3.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 0 0-3.09 3.09ZM18.259 8.715 18 9.75l-.259-1.035a3.375 3.375 0 0 0-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 0 0 2.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 0 0 2.456 2.456L21.75 6l-1.035.259a3.375 3.375 0 0 0-2.456 2.456ZM16.894 20.567 16.5 21.75l-.394-1.183a2.25 2.25 0 0 0-1.423-1.423L13.5 18.75l1.183-.394a2.25 2.25 0 0 0 1.423-1.423l.394-1.183.394 1.183a2.25 2.25 0 0 0 1.423 1.423l1.183.394-1.183.394a2.25 2.25 0 0 0-1.423 1.423Z"/>',
  terminal: '<path d="M6.75 7.5l3 2.25-3 2.25m4.5 0h3m-9 8.25h13.5A2.25 2.25 0 0 0 21 18V6a2.25 2.25 0 0 0-2.25-2.25H5.25A2.25 2.25 0 0 0 3 6v12a2.25 2.25 0 0 0 2.25 2.25Z"/>',
  lock: '<path d="M16.5 10.5V6.75a4.5 4.5 0 1 0-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 0 0 2.25-2.25v-6.75a2.25 2.25 0 0 0-2.25-2.25H6.75a2.25 2.25 0 0 0-2.25 2.25v6.75a2.25 2.25 0 0 0 2.25 2.25Z"/>',
  external: '<path d="M13.5 6H5.25A2.25 2.25 0 0 0 3 8.25v10.5A2.25 2.25 0 0 0 5.25 21h10.5A2.25 2.25 0 0 0 18 18.75V10.5m-10.5 6L21 3m0 0h-5.25M21 3v5.25"/>',
  leave: '<path d="M15.75 9V5.25A2.25 2.25 0 0 0 13.5 3h-6a2.25 2.25 0 0 0-2.25 2.25v13.5A2.25 2.25 0 0 0 7.5 21h6a2.25 2.25 0 0 0 2.25-2.25V15m-3 0-3-3m0 0 3-3m-3 3H21"/>',
  cameraOff: '<path d="m15.75 10.5 4.72-4.72a.75.75 0 0 1 1.28.53v11.38a.75.75 0 0 1-1.28.53l-4.72-4.72M12 18.75H4.5a2.25 2.25 0 0 1-2.25-2.25V9m12.841 9.091L16.5 19.5m-1.409-1.409c.407-.407.659-.97.659-1.591v-9a2.25 2.25 0 0 0-2.25-2.25h-9c-.621 0-1.184.252-1.591.659m12.182 12.182L2.909 5.909M1.5 4.5l1.409 1.409"/>',
  eyeSlash: '<path d="M3.98 8.223A10.477 10.477 0 0 0 1.934 12C3.226 16.338 7.244 19.5 12 19.5c.993 0 1.953-.138 2.863-.395M6.228 6.228A10.451 10.451 0 0 1 12 4.5c4.756 0 8.773 3.162 10.065 7.498a10.522 10.522 0 0 1-4.293 5.774M6.228 6.228 3 3m3.228 3.228 3.65 3.65m7.894 7.894L21 21m-3.228-3.228-3.65-3.65m0 0a3 3 0 1 0-4.243-4.243m4.242 4.242L9.88 9.88"/>',
  puzzle: '<path d="M14.25 6.087c0-.355.186-.676.401-.959.221-.29.349-.634.349-1.003 0-1.036-1.007-1.875-2.25-1.875s-2.25.84-2.25 1.875c0 .369.128.713.349 1.003.215.283.401.604.401.959v0a.64.64 0 0 1-.657.643 48.39 48.39 0 0 1-4.163-.3c.186 1.613.293 3.25.315 4.907a.656.656 0 0 1-.658.663v0c-.355 0-.676-.186-.959-.401a1.647 1.647 0 0 0-1.003-.349c-1.036 0-1.875 1.007-1.875 2.25s.84 2.25 1.875 2.25c.369 0 .713-.128 1.003-.349.283-.215.604-.401.959-.401v0c.31 0 .555.26.532.57a48.039 48.039 0 0 1-.642 5.056c1.518.19 3.058.309 4.616.354a.64.64 0 0 0 .657-.643v0c0-.355-.186-.676-.401-.959a1.647 1.647 0 0 1-.349-1.003c0-1.035 1.008-1.875 2.25-1.875 1.243 0 2.25.84 2.25 1.875 0 .369-.128.713-.349 1.003-.215.283-.4.604-.4.959v0c0 .333.277.599.61.58a48.1 48.1 0 0 0 5.427-.63 48.05 48.05 0 0 0 .582-4.717.532.532 0 0 0-.533-.57v0c-.355 0-.676.186-.959.401-.29.221-.634.349-1.003.349-1.035 0-1.875-1.007-1.875-2.25s.84-2.25 1.875-2.25c.37 0 .713.128 1.003.349.283.215.604.401.96.401v0a.656.656 0 0 0 .658-.663 48.422 48.422 0 0 0-.37-5.36c-1.886.342-3.81.574-5.766.689a.578.578 0 0 1-.61-.58v0Z"/>',
  pencil: '<path d="m16.862 4.487 1.687-1.688a1.875 1.875 0 1 1 2.652 2.652L10.582 16.07a4.5 4.5 0 0 1-1.897 1.13L6 18l.8-2.685a4.5 4.5 0 0 1 1.13-1.897l8.932-8.931Zm0 0L19.5 7.125M18 14v4.75A2.25 2.25 0 0 1 15.75 21H5.25A2.25 2.25 0 0 1 3 18.75V8.25A2.25 2.25 0 0 1 5.25 6H10"/>',
};
const icon = (name, px = 16, sw = 1.7) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="${sw}" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" style="width: ${px}px; height: ${px}px; flex-shrink: 0; display: block;">${ICON_PATHS[name]}</svg>`;

// Znak GitHuba (Octicons mark-github) — przy aktualizacjach z GitHub Releases.
const GITHUB_MARK = `<svg viewBox="0 0 16 16" fill="currentColor" role="img" aria-label="GitHub" style="width: 24px; height: 24px; display: block;"><path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z"/></svg>`;

// Przelacznik (role=switch). Klik przestawia go od razu w DOM, a backend
// potwierdza przy nastepnym pollu — bez tego odpowiedz na klik czekalaby 500 ms.
// Klawisz-modyfikator w napisach skrótów: macOS ma ⌘, Windows (WebView2) Ctrl.
// Obsługa klawiatury w app-main.js łapie metaKey I ctrlKey, więc różnią się
// tylko napisy.
const IS_MAC = /mac/i.test(navigator.platform || "");
const modKey = k => IS_MAC ? `⌘${k}` : `Ctrl+${k}`;

// Klawisz w podpowiedziach: wszystkie w jednakowej ramce i wielkości (strzałki
// systemowym fontem — w Plex Mono wychodziły malutkie).
const kHint = k => `<span class="hint-key${/^[←→↑↓ ]+$/.test(k) ? " arrows" : ""}">${k}</span>`;

const switchHtml = (on, action, labelText, id = "") =>
  `<button type="button" class="switch" role="switch" ${id ? `id="${id}"` : ""} aria-checked="${on ? "true" : "false"}" aria-label="${labelText}" onclick="flipSwitch(this); ${action}"></button>`;
function flipSwitch(el) {
  el.setAttribute("aria-checked", el.getAttribute("aria-checked") === "true" ? "false" : "true");
}
const switchOn = el => el.getAttribute("aria-checked") === "true";



// ---------- kompensacja ekspozycji (liczby, nie tekst) ----------

// Kompensacja ekspozycji. Backendy mówią różnymi słowami: „+2 2/3" (EDSDK),
// „+3.0", „0.3" — a bywa, że odczyt bieżącej
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
  if (kind === "ok") return `<span style="color: var(--ok);">✓</span> `;
  if (kind === "warn") return `<span style="color: var(--warn);">!</span> `;
  if (kind === "err") return `<span style="color: var(--err);">✗</span> `;
  return "";
}

// Powtórzony wpis nie jest dopisywany drugi raz (patrz WebUI._log) — backend
// podbija licznik, my doklejamy „×N".
const logCount = l => (l.n > 1 ? ` <span style="color: var(--fg-4);">×${l.n}</span>` : "");

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
