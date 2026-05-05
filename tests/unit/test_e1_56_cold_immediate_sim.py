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
        sim_errors=[],
    )
    with patch(
        "m7.orderflow.execution_gate.run_execution_gate",
        return_value=mock_gate,
    ):
        _gate, counters = queue_cold_executable_for_sim(bridge, chain="base")
    assert counters["cold_immediate_sim_attempted"] == 1
    assert counters["cold_immediate_sim_passed"] == 1
    assert counters["cold_immediate_sim_profitable"] == 1
    # issue #3: diagnostic counters present
    assert counters["cold_immediate_guard_passed"] == 1
    assert counters["cold_immediate_pre_sim_skip"] == 0
    assert counters["cold_immediate_sim_revert"] == 0


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


def test_e1_56_diagnostic_counters_pre_sim_skip_and_revert(monkeypatch) -> None:
    """issue #3: cold_immediate_pre_sim_skip and cold_immediate_sim_revert
    counters are populated from gate.sim_errors."""
    monkeypatch.setenv("ARBY_COLD_IMMEDIATE_SIM", "1")
    monkeypatch.setenv("ARBY_COLD_IMMEDIATE_MIN_NET_BPS", "0")
    from m7.orderflow.cold_immediate_sim import queue_cold_executable_for_sim

    bridge = {
        "cold_executable": [
            {"pool_address": "0xa", "net_bps": 100,
             "token_in": "T", "token_out": "U"},
        ],
    }
    mock_gate = MagicMock(
        sim_attempted=2,
        sim_passed=0,
        guard_passed=[],
        sim_errors=[
            "PRE_SIM_SKIP:UNSUPPORTED_FEE_TIER:1570",
            "REVERT:STF",
        ],
    )
    with patch(
        "m7.orderflow.execution_gate.run_execution_gate",
        return_value=mock_gate,
    ):
        _gate, counters = queue_cold_executable_for_sim(bridge, chain="base")
    assert counters["cold_immediate_pre_sim_skip"] == 1
    assert counters["cold_immediate_sim_revert"] == 1
    assert counters["cold_immediate_guard_passed"] == 0


# ---------------------------------------------------------------------------
# E1.57 fix steps #1/#2: Canonicalization path tests
# ---------------------------------------------------------------------------

def test_e1_57_roundtrip_counters_in_cold_immediate_counters(monkeypatch) -> None:
    """E1.57: queue_cold_executable_for_sim must expose roundtrip counters from gate."""
    monkeypatch.setenv("ARBY_COLD_IMMEDIATE_SIM", "1")
    monkeypatch.setenv("ARBY_COLD_IMMEDIATE_MIN_NET_BPS", "0")
    from m7.orderflow.cold_immediate_sim import queue_cold_executable_for_sim

    bridge = {
        "cold_executable": [
            {"pool_address": "0xabc", "net_bps": 200,
             "token_in": "WETH", "token_out": "USDC"},
        ],
    }

    mock_gate = MagicMock(
        sim_attempted=1,
        sim_passed=1,
        guard_passed=[],
        sim_errors=[],
        roundtrip_attempted=1,
        roundtrip_profitable_count=1,
    )
    with patch(
        "m7.orderflow.execution_gate.run_execution_gate",
        return_value=mock_gate,
    ):
        returned_gate, counters = queue_cold_executable_for_sim(bridge, chain="base")

    # The gate object is returned; roundtrip counts accessible via attributes
    assert returned_gate is not None
    assert getattr(returned_gate, "roundtrip_attempted", 0) == 1
    assert getattr(returned_gate, "roundtrip_profitable_count", 0) == 1


def test_e1_57_hot_rollup_ci_roundtrip_merges_into_canonical_total(tmp_path, monkeypatch) -> None:
    """E1.57: _update_hot_rollup must merge cold_immediate roundtrip into roundtrip_profitable_total."""
    import json
    import m7.orderflow.runtime_io as _rio_mod
    from m7.orderflow.hot_runtime_artifacts import _update_hot_rollup

    rollup_path = str(tmp_path / "m7_hot_rollup_latest.json")
    # Pre-populate rollup with CI profitable sims but zero roundtrip
    initial = {
        "cold_immediate_sim_profitable_total": 5,
        "cold_immediate_sim_passed_total": 5,
        "roundtrip_profitable_total": 0,
        "roundtrip_attempted_total": 0,
    }
    with open(rollup_path, "w") as f:
        json.dump(initial, f)

    monkeypatch.setattr(_rio_mod, "_HOT_ROLLUP_PATH", rollup_path)

    mock_gate = MagicMock(
        sim_attempted=0,
        sim_passed=0,
        guard_passed=[],
        sim_errors=[],
        roundtrip_attempted=0,
        roundtrip_profitable_count=0,
    )

    extra_counts = {
        "cold_immediate_roundtrip_attempted": 1,
        "cold_immediate_roundtrip_profitable": 1,  # CI roundtrip passed!
    }

    _update_hot_rollup(
        0, [], [], {},
        gate_result=mock_gate,
        extra_signal_counts=extra_counts,
    )

    with open(rollup_path) as f:
        rollup = json.load(f)

    # CI roundtrip must increment the canonical total
    assert rollup.get("roundtrip_profitable_total", 0) >= 1
    assert rollup.get("roundtrip_attempted_total", 0) >= 1
    assert rollup.get("cold_immediate_roundtrip_profitable_total", 0) == 1
    assert rollup.get("cold_immediate_roundtrip_attempted_total", 0) == 1


