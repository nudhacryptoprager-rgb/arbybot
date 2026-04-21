"""M7.E1.34g — tests for the 4 reviewer-driven diagnostics.

Covers:
- fix #1 funnel starvation: session_events_per_minute + session_elapsed_minutes.
- fix #2 bridge-drop reason propagation: loop_runner block 2 injects
  bridge_hit_not_scored_reason (shape-locked here via a helper-free fast
  classification test).
- fix #3 cost-model visibility: fast_path_net_bps_histogram bucketing.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest


def _call(tmp_path, monkeypatch, *, events_count, fast_results, bridge_diagnostics=None):
    import m7.orderflow.hot_runtime_artifacts as hra

    rollup_path = tmp_path / "m7_hot_rollup_latest.json"
    monkeypatch.setattr(hra._rio, "_HOT_ROLLUP_PATH", str(rollup_path))
    monkeypatch.setattr(hra._rio, "_SESSION_ID", "sid-g", raising=False)

    hra._update_hot_rollup(
        events_count=events_count,
        fast_results=fast_results,
        guard_results=None,
        bridge_diagnostics=bridge_diagnostics,
        ws_live_stats={
            "ws_connection_status": "connected",
            "ws_provider": "premium",
            "rpc_provider": "premium",
        },
        chain="base",
        gate_result=None,
    )
    return json.loads(rollup_path.read_text(encoding="utf-8"))


class TestFeedRateDiagnostic:
    def test_session_events_per_minute_populated(self, tmp_path, monkeypatch):
        rollup = _call(tmp_path, monkeypatch, events_count=5, fast_results=[])
        sess = rollup["session"]
        assert "session_elapsed_minutes" in sess
        assert sess["session_elapsed_minutes"] > 0
        assert "session_events_per_minute" in sess
        # With 5 events across a fresh session (< 1 min) the rate must be
        # >= 5 / 1.0 = 5.0 (session_elapsed_minutes clamped by denominator
        # floor 1/60 at minimum so the number never blows up).
        assert sess["session_events_per_minute"] >= 5.0

    def test_zero_events_does_not_nan(self, tmp_path, monkeypatch):
        rollup = _call(tmp_path, monkeypatch, events_count=0, fast_results=None)
        sess = rollup["session"]
        assert sess["session_events_per_minute"] == 0.0
        assert sess["session_elapsed_minutes"] >= 0.0


class TestNetBpsHistogram:
    def _r(self, bps):
        return SimpleNamespace(
            best_backrun_net_bps=bps,
            route_viable=False,
            profit_guard_passed=False,
            guard_reject_reason=None,
            scoring_path="registry_fast",
        )

    def test_buckets_classify_correctly(self, tmp_path, monkeypatch):
        fast = [
            self._r(-20),   # lt_-10
            self._r(-5),    # -10_to_-1
            self._r(-0.5),  # -1_to_0
            self._r(0.5),   # 0_to_1
            self._r(2),     # 1_to_5
            self._r(7),     # 5_to_10
            self._r(15),    # gte_10
            self._r(None),  # unknown
        ]
        rollup = _call(tmp_path, monkeypatch, events_count=8, fast_results=fast)
        hist = rollup["fast_path_net_bps_histogram"]
        assert hist["lt_-10"] == 1
        assert hist["-10_to_-1"] == 1
        assert hist["-1_to_0"] == 1
        assert hist["0_to_1"] == 1
        assert hist["1_to_5"] == 1
        assert hist["5_to_10"] == 1
        assert hist["gte_10"] == 1
        assert hist["unknown"] == 1

    def test_no_fast_results_no_histogram(self, tmp_path, monkeypatch):
        rollup = _call(tmp_path, monkeypatch, events_count=0, fast_results=[])
        assert "fast_path_net_bps_histogram" not in rollup


class TestBridgeReasonPropagation:
    """The code change lives in loop_runner.py; here we shape-lock the
    values it can inject so rollup reason_histogram stays stable."""

    def test_scoring_path_none_reason_routes_to_unknown_pair(self, tmp_path, monkeypatch):
        # Simulate loop_runner's upstream call: it already decided the
        # reason and passed it via bridge_diagnostics.
        rollup = _call(
            tmp_path,
            monkeypatch,
            events_count=1,
            fast_results=[],
            bridge_diagnostics={
                "bridge_pool_address_hit_count": 1,
                "bridge_hit_not_scored_reason": "HOT_SKIP_UNKNOWN_PAIR",
            },
        )
        rh = rollup["bridge_hit_but_not_fast_scored"]["reason_histogram"]
        assert rh.get("HOT_SKIP_UNKNOWN_PAIR") == 1

    def test_scoring_path_not_scored_reason(self, tmp_path, monkeypatch):
        rollup = _call(
            tmp_path,
            monkeypatch,
            events_count=1,
            fast_results=[],
            bridge_diagnostics={
                "bridge_pool_address_hit_count": 1,
                "bridge_hit_not_scored_reason": "NOT_SCORED",
            },
        )
        rh = rollup["bridge_hit_but_not_fast_scored"]["reason_histogram"]
        assert rh.get("NOT_SCORED") == 1
