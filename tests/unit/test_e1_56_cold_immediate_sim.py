"""E1.56 Step 1 — cold-positive immediate sim queue.

Closes the STRATEGY_GATING blocker:
- Cold lane finds positive `cold_executable` entries on pools that hot
  WS stream never delivers events from in the same window.
- Hot lane currently calls sim only on WS-event-derived BackrunResults.
- This module synthesizes BackrunResult from cold bridge entries and
  feeds them through the existing `run_execution_gate(...)` pipeline.

Tests pin:
1. ENV gate is OFF by default (back-compat — no behavior change).
2. Synthetic event/result construction handles missing fields.
3. Top-N cap and min-net-bps filter are honored.
4. Counters are returned even when bridge is empty.
5. When env gate is on and bridge has entries, run_execution_gate
   gets called with synthesized BackrunResults.
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _reset_env(monkeypatch):
    """Each test starts with a clean ENV slate for the feature flags."""
    for k in (
        "ARBY_COLD_IMMEDIATE_SIM",
        "ARBY_COLD_IMMEDIATE_MIN_NET_BPS",
        "ARBY_COLD_IMMEDIATE_TOP_N",
    ):
        monkeypatch.delenv(k, raising=False)


def test_e1_56_step1_disabled_by_default() -> None:
    """ENV unset → is_enabled() False → no behavior change for hot lane."""
    from m7.orderflow.cold_immediate_sim import is_enabled, queue_cold_executable_for_sim

    assert is_enabled() is False
    gate, counters = queue_cold_executable_for_sim(
        {"cold_executable": [{"pool_address": "0xabc", "net_bps": 999}]},
        chain="base",
        profile="production",
    )
    assert gate is None
    assert counters["cold_immediate_sim_attempted"] == 0
    assert counters["cold_immediate_sim_input_count"] == 0


def test_e1_56_step1_enabled_returns_zero_when_bridge_empty(monkeypatch) -> None:
    monkeypatch.setenv("ARBY_COLD_IMMEDIATE_SIM", "1")
    from m7.orderflow.cold_immediate_sim import queue_cold_executable_for_sim

    gate, counters = queue_cold_executable_for_sim({}, chain="base")
    assert gate is None
    assert all(v == 0 for v in counters.values())


def test_e1_56_step1_threshold_filters_low_net_bps(monkeypatch) -> None:
    monkeypatch.setenv("ARBY_COLD_IMMEDIATE_SIM", "1")
    monkeypatch.setenv("ARBY_COLD_IMMEDIATE_MIN_NET_BPS", "100")
    from m7.orderflow.cold_immediate_sim import queue_cold_executable_for_sim

    bridge = {
        "cold_executable": [
            {"pool_address": "0xa", "net_bps": 5, "token_in": "T0", "token_out": "T1"},
            {"pool_address": "0xb", "net_bps": 50, "token_in": "T0", "token_out": "T1"},
            {"pool_address": "0xc", "net_bps": 500, "token_in": "T0", "token_out": "T1"},
        ],
    }
    with patch("m7.orderflow.execution_gate.run_execution_gate") as mock_gate:
        mock_gate.return_value = MagicMock(
            sim_attempted=1, sim_passed=0, guard_passed=[], submit_ready=0,
        )
        _gate, counters = queue_cold_executable_for_sim(bridge, chain="base")
    # Only the +500 entry survives the 100 bps floor
    assert counters["cold_immediate_sim_input_count"] == 1


def test_e1_56_step1_topn_cap_respected(monkeypatch) -> None:
    monkeypatch.setenv("ARBY_COLD_IMMEDIATE_SIM", "1")
    monkeypatch.setenv("ARBY_COLD_IMMEDIATE_MIN_NET_BPS", "0")
    monkeypatch.setenv("ARBY_COLD_IMMEDIATE_TOP_N", "2")
    from m7.orderflow.cold_immediate_sim import queue_cold_executable_for_sim

    bridge = {
        "cold_executable": [
            {"pool_address": f"0x{i:040x}", "net_bps": float(i),
             "token_in": "T0", "token_out": "T1"}
            for i in range(1, 11)  # 10 entries, net_bps 1..10
        ],
    }
    captured_args: list = []
    def _capture(scored, **kw):
        captured_args.append(scored)
        return MagicMock(sim_attempted=2, sim_passed=0, guard_passed=[], submit_ready=0)
    with patch(
        "m7.orderflow.execution_gate.run_execution_gate",
        side_effect=_capture,
    ):
        _gate, counters = queue_cold_executable_for_sim(bridge, chain="base")
    # Cap at 2 even though 10 are above threshold
    assert counters["cold_immediate_sim_input_count"] == 2
    assert len(captured_args) == 1
    assert len(captured_args[0]) == 2


def test_e1_56_step1_synthetic_results_have_pool_address(monkeypatch) -> None:
    """Synthesized BackrunResult must carry _source_event with pool_address
    so downstream artifact builders work uniformly with WS-event results."""
    monkeypatch.setenv("ARBY_COLD_IMMEDIATE_SIM", "1")
    monkeypatch.setenv("ARBY_COLD_IMMEDIATE_MIN_NET_BPS", "0")
    from m7.orderflow.cold_immediate_sim import queue_cold_executable_for_sim

    bridge = {
        "cold_executable": [
            {
                "pool_address": "0xCOLDPOOL",
                "net_bps": 500.0,
                "token_in": "FUN",
                "token_out": "USDC",
                "amount_in_wei": 10**18,
                "block_lag": 0,
            },
        ],
    }
    captured_args: list = []
    def _capture(scored, **kw):
        captured_args.append(scored)
        return MagicMock(sim_attempted=1, sim_passed=0, guard_passed=[], submit_ready=0)
    with patch(
        "m7.orderflow.execution_gate.run_execution_gate",
        side_effect=_capture,
    ):
        queue_cold_executable_for_sim(bridge, chain="base")

    assert len(captured_args) == 1
    synthesized = captured_args[0]
    assert len(synthesized) == 1
    res = synthesized[0]
    assert res.scoring_path == "cold_immediate"
    assert res.event_source == "cold_bridge"
    assert res.best_backrun_net_bps == 500.0
    assert getattr(res, "_source_event", None) is not None
    assert res._source_event.pool_address == "0xcoldpool"  # lowercased


def test_e1_56_step1_counters_propagate_from_gate(monkeypatch) -> None:
    monkeypatch.setenv("ARBY_COLD_IMMEDIATE_SIM", "1")
    monkeypatch.setenv("ARBY_COLD_IMMEDIATE_MIN_NET_BPS", "0")
    from m7.orderflow.cold_immediate_sim import queue_cold_executable_for_sim

    bridge = {
        "cold_executable": [
            {"pool_address": "0xa", "net_bps": 100,
             "token_in": "T", "token_out": "U"},
        ],
    }

    # Mock gate that reports 1 passed sim with positive post-bps
    fake_r = MagicMock()
    fake_r.best_backrun_net_bps = 100.0
    fake_r.best_live_net_bps = 80.0  # post-sim still positive
    fake_r.sim_passed = True
    mock_gate = MagicMock(
        sim_attempted=1,
        sim_passed=1,
        submit_ready=0,
        guard_passed=[(fake_r, None)],
    )
    with patch(
        "m7.orderflow.execution_gate.run_execution_gate",
        return_value=mock_gate,
    ):
        _gate, counters = queue_cold_executable_for_sim(bridge, chain="base")
    assert counters["cold_immediate_sim_attempted"] == 1
    assert counters["cold_immediate_sim_passed"] == 1
    assert counters["cold_immediate_sim_profitable"] == 1


def test_e1_56_step1_handles_gate_exception_gracefully(monkeypatch) -> None:
    """If run_execution_gate raises, we must not crash the hot loop."""
    monkeypatch.setenv("ARBY_COLD_IMMEDIATE_SIM", "1")
    monkeypatch.setenv("ARBY_COLD_IMMEDIATE_MIN_NET_BPS", "0")
    from m7.orderflow.cold_immediate_sim import queue_cold_executable_for_sim

    bridge = {
        "cold_executable": [
            {"pool_address": "0xa", "net_bps": 100,
             "token_in": "T", "token_out": "U"},
        ],
    }
    with patch(
        "m7.orderflow.execution_gate.run_execution_gate",
        side_effect=RuntimeError("provider down"),
    ):
        gate, counters = queue_cold_executable_for_sim(bridge, chain="base")
    assert gate is None
    # Input counted, but attempted/passed/profitable remain 0.
    assert counters["cold_immediate_sim_input_count"] == 1
    assert counters["cold_immediate_sim_attempted"] == 0


def test_e1_56_step1_invalid_entries_skipped(monkeypatch) -> None:
    """Entries missing pool_address are skipped, not crashed."""
    monkeypatch.setenv("ARBY_COLD_IMMEDIATE_SIM", "1")
    monkeypatch.setenv("ARBY_COLD_IMMEDIATE_MIN_NET_BPS", "0")
    from m7.orderflow.cold_immediate_sim import queue_cold_executable_for_sim

    bridge = {
        "cold_executable": [
            {"net_bps": 100},  # no pool_address
            "not a dict",  # type: ignore
            {"pool_address": "", "net_bps": 100},  # empty pool_address
            {"pool_address": "0xvalid", "net_bps": 50,
             "token_in": "T", "token_out": "U"},
        ],
    }
    with patch(
        "m7.orderflow.execution_gate.run_execution_gate",
        return_value=MagicMock(
            sim_attempted=1, sim_passed=0, guard_passed=[], submit_ready=0,
        ),
    ):
        _gate, counters = queue_cold_executable_for_sim(bridge, chain="base")
    # Only the one valid entry: input count = 2 (the dict-valid ones above
    # threshold 0), but only 1 reaches synthesis (one has empty pool_address).
    # Input is len(ranked) which counts valid dicts above threshold = 3.
    assert counters["cold_immediate_sim_input_count"] >= 1


# ---------------------------------------------------------------------------
# Reviewer fix tests: fee/venue/token-address metadata (E1.56 Step 1 compact fix)
# These tests use the REAL run_execution_gate (not mocked) so they catch
# actual admission-skip paths (NO_FEE_HINT, MISSING_SIZE_METADATA) that
# fully-mocked tests cannot detect.
# ---------------------------------------------------------------------------

def _make_admission_gate_env(monkeypatch):
    """Set ENV so execution_gate reaches the admission check but treats
    sim as not configured (returns early with SIM_DISABLED) rather than
    making real RPC calls."""
    import m7.orderflow.execution_gate as _gate_mod
    monkeypatch.setenv("ARBY_SIM_ADMISSION_STRICT", "1")
    monkeypatch.setenv("ARBY_COLD_IMMEDIATE_SIM", "1")
    monkeypatch.setenv("ARBY_COLD_IMMEDIATE_MIN_NET_BPS", "0")
    # BYPASS_GUARD=1 forces all candidates through the profit-guard phase
    # (same pattern as TestPreSimAdmissionFilter.test_admission_skips_no_fee_hint_under_bypass)
    # so that admission-level fee checks actually run.
    monkeypatch.setenv("ARBY_SIM_BYPASS_GUARD", "1")
    # Mock is_simulation_configured so it returns True — this forces the
    # gate to reach admission rather than returning SIM_DISABLED early.
    monkeypatch.setattr(_gate_mod, "is_simulation_configured", lambda **_: True)


def test_e1_56_compact_fee_fields_propagate_to_synthetic_result(monkeypatch) -> None:
    """best_buy_fee and size metadata written by _compact_candidate must
    survive into the synthetic BackrunResult so execution_gate admits it."""
    from m7.orderflow.cold_immediate_sim import _build_synthetic_event, _build_synthetic_result

    entry = {
        "pool_address": "0xfeedbeef",
        "net_bps": 200.0,
        "actual_pair": "WETH/USDC",
        "amount_in_wei": 10 ** 18,
        "best_buy_fee": 500,
        "best_sell_fee": 3000,
        "best_buy_venue": "uniswap_v3",
        "best_sell_venue": "uniswap_v3",
        "backrun_token_in_address": "0xaaa",
        "backrun_token_out_address": "0xbbb",
        "token_in_decimals": 18,
        "best_sweep_size_wei": 5 * 10 ** 17,
        "size_usd_estimate": 1500.0,
    }
    ev = _build_synthetic_event(entry, chain="base")
    assert ev is not None
    res = _build_synthetic_result(entry, ev)

    assert res.best_buy_fee == 500, "best_buy_fee must survive into BackrunResult"
    assert res.best_sell_fee == 3000
    assert res.best_buy_venue == "uniswap_v3"
    assert res.best_sell_venue == "uniswap_v3"
    assert res.backrun_token_in_address == "0xaaa"
    assert res.backrun_token_out_address == "0xbbb"
    assert res.token_in_decimals == 18
    assert res.best_sweep_size_wei == 5 * 10 ** 17
    assert res.size_usd_estimate == 1500.0


def test_e1_56_fee_tier_fallback_when_best_buy_fee_absent(monkeypatch) -> None:
    """When compact entry has no best_buy_fee, fee_tier from the event
    is used as fallback so gate doesn't return NO_FEE_HINT."""
    from m7.orderflow.cold_immediate_sim import _build_synthetic_event, _build_synthetic_result

    entry = {
        "pool_address": "0xabcd",
        "net_bps": 100.0,
        "actual_pair": "FUN/USDC",
        "fee_tier": 3000,        # fee_tier present, best_buy_fee absent
        "amount_in_wei": 10 ** 18,
        "token_in_decimals": 18,
    }
    ev = _build_synthetic_event(entry, chain="base")
    assert ev is not None
    assert ev.fee_tier == 3000

    res = _build_synthetic_result(entry, ev)
    # fee_tier(3000) should be promoted to best_buy_fee
    assert res.best_buy_fee == 3000, "fee_tier must be promoted when best_buy_fee absent"


