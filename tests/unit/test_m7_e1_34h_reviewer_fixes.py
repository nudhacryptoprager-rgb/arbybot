"""M7.E1.34h — tests for the reviewer 10-step fix batch (code-addressable).

Covers:
- fix #3 enriched HOT_SKIP_UNKNOWN_PAIR sample propagation into
  rollup["bridge_hit_but_not_fast_scored"]["samples"].
- fix #5 supervisor_window block (cumulative events/min across child
  restarts, anchored to rollup.first_window_at not session_started_at).
- fix #6 flush_rollup_shutdown stamps last_heartbeat_utc / last_updated /
  shutdown_flush_at at supervisor end.
- fix #7 sim_failed_samples_recent ring pruned to current session_id so
  stale samples from previous child sessions do not contaminate fresh
  soak diagnosis.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest


def _call_rollup(tmp_path, monkeypatch, *, events_count, fast_results,
                 bridge_diagnostics=None, gate_result=None, session_id="sid-h"):
    import m7.orderflow.hot_runtime_artifacts as hra

    rollup_path = tmp_path / "m7_hot_rollup_latest.json"
    monkeypatch.setattr(hra._rio, "_HOT_ROLLUP_PATH", str(rollup_path))
    monkeypatch.setattr(hra._rio, "_SESSION_ID", session_id, raising=False)

    hra._update_hot_rollup(
        events_count=events_count,
        fast_results=fast_results,
        guard_results=None,
        bridge_diagnostics=bridge_diagnostics,
        ws_live_stats={"ws_connection_status": "connected"},
        chain="base",
        gate_result=gate_result,
    )
    return rollup_path, json.loads(rollup_path.read_text(encoding="utf-8"))


class TestBridgeSampleEnrichment:
    def test_sample_propagates_into_rollup_bucket(self, tmp_path, monkeypatch):
        bd = {
            "bridge_pool_address_hit_count": 1,
            "bridge_hit_not_scored_reason": "HOT_SKIP_UNKNOWN_PAIR",
            "bridge_hit_not_scored_sample": {
                "pool_address": "0xabc",
                "scoring_path": "hot_skip",
                "reason": "HOT_SKIP_UNKNOWN_PAIR",
                "actual_pair": "WETH/USDC",
                "token_in": "0xtok0",
                "token_out": "0xtok1",
                "fee_tier": 500,
                "venue": "uniswap_v3",
                "adapter_type": "v3",
            },
        }
        _, rollup = _call_rollup(
            tmp_path, monkeypatch,
            events_count=1, fast_results=[], bridge_diagnostics=bd,
        )
        diag = rollup["bridge_hit_but_not_fast_scored"]
        assert diag["reason_histogram"]["HOT_SKIP_UNKNOWN_PAIR"] == 1
        samples = diag["samples"]
        assert len(samples) == 1
        s = samples[0]
        assert s["pool_address"] == "0xabc"
        assert s["scoring_path"] == "hot_skip"
        assert s["actual_pair"] == "WETH/USDC"
        assert s["token_in"] == "0xtok0"
        assert s["token_out"] == "0xtok1"
        assert s["fee_tier"] == 500
        assert s["venue"] == "uniswap_v3"
        assert "observed_at" in s

    def test_samples_bounded_to_ten(self, tmp_path, monkeypatch):
        import m7.orderflow.hot_runtime_artifacts as hra

        rollup_path = tmp_path / "m7_hot_rollup_latest.json"
        monkeypatch.setattr(hra._rio, "_HOT_ROLLUP_PATH", str(rollup_path))
        monkeypatch.setattr(hra._rio, "_SESSION_ID", "sid-h", raising=False)

        for i in range(15):
            bd = {
                "bridge_pool_address_hit_count": 1,
                "bridge_hit_not_scored_reason": "NOT_SCORED",
                "bridge_hit_not_scored_sample": {
                    "pool_address": f"0x{i:040x}",
                    "scoring_path": None,
                    "reason": "NOT_SCORED",
                },
            }
            hra._update_hot_rollup(
                events_count=1, fast_results=[], guard_results=None,
                bridge_diagnostics=bd, chain="base",
            )
        rollup = json.loads(rollup_path.read_text(encoding="utf-8"))
        samples = rollup["bridge_hit_but_not_fast_scored"]["samples"]
        assert len(samples) == 10
        # Should be the last 10 observations (i=5..14).
        assert samples[0]["pool_address"].endswith(f"{5:040x}"[-6:])
        assert samples[-1]["pool_address"].endswith(f"{14:040x}"[-6:])


class TestSupervisorWindow:
    def test_supervisor_window_block_present(self, tmp_path, monkeypatch):
        _, rollup = _call_rollup(
            tmp_path, monkeypatch, events_count=3, fast_results=[],
        )
        sw = rollup.get("supervisor_window")
        assert sw is not None
        assert "first_window_at" in sw
        assert sw["events_total"] == 3
        assert sw["elapsed_minutes"] > 0
        assert sw["events_per_minute"] >= 3.0

    def test_supervisor_window_survives_session_id_change(
        self, tmp_path, monkeypatch
    ):
        import m7.orderflow.hot_runtime_artifacts as hra

        rollup_path = tmp_path / "m7_hot_rollup_latest.json"
        monkeypatch.setattr(hra._rio, "_HOT_ROLLUP_PATH", str(rollup_path))

        # First child session writes 2 events.
        monkeypatch.setattr(hra._rio, "_SESSION_ID", "sid-A", raising=False)
        hra._update_hot_rollup(
            events_count=2, fast_results=[], guard_results=None,
            bridge_diagnostics=None, chain="base",
        )
        # Supervisor restarts child -> new session_id -> session counters
        # reset, but supervisor_window must keep accumulating.
        monkeypatch.setattr(hra._rio, "_SESSION_ID", "sid-B", raising=False)
        hra._update_hot_rollup(
            events_count=3, fast_results=[], guard_results=None,
            bridge_diagnostics=None, chain="base",
        )
        rollup = json.loads(rollup_path.read_text(encoding="utf-8"))
        # session-level block reset to the new session_id with its own counters
        assert rollup["session"]["session_id"] == "sid-B"
        assert rollup["session"]["session_events_seen_total"] == 3
        # supervisor-level block accumulates across both sessions
        sw = rollup["supervisor_window"]
        assert sw["events_total"] == 5
        assert sw["events_per_minute"] >= 5.0


class TestShutdownFlush:
    def test_flush_writes_shutdown_fields_on_existing_rollup(
        self, tmp_path, monkeypatch
    ):
        import m7.orderflow.hot_runtime_artifacts as hra

        rollup_path = tmp_path / "m7_hot_rollup_latest.json"
        monkeypatch.setattr(hra._rio, "_HOT_ROLLUP_PATH", str(rollup_path))
        monkeypatch.setattr(hra._rio, "_SESSION_ID", "sid-h", raising=False)

        hra._update_hot_rollup(
            events_count=1, fast_results=[], guard_results=None,
            bridge_diagnostics=None, chain="base",
        )
        rollup_before = json.loads(rollup_path.read_text(encoding="utf-8"))
        assert "shutdown_flush_at" not in rollup_before

        hra.flush_rollup_shutdown(chain="base")
        rollup_after = json.loads(rollup_path.read_text(encoding="utf-8"))
        assert "shutdown_flush_at" in rollup_after
        assert rollup_after["last_heartbeat_utc"] == rollup_after["shutdown_flush_at"]
        assert rollup_after["last_updated"] == rollup_after["shutdown_flush_at"]
        assert rollup_after["chain"] == "base"

    def test_flush_is_noop_when_rollup_missing(self, tmp_path, monkeypatch):
        import m7.orderflow.hot_runtime_artifacts as hra

        rollup_path = tmp_path / "m7_hot_rollup_latest.json"
        monkeypatch.setattr(hra._rio, "_HOT_ROLLUP_PATH", str(rollup_path))

        # Should not raise, should not create a file from nothing.
        hra.flush_rollup_shutdown(chain="base")
        # Empty rollup is written (file with minimal fields) — either
        # behaviour is OK as long as no crash and a valid JSON exists or
        # not exists.
        if rollup_path.exists():
            obj = json.loads(rollup_path.read_text(encoding="utf-8"))
            assert obj.get("shutdown_flush_at")


class TestSimFailedSamplesSessionPrune:
    def test_previous_session_samples_dropped_on_next_append(
        self, tmp_path, monkeypatch
    ):
        import m7.orderflow.hot_runtime_artifacts as hra

        rollup_path = tmp_path / "m7_hot_rollup_latest.json"
        monkeypatch.setattr(hra._rio, "_HOT_ROLLUP_PATH", str(rollup_path))

        # Session A appends 2 failed samples.
        monkeypatch.setattr(hra._rio, "_SESSION_ID", "sid-A", raising=False)
        gate_a = SimpleNamespace(
            sim_attempted=1,
            sim_passed=0,
            submit_ready=0,
            sim_disabled=False,
            sim_blocker=None,
            roundtrip_attempted=0,
            sim_errors=["REVERT"],
            submit_blockers_detail=[],
            sim_failed_samples=[
                {"error": "REVERT", "venue": "v1", "token": "T"},
                {"error": "REVERT", "venue": "v2", "token": "T"},
            ],
        )
        hra._update_hot_rollup(
            events_count=1, fast_results=[], guard_results=None,
            bridge_diagnostics=None, chain="base", gate_result=gate_a,
        )
        rollup = json.loads(rollup_path.read_text(encoding="utf-8"))
        assert len(rollup["sim_failed_samples_recent"]) == 2
        assert all(
            s["session_id"] == "sid-A"
            for s in rollup["sim_failed_samples_recent"]
        )

        # Supervisor restarts child -> session B appends 1 new sample.
        # Ring must drop the A entries before merging.
        monkeypatch.setattr(hra._rio, "_SESSION_ID", "sid-B", raising=False)
        gate_b = SimpleNamespace(
            sim_attempted=1,
            sim_passed=0,
            submit_ready=0,
            sim_disabled=False,
            sim_blocker=None,
            roundtrip_attempted=0,
            sim_errors=["OUT_OF_GAS"],
            submit_blockers_detail=[],
            sim_failed_samples=[{"error": "OUT_OF_GAS", "venue": "v3"}],
        )
        hra._update_hot_rollup(
            events_count=1, fast_results=[], guard_results=None,
            bridge_diagnostics=None, chain="base", gate_result=gate_b,
        )
        rollup = json.loads(rollup_path.read_text(encoding="utf-8"))
        ring = rollup["sim_failed_samples_recent"]
        assert len(ring) == 1
        assert ring[0]["session_id"] == "sid-B"
        assert ring[0]["error"] == "OUT_OF_GAS"
        # sim_failed_samples_total still accumulates across sessions.
        assert rollup["sim_failed_samples_total"] == 3


class TestSupervisorEndAndSessionStartedAtTopLevel:
    """Reviewer post-20m-control fix #7: surface session_started_at and
    supervisor_end_utc at the top level of the rollup so reviewer
    staleness logic does not need to compute against last_updated alone.
    """

    def test_current_session_started_at_mirrors_session_block(
        self, tmp_path, monkeypatch
    ):
        import m7.orderflow.hot_runtime_artifacts as hra

        rollup_path = tmp_path / "m7_hot_rollup_latest.json"
        monkeypatch.setattr(hra._rio, "_HOT_ROLLUP_PATH", str(rollup_path))
        monkeypatch.setattr(hra._rio, "_SESSION_ID", "sid-X", raising=False)

        hra._update_hot_rollup(
            events_count=1, fast_results=[], guard_results=None,
            bridge_diagnostics=None, chain="base",
        )
        rollup = json.loads(rollup_path.read_text(encoding="utf-8"))
        assert rollup["current_session_started_at"] == rollup["session"]["session_started_at"]

    def test_supervisor_end_utc_starts_none_and_stamped_on_flush(
        self, tmp_path, monkeypatch
    ):
        import m7.orderflow.hot_runtime_artifacts as hra

        rollup_path = tmp_path / "m7_hot_rollup_latest.json"
        monkeypatch.setattr(hra._rio, "_HOT_ROLLUP_PATH", str(rollup_path))
        monkeypatch.setattr(hra._rio, "_SESSION_ID", "sid-Y", raising=False)

        hra._update_hot_rollup(
            events_count=1, fast_results=[], guard_results=None,
            bridge_diagnostics=None, chain="base",
        )
        rollup_before = json.loads(rollup_path.read_text(encoding="utf-8"))
        # supervisor_end_utc explicitly initialised to None at session start.
        assert rollup_before["supervisor_end_utc"] is None

        # Per-cycle child clean-exit MUST NOT stamp supervisor_end_utc.
        hra.flush_rollup_shutdown(chain="base")
        rollup_after_child = json.loads(rollup_path.read_text(encoding="utf-8"))
        assert rollup_after_child["supervisor_end_utc"] is None
        assert rollup_after_child["shutdown_flush_at"] is not None

        # Real supervisor exit hook stamps supervisor_end_utc.
        hra.mark_supervisor_end(chain="base")
        rollup_after_sv = json.loads(rollup_path.read_text(encoding="utf-8"))
        assert rollup_after_sv["supervisor_end_utc"] is not None
        assert rollup_after_sv["supervisor_end_utc"] == rollup_after_sv["shutdown_flush_at"]

    def test_supervisor_end_utc_resets_to_none_on_new_session(
        self, tmp_path, monkeypatch
    ):
        import m7.orderflow.hot_runtime_artifacts as hra

        rollup_path = tmp_path / "m7_hot_rollup_latest.json"
        monkeypatch.setattr(hra._rio, "_HOT_ROLLUP_PATH", str(rollup_path))

        # Session A: real supervisor exit (not per-cycle flush).
        monkeypatch.setattr(hra._rio, "_SESSION_ID", "sid-A", raising=False)
        hra._update_hot_rollup(
            events_count=1, fast_results=[], guard_results=None,
            bridge_diagnostics=None, chain="base",
        )
        hra.mark_supervisor_end(chain="base")
        rollup_after_a = json.loads(rollup_path.read_text(encoding="utf-8"))
        assert rollup_after_a["supervisor_end_utc"] is not None

        # Session B starts: supervisor_end_utc must reset to None.
        monkeypatch.setattr(hra._rio, "_SESSION_ID", "sid-B", raising=False)
        hra._update_hot_rollup(
            events_count=1, fast_results=[], guard_results=None,
            bridge_diagnostics=None, chain="base",
        )
        rollup_b = json.loads(rollup_path.read_text(encoding="utf-8"))
        assert rollup_b["supervisor_end_utc"] is None
        assert rollup_b["session"]["session_id"] == "sid-B"


class TestScoringBlackholeCounters:
    """Reviewer post-20m-control fix #3: top-level counters for windows
    with events but no fast scoring, classified by whether the bridge
    even matched a pool. Lets reviewer differentiate NO_BRIDGE_HIT (pool
    universe too narrow) from BRIDGE_HIT_NOT_SCORED (admission filter
    rejected) without per-window log archaeology.
    """

    def test_no_bridge_hit_increments_both_counters(
        self, tmp_path, monkeypatch
    ):
        import m7.orderflow.hot_runtime_artifacts as hra

        rollup_path = tmp_path / "m7_hot_rollup_latest.json"
        monkeypatch.setattr(hra._rio, "_HOT_ROLLUP_PATH", str(rollup_path))
        monkeypatch.setattr(hra._rio, "_SESSION_ID", "sid-bh-1", raising=False)

        hra._update_hot_rollup(
            events_count=5, fast_results=[], guard_results=None,
            bridge_diagnostics={"bridge_pool_address_hit_count": 0},
            chain="base",
        )
        rollup = json.loads(rollup_path.read_text(encoding="utf-8"))
        assert rollup["windows_events_without_fast_score_total"] == 1
        assert rollup["windows_events_without_bridge_hit_total"] == 1

    def test_bridge_hit_but_not_scored_only_increments_outer(
        self, tmp_path, monkeypatch
    ):
        import m7.orderflow.hot_runtime_artifacts as hra

        rollup_path = tmp_path / "m7_hot_rollup_latest.json"
        monkeypatch.setattr(hra._rio, "_HOT_ROLLUP_PATH", str(rollup_path))
        monkeypatch.setattr(hra._rio, "_SESSION_ID", "sid-bh-2", raising=False)

        hra._update_hot_rollup(
            events_count=5, fast_results=[], guard_results=None,
            bridge_diagnostics={"bridge_pool_address_hit_count": 2},
            chain="base",
        )
        rollup = json.loads(rollup_path.read_text(encoding="utf-8"))
        # Outer counter increments (no fast score) but the bridge-hit
        # subcounter MUST NOT increment (we DID get a bridge hit).
        assert rollup["windows_events_without_fast_score_total"] == 1
        assert rollup.get("windows_events_without_bridge_hit_total", 0) == 0

    def test_zero_events_does_not_count(
        self, tmp_path, monkeypatch
    ):
        import m7.orderflow.hot_runtime_artifacts as hra

        rollup_path = tmp_path / "m7_hot_rollup_latest.json"
        monkeypatch.setattr(hra._rio, "_HOT_ROLLUP_PATH", str(rollup_path))
        monkeypatch.setattr(hra._rio, "_SESSION_ID", "sid-bh-3", raising=False)

        hra._update_hot_rollup(
            events_count=0, fast_results=[], guard_results=None,
            bridge_diagnostics={"bridge_pool_address_hit_count": 0},
            chain="base",
        )
        rollup = json.loads(rollup_path.read_text(encoding="utf-8"))
        # No events => neither counter must increment.
        assert rollup.get("windows_events_without_fast_score_total", 0) == 0
        assert rollup.get("windows_events_without_bridge_hit_total", 0) == 0


class TestE146CurrentSessionWindow:
    """E1.46 reviewer fix #5: split supervisor_window into historical
    (cumulative) and current_session_window (fresh per session)."""

    def test_current_session_window_block_present(self, tmp_path, monkeypatch):
        _, rollup = _call_rollup(
            tmp_path, monkeypatch, events_count=4, fast_results=[],
        )
        csw = rollup.get("current_session_window")
        assert csw is not None
        assert csw["events_total"] == 4
        assert csw["elapsed_minutes"] is not None
        assert csw["events_per_minute"] is not None
        # Historical alias of supervisor_window must exist alongside.
        assert "historical_window" in rollup
        assert rollup["historical_window"] == rollup["supervisor_window"]

    def test_current_session_window_resets_on_new_session(
        self, tmp_path, monkeypatch
    ):
        import m7.orderflow.hot_runtime_artifacts as hra

        rollup_path = tmp_path / "m7_hot_rollup_latest.json"
        monkeypatch.setattr(hra._rio, "_HOT_ROLLUP_PATH", str(rollup_path))

        monkeypatch.setattr(hra._rio, "_SESSION_ID", "sid-A", raising=False)
        hra._update_hot_rollup(
            events_count=10, fast_results=[], guard_results=None,
            bridge_diagnostics=None, chain="base",
        )
        rollup = json.loads(rollup_path.read_text(encoding="utf-8"))
        assert rollup["current_session_window"]["events_total"] == 10

        # New session_id -> session counters reset, csw must reflect new
        # session only (NOT cumulative).
        monkeypatch.setattr(hra._rio, "_SESSION_ID", "sid-B", raising=False)
        hra._update_hot_rollup(
            events_count=2, fast_results=[], guard_results=None,
            bridge_diagnostics=None, chain="base",
        )
        rollup = json.loads(rollup_path.read_text(encoding="utf-8"))
        assert rollup["current_session_window"]["events_total"] == 2
        # supervisor_window/historical_window keeps accumulating.
        assert rollup["supervisor_window"]["events_total"] == 12


class TestE146SessionBridgeHitNotScoredHistogram:
    """E1.46 reviewer fix #2: session-scoped fresh histogram for
    BRIDGE_HIT_NOT_SCORED reasons, not only lifetime cumulative."""

    def test_session_bridge_hit_not_scored_histogram_increments(
        self, tmp_path, monkeypatch
    ):
        bd = {
            "bridge_pool_address_hit_count": 1,
            "bridge_hit_not_scored_reason": "PAIR_FILTERED",
        }
        _, rollup = _call_rollup(
            tmp_path, monkeypatch, events_count=1, fast_results=[],
            bridge_diagnostics=bd,
        )
        sess = rollup["session"]
        srh = sess.get("session_bridge_hit_not_scored_reason_histogram")
        assert srh == {"PAIR_FILTERED": 1}
        assert sess.get("session_bridge_hit_not_scored_windows") == 1

    def test_session_bridge_hit_histogram_resets_on_new_session(
        self, tmp_path, monkeypatch
    ):
        import m7.orderflow.hot_runtime_artifacts as hra

        rollup_path = tmp_path / "m7_hot_rollup_latest.json"
        monkeypatch.setattr(hra._rio, "_HOT_ROLLUP_PATH", str(rollup_path))

        monkeypatch.setattr(hra._rio, "_SESSION_ID", "sid-A", raising=False)
        hra._update_hot_rollup(
            events_count=1, fast_results=[], guard_results=None,
            bridge_diagnostics={
                "bridge_pool_address_hit_count": 1,
                "bridge_hit_not_scored_reason": "PAIR_FILTERED",
            },
            chain="base",
        )
        # New session
        monkeypatch.setattr(hra._rio, "_SESSION_ID", "sid-B", raising=False)
        hra._update_hot_rollup(
            events_count=1, fast_results=[], guard_results=None,
            bridge_diagnostics={
                "bridge_pool_address_hit_count": 1,
                "bridge_hit_not_scored_reason": "TIER_COLD",
            },
            chain="base",
        )
        rollup = json.loads(rollup_path.read_text(encoding="utf-8"))
        # Lifetime histogram has both; session histogram has only new.
        lifetime = rollup["bridge_hit_but_not_fast_scored"]["reason_histogram"]
        assert lifetime.get("PAIR_FILTERED") == 1
        assert lifetime.get("TIER_COLD") == 1
        sess = rollup["session"]
        srh = sess["session_bridge_hit_not_scored_reason_histogram"]
        assert srh == {"TIER_COLD": 1}
        assert sess["session_bridge_hit_not_scored_windows"] == 1
