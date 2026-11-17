/** Bezpieczne renderowanie widoku Analityka wyłącznie przez createElement i textContent (bez wstrzykiwania HTML). */
window.KaucjomatAnalyticsView = (() => {
  const node = (id) => document.getElementById(id);
  const KIND_LABELS = {
    generate: "Generowanie zbioru logów", analysis: "Analiza dwuetapowa", benchmark: "Benchmark GIL",
  };
  const decimal = (value, digits) => value.toFixed(digits).replace(".", ",");

  /** Formatuje czas w milisekundach z polskim przecinkiem dziesiętnym. */
  function formatMs(value) {
    return `${decimal(value, 1)} ms`;
  }

  /** Formatuje przyspieszenie względem przebiegu sekwencyjnego, np. `4,50x`. */
  function formatSpeedup(value) {
    return `${decimal(value, 2)}x`;
  }

  /** Wybiera komunikat 1-rdzeniowy: z wyniku zadania, a w jego braku z kontekstu bieżącej maszyny. */
  function pickWarning(context, result) {
    return result?.single_core_warning || context?.single_core_warning || null;
  }

  /** Adres wykresu z przebiegu na żywo tylko dla udanego benchmarku; plik wykresu jest jeden na serwer. */
  function chartUrl(job) {
    if (job?.kind !== "benchmark" || job.status !== "succeeded" || !job.job_id) return null;
    return `/api/analytics/benchmark/chart?job=${encodeURIComponent(job.job_id)}`;
  }

  /** Postęp określony tylko dla benchmarku; pozostałe zadania nie raportują liczb (pasek nieokreślony). */
  function progressState(job) {
    if (job?.kind !== "benchmark" || !Number.isInteger(job.progress_total) || job.progress_total <= 0) return null;
    return { value: job.progress_done || 0, max: job.progress_total };
  }

  /** Tekst statusu zadania po polsku, z fazą i licznikiem przebiegów, jeśli są znane. */
  function statusText(job) {
    const label = KIND_LABELS[job.kind] || "Zadanie";
    if (job.status === "running") {
      const state = progressState(job);
      const counter = state ? ` (${state.value} z ${state.max})` : "";
      const phase = job.phase || "w toku";
      // Faza benchmarku już zaczyna się od nazwy zadania, więc nie dublujemy etykiety.
      return `${phase.startsWith(label) ? phase : `${label}: ${phase}`}${counter}…`;
    }
    if (job.status === "succeeded") return `${label}: zakończono w ${formatMs(job.elapsed_ms || 0)}.`;
    return `${label}: ${job.error_message || "zadanie zakończyło się błędem"}`;
  }

  /** Tworzy element z tekstem z API, bez interpretacji HTML. */
  function element(tag, value, className = "") {
    const item = document.createElement(tag);
    item.textContent = value;
    item.className = className;
    return item;
  }

  /** Wypełnia listę faktów „etykieta: wartość” w wybranym kontenerze. */
  function facts(id, pairs) {
    const list = node(id);
    list.replaceChildren();
    for (const [label, value] of pairs) list.append(element("li", `${label}: ${value}`));
  }

  /** Pokazuje rdzenie CPU i stan GIL z kontekstu maszyny. */
  function environment(context) {
    node("analytics-cpu").textContent = `Rdzenie CPU: ${context.cpu_count}`;
    node("analytics-gil").textContent = `GIL: ${context.gil_enabled ? "aktywny" : "wyłączony (free-threading)"}`;
  }

  /** Pokazuje lub ukrywa wyjaśnienie dla maszyny jednordzeniowej. */
  function singleCore(message) {
    const box = node("analytics-single-core");
    box.textContent = message || "";
    box.hidden = !message;
  }

  /** Wypełnia listę wyboru presetów i zwraca wybrany identyfikator. */
  function presets(list) {
    const select = node("analytics-preset");
    select.replaceChildren();
    for (const preset of list) {
      const option = element("option", `${preset.label} — ${preset.size_label}`);
      option.value = preset.preset_id;
      select.append(option);
    }
  }

  /** Pokazuje opis czasu i charakteru wybranego presetu. */
  function presetHint(preset) {
    node("analytics-preset-hint").textContent = preset ? preset.description : "";
  }

  /** Renderuje tabelę, wnioski i opis środowiska raportu (referencyjnego lub na żywo). */
  function benchmark(report, label) {
    const env = report.environment;
    node("analytics-result-label").textContent = `${label} (DEMO)`;
    node("analytics-result-meta").textContent = `Python ${env.python_version} (${env.implementation}) · `
      + `${env.platform_summary} · rdzenie CPU: ${env.cpu_count} · GIL: ${env.gil_enabled ? "aktywny" : "wyłączony"} · `
      + `rekordy: ${report.dataset.valid_records} · powtórzenia: ${report.benchmark_config.repeats} · `
      + `suma kontrolna: ${report.verified_metrics.audit_checksum_hex}`;
    const body = node("analytics-table-body");
    body.replaceChildren();
    for (const item of report.strategies) {
      const row = element("tr", "", item.strategy_id === report.benchmark_config.fastest_strategy_id ? "is-fastest" : "");
      const cells = [item.strategy_label, item.workers, formatMs(item.median_ms), formatMs(item.mean_ms),
        formatMs(item.min_ms), formatMs(item.max_ms), formatSpeedup(item.speedup_vs_sequential)];
      for (const value of cells) row.append(element("td", String(value)));
      body.append(row);
    }
    const list = node("analytics-conclusions");
    list.replaceChildren();
    for (const conclusion of report.conclusions) list.append(element("li", conclusion));
  }

  /** Renderuje karty etapu 1 (wątki, I/O) i etapu 2 (procesy spawn, CPU) analizy dwuetapowej. */
  function stages(report) {
    const io = report.stage_one_io;
    const cpu = report.stage_two_cpu;
    const metrics = cpu.metrics;
    facts("analytics-stage1", [["Czas odczytu", formatMs(io.io_elapsed_ms)], ["Wątki", io.io_workers],
      ["Pliki", io.files_processed], ["Porcje", io.total_chunks], ["Poprawne rekordy", io.valid_records],
      ["Błędne linie", io.invalid_lines]]);
    facts("analytics-stage2", [["Czas obliczeń", formatMs(cpu.cpu_elapsed_ms)], ["Procesy spawn", cpu.cpu_workers],
      ["Rundy FNV-1a", cpu.work_iterations], ["Przyjęte", metrics.accepted_count],
      ["Szkło do kasy", metrics.redirected_glass_count], ["Odrzucone", metrics.rejected_count],
      ["Anomalie opóźnień", metrics.anomalous_latency_count], ["Suma kontrolna", metrics.audit_checksum_hex],
      ["Czas całkowity", formatMs(report.total_elapsed_ms)]]);
  }

  /** Pokazuje podsumowanie wygenerowanego zbioru logów. */
  function dataset(summary) {
    node("analytics-dataset").textContent = `Zbiór gotowy (${summary.log_dir}): pliki ${summary.file_count}, `
      + `linie ${summary.total_lines}, poprawne ${summary.expected_valid_records}, `
      + `błędne ${summary.expected_invalid_lines}, ziarno ${summary.seed}, czas ${formatMs(summary.elapsed_ms)}.`;
  }

  /** Ustawia tekst statusu oraz pasek postępu (nieokreślony, gdy zadanie nie raportuje liczb). */
  function status(message, job = null) {
    node("analytics-status").textContent = message;
    const bar = node("analytics-progress");
    const running = job?.status === "running";
    bar.hidden = !running;
    const state = running ? progressState(job) : null;
    if (state) {
      bar.max = state.max;
      bar.value = state.value;
    } else {
      bar.removeAttribute("value");
    }
  }

  /** Blokuje sterowanie na czas zadania lub braku kontekstu i oznacza widok jako zajęty. */
  function controls(busy, ready) {
    const targets = document.querySelectorAll("[data-analytics-kind], #analytics-preset, #analytics-reference-btn");
    targets.forEach((item) => { item.disabled = busy || !ready; });
    node("view-analityka").setAttribute("aria-busy", busy ? "true" : "false");
  }

  /** Pokazuje wykres PNG albo go ukrywa, gdy adres jest pusty. */
  function chart(src, alt) {
    const image = node("analytics-chart");
    image.hidden = !src;
    if (src) {
      image.alt = alt;
      image.src = src;
    }
  }

  return { formatMs, formatSpeedup, pickWarning, chartUrl, progressState, statusText, environment,
    singleCore, presets, presetHint, benchmark, stages, dataset, status, controls, chart };
})();
