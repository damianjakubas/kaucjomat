/** Kontroler widoku Analityka: kontekst, referencja, zadania w tle i odpytywanie statusu. */
(() => {
  const contract = window.KaucjomatAnalyticsContract;
  const view = window.KaucjomatAnalyticsView;
  const POLL_MS = 1000;
  const sequence = { context: 0, reference: 0, job: 0 };
  const inflight = { context: false, reference: false };
  let context = null;
  let reference = null;
  let job = null;
  let started = false;
  let locked = false;
  let liveBenchmark = false;
  let timer = null;
  const node = (id) => document.getElementById(id);
  const error = (message, source) => window.kaucjomatSetError(message, source);
  /** Nadaje odczytowi numer; nowszy odczyt tego samego rodzaju unieważnia starsze odpowiedzi. */
  const ticket = (key) => { sequence[key] += 1; return sequence[key]; };
  const fresh = (key, value) => sequence[key] === value;

  /** Pobiera JSON bez ukrywania błędu lub niepełnej odpowiedzi serwera. */
  async function fetchJson(url, body) {
    const response = await fetch(url, {
      headers: { Accept: "application/json", ...(body ? { "Content-Type": "application/json" } : {}) },
      ...(body ? { method: "POST", body: JSON.stringify(body) } : {}),
    });
    return { response, payload: await readJsonSafely(response) };
  }

  /** Odświeża blokady: sterowanie działa dopiero po poprawnym kontekście i poza trwającym zadaniem. */
  function refresh() {
    view.controls(locked, context !== null);
  }

  /** Zwraca wybrany w liście preset z kontekstu. */
  function selectedPreset() {
    const id = node("analytics-preset").value;
    return context ? context.presets.find((item) => item.preset_id === id) || null : null;
  }

  /** Pokazuje wyniki referencyjne z wykresem (domyślny stan widoku) oraz komunikat dla bieżącej maszyny. */
  function showReference() {
    if (!reference) return;
    liveBenchmark = false;
    view.benchmark(reference.benchmark, "Wyniki referencyjne");
    view.chart(reference.chart_url, "Wykres referencyjny: czasy sekwencyjnie, na wątkach i na procesach");
    view.singleCore(view.pickWarning(context, null));
  }

  /** Pobiera środowisko maszyny i presety; błąd zostawia sterowanie zablokowane. */
  async function loadContext() {
    if (inflight.context) return;
    inflight.context = true;
    const current = ticket("context");
    try {
      const { response, payload } = await fetchJson("/api/analytics/context");
      if (!fresh("context", current)) return;
      if (!response.ok || !contract.contextValid(payload)) throw new Error(payload?.message || "Niepełny kontekst analityki.");
      context = payload;
      view.environment(payload);
      view.presets(payload.presets);
      view.presetHint(selectedPreset());
      view.singleCore(view.pickWarning(payload, liveBenchmark ? job?.result : null));
      if (!locked) view.status("Gotowe: wybierz preset i uruchom zadanie.");
      error("", "analyticsContext");
    } catch (failure) {
      if (fresh("context", current)) error(`Nie udało się pobrać kontekstu analityki: ${failure.message}`, "analyticsContext");
    } finally {
      inflight.context = false;
      refresh();
    }
  }

  /** Pobiera zapisane wyniki referencyjne i pokazuje je, o ile nie ma jeszcze wyniku na żywo. */
  async function loadReference() {
    if (inflight.reference) return;
    inflight.reference = true;
    const current = ticket("reference");
    try {
      const { response, payload } = await fetchJson("/api/analytics/reference");
      if (!fresh("reference", current)) return;
      if (!response.ok || !contract.referenceValid(payload)) throw new Error(payload?.message || "Niepełne wyniki referencyjne.");
      reference = payload;
      error("", "analyticsReference");
      if (!liveBenchmark) showReference();
    } catch (failure) {
      if (fresh("reference", current)) error(`Nie udało się pobrać wyników referencyjnych: ${failure.message}`, "analyticsReference");
    } finally {
      inflight.reference = false;
    }
  }

  /** Pokazuje wynik udanego zadania właściwym widokiem: zbiór, karty etapów albo tabela z wykresem. */
  function renderResult(snapshot) {
    const result = snapshot.result;
    if (snapshot.kind === "generate") view.dataset(result);
    if (snapshot.kind === "analysis") view.stages(result);
    if (snapshot.kind === "benchmark") {
      liveBenchmark = true;
      view.benchmark(result, "Wynik na żywo");
      view.chart(view.chartUrl(snapshot), "Wykres z ostatniego benchmarku: czasy sekwencyjnie, na wątkach i na procesach");
    }
    view.singleCore(view.pickWarning(context, result));
  }

  /** Kończy śledzenie zadania: zwalnia przyciski i zatrzymuje odpytywanie. */
  function finish() {
    locked = false;
    if (timer !== null) clearTimeout(timer);
    timer = null;
    refresh();
  }

  /** Reaguje na migawkę: trwające zadanie blokuje UI, zakończone pokazuje wynik lub błąd. */
  function handleSnapshot(snapshot) {
    if (snapshot.status === "running") {
      job = snapshot;
      locked = true;
      view.status(view.statusText(snapshot), snapshot);
      refresh();
      timer = setTimeout(poll, POLL_MS);
      return;
    }
    if (!locked) return; // Po odświeżeniu strony dołączamy tylko do zadania, które jeszcze trwa.
    if (snapshot.status === "idle") {
      view.status("Zadanie zostało przerwane (np. restart serwera). Uruchom je ponownie.");
    } else {
      job = snapshot;
      view.status(view.statusText(snapshot), snapshot);
      if (snapshot.status === "succeeded") renderResult(snapshot);
      else error(`${view.statusText(snapshot)} (${snapshot.error_code})`, "analyticsJob");
    }
    finish();
  }

  /** Odpytuje bieżące zadanie; spóźnione odpowiedzi są pomijane po numerze odczytu. */
  async function poll() {
    timer = null;
    const current = ticket("job");
    try {
      const { response, payload } = await fetchJson("/api/analytics/jobs/current");
      if (!fresh("job", current)) return;
      if (!response.ok || !contract.jobValid(payload)) throw new Error(payload?.message || "Niepełny status zadania.");
      error("", "analyticsJob");
      handleSnapshot(payload);
    } catch (failure) {
      if (!fresh("job", current)) return;
      error(`Nie udało się odczytać statusu zadania: ${failure.message}`, "analyticsJob");
      if (locked) timer = setTimeout(poll, POLL_MS); // Serwer mógł tylko chwilowo nie odpowiadać.
    }
  }

  /** Startuje zadanie; sterowanie blokuje się od razu, więc podwójne kliknięcie nie uruchomi drugiego. */
  async function startJob(kind) {
    if (locked || context === null) return;
    locked = true;
    refresh();
    error("", "analyticsJob");
    ticket("job");
    try {
      const { response, payload } = await fetchJson("/api/analytics/jobs", { kind, preset: node("analytics-preset").value });
      if (response.status === 409) {
        view.status("Inne zadanie analityczne już trwa — dołączam do niego.");
        await poll();
        return;
      }
      if (!response.ok || !contract.jobValid(payload) || payload.status !== "running") {
        throw new Error(payload?.message || "Niepełna odpowiedź startu zadania.");
      }
      handleSnapshot(payload);
    } catch (failure) {
      error(`Nie udało się uruchomić zadania: ${failure.message}`, "analyticsJob");
      finish();
    }
  }

  /** Leniwie ładuje dane przy pierwszym wejściu w zakładkę i dołącza do trwającego zadania. */
  function activate() {
    const first = !started;
    started = true;
    if (context === null) void loadContext();
    if (reference === null) void loadReference();
    if (first) void poll();
  }

  /** Podpina zdarzenia sterowania: start zadań, referencja i opis wybranego presetu. */
  function bind() {
    document.querySelectorAll("[data-analytics-kind]").forEach((button) => {
      button.addEventListener("click", () => void startJob(button.dataset.analyticsKind));
    });
    node("analytics-reference-btn").addEventListener("click", () => {
      if (!locked) showReference();
    });
    node("analytics-preset").addEventListener("change", () => view.presetHint(selectedPreset()));
    node("analytics-chart").addEventListener("error", () => error("Nie udało się wczytać wykresu PNG.", "analyticsReference"));
    window.addEventListener("kaucjomat:view-selected", (event) => {
      if (event.detail?.viewId === "analityka") activate();
    });
    if (window.location.hash.replace(/^#/, "").toLowerCase() === "analityka") activate();
  }

  bind();
})();
