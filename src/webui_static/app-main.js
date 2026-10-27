"use strict";
// Shell aplikacji, render keyowany (anti-flicker), klawiatura i petla stanu.
// MUSI byc ladowany OSTATNI: tick() na dole rusza od razu.

// Baner aktualizacji nad zakladkami. Widoczny dopiero gdy backend znajdzie
// nowszy release; „Później" chowa go do konca uruchomienia (per wersja).
// Postęp pobierania (tekst i pasek) łata updateVolatile() po id — rebuild
// shella przy każdym procencie zrywałby stream live view.
function updateBanner() {
  const u = S.state && S.state.update;
  if (!u || !u.available || S.updateDismissed === u.available) return "";
  const hide = `S.updateDismissed = '${u.available}'; renderShell(true)`;
  const right = u.canApply
    ? `<button type="button" class="btn btn-sm" onclick="${hide}" ${u.busy ? "disabled" : ""}>Później</button>
       <button type="button" class="btn btn-primary btn-sm" onclick="applyUpdate()" ${u.busy ? "disabled" : ""}>${u.busy ? `<span class="spinner" style="border-color: rgba(255,255,255,.35); border-top-color: #fff;"></span>Aktualizuję…` : `${icon("download", 14, 2)}Zaktualizuj i uruchom ponownie`}</button>`
    : `<span style="font-size: 12px; color: var(--muted);">Uruchomienie ze źródeł: zaktualizuj przez <b class="mono" style="font-weight: 500; color: var(--text-2);">git pull</b></span>
       <button type="button" class="btn btn-sm" onclick="${hide}">Ukryj</button>`;
  return `
  <div class="update-banner">
    <span class="update-icon">${icon("download", 16, 2)}</span>
    <div style="flex: 1; min-width: 0; display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">
      <span style="font-size: 13px; font-weight: 600; color: var(--text);">Dostępna wersja <span class="mono">${u.available}</span></span>
      <span style="font-size: 12px; color: var(--muted);">masz <span class="mono">${u.current}</span></span>
      <span id="update-progress" class="mono" style="font-size: 12px; color: var(--accent-fg);">${u.busy && u.progress ? u.progress + "%" : ""}</span>
    </div>
    ${right}
    <span class="update-bar" style="display: ${u.busy ? "block" : "none"};"><span id="update-bar-fill" style="width: ${u.busy ? u.progress || 0 : 0}%;"></span></span>
  </div>`;
}

// Status Automatu w pasku: brak tokenu / blad listy sesji / odswiezanie /
// zdjecia sesji czekajace na wysylke / polaczono. Latany po id w updateVolatile.
function automatStatus(st) {
  const a = st.automat || {};
  if (!a.hasToken) return { cls: "", text: "brak tokenu" };
  if (a.error) return { cls: "err", text: "brak połączenia" };
  const waiting = st.session.name ? st.shots.filter(s => !s.uploaded && s.status !== "rejected").length : 0;
  if (waiting) return { cls: "warn", text: `wysyłanie ${plPhotos(waiting)}` };
  if (refreshingNow(st)) return { cls: "warn", text: "odświeżam…" };
  return { cls: "ok", text: "połączono" };
}

