"""Unit tests for m8_to_m9_token_trace_report."""
from __future__ import annotations

from scripts.m8_to_m9_token_trace_report import build_token_trace_report


def test_trace_flags_stub_sniper_and_missing_bridge_route():
    sniper = {
        "schema_family": "m8_sniper",
        "schema_revision": "phase2.0",
        "generated_at_utc": "2026-01-01T00:00:00Z",
        "source": "new_pool_listener",
        "freshness_s": 1.0,
        "status": "ACTIVE",
        "reasons": [],
        "metrics": {
            "pool_creation_events_seen": 1,
            "pool_creation_events_filtered_out": 0,
            "honeypot_check_pass": 0,
            "honeypot_check_fail": 0,
            "snipe_candidates_total": 1,
        },
        "recent_events": [
            {
                "event_id": "ev1",
                "pool": "0xabc",
                "dex": "uniswap_v3",
                "token0": "0x1111111111111111111111111111111111111111",
                "token1": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
                "token0_symbol": "FOO",
                "token1_symbol": "USDC",
            }
        ],
        "recent_events_by_dex": {},
    }
    report = build_token_trace_report(
        sniper=sniper,
        expansion={"routes_admitted": []},
        bridge={"active_routes": [], "bridge_source_metrics": {"graph_ready_from_m8": 0}},
        shadow={"cycles_found": 0, "top_opportunities": []},
    )
    assert report["sniper_assessment"]["operational"] is False
    assert report["summary"]["events_traced"] == 1
    assert report["token_traces"][0]["reject_reason"] == "NO_BRIDGE_ROUTE_FOR_TOKEN"
