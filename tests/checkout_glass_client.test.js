/** Testy kontraktu kasy DEMO i migracji sessionStorage uruchamiane przez node --test. */
const assert = require("node:assert/strict");
const { readFileSync, readdirSync } = require("node:fs");
const { join } = require("node:path");
const { test } = require("node:test");
const { createContext, runInContext, Script } = require("node:vm");
const generation = "12345678-1234-1234-1234-123456789012";
const operation = "87654321-1234-1234-1234-123456789012";
const fields = ["glass_count", "glass_return_grosze", "glass_return_formatted"];

test("Wszystkie lokalne skrypty przeglądarki mają poprawną składnię", () => {
  const directory = join(__dirname, "../src/kaucjomat/static");
  for (const name of readdirSync(directory).filter((name) => name.endsWith(".js"))) {
    assert.doesNotThrow(() => new Script(readFileSync(join(directory, name), "utf8"), { filename: name }));
  }
});

/** Uruchamia rzeczywiste skrypty klienta w odizolowanej pamięci karty. */
function client(saved = null) {
  let storage = saved === null ? null : JSON.stringify(saved);
  const sandbox = createContext({ window: {}, structuredClone, sessionStorage: {
    getItem: () => storage,
    setItem: (_key, value) => { storage = value; },
  } });
  for (const name of ["checkout_contract.js", "checkout_state.js"]) {
    runInContext(readFileSync(join(__dirname, "../src/kaucjomat/static", name), "utf8"), sandbox);
  }
  return { contract: sandbox.window.KaucjomatCheckoutContract,
    store: sandbox.window.KaucjomatCheckoutState, saved: () => JSON.parse(storage) };
}

/** Buduje spójną parę żądania i wyniku dla obu trybów rozliczenia. */
function transaction(mode, count) {
  const items = mode === "cash" ? [] : [{ product_id: "bread", quantity: 1 }];
  const request = { operation_id: operation, demo_generation_id: generation,
    voucher_code: "BON-DEMO-0001", redemption_mode: mode, items, glass_count: count };
  const total = mode === "cash" ? 0 : 3000;
  const due = mode === "cash" ? 0 : total - 50 - count * 100;
  const payout = mode === "cash" ? 50 + count * 100 : 0;
  const formatted = (grosze) => `${(grosze / 100).toFixed(2).replace(".", ",")} zł`;
  const settlement = { ...request, mode: "DEMO", voucher_status: "ZUŻYTY",
    redeemed_at_iso: "2026-11-16T12:00:00Z", voucher_amount_grosze: 50, voucher_amount_formatted: "0,50 zł",
    basket_total_grosze: total, basket_total_formatted: `${total / 100},00 zł`,
    glass_return_grosze: count * 100, glass_return_formatted: `${count},00 zł`,
    amount_due_grosze: due, amount_due_formatted: formatted(due),
    cash_payout_grosze: payout, cash_payout_formatted: formatted(payout),
    items: items.map((item) => ({ ...item, name: "Chleb", unit_price_grosze: 3000,
      unit_price_formatted: "30,00 zł", line_total_grosze: 3000, line_total_formatted: "30,00 zł" })),
  };
  return { request, payload: { mode: "DEMO", message: "Rozliczono DEMO.",
    was_idempotent_replay: false, settlement } };
}

/** Tworzy zapis karty z wynikiem albo żądaniem czekającym na ponowienie. */
function stateFor(mode, count, pending = false) {
  const { request, payload } = transaction(mode, count);
  return { version: 1, generation, basket: [{ product_id: "bread", quantity: 1 }], glassCount: count,
    code: request.voucher_code, pending: pending ? request : null,
    result: pending ? null : payload, lastApplied: pending ? null : operation };
}

for (const count of [-1, 21, true, false, 1.5, "1", null, [], {}]) {
  test(`Odrzuca nieprawidłową liczbę szkła: ${JSON.stringify(count)}`, () => {
    const { contract, store } = client();
    assert.equal(contract.glassCountValid(count), false);
    assert.equal(contract.requestValid(transaction("cash", count).request), false);
    assert.throws(() => store.write({ ...store.empty(generation), glassCount: count }));
  });
}

