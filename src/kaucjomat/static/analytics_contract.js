/** Walidacja odpowiedzi API widoku Analityka przed renderowaniem (bez ufania kształtowi danych). */
window.KaucjomatAnalyticsContract = (() => {
  const STRATEGY_ORDER = ["sequential", "threads", "processes_spawn"];
  const KINDS = ["generate", "analysis", "benchmark"];
  const STATUSES = ["idle", "running", "succeeded", "failed"];
  const number = (value) => typeof value === "number" && Number.isFinite(value);
  const nonNegative = (value) => number(value) && value >= 0;
  const count = (value) => Number.isInteger(value) && value >= 0;
  const text = (value) => typeof value === "string" && value.length > 0;
  const nullableText = (value) => value === null || text(value);
  /** Suma kontrolna jest tylko szesnastkowym napisem, bo wartość liczbowa przekracza zakres JS. */
  const checksumHex = (value) => typeof value === "string" && /^0x[0-9a-f]+$/.test(value);

  /** Środowisko maszyny i lista presetów muszą być kompletne, żeby wolno było uruchamiać zadania. */
  function contextValid(payload) {
    return payload?.mode === "DEMO" && Number.isInteger(payload.cpu_count) && payload.cpu_count >= 1
      && typeof payload.gil_enabled === "boolean" && nullableText(payload.single_core_warning)
      && Array.isArray(payload.presets) && payload.presets.length > 0
      && payload.presets.every((preset) => text(preset?.preset_id) && text(preset.label)
        && text(preset.description) && text(preset.size_label));
  }

  /** Wiersz strategii: liczby skończone, a przyspieszenie zgodne z medianami (z tolerancją zaokrągleń). */
  function strategyValid(strategy, index, sequentialMedian) {
    if (!strategy || strategy.strategy_id !== STRATEGY_ORDER[index] || !text(strategy.strategy_label)
      || !Number.isInteger(strategy.workers) || strategy.workers < 1) return false;
    const times = ["median_ms", "mean_ms", "min_ms", "max_ms"];
    if (!times.every((key) => number(strategy[key]) && strategy[key] > 0)) return false;
    const expected = sequentialMedian / strategy.median_ms;
    return number(strategy.speedup_vs_sequential)
      && Math.abs(strategy.speedup_vs_sequential - expected) <= 0.01 * Math.max(1, expected);
  }

  /** Raport benchmarku (referencyjny lub na żywo) ma ten sam kształt: DEMO i trzy strategie po kolei. */
  function benchmarkValid(report) {
    const env = report?.environment;
    const strategies = report?.strategies;
    if (report?.mode_label !== "DEMO" || !env || !Number.isInteger(env.cpu_count) || env.cpu_count < 1
      || !text(env.python_version) || typeof env.gil_enabled !== "boolean") return false;
    if (!Array.isArray(strategies) || strategies.length !== STRATEGY_ORDER.length) return false;
    const sequentialMedian = strategies[0]?.median_ms;
    return strategies.every((item, index) => strategyValid(item, index, sequentialMedian))
      && count(report.dataset?.valid_records) && count(report.benchmark_config?.repeats)
      && checksumHex(report.verified_metrics?.audit_checksum_hex)
      && nullableText(report.single_core_warning)
      && Array.isArray(report.conclusions) && report.conclusions.length > 0 && report.conclusions.every(text);
  }

  /** Wyniki referencyjne to raport benchmarku wraz z adresem wykresu z API analityki. */
  function referenceValid(payload) {
    return payload?.mode === "DEMO" && benchmarkValid(payload.benchmark)
      && text(payload.chart_url) && payload.chart_url.startsWith("/api/analytics/");
  }

  /** Raport analizy dwuetapowej: etap I/O (wątki) i etap CPU (procesy) z czasami i metrykami. */
  function analysisValid(report) {
    const io = report?.stage_one_io;
    const cpu = report?.stage_two_cpu;
    return report?.mode_label === "DEMO" && Number.isInteger(report.cpu_count) && report.cpu_count >= 1
      && nonNegative(report.total_elapsed_ms) && nullableText(report.single_core_warning)
      && !!io && count(io.files_processed) && count(io.total_chunks) && count(io.valid_records)
      && count(io.invalid_lines) && count(io.io_workers) && nonNegative(io.io_elapsed_ms)
      && !!cpu && count(cpu.cpu_workers) && count(cpu.work_iterations) && nonNegative(cpu.cpu_elapsed_ms)
      && count(cpu.metrics?.accepted_count) && count(cpu.metrics.redirected_glass_count)
      && count(cpu.metrics.rejected_count) && count(cpu.metrics.anomalous_latency_count)
      && checksumHex(cpu.metrics.audit_checksum_hex);
  }

  /** Podsumowanie wygenerowanego zbioru logów (etykieta katalogu jest względna, nie ścieżka lokalna). */
  function datasetValid(summary) {
    return summary?.mode_label === "DEMO" && text(summary.log_dir) && count(summary.file_count)
      && count(summary.total_lines) && count(summary.expected_valid_records)
      && count(summary.expected_invalid_lines) && Number.isInteger(summary.seed)
      && nonNegative(summary.elapsed_ms) && Array.isArray(summary.file_names);
  }

  /** Wybiera walidator wyniku według rodzaju zadania; nieznany rodzaj jest odrzucany. */
  function resultValid(kind, result) {
    const checks = { generate: datasetValid, analysis: analysisValid, benchmark: benchmarkValid };
    return Object.hasOwn(checks, kind) && checks[kind](result);
  }

  /** Migawka zadania: stan `idle` bywa pusty, pozostałe wymagają tożsamości, postępu i wyniku lub błędu. */
  function jobValid(payload) {
    if (payload?.mode !== "DEMO" || !STATUSES.includes(payload.status)) return false;
    if (payload.status === "idle") return true;
    const total = payload.progress_total;
    const done = payload.progress_done;
    const progressOk = (total === null || total === undefined || count(total))
      && (done === null || done === undefined || (count(done) && (!total || done <= total)));
    if (!KINDS.includes(payload.kind) || !text(payload.job_id) || !text(payload.preset_id) || !progressOk) {
      return false;
    }
    if (payload.status === "succeeded") return resultValid(payload.kind, payload.result);
    if (payload.status === "failed") return text(payload.error_code) && text(payload.error_message);
    return true;
  }

  return { contextValid, referenceValid, jobValid, benchmarkValid, analysisValid, datasetValid, resultValid };
})();