function shell() {
  const st = S.state;
  const conn = st && st.connected;
  const tab = k => `seg-btn${S.screen === k ? " on" : ""}`;
  const au = automatStatus(st);
  return `
<div class="ui" style="width: 100%; height: 100%; background: var(--ground); overflow: hidden; display: flex; flex-direction: column; font-size: 13px;">
  ${updateBanner()}

  <header class="topbar">
    <nav class="seg" aria-label="Główne">
      <div id="tab-pill" class="seg-pill"></div>
      <button type="button" id="tab-sesja" class="${tab("sesja")}" onclick="go('sesja')">${icon("camera")}Sesje</button>
      <button type="button" id="tab-ustawienia" class="${tab("ustawienia")}" onclick="go('ustawienia')">${icon("sliders")}Ustawienia</button>
    </nav>
    ${st.session.name ? `
    <nav class="crumbs" aria-label="Ścieżka">
      <a onclick="showLeaveConfirm()">Sesje</a><span aria-hidden="true">/</span>
      <span aria-current="page" style="font-weight: 600; color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${st.session.name}</span>
    </nav>` : ""}
    <div style="flex: 1;"></div>
    <div class="chip"><span class="dot ${conn ? "ok" : "err"}"></span><span id="conn-label">${conn ? "Aparat połączony" : "Aparat rozłączony"}</span>${conn ? `<span id="conn-fps" class="fps">${st.fps} fps</span>` : ""}</div>
    <div class="chip"><span id="automat-dot" class="dot ${au.cls}"></span>API<span id="automat-text" class="sub">${au.text}</span></div>
    <button type="button" id="theme-toggle" class="icon-btn" onclick="toggleTheme()" title="${themeToggleTitle()}" aria-label="${themeToggleTitle()}">${themeToggleIcon()}</button>
  </header>

  <div id="screen-sesja" style="flex: 1; display: ${S.screen === "sesja" ? "flex" : "none"}; min-height: 0;"></div>
  <div id="screen-ustawienia" style="flex: 1; display: ${S.screen === "ustawienia" ? "block" : "none"}; overflow: hidden; min-height: 0; background: var(--ground);"></div>
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
  st.post, st.previewOn, st.edsdkMissing, st.focusSupported, S.selShot, S.logOpen, S.grid, S.reviewMode]);

const stripSig = st => JSON.stringify([st.shots, st.processing, st.downloading]);

function renderShell(force) {
  const st = S.state;
  const u = st.update || {};
  // progress pobierania NIE jest w kluczu — łata go updateVolatile(), bo
  // rebuild shella niszczy <img> streamu (miganie przy każdym procencie)
  // S.screen NIE jest w kluczu: zmiana zakladki przelacza ekrany w miejscu
  // (go()), zeby pasek pod zakladka mogl przejechac, a ekran wejsc animacja
  const key = JSON.stringify([st.connected, st.session.name,
    u.available, u.busy, u.canApply, S.updateDismissed]);
  if (force || key !== lastShellKey) {
    // Wejście w sesję / wyjście z niej przebudowuje cały shell (nazwa sesji
    // jest w górnym pasku), a to zeruje lastSesja — bez zapamiętania widoku
    // sprzed przebudowy przejście lista <-> sesja traciło animację.
    const prevView = lastSesja ? (isStartKey(lastSesja) ? "start" : "sesja") : "";
    lastShellKey = key;
    $("app").innerHTML = shell();
    placeTabBar(false);
    lastSesja = lastUstawienia = "";
    renderScreens(true);
    const nowView = st.session.name ? "sesja" : "start";
    if (S.screen === "sesja" && prevView && prevView !== nowView) playScreenIn();
    return;
  }
  renderScreens(false);
}

// Zmienne drobiazgi (fps, badge histogramu, log, busy) aktualizowane
// punktowo po id — pelny rebuild ekranu niszczylby <img> streamu
// i podgladu (miganie co kazda zmiane stanu).
function updateVolatile(st) {
  // fps liczony na zywo przez watek aparatu, odswiezany co poll
  const fps = $("conn-fps");
  if (fps) fps.textContent = `${st.fps} fps`;
  const at = $("automat-text");
  if (at) {
    const au = automatStatus(st);
    if (at.textContent !== au.text) at.textContent = au.text;
    const ad = $("automat-dot");
    if (ad) ad.className = `dot ${au.cls}`;
  }
  const hist = $("hist-badge");
  if (hist) {
    const ht = $("hist-text"), hd = $("hist-dot");
    if (ht) ht.textContent = histLabel(st);
    if (hd) hd.className = `dot ${histDot(st)}`;
    hist.title = histTitle(st);
  }
  const lf = $("live-fps");
  if (lf) lf.textContent = st.fps;
  // EV jest ŚWIADOMIE łatane, nie keyowane: rebuild ekranu niszczy <img>
  // streamu MJPEG, a kompensacja zmienia się też z pokrętła na aparacie.
  // Cała łatka (w tym spinner oczekiwania na potwierdzenie z aparatu)
  // siedzi w evReconcile() w app-session.js.
  evReconcile(st);
  editReconcile(st);
  afReconcile(st);
  const sl = $("shoot-label");
  if (sl && performance.now() - shootErrAt > 4000) {
    sl.textContent = st.busy || "Zrób zdjęcie";
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
    if (st.warmup != null) {
      const wb = $("warmup-bar"), wt = $("warmup-text");
      if (wb) wb.style.width = `${warmupPct(st)}%`;
      if (wt) wt.innerHTML = warmupText(st);
    }
  }
  // „Odśwież listę" na ekranie startowym — spinner do konca odswiezania;
  // data-busy chroni animacje spinnera przed restartem przy kazdym pollu
  const rb = $("refresh-btn");
  if (rb) {
    const on = refreshingNow(st) ? "1" : "";
    if ((rb.dataset.busy || "") !== on) {
      rb.dataset.busy = on;
      rb.innerHTML = refreshBtnHtml();
    }
  }
  const up = $("update-progress");
  if (up) {
    const u = st.update || {};
    up.textContent = u.busy && u.progress ? `${u.progress}%` : "";
    const bar = $("update-bar-fill");
    if (bar) bar.style.width = `${u.busy ? u.progress || 0 : 0}%`;
  }
  const sig = logSig(st);
  if (sig !== S.lastLogLen) {
    S.lastLogLen = sig;
    ["log", "review-log"].forEach(prefix => {
      const line = $(`${prefix}-line`);
      if (line) line.innerHTML = lastLogLine();
      const lp = $(`${prefix}-panel`);
      if (lp) {
        lp.innerHTML = logLines();
        lp.scrollTop = lp.scrollHeight;
      }
    });
  }
}

// Jednorazowe przejscie przy zmianie widoku (lista sesji <-> sesja) — fade +
// minimalny scale, w duchu macOS. TYLKO przy realnej zmianie widoku: rebuildy
// w obrebie tego samego widoku (okladki, poll) i powroty po rebuildzie shella
// (prev === "") nie animuja, bo mrugaloby przy reconnextach i zmianie zakladki.
function playScreenIn(id = "screen-sesja") {
  const el = $(id);
  if (!el) return;
  el.style.animation = "none";
  void el.offsetWidth;   // restart animacji przy kolejnych przejsciach
  el.style.animation = "screenIn .38s cubic-bezier(0.32, 0.72, 0, 1)";
}

const isStartKey = k => typeof k === "string" && k.startsWith('["start"');

function renderScreens(force) {
  const st = S.state;
  updateVolatile(st);

  if (S.screen === "sesja" && !st.session.name) {
    const key = JSON.stringify(["start", st.automat, S.pendingNew, S.dayFocus,
                                S.sessionFilter, S.photosMin, S.photosMax, S.dateFilter]);
    if (force || key !== lastSesja) {
      // fokus i wartosc przezywaja rebuild w OBU polach ekranu startowego
      // (nazwa nowej sesji, filtr listy) — filtr rebuilduje na kazda litere
      const el = document.activeElement;
      const editId = el && ["new-session-input", "session-filter",
                            "photos-min", "photos-max"].includes(el.id)
        ? el.id : null;
      const keep = editId ? el.value : null;
      // fokus na polu nazwy tylko przy WEJŚCIU na ekran startowy (start
      // aplikacji, powrót z sesji/Ustawień — lastSesja jest wtedy zerowane);
      // kolejne rebuildy (dolatujące okładki) nie mają kraść fokusa
      const entering = !(typeof lastSesja === "string" && lastSesja.startsWith('["start"'));
      // okładki dolatują po kolei, każda = rebuild — bez tego lista skakałaby
      // na górę operatorowi w trakcie przeglądania
      const scroll = $("start-scroll") ? $("start-scroll").scrollTop : 0;
      const fromSesja = lastSesja && !isStartKey(lastSesja);
      lastSesja = key;
      snapshotSegs($("screen-sesja"));
      $("screen-sesja").innerHTML = startScreen();
      placeSegPill($("period-seg"), true);
      if (fromSesja) playScreenIn();
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
      const fromStart = isStartKey(lastSesja);
      // Przewinięcie paska zdjęć przechodzi przez przebudowę (wejście/wyjście
      // z podglądu): pasek stoi w tym samym miejscu, więc nie może skoczyć.
      // Na koniec jedziemy tylko, gdy przybyło zdjęć (świeży strzał).
      const oldStrip = $("review-strip") || $("filmstrip");
      const keepScroll = oldStrip && !fromStart && st.shots.length === S.stripCount ? oldStrip.scrollLeft : null;
      S.stripCount = st.shots.length;
      lastSesja = key;
      lastStrip = stripSig(st);
      S.lastLogLen = logSig(st);
      snapshotSegs($("screen-sesja"));
      $("screen-sesja").innerHTML = sesjaScreen();
      placeSegPill($("grid-seg"), true);
      if (fromStart) playScreenIn();
      ["filmstrip", "review-strip"].forEach(id => {
        const strip = $(id);
        if (!strip) return;
        if (keepScroll === null) strip.scrollLeft = strip.scrollWidth;
        else strip.scrollLeft = keepScroll;
        // w podglądzie oglądany kafelek musi być widać — dojeżdżamy płynnie
        // i tylko wtedy, gdy jest poza paskiem
        const tile = S.reviewMode && strip.querySelector(`[data-shot="${S.selShot}"]`);
        if (tile) {
          const a = tile.getBoundingClientRect(), b = strip.getBoundingClientRect();
          if (a.left < b.left || a.right > b.right) tile.scrollIntoView({ block: "nearest", inline: "nearest", behavior: "smooth" });
        }
      });
      const lp = $("log-panel");
      if (lp) lp.scrollTop = lp.scrollHeight;
    }
  } else {
    const key = JSON.stringify([st.settings, st.update]);
    if (force || key !== lastUstawienia) {
      if (document.activeElement && document.activeElement.tagName === "INPUT") return;
      lastUstawienia = key;
      const sc = $("settings-scroll") ? $("settings-scroll").scrollTop : 0;
      snapshotSegs($("screen-ustawienia"));
      $("screen-ustawienia").innerHTML = ustawieniaScreen();
      if ($("settings-scroll")) $("settings-scroll").scrollTop = sc;
      placeSegPill($("fps-seg"), true);
    }
  }
}

// Zmiana zakladki bez przebudowy shella: ekrany przelaczane w miejscu,
// niebieski pasek przejezdza pod nowa zakladke, a ekran wchodzi ta sama
// animacja co wejscie w sesje.
function go(screen) {
  if (S.screen === screen) return;
  S.screen = screen;
  ["sesja", "ustawienia"].forEach(k => {
    const t = $(`tab-${k}`);
    if (t) t.classList.toggle("on", k === screen);
    const el = $(`screen-${k}`);
    if (el) el.style.display = k === screen ? (k === "sesja" ? "flex" : "block") : "none";
  });
  placeTabBar(true);
  lastSesja = lastUstawienia = "";
  renderScreens(true);
  ["period-seg", "fps-seg", "grid-seg"].forEach(id => placeSegPill($(id), false));
  playScreenIn(`screen-${screen}`);
}

function placeTabBar(animate) {
  // biale tlo aktywnej zakladki (segmented control jak w macOS) przejezdza
  // pod nowa zakladke
  const t = $(`tab-${S.screen}`), pill = $("tab-pill");
  if (!t || !pill) return;
  const ease = "cubic-bezier(0.32, 0.72, 0, 1)";
  pill.style.transition = animate ? `left .36s ${ease}, width .36s ${ease}` : "none";
  pill.style.left = `${t.offsetLeft}px`;
  pill.style.width = `${t.offsetWidth}px`;
}


// ---------- akcje ----------

// Wyjscie z sesji = powrot na ekran startowy z lista sesji. Zmiana nazwy idzie
// wlasnie tamtedy (pole "Utworz i otworz"), wiec sidebar nie ma juz inputa.
function leaveSession() {
  S.pendingNew = null;
  // filtry listy nie maja przezywac wejscia do sesji — po powrocie operator ma
  // widziec pelna liste, a nie ogryzek po starym wyszukiwaniu
  S.sessionFilter = S.photosMin = S.photosMax = S.dateFilter = "";
  S.pickIdx = -1;
  post({ action: "clear_session" });
}

function shoot() {
  if (!S.state.connected || !S.state.session.name) return;
  flashNow();
  // Odpowiedź MUSI być obejrzana. Sam flash jest lokalny, więc odmowa backendu
  // („trwa aktualizacja", „aparat nie jest połączony") wyglądała identycznie jak zdjęcie
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

// Zmiana siatki W MIEJSCU: biale tlo przejezdza pod nowa opcje, linie siatki
// podmieniane na nakladce — rebuild ekranu zerwalby stream live view.
function setGrid(i) {
  if (S.grid === i) return;
  S.grid = i;
  const g = GRIDS[i];
  const ov = $("grid-overlay");
  if (ov) {
    ov.style.background = gridBackground(g.cols, g.rows);
    ov.style.display = g.cols && $("live") ? "block" : "none";
  }
  document.querySelectorAll("#grid-seg [data-grid]").forEach(b => {
    const on = +b.dataset.grid === i;
    b.classList.toggle("on", on);
    b.setAttribute("aria-pressed", on);
  });
  placeSegPill($("grid-seg"), true);
  lastSesja = sesjaKey(S.state);
}

// Biale tlo segmented controla pod aktywnym przyciskiem (.on). Pozycja jest
// pamietana per id kontrolki, wiec po przebudowie ekranu (filtr listy, zapis
// ustawienia) tlo PRZEJEZDZA ze starego miejsca, zamiast pojawic sie od razu.
const segPos = {};
function placeSegPill(seg, animate) {
  if (!seg) return;
  const pill = seg.querySelector(".overlay-pill, .seg-pill"), btn = seg.querySelector("button.on");
  if (!pill || !btn) return;
  const ease = "cubic-bezier(0.32, 0.72, 0, 1)";
  const to = { left: btn.offsetLeft, width: btn.offsetWidth };
  const from = seg.id && segPos[seg.id];
  if (seg.id) segPos[seg.id] = to;
  // animacja TYLKO przy realnej zmianie wyboru; świeżo zbudowany pill stoi na
  // 0/0 i bez tego warunku wjeżdżał od lewej przy każdej przebudowie ekranu
  const moved = from && (Math.abs(from.left - to.left) > .5 || Math.abs(from.width - to.width) > .5);
  if (animate && moved) {
    pill.style.transition = "none";
    pill.style.left = `${from.left}px`;
    pill.style.width = `${from.width}px`;
    void pill.offsetWidth;
  }
  pill.style.transition = animate && (moved || !seg.id) ? `left .32s ${ease}, width .32s ${ease}` : "none";
  pill.style.left = `${to.left}px`;
  pill.style.width = `${to.width}px`;
}

// Przed przebudową ekranu: gdzie BIAŁE TŁO jest teraz (także w trakcie
// animacji). Nowy przełącznik po przebudowie przejeżdża z tego miejsca — bez
// tego klik w filtr okresu (natychmiastowa przebudowa listy) gubił animację.
function snapshotSegs(root) {
  if (!root) return;
  root.querySelectorAll(".seg[id], .overlay-seg[id]").forEach(seg => {
    const pill = seg.querySelector(".overlay-pill, .seg-pill");
    if (!pill) return;
    const cs = getComputedStyle(pill);
    const width = parseFloat(cs.width) || 0;
    // jeszcze nieustawione tło (0 px) — zostaje ostatnia znana pozycja
    if (width) segPos[seg.id] = { left: parseFloat(cs.left) || 0, width };
  });
}

// Klik w opcję segmented controla: zaznaczenie i tło przestawiane od razu,
// zanim backend/rebuild odpowie.
function segClick(btn) {
  const seg = btn.closest(".seg, .overlay-seg");
  if (!seg) return;
  seg.querySelectorAll("button").forEach(b => {
    const on = b === btn;
    b.classList.toggle("on", on);
    b.setAttribute("aria-pressed", on);
  });
  placeSegPill(seg, true);
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
  // ⌘F / ⌘N na liscie sesji: fokus na wyszukiwarke / pole nowej sesji
  if ((e.metaKey || e.ctrlKey) && S.screen === "sesja" && S.state && !S.state.session.name
      && ["f", "n"].includes(e.key.toLowerCase())) {
    const el = $(e.key.toLowerCase() === "f" ? "session-filter" : "new-session-input");
    if (el) { e.preventDefault(); el.focus(); el.select(); }
    return;
  }
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
        movePickVertical(e.key === "ArrowDown" ? 1 : -1);
      } else if (e.key === "Enter") {
        openPicked();
      }
    }
    return;
  }
  if (e.metaKey || e.ctrlKey) return;

  // preventDefault na wszystkim co obslugujemy — bez tego WKWebView puszcza
  // klawisz w gore responder chain i macOS robi systemowy beep
  if (["Enter", " ", "Escape", "Backspace", "ArrowLeft", "ArrowRight",
       "p", "P", "a", "A", "x", "X", "e", "E"].includes(e.key)) {
    e.preventDefault();
  }
  // przy otwartym potwierdzeniu wyjscia reaguja TYLKO ESC (anuluj)
  // i ENTER (potwierdz) — reszta klawiszy nie ma strzelac zza modala
  if (S.leaveConfirm && !["Escape", "Enter"].includes(e.key)) return;
  // ekran startowy bez fokusa w polu: strzalki chodza po kafelkach sesji,
  // ENTER wchodzi w zaznaczona — skroty sesyjne (shoot itd.) nie dotycza
  // tego widoku
  if (S.screen === "sesja" && S.state && !S.state.session.name && !S.leaveConfirm) {
    if (e.key === "ArrowLeft") { e.preventDefault(); movePick(-1); }
    else if (e.key === "ArrowRight") { e.preventDefault(); movePick(1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); movePickVertical(-1); }
    else if (e.key === "ArrowDown") { e.preventDefault(); movePickVertical(1); }
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
      else if (S.edit) closeEdit();
      else if (S.reviewMode) closeReview();
      else if (S.screen === "sesja" && S.state && S.state.session.name) showLeaveConfirm();
      break;
    case "Backspace":
      if (S.reviewMode) deleteReviewed();
      break;
    case "p": case "P": toggle("preview", !S.state.previewOn); break;
    case "e": case "E": if (S.reviewMode) toggleEdit(); break;
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

// Motyw to atrybut na <html> — CSS podmienia tokeny, DOM nie jest ruszany
// (zero rebuildów, stream MJPEG żyje). Prawdą jest state.settings.uiTheme
// z backendu (.env); klik w Ustawieniach ustawia atrybut od razu, żeby nie
// czekać 500 ms na poll.
// Przelacznik motywu w pasku zakladek: ikona pokazuje motyw, NA KTORY sie
// przelaczy (slonce w ciemnym, ksiezyc w jasnym). Lata sie w miejscu — pelny
// rebuild ekranu sesji zerwalby stream live view.
const curTheme = () => document.documentElement.dataset.theme === "light" ? "light" : "dark";
const themeToggleTitle = () => curTheme() === "light" ? "Motyw ciemny" : "Motyw jasny";
function themeToggleIcon() {
  return icon(curTheme() === "light" ? "moon" : "sun");
}

function toggleTheme() {
  const next = curTheme() === "light" ? "dark" : "light";
  applyTheme(next);
  if (S.state && S.state.settings) S.state.settings.uiTheme = next;
  post({action: "set_app", key: "ui_theme", value: next});
  syncThemeToggle();
}

function syncThemeToggle() {
  const b = $("theme-toggle");
  if (!b) return;
  b.innerHTML = themeToggleIcon();
  b.title = themeToggleTitle();
  b.setAttribute("aria-label", themeToggleTitle());
}

function applyTheme(theme) {
  const t = theme === "light" ? "light" : "dark";
  if (document.documentElement.dataset.theme !== t) {
    document.documentElement.dataset.theme = t;
    syncThemeToggle();   // motyw zmieniony z Ustawien albo z .env
  }
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
    applyTheme(st.settings && st.settings.uiTheme);
    if (!lastShellKey) renderShell(true);
    else renderShell(false);
  } catch (e) {
    const el = $("conn-label");
    if (el) el.textContent = "brak połączenia z backendem";
  }
  setTimeout(tick, 500);
}
tick();
