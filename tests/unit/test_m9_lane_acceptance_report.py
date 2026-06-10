"""Unit tests for m9_lane_acceptance_report script."""
from __future__ import annotations

from scripts.m9_lane_acceptance_report import build_acceptance_report


def test_build_acceptance_report_blockers_when_m8_not_ready():
    report = build_acceptance_report(
        sniper={"status": "ACTIVE", "metrics": {"snipe_candidates_total": 11}, "recent_events": [{}] * 11},
        anchor={"status": "PASS", "metrics": {"stable_anchor_passes_total": 100, "qsr": 1.0}},
        expansion={"metrics": {"routes_admitted": 50, "multi_venue_tokens": 3}},
        bridge={
            "active_routes": [{"dex_id": "balancer_vault", "cross_mechanic": True}],
            "bridge_source_metrics": {
                "m8_new_pools_input": 11,
                "token_verified_count": 0,
                "graph_ready_from_m8": 0,
                "graph_ready_total": 100,
                "m8_funnel_reject_histogram": {"TOKEN_SYMBOL_MISSING": 11},
            },
        },
        shadow={
            "cycles_found": 100,
            "cycles_quoteable": 10,
            "cycles_positive_gross": 0,
            "cross_mechanic_cycles": 0,
            "qsr": 0.1,
        },
        rca=None,
    )
    assert "M8_DIRECT_INGESTION_NOT_READY" in report["blockers"]
    assert "NO_POSITIVE_GROSS" in report["blockers"]
    assert report["goal_status"] == "BLOCKED"
    assert report["funnel_layers"][1]["m8_funnel_reject_histogram"]["TOKEN_SYMBOL_MISSING"] == 11


def test_build_acceptance_report_m8_2_summary_from_artifact_summary():
    report = build_acceptance_report(
        sniper={"status": "ACTIVE", "metrics": {}, "recent_events": []},
        anchor={"metrics": {}},
        expansion={
            "summary": {
                "routes_admitted_count": 595,
                "connector_routes_count": 59,
                "subgraph_ready_tokens": 1,
                "verified_second_pool_count": 7,
                "multi_venue_tokens": 3,
                "hint_tokens_matched": 283,
                "external_hints_enabled": True,
                "m8_tokens_in": 272,
            }
        },
        bridge={"active_routes": [], "bridge_source_metrics": {}},
        shadow=None,
        rca=None,
    )
    layer = next(
        x for x in report["funnel_layers"] if x["layer"] == "M8_2_expansion"
    )
    assert layer["routes_admitted"] == 595
    assert layer["connector_routes_count"] == 59
    assert layer["subgraph_ready_tokens"] == 1
    assert layer["verified_second_pool_count"] == 7
    assert layer["external_hints_enabled"] is True


def test_build_acceptance_report_quote_blockers():
    report = build_acceptance_report(
        sniper={"status": "ACTIVE", "metrics": {}, "recent_events": [{}]},
        anchor={"metrics": {}},
        expansion={"metrics": {}},
        bridge={
            "active_routes": [],
            "bridge_source_metrics": {
                "graph_ready_from_m8": 8,
                "m8_stale": True,
                "sniper_age_seconds": 7200,
            },
        },
        shadow={
            "cycles_found": 362,
            "cycles_quoteable": 0,
            "cycles_positive_gross": 0,
            "qsr": 0.0,
            "cross_mechanic_cycles": 106,
            "cross_mechanic_cycles_found": 106,
            "cross_mechanic_cycles_quoteable": 0,
            "cycles_with_m8_pool": 0,
            "phantom_quote_diagnostics": {"phantom_count": 10},
            "cycle_reject_histogram": {"OVERSIZED_VS_DEPTH": 261},
        },
        rca=None,
    )
    assert "NO_QUOTEABLE_CYCLES" in report["blockers"]
    assert "QSR_ZERO" in report["blockers"]
    assert "CYCLES_WITH_M8_POOL_ZERO" in report["blockers"]
    assert "PHANTOM_QUOTE_PRESENT" in report["blockers"]
    assert "NO_CROSS_MECHANIC_CYCLES_QUOTEABLE" in report["blockers"]
    assert "M8_ARTIFACT_STALE" in report["blockers"]