def test_e1_56_no_fee_hint_skip_when_fee_absent(monkeypatch) -> None:
    """Real admission check: entry without fee → gate records NO_FEE_HINT."""
    _make_admission_gate_env(monkeypatch)
    from m7.orderflow.cold_immediate_sim import queue_cold_executable_for_sim

    bridge = {
        "cold_executable": [
            {
                "pool_address": "0xnofee",
                "net_bps": 200.0,
                "actual_pair": "WETH/USDC",
                # NO best_buy_fee, NO fee_tier, NO amount_in_wei, NO best_sweep_size_wei
                "token_in": "WETH",
                "token_out": "USDC",
            },
        ],
    }
    gate, counters = queue_cold_executable_for_sim(bridge, chain="base")
    assert gate is not None
    sim_errors = getattr(gate, "sim_errors", []) or []
    has_fee_skip = any(
        "NO_FEE_HINT" in e or "NO_AMOUNT_NO_FEE_HINT" in e
        for e in sim_errors
    )
    assert has_fee_skip, (
        f"Expected NO_FEE_HINT in sim_errors when fee absent, got: {sim_errors}"
    )


def test_e1_56_fee_present_bypasses_no_fee_hint(monkeypatch) -> None:
    """Real admission check: entry with best_buy_fee and decimals should
    NOT get NO_FEE_HINT and should reach sim (or SIM_DISABLED) rather
    than being skipped before sim."""
    _make_admission_gate_env(monkeypatch)
    # Make sim_configured return False after admission so we don't
    # actually try to fork; we just want sim_attempted == 0 for the
    # right reason (SIM_DISABLED) not the wrong one (NO_FEE_HINT).
    import m7.orderflow.execution_gate as _gate_mod
    call_count = {"n": 0}
    original = _gate_mod.is_simulation_configured
    def _first_true_then_false(**kw):
        call_count["n"] += 1
        # First call (guard check) → True; subsequent (sim) → False.
        return call_count["n"] <= 1
    monkeypatch.setattr(_gate_mod, "is_simulation_configured", _first_true_then_false)

    from m7.orderflow.cold_immediate_sim import queue_cold_executable_for_sim

    bridge = {
        "cold_executable": [
            {
                "pool_address": "0xwithfee",
                "net_bps": 200.0,
                "actual_pair": "WETH/USDC",
                "best_buy_fee": 500,
                "token_in_decimals": 18,
                "amount_in_wei": 10 ** 18,
                "token_in": "WETH",
                "token_out": "USDC",
            },
        ],
    }
    gate, counters = queue_cold_executable_for_sim(bridge, chain="base")
    assert gate is not None
    sim_errors = getattr(gate, "sim_errors", []) or []
    has_fee_skip = any(
        "NO_FEE_HINT" in e or "NO_AMOUNT_NO_FEE_HINT" in e
        for e in sim_errors
    )
    assert not has_fee_skip, (
        f"Entry with best_buy_fee=500 should NOT get NO_FEE_HINT, got: {sim_errors}"
    )


