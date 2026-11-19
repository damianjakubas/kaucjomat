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
