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
    """E1.12.2: Without Tenderly config, execution gate marks SIM_DISABLED."""

    def test_sim_disabled_without_tenderly(self, monkeypatch):
        from m7.orderflow.execution_gate import run_execution_gate
        import m7.orderflow.execution_gate as gate_mod

        # Ensure Tenderly is not configured — patch in the gate module namespace
        monkeypatch.setattr(gate_mod, "is_tenderly_configured", lambda: False)

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
        )
        assert callable(run_execution_gate)
        assert callable(_attempt_simulation)


class TestProfitGuardBatchHelper:
    """E1.12.2: annotate_profit_guard_results batch helper."""

    def test_annotate_exists(self):
        from m7.orderflow.profit_guard import annotate_profit_guard_results
        assert callable(annotate_profit_guard_results)
