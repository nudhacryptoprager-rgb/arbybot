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
        "cycles_found_by_length": {"2": 100, "3": 200, "4": 124},
        "discovery_cycles_by_length": {"2": 100, "3": 200, "4": 124},
        "cycle_lengths_used": [2, 3, 4],
        "m8_participation": {"cross_mechanic_cycles": 0},
    }
    rca = build_cycle_rca(artifact, source_artifact="data/tmp/test_shadow.json")
    assert rca["source_graph_fingerprint"]["cycles_found"] == 424
    assert rca["summary"]["cycles_found"] == 424
    assert rca["summary"]["cycles_quoteable"] == 0
    assert rca["summary"]["cycles_found_vs_quoteable_gap"] == 424
    assert rca["summary"]["cycles_found_by_length"]["3"] == 200
    assert rca["by_reject_reason"]["QUOTE_REVERT"] == 48
    assert rca["by_dex_id_leg_errors"]["curve_stable"] == 48
    assert "curve_lane_dominates_failures" in rca["root_cause_hints"]
    assert rca["by_cycle_length_rca"]["3_leg"]["discovery_cycles"] == 200
    assert rca["productive_lane_3_4_gap"]["3_4_leg_quoteability_proven"] is False


def test_build_cycle_rca_amount_continuity_and_value_loss():
    artifact = {
        "cycles_found": 10,
        "cycles_quoteable": 10,
        "cycles_positive_gross": 0,
        "qsr": 1.0,
        "top_opportunities": [
            {
                "cycle_id": "base:3:abc",
                "spread_bps": -9600,
                "market_size_usd": 25,
                "legs": [
                    {
                        "leg_idx": 0,
                        "dex_id": "curve_stable",
                        "token_in": "USDC",
                        "token_out": "USDbC",
                        "norm_amount_in": 25.0,
                        "norm_amount_out": 1.01,
                        "norm_value_ratio": 0.0404,
                        "raw_amount_in": 25_000_000,
                        "raw_amount_out": 1_010_000,
                        "stable_value_ratio_outlier": True,
                        "sanity_gate": "STABLE_VALUE_RATIO_OUTLIER",
                    },
                    {
                        "leg_idx": 1,
                        "dex_id": "maverick_v2",
                        "token_in": "USDbC",
                        "token_out": "WETH",
                        "prev_leg_out_raw": 1_010_000,
                        "current_leg_in_raw": 1_000_000_000_000_000,
                        "amount_continuity_ok": False,
                        "norm_value_ratio": 0.001,
                        "raw_amount_in": 1_000_000_000_000_000,
                    },
                ],
            }
        ],
    }
    rca = build_cycle_rca(artifact)
    assert rca["amount_continuity_rca"]["violation_count"] == 1
    tokens = {row["token_in"] for row in rca["top_value_loss_legs"]}
    assert "USDC" in tokens
    assert rca["summary"]["stable_value_ratio_outlier_legs"] >= 1
    assert rca["adapter_leg_isolation"]["curve_usdc_usdbc"]
