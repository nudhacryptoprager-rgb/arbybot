"""M8 dashboard contract tests.

The dashboard is read-only over ``new_pool_sniper_latest.json``.  Phase 1
listener rows must show the requested economics columns while honestly marking
execution as not realizable until later phases publish pricing/simulation data.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from monitoring.dashboard_server import (
    DASHBOARD_M8_HTML,
    build_m8_current_payload,
)


NOW = datetime(2026, 5, 13, 16, 45, 0, tzinfo=timezone.utc)


def _artifact():
    return {
        "schema_family": "m8_sniper",
        "schema_revision": "phase1.1",
        "generated_at_utc": "2026-05-13T16:44:27Z",
        "source": "sniper_smoke_run/base",
        "freshness_s": 12.5,
        "status": "ACTIVE",
        "reasons": [],
        "metrics": {
            "pool_creation_events_seen": 2,
            "pool_creation_events_filtered_out": 0,
            "snipe_candidates_total": 2,
            "raw_fetched": 2,
            "parse_ok": 2,
            "parse_failed": 0,
            "dedup_new": 2,
            "dedup_dropped": 0,
            "filter_passed": 2,
            "filter_rejected": 0,
            "candidates_queued": 2,
            "rpc_calls_made": 10,
            "rpc_errors": 0,
            "cycles_completed": 4,
            "elapsed_s": 120.0,
        },
        "recent_events": [
            {
                "event_id": "base:factory:tx:1",
                "chain": "base",
                "dex": "uniswap_v3",
                "factory": "0x33128a8fC17869897dcE68Ed026d694621f6FDfD",
                "pool": "0x299aecd2f356fe01b44274c9540e1d63a29ba79b",
                "token0": "0x4200000000000000000000000000000000000006",
                "token1": "0xac45caa7fa5501d9c5d2fbf331d0d35a54b88ea1",
                "block_number": 45950240,
                "tx_hash": "0xabc",
            }
        ],
    }


def test_m8_payload_surfaces_requested_opportunity_fields():
    payload = build_m8_current_payload(
        artifact=_artifact(),
        now_utc=NOW,
        file_age_s=3,
    )

    row = payload["opportunity_rows"][0]
    for key in (
        "pair",
        "pool",
        "spread_usd",
        "spread_bps",
        "volume_usd",
        "profit_usd",
        "is_realizable",
        "realizability_reason",
        "blocking_metrics",
    ):
        assert key in row


def test_phase1_listener_rows_are_not_claimed_realizable():
    payload = build_m8_current_payload(
        artifact=_artifact(),
        now_utc=NOW,
        file_age_s=3,
    )

    row = payload["opportunity_rows"][0]
    assert row["is_realizable"] is False
    assert "M8_PHASE1_LISTENER_ONLY" in row["realizability_reason"]
    assert row["blocking_metrics"]["spread_bps_available"] is False
    assert row["blocking_metrics"]["profit_usd_available"] is False
    assert row["blocking_metrics"]["simulation_available"] is False


def test_m8_funnel_exposes_stage_counts_and_drop_reasons():
    payload = build_m8_current_payload(
        artifact=_artifact(),
        now_utc=NOW,
        file_age_s=3,
    )

    funnel = payload["funnel"]
    assert funnel["rpc_calls_made"] == 10
    assert funnel["rpc_errors"] == 0
    assert funnel["cycles_completed"] == 4
    stages = {row["stage"]: row for row in funnel["stages"]}
    assert stages["raw_fetched"]["count"] == 2
    assert stages["parse_failed"]["count"] == 0
    assert stages["candidates_queued"]["count"] == 2


def test_m8_payload_handles_missing_artifact():
    payload = build_m8_current_payload(artifact={}, now_utc=NOW, file_age_s=None)

    assert payload["artifact"]["exists"] is False
    assert payload["artifact"]["status"] == "MISSING"
    assert payload["artifact"]["reasons"] == ["ARTIFACT_MISSING"]
    assert payload["opportunity_rows"] == []


def test_m8_dashboard_html_points_to_m8_api():
    html_path = Path(DASHBOARD_M8_HTML)
    assert html_path.name == "dashboard_m8.html"
    html = html_path.read_text(encoding="utf-8")
    assert "/api/m8/current" in html
    for label in ("Spread $", "Spread bps", "Volume $", "Profit $", "Signal Funnel"):
        assert label in html