for (const mode of ["purchases", "cash"]) {
  for (const count of [0, 1, 20]) {
    test(`Akceptuje poprawne rozliczenie ${mode} ze szkłem ${count} i odtworzenie karty`, () => {
      const { contract, store, saved } = client();
      const { request, payload } = transaction(mode, count);
      assert.equal(contract.quoteValid(payload.settlement, generation, request.items, count), true);
      assert.equal(contract.resultValid(payload, request), true);
      assert.equal(contract.resultValid({ ...payload, was_idempotent_replay: true }, request), true);
      store.write(stateFor(mode, count));
      assert.equal(client(saved()).store.read().glassCount, count);
      assert.equal(client(saved()).store.fault, "");
      const pending = client(stateFor(mode, count, true)).store;
      assert.equal(pending.fault, "");
      assert.equal(pending.read().pending.glass_count, count);
    });
  }
  for (const field of ["glass_count", "glass_return_grosze", "amount_due_grosze", "cash_payout_grosze"]) {
    test(`Odrzuca niespójny wynik ${mode}: ${field}`, () => {
      const { contract } = client();
      const { request, payload } = transaction(mode, 2);
      payload.settlement[field] += 1;
      assert.equal(contract.resultValid(payload, request), false);
    });
  }
  for (const pending of [false, true]) {
    test(`Migruje kompletny starszy zapis ${mode}, pending=${pending}, bez utraty danych`, () => {
      const legacy = stateFor(mode, 0, pending);
      delete legacy.glassCount;
      if (pending) delete legacy.pending.glass_count;
      else for (const field of fields) delete legacy.result.settlement[field];
      const { store } = client(legacy);
      assert.equal(store.fault, "");
      assert.deepEqual(store.read(), stateFor(mode, 0, pending));
    });
  }
}

for (let mask = 1; mask < 7; mask += 1) {
  test(`Odrzuca częściowy zapis pól szkła ${mask}, zachowując źródło`, () => {
    const corrupted = stateFor("cash", 0);
    fields.forEach((field, index) => { if (!(mask & (1 << index))) delete corrupted.result.settlement[field]; });
    const { store, saved } = client(corrupted);
    assert.notEqual(store.fault, "");
    assert.deepEqual(saved(), corrupted);
  });
}

test("Wymaga kompletnej specyfikacji szkła z backendu DEMO", () => {
  const { contract } = client();
  const payload = { mode: "DEMO", demo_generation_id: generation, vouchers: [],
    products: [{ product_id: "bread", name: "Chleb", unit_price_grosze: 3000, unit_price_formatted: "30,00 zł" }],
    glass_return_spec: { title: "Butelka szklana do 1,5 l", unit_deposit_grosze: 100,
      unit_deposit_formatted: "1,00 zł", max_volume_ml: 1500, max_quantity: 20 } };
  assert.equal(contract.contextValid(payload), true);
  for (const field of Object.keys(payload.glass_return_spec)) {
    const corrupted = structuredClone(payload);
    delete corrupted.glass_return_spec[field];
    assert.equal(!!contract.contextValid(corrupted), false);
  }
});

test("Odrzuca inne szkło niż w żądaniu i zachowuje regułę pustego koszyka gotówki", () => {
  const { contract } = client();
  const { request, payload } = transaction("cash", 2);
  assert.equal(contract.resultValid(payload, { ...request, glass_count: 1 }), false);
  assert.equal(contract.requestValid({ ...request, items: [{ product_id: "bread", quantity: 1 }] }), false);
  const purchases = transaction("purchases", 2);
  purchases.payload.settlement.voucher_amount_grosze = 2900;
  purchases.payload.settlement.amount_due_grosze = -100;
  assert.equal(contract.resultValid(purchases.payload, purchases.request), false);
});
