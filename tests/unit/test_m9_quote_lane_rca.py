"""Cycle quote RCA diagnostic tests."""
from __future__ import annotations

from scripts.m9_quote_lane_diagnostic import build_cycle_rca


def test_build_cycle_rca_breaks_down_zero_quoteable():
    artifact = {
        "cycles_found": 424,
        "cycles_quoteable": 0,
        "cycle_reject_histogram": {
            "CYCLE_QUOTE_FAILED": 323,
            "OVERSIZED_VS_DEPTH": 101,
        },
        "edge_error_histogram": [
            {
                "route_id": "curve_stable:USDC-USDbC@0",
                "errors": {"QUOTE_REVERT": 48},
            },
            {
                "route_id": "balancer_vault:WETH-USDC@0",
                "errors": {"QUOTE_OK_PRODUCTIVE": 0},
            },
        ],
        "cycles_by_length": {"2": 100, "3": 200, "4": 124},
        "m8_participation": {"cross_mechanic_cycles": 0},
    }
    rca = build_cycle_rca(artifact, source_artifact="data/tmp/test_shadow.json")
    assert rca["source_graph_fingerprint"]["cycles_found"] == 424
    assert rca["summary"]["cycles_found"] == 424
    assert rca["summary"]["cycles_quoteable"] == 0
    assert rca["summary"]["cycles_found_vs_quoteable_gap"] == 424
    assert rca["by_reject_reason"]["QUOTE_REVERT"] == 48
    assert "curve_lane_dominates_failures" in rca["root_cause_hints"]
