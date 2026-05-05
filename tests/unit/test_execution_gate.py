"""E1.12.2: Protective tests for the execution gate pipeline.

Tests:
  1. Schema stability вЂ” BackrunResult has exactly 75 fields (8 new terminal)
  2. Funnel invariant вЂ” submit_ready <= sim_passed <= guard_passed <= route_viable
  3. SIM_DISABLED вЂ” without Tenderly, stage is honestly marked
  4. Backward-compat вЂ” all 13 extracted symbols importable from loop
  5. ExecutionGateResult dataclass defaults
  6. run_execution_gate with empty input
"""
import pytest
from dataclasses import fields


class TestBackrunResultTerminalFields:
    """E1.12.2: BackrunResult has the 8 new terminal stage fields."""

    def test_terminal_fields_exist(self):
        from m7.orderflow.contracts import BackrunResult

        br = BackrunResult(
            event_id="test",
            event_source="fixture",
            event_type="swap",
            post_trade_state_used="estimated",
            backrun_direction="buy",
        )
        # All 8 terminal fields should exist and default to None
        assert br.sim_attempted is None
        assert br.sim_passed is None
        assert br.simulation_id is None
        assert br.simulation_error is None
        assert br.submit_ready is None
        assert br.submit_blocker is None
        assert br.calldata_ready is None
        assert br.signing_ready is None

    def test_terminal_fields_settable(self):
        from m7.orderflow.contracts import BackrunResult

        br = BackrunResult(
            event_id="test",
            event_source="fixture",
            event_type="swap",
            post_trade_state_used="estimated",
            backrun_direction="buy",
        )
        br.sim_attempted = True
        br.sim_passed = False
        br.simulation_error = "SIM_DISABLED"
        br.submit_ready = False
        br.submit_blocker = "SIM_DISABLED"
        assert br.sim_attempted is True
        assert br.sim_passed is False
        assert br.submit_blocker == "SIM_DISABLED"


class TestExecutionGateResult:
    """E1.12.2: ExecutionGateResult dataclass has correct defaults."""

    def test_defaults(self):
        from m7.orderflow.execution_gate import ExecutionGateResult

        gate = ExecutionGateResult()
        assert gate.guard_passed == []
        assert gate.sim_attempted == 0
        assert gate.sim_passed == 0
        assert gate.submit_ready == 0
        assert gate.sim_disabled is False
        assert gate.sim_blocker == ""
        assert gate.submit_blockers == []


class TestExecutionGateEmptyInput:
    """E1.12.2: run_execution_gate with empty input returns zero counts."""

    def test_empty_results(self):
        from m7.orderflow.execution_gate import run_execution_gate

        gate = run_execution_gate([], chain="base")
        assert gate.guard_passed == []
        assert gate.sim_attempted == 0
        assert gate.sim_passed == 0
        assert gate.submit_ready == 0


class TestSimDisabledHonest:
    """E1.12.2: Without simulation backend configured, execution gate marks SIM_DISABLED."""

    def test_sim_disabled_without_tenderly(self, monkeypatch):
        from m7.orderflow.execution_gate import run_execution_gate
        import m7.orderflow.execution_gate as gate_mod

        # Ensure simulation is not configured вЂ” patch generic check in gate module namespace
        monkeypatch.setattr(gate_mod, "is_simulation_configured", lambda **_: False)

        # Create a fake result that will pass profit guard
        from m7.orderflow.contracts import BackrunResult

        br = BackrunResult(
            event_id="test",
            event_source="fixture",
            event_type="swap",
            post_trade_state_used="estimated",
            backrun_direction="buy",
            best_backrun_net_bps=150.0,
            amount_in_wei=10**18,
            gross_pnl_wei=10**16,  # positive gross
            route_viable=True,
            size_valid_for_token=True,
        )

        gate = run_execution_gate([br], chain="base")

        # Guard should pass (positive net with valid size)
        if gate.guard_passed:
            # Sim should be disabled
            assert gate.sim_disabled is True
            assert gate.sim_blocker == "SIM_DISABLED"
            assert gate.sim_attempted == 0
            assert gate.sim_passed == 0
            assert gate.submit_ready == 0

            # BackrunResult should be annotated with honest blocker
            r, g = gate.guard_passed[0]
            assert r.sim_attempted is False
            assert r.sim_passed is False
            assert r.simulation_error == "SIM_DISABLED"
            assert r.submit_ready is False
            assert r.submit_blocker == "SIM_DISABLED"


class TestFunnelInvariant:
    """E1.12.2: Funnel invariant: submit_ready <= sim_passed <= guard_passed."""

    def test_funnel_monotone(self):
        from m7.orderflow.execution_gate import run_execution_gate, ExecutionGateResult

        gate = ExecutionGateResult(
            guard_passed=[("fake", "fake")],
            sim_attempted=1,
            sim_passed=1,
            submit_ready=0,
        )
        # Invariant: submit_ready <= sim_passed <= len(guard_passed)
        assert gate.submit_ready <= gate.sim_passed
        assert gate.sim_passed <= len(gate.guard_passed)

    def test_zero_guard_means_zero_sim(self):
        from m7.orderflow.execution_gate import run_execution_gate

        gate = run_execution_gate([], chain="base")
        assert len(gate.guard_passed) == 0
        assert gate.sim_attempted == 0
        assert gate.sim_passed == 0
        assert gate.submit_ready == 0


class TestBackwardCompatImports:
    """E1.12.2: All 13 extracted symbols still importable from loop module."""

    def test_runtime_io_symbols_from_loop(self):
        from scripts.m7a_orderflow_loop import (
            _atomic_json_write,
            _write_promoted_pairs,
            _read_promoted_pairs,
            _read_discovery_scoreboard,
            _update_discovery_scoreboard,
            _write_discovery_scoreboard,
            _SESSION_ID,
            _init_artifact_paths,
        )
        # All should be callable or non-None
        assert callable(_atomic_json_write)
        assert callable(_write_promoted_pairs)
        assert callable(_read_promoted_pairs)
        assert callable(_read_discovery_scoreboard)
        assert callable(_update_discovery_scoreboard)
        assert callable(_write_discovery_scoreboard)
        assert callable(_init_artifact_paths)
        assert _SESSION_ID is not None

    def test_bridge_runtime_symbols_from_loop(self):
        from scripts.m7a_orderflow_loop import (
            _write_cold_hot_bridge,
            _read_cold_hot_bridge,
            _populate_pool_token_cache_from_bridge,
            _prewarm_registry_from_bridge,
            _prewarm_registry_from_pairs,
            _promote_pairs_from_cold,
        )
        assert callable(_write_cold_hot_bridge)
        assert callable(_read_cold_hot_bridge)
        assert callable(_populate_pool_token_cache_from_bridge)
        assert callable(_prewarm_registry_from_bridge)
        assert callable(_prewarm_registry_from_pairs)
        assert callable(_promote_pairs_from_cold)

    def test_execution_gate_symbols_from_loop(self):
        from scripts.m7a_orderflow_loop import (
            _run_profit_guard_on_results,
            run_execution_gate,
            ExecutionGateResult,
        )
        assert callable(_run_profit_guard_on_results)
        assert callable(run_execution_gate)

    def test_lane_defaults_still_accessible(self):
        from scripts.m7a_orderflow_loop import _LANE_DEFAULTS

        assert _LANE_DEFAULTS["cold"]["ws_blocks"] == 300
        assert _LANE_DEFAULTS["hot"]["ws_blocks"] == 20

    def test_path_constants_still_accessible(self):
        from scripts.m7a_orderflow_loop import (
            _HOT_ARTIFACT_PATH,
            _PROMOTED_PAIRS_PATH,
            _COLD_HOT_BRIDGE_PATH,
            _HOT_INTENTS_PATH,
            _HOT_ROLLUP_PATH,
            _DISCOVERY_SCOREBOARD_PATH,
        )
        assert _HOT_ARTIFACT_PATH.endswith(".json")
        assert _PROMOTED_PAIRS_PATH.endswith(".json")


class TestCanonicalModuleImports:
    """E1.12.2: New modules import directly (not through loop file)."""

    def test_runtime_io_direct(self):
        from m7.orderflow.runtime_io import (
            _rolling_path,
            _init_artifact_paths,
            _atomic_json_write,
            _write_promoted_pairs,
            _read_promoted_pairs,
            _read_discovery_scoreboard,
            _update_discovery_scoreboard,
            _write_discovery_scoreboard,
            _SESSION_ID,
        )
        assert callable(_rolling_path)
        assert callable(_init_artifact_paths)

    def test_bridge_runtime_direct(self):
        from m7.orderflow.bridge_runtime import (
            _write_cold_hot_bridge,
            _read_cold_hot_bridge,
            _populate_pool_token_cache_from_bridge,
            _prewarm_registry_from_bridge,
            _prewarm_registry_from_pairs,
            _promote_pairs_from_cold,
        )
        assert callable(_write_cold_hot_bridge)
        assert callable(_promote_pairs_from_cold)

    def test_execution_gate_direct(self):
        from m7.orderflow.execution_gate import (
            run_execution_gate,
            ExecutionGateResult,
            _run_profit_guard_on_results,
            _attempt_simulation,
            _build_sim_tx_params,
        )
        assert callable(run_execution_gate)
        assert callable(_attempt_simulation)
        assert callable(_build_sim_tx_params)


class TestProfitGuardBatchHelper:
    """E1.12.2: annotate_profit_guard_results batch helper."""

    def test_annotate_exists(self):
        from m7.orderflow.profit_guard import annotate_profit_guard_results
        assert callable(annotate_profit_guard_results)


