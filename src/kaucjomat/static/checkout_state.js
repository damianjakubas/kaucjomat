/** Jeden wersjonowany zapis stanu karty; odczyty zwracają kopie, nigdy mutowalny pending. */
window.KaucjomatCheckoutState = (() => {
  const key = "kaucjomat.checkout.v1";
  const contract = window.KaucjomatCheckoutContract;
  let fault = "";
  const empty = (generation = null) => ({
    version: 1, generation, basket: [], glassCount: 0, code: "", result: null, lastApplied: null, pending: null,
  });
  let state = empty();

  /** Uzupełnia wyłącznie nieobecne pola starej wersji, nie naprawiając częściowych wyników. */
  function migrate(value) {
    if (!value || typeof value !== "object" || Array.isArray(value)) return value;
    if (!Object.hasOwn(value, "glassCount")) value.glassCount = 0;
    if (value.pending && typeof value.pending === "object" && !Object.hasOwn(value.pending, "glass_count")) {
      value.pending.glass_count = 0;
    }
    const result = value.result?.settlement;
    if (result && typeof result === "object"
      && ["glass_count", "glass_return_grosze", "glass_return_formatted"].every((key) => !Object.hasOwn(result, key))) {
      Object.assign(result, { glass_count: 0, glass_return_grosze: 0, glass_return_formatted: "0,00 zł" });
    }
    return value;
  }

  /** Sprawdza spójność całego zapisu, zamiast częściowo odzyskiwać uszkodzoną operację. */
  function valid(value) {
    if (!value || value.version !== 1 || !(value.generation === null || contract.uuid(value.generation))
      || !contract.itemsValid(value.basket) || !contract.glassCountValid(value.glassCount)
      || typeof value.code !== "string" || value.code.length > 64
      || !(value.lastApplied === null || contract.uuid(value.lastApplied))) return false;
    if (value.pending !== null && (!contract.requestValid(value.pending)
      || value.pending.demo_generation_id !== value.generation)) return false;
    if (value.result !== null) {
      const result = value.result?.settlement;
      if (!result || !contract.resultValid(value.result, {
        ...result, items: result.items,
      }) || result.operation_id !== value.lastApplied || result.demo_generation_id !== value.generation) return false;
    }
    return true;
  }

  try {
    const saved = sessionStorage.getItem(key);
    if (saved !== null) {
      const restored = migrate(JSON.parse(saved));
      if (!valid(restored)) throw new Error("Niepoprawny zapis kasy. Użyj resetu DEMO, aby rozpocząć nowy pokaz.");
      state = restored;
    }
  } catch (error) {
    fault = `Nie można odtworzyć stanu kasy: ${error.message}`;
  }

  return {
    get fault() { return fault; },
    /** Zwraca odłączoną kopię stanu, chroniąc treść oczekującego żądania. */
    read() { return structuredClone(state); },
    /** Zapisuje najpierw storage, potem pamięć; wyjątek nie usuwa starego pending. */
    write(next) {
      if (!valid(next)) throw new Error("Niespójny lokalny stan kasy DEMO.");
      try {
        sessionStorage.setItem(key, JSON.stringify(next));
      } catch {
        throw new Error("Nie można zapisać stanu karty. Sprawdź dostęp do pamięci przeglądarki i ponów.");
      }
      state = structuredClone(next);
      fault = "";
    },
    empty,
  };
})();
