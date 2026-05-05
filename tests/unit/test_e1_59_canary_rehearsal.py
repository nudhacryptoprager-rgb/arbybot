"""E1.59 step #9: canary dry-run rehearsal aggregator."""

from __future__ import annotations

import pytest

from m7.orderflow import canary_rehearsal as cr


@pytest.fixture(autouse=True)
def _enable(monkeypatch):
    monkeypatch.setenv("ARBY_CANARY_REHEARSAL", "1")
    monkeypatch.setenv("ARBY_CANARY_DRY_RUN", "1")
    cr.reset()
    yield


def test_disabled_runs_helpers_without_recording(monkeypatch):
    monkeypatch.setenv("ARBY_CANARY_REHEARSAL", "0")
    cr.reset()
    rollup = {}
    out = cr.rehearse(owner="0xO", chain="base", rollup=rollup, window_pnl_wei=0)
    assert out["canary"]["status"] == "dry_run_submitted"
    snap = cr.snapshot()
    assert snap["rehearsals_total"] == 0


def test_rehearse_passes_when_pnl_positive():
    rollup = {}
    out = cr.rehearse(owner="0xO", chain="base", rollup=rollup, window_pnl_wei=1_000)
    assert out["ok"] is True
    assert out["canary"]["status"] == "dry_run_submitted"
    assert out["canary"]["tx_hash"] is not None
    assert out["pnl_guard"]["kill_switch_active"] is False
    snap = cr.snapshot()
    assert snap["rehearsals_total"] == 1
    assert snap["canary_dry_run_submitted"] == 1
    assert snap["pnl_guard_passes"] == 1


def test_rehearse_trips_kill_switch_on_large_loss(monkeypatch):
    monkeypatch.setenv("ARBY_MAX_LOSS_WEI", "100")
    rollup = {}
    out = cr.rehearse(owner="0xO", chain="base", rollup=rollup, window_pnl_wei=-10_000)
    assert out["ok"] is False
    assert out["pnl_guard"]["kill_switch_active"] is True
    snap = cr.snapshot()
    assert snap["pnl_guard_kill_switch_trips"] == 1


def test_canary_rejected_on_missing_owner():
    rollup = {}
    out = cr.rehearse(owner="", chain="base", rollup=rollup, window_pnl_wei=0)
    assert out["canary"]["status"] == "rejected"
    snap = cr.snapshot()
    assert snap["canary_rejected"] == 1


def test_recent_rehearsals_capped():
    for i in range(30):
        cr.rehearse(
            owner="0xO",
            chain="base",
            rollup={},
            window_pnl_wei=0,
            candidate_id=f"c{i}",
        )
    snap = cr.snapshot()
    assert len(snap["recent_rehearsals"]) == 20
    assert snap["recent_rehearsals"][-1]["candidate_id"] == "c29"


def test_rollup_is_mutated_in_place():
    rollup: dict = {}
    cr.rehearse(owner="0xO", chain="base", rollup=rollup, window_pnl_wei=500)
    assert "runtime_pnl_cumulative_wei" in rollup
    assert rollup["runtime_pnl_cumulative_wei"] == 500