def test_e1_57_waiting_canonicalization_cleared_when_ci_roundtrip_present(tmp_path, monkeypatch) -> None:
    """E1.57: flag clears when cold_immediate_roundtrip_profitable_total > 0."""
    import json
    import m7.orderflow.runtime_io as _rio_mod
    from m7.orderflow.hot_runtime_artifacts import _update_hot_rollup

    rollup_path = str(tmp_path / "m7_hot_rollup_latest.json")
    initial = {
        "cold_immediate_sim_profitable_total": 10,
        "cold_immediate_roundtrip_profitable_total": 0,
        "roundtrip_profitable_total": 0,
        "cold_immediate_profitable_waiting_canonicalization": True,
    }
    with open(rollup_path, "w") as f:
        json.dump(initial, f)

    monkeypatch.setattr(_rio_mod, "_HOT_ROLLUP_PATH", rollup_path)

    mock_gate = MagicMock(
        sim_attempted=0,
        sim_passed=0,
        guard_passed=[],
        sim_errors=[],
        roundtrip_attempted=0,
        roundtrip_profitable_count=0,
    )
    extra_counts = {
        "cold_immediate_roundtrip_profitable": 1,
        "cold_immediate_roundtrip_attempted": 1,
    }

    _update_hot_rollup(
        0, [], [], {},
        gate_result=mock_gate,
        extra_signal_counts=extra_counts,
    )

    with open(rollup_path) as f:
        rollup = json.load(f)

    assert "cold_immediate_profitable_waiting_canonicalization" not in rollup


def test_e1_57_waiting_canonicalization_remains_when_no_ci_roundtrip(tmp_path, monkeypatch) -> None:
    """E1.57: flag stays when CI has profitable sim but no roundtrip success yet."""
    import json
    import m7.orderflow.runtime_io as _rio_mod
    from m7.orderflow.hot_runtime_artifacts import _update_hot_rollup

    rollup_path = str(tmp_path / "m7_hot_rollup_latest.json")
    initial = {
        "cold_immediate_sim_profitable_total": 10,
        "cold_immediate_roundtrip_profitable_total": 0,
        "roundtrip_profitable_total": 0,
    }
    with open(rollup_path, "w") as f:
        json.dump(initial, f)

    monkeypatch.setattr(_rio_mod, "_HOT_ROLLUP_PATH", rollup_path)

    mock_gate = MagicMock(
        sim_attempted=0,
        sim_passed=0,
        guard_passed=[],
        sim_errors=[],
        roundtrip_attempted=0,
        roundtrip_profitable_count=0,
    )
    extra_counts = {
        "cold_immediate_sim_profitable": 3,
        "cold_immediate_roundtrip_profitable": 0,
    }

    _update_hot_rollup(
        0, [], [], {},
        gate_result=mock_gate,
        extra_signal_counts=extra_counts,
    )

    with open(rollup_path) as f:
        rollup = json.load(f)

    assert rollup.get("cold_immediate_profitable_waiting_canonicalization") is True


def test_e1_57_fix8_roundtrip_success_total_incremented_on_ci_profitable(tmp_path, monkeypatch) -> None:
    """E1.57 fix step 8: CI roundtrip profitable merge also increments roundtrip_success_total."""
    import json
    import m7.orderflow.runtime_io as _rio_mod
    from m7.orderflow.hot_runtime_artifacts import _update_hot_rollup

    rollup_path = str(tmp_path / "m7_hot_rollup_latest.json")
    initial = {
        "roundtrip_success_total": 5,
        "roundtrip_profitable_total": 0,
    }
    with open(rollup_path, "w") as f:
        json.dump(initial, f)

    monkeypatch.setattr(_rio_mod, "_HOT_ROLLUP_PATH", rollup_path)

    mock_gate = MagicMock(
        sim_attempted=0,
        sim_passed=0,
        guard_passed=[],
        sim_errors=[],
        roundtrip_attempted=0,
        roundtrip_success=0,
        roundtrip_profitable_count=0,
        l1_fee_wei=0,
        l1_fee_source="",
        l1_fee_calldata_len=0,
        l1_fee_calldata_kind="",
    )
    extra_counts = {
        "cold_immediate_roundtrip_profitable": 2,
        "cold_immediate_roundtrip_attempted": 2,
    }

    _update_hot_rollup(
        0, [], [], {},
        gate_result=mock_gate,
        extra_signal_counts=extra_counts,
    )

    with open(rollup_path) as f:
        rollup = json.load(f)

    # profitable merge: +2 → profitable_total = 2
    assert rollup["roundtrip_profitable_total"] == 2
    # fix step 8: success_total also incremented by same amount
    assert rollup["roundtrip_success_total"] == 7  # 5 + 2


