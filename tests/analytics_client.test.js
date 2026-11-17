/** Testy kontraktu i formatowania widoku Analityka uruchamiane przez node --test. */
const assert = require("node:assert/strict");
const { readFileSync } = require("node:fs");
const { join } = require("node:path");
const { test } = require("node:test");
const { createContext, runInContext } = require("node:vm");
const staticDir = join(__dirname, "../src/kaucjomat/static");
const reference = JSON.parse(readFileSync(
  join(__dirname, "../src/kaucjomat/data/reference/gil_benchmark_reference.json"), "utf8"));

/** Ładuje kontrakt i widok w odizolowanej pamięci, tak jak robi to przeglądarka. */
function client() {
  const sandbox = createContext({ window: {} });
  for (const name of ["analytics_contract.js", "analytics_view.js"]) {
    runInContext(readFileSync(join(staticDir, name), "utf8"), sandbox);
  }
  return { contract: sandbox.window.KaucjomatAnalyticsContract, view: sandbox.window.KaucjomatAnalyticsView };
}

const copy = (value) => structuredClone(value);
const analysis = () => ({
  mode_label: "DEMO", cpu_count: 4, total_elapsed_ms: 900.5, single_core_warning: null,
  stage_one_io: { files_processed: 4, total_chunks: 8, valid_records: 100, invalid_lines: 2, io_workers: 4, io_elapsed_ms: 12.5 },
  stage_two_cpu: { cpu_workers: 4, work_iterations: 30, cpu_elapsed_ms: 800.1, metrics: {
    accepted_count: 60, redirected_glass_count: 20, rejected_count: 20, anomalous_latency_count: 5,
    audit_checksum_hex: "0xabc123" } },
});
const dataset = () => ({ mode_label: "DEMO", log_dir: "logs/quick", file_count: 4, total_lines: 8000,
  expected_valid_records: 7900, expected_invalid_lines: 100, seed: 7, elapsed_ms: 12.3, file_names: ["a.log"] });
const job = (extra) => ({ mode: "DEMO", status: "running", job_id: "abc", kind: "benchmark", preset_id: "quick",
  progress_done: 1, progress_total: 6, ...extra });

test("Referencyjny raport benchmarku przechodzi walidację", () => {
  const { contract } = client();
  assert.equal(contract.benchmarkValid(reference), true);
  assert.equal(contract.referenceValid({ mode: "DEMO", benchmark: reference, chart_url: "/api/analytics/reference/chart" }), true);
});

test("Odrzuca raport benchmarku: zły tryb, kolejność, speedup, liczby niefinitywne i brak sumy hex", () => {
  const { contract } = client();
  const mutate = (change) => { const report = copy(reference); change(report); return contract.benchmarkValid(report); };
  assert.equal(mutate((r) => { r.mode_label = "PROD"; }), false);
  assert.equal(mutate((r) => { r.strategies.reverse(); }), false);
  assert.equal(mutate((r) => { r.strategies.pop(); }), false);
  assert.equal(mutate((r) => { r.strategies[2].speedup_vs_sequential = 9; }), false);
  assert.equal(mutate((r) => { r.strategies[1].median_ms = Infinity; }), false);
  assert.equal(mutate((r) => { r.strategies[1].median_ms = NaN; }), false);
  assert.equal(mutate((r) => { r.verified_metrics.audit_checksum_hex = "16184670422353667457"; }), false);
  assert.equal(mutate((r) => { delete r.verified_metrics.audit_checksum_hex; }), false);
  assert.equal(mutate((r) => { r.conclusions = []; }), false);
  assert.equal(contract.referenceValid({ mode: "DEMO", benchmark: reference, chart_url: "http://x/y.png" }), false);
});

test("Waliduje kontekst: rdzenie, GIL, presety i komunikat 1-rdzeniowy", () => {
  const { contract } = client();
  const context = { mode: "DEMO", cpu_count: 1, gil_enabled: true, single_core_warning: "jednordzeniowe",
    presets: [{ preset_id: "quick", label: "Szybki", description: "opis", size_label: "Pliki: 4" }] };
  assert.equal(contract.contextValid(context), true);
  assert.equal(contract.contextValid({ ...context, single_core_warning: null }), true);
  assert.equal(contract.contextValid({ ...context, cpu_count: 0 }), false);
  assert.equal(contract.contextValid({ ...context, presets: [] }), false);
  assert.equal(contract.contextValid({ ...context, mode: "LIVE" }), false);
});

