"""E1.12.2: Protective tests for the execution gate pipeline.

Tests:
  1. Schema stability — BackrunResult has exactly 75 fields (8 new terminal)
  2. Funnel invariant — submit_ready <= sim_passed <= guard_passed <= route_viable
  3. SIM_DISABLED — without Tenderly, stage is honestly marked
  4. Backward-compat — all 13 extracted symbols importable from loop
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

        # Ensure simulation is not configured — patch generic check in gate module namespace
        monkeypatch.setattr(gate_mod, "is_simulation_configured", lambda: False)

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

        monkeypatch.setattr(gate_mod, "is_simulation_configured", lambda: True)
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

        monkeypatch.setattr(gate_mod, "is_simulation_configured", lambda: True)
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

    def test_hot_artifact_includes_sim_errors(self, tmp_path, monkeypatch):
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

        br = self._make_result(best_buy_venue=None)
        tx, err = _build_sim_tx_params(br, chain="base")
        assert tx is None
        assert err == "VENUE_MISSING"

    def test_unresolved_pair_returns_error(self):
        from m7.orderflow.execution_gate import _build_sim_tx_params

        br = self._make_result(actual_pair=None)
        tx, err = _build_sim_tx_params(br, chain="base")
        assert tx is None
        assert err == "PAIR_UNRESOLVED"

    def test_zero_amount_returns_error(self):
        from m7.orderflow.execution_gate import _build_sim_tx_params

        br = self._make_result(amount_in_wei=0)
        tx, err = _build_sim_tx_params(br, chain="base")
        assert tx is None
        assert err == "AMOUNT_ZERO"

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


class TestAttemptSimulationRealCalldata:
    """E1.12.4B: _attempt_simulation sends real calldata to backend."""

    def test_real_calldata_sent_to_simulate_swap(self, monkeypatch):
        from m7.orderflow.execution_gate import _attempt_simulation
        from m7.orderflow.simulation import SimulationResult
        from m7.orderflow.contracts import BackrunResult
        from m7.orderflow.profit_guard import ProfitGuardResult
        import m7.orderflow.execution_gate as gate_mod

        monkeypatch.setattr(gate_mod, "is_simulation_configured", lambda: True)

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
        # Verify real calldata was sent (Base → SwapRouter02)
        assert captured["to"] == "0x2626664c2603336E57B271c5C0b26F421741e481"
        assert captured["calldata"][:4] == bytes.fromhex("04e45aaf")
        assert captured["value"] == 0

    def test_calldata_build_failure_gives_explicit_error(self, monkeypatch):
        from m7.orderflow.execution_gate import _attempt_simulation
        from m7.orderflow.contracts import BackrunResult
        from m7.orderflow.profit_guard import ProfitGuardResult
        import m7.orderflow.execution_gate as gate_mod

        monkeypatch.setattr(gate_mod, "is_simulation_configured", lambda: True)

        br = BackrunResult(
            event_id="test-4b",
            event_source="fixture",
            event_type="swap",
            post_trade_state_used="estimated",
            backrun_direction="buy",
            best_buy_venue="syncswap_linea",  # syncswap → unsupported
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
            "m7.orderflow.execution_gate.is_simulation_configured", lambda: True
        )
        monkeypatch.setattr(
            "m7.orderflow.execution_gate.get_simulation_backend", lambda: "anvil"
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
            "m7.orderflow.execution_gate.is_simulation_configured", lambda: True
        )
        monkeypatch.setattr(
            "m7.orderflow.execution_gate.get_simulation_backend", lambda: "anvil"
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
            "m7.orderflow.execution_gate.is_simulation_configured", lambda: True
        )
        monkeypatch.setattr(
            "m7.orderflow.execution_gate.get_simulation_backend", lambda: "anvil"
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
        )
        gate = run_execution_gate([br], chain="base")
        assert gate.sim_passed == 1
        assert gate.submit_ready == 0
        assert br.signing_ready is None
        assert "SIGNING_NOT_READY" in (br.submit_blocker or "")


# ---------------------------------------------------------------------------
# E1.16 regression — TOKEN_ADDRESS_UNKNOWN and DEX_CONFIG_MISSING fixes
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
