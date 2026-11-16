/** Walidacja odpowiedzi kasy przed zastosowaniem lokalnych skutków rozliczenia. */
window.KaucjomatCheckoutContract = (() => {
  const money = (value) => Number.isSafeInteger(value) && value >= 0;
  const text = (value) => typeof value === "string" && value.length > 0;
  /** Liczba butelek jest całkowita i mieści się w limicie jednej transakcji DEMO. */
  const glassCountValid = (value) => Number.isInteger(value) && value >= 0 && value <= 20;
  const uuid = (value) => typeof value === "string"
    && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value);
  const canonical = (items) => [...items].sort((a, b) => a.product_id.localeCompare(b.product_id));

  /** Odrzuca uszkodzony koszyk lokalny bez konwersji typów ilości. */
  function itemsValid(items) {
    return Array.isArray(items) && items.length <= 20
      && new Set(items.map((item) => item?.product_id)).size === items.length
      && items.every((item) => item && text(item.product_id) && item.product_id.length <= 64
        && Number.isInteger(item.quantity) && item.quantity >= 1 && item.quantity <= 99);
  }

  /** Porównuje tożsamość pozycji, niezależnie od kolejności przesłanej przez serwer. */
  function sameItems(left, right) {
    if (!itemsValid(left) || !itemsValid(right) || left.length !== right.length) return false;
    return canonical(left).every((item, index) => item.product_id === canonical(right)[index].product_id
      && item.quantity === canonical(right)[index].quantity);
  }

  /** Sprawdza wszystkie pola wyceny oraz arytmetykę migawki otrzymanej z backendu. */
  function quoteValid(quote, generation, items, glassCount = 0) {
    return quote?.mode === "DEMO" && quote.demo_generation_id === generation
      && glassCountValid(glassCount) && quote.glass_count === glassCount
      && quote.glass_return_grosze === glassCount * 100 && text(quote.glass_return_formatted)
      && sameItems(quote.items, items) && money(quote.basket_total_grosze)
      && text(quote.basket_total_formatted)
      && quote.items.every((item) => text(item.name) && money(item.unit_price_grosze)
        && text(item.unit_price_formatted) && text(item.line_total_formatted)
        && money(item.line_total_grosze) && item.line_total_grosze === item.unit_price_grosze * item.quantity)
      && quote.basket_total_grosze === quote.items.reduce((sum, item) => sum + item.line_total_grosze, 0);
  }

  /** Sprawdza żądanie oczekujące zachowane przez F5. */
  function requestValid(request) {
    return request && uuid(request.operation_id) && uuid(request.demo_generation_id)
      && text(request.voucher_code) && request.voucher_code.length <= 64
      && request.voucher_code === request.voucher_code.trim().toUpperCase()
      && ["purchases", "cash"].includes(request.redemption_mode) && itemsValid(request.items)
      && glassCountValid(request.glass_count)
      && (request.redemption_mode !== "cash" || request.items.length === 0);
  }

  /** Sukces musi odpowiadać dokładnie oczekującemu żądaniu, także podczas replayu. */
  function resultValid(payload, request) {
    if (!requestValid(request) || payload?.mode !== "DEMO" || !text(payload.message)
      || typeof payload.was_idempotent_replay !== "boolean") return false;
    const result = payload.settlement;
    if (!result || !quoteValid(result, request.demo_generation_id, request.items, request.glass_count)
      || result.operation_id !== request.operation_id || result.voucher_code !== request.voucher_code
      || result.redemption_mode !== request.redemption_mode || result.voucher_status !== "ZUŻYTY"
      || !text(result.redeemed_at_iso) || !Number.isFinite(Date.parse(result.redeemed_at_iso))) return false;
    for (const key of ["voucher_amount", "amount_due", "cash_payout"]) {
      if (!money(result[`${key}_grosze`]) || !text(result[`${key}_formatted`])) return false;
    }
    return result.voucher_amount_grosze > 0 && (request.redemption_mode === "cash"
      ? result.basket_total_grosze === 0 && result.amount_due_grosze === 0
        && result.cash_payout_grosze === result.voucher_amount_grosze + result.glass_return_grosze
      : result.cash_payout_grosze === 0
        && result.basket_total_grosze >= result.voucher_amount_grosze + result.glass_return_grosze
        && result.amount_due_grosze === result.basket_total_grosze - result.voucher_amount_grosze - result.glass_return_grosze);
  }

  /** Kontekst bez kompletnego katalogu i listy nie pozwala rozpocząć nowej realizacji. */
  function contextValid(payload) {
    const glass = payload?.glass_return_spec;
    return payload?.mode === "DEMO" && uuid(payload.demo_generation_id)
      && glass && text(glass.title) && glass.unit_deposit_grosze === 100
      && text(glass.unit_deposit_formatted) && glass.max_volume_ml === 1500 && glass.max_quantity === 20
      && Array.isArray(payload.products) && payload.products.length > 0
      && payload.products.every((item) => text(item.product_id) && text(item.name)
        && money(item.unit_price_grosze) && text(item.unit_price_formatted))
      && Array.isArray(payload.vouchers) && payload.vouchers.every((voucher) => text(voucher.voucher_code)
        && money(voucher.amount_grosze) && text(voucher.amount_formatted)
        && ["AKTYWNY", "ZUŻYTY", "WYGASŁY"].includes(voucher.status)
        && text(voucher.issued_at_iso) && text(voucher.expires_at_iso));
  }

  return { uuid, glassCountValid, itemsValid, sameItems, quoteValid, requestValid, resultValid, contextValid };
})();