test("Waliduje migawki zadań: idle, running z brakiem liczb, succeeded i failed", () => {
  const { contract } = client();
  assert.equal(contract.jobValid({ mode: "DEMO", status: "idle" }), true);
  assert.equal(contract.jobValid(job({})), true);
  assert.equal(contract.jobValid(job({ kind: "analysis", progress_total: null, progress_done: null })), true);
  assert.equal(contract.jobValid(job({ kind: "generate", progress_total: 0, progress_done: 0 })), true);
  assert.equal(contract.jobValid(job({ progress_done: 7 })), false);
  assert.equal(contract.jobValid(job({ kind: "inne" })), false);
  assert.equal(contract.jobValid(job({ status: "nieznany" })), false);
  assert.equal(contract.jobValid(job({ status: "failed", error_code: "X", error_message: "Błąd" })), true);
  assert.equal(contract.jobValid(job({ status: "failed" })), false);
  assert.equal(contract.jobValid(job({ status: "succeeded", result: reference })), true);
  assert.equal(contract.jobValid(job({ status: "succeeded", result: null })), false);
  assert.equal(contract.jobValid(job({ status: "succeeded", kind: "analysis", result: reference })), false);
});

test("Waliduje wyniki analizy i generowania zbioru", () => {
  const { contract } = client();
  assert.equal(contract.analysisValid(analysis()), true);
  assert.equal(contract.datasetValid(dataset()), true);
  const broken = analysis();
  broken.stage_two_cpu.metrics.audit_checksum_hex = 123;
  assert.equal(contract.analysisValid(broken), false);
  assert.equal(contract.analysisValid({ ...analysis(), mode_label: "X" }), false);
  assert.equal(contract.datasetValid({ ...dataset(), log_dir: "" }), false);
  assert.equal(contract.resultValid("analysis", analysis()), true);
  assert.equal(contract.resultValid("nieznany", analysis()), false);
});

test("Formatuje czasy i speedup po polsku", () => {
  const { view } = client();
  assert.equal(view.formatMs(6625.687), "6625,7 ms");
  assert.equal(view.formatSpeedup(4.5006), "4,50x");
  assert.equal(view.formatSpeedup(0.976), "0,98x");
});

test("Wybiera wariant komunikatu 1-rdzeniowego: wynik, kontekst albo brak", () => {
  const { view } = client();
  assert.equal(view.pickWarning({ single_core_warning: "kontekst" }, null), "kontekst");
  assert.equal(view.pickWarning({ single_core_warning: "kontekst" }, { single_core_warning: "wynik" }), "wynik");
  assert.equal(view.pickWarning({ single_core_warning: null }, { single_core_warning: null }), null);
  assert.equal(view.pickWarning(null, null), null);
});

test("Wykres z przebiegu tylko dla udanego benchmarku, postęp tylko dla benchmarku", () => {
  const { view } = client();
  assert.equal(view.chartUrl(job({ status: "succeeded" })), "/api/analytics/benchmark/chart?job=abc");
  assert.equal(view.chartUrl(job({ status: "running" })), null);
  assert.equal(view.chartUrl(job({ status: "failed" })), null);
  assert.equal(view.chartUrl(job({ status: "succeeded", kind: "analysis" })), null);
  assert.equal(view.chartUrl(null), null);
  assert.deepEqual({ ...view.progressState(job({})) }, { value: 1, max: 6 });
  assert.equal(view.progressState(job({ kind: "analysis" })), null);
  assert.equal(view.progressState(job({ progress_total: 0 })), null);
  assert.match(view.statusText(job({ phase: "Benchmark GIL: threads" })), /\(1 z 6\)/);
  assert.match(view.statusText(job({ status: "failed", error_message: "Brak zbioru" })), /Brak zbioru/);
});
