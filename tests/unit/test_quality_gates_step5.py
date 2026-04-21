"""Step 5 (Apr-21 soak): operational quality gates in the rolling aggregator.

Tests two new checks added to m4/rolling_store.py:
  - TOP_PAIR_DOMINANCE_WARN/FAIL: flags when one pair monopolizes signal flow
  - DRIFT_WORST_PAIR_WARN/FAIL: flags when notional-drift worst-pair exceeds
    safe bounds on a per-chain frontier.
"""
import tempfile
from pathlib import Path

import pytest

from m4.rolling_store import emit_to_aggregator_light


def _make_run_summary(run_id: str, signals_per_pair: dict, *, net_usdc: float = 1.0,
                      drift_worst_bps: float | None = None) -> dict:
    ds = {
        "drift_excluded_count": 0,
        "drift_rejection_rate": 0.0,
        "signal_drift_median_pct": 0.0,
        "signal_drift_p90_pct": 0.0,
        "signal_drift_median_bps": 0.0,
        "pairs_with_drift_data": 0,
        "pairs_with_exclusions": 0,
    }
    if drift_worst_bps is not None:
        ds["per_pair_drift_summary"] = [
            {"pair": "WORST/USDC", "notional_drift_median_bps": drift_worst_bps},
        ]
    return {
        "run_id": run_id,
        "timestamp": f"2026-04-21T10:00:{int(run_id[-2:]) % 60:02d}Z",
        "status": "PASS",
        "metrics": {
            "total_net_usdc": net_usdc,
            "signals_count": sum(signals_per_pair.values()) or 5,
            "included_signals_count": sum(signals_per_pair.values()) or 5,
            "signals_per_pair": signals_per_pair,
            "drift_summary": ds,
        },
        "inputs": {"run_mode": "REGISTRY_REAL", "chain_id": 8453, "chain_key": "base"},
    }


def _run_rolling(runs: list[dict]) -> dict:
    with tempfile.TemporaryDirectory() as td:
        agg_path = Path(td) / "agg.json"
        result: dict = {}
        for rs in runs:
            result = emit_to_aggregator_light(rs, agg_path, max_runs=200)
        return result


def test_top_pair_dominance_warn_triggers_at_threshold():
    # 50% for TOP/USDC > 0.40 → WARN but < 0.70 → not FAIL
    # 15 runs to clear warmup (MIN_RUNS_FOR_AGG=10) and 30+ total signals.
    runs = [
        _make_run_summary(f"run_{i:02d}", {"TOP/USDC": 50, "OTHER/USDC": 25, "OTHER2/USDC": 25})
        for i in range(15)
    ]
    agg = _run_rolling(runs)
    warnings = agg.get("quality_warnings") or []
    assert any(w.startswith("TOP_PAIR_DOMINANCE_WARN(TOP/USDC") for w in warnings), warnings
    assert not any(w.startswith("TOP_PAIR_DOMINANCE_FAIL") for w in warnings), warnings
    assert "TOP_PAIR_DOMINANCE_WARN" in (agg.get("agg_reasons") or []), agg.get("agg_reasons")


def test_top_pair_dominance_fail_triggers_at_high_share():
    # 90% share > 0.70 → FAIL
    runs = [
        _make_run_summary(f"run_{i:02d}", {"TOP/USDC": 90, "OTHER/USDC": 10})
        for i in range(15)
    ]
    agg = _run_rolling(runs)
    warnings = agg.get("quality_warnings") or []
    assert any(w.startswith("TOP_PAIR_DOMINANCE_FAIL(TOP/USDC") for w in warnings), warnings
    assert "TOP_PAIR_DOMINANCE_FAIL" in (agg.get("agg_reasons") or [])
    # has_fail_threshold in rolling_store.py promotes to agg_status=FAIL.
    assert agg.get("agg_status") == "FAIL"


def test_top_pair_dominance_ok_when_balanced():
    runs = [
        _make_run_summary(f"run_{i:02d}", {"A/USDC": 10, "B/USDC": 10, "C/USDC": 10, "D/USDC": 10, "E/USDC": 10})
        for i in range(15)
    ]
    agg = _run_rolling(runs)
    warnings = agg.get("quality_warnings") or []
    assert not any(w.startswith("TOP_PAIR_DOMINANCE") for w in warnings), warnings


def test_top_pair_dominance_skipped_when_no_per_pair_counts():
    # Runs without signals_per_pair must not raise or emit any dominance warn.
    runs = [
        _make_run_summary(f"run_{i:02d}", {})  # empty per-pair → skip check
        for i in range(15)
    ]
    agg = _run_rolling(runs)
    warnings = agg.get("quality_warnings") or []
    assert not any(w.startswith("TOP_PAIR_DOMINANCE") for w in warnings), warnings


def test_drift_worst_pair_warn_triggers():
    # 800 bps > 500 WARN threshold < 2000 FAIL
    runs = [
        _make_run_summary(
            f"run_{i:02d}",
            {"A/USDC": 10, "B/USDC": 10},
            drift_worst_bps=800.0,
        )
        for i in range(15)
    ]
    agg = _run_rolling(runs)
    warnings = agg.get("quality_warnings") or []
    assert any("DRIFT_WORST_PAIR_WARN" in w for w in warnings), warnings
    assert not any("DRIFT_WORST_PAIR_FAIL" in w for w in warnings), warnings


def test_drift_worst_pair_fail_triggers():
    # 3000 bps > 2000 FAIL threshold
    runs = [
        _make_run_summary(
            f"run_{i:02d}",
            {"A/USDC": 10, "B/USDC": 10},
            drift_worst_bps=3000.0,
        )
        for i in range(15)
    ]
    agg = _run_rolling(runs)
    warnings = agg.get("quality_warnings") or []
    assert any("DRIFT_WORST_PAIR_FAIL" in w for w in warnings), warnings
    assert "DRIFT_WORST_PAIR_FAIL" in (agg.get("agg_reasons") or [])
