"use strict";
// Zakladka Ustawienia + akcje sprawdzania/instalacji aktualizacji.

function ustawieniaScreen() {
  const st = S.state, cfg = st.settings, u = st.update || {current: "?", status: ""};
  // Backend ustawia `checking` już w handlerze akcji, ale poll ma 500 ms —
  // `S.checkStartedAt` trzyma spinner od razu po kliknięciu (i minimum ~600 ms,
  // żeby szybka odpowiedź nie mignęła bez śladu).
  const checking = u.checking || (S.checkStartedAt && Date.now() - S.checkStartedAt < 600);
  const card = `display: flex; flex-direction: column; gap: 12px; background: #232326; border: 1px solid #2f2f35; border-radius: 6px; padding: 16px 18px;`;
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
      <div style="display: flex; align-items: center; gap: 10px;">
        <button onclick="post({action:'test_connection'})" style="${btnGray} font-size: 11.5px;">Testuj połączenie</button>
        <span style="${mono} font-size: 10.5px; color: ${cfg.testResult.startsWith("✓") ? "#9fe0a8" : "#e0b96a"};">${cfg.testResult}</span>
      </div>
    </div>

    <div style="${card}">
      <div style="${head}">Podgląd</div>
      <div style="display: grid; grid-template-columns: 120px 1fr; gap: 8px 10px; align-items: center;">
        <div style="color: #b4b4bb;">FPS podglądu</div>
        <select onchange="post({action:'set_app', key:'preview_fps', value:this.value})" style="${sel}">
          ${[10, 15, 20, 25, 30].map(f => `<option ${f === cfg.previewFps ? "selected" : ""}>${f}</option>`).join("")}
        </select>
      </div>
    </div>

    <div style="${card}">
      <div style="${head}">Aktualizacje</div>
      <div style="display: grid; grid-template-columns: 120px 1fr; gap: 8px 10px; align-items: center;">
        <div style="color: #b4b4bb;">Wersja</div>
        <div style="${mono} font-size: 11.5px; color: #c9c9cf;">${u.current}</div>
      </div>
      <div style="display: flex; align-items: center; gap: 10px; flex-wrap: wrap;">
        <button onclick="checkUpdate()" ${checking ? "disabled" : ""} style="${btnGray} font-size: 11.5px; display: inline-flex; align-items: center; gap: 7px; ${checking ? "opacity: .7;" : ""}">${checking ? `<span class="spinner"></span>Sprawdzam…` : "Sprawdź aktualizacje"}</button>
        ${u.available && u.canApply ? `<button onclick="applyUpdate()" ${u.busy ? "disabled" : ""} style="height: 26px; padding: 0 12px; ${btnBlue} border-radius: 4px; font-size: 11.5px; font-weight: 600; display: inline-flex; align-items: center; gap: 7px; ${u.busy ? "opacity: .6;" : ""}">${u.busy ? `<span class="spinner"></span>Aktualizuję…` : `Zainstaluj ${u.available}`}</button>` : ""}
        <span style="${mono} font-size: 10.5px; color: ${checking ? "#9d9da3" : u.status.startsWith("✗") ? "#e07a7a" : u.available ? "#e0b96a" : "#9fe0a8"};">${checking ? "Pytam GitHuba o najnowsze wydanie…" : u.status}</span>
      </div>
      ${u.available && !u.canApply ? `<div style="${mono} font-size: 10.5px; color: #77777f;">Uruchomienie ze źródeł — aktualizacja przez <b>git pull</b>. Automatyczna podmiana działa tylko dla .exe na Windowsie.</div>` : ""}
      ${u.available && u.notes ? `<div style="${mono} font-size: 10.5px; color: #8f8f97; white-space: pre-wrap; max-height: 96px; overflow: auto;">${u.notes}</div>` : ""}
    </div>

    <div style="display: flex; flex-direction: column; gap: 10px; background: #232326; border: 1px solid #2f2f35; border-radius: 6px; padding: 16px 18px;">
      <div style="${head}">Skróty klawiszowe</div>
      <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 6px 18px; ${mono} font-size: 11px; color: #a8a8af;">
        <div>ENTER — zdjęcie</div><div>P — podgląd on/off</div>
        <div>SPACJA — podgląd zdjęć na live view</div><div>← → — zmiana zdjęcia / nawigacja</div>
        <div>BACKSPACE — usuń oglądane zdjęcie</div><div>ESC — zamknij podgląd</div>
      </div>
    </div>`;
}

function checkUpdate() {
  S.checkStartedAt = Date.now();
  post({ action: "check_update" });
  renderScreens(true);
  // pod koniec minimalnego czasu spinnera przemaluj — poll mógł w tym czasie
  // przynieść już gotowy wynik, a klucz ekranu się wtedy nie zmienił
  setTimeout(() => { S.checkStartedAt = 0; renderScreens(true); }, 650);
}

// Backend pobiera paczke, zamyka aplikacje i odpala aktualizator (.exe z
// pobranej paczki), ktory podmienia pliki i uruchamia aplikacje z powrotem —
// okno zniknie samo.
function applyUpdate() {
  const u = S.state.update || {};
  if (!u.canApply || u.busy) return;
  post({ action: "apply_update" });
}
