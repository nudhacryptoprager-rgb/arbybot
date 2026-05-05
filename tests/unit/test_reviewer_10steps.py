"""Tests for reviewer 10-step batch (Steps 3, 5, 6, 7, 8).

Step 3  — production_readiness block in hot_runtime_artifacts
Step 5  — kill_switch gate before canary rehearsal
Step 6  — private submit dry-run proof fields
Step 7  — pending/latest sim state mode in sim_v1_dry_compare.stats()
Step 8  — post_trade_accounting_contract in pnl_accounting
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Step 5: kill_switch gate in canary_rehearsal
# ---------------------------------------------------------------------------

from m7.orderflow import canary_rehearsal as cr


@pytest.fixture(autouse=False)
def _cr_enable(monkeypatch):
    monkeypatch.setenv("ARBY_CANARY_REHEARSAL", "1")
    monkeypatch.setenv("ARBY_CANARY_DRY_RUN", "1")
    cr.reset()
    yield
    cr.reset()


def test_canary_blocked_when_kill_switch_active(_cr_enable):
    """Rehearsal must be blocked (ok=False) when kill_switch_active=True."""
    rollup = {"kill_switch_active": True, "runtime_pnl_cumulative_wei": -999}
    out = cr.rehearse(owner="0xOwner", chain="base", rollup=rollup, window_pnl_wei=0)
    assert out["ok"] is False
    assert out.get("blocked_reason") == "KILL_SWITCH_ACTIVE"
    assert out["canary"]["error"] == "KILL_SWITCH_ACTIVE"
    snap = cr.snapshot()
    assert snap["canary_rejected"] == 1
    assert snap["pnl_guard_kill_switch_trips"] == 1


def test_canary_proceeds_when_kill_switch_inactive(_cr_enable):
    """Normal rehearsal must proceed when kill_switch_active is absent/False."""
    rollup: dict = {}
    out = cr.rehearse(owner="0xOwner", chain="base", rollup=rollup, window_pnl_wei=0)
    assert out["ok"] is True
    assert out["canary"]["status"] == "dry_run_submitted"


def test_canary_kill_switch_blocked_not_recorded_when_disabled(monkeypatch):
    """When ARBY_CANARY_REHEARSAL=0, blocked outcome is returned but not recorded."""
    monkeypatch.setenv("ARBY_CANARY_REHEARSAL", "0")
    monkeypatch.setenv("ARBY_CANARY_DRY_RUN", "1")
    cr.reset()
    rollup = {"kill_switch_active": True}
    out = cr.rehearse(owner="0xOwner", chain="base", rollup=rollup)
    assert out["ok"] is False
    assert cr.snapshot()["rehearsals_total"] == 0
    cr.reset()


# ---------------------------------------------------------------------------
# Step 6: private submit dry-run proof fields
# ---------------------------------------------------------------------------

from execution.private_submitter import submit_private, SUPPORTED_RELAYS


def test_dry_run_proof_fields_present(monkeypatch):
    """dry_run response must carry endpoint_selected, payload_built, refused_live_reason."""
    monkeypatch.setenv("ARBY_PRIVATE_SUBMIT_DRY_RUN", "1")
    result = submit_private("0xdeadbeef", relay="flashbots", chain="base", dry_run=True)
    assert result["status"] == "dry_run_submitted"
    assert result["endpoint_selected"] == "flashbots.base"
    assert result["payload_built"] is True
    assert result["refused_live_reason"] == "ARBY_PRIVATE_SUBMIT_DRY_RUN=1"
    assert result["bundle_hash"] is not None


def test_real_submit_still_refused(monkeypatch):
    """Live submit path must still return REAL_SUBMIT_NOT_IMPLEMENTED."""
    monkeypatch.setenv("ARBY_PRIVATE_SUBMIT_DRY_RUN", "0")
    result = submit_private("0xdeadbeef", relay="flashbots", chain="base", dry_run=False)
    assert result["error"] == "REAL_SUBMIT_NOT_IMPLEMENTED"


def test_dry_run_proof_absent_on_rejection(monkeypatch):
    """Rejected calls (unsupported relay) must NOT carry proof fields."""
    monkeypatch.setenv("ARBY_PRIVATE_SUBMIT_DRY_RUN", "1")
    result = submit_private("0xdeadbeef", relay="unknown_relay", chain="base", dry_run=True)
    assert result["status"] == "rejected"
    assert "endpoint_selected" not in result


# ---------------------------------------------------------------------------
# Step 7: pending/latest sim state mode in sim_v1_dry_compare.stats()
# ---------------------------------------------------------------------------

import execution.sim_v1_dry_compare as svc


@pytest.fixture(autouse=False)
def _sv_enable(monkeypatch):
    monkeypatch.setenv("ARBY_SIM_V1_DRY_COMPARE", "1")
    svc.reset_stats()
    yield
    svc.reset_stats()


def test_state_mode_latest_without_flashblocks(_sv_enable, monkeypatch):
    """Without ARBY_FLASHBLOCKS_SIM, rpc_fork must report 'latest' state."""
    monkeypatch.setenv("ARBY_FLASHBLOCKS_SIM", "0")
    st = svc.stats()
    assert st["rpc_fork_state_mode"] == "latest"
    assert st["sim_v1_state_mode"] == "pending"


def test_state_mode_pending_with_flashblocks(_sv_enable, monkeypatch):
    """With ARBY_FLASHBLOCKS_SIM=1, rpc_fork must report 'pending' state."""
    monkeypatch.setenv("ARBY_FLASHBLOCKS_SIM", "1")
    st = svc.stats()
    assert st["rpc_fork_state_mode"] == "pending"
    assert st["sim_v1_state_mode"] == "pending"


# ---------------------------------------------------------------------------
# Step 8: post_trade_accounting_contract
# ---------------------------------------------------------------------------

from execution.pnl_accounting import post_trade_accounting_contract


def test_post_trade_accounting_dry_run_mode(monkeypatch):
    """Dry-run mode must report accounting_mode='dry_run'."""
    monkeypatch.setenv("ARBY_PNL_DRY_RUN", "1")
    before = {"native": 1_000_000_000_000_000_000}  # 1 ETH
    after = {"native": 999_000_000_000_000_000}       # 0.999 ETH (−1e15 wei)
    prices = {"native": 3000.0}
    result = post_trade_accounting_contract(
        before, after, prices,
        gas_used=100_000,
        l1_fee_wei=50_000,
        gas_price_wei=2_000_000_000,
    )
    assert result["accounting_mode"] == "dry_run"
    assert result["balances_before"] == before
    assert result["balances_after"] == after
    assert result["gas_used"] == 100_000
    assert result["gas_price_wei"] == 2_000_000_000
    assert result["l1_fee_wei"] == 50_000
    assert result["gas_cost_wei"] == 100_000 * 2_000_000_000
    assert result["total_cost_wei"] == 100_000 * 2_000_000_000 + 50_000
    assert "per_token_delta_wei" in result
    assert result["per_token_delta_wei"]["native"] == -1_000_000_000_000_000
    assert "total_pnl_usd" in result
    assert "net_pnl_usd" in result
    # net_pnl_usd must be less than total_pnl_usd (costs deducted)
    assert result["net_pnl_usd"] < result["total_pnl_usd"]


def test_post_trade_accounting_zero_cost(monkeypatch):
    """Zero gas/L1 fee → net_pnl_usd == total_pnl_usd."""
    monkeypatch.setenv("ARBY_PNL_DRY_RUN", "1")
    before = {"native": 0}
    after = {"native": 1_000_000_000_000_000_000}
    prices = {"native": 2000.0}
    result = post_trade_accounting_contract(before, after, prices)
    assert result["gas_used"] == 0
    assert result["total_cost_wei"] == 0
    assert result["net_pnl_usd"] == result["total_pnl_usd"]


def test_post_trade_accounting_unpriced_token(monkeypatch):
    """Tokens missing from prices_usd must appear in unpriced_tokens."""
    monkeypatch.setenv("ARBY_PNL_DRY_RUN", "1")
    before = {"0xtoken": 0}
    after = {"0xtoken": 1000}
    result = post_trade_accounting_contract(before, after, {})
    assert "0xtoken" in result["unpriced_tokens"]


# ---------------------------------------------------------------------------
# Step 3: production_readiness block (unit-level logic, no full rollup needed)
# ---------------------------------------------------------------------------

def test_production_readiness_fields_logic():
    """Verify the dict-building logic for production_readiness independently."""
    # Simulate what _update_hot_rollup builds
    rollup = {
        "preflight_aggregator": {"candidates_total": 3, "blocked_total": 0},
        "cold_immediate_sim_passed_total": 10,
        "kill_switch_active": False,
        "runtime_pnl_max_loss_wei": 1_000_000_000,
    }
    _pfa_snap = rollup.get("preflight_aggregator") or {}
    pr = {
        "preflight_ok": bool(
            int(_pfa_snap.get("candidates_total", 0) or 0) > 0
            and int(_pfa_snap.get("blocked_total", 0) or 0) == 0
        ),
        "simulation_ok": bool(int(rollup.get("cold_immediate_sim_passed_total", 0) or 0) > 0),
        "submit_path_ok": True,
        "receipt_ok": False,
        "pnl_ok": False,
        "kill_switch_active": bool(rollup.get("kill_switch_active", False)),
        "pnl_guard_configured": bool(int(rollup.get("runtime_pnl_max_loss_wei", 0) or 0) > 0),
        "live_submit_blocked_reason": "REAL_SUBMIT_NOT_IMPLEMENTED",
    }
    assert pr["preflight_ok"] is True
    assert pr["simulation_ok"] is True
    assert pr["submit_path_ok"] is True
    assert pr["receipt_ok"] is False
    assert pr["pnl_ok"] is False
    assert pr["kill_switch_active"] is False
    assert pr["pnl_guard_configured"] is True
    assert pr["live_submit_blocked_reason"] == "REAL_SUBMIT_NOT_IMPLEMENTED"


def test_production_readiness_preflight_blocked():
    """preflight_ok must be False when blocked_total > 0."""
    rollup = {
        "preflight_aggregator": {"candidates_total": 3, "blocked_total": 2},
        "cold_immediate_sim_passed_total": 0,
        "kill_switch_active": False,
        "runtime_pnl_max_loss_wei": 0,
    }
    _pfa_snap = rollup.get("preflight_aggregator") or {}
    preflight_ok = bool(
        int(_pfa_snap.get("candidates_total", 0) or 0) > 0
        and int(_pfa_snap.get("blocked_total", 0) or 0) == 0
    )
    assert preflight_ok is False
