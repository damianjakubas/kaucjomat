"""Wnioski edukacyjne o wpływie GIL, dobierane na podstawie zmierzonych czasów."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from kaucjomat.gil_benchmark import BenchmarkStrategyResult, GilEnvironmentInfo

_SPEEDUP_THRESHOLD = 1.2  # Próg przyspieszenia uznawany za realny zysk z równoległości.


def _threads_conclusion(
    env: GilEnvironmentInfo, thr: BenchmarkStrategyResult, seq: BenchmarkStrategyResult,
) -> str:
    """Opisuje wynik wątków zależnie od zmierzonego przyspieszenia i stanu GIL."""
    head = (f"Wątki ({thr.workers} pracowników) uzyskały medianę {thr.median_ms:.1f} ms "
            f"({thr.speedup_vs_sequential:.2f}x względem sekwencyjnego {seq.median_ms:.1f} ms)")
    if thr.speedup_vs_sequential >= _SPEEDUP_THRESHOLD:
        if env.gil_enabled:
            tail = (
                "jednak przy aktywnym GIL nie oznacza to równoległego wykonywania "
                "kodu bajtowego Pythona — zysk może wynikać z operacji zwalniających GIL "
                "(I/O lub kod natywny), wahań krótkiego pomiaru albo zmienności systemu "
                "(taktowanie, planista)."
            )
        else:
            tail = "co wskazuje na równoległe wykonanie kodu bajtowego (build free-threading)."
    elif env.gil_enabled:
        tail = "co potwierdza serializację kodu bajtowego Pythona przez GIL w jednym procesie."
    else:
        tail = "mimo wyłączonego GIL; wynik może wynikać z narzutu puli wątków."
    return f"{head}, {tail}"


def _processes_conclusion(
    env: GilEnvironmentInfo, proc: BenchmarkStrategyResult, seq: BenchmarkStrategyResult,
) -> str:
    """Opisuje wynik procesów spawn zależnie od zmierzonego przyspieszenia i stanu GIL."""
    head = (f"Procesy spawn ({proc.workers} pracowników) osiągnęły medianę {proc.median_ms:.1f} ms "
            f"({proc.speedup_vs_sequential:.2f}x względem przebiegu sekwencyjnego)")
    if proc.speedup_vs_sequential >= _SPEEDUP_THRESHOLD:
        if env.gil_enabled:
            return f"{head}, omijając GIL dzięki niezależnym interpreterom."
        # Build free-threading: GIL nie istnieje, więc zysk wynika z osobnych procesów.
        return f"{head}, dzięki niezależnym procesom (osobna pamięć i interpreter)."
    return f"{head} — bez wyraźnego zysku: narzut startu spawn i IPC lub zbyt mało rdzeni CPU."


def build_single_core_warning(cpu_count: int) -> str | None:
    """Zwraca wyjaśnienie dla środowiska jednordzeniowego albo ``None`` przy 2+ rdzeniach."""
    if cpu_count > 1:
        return None
    return (
        "Wykryto środowisko jednordzeniowe (cpu_count=1): pula procesów spawn nie ma "
        "dodatkowych rdzeni CPU, więc narzut startu procesów i IPC może ją spowolnić. "
        "Przyspieszenie procesów powyżej 1,0x wymaga wielu rdzeni, a wątki nie dadzą "
        "przyspieszenia przy jednym rdzeniu (niezależnie od stanu GIL)."
    )


def build_conclusions(
    env: GilEnvironmentInfo, strategies: tuple[BenchmarkStrategyResult, ...],
) -> tuple[str | None, tuple[str, ...]]:
    """Buduje ostrzeżenie dla 1 CPU oraz krótkie wnioski domenowe o wpływie GIL."""
    by_id = {item.strategy_id: item for item in strategies}
    seq, thr, proc = by_id["sequential"], by_id["threads"], by_id["processes_spawn"]
    single_core_warning = build_single_core_warning(env.cpu_count)

    gil_state = "aktywny" if env.gil_enabled else "wyłączony (free-threading)"
    conclusions = [
        f"Środowisko: {env.implementation} {env.python_version}, wykryte rdzenie CPU={env.cpu_count}, "
        f"GIL={gil_state} (interwał przełączania {env.switch_interval_s:.4f} s).",
        _threads_conclusion(env, thr, seq),
        _processes_conclusion(env, proc, seq),
    ]
    if single_core_warning is not None:
        conclusions.append(single_core_warning)
    return single_core_warning, tuple(conclusions)
