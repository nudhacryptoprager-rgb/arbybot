"""M7.E1.34f — tests for reviewer fix batch after 30m E1.34e validation soak.

Covers:
- Per-lane freshness anchors (last_heartbeat_utc / last_event_utc /
  last_scored_utc) in hot rollup (fix #3).
- bridge_hit_but_not_fast_scored diagnostic bucket (fix #5).
- reviewer_soak_summary staleness anchored to supervisor-end UTC,
  not wall-clock (fix #2).
- reviewer_soak_summary fresh_failed_samples filters by current
  session_id (fix #7).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


# --------------------------------------------------------------------------- #
# Fix #3 + #5: hot rollup timestamps + bridge-hit diagnostic
# --------------------------------------------------------------------------- #

class TestHotRollupHeartbeatAnchors:
    def _call_update(
        self,
        tmp_path,
        monkeypatch,
        events_count: int,
        fast_results: list | None,
        bridge_diagnostics: dict | None,
    ):
        # Isolate rolling artifact paths to tmp dir.
        import m7.orderflow.hot_runtime_artifacts as hra

        rollup_path = tmp_path / "m7_hot_rollup_latest.json"
        monkeypatch.setattr(hra._rio, "_HOT_ROLLUP_PATH", str(rollup_path))
        monkeypatch.setattr(hra._rio, "_SESSION_ID", "test-sid", raising=False)

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

    def test_last_heartbeat_always_set(self, tmp_path, monkeypatch):
        rollup = self._call_update(tmp_path, monkeypatch, 0, None, None)
        assert rollup.get("last_heartbeat_utc")
        # No events, no scoring → last_event_utc / last_scored_utc absent.
        assert "last_event_utc" not in rollup
        assert "last_scored_utc" not in rollup

    def test_last_event_moves_only_on_events(self, tmp_path, monkeypatch):
        rollup = self._call_update(tmp_path, monkeypatch, 3, None, None)
        assert rollup.get("last_event_utc")
        assert "last_scored_utc" not in rollup

    def test_last_scored_moves_only_on_fast_results(self, tmp_path, monkeypatch):
        class _R:
            best_backrun_net_bps = 5
            route_viable = True
            profit_guard_passed = True
            guard_reject_reason = None

        rollup = self._call_update(tmp_path, monkeypatch, 1, [_R()], None)
        assert rollup.get("last_scored_utc")

    def test_bridge_hit_without_fast_scored_diagnostic(self, tmp_path, monkeypatch):
        rollup = self._call_update(
            tmp_path,
            monkeypatch,
            events_count=1,
            fast_results=[],
            bridge_diagnostics={
                "bridge_pool_address_hit_count": 2,
                "bridge_hit_not_scored_reason": "UNKNOWN_PAIR",
            },
        )
        diag = rollup.get("bridge_hit_but_not_fast_scored") or {}
        assert diag.get("windows") == 1
        assert diag.get("bridge_hits") == 2
        assert diag.get("reason_histogram", {}).get("UNKNOWN_PAIR") == 1

    def test_bridge_hit_with_fast_scored_no_diagnostic(self, tmp_path, monkeypatch):
        class _R:
            best_backrun_net_bps = 5
            route_viable = True
            profit_guard_passed = True
            guard_reject_reason = None

        rollup = self._call_update(
            tmp_path,
            monkeypatch,
            events_count=1,
            fast_results=[_R()],
            bridge_diagnostics={"bridge_pool_address_hit_count": 1},
        )
        assert "bridge_hit_but_not_fast_scored" not in rollup


# --------------------------------------------------------------------------- #
# Fix #7: fresh_failed_samples helper filters by session_id
# --------------------------------------------------------------------------- #

class TestFreshFailedSamples:
    def test_filters_to_current_session(self):
        from scripts.reviewer_soak_summary import fresh_failed_samples

        rollup = {
            "sim_failed_samples_recent": [
                {"pair": "A", "session_id": "old"},
                {"pair": "B", "session_id": "cur"},
                {"pair": "C", "session_id": "cur"},
                {"pair": "D"},  # untagged
            ],
        }
        fresh = fresh_failed_samples(rollup, "cur")
        assert [s["pair"] for s in fresh] == ["B", "C"]

    def test_empty_on_missing_session_id(self):
        from scripts.reviewer_soak_summary import fresh_failed_samples

        rollup = {"sim_failed_samples_recent": [{"pair": "X", "session_id": "any"}]}
        assert fresh_failed_samples(rollup, None) == []
        assert fresh_failed_samples(rollup, "") == []

    def test_empty_on_missing_list(self):
        from scripts.reviewer_soak_summary import fresh_failed_samples

        assert fresh_failed_samples({}, "cur") == []
        assert fresh_failed_samples({"sim_failed_samples_recent": None}, "cur") == []


# --------------------------------------------------------------------------- #
# Fix #2: staleness anchor CLI flag (argparse wiring)
# --------------------------------------------------------------------------- #

class TestStalenessAnchorFlag:
    def test_help_mentions_staleness_anchor(self):
        proc = subprocess.run(
            [sys.executable, "scripts/reviewer_soak_summary.py", "--help"],
            capture_output=True,
            text=True,
            cwd=str(Path(__file__).resolve().parents[2]),
        )
        assert proc.returncode == 0
        assert "--staleness-anchor-utc" in proc.stdout
        assert "supervisor end" in proc.stdout.lower()
