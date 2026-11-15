/**
 * Logika stanowiska Butelkomatu DEMO (Drag & Drop, przycisk "Wrzuć", podsumowanie sesji).
 * Czysty vanilla JS aktualizujący DOM wyłącznie bezpiecznym textContent / createElement.
 */

const STATUS_CLASS_MAP = { ACCEPTED: "is-accepted", REDIRECT_TO_CASHIER: "is-redirected", REJECTED: "is-rejected" };
const GROUP_LABEL_MAP = { valid: "Kaucja w automacie", glass: "Szkło do kasy", invalid: "Przypadek odrzucenia" };

/**
 * Zgłasza lub czyści komunikat błędu dla źródła "returns" we wspólnym banerze powłoki.
 * @param {string} message - Treść błędu po polsku; pusty napis usuwa błąd.
 * @returns {void}
 */
function reportReturnsError(message) {
  if (typeof window.kaucjomatSetError === "function") window.kaucjomatSetError(message, "returns");
}

/**
 * Wykonuje żądanie JSON do API zwrotów i zgłasza ewentualny błąd w banerze powłoki.
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
 * Formatuje kwotę w groszach jako polski napis z dopiskiem zł (np. "0,50 zł").
 * @param {number} grosze - Kwota w groszach.
 * @returns {string} Sformatowana kwota w PLN.
 */
function formatPlnFromGrosze(grosze) {
  const numeric = Number.isFinite(Number(grosze)) ? Number(grosze) : 0;
  return `${(numeric / 100).toFixed(2).replace(".", ",")} zł`;
}

/**
 * Tworzy czytelną etykietę nagłówka decyzji skanera na podstawie statusu walidacji.
 * @param {object} decision - Obiekt decyzji lub rekordu próby z API zwrotów.
 * @returns {string} Polska etykieta statusu decyzji wraz z kwotą kaucji DEMO.
 */
function formatDecisionHeadline(decision) {
  if (decision.status === "ACCEPTED") {
    return `AKCEPTACJA +${decision.deposit_formatted || formatPlnFromGrosze(decision.deposit_grosze)}`;
  }
  if (decision.status === "REDIRECT_TO_CASHIER") {
    const val = decision.cashier_suggested_formatted || formatPlnFromGrosze(decision.cashier_suggested_grosze);
    return `SKIEROWANO DO KASY (+${val} w kasie)`;
  }
  return `ODRZUCONO (${decision.reason_code || "BŁĄD"})`;
}

/**
 * Aktualizuje ekran decyzji skanera oraz wyświetla szczegóły parsowania re i czas odpowiedzi.
 * @param {object} decision - Decyzja walidacji z backendu FastAPI.
 * @param {number} roundTripMs - Zmierzone po stronie przeglądarki opóźnienie rundy HTTP w ms.
 * @returns {void}
 */
function renderScannerDecision(decision, roundTripMs) {
  const box = document.getElementById("scanner-result-box");
  const titleNode = document.getElementById("scanner-status-title");
  const msgNode = document.getElementById("scanner-status-message");
  const metaNode = document.getElementById("scanner-status-meta");
  if (!box || !titleNode || !msgNode || !metaNode) return;

  box.classList.remove("is-accepted", "is-redirected", "is-rejected");
  const statusClass = STATUS_CLASS_MAP[decision.status];
  if (statusClass) box.classList.add(statusClass);

  titleNode.textContent = formatDecisionHeadline(decision);
  msgNode.textContent = decision.message || "Zakończono walidację opakowania.";
  const eanLabel = decision.ean || "brak poprawnego EAN";
  const instanceLabel = decision.instance_id || "brak ID egzemplarza";
  const serverMs = Number(decision.elapsed_ms || 0).toFixed(2);
  const clientMs = Math.max(0.1, roundTripMs).toFixed(2);
  metaNode.textContent = `EAN: ${eanLabel} | ID egzemplarza: ${instanceLabel} | Czas skanera: ${serverMs} ms (HTTP+DOM: ${clientMs} ms, limit < 200 ms)`;
}

/**
 * Przywraca ekran skanera do stanu początkowego po wyzerowaniu stanu DEMO.
 * @returns {void}
 */
