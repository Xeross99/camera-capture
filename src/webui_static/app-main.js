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
    <div style="margin-left: auto; display: flex; align-items: center; gap: 16px; font-size: 11.5px; color: #9d9da3;">
      <div style="display: flex; align-items: center; gap: 7px;">
        <span style="display: flex; color: ${conn ? "#34c759" : "#e05a5a"};">${CAM_ICON}</span><span id="conn-label">${conn ? `Aparat połączony · ${st.fps} fps` : "Aparat rozłączony"}</span>
      </div>
      ${st && st.robot && st.robot.enabled ? `
      <div style="display: flex; align-items: center; gap: 7px;">
        <span id="robot-dot" style="display: flex; color: ${st.robot.connected ? "#34c759" : "#e05a5a"};">${ROBOT_ICON}</span><span id="robot-conn-label">${st.robot.connected ? "Robot połączony" : "Robot rozłączony"}</span>
      </div>` : ""}
    </div>
  </div>

  <div id="screen-sesja" style="flex: 1; display: ${S.screen === "sesja" ? "flex" : "none"}; min-height: 0;"></div>
  <div id="screen-ustawienia" style="flex: 1; display: ${S.screen === "ustawienia" ? "grid" : "none"}; overflow: auto; background: #1d1d20; padding: 24px 28px; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 24px; align-content: start;"></div>
