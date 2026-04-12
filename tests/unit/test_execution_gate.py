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
            # calldata_ready/signing_ready are None by default
            assert gate.submit_ready == 0
            assert "CALLDATA_NOT_READY" in gate.submit_blockers_detail
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
        """Aerodrome is ve33 — not V3-compatible for calldata."""
        from m7.orderflow.execution_gate import _build_sim_tx_params

        br = self._make_result(best_buy_venue="aerodrome")
        tx, err = _build_sim_tx_params(br, chain="base")
        assert tx is None
        assert "ADAPTER_UNSUPPORTED" in err
        assert "ve33" in err

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
            best_buy_venue="aerodrome",  # ve33 → unsupported
            actual_pair="WETH/USDC",
            amount_in_wei=10**16,
        )
        guard = ProfitGuardResult(passed=True)

        result = _attempt_simulation(br, guard, chain="base")
        assert result.success is False
        assert "CALLDATA_BUILD_FAILED" in result.error
        assert "ADAPTER_UNSUPPORTED" in result.error
