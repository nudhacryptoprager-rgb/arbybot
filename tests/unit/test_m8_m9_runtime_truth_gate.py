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


def test_run_timestamp_is_canonical_over_generated_at_utc():
    """run_context.run_timestamp must be used when present; generated_at_utc
    is a legacy fallback only."""
    bundle = _coherent_bundle()
    bundle["bridge"] = {
        "run_context": {"run_timestamp": _iso(NOW - timedelta(minutes=5))},
        "generated_at_utc": _iso(NOW - timedelta(hours=5)),  # would be stale
    }
    verdict = evaluate_runtime_truth_gate(now=NOW, **bundle)
    assert "BRIDGE_STALE" not in verdict["blockers"]
    assert (
        verdict["per_artifact"]["bridge"]["timestamp_source"]
        == "run_context.run_timestamp"
    )
    assert verdict["truth_status"] == "PASS"


def test_shared_session_id_widens_window_for_serial_pipeline():
    """A serial M8->M8.1->M8.2->M8.3->bridge pipeline legitimately runs
    longer than the ad-hoc 48 min proximity threshold. When all
    session-bearing artifacts share a session_id, the window is widened to
    session_window_seconds (default 90 min) so a 44-min serial bundle still
    counts as one runtime window."""
    bundle = _coherent_bundle()
    # Sniper is fresh; bridge is 44 min older — would exceed the default
    # 48-min ad-hoc window only just barely, but the 30-min default from
    # the old gate would have failed it. Here we use 70 min to prove the
    # session-widened budget (90 min) admits it while the ad-hoc budget
    # (48 min) would not.
    fresh_ts = _iso(NOW - timedelta(minutes=2))
    older_ts = _iso(NOW - timedelta(minutes=72))
    shared_sid = "session-2026-07-19-serial-1"
    for key in ("sniper", "anchor", "hints", "expansion", "m8_3_registry", "bridge"):
        doc = dict(bundle[key])
        doc["run_context"] = {"session_id": shared_sid, "run_timestamp": older_ts if key == "bridge" else fresh_ts}
        bundle[key] = doc
    # Without session widening (window_seconds=48*60) this would BLOCK.
    verdict = evaluate_runtime_truth_gate(now=NOW, **bundle)
    assert verdict["session_id"] == shared_sid
    assert "MIXED_RUNTIME_WINDOW" not in verdict["blockers"]
    assert verdict["truth_status"] == "PASS"
    # And the effective window is the session window:
    assert verdict["window_seconds"] == 90 * 60


def test_session_id_mismatch_is_hard_blocker():
    """Artifacts declaring different session_id values cannot be stitched
    even when temporally close."""
    bundle = _coherent_bundle()
    bundle["bridge"] = {
        **bundle["bridge"],
        "run_context": {
            "session_id": "session-A",
            "run_timestamp": _iso(NOW - timedelta(minutes=5)),
        },
    }
    bundle["expansion"] = {
        **bundle["expansion"],
        "run_context": {
            "session_id": "session-B",
            "run_timestamp": _iso(NOW - timedelta(minutes=5)),
        },
    }
    verdict = evaluate_runtime_truth_gate(now=NOW, **bundle)
    assert "SESSION_ID_MISMATCH" in verdict["blockers"]
    assert verdict["truth_status"] == "BLOCKED"
    assert verdict["blocker_class"] == BLOCKER_CLASS_CODE_ARTIFACT_CONTRACT


def test_serial_bundle_with_2645s_delta_passes_with_session_id():
    """Regression for the review finding: a real serial bundle with delta
    2645s was rejected by the old fixed 1800s window. With session_id
    binding and the 90-min session window, this exact delta must PASS."""
    bundle = _coherent_bundle()
    shared_sid = "session-2026-07-19-serial-2645s"
    sniper_ts = _iso(NOW - timedelta(minutes=5))
    bridge_ts = _iso(NOW - timedelta(seconds=2645 + 5 * 60))  # 44 min older
    for key in ("sniper", "anchor", "hints", "expansion", "m8_3_registry"):
        doc = dict(bundle[key])
        doc["run_context"] = {"session_id": shared_sid, "run_timestamp": sniper_ts}
        bundle[key] = doc
    bundle["bridge"] = {
        **bundle["bridge"],
        "run_context": {"session_id": shared_sid, "run_timestamp": bridge_ts},
    }
    verdict = evaluate_runtime_truth_gate(now=NOW, **bundle)
    assert "MIXED_RUNTIME_WINDOW" not in verdict["blockers"]
    assert verdict["truth_status"] == "PASS"
    assert verdict["window_max_delta_seconds"] >= 2645
