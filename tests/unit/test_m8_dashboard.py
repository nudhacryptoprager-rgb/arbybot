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


# ---------------------------------------------------------------------------
# Phase 2 dashboard tests
# ---------------------------------------------------------------------------

def _artifact_with_phase2():
    """Artifact where the single event already has a phase2_decision block."""
    art = _artifact()
    art["metrics"].update({
        "phase2_reject_histogram": {"INSUFFICIENT_DATA": 2, "LOW_LIQUIDITY": 1},
        "phase2_would_enter_count": 1,
        "phase2_expected_pnl_non_null_count": 1,
    })
    art["recent_events"][0]["phase2_decision"] = {
        "dry_run_decision": "WOULD_ENTER",
        "estimated_spread_bps": 120.5,
        "expected_pnl_usd": 0.72,
        "liquidity_usd": 5000.0,
        "honeypot_verdict": "OK",
        "mirror_found": True,
        "slippage_result": {"ok": True, "impact_bps": 15.0},
    }
    return art


def test_phase2_fields_appear_in_opportunity_row():
    """Row must expose phase2 enrichment fields when phase2_decision is present."""
    payload = build_m8_current_payload(
        artifact=_artifact_with_phase2(),
        now_utc=NOW,
        file_age_s=3,
    )
    row = payload["opportunity_rows"][0]
    assert row["phase2_decision"] == "WOULD_ENTER"
    assert row["liquidity_usd"] == 5000.0
    assert row["honeypot_verdict"] == "OK"
    assert row["mirror_found"] is True
    assert row["slippage_result"]["ok"] is True


def test_phase2_would_enter_makes_row_realizable():
    """A WOULD_ENTER phase2 decision must flip is_realizable to True."""
    payload = build_m8_current_payload(
        artifact=_artifact_with_phase2(),
        now_utc=NOW,
        file_age_s=3,
    )
    row = payload["opportunity_rows"][0]
    assert row["is_realizable"] is True


def test_phase2_spread_bps_and_profit_usd_from_decision():
    """spread_bps and profit_usd should fall back to phase2_decision values."""
    payload = build_m8_current_payload(
        artifact=_artifact_with_phase2(),
        now_utc=NOW,
        file_age_s=3,
    )
    row = payload["opportunity_rows"][0]
    # spread_bps from phase2_decision.estimated_spread_bps
    assert row["spread_bps"] is not None
    assert float(row["spread_bps"]) == 120.5
    # profit_usd from phase2_decision.expected_pnl_usd
    assert row["profit_usd"] is not None
    assert float(row["profit_usd"]) == 0.72


def test_funnel_includes_phase2_counters():
    """phase2 reject histogram and counters must appear in the funnel dict."""
    payload = build_m8_current_payload(
        artifact=_artifact_with_phase2(),
        now_utc=NOW,
        file_age_s=3,
    )
    funnel = payload["funnel"]
    assert funnel["phase2_reject_histogram"]["INSUFFICIENT_DATA"] == 2
    assert funnel["phase2_reject_histogram"]["LOW_LIQUIDITY"] == 1
    assert funnel["phase2_would_enter_count"] == 1
    assert funnel["phase2_expected_pnl_non_null_count"] == 1


def test_funnel_phase2_counters_zero_by_default():
    """phase2 counters must be present and 0 when metrics have no phase2 data."""
    payload = build_m8_current_payload(
        artifact=_artifact(),
        now_utc=NOW,
        file_age_s=3,
    )
    funnel = payload["funnel"]
    assert funnel["phase2_reject_histogram"] == {}
    assert funnel["phase2_would_enter_count"] == 0
    assert funnel["phase2_expected_pnl_non_null_count"] == 0