function resetScannerBoxView() {
  const box = document.getElementById("scanner-result-box");
  const titleNode = document.getElementById("scanner-status-title");
  const msgNode = document.getElementById("scanner-status-message");
  const metaNode = document.getElementById("scanner-status-meta");
  if (!box || !titleNode || !msgNode || !metaNode) return;

  box.classList.remove("is-accepted", "is-redirected", "is-rejected");
  titleNode.textContent = "GOTOWY DO SKANU (STAN DEMO ZRESETOWANY)";
  msgNode.textContent = "Rejestr egzemplarzy i licznik bieżącej sesji zostały wyzerowane.";
  metaNode.textContent = "Możesz ponownie wrzucić dowolną kartę z półki testowej.";
}

/**
 * Renderuje liczniki sesji zwrotów oraz listę ostatnich prób w bieżącej sesji DEMO.
 * @param {object} session - Migawka sesji zwrócona przez API `/api/returns/session` lub `/deposit`.
 * @returns {void}
 */
function renderSessionState(session) {
  const setTxt = (id, val) => { const n = document.getElementById(id); if (n) n.textContent = val; };
  setTxt("session-total-amount", session.total_formatted || "0,00 zł");
  setTxt("session-accepted-count", String(session.accepted_count ?? 0));
  setTxt("session-redirected-count", String(session.redirected_glass_count ?? 0));
  setTxt("session-rejected-count", String(session.rejected_count ?? 0));
  setTxt("session-registry-count", String(session.returned_registry_size ?? 0));
  setTxt(
    "voucher-next-step-hint",
    session.can_issue_voucher
      ? `Zebrano ${session.total_formatted} kaucji DEMO — gotowe do wystawienia bonu ważnego 100 dni w kolejnym kroku (S-02).`
      : "Wystawienie bonu DEMO (ważnego 100 dni) dla zebranej kwoty realizuje kolejny krok systemu (widok Kasy / Bonu).",
  );

  const listNode = document.getElementById("session-attempts-list");
  if (!listNode) return;
  // Czyścimy listę i budujemy wiersze bezpiecznie przez createElement (ochrona przed XSS).
  listNode.textContent = "";
  const attempts = Array.isArray(session.attempts) ? [...session.attempts].reverse() : [];
  if (attempts.length === 0) {
    const emptyItem = document.createElement("li");
    emptyItem.className = "attempt-empty";
    emptyItem.textContent = "Brak wrzutów w tej sesji DEMO.";
    listNode.appendChild(emptyItem);
    return;
  }

  attempts.forEach((attempt) => {
    const item = document.createElement("li");
    item.className = `attempt-item ${STATUS_CLASS_MAP[attempt.status] || ""}`.trim();
    const header = document.createElement("strong");
    const prefix = `#${attempt.attempt_no} ${attempt.title}`;
    if (attempt.status === "ACCEPTED") header.textContent = `${prefix} — AKCEPTACJA (+${attempt.deposit_grosze} gr)`;
    else if (attempt.status === "REDIRECT_TO_CASHIER") header.textContent = `${prefix} — DO KASY (${attempt.cashier_suggested_grosze} gr)`;
    else header.textContent = `${prefix} — ODRZUCONO (${attempt.reason_code || "BŁĄD"})`;
    const details = document.createElement("div");
    details.textContent = attempt.message || "";
    item.append(header, details);
    listNode.appendChild(item);
  });
}

/**
 * Buduje pojedynczy element DOM karty opakowania na półkę testową z obsługą Drag & Drop.
 * @param {object} card - Metadane karty testowej z `/api/returns/cards`.
 * @returns {HTMLElement} Gotowy element `<article>` karty opakowania.
 */
function buildPackageCardElement(card) {
  const article = document.createElement("article");
  article.className = `package-card package-card-group-${card.group || "valid"}`;
  article.setAttribute("draggable", "true");
  article.dataset.cardId = card.card_id;
  article.addEventListener("dragstart", (event) => {
    if (event.dataTransfer) {
      event.dataTransfer.setData("text/plain", card.card_id);
      event.dataTransfer.effectAllowed = "copy";
    }
  });

  const head = document.createElement("div");
  head.className = "package-card-head";
  const badge = document.createElement("span");
  badge.className = "package-card-badge";
  badge.textContent = card.badge || "DEMO";
  const groupLabel = document.createElement("small");
  groupLabel.textContent = GROUP_LABEL_MAP[card.group] || "Karta testowa";
  head.append(badge, groupLabel);

  const title = document.createElement("h4");
  title.className = "package-card-title";
  title.textContent = card.title || card.card_id;
  const subtitle = document.createElement("p");
  subtitle.className = "package-card-subtitle";
  subtitle.textContent = `${card.subtitle || ""} · ${card.expected_hint || ""}`;
  const code = document.createElement("p");
  code.className = "package-card-code";
  code.textContent = card.package_code || "";
  const button = document.createElement("button");
  button.type = "button";
  button.className = "btn-deposit-card";
  button.textContent = "Wrzuć do automatu";
  button.addEventListener("click", () => { void submitPackageDeposit(card.card_id); });

  article.append(head, title, subtitle, code, button);
  return article;
}

