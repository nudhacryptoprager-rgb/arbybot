"""E1.33: Tests for profit_realism_status invariant guard.

Ensures ROUNDTRIP_PROFITABLE cannot coexist with real_quote_count==0 or
profitable_count==0. If upstream drifts, build_truth_data demotes the status
and annotates the truth_report for RCA.
"""
from __future__ import annotations

import pytest

from strategy.artifacts import build_truth_data


def _minimal_stats(roundtrip: dict | None = None) -> dict:
    """Produce minimal stats dict to exercise build_truth_data."""
    return {
        "quotes_total": 0,
        "quotes_fetched": 0,
        "dexes_active": [],
        "price_sanity_passed": 0,
        "price_sanity_failed": 0,
        "suspect_quotes": 0,
        "suspect_reasons": {},
        "opportunity_engine": {"summary": {}},
        "roundtrip": roundtrip or {},
    }


def _base_config() -> dict:
    return {
        "kill_switch_active": True,
        "execution_enabled": False,
        "truth_mode_m42": False,
        "run_kind": "NORMAL",
    }


def _call_build(rt: dict) -> dict:
    return build_truth_data(
        config=_base_config(),
        stats=_minimal_stats(rt),
        current_block=0,
        spread_signals=[],
        suspect_examples=[],
        infra_payload={},
        raw_bps=0,
        spread_threshold_bps=10,
        rejected_quotes=[],
    )


def test_invariant_demotes_when_real_quote_count_zero():
    """ROUNDTRIP_PROFITABLE with real_quote_count=0 must be demoted."""
    rt = {
        "enabled": True,
        "evaluated_count": 5,
        "profitable_count": 0,
        "real_quote_count": 0,
        "executable_evidence": "SWEEP_PROFITABLE",
        "dynamic_sweep": {
            "enabled": True,
            "best_net_pnl_bps": 12.5,
        },
    }
    td = _call_build(rt)
    assert td["profit_realism_status"] == "ROUNDTRIP_NOT_PROFITABLE"
    violation = td.get("profit_realism_invariant_violation")
    assert violation is not None
    assert violation["original_status"] == "ROUNDTRIP_PROFITABLE"
    assert violation["real_quote_count"] == 0
    assert violation["profitable_count"] == 0


def test_invariant_demotes_when_profitable_count_zero():
    rt = {
        "enabled": True,
        "evaluated_count": 5,
        "profitable_count": 0,
        "real_quote_count": 4,
        "executable_evidence": "SWEEP_PROFITABLE",
        "dynamic_sweep": {"enabled": True, "best_net_pnl_bps": 15.0},
    }
    td = _call_build(rt)
    assert td["profit_realism_status"] == "ROUNDTRIP_NOT_PROFITABLE"
    assert td.get("profit_realism_invariant_violation") is not None


def test_invariant_passes_when_legit_profitable():
    rt = {
        "enabled": True,
        "evaluated_count": 5,
        "profitable_count": 2,
        "real_quote_count": 4,
        "executable_evidence": "NO_DATA",
        "dynamic_sweep": {},
    }
    td = _call_build(rt)
    assert td["profit_realism_status"] == "ROUNDTRIP_PROFITABLE"
    assert "profit_realism_invariant_violation" not in td


def test_invariant_does_not_touch_non_profitable_statuses():
    rt = {
        "enabled": True,
        "evaluated_count": 3,
        "profitable_count": 0,
        "real_quote_count": 0,
        "dynamic_sweep": {},
    }
    td = _call_build(rt)
    assert td["profit_realism_status"] == "ROUNDTRIP_NOT_PROFITABLE"
    assert "profit_realism_invariant_violation" not in td
