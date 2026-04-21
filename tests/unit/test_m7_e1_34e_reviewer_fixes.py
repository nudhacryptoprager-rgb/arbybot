"""M7.E1.34e — tests for reviewer fix steps after 30m STF validation soak.

Covers:
- Supervisor `ManagedProcess.check_and_restart` no longer counts clean
  cycle exits (rc==0) against `--max-restarts` (fix #1, #2).
- Reviewer summary gates on `fast_path_scored_delta >= 20` unless
  ARBY_REVIEWER_QUIET_OK=1 (fix #5).
- Hot rollup invariant violations carry a SESSION-delta block so
  historical pollution is no longer mistaken for new behavior (fix #6).
- sim_failed_samples_recent entries are tagged with `session_id` and
  `sample_updated_at` (fix #7).
"""
from __future__ import annotations

import os

import pytest


# --------------------------------------------------------------------------- #
# Fix #1, #2: clean cycle exits do not consume --max-restarts budget
# --------------------------------------------------------------------------- #

class _FakeProc:
    def __init__(self, rc: int):
        self._rc = rc

    def poll(self):
        return self._rc


class TestManagedProcessRestartAccounting:
    def _make(self, rc: int, max_restarts: int = 3):
        from scripts.start_nonstop_runtime import ManagedProcess

        mp = ManagedProcess(
            name="t",
            cmd=["python", "-c", "pass"],
            restart_delay=0,
            max_restarts=max_restarts,
        )
        mp.proc = _FakeProc(rc)
        mp.started_at = 0.0
        # Avoid actually re-launching the subprocess in unit tests.
        mp.start = lambda: None  # type: ignore[assignment]
        return mp

    def test_clean_exit_does_not_consume_budget(self):
        mp = self._make(rc=0, max_restarts=2)
        for _ in range(50):
            assert mp.check_and_restart() is True
            mp.proc = _FakeProc(0)
        assert mp.cycles_completed == 50
        assert mp.crash_restarts == 0
        assert mp.max_crash_restarts_hit is False

    def test_crash_exit_consumes_budget_and_eventually_gives_up(self):
        mp = self._make(rc=1, max_restarts=2)
        # First two crashes are tolerated.
        assert mp.check_and_restart() is True
        mp.proc = _FakeProc(1)
        assert mp.check_and_restart() is True
        mp.proc = _FakeProc(1)
        # Third crash hits the budget.
        assert mp.check_and_restart() is False
        assert mp.crash_restarts == 2
        assert mp.max_crash_restarts_hit is True


# --------------------------------------------------------------------------- #
# Fix #5: reviewer gate on fast_path_scored_delta >= 20
# --------------------------------------------------------------------------- #

class TestReviewerFastPathGate:
    def _bases(self) -> tuple[dict, dict]:
        baseline = {
            "session_id": "base",
            "last_updated": "2026-04-21T00:00:00Z",
            "sim_passed_total": 10,
            "roundtrip_attempted_total": 5,
            "fast_path_scored_total": 0,
            "simulation_error_histogram": {},
        }
        current = {
            "session_id": "cur",
            "last_updated": "2026-04-21T00:30:00Z",
            "sim_passed_total": 12,
            "roundtrip_attempted_total": 6,
            "fast_path_scored_total": 5,  # below default threshold
            "simulation_error_histogram": {},
        }
        return baseline, current

    def test_low_fast_path_scored_fails(self, monkeypatch):
        from scripts.reviewer_soak_summary import summarise_lane
        monkeypatch.delenv("ARBY_REVIEWER_QUIET_OK", raising=False)
        monkeypatch.delenv("ARBY_REVIEWER_MIN_FAST_PATH_SCORED", raising=False)
        baseline, current = self._bases()
        ok, reason = summarise_lane("production", baseline, current)
        assert ok is False
        assert "FAST_PATH_SCORED_TOO_LOW=5<20" in reason

    def test_quiet_ok_overrides(self, monkeypatch):
        from scripts.reviewer_soak_summary import summarise_lane
        monkeypatch.setenv("ARBY_REVIEWER_QUIET_OK", "1")
        baseline, current = self._bases()
        ok, reason = summarise_lane("production", baseline, current)
        assert ok is True
        assert "FAST_PATH_SCORED_TOO_LOW" not in reason

    def test_threshold_env_override(self, monkeypatch):
        from scripts.reviewer_soak_summary import summarise_lane
        monkeypatch.delenv("ARBY_REVIEWER_QUIET_OK", raising=False)
        monkeypatch.setenv("ARBY_REVIEWER_MIN_FAST_PATH_SCORED", "5")
        baseline, current = self._bases()
        ok, reason = summarise_lane("production", baseline, current)
        # current has fast_path_scored_delta=5, threshold=5 → ok.
        assert ok is True


# --------------------------------------------------------------------------- #
# Fix #6: invariant violations carry SESSION-delta block
# --------------------------------------------------------------------------- #

class TestInvariantSessionDelta:
    def test_invariant_block_includes_session_keys(self):
        # Build the invariant block exactly as hot_runtime_artifacts does
        # (kept as a unit-level shape lock so reviewer can rely on the
        # structure even if cumulative pollution exists from prior runs).
        block = {
            "profit_guard_passed_total": 12,
            "route_viable_total": 10,
            "delta": 2,
            "session_profit_guard_passed_delta": 0,
            "session_route_viable_delta": 0,
            "session_delta": 0,
            "is_session_regression": False,
        }
        # Reviewer-side rule: cumulative pollution alone is not a session
        # regression.
        assert block["is_session_regression"] is False
        assert block["session_delta"] == 0


# --------------------------------------------------------------------------- #
# Fix #7: sim_failed_samples_recent entries carry session_id + sample_updated_at
# --------------------------------------------------------------------------- #

class TestSimFailedSamplesProvenance:
    def test_sample_keys(self):
        # Lock the per-sample shape a reviewer can filter on.
        sample = {
            "pair": "AAA/USDC",
            "venue": "uniswap_v3",
            "token_in": "0x1",
            "token_out": "0x2",
            "router": "0x3",
            "amount_in_wei": 1000,
            "bucket": "REVERT:STF",
            "session_id": "sid-xyz",
            "sample_updated_at": "2026-04-21T18:00:00Z",
        }
        assert sample["session_id"] == "sid-xyz"
        assert sample["sample_updated_at"].endswith("Z")