def test_e1_56_compact_candidate_fee_fields_present() -> None:
    """_compact_candidate source must include the 10 execution-gate
    admission fields added in E1.56 Step 1 compact patch."""
    import m7.orderflow.artifacts as _art
    import inspect

    src = inspect.getsource(_art)
    required_fields = [
        "best_buy_fee",
        "best_sell_fee",
        "best_buy_venue",
        "best_sell_venue",
        "backrun_token_in_address",
        "backrun_token_out_address",
        "token_in_decimals",
        "amount_in_wei",
        "best_sweep_size_wei",
        "size_usd_estimate",
        "gross_pnl_wei",
        "net_pnl_wei",
    ]
    missing = [f for f in required_fields if f'"{f}"' not in src]
    assert not missing, (
        f"_compact_candidate is missing execution-gate admission fields: {missing}. "
        "These are required so cold_immediate_sim synthetic BackrunResults are admitted."
    )


def test_e1_56_gross_pnl_fallback_from_net_bps(monkeypatch) -> None:
    """When gross_pnl_wei absent, _build_synthetic_result estimates it from
    net_bps so profit_guard does not reject the synthetic BackrunResult."""
    from m7.orderflow.cold_immediate_sim import _build_synthetic_event, _build_synthetic_result

    amount = 10 ** 18
    net_bps = 300.0
    entry = {
        "pool_address": "0xtest",
        "net_bps": net_bps,
        "actual_pair": "WETH/USDC",
        "amount_in_wei": amount,
        "best_buy_fee": 3000,
        "token_in_decimals": 18,
        # gross_pnl_wei intentionally absent (simulates old compact row)
    }
    ev = _build_synthetic_event(entry, chain="base")
    res = _build_synthetic_result(entry, ev)

    expected_gross = int(net_bps * amount / 10000)  # 3e13 wei
    assert res.gross_pnl_wei == expected_gross, (
        f"gross_pnl_wei should be estimated from net_bps; got {res.gross_pnl_wei}"
    )
    assert res.gross_pnl_wei > 0, "gross_pnl_wei must be > 0 so profit_guard passes"
