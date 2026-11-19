/** Testy mapowania kart opakowań na ilustracje półki butelkomatu uruchamiane przez node --test. */
const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const { test } = require("node:test");
const { createContext, runInContext } = require("node:vm");
const staticDir = join(__dirname, "../src/kaucjomat/static");

/** Ładuje moduł ilustracji w odizolowanej pamięci z samym `window`, bez DOM. */
function loadArt() {
  const sandbox = createContext({ window: {} });
  runInContext(readFileSync(join(staticDir, "return_machine_art.js"), "utf8"), sandbox);
  return sandbox.window.KaucjomatReturnArt;
}

/** Buduje kartę o domyślnych atrybutach poprawnego PET z możliwością nadpisania pól. */
function card(overrides) {
  return { category: "PET", volume_ml: 1500, has_deposit_logo: true, is_crushed: false, is_empty: true, ...overrides };
}

// Atrybuty ośmiu kart katalogu przepisane z backendu wraz z oczekiwanym plikiem.
const CATALOG = [
  ["pet-water-1500-a", card({}), "pet-1500.svg"],
  ["pet-water-1500-b", card({}), "pet-1500.svg"],
  ["can-cola-500", card({ category: "CAN", volume_ml: 500 }), "can-500.svg"],
  ["glass-beer-500", card({ category: "GLASS", volume_ml: 500 }), "glass-500.svg"],
  ["reject-no-logo", card({ volume_ml: 500, has_deposit_logo: false }), "pet-500-no-logo.svg"],
  ["reject-crushed-can", card({ category: "CAN", volume_ml: 500, is_crushed: true }), "can-crushed.svg"],
  ["reject-dairy-carton", card({ category: "DAIRY_CARTON", volume_ml: 1000 }), "carton-milk.svg"],
  ["reject-over-volume", card({ volume_ml: 5000 }), "pet-jug-5000.svg"],
];

test("Moduł ilustracji ładuje się w vm z samym window i eksportuje API", () => {
  const art = loadArt();
  assert.equal(typeof art.resolvePackageArt, "function");
  assert.equal(typeof art.buildPackageFigure, "function");
});

for (const [cardId, attributes, file] of CATALOG) {
  test(`Karta ${cardId} dostaje ilustrację ${file}`, () => {
    const result = loadArt().resolvePackageArt(attributes);
    assert.equal(result.src, `/static/assets/${file}`);
    assert.ok(result.alt.length > 0);
  });
}

test("Każdy plik wskazany przez mapowanie istnieje na dysku", () => {
  const { existsSync } = require("node:fs");
  for (const [, , file] of CATALOG) {
    assert.ok(existsSync(join(staticDir, "assets", file)), `Brak pliku ${file}.`);
  }
});

test("Zgniecenie ma pierwszeństwo przed kategorią", () => {
  const art = loadArt();
  assert.match(art.resolvePackageArt(card({ category: "GLASS", is_crushed: true })).src, /can-crushed\.svg$/);
});

test("Kategoria OTHER i nieznana mają odpowiednio karton i domyślną butelkę", () => {
  const art = loadArt();
  assert.match(art.resolvePackageArt(card({ category: "OTHER" })).src, /carton-milk\.svg$/);
  assert.match(art.resolvePackageArt(card({ category: "NIEZNANA" })).src, /pet-1500\.svg$/);
  assert.match(art.resolvePackageArt(undefined).src, /pet-1500\.svg$/);
});

test("Klasa rozmiaru wynika z pojemności 500, 1500 i 5000 ml", () => {
  const art = loadArt();
  assert.equal(art.resolvePackageArt(card({ volume_ml: 500 })).sizeClass, "is-small");
  assert.equal(art.resolvePackageArt(card({ volume_ml: 1500 })).sizeClass, "is-medium");
  assert.equal(art.resolvePackageArt(card({ volume_ml: 5000 })).sizeClass, "is-large");
});

/** Ładuje moduł efektów z atrapą DOM zawierającą front automatu i kontrolkę stanu. */
function loadFx() {
  const front = { dataset: {} };
  const led = { textContent: "" };
  const document = {
    querySelector: (selector) => (selector === ".machine-front" ? front : null),
    getElementById: (id) => (id === "machine-led" ? led : null),
  };
  const sandbox = createContext({ window: {}, document });
  runInContext(readFileSync(join(staticDir, "return_machine_fx.js"), "utf8"), sandbox);
  return { fx: sandbox.window.KaucjomatReturnFx, front, led };
}

test("Moduł efektów ładuje się w vm bez DOM i eksportuje API", () => {
  const sandbox = createContext({ window: {} });
  runInContext(readFileSync(join(staticDir, "return_machine_fx.js"), "utf8"), sandbox);
  const fx = sandbox.window.KaucjomatReturnFx;
  for (const name of ["setMachineState", "clearScanning", "markPendingAttempt", "isFreshAttempt", "roundTripFor", "playVoucherIssue"]) {
    assert.equal(typeof fx[name], "function", name);
  }
});

test("Stan maszyny ustawia atrybut frontu i napis kontrolki", () => {
  const { fx, front, led } = loadFx();
  const expected = { idle: "GOTOWY", scanning: "SKANOWANIE", accepted: "PRZYJĘTO", redirected: "DO KASY", rejected: "ODRZUCONO" };
  for (const [state, label] of Object.entries(expected)) {
    fx.setMachineState(state);
    assert.equal(front.dataset.machineState, state);
    assert.equal(led.textContent, label);
  }
  fx.setMachineState("nieznany");
  assert.equal(front.dataset.machineState, "idle");
});

test("clearScanning zdejmuje tylko skanowanie i nie psuje decyzji", () => {
  const { fx, front } = loadFx();
  fx.setMachineState("scanning");
  fx.clearScanning();
  assert.equal(front.dataset.machineState, "idle");
  fx.setMachineState("rejected");
  fx.clearScanning();
  assert.equal(front.dataset.machineState, "rejected");
});

test("Świeża próba wygasa po 1,5 s i dotyczy tylko oznaczonego numeru", () => {
  const { fx } = loadFx();
  assert.equal(fx.isFreshAttempt(1, 1000), false);
  fx.markPendingAttempt(3, 41.5, 1000);
  assert.equal(fx.isFreshAttempt(3, 1000), true);
  assert.equal(fx.isFreshAttempt(3, 2499), true);
  assert.equal(fx.isFreshAttempt(3, 2500), false);
  assert.equal(fx.isFreshAttempt(2, 1200), false);
});

test("Czas HTTP+DOM jest pamiętany dla ostatniej próby, a bez pomiaru wynosi null", () => {
  const { fx } = loadFx();
  assert.equal(fx.roundTripFor(1), null);
  fx.markPendingAttempt(2, 37.25, 0);
  assert.equal(fx.roundTripFor(2), 37.25);
  assert.equal(fx.roundTripFor(1), null);
  fx.markPendingAttempt(3, null, 0);
  assert.equal(fx.roundTripFor(3), null);
});
