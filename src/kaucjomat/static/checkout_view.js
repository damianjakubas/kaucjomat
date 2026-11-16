/** Bezpieczne renderowanie kasy DEMO przez createElement i textContent. */
window.KaucjomatCheckoutView = (() => {
  const node = (id) => document.getElementById(id);

  /** Tworzy element z tekstem pochodzącym z API, bez interpretacji HTML. */
  function element(tag, text, className = "") {
    const item = document.createElement(tag);
    item.textContent = text;
    item.className = className;
    return item;
  }

  /** Tworzy przycisk delegowany do kontrolera, z opisem dla klawiatury i czytnika. */
  function button(text, action, productId, label = text) {
    const item = element("button", text);
    item.type = "button";
    item.dataset.checkoutAction = action;
    item.dataset.productId = productId;
    item.setAttribute("aria-label", label);
    return item;
  }

  /** Renderuje katalog; nazwy i ceny pokazuje wyłącznie z kontekstu backendu. */
  function catalog(products) {
    const list = node("checkout-products");
    list.replaceChildren();
    for (const product of products) {
      const row = element("li", "", "checkout-row");
      row.append(element("span", `${product.name} · ${product.unit_price_formatted}`),
        button("Dodaj", "add", product.product_id, `Dodaj: ${product.name}`));
      list.append(row);
    }
  }

  /** Odtwarza koszyk i zachowuje focus kontrolki po zmianie ilości. */
  function basket(state, products, quote) {
    const active = document.activeElement;
    const focus = active?.closest("#checkout-basket") ? {
      action: active.dataset.checkoutAction, product: active.dataset.productId,
    } : null;
    const list = node("checkout-basket");
    list.replaceChildren();
    if (!state.basket.length) list.append(element("li", "Koszyk jest pusty.", "checkout-empty"));
    for (const item of state.basket) {
      const name = products.find((product) => product.product_id === item.product_id)?.name || item.product_id;
      const priced = quote?.items.find((product) => product.product_id === item.product_id);
      const row = element("li", "", "checkout-row");
      const controls = element("span", "", "checkout-quantity");
      controls.append(button("−", "remove", item.product_id, `Usuń sztukę: ${name}`),
        element("span", `${item.quantity} szt.`), button("+", "add", item.product_id, `Dodaj sztukę: ${name}`));
      row.append(element("span", `${name}${priced ? ` · ${priced.line_total_formatted}` : ""}`), controls);
      list.append(row);
    }
    node("checkout-total").textContent = quote ? quote.basket_total_formatted : "Oczekiwanie na wycenę…";
    if (focus) {
      const target = [...list.querySelectorAll("button")].find((item) => item.dataset.checkoutAction === focus.action
        && item.dataset.productId === focus.product);
      (target || node("checkout-products").querySelector("button"))?.focus({ preventScroll: true });
    }
  }

  /** Pokazuje statusy i daty; wybór bonu jedynie wypełnia pole kodu. */
  function vouchers(items) {
    const list = node("checkout-vouchers");
    list.replaceChildren();
    for (const voucher of items) {
      const row = element("li", "", "checkout-voucher");
      const choose = button(`${voucher.voucher_code} · ${voucher.amount_formatted}`, "voucher", "");
      choose.dataset.voucherCode = voucher.voucher_code;
      choose.dataset.inactive = String(voucher.status !== "AKTYWNY");
      choose.setAttribute("aria-describedby", `checkout-voucher-${list.children.length}`);
      const status = element("p", `${voucher.status} · Wystawiono: ${formatIsoDateUtc(voucher.issued_at_iso)}
        · Ważny do: ${formatIsoDateUtc(voucher.expires_at_iso)}
        ${voucher.redeemed_at_iso ? ` · Zrealizowano: ${formatIsoDateUtc(voucher.redeemed_at_iso)}` : ""}`);
      status.id = `checkout-voucher-${list.children.length}`;
      if (voucher.status !== "AKTYWNY") status.append(element("span", voucher.status === "ZUŻYTY"
        ? " — Bon został już wykorzystany." : " — Upłynął termin ważności bonu."));
      row.append(choose, status);
      list.append(row);
    }
    if (!items.length) list.append(element("li", "Brak bonów DEMO."));
  }

  /** Renderuje wyłącznie ostatnie rozstrzygnięcie, niezależnie od bieżącej listy bonów. */
  function result(payload) {
    const section = node("checkout-result");
    section.hidden = !payload;
    const body = node("checkout-result-body");
    body.replaceChildren();
    if (!payload) return;
    const value = payload.settlement;
    body.append(element("p", payload.message), element("p", `${value.voucher_code} · ZUŻYTY
      · ${formatIsoDateUtc(value.redeemed_at_iso)} · Bon: ${value.voucher_amount_formatted}`));
    const list = element("ul", "");
    for (const item of value.items) list.append(element("li",
      `${item.name} × ${item.quantity} · ${item.unit_price_formatted}/szt. · ${item.line_total_formatted}`));
    body.append(list, element("p", `Zakupy: ${value.basket_total_formatted}`), element("strong",
      value.redemption_mode === "cash" ? `Wypłata DEMO: ${value.cash_payout_formatted}`
        : `Pozostała kwota do zapłaty: ${value.amount_due_formatted}`));
    body.append(element("p", value.redemption_mode === "cash"
      ? "Koszyk został zachowany. Zakupy pozostają nierozliczone."
      : "Koszyk wyczyszczono. Pozostała kwota jest wynikiem symulacji DEMO."));
  }

  /** Aktualizuje blokady bez przebudowy listy i utraty fokusu podczas żądania. */
  function controls(state, context, quote, busy, fault) {
    const locked = busy || !!state.pending || !context || !!fault;
    document.querySelectorAll("[data-checkout-action]").forEach((item) => {
      const quantity = state.basket.find((entry) => entry.product_id === item.dataset.productId)?.quantity || 0;
      item.disabled = locked || item.dataset.inactive === "true"
        || (item.dataset.checkoutAction === "add" && quantity >= 99);
    });
    const input = node("checkout-code");
    if (input.value !== state.code) input.value = state.code;
    input.disabled = locked;
    node("checkout-purchases").disabled = locked || !quote || !state.code.trim();
    node("checkout-cash").disabled = locked || !state.code.trim();
    node("checkout-retry").hidden = !state.pending;
    node("checkout-retry").disabled = busy;
    node("checkout-refresh").disabled = busy;
    node("checkout-pending").hidden = !state.pending;
    node("checkout-context-state").textContent = context ? "Ceny i statusy pobrano z serwera DEMO."
      : "Brak aktualnego kontekstu. Odśwież dane przed nowym rozliczeniem.";
    node("checkout-quote-state").textContent = quote ? "Wycena backendu jest aktualna."
      : "Zakupy czekają na wycenę. Wypłata gotówki jest niezależna od koszyka.";
  }

  return { catalog, basket, vouchers, result, controls };
})();