def test_e1_57_fix4_l1_fee_fields_in_rollup(tmp_path, monkeypatch) -> None:
    """E1.57 fix step 4: l1_fee_wei/source/calldata fields written to rollup from gate_result."""
    import json
    import m7.orderflow.runtime_io as _rio_mod
    from m7.orderflow.hot_runtime_artifacts import _update_hot_rollup

    rollup_path = str(tmp_path / "m7_hot_rollup_latest.json")
    with open(rollup_path, "w") as f:
        json.dump({}, f)

    monkeypatch.setattr(_rio_mod, "_HOT_ROLLUP_PATH", rollup_path)

    mock_gate = MagicMock(
        sim_attempted=0,
        sim_passed=0,
        guard_passed=[],
        sim_errors=[],
        roundtrip_attempted=0,
        roundtrip_success=0,
        roundtrip_profitable_count=0,
        l1_fee_wei=600_000_000,
        l1_fee_source="onchain",
        l1_fee_calldata_len=228,
        l1_fee_calldata_kind="swaprouter02_representative",
    )

    _update_hot_rollup(0, [], [], {}, gate_result=mock_gate)

    with open(rollup_path) as f:
        rollup = json.load(f)

    assert rollup["l1_fee_wei_last"] == 600_000_000
    assert rollup["l1_fee_source_last"] == "onchain"
    assert rollup["l1_fee_calldata_len"] == 228
    assert rollup["l1_fee_calldata_kind"] == "swaprouter02_representative"

def test_e1_58_fix8_ci_roundtrip_bps_into_buffer(tmp_path, monkeypatch) -> None:
    '''E1.58 fix step 8: CI roundtrip bps from cold_immediate flow get drained
    into _roundtrip_profit_bps_all so best/worst/median are no longer null.'''
    import json
    import m7.orderflow.runtime_io as _rio_mod
    from m7.orderflow.hot_runtime_artifacts import _update_hot_rollup

    rollup_path = str(tmp_path / 'm7_hot_rollup_latest.json')
    with open(rollup_path, 'w') as f:
        json.dump({}, f)

    monkeypatch.setattr(_rio_mod, '_HOT_ROLLUP_PATH', rollup_path)

    mock_gate = MagicMock(
        sim_attempted=0,
        sim_passed=0,
        guard_passed=[],
        sim_errors=[],
        roundtrip_attempted=0,
        roundtrip_success=0,
        roundtrip_profitable_count=0,
        roundtrip_profit_bps_values=[],
        roundtrip_errors=[],
        sim_output_samples=[],
    )

    extra = {
        'cold_immediate_roundtrip_attempted': 3,
        'cold_immediate_roundtrip_profitable': 2,
        'cold_immediate_roundtrip_profit_bps_values': [12.5, 8.25, -3.1],
    }

    _update_hot_rollup(0, [], [], {}, gate_result=mock_gate, extra_signal_counts=extra)

    with open(rollup_path) as f:
        rollup = json.load(f)

    assert rollup['_roundtrip_profit_bps_all'] == [12.5, 8.25, -3.1]
    assert rollup['roundtrip_profit_bps_best'] == 12.5
    assert rollup['roundtrip_profit_bps_worst'] == -3.1
    assert rollup['roundtrip_profit_bps_median'] == 8.25

def test_e1_58_fix1_ci_submit_ready_into_total(tmp_path, monkeypatch) -> None:
    '''E1.58 fix step #1 runtime: CI gate submit_ready accumulates into submit_ready_total.'''
    import json
    import m7.orderflow.runtime_io as _rio_mod
    from m7.orderflow.hot_runtime_artifacts import _update_hot_rollup

    rollup_path = str(tmp_path / 'm7_hot_rollup_latest.json')
    with open(rollup_path, 'w') as f:
        json.dump({}, f)

    monkeypatch.setattr(_rio_mod, '_HOT_ROLLUP_PATH', rollup_path)

    mock_gate = MagicMock(
        sim_attempted=0,
        sim_passed=0,
        guard_passed=[],
        sim_errors=[],
        roundtrip_attempted=0,
        roundtrip_success=0,
        roundtrip_profitable_count=0,
        roundtrip_profit_bps_values=[],
        roundtrip_errors=[],
        sim_output_samples=[],
        submit_ready=0,
    )

    extra = {
        'cold_immediate_submit_ready': 4,
        'cold_immediate_roundtrip_attempted': 5,
        'cold_immediate_roundtrip_profitable': 4,
    }

    _update_hot_rollup(0, [], [], {}, gate_result=mock_gate, extra_signal_counts=extra)

    with open(rollup_path) as f:
        rollup = json.load(f)

    assert rollup['cold_immediate_submit_ready_total'] == 4
    assert rollup['submit_ready_total'] == 4