/**
 * Pobiera 8 kart testowych z `/api/returns/cards` i renderuje półkę opakowań.
 * @returns {Promise<void>} Obietnica kończąca się po wyrenderowaniu półki kart.
 */
async function loadReturnCards() {
  const shelf = document.getElementById("package-cards-shelf");
  if (!shelf) return;
  try {
    const payload = await fetchReturnJson("/api/returns/cards");
    if (!Array.isArray(payload.cards)) throw new Error("Niepoprawna lista kart.");
    shelf.textContent = "";
    payload.cards.forEach((card) => shelf.appendChild(buildPackageCardElement(card)));
    reportReturnsError("");
  } catch (error) {
    reportReturnsError(`Nie udało się wczytać kart testowych: ${error instanceof Error ? error.message : String(error)}`);
  }
}

/**
 * Pobiera aktualny stan sesji zwrotu z `/api/returns/session` i odtwarza go w interfejsie.
 * @returns {Promise<void>} Obietnica kończąca się po odtworzeniu liczników i historii.
 */
async function loadReturnSession() {
  try {
    const session = await fetchReturnJson("/api/returns/session");
    renderSessionState(session);
    if (Array.isArray(session.attempts) && session.attempts.length > 0) {
      const latest = session.attempts[session.attempts.length - 1];
      renderScannerDecision(latest, Number(latest.elapsed_ms || 0));
    }
    reportReturnsError("");
  } catch (error) {
    reportReturnsError(`Nie udało się odczytać stanu sesji DEMO: ${error instanceof Error ? error.message : String(error)}`);
  }
}

/**
 * Wysyła żądanie wrzutu wskazanej karty do `POST /api/returns/deposit` i aktualizuje ekran skanera.
 * @param {string} cardId - Identyfikator karty z półki testowej.
 * @returns {Promise<void>} Obietnica kończąca się po zaktualizowaniu decyzji i sesji.
 */
async function submitPackageDeposit(cardId) {
  const startTime = performance.now();
  try {
    const payload = await fetchReturnJson("/api/returns/deposit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ card_id: cardId }),
    });
    if (!payload.decision || !payload.session) throw new Error("Brak decyzji skanera.");
    renderScannerDecision(payload.decision, performance.now() - startTime);
    renderSessionState(payload.session);
    reportReturnsError("");
  } catch (error) {
    reportReturnsError(`Błąd podczas walidacji wrzutu: ${error instanceof Error ? error.message : String(error)}`);
  }
}

/**
 * Wywołuje `POST /api/returns/reset`, zerując rejestr egzemplarzy oraz licznik bieżącej sesji DEMO.
 * @returns {Promise<void>} Obietnica kończąca się po wyczyszczeniu widoku i sesji.
 */
async function resetReturnDemoState() {
  try {
    const payload = await fetchReturnJson("/api/returns/reset", { method: "POST" });
    if (!payload.session) throw new Error("Brak sesji w odpowiedzi resetu.");
    renderSessionState(payload.session);
    resetScannerBoxView();
    reportReturnsError("");
  } catch (error) {
    reportReturnsError(`Nie udało się zresetować stanu DEMO: ${error instanceof Error ? error.message : String(error)}`);
  }
}

/**
 * Inicjalizuje strefę Drag & Drop wlotu butelkomatu, przycisk resetu oraz startowe ładowanie danych.
 * @returns {void}
 */
function initReturnMachine() {
  const dropzone = document.getElementById("deposit-dropzone");
  const resetBtn = document.getElementById("reset-demo-btn");
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
  if (resetBtn) resetBtn.addEventListener("click", () => { void resetReturnDemoState(); });
  void loadReturnCards();
  void loadReturnSession();
}

document.addEventListener("DOMContentLoaded", initReturnMachine);
