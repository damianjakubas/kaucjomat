/**
 * Logika przełącznika 3 widoków powłoki edukacyjnej KaucjaSim DEMO.
 * Działa w czystym vanilla JS bez zależności zewnętrznych i bez bundlerów.
 */

const VALID_VIEW_IDS = ["butelkomat", "kasa", "analityka"];
const DEFAULT_VIEW_ID = "butelkomat";
const errorMessagesBySource = {
  health: "",
  view: "",
  returns: "",
  returnsCards: "",
  returnsSession: "",
  returnsAction: "",
  returnsVoucher: "",
  checkoutContext: "",
  checkoutQuote: "",
  checkoutAction: "",
  checkoutStorage: "",
};

/**
 * Normalizuje identyfikator widoku (np. z hasha URL) do jednej z 3 obsługiwanych zakładek.
 * @param {string} rawViewId - Surowy identyfikator lub fragment po znaku '#'.
 * @returns {string} Poprawny identyfikator widoku powłoki DEMO.
 */
function resolveViewId(rawViewId) {
  const cleaned = String(rawViewId || "").replace(/^#/, "").trim().toLowerCase();
  return VALID_VIEW_IDS.includes(cleaned) ? cleaned : DEFAULT_VIEW_ID;
}

/**
 * Bezpiecznie parsuje odpowiedź JSON, zwracając null przy treściach niebędących JSON-em.
 * @param {Response} response - Obiekt odpowiedzi z funkcji fetch.
 * @returns {Promise<object|null>} Sparsowany obiekt JSON lub null w razie błędu formatu.
 */
async function readJsonSafely(response) {
  const contentType = (response.headers.get("content-type") || "").toLowerCase();
  if (!contentType.includes("application/json")) {
    return null;
  }
  try {
    return await response.json();
  } catch {
    return null;
  }
}

/**
 * Wyświetla lub ukrywa baner błędu komunikacji z API z rozdzieleniem źródeł (health/view/returns*).
 * @param {string} message - Treść błędu po polsku; pusty napis czyści dane źródło.
 * @param {"health"|"view"|"returns"|"returnsCards"|"returnsSession"|"returnsAction"|"returnsVoucher"} [source="view"] - Nazwa źródła zgłaszającego komunikat.
 * @returns {void}
 */
function renderErrorBanner(message, source = "view") {
  const banner = document.getElementById("error-banner");
  const messageNode = document.getElementById("error-banner-message");
  if (!banner || !messageNode) {
    return;
  }

  const key = Object.hasOwn(errorMessagesBySource, source) ? source : "view";
  errorMessagesBySource[key] = message ? String(message) : "";

  const activeMessages = Object.values(errorMessagesBySource).filter(Boolean);
  if (activeMessages.length === 0) {
    banner.hidden = true;
    messageNode.textContent = "";
    return;
  }

  messageNode.textContent = activeMessages.join(" | ");
  banner.hidden = false;
}

window.kaucjomatSetError = renderErrorBanner;

/**
 * Pobiera z backendu FastAPI metadane wybranego widoku i aktualizuje opis sekcji w DOM.
 * @param {string} viewId - Identyfikator widoku ('butelkomat' | 'kasa' | 'analityka').
 * @returns {Promise<void>} Obietnica kończąca się po zaktualizowaniu metadanych widoku lub banera błędu.
 */
async function fetchViewMetadata(viewId) {
  const safeViewId = resolveViewId(viewId);
  try {
    const response = await fetch(`/api/views/${encodeURIComponent(safeViewId)}`, {
      headers: { Accept: "application/json" },
    });
    const payload = await readJsonSafely(response);

    if (!response.ok) {
      const errorText = payload && payload.message
        ? `${payload.message} (${payload.error_code || response.status})`
        : `Nie udało się pobrać danych widoku (HTTP ${response.status}).`;
      renderErrorBanner(errorText, "view");
      return;
    }

    // Czyścimy wyłącznie błąd widoku, aby nie ukryć ewentualnej awarii /api/health.
    renderErrorBanner("", "view");
    if (!payload) {
      return;
    }

    const escapedId = typeof CSS !== "undefined" && typeof CSS.escape === "function"
      ? CSS.escape(safeViewId)
      : safeViewId;
    const titleNode = document.querySelector(`[data-view-title="${escapedId}"]`);
    const descNode = document.querySelector(`[data-view-description="${escapedId}"]`);
    const scopeNode = document.querySelector(`[data-view-scope="${escapedId}"]`);

    if (titleNode && payload.title) {
      titleNode.textContent = payload.title;
    }
    if (descNode && payload.description) {
      descNode.textContent = payload.description;
    }
    if (scopeNode && payload.planned_scope) {
      scopeNode.textContent = payload.planned_scope;
    }
  } catch (error) {
    const details = error instanceof Error ? error.message : String(error);
    renderErrorBanner(`Brak połączenia z lokalnym API DEMO: ${details}`, "view");
  }
}

/**
 * Przełącza aktywny widok synchronicznie w DOM (< 5 ms), aktualizuje hash URL i pobiera metadane.
 * @param {string} viewId - Identyfikator docelowego widoku.
 * @returns {void}
 */
function selectView(viewId) {
  const targetId = resolveViewId(viewId);
  const startTime = performance.now();

  // Natychmiastowa aktualizacja stanu zakładek i atrybutu hidden bez czekania na sieć.
  const tabs = document.querySelectorAll("[data-view-target]");
  tabs.forEach((tab) => {
    const isActive = tab.getAttribute("data-view-target") === targetId;
    tab.setAttribute("aria-selected", isActive ? "true" : "false");
    tab.classList.toggle("is-active", isActive);
  });

  const panels = document.querySelectorAll("[data-view-panel]");
  panels.forEach((panel) => {
    const isVisible = panel.getAttribute("data-view-panel") === targetId;
    panel.hidden = !isVisible;
  });

  const elapsedMs = Math.max(0.1, performance.now() - startTime).toFixed(2);
  const latencyNode = document.querySelector(`[data-view-latency="${targetId}"]`);
  if (latencyNode) {
    latencyNode.textContent = `Przełączanie lokalne: ${elapsedMs} ms (limit < 200 ms)`;
  }

  // Synchronizujemy hash adresu URL bez powodowania przewijania strony.
  if (window.location.hash !== `#${targetId}`) {
    window.history.replaceState(null, "", `#${targetId}`);
  }

  void fetchViewMetadata(targetId);
  window.dispatchEvent(new CustomEvent("kaucjomat:view-selected", { detail: { viewId: targetId } }));
}

/**
 * Odpytuje endpoint `/api/health` i aktualizuje wskaźnik statusu lokalnego backendu DEMO.
 * @returns {Promise<void>} Obietnica kończąca aktualizację paska zdrowia systemu.
 */
async function refreshHealthStatus() {
  const pill = document.getElementById("health-status");
  const textNode = document.getElementById("health-status-text");
  const summaryNode = document.getElementById("api-meta-summary");

  try {
    const response = await fetch("/api/health", {
      headers: { Accept: "application/json" },
    });
    const health = await readJsonSafely(response);
    if (!response.ok || !health) {
      throw new Error(`HTTP ${response.status}`);
    }

    renderErrorBanner("", "health");
    if (pill) {
      pill.classList.remove("is-error");
    }
    if (textNode) {
      const modeLabel = health.mode || "DEMO";
      const viewsCount = Number.isInteger(health.views_count) ? health.views_count : 3;
      textNode.textContent = `Backend lokalny: OK · Tryb ${modeLabel} (${viewsCount} widoki)`;
    }
    if (summaryNode) {
      const appName = health.app_name || "KaucjaSim";
      const version = health.version || "0.1.0";
      const modeLabel = health.mode || "DEMO";
      summaryNode.textContent = `${appName} v${version} · Tryb ${modeLabel}`;
    }
  } catch (error) {
    const details = error instanceof Error ? error.message : String(error);
    if (pill) {
      pill.classList.add("is-error");
    }
    if (textNode) {
      textNode.textContent = "Backend lokalny: niedostępny";
    }
    renderErrorBanner(`Nie udało się odczytać /api/health: ${details}`, "health");
  }
}

/**
 * Inicjalizuje powłokę aplikacji: podpina zdarzenia zakładek, obsługę zmiany hasha oraz startowy stan API.
 * @returns {void}
 */
function initAppShell() {
  const tabs = document.querySelectorAll("[data-view-target]");
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      const targetId = tab.getAttribute("data-view-target") || DEFAULT_VIEW_ID;
      selectView(targetId);
    });
  });

  window.addEventListener("hashchange", () => {
    selectView(window.location.hash);
  });

  const initialView = resolveViewId(window.location.hash);
  selectView(initialView);
  void refreshHealthStatus();
}

document.addEventListener("DOMContentLoaded", initAppShell);