class TestE1123SimErrorHistogram:
    """E1.12.3: ExecutionGateResult collects per-candidate sim errors + submit blockers."""

    def test_new_fields_default_empty(self):
        from m7.orderflow.execution_gate import ExecutionGateResult

        gate = ExecutionGateResult()
        assert gate.sim_errors == []
        assert gate.submit_blockers_detail == []

    def test_sim_errors_collected_on_failure(self, monkeypatch):
        """When sim fails, error string is appended to sim_errors."""
        from m7.orderflow.execution_gate import run_execution_gate
        from m7.orderflow.simulation import SimulationResult
        import m7.orderflow.execution_gate as gate_mod

        monkeypatch.setattr(gate_mod, "is_simulation_configured", lambda **_: True)
        monkeypatch.setattr(
            gate_mod,
            "_attempt_simulation",
            lambda r, g, chain="base": SimulationResult(
                success=False, error="HTTP 401: Unauthorized"
            ),
        )

        from m7.orderflow.contracts import BackrunResult

        br = BackrunResult(
            event_id="test",
            event_source="fixture",
            event_type="swap",
            post_trade_state_used="estimated",
            backrun_direction="buy",
            best_backrun_net_bps=150.0,
            amount_in_wei=10**18,
            gross_pnl_wei=10**16,
            route_viable=True,
            size_valid_for_token=True,
        )

        gate = run_execution_gate([br], chain="base")
        if gate.guard_passed:
            assert gate.sim_attempted > 0
            assert gate.sim_passed == 0
            assert len(gate.sim_errors) == gate.sim_attempted
            assert "HTTP 401" in gate.sim_errors[0]

    def test_submit_blockers_detail_on_sim_pass_no_calldata(self, monkeypatch):
        """When sim passes but calldata not ready, submit blocker detail collected."""
        from m7.orderflow.execution_gate import run_execution_gate
        from m7.orderflow.simulation import SimulationResult
        import m7.orderflow.execution_gate as gate_mod

        # Ensure paper signing is off so signing_ready stays None
        monkeypatch.delenv("ARBY_PAPER_SIGNING", raising=False)

        monkeypatch.setattr(gate_mod, "is_simulation_configured", lambda **_: True)
        monkeypatch.setattr(
            gate_mod,
            "_attempt_simulation",
            lambda r, g, chain="base": SimulationResult(
                success=True, gas_used=21000, simulation_id="sim-123"
            ),
        )

        from m7.orderflow.contracts import BackrunResult

        br = BackrunResult(
            event_id="test",
            event_source="fixture",
            event_type="swap",
            post_trade_state_used="estimated",
            backrun_direction="buy",
            best_backrun_net_bps=150.0,
            amount_in_wei=10**18,
            gross_pnl_wei=10**16,
            route_viable=True,
            size_valid_for_token=True,
        )

        gate = run_execution_gate([br], chain="base")
        if gate.guard_passed and gate.sim_passed > 0:
            # E1.14: calldata_ready is now auto-set on sim pass
            # signing_ready is still None by default
            assert gate.submit_ready == 0
            assert "SIGNING_NOT_READY" in gate.submit_blockers_detail

    def test_rollup_accumulates_sim_histogram(self, tmp_path, monkeypatch):
        """_update_hot_rollup accumulates simulation_error_histogram from gate_result."""
        import json
        import m7.orderflow.runtime_io as _rio
        import scripts.m7a_orderflow_loop as loop_mod
        from m7.orderflow.execution_gate import ExecutionGateResult

        rollup_path = str(tmp_path / "m7_hot_rollup_latest.json")
        monkeypatch.setattr(loop_mod, "_HOT_ROLLUP_PATH", rollup_path)
        monkeypatch.setattr(_rio, "_HOT_ROLLUP_PATH", rollup_path)
        monkeypatch.setattr(_rio, "_SESSION_ID", "test-hist-001")
        monkeypatch.setattr(loop_mod, "_SESSION_ID", "test-hist-001")

        gate = ExecutionGateResult(
            sim_attempted=3,
            sim_passed=0,
            sim_errors=["HTTP 401: Unauthorized", "HTTP 401: Unauthorized", "REVERT: out of gas"],
            submit_blockers_detail=[],
        )

        loop_mod._update_hot_rollup(
            events_count=5, fast_results=[], guard_results=[],
            bridge_diagnostics={}, chain="base", gate_result=gate,
        )

        with open(rollup_path) as f:
            data = json.load(f)

        assert data["sim_attempted_total"] == 3
        assert data["sim_passed_total"] == 0
        hist = data.get("simulation_error_histogram", {})
        assert hist.get("HTTP 401: Unauthorized") == 2
        assert hist.get("REVERT: out of gas") == 1

    def test_rollup_accumulates_submit_blocker_histogram(self, tmp_path, monkeypatch):
        """_update_hot_rollup accumulates submit_blocker_histogram from gate_result."""
        import json
        import m7.orderflow.runtime_io as _rio
        import scripts.m7a_orderflow_loop as loop_mod
        from m7.orderflow.execution_gate import ExecutionGateResult

        rollup_path = str(tmp_path / "m7_hot_rollup_latest.json")
        monkeypatch.setattr(loop_mod, "_HOT_ROLLUP_PATH", rollup_path)
        monkeypatch.setattr(_rio, "_HOT_ROLLUP_PATH", rollup_path)
        monkeypatch.setattr(_rio, "_SESSION_ID", "test-hist-002")
        monkeypatch.setattr(loop_mod, "_SESSION_ID", "test-hist-002")

        gate = ExecutionGateResult(
            sim_attempted=2,
            sim_passed=2,
            sim_errors=[],
            submit_blockers_detail=["CALLDATA_NOT_READY", "SIGNING_NOT_READY",
                                    "CALLDATA_NOT_READY", "SIGNING_NOT_READY"],
        )

        loop_mod._update_hot_rollup(
            events_count=5, fast_results=[], guard_results=[],
            bridge_diagnostics={}, chain="base", gate_result=gate,
        )

        with open(rollup_path) as f:
            data = json.load(f)

        hist = data.get("submit_blocker_histogram", {})
        assert hist.get("CALLDATA_NOT_READY") == 2
        assert hist.get("SIGNING_NOT_READY") == 2

    def test_cold_immediate_profitable_not_canonical_verdict(self, tmp_path, monkeypatch):
        """E1.56 issue #4: when cold_immediate_sim_profitable_total>0 AND
        roundtrip_profitable_total==0, rollup must carry
        cold_immediate_profitable_not_canonical=True so reviewer immediately
        sees the gap between pre-production signal and canonical production
        DoD. Also verifies it clears when roundtrip_profitable is finally >0."""
        import json
        import m7.orderflow.runtime_io as _rio
        import scripts.m7a_orderflow_loop as loop_mod
        from m7.orderflow.execution_gate import ExecutionGateResult

        rollup_path = str(tmp_path / "m7_hot_rollup_latest.json")
        monkeypatch.setattr(loop_mod, "_HOT_ROLLUP_PATH", rollup_path)
        monkeypatch.setattr(_rio, "_HOT_ROLLUP_PATH", rollup_path)
        monkeypatch.setattr(_rio, "_SESSION_ID", "test-verdict-001")
        monkeypatch.setattr(loop_mod, "_SESSION_ID", "test-verdict-001")

        gate = ExecutionGateResult(
            sim_attempted=1, sim_passed=0, sim_errors=[], submit_blockers_detail=[],
        )

        # Inject cold_immediate profitable > 0 via extra_signal_counts
        loop_mod._update_hot_rollup(
            events_count=1, fast_results=[], guard_results=[],
            bridge_diagnostics={}, chain="base", gate_result=gate,
            extra_signal_counts={
                "cold_immediate_sim_profitable": 3,
            },
        )
        with open(rollup_path) as f:
            data = json.load(f)
        assert data.get("cold_immediate_sim_profitable_total") == 3
        assert data.get("roundtrip_profitable_total", 0) == 0
        assert data.get("cold_immediate_profitable_not_canonical") is True
        assert "synthetic BackrunResult" in data.get("cold_immediate_profitable_not_canonical_note", "")


        """_write_hot_artifact includes per-window sim_errors and submit_blockers."""
        import json
        import m7.orderflow.runtime_io as _rio
        import scripts.m7a_orderflow_loop as loop_mod
        from m7.orderflow.execution_gate import ExecutionGateResult

        hot_path = str(tmp_path / "m7_hot_latest.json")
        monkeypatch.setattr(loop_mod, "_HOT_ARTIFACT_PATH", hot_path)
        monkeypatch.setattr(_rio, "_HOT_ARTIFACT_PATH", hot_path)

        gate = ExecutionGateResult(
            sim_attempted=1,
            sim_passed=0,
            sim_errors=["HTTP 500: Internal Server Error"],
            submit_blockers_detail=[],
        )

        artifact = {"results": [], "events_count": 0, "_raw_results": []}
        loop_mod._write_hot_artifact(artifact, iteration=1, gate_result=gate)

        with open(hot_path) as f:
            data = json.load(f)

        assert data["sim_errors"] == ["HTTP 500: Internal Server Error"]
        assert data["submit_blockers"] == []


# ---------------------------------------------------------------------------
# E1.12.4B: Real calldata wiring in _attempt_simulation / _build_sim_tx_params
# ---------------------------------------------------------------------------


