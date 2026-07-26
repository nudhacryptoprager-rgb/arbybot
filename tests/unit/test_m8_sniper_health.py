"""Unit tests for monitoring.sniper_health — M8 acceptance gate."""
from __future__ import annotations

import json

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


def test_self_test_skipped_unverified_blocks():
    art = _base_artifact(self_test_source="skipped_unverified", reasons=["SELF_TEST_SKIPPED"])
    health = evaluate_m8_sniper_health(art)
    assert "M8_SELF_TEST_SKIPPED" in health["blockers"]


def test_legacy_self_test_skipped_reason_still_blocks():
    art = _base_artifact(reasons=["SELF_TEST_SKIPPED"])
    health = evaluate_m8_sniper_health(art)
    assert "M8_SELF_TEST_SKIPPED" in health["blockers"]


def test_checkpoint_self_test_source_does_not_block():
    art = _base_artifact(
        self_test_source="checkpoint",
        reasons=[],
        self_test_by_dex={"uniswap_v3": {"status": "PASS"}},
    )
    health = evaluate_m8_sniper_health(art)
    assert health["goal_status"] == "REACHED"
    assert "M8_SELF_TEST_SKIPPED" not in health["blockers"]


def test_live_self_test_source_does_not_block():
    art = _base_artifact(
        self_test_source="live",
        self_test_by_dex={"uniswap_v3": {"status": "PASS"}},
    )
    health = evaluate_m8_sniper_health(art)
    assert health["goal_status"] == "REACHED"
    assert "M8_SELF_TEST_SKIPPED" not in health["blockers"]


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


def test_batch2_checkpoint_skip_self_test_passes_acceptance_gate(tmp_path, monkeypatch):
    """Batch 1 checkpoint + batch 2 --skip-self-test must not false-block health."""
    from discovery.new_pool_listener import load_factory_config
    from m8.runtime.sniper_checkpoint import (
        build_factory_config_fingerprint,
        write_checkpoint_artifact,
    )
    from scripts.sniper_smoke_run import main

    session_id = "2026-07-26T12:00:00Z"
    rpc_url = "https://rpc.example.test"
    configs = load_factory_config(chain_filter="base")
    assert configs
    fingerprint = build_factory_config_fingerprint(configs)
    checkpoint_path = tmp_path / "checkpoint.json"
    write_checkpoint_artifact(
        str(checkpoint_path),
        session_id=session_id,
        chain="base",
        rpc_url=rpc_url,
        factory_config_fingerprint=fingerprint,
        self_test_results={"uniswap_v3": {"status": "PASS"}},
        batch_index=1,
    )

    artifact_path = tmp_path / "new_pool_sniper_latest.json"
    monkeypatch.setenv("ARBY_SNIPER_ENABLE", "1")
    monkeypatch.setenv("ARBY_PIPELINE_SESSION_ID", session_id)
    monkeypatch.setattr(
        "monitoring.sniper_artifacts.ROLLING_ARTIFACT_PATH",
        artifact_path,
    )
    monkeypatch.setattr("m8.runtime.smoke_run._resolve_ws_url", lambda *_a, **_k: None)

    class _FakeLane:
        http_url = rpc_url
        w3 = object()
        primary_provider = "test"

    def _fake_online_loop(**kwargs):
        funnel = kwargs["funnel"]
        funnel.set_listener_mode("ws+http_fallback")
        funnel.update_ws_stats(connected=True, subscriptions=12, events_seen=3)
        funnel.record_factory_poll("uniswap_v3", ok=True)

    monkeypatch.setattr("m8.runtime.smoke_run._build_sniper_rpc_lane", lambda *_a, **_k: _FakeLane())
    monkeypatch.setattr("m8.runtime.smoke_run._run_online_loop", _fake_online_loop)

    rc = main(
        argv=[
            "--chain",
            "base",
            "--duration-minutes",
            "0",
            "--acceptance-run",
            "--skip-preflight",
            "--skip-self-test",
            "--checkpoint-artifact",
            str(checkpoint_path),
            "--streaming-batch-index",
            "2",
            "--rpc-url",
            rpc_url,
        ]
    )
    assert rc == 0
    art = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert art.get("self_test_source") == "checkpoint"
    assert "SELF_TEST_SKIPPED" not in (art.get("reasons") or [])
    health = art.get("m8_health") or evaluate_m8_sniper_health(art)
    assert health["goal_status"] == "REACHED"
    assert "M8_SELF_TEST_SKIPPED" not in health.get("blockers", [])


def test_manual_skip_without_checkpoint_still_blocks_health():
    art = _base_artifact(
        self_test_source="skipped_unverified",
        reasons=["SELF_TEST_SKIPPED"],
        self_test_by_dex={},
    )
    health = evaluate_m8_sniper_health(art)
    assert health["goal_status"] == "BLOCKED"
    assert "M8_SELF_TEST_SKIPPED" in health["blockers"]
