"""Unit tests for monitoring.sniper_health — M8 acceptance gate."""
from __future__ import annotations

from monitoring.sniper_health import evaluate_m8_sniper_health


def _base_artifact(**overrides):
    artifact = {
        "status": "ACTIVE",
        "reasons": [],
        "metrics": {
            "rpc_calls_made": 100,
            "rpc_errors": 0,
            "parse_failed": 0,
            "listener_mode": "ws+http_fallback",
            "ws_connected": True,
            "snipe_candidates_total": 5,
            "factory_breakdown": {
                "uniswap_v3": {"polls_ok": 10, "errors": 0, "raw_logs": 3},
            },
            "factory_last_success_ts": {"uniswap_v3": 1710000000.0},
            "pending_registry_sync": {"registry_out_of_sync": False},
        },
        "self_test_by_dex": {
            "uniswap_v3": {"status": "PASS"},
        },
        "recent_events_by_dex": {
            "uniswap_v3": [{"event_id": "e1"}],
        },
    }
    artifact.update(overrides)
    return artifact


def test_healthy_artifact_reaches_goal():
    health = evaluate_m8_sniper_health(_base_artifact())
    assert health["goal_status"] == "REACHED"
    assert health["blockers"] == []


def test_rpc_error_rate_high_blocks():
    art = _base_artifact()
    art["metrics"]["rpc_errors"] = 10
    art["metrics"]["rpc_calls_made"] = 20
    health = evaluate_m8_sniper_health(art)
    assert "M8_RPC_ERROR_RATE_HIGH" in health["blockers"]
    assert health["goal_status"] == "BLOCKED"


def test_http_only_degraded_blocks():
    art = _base_artifact()
    art["metrics"]["listener_mode"] = "http_only"
    art["metrics"]["ws_connected"] = False
    health = evaluate_m8_sniper_health(art)
    assert "M8_HTTP_ONLY_DEGRADED" in health["blockers"]


def test_self_test_skipped_blocks():
    art = _base_artifact(reasons=["SELF_TEST_SKIPPED"])
    health = evaluate_m8_sniper_health(art)
    assert "M8_SELF_TEST_SKIPPED" in health["blockers"]


def test_factory_degraded_blocks():
    art = _base_artifact()
    art["metrics"]["factory_breakdown"] = {
        "alien_base_v2": {"polls_ok": 0, "errors": 5, "raw_logs": 0},
    }
    art["recent_events_by_dex"] = {}
    health = evaluate_m8_sniper_health(art)
    assert "M8_FACTORY_DEGRADED" in health["blockers"]
    assert "alien_base_v2" in health["degraded_dexes"]


def test_pending_registry_out_of_sync_blocks():
    art = _base_artifact()
    art["metrics"]["pending_registry_sync"] = {"registry_out_of_sync": True}
    health = evaluate_m8_sniper_health(art)
    assert "M8_PENDING_REGISTRY_OUT_OF_SYNC" in health["blockers"]


def test_factory_no_http_success_blocks_without_ws():
    art = _base_artifact()
    art["metrics"]["rpc_calls_made"] = 12
    art["metrics"]["rpc_errors"] = 12
    art["metrics"]["factory_last_success_ts"] = {}
    art["metrics"]["listener_mode"] = "http_only"
    art["metrics"]["ws_connected"] = False
    health = evaluate_m8_sniper_health(art)
    assert "M8_FACTORY_NO_HTTP_SUCCESS" in health["blockers"]


def test_ws_lane_waives_http_rpc_errors_when_events_seen():
    art = _base_artifact()
    art["metrics"]["rpc_calls_made"] = 12
    art["metrics"]["rpc_errors"] = 12
    art["metrics"]["listener_mode"] = "ws+http_fallback"
    art["metrics"]["ws_connected"] = True
    art["metrics"]["ws_events_seen"] = 5
    art["metrics"]["factory_breakdown"] = {
        "uniswap_v4": {"polls_ok": 0, "errors": 1, "raw_logs": 0, "parse_ok": 5, "candidates": 5},
    }
    health = evaluate_m8_sniper_health(art)
    assert "M8_RPC_ERROR_RATE_HIGH" not in health["blockers"]
    assert "M8_FACTORY_DEGRADED" not in health["blockers"]
    assert health["ws_lane_healthy"] is True


def test_extended_metric_keys_present_in_funnel_snapshot():
    from monitoring.sniper_funnel import FunnelTracker

    funnel = FunnelTracker()
    funnel.record_factory_poll("uniswap_v3", ok=True, error_code="")
    snap = funnel.snapshot()
    for key in (
        "factory_error_rate_by_dex",
        "factory_last_success_ts",
        "factory_last_error_code",
        "dexes_degraded",
        "pending_registry_sync",
    ):
        assert key in snap
