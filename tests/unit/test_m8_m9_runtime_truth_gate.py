"""Unit tests for monitoring.runtime_truth_gate (M8 -> M9 evidence integrity).

Locks the contract from the production-readiness review:
  * an 84-byte stub sniper artifact with a ``0xabc`` placeholder pool must be
    refused as CODE_ARTIFACT_CONTRACT (never a market blocker);
  * a stale bridge input must refuse the bundle;
  * artifacts from mixed runtime windows must refuse the bundle;
  * a coherent fresh bundle within one run_timestamp window must PASS.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from monitoring.runtime_truth_gate import (
    BLOCKER_CLASS_CODE_ARTIFACT_CONTRACT,
    evaluate_runtime_truth_gate,
)
from monitoring.sniper_artifacts import make_sniper_artifact

NOW = datetime(2026, 7, 19, 12, 0, 0, tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _valid_sniper(ts: str) -> dict:
    art = make_sniper_artifact(
        metrics={"pool_creation_events_seen": 5},
        status="ACTIVE",
        reasons=[],
        generated_at_utc=ts,
        recent_events=[
            {
                "event_id": "e1",
                "pool_address": "0x" + "a" * 40,
                "pool": "0x" + "a" * 40,
            },
            {
                "event_id": "e2",
                "pool_address": "0x" + "b" * 40,
                "pool": "0x" + "b" * 40,
            },
        ],
        recent_events_by_dex={"uniswap_v4": [{"event_id": "e1"}]},
        self_test_by_dex={"uniswap_v4": {"status": "PASS"}},
    )
    art["m8_health"] = {"goal_status": "REACHED"}
    return art


def _ts_doc(ts: str) -> dict:
    return {"generated_at_utc": ts}


def _coherent_bundle(now: datetime = NOW) -> dict:
    ts = _iso(now - timedelta(minutes=5))
    return {
        "sniper": _valid_sniper(ts),
        "anchor": _ts_doc(ts),
        "hints": _ts_doc(ts),
        "expansion": _ts_doc(ts),
        "m8_3_registry": _ts_doc(ts),
        "bridge": _ts_doc(ts),
    }


def test_stub_sniper_placeholder_pool_blocks_as_code_artifact_contract():
    """0xabc stub (84-byte artifact) must be refused; never a market verdict."""
    stub = {"status": "ACTIVE", "recent_events": [{"event_id": "e1", "pool_address": "0xabc"}]}
    bundle = _coherent_bundle()
    bundle["sniper"] = stub
    verdict = evaluate_runtime_truth_gate(now=NOW, **bundle)
    assert verdict["truth_status"] == "BLOCKED"
    assert verdict["blocker_class"] == BLOCKER_CLASS_CODE_ARTIFACT_CONTRACT
    assert "M8_SNIPER_ARTIFACT_INVALID_OR_STUB" in verdict["blockers"]
    assert "M8_SNIPER_SCHEMA_INVALID" in verdict["blockers"]
    assert "M8_SNIPER_STUB_PLACEHOLDER_POOL" in verdict["blockers"]
    assert verdict["sniper_assessment"]["operational"] is False


def test_stale_bridge_blocks():
    """Bridge older than its 6h threshold refuses the bundle (stale bridge case)."""
    bundle = _coherent_bundle()
    bundle["bridge"] = _ts_doc(_iso(NOW - timedelta(hours=8)))
    verdict = evaluate_runtime_truth_gate(now=NOW, **bundle)
    assert verdict["truth_status"] == "BLOCKED"
    assert "BRIDGE_STALE" in verdict["blockers"]
    assert verdict["per_artifact"]["bridge"]["status"] == "STALE"


def test_mixed_runtime_window_blocks():
    """Artifacts hours apart (mixed bundle) refuse even when none are stale."""
    bundle = _coherent_bundle()
    # Bridge and expansion from a different runtime window (2h before sniper),
    # still within their 6h staleness ceilings.
    old_ts = _iso(NOW - timedelta(hours=2, minutes=5))
    bundle["bridge"] = _ts_doc(old_ts)
    bundle["expansion"] = _ts_doc(old_ts)
    verdict = evaluate_runtime_truth_gate(now=NOW, **bundle)
    assert verdict["truth_status"] == "BLOCKED"
    assert "MIXED_RUNTIME_WINDOW" in verdict["blockers"]
    assert "BRIDGE_STALE" not in verdict["blockers"]
    assert verdict["window_max_delta_seconds"] >= 2 * 3600


def test_missing_input_artifact_blocks():
    bundle = _coherent_bundle()
    bundle["m8_3_registry"] = None
    verdict = evaluate_runtime_truth_gate(now=NOW, **bundle)
    assert verdict["truth_status"] == "BLOCKED"
    assert "M8_3_ARTIFACT_MISSING" in verdict["blockers"]


def test_missing_timestamp_blocks():
    bundle = _coherent_bundle()
    bundle["expansion"] = {"no_timestamp_here": True}
    verdict = evaluate_runtime_truth_gate(now=NOW, **bundle)
    assert verdict["truth_status"] == "BLOCKED"
    assert "EXPANSION_TIMESTAMP_MISSING" in verdict["blockers"]


def test_coherent_fresh_bundle_passes():
    verdict = evaluate_runtime_truth_gate(now=NOW, **_coherent_bundle())
    assert verdict["truth_status"] == "PASS"
    assert verdict["blockers"] == []
    assert verdict["blocker_class"] is None
    assert verdict["sniper_assessment"]["operational"] is True


def test_window_budget_is_configurable():
    """Long-pipeline runs may widen the window budget explicitly."""
    bundle = _coherent_bundle()
    old_ts = _iso(NOW - timedelta(hours=2, minutes=5))
    bundle["bridge"] = _ts_doc(old_ts)
    bundle["expansion"] = _ts_doc(old_ts)
    verdict = evaluate_runtime_truth_gate(now=NOW, window_seconds=3 * 3600, **bundle)
    assert "MIXED_RUNTIME_WINDOW" not in verdict["blockers"]
    assert verdict["truth_status"] == "PASS"
