"""E1.59 runtime wiring tests.

Verifies that module snapshots appear in the hot rollup artifact and
that cold_immediate_sim calls the E1.59 instrumentation hooks when
their ARBY_* flags are ON.
"""
from __future__ import annotations

import os
import json
import tempfile
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _FakeGate:
    """Minimal ExecutionGateResult stub for cold_immediate_sim patches."""
    sim_attempted = 0
    sim_passed = 0
    submit_ready = 0
    guard_passed = []
    sim_errors = []
    sim_failed_samples = []
    sim_output_samples = []
    roundtrip_attempted = 0
    roundtrip_success = 0
    roundtrip_profitable_count = 0
    roundtrip_profit_bps_values = []
    roundtrip_errors = []
    submit_blockers = []
    submit_blockers_detail = []
    scorer_sim_divergence_samples = []
    simulation_backend = None
    l1_fee_wei = 0
    l1_fee_source = "not_applicable"
    l1_fee_calldata_len = 0
    l1_fee_calldata_kind = None
    guard_bypassed = False
    sim_disabled = False
    sim_blocker = None


# ---------------------------------------------------------------------------
# Test: _update_hot_rollup merges E1.59 module snapshots
# ---------------------------------------------------------------------------

def _rollup_with_modules(tmp_path, monkeypatch, flags: dict) -> dict:
    """Run _update_hot_rollup with given flags and return the written rollup."""
    for k, v in flags.items():
        monkeypatch.setenv(k, v)

    rollup_path = str(tmp_path / "rollup.json")
    monkeypatch.setattr("m7.orderflow.runtime_io._HOT_ROLLUP_PATH", rollup_path)

    # Pre-populate modules with data so snapshots are non-empty
    if flags.get("ARBY_REVERT_TAXONOMY") == "1":
        from m7.orderflow.revert_taxonomy import reset as rt_reset, record as rt_rec
        rt_reset()
        rt_rec("REVERT:STF", pair="A/B", fee=500, pool="0x1", size_wei=100, block=1, extra={})

    if flags.get("ARBY_POOL_PROMOTION") == "1":
        from m7.orderflow.disc_to_prod_pool_promotion import reset as pp_reset, observe_profitable as pp_obs
        pp_reset()
        pp_obs(pool="0xAAA", pair="A/B", chain="base", profit_bps=50.0)

    if flags.get("ARBY_EXECUTION_PREFLIGHT") == "1":
        from m7.orderflow.preflight_aggregator import reset as pfa_reset, record as pfa_rec
        pfa_reset()
        pfa_rec(["PREFLIGHT_ROUTER_NO_CODE"], router="0xR")

    if flags.get("ARBY_CANARY_REHEARSAL") == "1":
        monkeypatch.setenv("ARBY_CANARY_DRY_RUN", "1")
        from m7.orderflow.canary_rehearsal import reset as cr_reset, rehearse as cr_run
        cr_reset()
        cr_run(owner="0xO", chain="base", rollup={}, window_pnl_wei=100)

    if flags.get("ARBY_SIM_V1_DRY_COMPARE") == "1":
        from execution.sim_v1_dry_compare import reset_stats as sv_reset, compare_results, SimResult
        sv_reset()
        r = SimResult(success=True, revert_reason=None, profit_bps=10.0, gas_used=100000)
        compare_results(r, r, candidate_id="test")

    if flags.get("ARBY_PROVIDER_THROTTLE") == "1":
        from core.provider_throttle import provider_throttle
        provider_throttle.reset()
        provider_throttle.acquire("calls", blocking=False)

    from m7.orderflow.hot_runtime_artifacts import _update_hot_rollup
    _update_hot_rollup(
        events_count=0,
        fast_results=[],
        guard_results=[],
        bridge_diagnostics={},
        ws_live_stats=None,
        hot_active_pools={},
        bridge={},
        chain="base",
        gate_result=None,
        extra_signal_counts=None,
    )

    with open(rollup_path) as f:
        return json.load(f)


def test_rollup_merges_revert_taxonomy_when_enabled(tmp_path, monkeypatch):
    rollup = _rollup_with_modules(tmp_path, monkeypatch, {"ARBY_REVERT_TAXONOMY": "1"})
    assert "revert_taxonomy" in rollup
    assert rollup["revert_taxonomy"]["total"] > 0


def test_rollup_no_revert_taxonomy_when_disabled(tmp_path, monkeypatch):
    rollup = _rollup_with_modules(tmp_path, monkeypatch, {"ARBY_REVERT_TAXONOMY": "0"})
    assert "revert_taxonomy" not in rollup


def test_rollup_merges_pool_promotion_when_enabled(tmp_path, monkeypatch):
    rollup = _rollup_with_modules(tmp_path, monkeypatch, {"ARBY_POOL_PROMOTION": "1"})
    assert "pool_promotion" in rollup
    assert rollup["pool_promotion"]["active_count"] > 0


def test_rollup_merges_preflight_aggregator_when_enabled(tmp_path, monkeypatch):
    rollup = _rollup_with_modules(
        tmp_path, monkeypatch,
        {"ARBY_EXECUTION_PREFLIGHT": "1"},
    )
    assert "preflight_aggregator" in rollup
    assert rollup["preflight_aggregator"]["blocked_total"] == 1


