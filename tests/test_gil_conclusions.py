"""Bezpośrednie testy jednostkowe wniosków o GIL (`kaucjomat.gil_conclusions`)."""

from __future__ import annotations

import pytest

from kaucjomat.gil_benchmark import BenchmarkStrategyResult, GilEnvironmentInfo
from kaucjomat.gil_conclusions import build_conclusions

_SERIAL = "serializację kodu bajtowego Pythona przez GIL"
_BYTECODE = "równoległe wykonanie kodu bajtowego"


def _strategy_stub(strategy_id: str, speedup: float, workers: int = 4) -> BenchmarkStrategyResult:
    """Tworzy deterministyczny wynik strategii do testów wniosków o GIL."""
    median_ms = 1000.0 / speedup
    return BenchmarkStrategyResult(
        strategy_id=strategy_id, strategy_label=strategy_id, workers=workers, repeats=1,
        runs_ms=(median_ms,), median_ms=median_ms, mean_ms=median_ms,
        min_ms=median_ms, max_ms=median_ms,
        speedup_vs_sequential=speedup, relative_to_sequential_pct=100.0 / speedup,
    )


@pytest.mark.parametrize(
    ("gil_enabled", "cpu_count", "thr_speedup", "proc_speedup", "expected_thr", "forbidden_thr", "expected_proc"),
    [
        pytest.param(
            True, 8, 1.45, 2.40, ("zwalniających GIL",), (_BYTECODE, "mimo aktywnego GIL"),
            "omijając GIL", id="gil-active-threads-faster",
        ),
        pytest.param(
            False, 8, 1.45, 2.40, ("free-threading", _BYTECODE), (),
            "osobna pamięć i interpreter", id="free-threading-threads-faster",
        ),
        pytest.param(
            True, 8, 0.98, 2.40, (_SERIAL,), (), "omijając GIL", id="gil-active-threads-flat",
        ),
        pytest.param(
            False, 1, 0.98, 0.85, ("mimo wyłączonego GIL",), (),
            "bez wyraźnego zysku", id="free-threading-single-core",
        ),
    ],
)
def test_build_conclusions_covers_all_gil_and_process_branches(
    gil_enabled: bool,
    cpu_count: int,
    thr_speedup: float,
    proc_speedup: float,
    expected_thr: tuple[str, ...],
    forbidden_thr: tuple[str, ...],
    expected_proc: str,
) -> None:
    """Sprawdza wszystkie gałęzie wniosków wątków, procesów oraz ostrzeżenia dla 1 CPU."""
    env = GilEnvironmentInfo(
        python_version="3.13.5", implementation="CPython", platform_summary="Test OS",
        cpu_count=cpu_count, gil_enabled=gil_enabled,
        free_threading_build=not gil_enabled, switch_interval_s=0.005,
    )
    strategies = (
        _strategy_stub("sequential", 1.0, workers=1),
        _strategy_stub("threads", thr_speedup, workers=4),
        _strategy_stub("processes_spawn", proc_speedup, workers=4),
    )
    warning, conclusions = build_conclusions(env, strategies)

    assert ("GIL=aktywny" if gil_enabled else "GIL=wyłączony (free-threading)") in conclusions[0]
    for phrase in expected_thr:
        assert phrase in conclusions[1]
    for phrase in forbidden_thr:
        assert phrase not in conclusions[1]
    assert expected_proc in conclusions[2]
    # Przy wyłączonym GIL żaden wniosek nie może obwiniać blokady GIL.
    assert gil_enabled or "z powodu blokady GIL" not in " ".join(conclusions)
    assert (warning is not None) == (cpu_count <= 1)
    assert len(conclusions) == (4 if cpu_count <= 1 else 3)
