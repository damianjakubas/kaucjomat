/**
 * Stan efektów Butelkomatu DEMO: kontrolka maszyny, podświetlenie nowego wiersza dziennika i wysunięcie bonu.
 * Moduł nie dotyka DOM podczas ładowania, więc da się go uruchomić w sandboxie testowym z samym `window`.
 */
window.KaucjomatReturnFx = (() => {
  const FRESH_MS = 1500;
  const PRINT_MS = 900;
  const LED_LABELS = { idle: "GOTOWY", scanning: "SKANOWANIE", accepted: "PRZYJĘTO", redirected: "DO KASY", rejected: "ODRZUCONO" };
  // Ostatnia próba wykonana w tej karcie przeglądarki: oznaczenie „świeżości” i zmierzony czas HTTP+DOM.
  let pending = null;
  let measured = null;

  /**
   * Ustawia stan frontu automatu oraz napis na kontrolce; nieznany stan oznacza gotowość.
   * @param {"idle"|"scanning"|"accepted"|"redirected"|"rejected"} state - Nowy stan maszyny.
   * @returns {void}
   */
  function setMachineState(state) {
    const key = Object.prototype.hasOwnProperty.call(LED_LABELS, state) ? state : "idle";
    const front = document.querySelector(".machine-front");
    if (front) front.dataset.machineState = key;
    const led = document.getElementById("machine-led");
    if (led) led.textContent = LED_LABELS[key];
  }

  /**
   * Zdejmuje stan skanowania, jeśli żadna decyzja go nie zastąpiła (np. po błędzie API).
   * @returns {void}
   */
  function clearScanning() {
    const front = document.querySelector(".machine-front");
    if (front && front.dataset.machineState === "scanning") setMachineState("idle");
  }

  /**
   * Zapamiętuje próbę wykonaną przed chwilą: jej numer do podświetlenia i czas HTTP+DOM zmierzony przez klienta.
   * @param {number} attemptNo - Numer próby z sesji zwrotu.
   * @param {number|null} roundTripMs - Zmierzony czas HTTP+DOM w ms lub brak pomiaru.
   * @param {number} [now=Date.now()] - Bieżący czas w ms (wstrzykiwany w testach).
   * @returns {void}
   */
  function markPendingAttempt(attemptNo, roundTripMs, now = Date.now()) {
    const ms = Number(roundTripMs);
    measured = { attemptNo, ms: roundTripMs !== null && Number.isFinite(ms) ? ms : null };
    pending = { attemptNo, until: now + FRESH_MS };
  }

  /**
   * Sprawdza, czy próba została wykonana przed chwilą i jej wiersz ma mignąć.
   * @param {number} attemptNo - Numer próby renderowanego wiersza.
   * @param {number} [now=Date.now()] - Bieżący czas w ms (wstrzykiwany w testach).
   * @returns {boolean} Prawda tylko w krótkim oknie po wrzucie wykonanym w tej karcie.
   */
  function isFreshAttempt(attemptNo, now = Date.now()) {
    return pending !== null && pending.attemptNo === attemptNo && now < pending.until;
  }

  /**
   * Zwraca czas HTTP+DOM zmierzony po stronie klienta dla danej próby.
   * @param {number} attemptNo - Numer próby z sesji zwrotu.
   * @returns {number|null} Czas w ms albo null, gdy próby nie wykonano w tej karcie (np. po F5).
   */
  function roundTripFor(attemptNo) {
    return measured !== null && measured.attemptNo === attemptNo ? measured.ms : null;
  }

  /**
   * Uruchamia animację wysunięcia bonu ze szczeliny; wołana tylko po faktycznym wystawieniu bonu.
   * @returns {void}
   */
  function playVoucherIssue() {
    const card = document.getElementById("issued-voucher-card");
    if (!card) return;
    card.classList.remove("is-printing");
    void card.offsetWidth;
    card.classList.add("is-printing");
    setTimeout(() => card.classList.remove("is-printing"), PRINT_MS);
  }

  return { setMachineState, clearScanning, markPendingAttempt, isFreshAttempt, roundTripFor, playVoucherIssue };
})();