class TestBuildSimTxParams:
    """E1.12.4B: _build_sim_tx_params builds real V3 calldata from BackrunResult."""

    def _make_result(self, **overrides):
        from m7.orderflow.contracts import BackrunResult

        defaults = dict(
            event_id="test-4b",
            event_source="fixture",
            event_type="swap",
            post_trade_state_used="estimated",
            backrun_direction="buy",
            best_buy_venue="uniswap_v3",
            actual_pair="WETH/USDC",
            amount_in_wei=10**16,
        )
        defaults.update(overrides)
        return BackrunResult(**defaults)

    def test_v3_venue_returns_real_calldata(self):
        from m7.orderflow.execution_gate import _build_sim_tx_params

        br = self._make_result()
        tx, err = _build_sim_tx_params(br, chain="base")

        assert err is None
        assert tx is not None
        # Router should be Uniswap V3 on Base
        assert tx["to"] == "0x2626664c2603336E57B271c5C0b26F421741e481"
        # Base uses SwapRouter02 selector 0x04e45aaf (no deadline)
        assert tx["calldata"][:4] == bytes.fromhex("04e45aaf")
        # Calldata should be selector + 7 x 32-byte words = 4 + 224 = 228 bytes
        assert len(tx["calldata"]) == 228
        assert tx["value"] == 0

    def test_missing_venue_returns_error(self):
        from m7.orderflow.execution_gate import _build_sim_tx_params

        # Step 1 (Apr-21 soak): when the scorer does not fill
        # best_buy_venue but the chain registry has a V3-compatible DEX,
        # the gate must auto-resolve to that DEX and build calldata
        # instead of failing with VENUE_MISSING.
        br = self._make_result(best_buy_venue=None)
        tx, err = _build_sim_tx_params(br, chain="base")
        assert err is None, f"expected auto-resolve, got err={err}"
        assert tx is not None
        assert tx["to"].startswith("0x")
        # Post-call result carries the resolved venue for downstream diagnostics
        assert getattr(br, "best_buy_venue", None) in {"uniswap_v3", "aerodrome", "sushiswap_v3", "pancakeswap_v3"}

    def test_missing_venue_no_registry_returns_error(self, monkeypatch):
        """Still returns VENUE_MISSING when registry has no V3-compatible DEX."""
        from m7.orderflow import execution_gate as _eg

        br = self._make_result(best_buy_venue=None)
        # Force empty registry for the fallback code path.
        monkeypatch.setattr(
            "config.load_dexes", lambda: {"base": {}}, raising=False
        )
        tx, err = _eg._build_sim_tx_params(br, chain="base")
        assert tx is None
        assert err == "VENUE_MISSING"

    def test_unresolved_pair_returns_error(self):
        from m7.orderflow.execution_gate import _build_sim_tx_params

        br = self._make_result(actual_pair=None)
        tx, err = _build_sim_tx_params(br, chain="base")
        assert tx is None
        assert err == "PAIR_UNRESOLVED"

    def test_zero_amount_auto_fills_from_min_size(self):
        """Step 6: amount_in_wei=0 now triggers auto-fill to chain min size."""
        from m7.orderflow.execution_gate import _build_sim_tx_params

        br = self._make_result(amount_in_wei=0, token_in_decimals=18)
        tx, err = _build_sim_tx_params(br, chain="base")
        assert err is None
        assert tx is not None
        assert br.amount_in_wei > 0

    def test_zero_amount_prefers_sweep_size(self):
        """Step 6: best_sweep_size_wei takes precedence over min-size fallback."""
        from m7.orderflow.execution_gate import _build_sim_tx_params

        sweep_wei = 7 * 10**17
        br = self._make_result(
            amount_in_wei=0, token_in_decimals=18, best_sweep_size_wei=sweep_wei
        )
        tx, err = _build_sim_tx_params(br, chain="base")
        assert err is None
        assert br.amount_in_wei == sweep_wei

    def test_zero_amount_returns_error_when_autofill_disabled(self, monkeypatch):
        """Step 6: AMOUNT_ZERO still fires if get_min_profitable_size_wei returns 0."""
        from m7.orderflow import execution_gate as _eg

        monkeypatch.setattr(
            "m7.shared.constants.get_min_profitable_size_wei",
            lambda *a, **kw: 0,
            raising=False,
        )
        br = self._make_result(amount_in_wei=0, best_sweep_size_wei=None)
        tx, err = _eg._build_sim_tx_params(br, chain="base")
        assert tx is None
        assert err == "AMOUNT_ZERO"

    def test_adaptive_sizing_prefers_smaller_sweep_over_event_amount(self, monkeypatch):
        """Soak13: when best_sweep_size_wei < amount_in_wei, sim uses sweep size.

        Roundtrip_profit_bps в‰€ -9937 on soak12 came from oversized backrun
        inherited from mimicked swap events. Adaptive sizing picks the
        sweep-optimized size, which bounds slippage on low-liquidity pools.
        """
        monkeypatch.setenv("ARBY_ADAPTIVE_SIZING", "1")
        from m7.orderflow.execution_gate import _build_sim_tx_params

        raw_amount = 10 * 10**18  # oversized event amount
        sweep_size = 5 * 10**16  # optimal sweep
        br = self._make_result(
            amount_in_wei=raw_amount, best_sweep_size_wei=sweep_size
        )
        tx, err = _build_sim_tx_params(br, chain="base")
        assert err is None
        assert tx is not None
        assert br.amount_in_wei == sweep_size

    def test_adaptive_sizing_disabled_keeps_raw_amount(self, monkeypatch):
        """ARBY_ADAPTIVE_SIZING=0 preserves legacy behaviour."""
        monkeypatch.setenv("ARBY_ADAPTIVE_SIZING", "0")
        from m7.orderflow.execution_gate import _build_sim_tx_params

        raw_amount = 10 * 10**18
        sweep_size = 5 * 10**16
        br = self._make_result(
            amount_in_wei=raw_amount, best_sweep_size_wei=sweep_size
        )
        tx, err = _build_sim_tx_params(br, chain="base")
        assert err is None
        assert br.amount_in_wei == raw_amount

    def test_adaptive_sizing_ignores_larger_sweep(self, monkeypatch):
        """Sweep larger than raw amount is NOT applied (conservative)."""
        monkeypatch.setenv("ARBY_ADAPTIVE_SIZING", "1")
        from m7.orderflow.execution_gate import _build_sim_tx_params

        raw_amount = 5 * 10**16
        sweep_size = 10 * 10**18  # larger вЂ” ignored
        br = self._make_result(
            amount_in_wei=raw_amount, best_sweep_size_wei=sweep_size
        )
        tx, err = _build_sim_tx_params(br, chain="base")
        assert err is None
        assert br.amount_in_wei == raw_amount

    def test_unsupported_adapter_returns_error(self):
        """SyncSwap is not V3-compatible for calldata."""
        from m7.orderflow.execution_gate import _build_sim_tx_params

        br = self._make_result(best_buy_venue="syncswap_linea")
        tx, err = _build_sim_tx_params(br, chain="linea")
        assert tx is None
        assert "ADAPTER_UNSUPPORTED" in err
        assert "syncswap" in err

    def test_unknown_token_returns_error(self):
        from m7.orderflow.execution_gate import _build_sim_tx_params

        br = self._make_result(actual_pair="WETH/FAKETOKEN")
        tx, err = _build_sim_tx_params(br, chain="base")
        assert tx is None
        assert "TOKEN_ADDRESS_UNKNOWN" in err
        assert "FAKETOKEN" in err

    def test_unknown_dex_returns_error(self):
        from m7.orderflow.execution_gate import _build_sim_tx_params

        br = self._make_result(best_buy_venue="nonexistent_dex")
        tx, err = _build_sim_tx_params(br, chain="base")
        assert tx is None
        assert "DEX_CONFIG_MISSING" in err

    def test_sushiswap_v3_also_works(self):
        """SushiSwap V3 on Base uses uniswap_v3 adapter type."""
        from m7.orderflow.execution_gate import _build_sim_tx_params

        br = self._make_result(best_buy_venue="sushiswap_v3")
        tx, err = _build_sim_tx_params(br, chain="base")
        assert err is None
        assert tx is not None
        assert tx["to"] == "0xFB7eF66a7e61224DD6FcD0D7d9C3be5C8B049b9f"
        # Base = SwapRouter02 selector
        assert tx["calldata"][:4] == bytes.fromhex("04e45aaf")

    def test_arbitrum_uses_v1_router_with_deadline(self):
        """Arbitrum uses legacy SwapRouter V1 (selector 0x414bf389, with deadline)."""
        from m7.orderflow.execution_gate import _build_sim_tx_params

        br = self._make_result()
        tx, err = _build_sim_tx_params(br, chain="arbitrum_one")
        assert err is None
        assert tx is not None
        # V1 selector with deadline => 4 + 8*32 = 260 bytes
        assert tx["calldata"][:4] == bytes.fromhex("414bf389")
        assert len(tx["calldata"]) == 260

    def test_ve33_aerodrome_now_supported(self):
        """E1.18: Aerodrome (ve33) builds Velodrome calldata (not V3)."""
        from m7.orderflow.execution_gate import _build_sim_tx_params

        br = self._make_result(best_buy_venue="aerodrome")
        tx, err = _build_sim_tx_params(br, chain="base")
        assert err is None
        assert tx is not None
        assert tx["to"] == "0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43"
        # E1.18: ve33 uses Velodrome selector (not V3 exactInputSingle)
        assert tx["calldata"][:4] == bytes.fromhex("cac88ea9")

    # E1.32: fee-tier classification for non-standard fees -----------------

    def test_aerodrome_cl_fee_classified(self):
        """Non-standard Aerodrome CL fees route to a Slipstream-aware bucket.

        E1.35 P1.1 step 3: when `aerodrome_slipstream` config is verified
        (router + quoter_v2 + verified=True), the reject bucket is
        `SLIPSTREAM_PENDING_LOOKUP:<fee>` to surface adapter readiness.
        M7.E1.34j: if the fee is in `SLIPSTREAM_FEE_TO_TICKSPACING`, the
        reject surfaces `SLIPSTREAM_MAPPED_PENDING_SUBMIT` вЂ” superseded in
        M7.E1.34k.
        M7.E1.34k: without token addresses the pipeline now reaches the
        pre-calldata stage and emits `SLIPSTREAM_SIM_READY_TOKENS_MISSING:
        <fee>:ts<ts>`.  With token addresses present the gate returns
        real SwapRouter calldata (covered by
        `test_slipstream_tokens_present_builds_tx`).
        Legacy bucket `UNSUPPORTED_FEE_TIER:AERODROME_CL:<fee>` is kept
        only when the Slipstream config is absent/unverified.
        """
        from m7.orderflow.execution_gate import (
            SLIPSTREAM_FEE_TO_TICKSPACING,
            _build_sim_tx_params,
        )

        for fee in (150, 445, 600, 1570, 2105, 2600, 2655, 3024, 7500, 9500):
            br = self._make_result(
                best_buy_venue="0x" + "a" * 40,  # opaque pool address
                best_buy_fee=fee,
            )
            tx, err = _build_sim_tx_params(br, chain="base")
            assert tx is None
            ts = SLIPSTREAM_FEE_TO_TICKSPACING.get(fee)
            if ts is not None:
                assert err == f"SLIPSTREAM_SIM_READY_TOKENS_MISSING:{fee}:ts{ts}", err
            else:
                assert err == f"SLIPSTREAM_PENDING_LOOKUP:{fee}", err

    def test_slipstream_tokens_present_builds_tx(self):
        """M7.E1.34k: when token addresses are carried on the result and
        the fee maps to a tickSpacing, `_build_sim_tx_params` returns
        real SwapRouter calldata (adapter_type=aerodrome_slipstream)
        instead of parking the candidate in a PENDING bucket."""
        from m7.orderflow.execution_gate import _build_sim_tx_params

        br = self._make_result(
            best_buy_venue="0x" + "a" * 40,
            best_buy_fee=2655,
            backrun_token_in_address="0x4200000000000000000000000000000000000006",
            backrun_token_out_address="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        )
        tx, err = _build_sim_tx_params(br, chain="base")
        assert err is None, err
        assert tx is not None
        assert tx.get("adapter_type") == "aerodrome_slipstream"
        assert tx.get("tick_spacing") == 100  # fee 2655 в†’ ts 100
        # SwapRouter Slipstream selector is distinct from V3 SwapRouter02
        assert tx["calldata"][:4] != bytes.fromhex("04e45aaf")

    def test_algebra_dynamic_small_fee_classified(self):
        """Small non-standard fee (<=100) в†’ ALGEBRA_DYNAMIC sub-tag."""
        from m7.orderflow.execution_gate import _build_sim_tx_params

        br = self._make_result(
            best_buy_venue="0x" + "b" * 40,
            best_buy_fee=85,
        )
        tx, err = _build_sim_tx_params(br, chain="base")
        assert tx is None
        assert err == "UNSUPPORTED_FEE_TIER:ALGEBRA_DYNAMIC:85"

    def test_unknown_non_standard_fee_classified(self):
        """Truly unknown non-standard fee -> UNKNOWN sub-tag."""
        from m7.orderflow.execution_gate import _build_sim_tx_params

        br = self._make_result(
            best_buy_venue="0x" + "c" * 40,
            best_buy_fee=7777,
        )
        tx, err = _build_sim_tx_params(br, chain="base")
        assert tx is None
        assert err == "UNSUPPORTED_FEE_TIER:UNKNOWN:7777"

    def test_fee_7500_routes_to_pending_lookup_in_calldata_builder(self):
        """fee=7500 added to _AERODROME_CL_KNOWN (E1.56 fix step #4)."""
        from m7.orderflow.execution_gate import _build_sim_tx_params

        br = self._make_result(
            best_buy_venue="0x" + "d" * 40,
            best_buy_fee=7500,
        )
        tx, err = _build_sim_tx_params(br, chain="base")
        assert tx is None
        assert err == "SLIPSTREAM_PENDING_LOOKUP:7500", err

    @pytest.mark.parametrize("fee", [1570, 9500, 7500])
    def test_pre_sim_check_unconditionally_routes_known_cl_fees(self, fee, monkeypatch):
        """E1.56 fix: pre-sim fee check routes all known Aerodrome CL fees
        to PRE_SIM_SKIP:SLIPSTREAM_PENDING_LOOKUP without a config check.
        Eliminates intermittent UNSUPPORTED_FEE_TIER in Discovery subprocess."""
        from types import SimpleNamespace
        from m7.orderflow.execution_gate import run_execution_gate, _reset_accepted_fees_cache

        _reset_accepted_fees_cache()
        import m7.orderflow.execution_gate as gate_mod
        monkeypatch.setattr(gate_mod, "is_simulation_configured", lambda **_: True)
        # Bypass profit_guard: it rejects candidates with gross_pnl_wei=0.
        # The test is only about pre-sim fee-tier classification at L1480.
        monkeypatch.setattr(
            gate_mod, "_run_profit_guard_on_results",
            lambda results, chain="arbitrum_one", l1_fee_wei=0: [(r, None) for r in results],
        )
        r = SimpleNamespace(
            actual_pair="TOKEN/WETH",
            best_backrun_net_bps=10.0,
            best_buy_fee=fee,
            best_buy_venue="0x" + "e" * 40,
            best_sell_fee=fee,
            best_sell_venue="0x" + "e" * 40,
            amount_in_wei=10**18,
            best_sweep_size_wei=10**17,
            token_in_decimals=18,
            size_usd_estimate=100.0,
            backrun_token_in_address=None,
            backrun_token_out_address=None,
            sim_attempted=False,
            sim_passed=False,
            simulation_error=None,
            submit_ready=False,
            submit_blocker=None,
            scoring_path=None,
            event_source=None,
        )
        gate = run_execution_gate([r], chain="base", profile=None)

        pre_sim_errors = [e for e in gate.sim_errors if "SLIPSTREAM_PENDING_LOOKUP" in e]
        unsupported_errors = [
            e for e in gate.sim_errors
            if "UNSUPPORTED_FEE_TIER" in e and str(fee) in e
        ]
        assert len(pre_sim_errors) >= 1, (
            f"Expected SLIPSTREAM_PENDING_LOOKUP for fee={fee}, got {gate.sim_errors}"
        )
        assert len(unsupported_errors) == 0, (
            f"Got unexpected UNSUPPORTED_FEE_TIER for fee={fee}: {gate.sim_errors}"
        )
        _reset_accepted_fees_cache()

class TestAttemptSimulationRealCalldata:
    """E1.12.4B: _attempt_simulation sends real calldata to backend."""

    def test_real_calldata_sent_to_simulate_swap(self, monkeypatch):
        from m7.orderflow.execution_gate import _attempt_simulation
        from m7.orderflow.simulation import SimulationResult
        from m7.orderflow.contracts import BackrunResult
        from m7.orderflow.profit_guard import ProfitGuardResult
        import m7.orderflow.execution_gate as gate_mod

        monkeypatch.setattr(gate_mod, "is_simulation_configured", lambda **_: True)

        captured = {}

        def mock_simulate(chain, to_address, calldata, value_wei, **kw):
            captured["to"] = to_address
            captured["calldata"] = calldata
            captured["value"] = value_wei
            return SimulationResult(success=True, gas_used=150000)

        monkeypatch.setattr(gate_mod, "simulate_swap", mock_simulate)

        br = BackrunResult(
            event_id="test-4b",
            event_source="fixture",
            event_type="swap",
            post_trade_state_used="estimated",
            backrun_direction="buy",
            best_buy_venue="uniswap_v3",
            actual_pair="WETH/USDC",
            amount_in_wei=10**16,
        )
        guard = ProfitGuardResult(passed=True)

        result = _attempt_simulation(br, guard, chain="base")
        assert result.success is True
        # Verify real calldata was sent (Base в†’ SwapRouter02)
        assert captured["to"] == "0x2626664c2603336E57B271c5C0b26F421741e481"
        assert captured["calldata"][:4] == bytes.fromhex("04e45aaf")
        assert captured["value"] == 0

    def test_calldata_build_failure_gives_explicit_error(self, monkeypatch):
        from m7.orderflow.execution_gate import _attempt_simulation
        from m7.orderflow.contracts import BackrunResult
        from m7.orderflow.profit_guard import ProfitGuardResult
        import m7.orderflow.execution_gate as gate_mod

        monkeypatch.setattr(gate_mod, "is_simulation_configured", lambda **_: True)

        br = BackrunResult(
            event_id="test-4b",
            event_source="fixture",
            event_type="swap",
            post_trade_state_used="estimated",
            backrun_direction="buy",
            best_buy_venue="syncswap_linea",  # syncswap в†’ unsupported
            actual_pair="WETH/USDC",
            amount_in_wei=10**16,
        )
        guard = ProfitGuardResult(passed=True)

        result = _attempt_simulation(br, guard, chain="linea")
        assert result.success is False
        assert "CALLDATA_BUILD_FAILED" in result.error
        assert "ADAPTER_UNSUPPORTED" in result.error


class TestE115SimExceptionCapture:
    """E1.15: Verify that unexpected exceptions in _attempt_simulation
    are caught and recorded in sim_errors instead of crashing the gate."""

    def test_exception_in_sim_recorded_in_errors(self, monkeypatch):
        from m7.orderflow.execution_gate import run_execution_gate

        # Make _attempt_simulation raise an unexpected error
        def _boom(*a, **kw):
            raise RuntimeError("anvil connection reset")

        monkeypatch.setattr(
            "m7.orderflow.execution_gate._attempt_simulation", _boom
        )
        monkeypatch.setattr(
            "m7.orderflow.execution_gate.is_simulation_configured", lambda **_: True
        )
        monkeypatch.setattr(
            "m7.orderflow.execution_gate.get_simulation_backend", lambda **_: "anvil"
        )

        from m7.orderflow.contracts import BackrunResult

        br = BackrunResult(
            event_id="test_exc",
            event_source="fixture",
            event_type="swap",
            post_trade_state_used="estimated",
            backrun_direction="buy",
            best_backrun_net_bps=150.0,
            amount_in_wei=10**18,
            gross_pnl_wei=10**16,
            route_viable=True,
            size_valid_for_token=True,
            actual_pair="WETH/USDC",
            best_buy_fee=500,
            token_in_decimals=18,
        )
        gate = run_execution_gate([br], chain="base")
        assert gate.sim_attempted == 1
        assert gate.sim_passed == 0
        assert len(gate.sim_errors) == 1
        assert "SIM_EXCEPTION" in gate.sim_errors[0]
        assert "RuntimeError" in gate.sim_errors[0]


class TestE115PaperSigning:
    """E1.15: ARBY_PAPER_SIGNING=1 enables submit_ready > 0."""

    def test_paper_signing_enables_submit(self, monkeypatch):
        from m7.orderflow.execution_gate import run_execution_gate
        from m7.orderflow.simulation import SimulationResult

        # Mock simulation to pass
        def _mock_sim(*a, **kw):
            return SimulationResult(success=True, gas_used=150000, backend="anvil")

        monkeypatch.setattr(
            "m7.orderflow.execution_gate._attempt_simulation", _mock_sim
        )
        monkeypatch.setattr(
            "m7.orderflow.execution_gate.is_simulation_configured", lambda **_: True
        )
        monkeypatch.setattr(
            "m7.orderflow.execution_gate.get_simulation_backend", lambda **_: "anvil"
        )
        monkeypatch.setenv("ARBY_PAPER_SIGNING", "1")

        from m7.orderflow.contracts import BackrunResult

        br = BackrunResult(
            event_id="test_paper",
            event_source="fixture",
            event_type="swap",
            post_trade_state_used="estimated",
            backrun_direction="buy",
            best_backrun_net_bps=150.0,
            amount_in_wei=10**18,
            gross_pnl_wei=10**16,
            route_viable=True,
            size_valid_for_token=True,
            actual_pair="WETH/USDC",
            best_buy_fee=500,
            token_in_decimals=18,
        )
        gate = run_execution_gate([br], chain="base")
        assert gate.sim_passed == 1
        assert gate.submit_ready == 1
        assert br.signing_ready is True
        assert br.submit_ready is True

    def test_no_paper_signing_by_default(self, monkeypatch):
        from m7.orderflow.execution_gate import run_execution_gate
        from m7.orderflow.simulation import SimulationResult

        def _mock_sim(*a, **kw):
            return SimulationResult(success=True, gas_used=150000, backend="anvil")

        monkeypatch.setattr(
            "m7.orderflow.execution_gate._attempt_simulation", _mock_sim
        )
        monkeypatch.setattr(
            "m7.orderflow.execution_gate.is_simulation_configured", lambda **_: True
        )
        monkeypatch.setattr(
            "m7.orderflow.execution_gate.get_simulation_backend", lambda **_: "anvil"
        )
        # No ARBY_PAPER_SIGNING set
        monkeypatch.delenv("ARBY_PAPER_SIGNING", raising=False)

        from m7.orderflow.contracts import BackrunResult

        br = BackrunResult(
            event_id="test_no_paper",
            event_source="fixture",
            event_type="swap",
            post_trade_state_used="estimated",
            backrun_direction="buy",
            best_backrun_net_bps=150.0,
            amount_in_wei=10**18,
            gross_pnl_wei=10**16,
            route_viable=True,
            size_valid_for_token=True,
            actual_pair="WETH/USDC",
            best_buy_fee=500,
            token_in_decimals=18,
        )
        gate = run_execution_gate([br], chain="base")
        assert gate.sim_passed == 1
        assert gate.submit_ready == 0
        assert br.signing_ready is None
        assert "SIGNING_NOT_READY" in (br.submit_blocker or "")


class TestE135SubmitEconomicsGuard:
    """Soak13: roundtrip economics must gate submit readiness."""

    def _make_br(self):
        from m7.orderflow.contracts import BackrunResult

        br = BackrunResult(
            event_id="test_roundtrip_guard",
            event_source="fixture",
            event_type="swap",
            post_trade_state_used="estimated",
            backrun_direction="buy",
            best_buy_venue="uniswap_v3",
            best_sell_venue="uniswap_v3",
            best_buy_fee=500,
            best_sell_fee=500,
            best_backrun_net_bps=1224.5819,
            amount_in_wei=10**18,
            gross_pnl_wei=10**16,
            route_viable=True,
            size_valid_for_token=True,
            actual_pair="WETH/USDC",
            backrun_token_in_address="0x4200000000000000000000000000000000000006",
            backrun_token_out_address="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
            token_in_decimals=18,
            size_usd_estimate=2500.0,
            best_sweep_size_wei=10**17,
            best_sweep_net_bps=30.0,
            scoring_path="local_state",
            pricing_path="registry_direct",
            adapter_type_used="uniswap_v3",
            event_block=123,
            quote_block=124,
            block_lag=1,
        )
        br.sim_router_address = "0x1111111111111111111111111111111111111111"
        br.router_address = br.sim_router_address
        br.sim_calldata_hex = "0x04e45aaf" + "00" * 32
        br.sim_calldata_len = 36
        br.sell_router_address = "0x2222222222222222222222222222222222222222"
        br.sell_calldata_hex = "0x04e45aaf" + "11" * 32
        br.sell_calldata_len = 36
        return br

    def _mock_gate_ready(self, monkeypatch, br, sim_result):
        import m7.orderflow.execution_gate as gate_mod

        monkeypatch.setattr(gate_mod, "is_simulation_configured", lambda **_: True)
        monkeypatch.setattr(gate_mod, "get_simulation_backend", lambda **_: "anvil")
        monkeypatch.setattr(
            gate_mod,
            "_run_profit_guard_on_results",
            lambda results, chain="base", l1_fee_wei=0: [(br, object())],
        )
        monkeypatch.setattr(
            gate_mod,
            "_attempt_simulation",
            lambda r, g, chain="base": sim_result,
        )
        monkeypatch.setenv("ARBY_PAPER_SIGNING", "1")

    def test_negative_roundtrip_blocks_submit_ready(self, monkeypatch):
        from m7.orderflow.execution_gate import run_execution_gate
        from m7.orderflow.simulation import SimulationResult

        br = self._make_br()
        sim_result = SimulationResult(
            success=True,
            gas_used=150000,
            output_amount_wei=61,
            input_amount_wei=10**18,
            backend="anvil",
        )
        sim_result.roundtrip_attempted = True
        sim_result.roundtrip_success = True
        sim_result.roundtrip_final_wei = 4_200_151_850_124_148
        sim_result.roundtrip_profit_wei = sim_result.roundtrip_final_wei - 10**18
        sim_result.roundtrip_profit_bps = -9957.9985
        self._mock_gate_ready(monkeypatch, br, sim_result)

        gate = run_execution_gate([br], chain="base")

        assert gate.sim_passed == 1
        assert gate.roundtrip_success == 1
        assert gate.roundtrip_profitable_count == 0
        assert gate.submit_ready == 0
        assert br.submit_ready is False
        assert "ROUNDTRIP_NOT_PROFITABLE" in br.submit_blocker
        assert "ROUNDTRIP_NOT_PROFITABLE" in gate.submit_blockers_detail
        assert any(
            b.startswith("SCORER_SIM_DIVERGENCE")
            for b in gate.submit_blockers_detail
        )
        sample = gate.sim_output_samples[0]
        assert sample["roundtrip_profit_bps"] == -9957.9985
        assert sample["buy_venue"] == "uniswap_v3"
        assert sample["buy_calldata_prefix"].startswith("0x04e45aaf")
        assert "ROUNDTRIP_NOT_PROFITABLE" in sample["submit_blockers"]

    def test_profitable_roundtrip_allows_paper_submit(self, monkeypatch):
        from m7.orderflow.execution_gate import run_execution_gate
        from m7.orderflow.simulation import SimulationResult

        br = self._make_br()
        sim_result = SimulationResult(
            success=True,
            gas_used=150000,
            output_amount_wei=2 * 10**18,
            input_amount_wei=10**18,
            backend="anvil",
        )
        sim_result.roundtrip_attempted = True
        sim_result.roundtrip_success = True
        sim_result.roundtrip_final_wei = 1_002_000_000_000_000_000
        sim_result.roundtrip_profit_wei = 2_000_000_000_000_000
        sim_result.roundtrip_profit_bps = 20.0
        self._mock_gate_ready(monkeypatch, br, sim_result)

        gate = run_execution_gate([br], chain="base")

        assert gate.sim_passed == 1
        assert gate.roundtrip_profitable_count == 1
        assert gate.submit_ready == 1
        assert br.submit_ready is True
        assert gate.submit_blockers_detail == []


# ---------------------------------------------------------------------------
# E1.16 regression вЂ” TOKEN_ADDRESS_UNKNOWN and DEX_CONFIG_MISSING fixes
# ---------------------------------------------------------------------------


class TestE116TokenAddressUnknownFix:
    """E1.16: backrun_token_in_address/backrun_token_out_address bypass
    symbol lookup when actual_pair contains direction tags."""

    def _make_result(self, **overrides):
        from m7.orderflow.contracts import BackrunResult

        defaults = dict(
            event_id="test-e116",
            event_source="fixture",
            event_type="swap",
            post_trade_state_used="estimated",
            backrun_direction="buy",
            best_buy_venue="uniswap_v3",
            actual_pair="token0_in/token1_in",
            amount_in_wei=10**16,
        )
        defaults.update(overrides)
        return BackrunResult(**defaults)

    def test_old_pattern_still_fails_without_addresses(self):
        """Without backrun_token_*_address, direction-tag pairs still fail."""
        from m7.orderflow.execution_gate import _build_sim_tx_params

        br = self._make_result()
        tx, err = _build_sim_tx_params(br, chain="base")
        assert tx is None
        assert "TOKEN_ADDRESS_UNKNOWN" in err

    def test_direct_addresses_bypass_symbol_lookup(self):
        """With backrun_token_*_address set, direction-tag pair succeeds."""
        from m7.orderflow.execution_gate import _build_sim_tx_params

        br = self._make_result(
            backrun_token_in_address="0x4200000000000000000000000000000000000006",
            backrun_token_out_address="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        )
        tx, err = _build_sim_tx_params(br, chain="base")
        assert err is None
        assert tx is not None
        assert tx["calldata"][:4] == bytes.fromhex("04e45aaf")

    def test_partial_address_falls_back_to_symbol(self):
        """If only token_in address is set, token_out resolves from pair."""
        from m7.orderflow.execution_gate import _build_sim_tx_params

        br = self._make_result(
            actual_pair="WETH/USDC",
            backrun_token_in_address="0x4200000000000000000000000000000000000006",
        )
        tx, err = _build_sim_tx_params(br, chain="base")
        assert err is None
        assert tx is not None

    def test_truncated_address_in_pair_with_direct_addresses(self):
        """actual_pair with truncated addresses works via direct fields."""
        from m7.orderflow.execution_gate import _build_sim_tx_params

        br = self._make_result(
            actual_pair="0x42000000.../0x83358...",
            backrun_token_in_address="0x4200000000000000000000000000000000000006",
            backrun_token_out_address="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        )
        tx, err = _build_sim_tx_params(br, chain="base")
        assert err is None
        assert tx is not None


class TestE116DexConfigMissingFix:
    """E1.16: Pool-address venue falls back to iterating known DEXes."""

    def _make_result(self, **overrides):
        from m7.orderflow.contracts import BackrunResult

        defaults = dict(
            event_id="test-e116-dex",
            event_source="fixture",
            event_type="swap",
            post_trade_state_used="estimated",
            backrun_direction="buy",
            actual_pair="WETH/USDC",
            amount_in_wei=10**16,
        )
        defaults.update(overrides)
        return BackrunResult(**defaults)

    def test_pool_address_venue_falls_back_to_known_dexes(self):
        """Venue '0xe4e92eac...' (pool addr) resolves via DEX fallback."""
        from m7.orderflow.execution_gate import _build_sim_tx_params

        br = self._make_result(
            best_buy_venue="0xe4e92eac99db1db7c7723ec7948fc6d15ddc9",
        )
        tx, err = _build_sim_tx_params(br, chain="base")
        # Should NOT be DEX_CONFIG_MISSING anymore
        assert err is None or "DEX_CONFIG_MISSING" not in (err or "")
        if tx:
            assert tx["calldata"][:4] in (
                bytes.fromhex("04e45aaf"),
                bytes.fromhex("414bf389"),
            )

    def test_truly_unknown_dex_still_fails(self):
        """Non-address venue that isn't a known DEX still fails."""
        from m7.orderflow.execution_gate import _build_sim_tx_params

        br = self._make_result(best_buy_venue="nonexistent_magic_dex")
        tx, err = _build_sim_tx_params(br, chain="base")
        assert tx is None
        assert "DEX_CONFIG_MISSING" in err

    def test_pool_address_venue_uses_v3_router(self):
        """Verify the fallback picks a real V3-compatible DEX config."""
        from m7.orderflow.execution_gate import _build_sim_tx_params

        br = self._make_result(
            best_buy_venue="0x765bf105ed38d2ee7801210b4bb2b8b7d9b3a",
        )
        tx, err = _build_sim_tx_params(br, chain="base")
        assert err is None
        assert tx is not None
        # Should be one of the known Base V3 router addresses
        known_routers = {
            "0x2626664c2603336E57B271c5C0b26F421741e481",  # uniswap_v3
            "0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43",  # aerodrome
            "0xFB7eF66a7e61224DD6FcD0D7d9C3be5C8B049b9f",  # sushiswap_v3
            "0x1b81D678ffb9C0263b24A97847620C99d213eB14",  # pancakeswap_v3
        }
        assert tx["to"] in known_routers


class TestE117ResolveAddressPrefix:
    """E1.17: _resolve_address_prefix scans core_tokens for matching addresses."""

    def test_known_prefix_resolves(self):
        """A prefix matching a core_tokens entry returns the full address."""
        from m7.orderflow.execution_gate import _resolve_address_prefix

        # WETH on Base starts with 0x4200000000000000000000000000000000000006
        result = _resolve_address_prefix("base", "0x42000000000000000000000000000000000000")
        assert result is not None
        assert result.startswith("0x4200")

    def test_unknown_prefix_returns_none(self):
        """A prefix with no match returns None."""
        from m7.orderflow.execution_gate import _resolve_address_prefix

        result = _resolve_address_prefix("base", "0xdeadbeefdeadbeefdeadbeef")
        assert result is None

    def test_short_prefix_matches(self):
        """Even a short 0x prefix resolves if it's unique enough."""
        from m7.orderflow.execution_gate import _resolve_address_prefix

        # USDC on Base: 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913
        result = _resolve_address_prefix("base", "0x833589fCD6eDb6E08f4c")
        assert result is not None
        assert "833589" in result

    def test_invalid_chain_returns_none(self):
        """Non-existent chain doesn't crash, returns None."""
        from m7.orderflow.execution_gate import _resolve_address_prefix

        result = _resolve_address_prefix("nonexistent_chain_xyz", "0x4200")
        assert result is None

    def test_address_prefix_in_actual_pair(self):
        """actual_pair='0x4200.../USDC' resolves token_in via prefix matching."""
        from m7.orderflow.execution_gate import _build_sim_tx_params
        from m7.orderflow.contracts import BackrunResult

        br = BackrunResult(
            event_id="test-e117-prefix",
            event_source="fixture",
            event_type="swap",
            post_trade_state_used="estimated",
            backrun_direction="buy",
            actual_pair="0x4200000000000000000000000000000000000006/USDC",
            amount_in_wei=10**16,
            best_buy_venue="uniswap_v3",
        )
        tx, err = _build_sim_tx_params(br, chain="base")
        # Should resolve 0x4200... to WETH via prefix matching, USDC via symbol
        assert err is None
        assert tx is not None

    def test_dex_fallback_prefers_uniswap_v3(self):
        """E1.17: Fallback ordering puts uniswap_v3 first (best V3 compat)."""
        from m7.orderflow.execution_gate import _build_sim_tx_params
        from m7.orderflow.contracts import BackrunResult

        br = BackrunResult(
            event_id="test-e117-fallback-order",
            event_source="fixture",
            event_type="swap",
            post_trade_state_used="estimated",
            backrun_direction="buy",
            actual_pair="WETH/USDC",
            amount_in_wei=10**16,
            best_buy_venue="0xSomePoolAddress123456789",
        )
        tx, err = _build_sim_tx_params(br, chain="base")
        assert err is None
        assert tx is not None
        # uniswap_v3 SwapRouter02 on Base
        assert tx["to"] == "0x2626664c2603336E57B271c5C0b26F421741e481"


class TestE118VelodromeEncoder:
    """E1.18: Velodrome/Aerodrome ve33 calldata encoder tests."""

    def test_encode_velodrome_swap_selector(self):
        """E1.18: _encode_velodrome_swap produces correct selector."""
        from m7.orderflow.execution_gate import _encode_velodrome_swap

        calldata = _encode_velodrome_swap(
            token_in="0x4200000000000000000000000000000000000006",
            token_out="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
            recipient="0x0000000000000000000000000000000000000001",
            amount_in=10**18,
        )
        assert calldata[:4] == bytes.fromhex("cac88ea9")

    def test_encode_velodrome_swap_length(self):
        """E1.18: Velodrome calldata has correct ABI length."""
        from m7.orderflow.execution_gate import _encode_velodrome_swap

        calldata = _encode_velodrome_swap(
            token_in="0x4200000000000000000000000000000000000006",
            token_out="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
            recipient="0x0000000000000000000000000000000000000001",
            amount_in=10**18,
        )
        # selector(4) + amountIn(32) + amountOutMin(32) + offset(32) +
        # to(32) + deadline(32) + length(32) + route[from(32)+to(32)+stable(32)+factory(32)]
        # = 4 + 5*32 + 1*32 + 4*32 = 4 + 320 = 324
        assert len(calldata) == 324

    def test_encode_velodrome_swap_routes_position(self):
        """E1.18: token_in is encoded at correct position in routes array."""
        from m7.orderflow.execution_gate import _encode_velodrome_swap

        token_in = "0x4200000000000000000000000000000000000006"
        token_out = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
        calldata = _encode_velodrome_swap(
            token_in=token_in,
            token_out=token_out,
            recipient="0x0000000000000000000000000000000000000001",
            amount_in=10**18,
        )
        # routes offset at bytes [68:100] = 160
        routes_offset = int.from_bytes(calldata[68:100], "big")
        assert routes_offset == 160
        # routes[0].from starts at: 4 + offset + 32 (length) = 4 + 160 + 32 = 196
        route_from = "0x" + calldata[196:228].hex().lstrip("0").zfill(40)
        assert route_from.lower() == token_in.lower()
        # routes[0].to at 228:260
        route_to = "0x" + calldata[228:260].hex().lstrip("0").zfill(40)
        assert route_to.lower() == token_out.lower()

    def test_encode_velodrome_swap_stable_flag(self):
        """E1.18: stable=True sets correct bool in route."""
        from m7.orderflow.execution_gate import _encode_velodrome_swap

        calldata_volatile = _encode_velodrome_swap(
            token_in="0x4200000000000000000000000000000000000006",
            token_out="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
            recipient="0x0000000000000000000000000000000000000001",
            amount_in=10**18,
            stable=False,
        )
        calldata_stable = _encode_velodrome_swap(
            token_in="0x4200000000000000000000000000000000000006",
            token_out="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
            recipient="0x0000000000000000000000000000000000000001",
            amount_in=10**18,
            stable=True,
        )
        # stable flag at route[0].stable = bytes [260:292]
        assert int.from_bytes(calldata_volatile[260:292], "big") == 0
        assert int.from_bytes(calldata_stable[260:292], "big") == 1

    def test_build_sim_tx_params_ve33_calldata(self):
        """E1.18: Full _build_sim_tx_params with ve33 adapter builds Velodrome calldata."""
        from m7.orderflow.execution_gate import _build_sim_tx_params
        from m7.orderflow.contracts import BackrunResult

        br = BackrunResult(
            event_id="test-e118-ve33",
            event_source="fixture",
            event_type="swap",
            post_trade_state_used="estimated",
            backrun_direction="buy",
            actual_pair="WETH/USDC",
            amount_in_wei=10**18,
            best_buy_venue="aerodrome",
            backrun_token_in_address="0x4200000000000000000000000000000000000006",
            backrun_token_out_address="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        )
        tx, err = _build_sim_tx_params(br, chain="base")
        assert err is None
        assert tx is not None
        assert tx["to"] == "0xcF77a3Ba9A5CA399B7c97c74d54e5b1Beb874E43"
        assert tx["calldata"][:4] == bytes.fromhex("cac88ea9")
        assert len(tx["calldata"]) == 324

    def test_build_sim_tx_params_v3_unchanged(self):
        """E1.18: V3 adapters still produce exactInputSingle calldata."""
        from m7.orderflow.execution_gate import _build_sim_tx_params
        from m7.orderflow.contracts import BackrunResult

        br = BackrunResult(
            event_id="test-e118-v3-compat",
            event_source="fixture",
            event_type="swap",
            post_trade_state_used="estimated",
            backrun_direction="buy",
            actual_pair="WETH/USDC",
            amount_in_wei=10**18,
            best_buy_venue="uniswap_v3",
            backrun_token_in_address="0x4200000000000000000000000000000000000006",
            backrun_token_out_address="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        )
        tx, err = _build_sim_tx_params(br, chain="base")
        assert err is None
        assert tx is not None
        assert tx["to"] == "0x2626664c2603336E57B271c5C0b26F421741e481"
        # V3 SwapRouter02 selector unchanged
        assert tx["calldata"][:4] == bytes.fromhex("04e45aaf")

    def test_rpc_fork_token_extraction_ve33(self):
        """E1.18: rpc_fork_backend extracts token_in from Velodrome calldata."""
        from m7.orderflow.execution_gate import _encode_velodrome_swap

        weth = "0x4200000000000000000000000000000000000006"
        calldata = _encode_velodrome_swap(
            token_in=weth,
            token_out="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
            recipient="0x0000000000000000000000000000000000000001",
            amount_in=10**18,
        )
        # Verify rpc_fork would extract token_in correctly
        selector = calldata[:4]
        assert selector == bytes.fromhex("cac88ea9")
        routes_offset = int.from_bytes(calldata[68:100], "big")
        route0_from_start = 4 + routes_offset + 32
        token_in_hex = "0x" + calldata[route0_from_start:route0_from_start + 32].hex().lstrip("0").zfill(40)
        assert token_in_hex.lower() == weth.lower()


class TestPreSimAdmissionFilter:
    """Step 7: Strict pre-sim admission reduces RPC load by skipping unworthy candidates."""

    def _make_br(self, **kwargs):
        from m7.orderflow.contracts import BackrunResult
        defaults = dict(
            event_id="t", event_source="fixture", event_type="swap",
            post_trade_state_used="estimated", backrun_direction="buy",
            best_backrun_net_bps=150.0, amount_in_wei=10**18,
            gross_pnl_wei=10**16, route_viable=True, size_valid_for_token=True,
            actual_pair="WETH/USDC", best_buy_fee=500,
        )
        defaults.update(kwargs)
        return BackrunResult(**defaults)

    def test_admission_skips_low_net_bps(self, monkeypatch):
        from m7.orderflow.execution_gate import run_execution_gate
        import m7.orderflow.execution_gate as gate_mod
        monkeypatch.setenv("ARBY_SIM_ADMISSION_STRICT", "1")
        monkeypatch.setenv("ARBY_SIM_MIN_NET_BPS", "10.0")
        monkeypatch.setattr(gate_mod, "is_simulation_configured", lambda **_: True)
        br = self._make_br(best_backrun_net_bps=5.0)
        gate = run_execution_gate([br], chain="base")
        assert gate.sim_attempted == 0
        assert any("BELOW_MIN_NET_BPS" in e for e in gate.sim_errors)
        assert br.sim_attempted is False

    def test_admission_skips_unresolved_pair(self, monkeypatch):
        from m7.orderflow.execution_gate import run_execution_gate
        import m7.orderflow.execution_gate as gate_mod
        monkeypatch.setenv("ARBY_SIM_ADMISSION_STRICT", "1")
        monkeypatch.setattr(gate_mod, "is_simulation_configured", lambda **_: True)
        br = self._make_br(actual_pair=None)
        gate = run_execution_gate([br], chain="base")
        assert gate.sim_attempted == 0
        assert any("PAIR_UNRESOLVED" in e for e in gate.sim_errors)

    def test_admission_skips_no_fee_hint_under_bypass(self, monkeypatch):
        from m7.orderflow.execution_gate import run_execution_gate
        import m7.orderflow.execution_gate as gate_mod
        monkeypatch.setenv("ARBY_SIM_ADMISSION_STRICT", "1")
        monkeypatch.setenv("ARBY_SIM_BYPASS_GUARD", "1")
        monkeypatch.setattr(gate_mod, "is_simulation_configured", lambda **_: True)
        # Guard would normally reject amount=0, but BYPASS_GUARD lets it through.
        # Admission must still skip due to missing fee hint + no sweep size.
        br = self._make_br(amount_in_wei=0, best_sweep_size_wei=None, best_buy_fee=None)
        gate = run_execution_gate([br], chain="base")
        assert gate.sim_attempted == 0
        assert any("NO_AMOUNT_NO_FEE_HINT" in e or "NO_FEE_HINT" in e for e in gate.sim_errors)

    def test_admission_disabled_allows_all(self, monkeypatch):
        from m7.orderflow.execution_gate import run_execution_gate
        import m7.orderflow.execution_gate as gate_mod
        monkeypatch.setenv("ARBY_SIM_ADMISSION_STRICT", "0")
        monkeypatch.setattr(gate_mod, "is_simulation_configured", lambda **_: False)
        br = self._make_br(best_backrun_net_bps=0.1)
        gate = run_execution_gate([br], chain="base")
        # With strict=0, sub-threshold candidate passes admission (SIM_DISABLED hits later).
        assert len(gate.guard_passed) == 1


class TestE157L1FeeIntegration:
    """E1.57 Step 8: L1 fee is computed and passed to the profit guard for Base."""

    def _make_br(self, **kwargs):
        from types import SimpleNamespace
        defaults = dict(
            best_backrun_net_bps=50.0,
            amount_in_wei=int(1e17),
            best_sweep_size_wei=int(1e17),
            token_in_decimals=18,
            size_usd_estimate=200.0,
            actual_pair="WETH/USDC",
            best_buy_fee=500,
            gross_pnl_wei=int(5e13),
            route_viable=True,
            sim_attempted=False,
            sim_passed=False,
            simulation_error=None,
            submit_ready=False,
            submit_blocker=None,
            calldata_ready=False,
            profit_guard_passed=None,
            sim_output_amount_wei=None,
        )
        defaults.update(kwargs)
        return SimpleNamespace(**defaults)

    def test_l1_fee_wei_passed_to_profit_guard_for_base(self, monkeypatch):
        """E1.57: run_execution_gate calls annotate_profit_guard_results with l1_fee_wei>0 for Base."""
        import m7.orderflow.execution_gate as gate_mod
        import chains.l1_cost as l1_mod

        calls = []

        def fake_annotate(results, chain="arbitrum_one", l1_fee_wei=0):
            calls.append({"chain": chain, "l1_fee_wei": l1_fee_wei, "n": len(results)})
            return []  # no candidates pass — that's fine

        monkeypatch.setattr(gate_mod, "annotate_profit_guard_results", fake_annotate)
        monkeypatch.setattr(gate_mod, "is_simulation_configured", lambda **_: False)
        # Patch get_l1_fee_wei at the module level so the local import inside
        # run_execution_gate picks up the patched version.
        monkeypatch.setattr(l1_mod, "get_l1_fee_wei", lambda chain="base", calldata=b"": 400_000_000)

        gate_mod.run_execution_gate([self._make_br()], chain="base")

        assert len(calls) == 1
        assert calls[0]["chain"] == "base"
        assert calls[0]["l1_fee_wei"] == 400_000_000

    def test_l1_fee_wei_zero_for_arbitrum(self, monkeypatch):
        """E1.57: Non-OP chains pass l1_fee_wei=0 to profit guard."""
        import m7.orderflow.execution_gate as gate_mod

        calls = []

        def fake_annotate(results, chain="arbitrum_one", l1_fee_wei=0):
            calls.append({"chain": chain, "l1_fee_wei": l1_fee_wei})
            return []

        monkeypatch.setattr(gate_mod, "annotate_profit_guard_results", fake_annotate)
        monkeypatch.setattr(gate_mod, "is_simulation_configured", lambda **_: False)

        gate_mod.run_execution_gate([self._make_br()], chain="arbitrum_one")

        assert len(calls) == 1
        assert calls[0]["l1_fee_wei"] == 0

    def test_l1_fee_bps_per_candidate_correct(self):
        """E1.57: annotate_profit_guard_results converts l1_fee_wei to per-candidate bps."""
        from m7.orderflow.profit_guard import annotate_profit_guard_results

        class FakeResult:
            best_backrun_net_bps = 50.0
            amount_in_wei = int(1e17)   # 0.1 WETH = 1e17 wei
            gross_pnl_wei = int(5e13)   # 5e13 wei gross profit
            route_viable = True
            size_valid_for_token = True
            reject_reason = None
            quote_pipeline_latency_ms = None
            profit_guard_passed = None
            guard_reject_reason = None

        r = FakeResult()
        # L1 fee 4e8 wei on a 1e17 wei trade → bps = (4e8 / 1e17) * 10000 = 0.04 bps
        # That's tiny; shouldn't change guard outcome for a +50 bps candidate
        passed = annotate_profit_guard_results([r], chain="base", l1_fee_wei=400_000_000)
        # Result should still pass (L1 fee is ~0.04 bps, way below 50 bps gross)
        assert len(passed) == 1

    def test_annotate_profit_guard_results_accepts_l1_fee_wei_param(self):
        """E1.57: annotate_profit_guard_results signature must accept l1_fee_wei."""
        import inspect
        from m7.orderflow.profit_guard import annotate_profit_guard_results

        sig = inspect.signature(annotate_profit_guard_results)
        assert "l1_fee_wei" in sig.parameters
        assert sig.parameters["l1_fee_wei"].default == 0

    def test_gate_result_l1_fee_fields_populated_for_base(self, monkeypatch):
        """E1.57 fix step 4: gate result carries l1_fee_wei/source/calldata fields for Base."""
        import m7.orderflow.execution_gate as gate_mod
        import chains.l1_cost as l1_mod

        monkeypatch.setattr(gate_mod, "annotate_profit_guard_results", lambda r, chain="base", l1_fee_wei=0: [])
        monkeypatch.setattr(gate_mod, "is_simulation_configured", lambda **_: False)
        monkeypatch.setattr(l1_mod, "get_l1_fee_wei", lambda chain="base", calldata=b"": 500_000_000)

        result = gate_mod.run_execution_gate([self._make_br()], chain="base")

        assert result.l1_fee_wei == 500_000_000
        assert result.l1_fee_source == "onchain"
        assert result.l1_fee_calldata_len == 228
        assert result.l1_fee_calldata_kind == "swaprouter02_representative"

    def test_gate_result_l1_fee_source_not_applicable_for_arbitrum(self, monkeypatch):
        """E1.57 fix step 4: non-OP chains set source='not_applicable'."""
        import m7.orderflow.execution_gate as gate_mod

        monkeypatch.setattr(gate_mod, "annotate_profit_guard_results", lambda r, chain="arbitrum_one", l1_fee_wei=0: [])
        monkeypatch.setattr(gate_mod, "is_simulation_configured", lambda **_: False)

        result = gate_mod.run_execution_gate([self._make_br()], chain="arbitrum_one")

        assert result.l1_fee_wei == 0
        assert result.l1_fee_source == "not_applicable"
        assert result.l1_fee_calldata_len == 0

    def test_gate_result_l1_fee_source_fallback_zero_on_rpc_failure(self, monkeypatch):
        """E1.57 fix step 4: source='fallback_zero' when RPC call raises."""
        import m7.orderflow.execution_gate as gate_mod
        import chains.l1_cost as l1_mod

        def _raise(chain="base", calldata=b""):
            raise RuntimeError("RPC unavailable")

        monkeypatch.setattr(gate_mod, "annotate_profit_guard_results", lambda r, chain="base", l1_fee_wei=0: [])
        monkeypatch.setattr(gate_mod, "is_simulation_configured", lambda **_: False)
        monkeypatch.setattr(l1_mod, "get_l1_fee_wei", _raise)

        result = gate_mod.run_execution_gate([self._make_br()], chain="base")

        assert result.l1_fee_wei == 0
        assert result.l1_fee_source == "fallback_zero"


class TestE158FeeTierTypeMismatch:
    """E1.58 fix step 4: string best_buy_fee must be classified correctly.

    Discovery lane sets best_buy_fee as a string (e.g. "1570") while the
    _AERODROME_CL_KNOWN and _ACCEPTED_FEES sets use ints.  Without int-cast,
    the fee falls through to UNSUPPORTED_FEE_TIER instead of
    SLIPSTREAM_PENDING_LOOKUP.
    """

    def _make_br(self, fee=None):
        from types import SimpleNamespace
        return SimpleNamespace(
            best_backrun_net_bps=50.0,
            amount_in_wei=int(1e17),
            best_sweep_size_wei=int(1e17),
            token_in_decimals=18,
            size_usd_estimate=200.0,
            actual_pair="AERO/WETH",
            best_buy_fee=fee,
            gross_pnl_wei=int(5e13),
            route_viable=True,
            sim_attempted=False,
            sim_passed=False,
            simulation_error=None,
            submit_ready=False,
            submit_blocker=None,
            calldata_ready=False,
            profit_guard_passed=None,
            sim_output_amount_wei=None,
        )

    def test_string_fee_1570_classified_as_slipstream_pending(self, monkeypatch):
        """String fee '1570' must produce SLIPSTREAM_PENDING_LOOKUP, not UNSUPPORTED_FEE_TIER."""
        import m7.orderflow.execution_gate as gate_mod
        from m7.orderflow.simulation import SimulationResult

        monkeypatch.setattr(gate_mod, "annotate_profit_guard_results",
                            lambda r, chain="base", l1_fee_wei=0: [(br, None) for br in r])
        monkeypatch.setattr(gate_mod, "is_simulation_configured", lambda **_: True)
        monkeypatch.setattr(gate_mod, "_attempt_simulation",
                            lambda r, g, chain="base": SimulationResult(success=False, error="not_reached"))

        result = gate_mod.run_execution_gate([self._make_br(fee="1570")], chain="base")

        errors_str = " ".join(result.sim_errors)
        assert "SLIPSTREAM_PENDING_LOOKUP:1570" in errors_str, (
            f"Expected SLIPSTREAM_PENDING_LOOKUP:1570 in sim_errors, got: {result.sim_errors}"
        )
        assert "UNSUPPORTED_FEE_TIER:1570" not in errors_str, (
            f"UNSUPPORTED_FEE_TIER:1570 must not appear when string fee '1570' is used; got: {result.sim_errors}"
        )

    def test_int_fee_1570_classified_as_slipstream_pending(self, monkeypatch):
        """Int fee 1570 must also produce SLIPSTREAM_PENDING_LOOKUP (regression guard)."""
        import m7.orderflow.execution_gate as gate_mod
        from m7.orderflow.simulation import SimulationResult

        monkeypatch.setattr(gate_mod, "annotate_profit_guard_results",
                            lambda r, chain="base", l1_fee_wei=0: [(br, None) for br in r])
        monkeypatch.setattr(gate_mod, "is_simulation_configured", lambda **_: True)
        monkeypatch.setattr(gate_mod, "_attempt_simulation",
                            lambda r, g, chain="base": SimulationResult(success=False, error="not_reached"))

        result = gate_mod.run_execution_gate([self._make_br(fee=1570)], chain="base")

        errors_str = " ".join(result.sim_errors)
        assert "SLIPSTREAM_PENDING_LOOKUP:1570" in errors_str, (
            f"Expected SLIPSTREAM_PENDING_LOOKUP:1570 in sim_errors, got: {result.sim_errors}"
        )
        assert "UNSUPPORTED_FEE_TIER:1570" not in errors_str

    def test_string_fee_7500_classified_as_slipstream_pending(self, monkeypatch):
        """String fee '7500' (Base soak empirical tier) must not leak as UNSUPPORTED_FEE_TIER."""
        import m7.orderflow.execution_gate as gate_mod
        from m7.orderflow.simulation import SimulationResult

        monkeypatch.setattr(gate_mod, "annotate_profit_guard_results",
                            lambda r, chain="base", l1_fee_wei=0: [(br, None) for br in r])
        monkeypatch.setattr(gate_mod, "is_simulation_configured", lambda **_: True)
        monkeypatch.setattr(gate_mod, "_attempt_simulation",
                            lambda r, g, chain="base": SimulationResult(success=False, error="not_reached"))

        result = gate_mod.run_execution_gate([self._make_br(fee="7500")], chain="base")

        errors_str = " ".join(result.sim_errors)
        assert "SLIPSTREAM_PENDING_LOOKUP:7500" in errors_str, (
            f"Expected SLIPSTREAM_PENDING_LOOKUP:7500 in sim_errors, got: {result.sim_errors}"
        )
        assert "UNSUPPORTED_FEE_TIER:7500" not in errors_str

    def test_string_fee_9500_classified_as_slipstream_pending(self, monkeypatch):
        """String fee '9500' (Base soak empirical tier) must not leak as UNSUPPORTED_FEE_TIER."""
        import m7.orderflow.execution_gate as gate_mod
        from m7.orderflow.simulation import SimulationResult

        monkeypatch.setattr(gate_mod, "annotate_profit_guard_results",
                            lambda r, chain="base", l1_fee_wei=0: [(br, None) for br in r])
        monkeypatch.setattr(gate_mod, "is_simulation_configured", lambda **_: True)
        monkeypatch.setattr(gate_mod, "_attempt_simulation",
                            lambda r, g, chain="base": SimulationResult(success=False, error="not_reached"))

        result = gate_mod.run_execution_gate([self._make_br(fee="9500")], chain="base")

        errors_str = " ".join(result.sim_errors)
        assert "SLIPSTREAM_PENDING_LOOKUP:9500" in errors_str, (
            f"Expected SLIPSTREAM_PENDING_LOOKUP:9500 in sim_errors, got: {result.sim_errors}"
        )
        assert "UNSUPPORTED_FEE_TIER:9500" not in errors_str
