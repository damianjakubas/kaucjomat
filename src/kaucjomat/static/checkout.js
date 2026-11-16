/** Kontroler kasy DEMO: odczyty, trwały pending i jawne odzyskanie wyniku. */
(() => {
  const demo = window.KaucjomatDemo;
  const store = window.KaucjomatCheckoutState;
  const contract = window.KaucjomatCheckoutContract;
  const view = window.KaucjomatCheckoutView;
  let context = null;
  let quote = null;
  const node = (id) => document.getElementById(id);
  const error = (message, source) => window.kaucjomatSetError(message, source);

  /** Stosuje blokady również wtedy, gdy mutację rozpoczął inny widok. */
  function controls() {
    view.controls(store.read(), context, quote, demo.busy, store.fault);
  }

  /** Zapis lokalny jest warunkiem zmiany ekranu i wysłania nowej operacji. */
  function save(next) {
    try {
      store.write(next);
      error("", "checkoutStorage");
      return true;
    } catch (failure) {
      error(failure.message, "checkoutStorage");
      return false;
    }
  }

  /** Odtwarza ekran z jednej spójnej lokalnej migawki. */
  function render() {
    const state = store.read();
    view.basket(state, context?.products || [], quote);
    view.result(state.result);
    controls();
  }

  /** Pobiera JSON bez ukrywania błędu lub niekompletnej odpowiedzi serwera. */
  async function fetchJson(url, body) {
    const response = await fetch(url, {
      headers: { Accept: "application/json", ...(body ? { "Content-Type": "application/json" } : {}) },
      ...(body ? { method: "POST", body: JSON.stringify(body) } : {}),
    });
    return { response, payload: await readJsonSafely(response) };
  }

  /** Zmiana generacji oznacza nowy pokaz i usuwa także stary pending. */
  function generationChanged(generation) {
    const state = store.read();
    if (state.generation === generation) return true;
    const changed = state.generation !== null;
    const next = changed ? store.empty(generation) : { ...state, generation };
    if (!save(next)) return false;
    if (changed) {
      node("checkout-message").textContent = "Pokaz DEMO został zresetowany. Wyczyszczono lokalny stan kasy.";
      error("", "checkoutAction");
      error("", "checkoutQuote");
    }
    return true;
  }

  /** Kontekst ma własny numer odczytu; spóźnione błędy też nie zmieniają ekranu. */
  async function loadContext() {
    if (demo.busy) return;
    const ticket = demo.read("checkoutContext");
    demo.read("checkoutQuote"); // Starsza wycena nie dotyczy jeszcze odświeżanego kontekstu.
    context = null;
    quote = null;
    controls();
    try {
      const { response, payload } = await fetchJson("/api/checkout/context");
      if (!demo.current(ticket)) return;
      if (!response.ok || !contract.contextValid(payload)) throw new Error(payload?.message || "Niepełny kontekst kasy.");
      if (store.fault || !generationChanged(payload.demo_generation_id)) {
        error(store.fault || "Nie można zapisać nowej generacji DEMO.", "checkoutStorage");
        return;
      }
      context = payload;
      view.catalog(payload.products);
      view.vouchers(payload.vouchers);
      error("", "checkoutContext");
      render();
      void loadQuote();
    } catch (failure) {
      if (!demo.current(ticket)) return;
      error(`Nie udało się odświeżyć kasy DEMO: ${failure.message}`, "checkoutContext");
      controls();
    }
  }

  /** Wycena dotyczy wyłącznie bieżącego koszyka; gotówka na nią nie czeka. */
  async function loadQuote() {
    const state = store.read();
    if (!context || demo.busy) return;
    const ticket = demo.read("checkoutQuote");
    quote = null;
    controls();
    try {
      const { response, payload } = await fetchJson("/api/checkout/quote", {
        demo_generation_id: state.generation, items: state.basket,
      });
      if (!demo.current(ticket)) return;
      if (payload?.error_code === "DEMO_GENERATION_CONFLICT") { void loadContext(); return; }
      if (!response.ok || !contract.quoteValid(payload, state.generation, state.basket)) {
        throw new Error(payload?.message || "Niepełna wycena koszyka.");
      }
      quote = payload;
      error("", "checkoutQuote");
      view.basket(store.read(), context.products, quote);
      controls();
    } catch (failure) {
      if (!demo.current(ticket)) return;
      error(`Nie można wycenić koszyka: ${failure.message}`, "checkoutQuote");
      controls();
    }
  }

  /** Edytuje ilości i zapisuje koszyk przed zleceniem nowej wyceny. */
  function editBasket(productId, delta) {
    const state = store.read();
    if (demo.busy || state.pending || !context || store.fault) return;
    if (!context.products.some((product) => product.product_id === productId)) return;
    const item = state.basket.find((entry) => entry.product_id === productId);
    const quantity = (item?.quantity || 0) + delta;
    if (quantity < 0 || quantity > 99) return;
    state.basket = state.basket.filter((entry) => entry.product_id !== productId);
    if (quantity) state.basket.push({ product_id: productId, quantity });
    if (!save(state)) return;
    quote = null;
    render();
    void loadQuote();
  }

  /** Zapamiętuje kod bez uruchamiania realizacji ani zmiany wybranego trybu. */
  function selectCode(code) {
    const state = store.read();
    if (demo.busy || state.pending || !context || store.fault) return;
    save({ ...state, code });
    controls(); // Po odmowie zapisu pole musi nadal pokazywać kod zapisanej operacji.
  }

  /** Tworzy pending przed POST; awaria storage uniemożliwia nowe rozliczenie. */
  async function redeem(mode) {
    const state = store.read();
    if (demo.busy || state.pending || !context || store.fault || (mode === "purchases" && !quote)) return;
    const code = state.code.trim().toUpperCase();
    if (!code) return;
    const pending = { operation_id: crypto.randomUUID(), demo_generation_id: state.generation,
      voucher_code: code, redemption_mode: mode, items: mode === "cash" ? [] : state.basket };
    if (!save({ ...state, pending })) return;
    await retry();
  }

  /** Ponawia wyłącznie zapisane żądanie; nie generuje nowego identyfikatora. */
  async function retry() {
    const pending = store.read().pending;
    if (!pending || !demo.begin("redemption")) return;
    const started = performance.now();
    let focusResult = false;
    try {
      const { response, payload } = await fetchJson("/api/checkout/redeem", pending);
      if (response.ok && contract.resultValid(payload, pending)) {
        const state = store.read();
        const next = { ...state, result: payload, pending: null, lastApplied: pending.operation_id,
          basket: pending.redemption_mode === "purchases" && state.lastApplied !== pending.operation_id ? [] : state.basket };
        if (!save(next)) throw new Error("Wynik serwera wymaga ponownego odzyskania z powodu błędu zapisu karty.");
        node("checkout-message").textContent = payload.message;
        error("", "checkoutAction");
        render();
        focusResult = true;
      } else if (response.status >= 400 && response.status < 500 && payload?.mode === "DEMO"
        && typeof payload.error_code === "string" && typeof payload.message === "string") {
        const next = payload.error_code === "DEMO_GENERATION_CONFLICT"
          ? store.empty() : { ...store.read(), pending: null };
        if (!save(next)) throw new Error("Nie zapisano odmowy. Sprawdź wynik ponownie.");
        node("checkout-message").textContent = payload.message;
        error(`${payload.message} (${payload.error_code})`, "checkoutAction");
        render();
      } else {
        throw new Error("Nie otrzymano jednoznacznego wyniku serwera.");
      }
    } catch (failure) {
      node("checkout-message").textContent = "Wynik nieustalony. Użyj „Sprawdź ponownie”; zachowano to samo żądanie DEMO.";
      error(`${failure.message} Sprawdź ponownie.`, "checkoutAction");
    } finally {
      const elapsed = performance.now() - started;
      node("checkout-timing").textContent = `Weryfikacja HTTP + DOM: ${elapsed.toFixed(2)} ms (limit < 200 ms)`;
      node("checkout-timing").dataset.elapsedMs = String(elapsed);
      demo.end("redemption");
      controls();
      (focusResult ? node("checkout-result") : node("checkout-message")).focus({ preventScroll: true });
    }
  }

  /** Reset lokalny wykonywany jest wyłącznie po potwierdzonym resecie serwera. */
  function onStateChanged(event) {
    context = null;
    quote = null;
    if (event.detail.phase === "end") {
      if (event.detail.reason === "reset") {
        if (save(store.empty())) {
          node("checkout-message").textContent = "Wyczyszczono kasę DEMO.";
          for (const source of ["checkoutAction", "checkoutQuote", "checkoutContext"]) error("", source);
          render();
        }
      }
      void loadContext();
    }
    controls();
  }

  /** Podpina klawiaturę i kliknięcia; F5 jedynie oferuje odzyskanie, bez automatycznego POST. */
  function init() {
    node("view-kasa").addEventListener("click", (event) => {
      const target = event.target.closest("[data-checkout-action]");
      if (!target || target.disabled) return;
      const action = target.dataset.checkoutAction;
      if (action === "voucher") { selectCode(target.dataset.voucherCode); node("checkout-code").focus(); }
      else editBasket(target.dataset.productId, action === "add" ? 1 : -1);
    });
    node("checkout-code").addEventListener("input", (event) => selectCode(event.target.value));
    node("checkout-purchases").addEventListener("click", () => { void redeem("purchases"); });
    node("checkout-cash").addEventListener("click", () => { void redeem("cash"); });
    node("checkout-retry").addEventListener("click", () => { void retry(); });
    node("checkout-refresh").addEventListener("click", () => { void loadContext(); });
    window.addEventListener("kaucjomat:state-changed", onStateChanged);
    window.addEventListener("kaucjomat:view-selected", (event) => { if (event.detail.viewId === "kasa") void loadContext(); });
    window.addEventListener("focus", () => { void loadContext(); });
    document.addEventListener("visibilitychange", () => { if (!document.hidden) void loadContext(); });
    if (store.fault) error(store.fault, "checkoutStorage");
    if (store.read().pending) node("checkout-message").textContent = "Odtworzono oczekujące żądanie. Wybierz „Sprawdź ponownie”.";
    render();
    void loadContext();
  }
  document.addEventListener("DOMContentLoaded", init);
})();
