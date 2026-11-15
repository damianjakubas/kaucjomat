/**
 * Logika przełącznika 3 widoków powłoki edukacyjnej KaucjaSim DEMO.
 * Działa w czystym vanilla JS bez zależności zewnętrznych i bez bundlerów.
 */

const VALID_VIEW_IDS = ["butelkomat", "kasa", "analityka"];
const DEFAULT_VIEW_ID = "butelkomat";

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
 * Wyświetla lub ukrywa czytelny baner błędu komunikacji z lokalnym API DEMO.
 * @param {string} message - Treść błędu po polsku; pusty napis ukrywa baner.
 * @returns {void}
 */
function renderErrorBanner(message) {
  const banner = document.getElementById("error-banner");
  const messageNode = document.getElementById("error-banner-message");
  if (!banner || !messageNode) {
    return;
  }

  if (!message) {
    banner.hidden = true;
    messageNode.textContent = "";
    return;
  }

  messageNode.textContent = message;
  banner.hidden = false;
}

/**
 * Pobiera z backendu FastAPI metadane wybranego widoku i aktualizuje opis sekcji w DOM.
 * @param {string} viewId - Identyfikator widoku ('butelkomat' | 'kasa' | 'analityka').
 * @returns {Promise<void>} Obietnica kończąca się po zaktualizowaniu metadanych widoku lub banera błędu.
 */
async function fetchViewMetadata(viewId) {
  try {
    const response = await fetch(`/api/views/${encodeURIComponent(viewId)}`, {
      headers: { Accept: "application/json" },
    });
    const payload = await response.json();

    if (!response.ok) {
      const errorText = payload && payload.message
        ? `${payload.message} (${payload.error_code || response.status})`
        : `Nie udało się pobrać danych widoku (${response.status}).`;
      renderErrorBanner(errorText);
      return;
    }

    // Czyścimy poprzedni błąd po poprawnym odświeżeniu danych z backendu.
    renderErrorBanner("");

    const titleNode = document.querySelector(`[data-view-title="${viewId}"]`);
    const descNode = document.querySelector(`[data-view-description="${viewId}"]`);
    const scopeNode = document.querySelector(`[data-view-scope="${viewId}"]`);

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
    renderErrorBanner(`Brak połączenia z lokalnym API DEMO: ${details}`);
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
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const health = await response.json();
    if (pill) {
      pill.classList.remove("is-error");
    }
    if (textNode) {
      textNode.textContent = `Backend lokalny: OK · Tryb ${health.mode} (${health.views_count} widoki)`;
    }
    if (summaryNode) {
      summaryNode.textContent = `${health.app_name} v${health.version} · Tryb ${health.mode}`;
    }
  } catch (error) {
    const details = error instanceof Error ? error.message : String(error);
    if (pill) {
      pill.classList.add("is-error");
    }
    if (textNode) {
      textNode.textContent = "Backend lokalny: niedostępny";
    }
    renderErrorBanner(`Nie udało się odczytać /api/health: ${details}`);
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
