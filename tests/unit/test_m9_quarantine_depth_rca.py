"""Unit tests for quarantine depth RCA."""
from __future__ import annotations

from m9.graph_arb.quarantine_depth_rca import (
    classify_quarantine_route,
    run_quarantine_depth_rca,
)


def test_false_positive_distinct_probe_toxicity():
    route = {
        "pool_quality_state": "QUARANTINED",
        "depth_reject_reason": "TOXIC_PRICE_IMPACT",
        "depth_probe_source": "distinct_depth_probe",
        "effective_depth_usd": 10.5,
        "price_impact_at_100usd": 0.95,
    }
    assert classify_quarantine_route(route) == "false_positive_distinct_probe_toxicity"


def test_genuinely_thin_pool():
    route = {
        "depth_reject_reason": "TOXIC_PRICE_IMPACT",
        "effective_depth_usd": 8.0,
        "price_impact_at_100usd": 0.99,
        "depth_probe_source": "on_chain",
    }
    assert classify_quarantine_route(route) == "genuinely_thin_or_toxic"


def test_run_quarantine_rca_summary():
    routes = [
        {
            "route_id": "a",
            "pool_quality_state": "QUARANTINED",
            "depth_reject_reason": "TOXIC_PRICE_IMPACT",
            "depth_probe_source": "distinct_depth_probe",
            "effective_depth_usd": 10.5,
            "price_impact_at_100usd": 0.95,
        },
        {
            "route_id": "b",
            "pool_quality_state": "QUARANTINED",
            "depth_reject_reason": "TOXIC_PRICE_IMPACT",
            "effective_depth_usd": 5.0,
            "price_impact_at_100usd": 0.99,
        },
    ]
    report = run_quarantine_depth_rca(active_routes=routes, quarantined_routes=[])
    assert report["active_quarantine_candidates"] == 2
    assert report["false_positive_distinct_probe_count"] >= 1
