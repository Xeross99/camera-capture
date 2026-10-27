"use strict";
// Tłumaczenia interfejsu (PL / EN). Kluczem jest POLSKI tekst — ten sam, który
// stoi w kodzie — więc brak tłumaczenia nie gubi napisu, tylko zostawia polski.
// Zmienne w nawiasach klamrowych: t("Pobrano {n} z API", {n: 3}).
//
// Słownik angielski uzupełnia każdy plik app-*.js własnym blokiem
// Object.assign(I18N_EN, {...}) — teksty leżą przy kodzie, który ich używa.
// Język przychodzi ze stanu backendu (settings.uiLang, UI_LANG w .env).

const I18N_EN = {};
let LANG = "pl";

function t(pl, vars) {
  let s = (LANG === "en" && I18N_EN[pl] !== undefined) ? I18N_EN[pl] : pl;
  if (vars) s = s.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? vars[k] : m));
  return s;
}

// Liczba + rzeczownik w języku interfejsu. Polski ma trzy formy
// (1 zdjęcie, 2 zdjęcia, 5 zdjęć), angielski dwie (1 photo, 2 photos).
const plForm = (n, one, few, many) =>
  n === 1 ? one : (n % 10 >= 2 && n % 10 <= 4 && !(n % 100 >= 12 && n % 100 <= 14) ? few : many);
const nForm = (n, pl, en) => (LANG === "en" ? (n === 1 ? en[0] : en[1]) : plForm(n, pl[0], pl[1], pl[2]));
const nWord = (n, pl, en) => `${n} ${nForm(n, pl, en)}`;

const PL_MONTHS = ["stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca",
  "lipca", "sierpnia", "września", "października", "listopada", "grudnia"];
const EN_MONTHS = ["January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December"];
const EN_MONTHS_SHORT = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const EN_WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
// miesiąc w dacie: „27 października" / „27 October"
const monthName = m => (LANG === "en" ? EN_MONTHS : PL_MONTHS)[m];
