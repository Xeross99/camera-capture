"use strict";
// Shell aplikacji, render keyowany (anti-flicker), klawiatura i petla stanu.
// MUSI byc ladowany OSTATNI: tick() na dole rusza od razu.

// Baner aktualizacji nad zakladkami. Widoczny dopiero gdy backend znajdzie
// nowszy release; „Później" chowa go do konca uruchomienia (per wersja).
function updateBanner() {
  const u = S.state && S.state.update;
  if (!u || !u.available || S.updateDismissed === u.available) return "";
  const right = u.canApply
    ? `<button onclick="applyUpdate()" ${u.busy ? "disabled" : ""} style="height: 24px; padding: 0 12px; ${btnBlue} border-radius: 4px; font-size: 11.5px; font-weight: 600; display: inline-flex; align-items: center; gap: 7px; ${u.busy ? "opacity: .6;" : ""}">${u.busy ? `<span class="spinner"></span>Aktualizuję…` : "Zaktualizuj i uruchom ponownie"}</button>
       <button onclick="S.updateDismissed = '${u.available}'; renderShell(true)" style="${btnGray} height: 24px; padding: 0 10px; font-size: 11.5px; opacity: .75;">Później</button>`
    : `<span style="${mono} font-size: 11px; color: #d8c39a;">uruchomienie ze źródeł — zaktualizuj przez <b>git pull</b></span>
       <button onclick="S.updateDismissed = '${u.available}'; renderShell(true)" style="${btnGray} height: 24px; padding: 0 10px; font-size: 11.5px; opacity: .75;">Ukryj</button>`;
  return `
  <div style="flex: 0 0 auto; background: #2e2921; border-bottom: 1px solid #4d4126; display: flex; align-items: center; gap: 12px; padding: 7px 14px;">
    <span style="font-size: 12.5px; color: #f0e2c2;">Dostępna aktualizacja <b>${u.available}</b> <span style="${mono} font-size: 11px; color: #b9a888;">(masz ${u.current})</span></span>
    <span id="update-progress" style="${mono} font-size: 11px; color: #b9a888;">${u.busy && u.progress ? u.progress + "%" : ""}</span>
    <span style="margin-left: auto; display: flex; align-items: center; gap: 8px;">${right}</span>
  </div>`;
}

function shell() {
  const st = S.state;
  const conn = st && st.connected;
  const tab = k => S.screen === k ? "#f2f2f5" : "#9d9da3";
  const bar = k => S.screen === k ? ACCENT : "transparent";
  return `
<div style="width: 100%; height: 100%; background: #232326; overflow: hidden; display: flex; flex-direction: column; font-family: -apple-system, 'Helvetica Neue', Helvetica, sans-serif; color: #e8e8ea; font-size: 13px;">
  ${updateBanner()}

  <div style="height: 34px; flex: 0 0 34px; background: #2a2a2d; border-bottom: 1px solid #17171a; display: flex; align-items: stretch; padding: 0 10px; gap: 2px;">
    <div onclick="go('sesja')" style="display: flex; align-items: center; padding: 0 18px; font-size: 12.5px; font-weight: 500; cursor: default; color: ${tab("sesja")}; border-bottom: 2px solid ${bar("sesja")};">Sesja</div>
    <div onclick="go('ustawienia')" style="display: flex; align-items: center; padding: 0 18px; font-size: 12.5px; font-weight: 500; cursor: default; color: ${tab("ustawienia")}; border-bottom: 2px solid ${bar("ustawienia")};">Ustawienia</div>
    <div style="margin-left: auto; display: flex; align-items: center; gap: 14px; ${mono} font-size: 11px; color: #7e7e85;">
      <div>sesja: <span style="color: #c9c9cf;" id="stat-name">—</span></div>
      <div>zdjęć: <span style="color: #c9c9cf;" id="stat-count">0</span></div>
      <div style="display: flex; align-items: center; gap: 7px; font-family: -apple-system, 'Helvetica Neue', Helvetica, sans-serif; font-size: 11.5px; color: #9d9da3;">
        <div style="width: 7px; height: 7px; border-radius: 50%; background: ${conn ? "#34c759" : "#e05a5a"};"></div><span id="conn-label">${conn ? `Aparat połączony · ${st.fps} fps` : "Aparat rozłączony"}</span>
      </div>
    </div>
  </div>

  <div id="screen-sesja" style="flex: 1; display: ${S.screen === "sesja" ? "flex" : "none"}; min-height: 0;"></div>
  <div id="screen-ustawienia" style="flex: 1; display: ${S.screen === "ustawienia" ? "grid" : "none"}; overflow: auto; background: #1d1d20; padding: 24px 28px; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 24px; align-content: start;"></div>
</div>`;
}