def test_rollup_merges_canary_rehearsal_when_enabled(tmp_path, monkeypatch):
    rollup = _rollup_with_modules(
        tmp_path, monkeypatch,
        {"ARBY_CANARY_REHEARSAL": "1", "ARBY_CANARY_DRY_RUN": "1"},
    )
    assert "canary_rehearsal" in rollup
    assert rollup["canary_rehearsal"]["rehearsals_total"] > 0


def test_rollup_merges_sim_v1_when_enabled(tmp_path, monkeypatch):
    rollup = _rollup_with_modules(tmp_path, monkeypatch, {"ARBY_SIM_V1_DRY_COMPARE": "1"})
    assert "sim_v1_dry_compare" in rollup
    assert rollup["sim_v1_dry_compare"]["samples_total"] > 0


def test_rollup_merges_provider_throttle_when_enabled(tmp_path, monkeypatch):
    rollup = _rollup_with_modules(tmp_path, monkeypatch, {"ARBY_PROVIDER_THROTTLE": "1"})
    assert "provider_throttle" in rollup
    assert "calls" in rollup["provider_throttle"]


# ---------------------------------------------------------------------------
# Test: cold_immediate_sim calls revert_taxonomy + preflight_aggregator
# ---------------------------------------------------------------------------

def test_cold_immediate_sim_feeds_revert_taxonomy(monkeypatch):
    """When ARBY_REVERT_TAXONOMY=1, sim errors are forwarded to revert_taxonomy."""
    monkeypatch.setenv("ARBY_COLD_IMMEDIATE_SIM", "1")
    monkeypatch.setenv("ARBY_COLD_IMMEDIATE_MIN_NET_BPS", "0")
    monkeypatch.setenv("ARBY_COLD_IMMEDIATE_TOP_N", "2")
    monkeypatch.setenv("ARBY_REVERT_TAXONOMY", "1")

    from m7.orderflow.revert_taxonomy import reset as rt_reset, snapshot as rt_snap
    rt_reset()

    # Patch run_execution_gate to return a gate with one REVERT error
    fake_gate = _FakeGate()
    fake_gate.sim_attempted = 1
    fake_gate.sim_errors = ["REVERT:STF:0xabc"]
    fake_gate.sim_failed_samples = [{"pair": "A/B", "buy_fee": 500, "amount_in_wei": 1000}]

    import m7.orderflow.execution_gate as _egate
    monkeypatch.setattr(_egate, "run_execution_gate", lambda *a, **kw: fake_gate)

    bridge = {
        "cold_executable": [
            {
                "pool_address": "0x1",
                "actual_pair": "A/B",
                "token_in": "0xTA",
                "token_out": "0xTB",
                "router": "0xROUTER",
                "buy_fee": 500,
                "net_bps": 10.0,
            },
        ]
    }
    from m7.orderflow.cold_immediate_sim import queue_cold_executable_for_sim
    queue_cold_executable_for_sim(bridge, chain="base", profile="production")

    snap = rt_snap()
    assert snap["total"] >= 1, f"expected taxonomy hit, got {snap}"


def test_cold_immediate_sim_feeds_preflight_aggregator(monkeypatch):
    """When ARBY_EXECUTION_PREFLIGHT=1, preflight_aggregator.record is called."""
    monkeypatch.setenv("ARBY_COLD_IMMEDIATE_SIM", "1")
    monkeypatch.setenv("ARBY_COLD_IMMEDIATE_MIN_NET_BPS", "0")
    monkeypatch.setenv("ARBY_COLD_IMMEDIATE_TOP_N", "2")
    monkeypatch.setenv("ARBY_EXECUTION_PREFLIGHT", "1")

    from m7.orderflow.preflight_aggregator import reset as pfa_reset, snapshot as pfa_snap
    pfa_reset()

    # Gate with one guard_passed candidate (no sim errors)
    fake_gate = _FakeGate()
    fake_gate.sim_passed = 1
    fake_gate.submit_ready = 1
    fake_gate.guard_passed = [(object(), None)]  # minimal stub

    import m7.orderflow.execution_gate as _egate
    monkeypatch.setattr(_egate, "run_execution_gate", lambda *a, **kw: fake_gate)
    # Patch run_preflight to return empty (pass)
    import m7.orderflow.preflight as _pf
    monkeypatch.setattr(_pf, "run_preflight", lambda **kw: [])

    bridge = {
        "cold_executable": [
            {
                "pool_address": "0x1",
                "actual_pair": "A/B",
                "token_in": "0xTA",
                "token_out": "0xTB",
                "router": "0xROUTER",
                "buy_fee": 500,
                "net_bps": 10.0,
            },
        ]
    }
    from m7.orderflow.cold_immediate_sim import queue_cold_executable_for_sim
    queue_cold_executable_for_sim(bridge, chain="base", profile="production")

    snap = pfa_snap()
    assert snap["candidates_total"] >= 1, f"expected preflight hit, got {snap}"
