/**
 * Kontroler komunikacji API i obsługi zdarzeń stanowiska Butelkomatu DEMO.
 */

const returnDemo = window.KaucjomatDemo;

/**
 * Zgłasza lub czyści komunikat błędu dla wskazanego źródła we wspólnym banerze powłoki.
 * @param {string} message - Treść błędu po polsku; pusty napis usuwa błąd dla danego źródła.
 * @param {"returnsCards"|"returnsSession"|"returnsAction"|"returnsVoucher"} [source="returnsAction"] - Klucz źródła błędu.
 * @returns {void}
 */
function reportReturnsError(message, source = "returnsAction") {
  if (typeof window.kaucjomatSetError === "function") window.kaucjomatSetError(message, source);
}

/**
 * Przełącza stan blokady przycisków wrzutu, wystawienia bonu i resetu na czas trwania żądania API.
 * @param {boolean} isBusy - Czy operacja mutująca stan DEMO jest w toku.
 * @returns {void}
 */
function setMachineControlsBusy(isBusy) {
  const resetBtn = document.getElementById("reset-demo-btn");
  if (resetBtn) resetBtn.disabled = isBusy;
  const issueBtn = document.getElementById("issue-voucher-btn");
  if (issueBtn) issueBtn.disabled = isBusy ? true : issueBtn.dataset.canIssue !== "true";
  document.querySelectorAll(".btn-deposit-card").forEach((btn) => {
    btn.disabled = isBusy;
  });
}

/**
 * Wykonuje żądanie JSON do API zwrotów i zgłasza czytelny wyjątek przy błędzie HTTP.
 * @param {string} url - Adres endpointu API.
 * @param {RequestInit} options - Opcje wywołania fetch.
 * @returns {Promise<object>} Sparsowany obiekt odpowiedzi JSON.
 */
async function fetchReturnJson(url, options = {}) {
  const headers = { Accept: "application/json", ...(options.headers || {}) };
  const response = await fetch(url, { ...options, headers });
  const contentType = (response.headers.get("content-type") || "").toLowerCase();
  const payload = contentType.includes("application/json") ? await response.json().catch(() => null) : null;
  if (!response.ok || !payload) {
    throw new Error((payload && payload.message) || `HTTP ${response.status}`);
  }
  return payload;
}

/**
 * Pobiera 8 kart testowych z `/api/returns/cards` i renderuje półkę opakowań.
 * @returns {Promise<void>} Obietnica kończąca się po wyrenderowaniu półki kart.
 */
async function loadReturnCards() {
  const shelf = document.getElementById("package-cards-shelf");
  if (!shelf || !window.KaucjomatReturnView) return;
  const ticket = returnDemo.read("returnsCards");
  try {
    const payload = await fetchReturnJson("/api/returns/cards");
    if (!returnDemo.current(ticket)) return;
    if (!Array.isArray(payload.cards)) throw new Error("Niepoprawna lista kart.");
    shelf.textContent = "";
    payload.cards.forEach((card) => {
      const cardNode = window.KaucjomatReturnView.buildPackageCardElement(
        card,
        (selectedCardId) => { void submitPackageDeposit(selectedCardId); },
      );
      shelf.appendChild(cardNode);
    });
    setMachineControlsBusy(returnDemo.busy);
    reportReturnsError("", "returnsCards");
  } catch (error) {
    if (!returnDemo.current(ticket)) return;
    reportReturnsError(
      `Nie udało się wczytać kart testowych: ${error instanceof Error ? error.message : String(error)}`,
      "returnsCards",
    );
  }
}

/**
 * Pobiera aktualny stan sesji zwrotu z `/api/returns/session` i odtwarza go w interfejsie.
 * @returns {Promise<void>} Obietnica kończąca się po odtworzeniu liczników i historii.
 */
