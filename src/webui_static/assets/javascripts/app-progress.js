"use strict";
// Kafelek postępu zdjęcia w pasku zdjęć: „Obróbka 62%", pasek, kropki etapów
// i nazwa bieżącego etapu (z aparatu → wycinanie → … → zapis).
//
// Backend (src/progress.py) podaje etapy z szacowanym czasem, numer bieżącego
// i ile już trwa. Procent liczony jest tu co klatkę (requestAnimationFrame),
// więc pasek rośnie płynnie między pollami stanu (co 500 ms), a nie skokami.
// Kafelek łatany jest w miejscu po data-proc — przebudowa paska zdjęć przy
// każdej klatce zrywałaby animacje i miniatury.

Object.assign(I18N_EN, {
  "Obróbka": "Processing",
  "Z aparatu": "From camera",
  "W kolejce": "Queued",
  "Zapowiedź": "Announcing",
  "Wycinanie": "Cutting out",
  "Maska i cienie": "Mask and shadows",
  "Kadrowanie": "Framing",
  "Białe tło": "White background",
  "Zapis": "Saving",
});

const procLabel = key => ({
  camera: t("Z aparatu"),
  queue: t("W kolejce"),
  announce: t("Zapowiedź"),
  rembg: t("Wycinanie"),
  mask: t("Maska i cienie"),
  crop: t("Kadrowanie"),
  compose: t("Białe tło"),
  logo: "Logo",
  save: t("Zapis"),
}[key] || key);

S.procShown = {};   // plik -> pokazany procent (rośnie, nigdy nie cofa)

// Docelowy procent w chwili `now`. W bieżącym etapie pasek zbliża się do jego
// końca coraz wolniej (1 − e^−x): etap dłuższy niż zwykle nie zatrzymuje
// paska w miejscu, a krótszy po prostu przeskakuje dalej przy następnym etapie.
function procTarget(p, now) {
  const est = p.stages.map(s => s[1]);
  const total = est.reduce((a, b) => a + b, 0) || 1;
  const before = est.slice(0, p.index).reduce((a, b) => a + b, 0);
  const cur = est[p.index] || 0;
  const ago = (p.agoMs + Math.max(0, now - (S.procRecv || now))) / 1000;
  const inStage = cur ? cur * (1 - Math.exp(-1.6 * ago / cur)) : 0;
  return Math.min(99, 100 * (before + inStage) / total);
}

const procPips = p => p.stages
  .map(([key], i) => key === "queue" ? "" : `<span class="proc-pip${i < p.index ? " done" : i === p.index ? " on" : ""}"></span>`)
  .join("");

function procTileHtml(p) {
  const first = S.procShown[p.file] == null;
  const pct = first ? 0 : S.procShown[p.file];
  const key = p.stages[p.index][0];
  return `
    <div class="shot-wait proc${first ? " proc-new" : ""}" data-proc="${escapeHtml(p.file)}" title="${escapeHtml(p.file)}">
      <div class="proc-head">${t("Obróbka")} <span class="proc-pct">${Math.floor(pct)}%</span></div>
      <div class="proc-bar"><span class="proc-fill" style="transform: scaleX(${pct / 100});"></span></div>
      <div class="proc-pips">${procPips(p)}</div>
      <div class="proc-stage" data-stage="${key}"><span class="proc-label">${procLabel(key)}</span></div>
    </div>`;
}

// Zmiana etapu: stara nazwa wyjeżdża do góry, nowa wjeżdża od dołu, kropka
// etapu przesuwa się dalej, a pasek krótko się rozjaśnia.
function procSwapStage(tile, p) {
  const box = tile.querySelector(".proc-stage");
  const key = p.stages[p.index][0];
  if (!box || box.dataset.stage === key) return;
  box.dataset.stage = key;
  box.querySelectorAll(".proc-label:not(.out)").forEach(old => {
    old.classList.remove("in");
    old.classList.add("out");
    setTimeout(() => old.remove(), 320);
  });
  const label = document.createElement("span");
  label.className = "proc-label in";
  label.textContent = procLabel(key);
  box.appendChild(label);
  const pips = tile.querySelector(".proc-pips");
  if (pips) pips.innerHTML = procPips(p);
  const fill = tile.querySelector(".proc-fill");
  if (fill) {
    fill.classList.remove("bump");
    void fill.offsetWidth;   // restart animacji przy szybkich zmianach etapów
    fill.classList.add("bump");
  }
}

let procLast = 0;
function procFrame(now) {
  const dt = procLast ? Math.min(0.1, (now - procLast) / 1000) : 0;
  procLast = now;
  const list = (S.state && S.state.progress) || [];
  const live = new Set();
  list.forEach(p => {
    live.add(p.file);
    const tiles = document.querySelectorAll(`[data-proc="${CSS.escape(p.file)}"]`);
    if (!tiles.length) return;
    const shown = S.procShown[p.file] || 0;
    const target = Math.max(shown, procTarget(p, now));
    // dojazd do celu z wygładzeniem — skok po szybkim etapie też jest płynny
    const next = shown + (target - shown) * Math.min(1, dt * 7);
    S.procShown[p.file] = next;
    tiles.forEach(tile => {
      tile.classList.remove("proc-new");
      const fill = tile.querySelector(".proc-fill");
      if (fill) fill.style.transform = `scaleX(${next / 100})`;
      const pct = tile.querySelector(".proc-pct");
      const txt = `${Math.floor(next)}%`;
      if (pct && pct.textContent !== txt) pct.textContent = txt;
      procSwapStage(tile, p);
    });
  });
  Object.keys(S.procShown).forEach(f => { if (!live.has(f)) delete S.procShown[f]; });
  requestAnimationFrame(procFrame);
}
requestAnimationFrame(procFrame);