// ---------- rendering ----------

let lastShellKey = "", lastSesja = "", lastUstawienia = "";

const sesjaKey = st => JSON.stringify([st.session.name, st.session.dir, st.shots,
  st.processing, st.downloading, st.post, st.previewOn, S.selShot, S.logOpen,
  S.grid, S.reviewMode]);

function renderShell(force) {
  const st = S.state;
  const u = st.update || {};
  // progress pobierania NIE jest w kluczu — łata go updateVolatile(), bo
  // rebuild shella niszczy <img> streamu (miganie przy każdym procencie)
  const key = JSON.stringify([S.screen, st.connected,
    u.available, u.busy, u.canApply, S.updateDismissed]);
  if (force || key !== lastShellKey) {
    lastShellKey = key;
    $("app").innerHTML = shell();
    lastSesja = lastUstawienia = "";
    renderScreens(true);
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
  const hist = $("hist-badge");
  if (hist) {
    hist.textContent = histLabel(st);
    hist.style.color = histColor(st);
    hist.title = histTitle(st);
  }
  // EV jest ŚWIADOMIE łatane, nie keyowane: rebuild ekranu niszczy <img>
  // streamu MJPEG, a kompensacja zmienia się też z pokrętła na aparacie
  const evVal = $("ev-value");
  if (evVal) {
    const ev = st.camera && st.camera.ev;
    evVal.textContent = ev ? evLabel(ev.current) : "—";
    const hint = $("ev-hint");
    if (hint) hint.textContent = evHint(st);
    ["ev-minus", "ev-plus"].forEach(id => {
      const b = $(id);
      if (b) b.style.opacity = ev ? 1 : .35;
    });
  }
  const sl = $("shoot-label");
  if (sl) sl.textContent = st.busy || "Zrób zdjęcie";
  const up = $("update-progress");
  if (up) {
    const u = st.update || {};
    up.textContent = u.busy && u.progress ? `${u.progress}%` : "";
  }
  const sig = logSig(st);
  if (sig !== S.lastLogLen) {
    S.lastLogLen = sig;
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
  updateVolatile(st);

  if (S.screen === "sesja" && !st.session.name) {
    const key = JSON.stringify(["start", st.automat, S.pendingNew, S.dayFocus]);
    if (force || key !== lastSesja) {
      const el = document.activeElement;
      const editing = el && el.id === "new-session-input";
      const keep = editing ? el.value : null;
      // okładki dolatują po kolei, każda = rebuild — bez tego lista skakałaby
      // na górę operatorowi w trakcie przeglądania
      const scroll = $("start-scroll") ? $("start-scroll").scrollTop : 0;
      lastSesja = key;
      $("screen-sesja").innerHTML = startScreen();
      if ($("start-scroll")) $("start-scroll").scrollTop = scroll;
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
      S.lastLogLen = logSig(st);
      $("screen-sesja").innerHTML = sesjaScreen();
      // najnowsze zdjecie na wierzchu; w podgladzie zamiast tego dojezdzamy do
      // zaznaczonego kafelka, zeby bylo widac, ktore zdjecie sie oglada
      ["filmstrip", "review-strip"].forEach(id => {
        const strip = $(id);
        if (!strip) return;
        const tile = S.reviewMode && strip.querySelector(`[data-shot="${S.selShot}"]`);
        if (tile) tile.scrollIntoView({ block: "nearest", inline: "center" });
        else strip.scrollLeft = strip.scrollWidth;
      });
      const lp = $("log-panel");
      if (lp) lp.scrollTop = lp.scrollHeight;
    }
  } else {
    const key = JSON.stringify([st.settings, st.update]);
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

// Wyjscie z sesji = powrot na ekran startowy z lista sesji. Zmiana nazwy idzie
// wlasnie tamtedy (pole "Utworz i otworz"), wiec sidebar nie ma juz inputa.
function leaveSession() {
  S.pendingNew = null;
  post({ action: "clear_session" });
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

function cycleGrid() {
  S.grid = (S.grid + 1) % GRIDS.length;
  renderScreens();
}

function reviewSelected(verdict) {
  const f = S.state.shots[S.selShot];
  if (!f) return;
  post({
    action: "review", verdict,
    session: S.state.session.name,
    file: f.file,
  });
}

// ---------- klawiatura ----------

document.addEventListener("keydown", e => {
  const tag = document.activeElement ? document.activeElement.tagName : "";
  if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") {
    if (e.key === "Enter" && document.activeElement.id === "new-session-input") {
      commitNewSession();
    }
    return;
  }
  if (e.metaKey || e.ctrlKey) return;

  // preventDefault na wszystkim co obslugujemy — bez tego WKWebView puszcza
  // klawisz w gore responder chain i macOS robi systemowy beep
  if (["Enter", " ", "Escape", "Backspace", "ArrowLeft", "ArrowRight",
       "p", "P", "a", "A", "x", "X"].includes(e.key)) {
    e.preventDefault();
  }
  switch (e.key) {
    case "Enter": shoot(); break;
    case " ": toggleReview(); break;
    case "Escape":
      if (S.reviewMode) closeReview();
      break;
    case "Backspace":
      if (S.reviewMode) deleteReviewed();
      break;
    case "p": case "P": toggle("preview", !S.state.previewOn); break;
    case "ArrowLeft": navShot(-1); break;
    case "ArrowRight": navShot(1); break;
    case "a": case "A": reviewSelected("accepted"); break;
    case "x": case "X":
      if (S.selShot >= 0) reviewSelected("rejected");
      else post({ action: "reject_last" });
      break;
  }
});

// ---------- petla stanu ----------

// Log przychodzi PRZYROSTOWO (backend zwraca tylko wpisy z seq > since) —
// pelna lista zyje tutaj. Wpis o id ostatniej linii to podbicie licznika ×N
// (podmiana w miejscu), kazdy inny to nowa linia. Limit 500 jak w backendzie.
let logCache = [];
function mergeLog(tail) {
  for (const e of tail || []) {
    const last = logCache[logCache.length - 1];
    if (last && last.id === e.id) logCache[logCache.length - 1] = e;
    else logCache.push(e);
  }
  if (logCache.length > 500) logCache = logCache.slice(-500);
  return logCache;
}

async function tick() {
  try {
    const r = await fetch(`/api/state?since=${S.logSeq || 0}`);
    const st = await r.json();
    // restart backendu = licznik seq od zera — zaczynamy log od nowa,
    // inaczej nasz stary kursor odsiewałby wszystko w nieskończoność
    if ((st.logSeq || 0) < (S.logSeq || 0)) logCache = [];
    S.logSeq = st.logSeq || 0;
    st.log = mergeLog(st.log);
    S.state = st;
    if (!lastShellKey) renderShell(true);
    else renderShell(false);
  } catch (e) {
    const el = $("conn-label");
    if (el) el.textContent = "brak połączenia z backendem";
  }
  setTimeout(tick, 500);
}
tick();