async function loadReturnSession() {
  if (!window.KaucjomatReturnView) return;
  const ticket = returnDemo.read("returnsSession");
  try {
    const session = await fetchReturnJson("/api/returns/session");
    // Odrzucamy spóźnioną odpowiedź startową, jeśli użytkownik zdążył już zmutować stan.
    if (!returnDemo.current(ticket)) return;
    window.KaucjomatReturnView.renderSessionState(session);
    // Najnowsza próba z historii znajduje się pod indeksem 0 (posortowane malejąco od ostatniej).
    if (Array.isArray(session.attempts) && session.attempts.length > 0) {
      const latest = session.attempts[0];
      window.KaucjomatReturnView.renderScannerDecision(latest, Number(latest.elapsed_ms || 0));
    }
    else window.KaucjomatReturnView.resetScannerBoxView();
    reportReturnsError("", "returnsSession");
  } catch (error) {
    if (!returnDemo.current(ticket)) return;
    reportReturnsError(
      `Nie udało się odczytać stanu sesji DEMO: ${error instanceof Error ? error.message : String(error)}`,
      "returnsSession",
    );
  }
}

/**
 * Wysyła żądanie wrzutu wskazanej karty do `POST /api/returns/deposit` i aktualizuje ekran skanera.
 * @param {string} cardId - Identyfikator karty z półki testowej.
 * @returns {Promise<void>} Obietnica kończąca się po zaktualizowaniu decyzji i sesji.
 */
async function submitPackageDeposit(cardId) {
  if (!window.KaucjomatReturnView || !returnDemo.begin("deposit")) return;
  setMachineControlsBusy(true);
  const startTime = performance.now();
  try {
    const payload = await fetchReturnJson("/api/returns/deposit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ card_id: cardId }),
    });
    if (!payload.decision || !payload.session) throw new Error("Brak decyzji skanera.");
    window.KaucjomatReturnView.renderScannerDecision(payload.decision, performance.now() - startTime);
    window.KaucjomatReturnView.renderSessionState(payload.session);
    reportReturnsError("", "returnsAction");
  } catch (error) {
    reportReturnsError(
      `Błąd podczas walidacji wrzutu: ${error instanceof Error ? error.message : String(error)}`,
      "returnsAction",
    );
  } finally {
    returnDemo.end("deposit");
    setMachineControlsBusy(false);
  }
}

/**
 * Pobiera listę bonów z `/api/returns/vouchers` i odtwarza na ekranie ostatni bon użytkownika (po F5).
 * @returns {Promise<void>} Obietnica kończąca się po wyrenderowaniu lub ukryciu karty bonu DEMO.
 */
async function loadLatestIssuedVoucher() {
  if (!window.KaucjomatReturnView) return;
  const ticket = returnDemo.read("returnsVoucher");
  try {
    const payload = await fetchReturnJson("/api/returns/vouchers");
    if (!returnDemo.current(ticket)) return;
    const vouchers = Array.isArray(payload.vouchers) ? payload.vouchers : [];
    const latestUserVoucher = vouchers.find((item) => item && item.is_test_seed === false) || null;
    window.KaucjomatReturnView.renderIssuedVoucher(latestUserVoucher);
    reportReturnsError("", "returnsVoucher");
  } catch (error) {
    if (!returnDemo.current(ticket)) return;
    reportReturnsError(
      `Nie udało się odtworzyć listy bonów DEMO: ${error instanceof Error ? error.message : String(error)}`,
      "returnsVoucher",
    );
  }
}

/**
 * Zamyka bieżącą sesję zwrotu przez `POST /api/returns/voucher` i wyświetla wygenerowany bon DEMO.
 * @returns {Promise<void>} Obietnica kończąca się po aktualizacji sesji i karty bonu.
 */
