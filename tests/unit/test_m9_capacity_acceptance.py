"""Acceptance report includes NO_ECON_CAPACITY_CYCLES from capacity diagnostic."""
from __future__ import annotations

from scripts.m9_lane_acceptance_report import build_acceptance_report


def test_no_econ_capacity_cycles_blocker():
    shadow = {
        "cycles_found": 100,
        "cycles_quoteable": 0,
        "cycles_positive_gross": 0,
        "qsr": 1.0,
        "qsr_econ": 1.0,
        "depth_aware_known_rate": 0.5,
        "quote_size_truth": {
            "econ_gate_attempts": 100,
            "econ_rpc_quote_attempts": 0,
        },
    }
    capacity = {
        "cycles_total": 500,
        "cycles_at_econ_floor": 0,
        "cycles_at_production_floor": 0,
        "near_econ_cycles_count": 2,
        "economic_size_floor_usd": 180.0,
    }
    report = build_acceptance_report(
        sniper={"metrics": {}},
        anchor={"metrics": {}},
        expansion={"metrics": {}, "summary": {}},
        bridge={"active_routes": [], "bridge_source_metrics": {}},
        shadow=shadow,
        rca={"summary": {}},
        capacity_metrics=capacity,
    )
    assert "NO_ECON_CAPACITY_CYCLES" in report["m9_blockers"]
    assert "NO_ECON_CAPACITY_CYCLES_AT_PRODUCTION_FLOOR" in report["m9_blockers"]
    assert "NEAR_ECON_CAPACITY_ONLY" in report["m9_blockers"]
    assert "ECON_RPC_QUOTES_ZERO" in report["m9_blockers"]