</div>`;
}

// ---------- rendering ----------

let lastShellKey = "", lastSesja = "", lastUstawienia = "", lastStrip = "";

// W trybie przeglądania (overlay) zdjęcia NIE są częścią klucza: świeży strzał
// dołączający do listy (processing → shots) przebudowywałby ekran i odtwarzał
// overlay — mignięcie + powtórka animacji wejścia dokładnie w chwili, gdy
// zdjęcie „się dodaje". Pasek w overlayu aktualizuje wtedy refreshStrips()
// z pollu (renderScreens), bez dotykania reszty DOM.
const sesjaKey = st => JSON.stringify([st.session.name, st.session.dir,
  ...(S.reviewMode ? [] : [st.shots, st.processing, st.downloading]),
  st.post, st.previewOn, S.selShot, S.logOpen, S.grid, S.reviewMode]);

const stripSig = st => JSON.stringify([st.shots, st.processing, st.downloading]);

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
  // status robota w pasku zakładek — łatany po id jak aparat, bo połączenie
  // ramienia zmienia się bez rebuildu shella (nie siedzi w jego kluczu)
  const rl = $("robot-conn-label");
  if (rl) {
    const rc = !!(st.robot && st.robot.connected);
    rl.textContent = rc ? "Robot połączony" : "Robot rozłączony";
    const rd = $("robot-dot");
    if (rd) rd.style.color = rc ? "#34c759" : "#e05a5a";
  }
  const hist = $("hist-badge");
  if (hist) {
    hist.textContent = histLabel(st);
    hist.style.color = histColor(st);
    hist.title = histTitle(st);
  }
  // EV jest ŚWIADOMIE łatane, nie keyowane: rebuild ekranu niszczy <img>
  // streamu MJPEG, a kompensacja zmienia się też z pokrętła na aparacie.
  // Cała łatka (w tym spinner oczekiwania na potwierdzenie z aparatu)
  // siedzi w evReconcile() w app-session.js.
  evReconcile(st);
  const sl = $("shoot-label");
  if (sl && performance.now() - shootErrAt > 4000) {
    sl.textContent = st.busy || (st.robot && st.robot.busy ? "Ramię w ruchu…" : "Zrób zdjęcie");
  }
  // Spinner obok tekstu fazy — widoczny zawsze, gdy przycisk nie strzeli od
  // reki (takze podczas komunikatu bledu po odmowie: busy jest wtedy false,
  // wiec znika i nie sugeruje trwajacej pracy).
  const ss = $("shoot-spin");
  if (ss) ss.style.display = shootBusy(st) ? "inline-block" : "none";
  // Overlay rozgrzewki silnika czyszczenia tła — łatany po id (rebuild zabiłby
  // <img> streamu), znika sam, gdy backend zgłosi warmup: null.
  const wo = $("warmup-overlay");
  if (wo) {
    wo.style.display = st.warmup != null ? "flex" : "none";
    const ws = $("warmup-s");
    if (ws && st.warmup != null) ws.textContent = st.warmup;
  }
  // Panel robota też jest ŚWIADOMIE łatany, nie keyowany — stan ramienia
  // zmienia się co poll (busy/rozłączenie), a rebuild ekranu zabiłby <img>
  // streamu MJPEG przy każdym przejeździe.
  robotReconcile();
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
  updateVolatile(st);

  if (S.screen === "sesja" && !st.session.name) {
    const key = JSON.stringify(["start", st.automat, S.pendingNew, S.dayFocus,
                                S.sessionFilter]);
    if (force || key !== lastSesja) {
      // fokus i wartosc przezywaja rebuild w OBU polach ekranu startowego
      // (nazwa nowej sesji, filtr listy) — filtr rebuilduje na kazda litere
      const el = document.activeElement;
      const editId = el && (el.id === "new-session-input" || el.id === "session-filter")
        ? el.id : null;
      const keep = editId ? el.value : null;
      // fokus na polu nazwy tylko przy WEJŚCIU na ekran startowy (start
      // aplikacji, powrót z sesji/Ustawień — lastSesja jest wtedy zerowane);
      // kolejne rebuildy (dolatujące okładki) nie mają kraść fokusa
      const entering = !(typeof lastSesja === "string" && lastSesja.startsWith('["start"'));
      // okładki dolatują po kolei, każda = rebuild — bez tego lista skakałaby
      // na górę operatorowi w trakcie przeglądania
      const scroll = $("start-scroll") ? $("start-scroll").scrollTop : 0;
      lastSesja = key;
      $("screen-sesja").innerHTML = startScreen();
      if ($("start-scroll")) $("start-scroll").scrollTop = scroll;
      if (keep !== null) {
        const i = $(editId);
        if (i) {
          i.value = keep;
          // preventScroll: pole nazwy jest auto-fokusowane przy wejsciu i
          // fokus na nim ZOSTAJE, wiec kazdy rebuild (dolatujaca okladka)
          // odtwarzal fokus, a gole focus() dowozi element do widoku —
          // przewinieta lista wracala na gore mimo odtworzenia scrollTop
          i.focus({ preventScroll: true });
          i.setSelectionRange(keep.length, keep.length);
        }
      } else if (entering) {
        const i = $("new-session-input");
        if (i) i.focus({ preventScroll: true });
      }
    }
  } else if (S.screen === "sesja") {
    const key = sesjaKey(st);
    if (!(force || key !== lastSesja)) {
      // bez rebuildu, ale w przeglądzie pasek zdjęć ma nadążać za stanem
      // (świeży strzał, skeleton obróbki) — łatka zamiast przebudowy
      if (S.reviewMode && stripSig(st) !== lastStrip) {
        lastStrip = stripSig(st);
        refreshStrips();
      }
      return;
    }
    {
      lastSesja = key;
      lastStrip = stripSig(st);
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
  // filtr listy nie ma przezywac wejscia do sesji — po powrocie operator ma
  // widziec pelna liste, a nie ogryzek po starym wyszukiwaniu
  S.sessionFilter = "";
  S.pickIdx = -1;
  post({ action: "clear_session" });
}

function shoot() {
  if (!S.state.connected || !S.state.session.name) return;
  // migawka w trakcie przejazdu ramienia = rozmycie; backend i tak odmówi,
  // ale bez tego mignąłby jeszcze biały flash sugerujący zrobione zdjęcie
  if (S.state.robot && S.state.robot.busy) return;
  flashNow();
  // Odpowiedź MUSI być obejrzana. Sam flash jest lokalny, więc odmowa backendu
  // („trwa aktualizacja", „ramię w ruchu") wyglądała identycznie jak zdjęcie
  // zrobione poprawnie: błysk i nic więcej. Powód ląduje na przycisku, bo tam
  // patrzy operator po naciśnięciu ENTER.
  post({ action: "shoot" }).then(r => r.json()).then(res => {
    if (res && res.ok === false) shootError(res.error);
  }).catch(e => shootError("brak odpowiedzi aplikacji"));
}

// Napis wraca sam: `updateVolatile()` przepisuje etykietę przy każdym pollu
// (500 ms), więc trzymamy błąd chwilę dłużej, żeby dało się go przeczytać.
let shootErrAt = 0;
function shootError(text) {
  const el = $("shoot-label");
  if (!el) return;
  el.textContent = "✗ " + text;
  shootErrAt = performance.now();
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
    // pole filtra: ↑/↓ przesuwaja zaznaczenie kafelka bez wychodzenia
    // z inputa (←/→ zostaja dla kursora w tekscie), ENTER wchodzi w sesje
    if (document.activeElement.id === "session-filter") {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        movePick(e.key === "ArrowDown" ? 1 : -1);
      } else if (e.key === "Enter") {
        openPicked();
      }
    }
    return;
  }
  // Skróty robota (⌘1/⌘2 ujęcie) — tylko na ekranie Sesji z otwartą sesją,
  // czyli tam, gdzie panel jest widoczny. Skróty odległości (⌘−/⌘=) i kąta
  // kamery (⌘[/⌘]) usunięte razem z tymi suwakami: każda regulacja psuła
  // ustawione ujęcie (patrz komentarz w app-robot.js).
  if ((e.metaKey || e.ctrlKey) && S.screen === "sesja" && S.state.session.name) {
    const robotKey = {
      "1": () => robotPose("top90"), "2": () => robotPose("a45"),
    }[e.key];
    if (robotKey) { e.preventDefault(); robotKey(); return; }
  }
  if (e.metaKey || e.ctrlKey) return;

  // preventDefault na wszystkim co obslugujemy — bez tego WKWebView puszcza
  // klawisz w gore responder chain i macOS robi systemowy beep
  if (["Enter", " ", "Escape", "Backspace", "ArrowLeft", "ArrowRight",
       "p", "P", "a", "A", "x", "X"].includes(e.key)) {
    e.preventDefault();
  }
  // przy otwartym potwierdzeniu wyjscia reaguja TYLKO ESC (anuluj)
  // i ENTER (potwierdz) — reszta klawiszy nie ma strzelac zza modala
  if (S.leaveConfirm && !["Escape", "Enter"].includes(e.key)) return;
  // ekran startowy bez fokusa w polu: strzalki chodza po kafelkach sesji,
  // ENTER wchodzi w zaznaczona — skroty sesyjne (shoot itd.) nie dotycza
  // tego widoku
  if (S.screen === "sesja" && S.state && !S.state.session.name && !S.leaveConfirm) {
    if (["ArrowLeft", "ArrowUp"].includes(e.key)) { e.preventDefault(); movePick(-1); }
    else if (["ArrowRight", "ArrowDown"].includes(e.key)) { e.preventDefault(); movePick(1); }
    else if (e.key === "Enter") { e.preventDefault(); openPicked(); }
    return;
  }
  switch (e.key) {
    case "Enter":
      if (S.leaveConfirm) confirmLeave();
      else shoot();
      break;
    case " ": toggleReview(); break;
    case "Escape":
      if (S.leaveConfirm) hideLeaveConfirm();
      else if (S.reviewMode) closeReview();
      else if (S.screen === "sesja" && S.state && S.state.session.name) showLeaveConfirm();
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
