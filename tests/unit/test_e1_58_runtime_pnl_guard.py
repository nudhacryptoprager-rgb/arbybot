"""Unit tests for E1.58 fix step #6: runtime PnL guard / max-loss kill-switch."""

from __future__ import annotations

import pytest

from m7.orderflow import runtime_pnl_guard as rpg


def test_default_max_loss_wei_constant():
    assert rpg.DEFAULT_MAX_LOSS_WEI == 1_000_000_000


def test_apply_first_window_profit(monkeypatch):
    monkeypatch.delenv("ARBY_MAX_LOSS_WEI", raising=False)
    monkeypatch.delenv("ARBY_PNL_GUARD_RESET", raising=False)
    rollup = {}
    rpg.apply_runtime_pnl_guard(rollup, window_pnl_wei=500)
    assert rollup["runtime_pnl_cumulative_wei"] == 500
    assert rollup["runtime_pnl_window_count"] == 1
    assert rollup.get("kill_switch_active") in (False, None)
    assert rollup.get("runtime_pnl_blocker") in (None, False)
    assert rollup["runtime_pnl_max_loss_wei"] == rpg.DEFAULT_MAX_LOSS_WEI


def test_apply_accumulates_over_windows(monkeypatch):
    monkeypatch.delenv("ARBY_PNL_GUARD_RESET", raising=False)
    rollup = {}
    rpg.apply_runtime_pnl_guard(rollup, window_pnl_wei=100)
    rpg.apply_runtime_pnl_guard(rollup, window_pnl_wei=-30)
    rpg.apply_runtime_pnl_guard(rollup, window_pnl_wei=20)
    assert rollup["runtime_pnl_cumulative_wei"] == 90
    assert rollup["runtime_pnl_window_count"] == 3


def test_apply_none_pnl_treated_as_zero(monkeypatch):
    monkeypatch.delenv("ARBY_PNL_GUARD_RESET", raising=False)
    rollup = {}
    rpg.apply_runtime_pnl_guard(rollup, window_pnl_wei=None)
    assert rollup["runtime_pnl_cumulative_wei"] == 0
    assert rollup["runtime_pnl_window_count"] == 1


def test_kill_switch_trips_on_excess_loss(monkeypatch):
    monkeypatch.setenv("ARBY_MAX_LOSS_WEI", "1000")
    monkeypatch.delenv("ARBY_PNL_GUARD_RESET", raising=False)
    rollup = {}
    rpg.apply_runtime_pnl_guard(rollup, window_pnl_wei=-500)
    assert rollup.get("kill_switch_active") in (False, None)
    assert rollup.get("runtime_pnl_blocker") in (None,)
    rpg.apply_runtime_pnl_guard(rollup, window_pnl_wei=-600)
    assert rollup["runtime_pnl_cumulative_wei"] == -1100
    assert rollup["kill_switch_active"] is True
    assert rollup["runtime_pnl_blocker"] == "MAX_LOSS_EXCEEDED"


def test_kill_switch_recovery_clears_blocker(monkeypatch):
    monkeypatch.setenv("ARBY_MAX_LOSS_WEI", "100")
    monkeypatch.delenv("ARBY_PNL_GUARD_RESET", raising=False)
    rollup = {}
    rpg.apply_runtime_pnl_guard(rollup, window_pnl_wei=-200)
    assert rollup["kill_switch_active"] is True
    rpg.apply_runtime_pnl_guard(rollup, window_pnl_wei=300)
    assert rollup["runtime_pnl_cumulative_wei"] == 100
    assert rollup["kill_switch_active"] is False
    assert rollup["runtime_pnl_blocker"] is None


def test_explicit_reset_clears_state(monkeypatch):
    monkeypatch.delenv("ARBY_PNL_GUARD_RESET", raising=False)
    rollup = {
        "runtime_pnl_cumulative_wei": -5000,
        "runtime_pnl_window_count": 7,
        "kill_switch_active": True,
        "runtime_pnl_blocker": "MAX_LOSS_EXCEEDED",
    }
    monkeypatch.setenv("ARBY_PNL_GUARD_RESET", "1")
    rpg.apply_runtime_pnl_guard(rollup, window_pnl_wei=42)
    assert rollup["runtime_pnl_cumulative_wei"] == 0
    assert rollup["runtime_pnl_window_count"] == 0
    assert rollup["kill_switch_active"] is False
    assert rollup["runtime_pnl_blocker"] is None
    assert rollup["runtime_pnl_reset_requested"] is True


def test_invalid_max_loss_env_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("ARBY_MAX_LOSS_WEI", "not-a-number")
    monkeypatch.delenv("ARBY_PNL_GUARD_RESET", raising=False)
    rollup = {}
    rpg.apply_runtime_pnl_guard(rollup, window_pnl_wei=-100)
    assert rollup["runtime_pnl_max_loss_wei"] == rpg.DEFAULT_MAX_LOSS_WEI


def test_external_kill_switch_true_preserved(monkeypatch):
    """If kill_switch_active=True is set by another guard (e.g. profile-level),
    the runtime PnL guard must not clear it just because PnL is healthy.
    """
    monkeypatch.setenv("ARBY_MAX_LOSS_WEI", "10000")
    monkeypatch.delenv("ARBY_PNL_GUARD_RESET", raising=False)
    rollup = {"kill_switch_active": True, "runtime_pnl_blocker": "EXTERNAL_BLOCK"}
    rpg.apply_runtime_pnl_guard(rollup, window_pnl_wei=100)
    # blocker is non-MAX_LOSS_EXCEEDED → stays True
    assert rollup["kill_switch_active"] is True
    assert rollup["runtime_pnl_blocker"] == "EXTERNAL_BLOCK"