async function issueSessionVoucher() {
  if (!window.KaucjomatReturnView || !returnDemo.begin("issue")) return;
  const issueBtn = document.getElementById("issue-voucher-btn");
  const currentSessionId = issueBtn ? issueBtn.dataset.sessionId || "" : "";
  setMachineControlsBusy(true);
  try {
    const payload = await fetchReturnJson("/api/returns/voucher", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(currentSessionId ? { session_id: currentSessionId } : {}),
    });
    if (!payload.voucher || !payload.session) throw new Error("Brak danych bonu w odpowiedzi API.");
    window.KaucjomatReturnView.renderSessionState(payload.session);
    window.KaucjomatReturnView.renderIssuedVoucher(payload.voucher);
    window.KaucjomatReturnView.resetScannerBoxView(
      `WYSTAWIONO BON DEMO (${payload.voucher.voucher_code})`,
      `Wystawiono bon na kwotę ${payload.voucher.amount_formatted}. Rozpoczęto nową pustą sesję zwrotu z zachowaniem rejestru ID.`,
      "Możesz wydrukować bon / zapisać PDF albo wrzucić kolejne opakowania.",
    );
    reportReturnsError("", "returnsAction");
    reportReturnsError("", "returnsVoucher");
  } catch (error) {
    reportReturnsError(
      `Nie udało się wystawić bonu DEMO: ${error instanceof Error ? error.message : String(error)}`,
      "returnsAction",
    );
  } finally {
    returnDemo.end("issue");
    setMachineControlsBusy(false);
  }
}

/**
 * Wywołuje `POST /api/returns/reset`, zerując rejestr egzemplarzy oraz licznik bieżącej sesji DEMO.
 * @returns {Promise<void>} Obietnica kończąca się po wyczyszczeniu widoku i sesji.
 */
async function resetReturnDemoState() {
  if (!window.KaucjomatReturnView || !returnDemo.begin("reset")) return;
  let didReset = false;
  setMachineControlsBusy(true);
  try {
    const payload = await fetchReturnJson("/api/returns/reset", { method: "POST" });
    if (!payload.session) throw new Error("Brak sesji w odpowiedzi resetu.");
    didReset = true;
    window.KaucjomatReturnView.renderSessionState(payload.session);
    window.KaucjomatReturnView.renderIssuedVoucher(null);
    window.KaucjomatReturnView.resetScannerBoxView();
    reportReturnsError("", "returnsAction");
    reportReturnsError("", "returnsVoucher");
  } catch (error) {
    reportReturnsError(
      `Nie udało się zresetować stanu DEMO: ${error instanceof Error ? error.message : String(error)}`,
      "returnsAction",
    );
  } finally {
    returnDemo.end(didReset ? "reset" : "refresh");
    setMachineControlsBusy(false);
  }
}

/**
 * Inicjalizuje strefę Drag & Drop wlotu butelkomatu, przyciski bonu/druku/resetu oraz startowe ładowanie danych.
 * @returns {void}
 */
function initReturnMachine() {
  const dropzone = document.getElementById("deposit-dropzone");
  const resetBtn = document.getElementById("reset-demo-btn");
  const issueBtn = document.getElementById("issue-voucher-btn");
  const printBtn = document.getElementById("print-voucher-btn");
  if (!dropzone) return;

  dropzone.addEventListener("dragover", (event) => {
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
    dropzone.classList.add("is-dragover");
  });
  dropzone.addEventListener("dragleave", () => dropzone.classList.remove("is-dragover"));
  dropzone.addEventListener("drop", (event) => {
    event.preventDefault();
    dropzone.classList.remove("is-dragover");
    const cardId = event.dataTransfer ? event.dataTransfer.getData("text/plain").trim() : "";
    if (cardId) void submitPackageDeposit(cardId);
  });
  if (issueBtn) issueBtn.addEventListener("click", () => { void issueSessionVoucher(); });
  if (printBtn) printBtn.addEventListener("click", () => { window.print(); });
  if (resetBtn) resetBtn.addEventListener("click", () => { void resetReturnDemoState(); });
  window.addEventListener("kaucjomat:state-changed", (event) => {
    setMachineControlsBusy(returnDemo.busy);
    if (event.detail.phase === "end") {
      void loadReturnSession();
      void loadLatestIssuedVoucher();
      if (!document.querySelector(".btn-deposit-card")) void loadReturnCards();
    }
  });
  window.addEventListener("kaucjomat:view-selected", (event) => {
    if (event.detail.viewId === "butelkomat" && !returnDemo.busy) {
      void loadReturnSession();
      void loadLatestIssuedVoucher();
    }
  });
  void loadReturnCards();
  void loadReturnSession();
  void loadLatestIssuedVoucher();
}

document.addEventListener("DOMContentLoaded", initReturnMachine);
