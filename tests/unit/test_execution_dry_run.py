# PATH: tests/unit/test_execution_dry_run.py
"""
Tests for M4.3 execution dry-run stub.

v2.1.0-fix: Verifies execution path with kill_switch=True by default.
"""

import pytest
from execution.state_machine import (
    TradeStateMachine,
    TradeState,
    ExecutionContext,
    ExecutionMode,
    get_execution_context,
    simulate_trade_execution,
)


class TestExecutionContext:
    """Tests for ExecutionContext safety controls."""

    def test_default_context_blocks_execution(self):
        """Default context should block execution (kill switch ON)."""
        ctx = ExecutionContext()
        
        assert ctx.kill_switch_active is True
        assert ctx.mode == ExecutionMode.DRY_RUN
        assert ctx.is_execution_allowed() is False
        assert ctx.get_execution_blocker() == "KILL_SWITCH_ACTIVE"

    def test_live_mode_still_blocked_by_kill_switch(self):
        """Even in LIVE mode, kill switch should block."""
        ctx = ExecutionContext(mode=ExecutionMode.LIVE, kill_switch_active=True)
        
        assert ctx.is_execution_allowed() is False
        assert ctx.get_execution_blocker() == "KILL_SWITCH_ACTIVE"

    def test_blockers_prevent_execution(self):
        """Blockers list should prevent execution."""
        ctx = ExecutionContext(
            mode=ExecutionMode.LIVE,
            kill_switch_active=False,
            blockers=["TEST_BLOCKER"],
        )
        
        assert ctx.is_execution_allowed() is False
        assert ctx.get_execution_blocker() == "TEST_BLOCKER"

    def test_fully_enabled_allows_execution(self):
        """Only when all conditions met should execution be allowed."""
        ctx = ExecutionContext(
            mode=ExecutionMode.LIVE,
            kill_switch_active=False,
            blockers=[],
        )
        
        assert ctx.is_execution_allowed() is True
        assert ctx.get_execution_blocker() is None


class TestTradeStateMachine:
    """Tests for TradeStateMachine transitions."""

    def test_pending_to_simulating(self):
        """Trade should transition from PENDING to SIMULATING."""
        trade = TradeStateMachine(trade_id="test-001")
        assert trade.state == TradeState.PENDING
        
        trade.transition_to(TradeState.SIMULATING, reason="Starting simulation")
        assert trade.state == TradeState.SIMULATING
        assert len(trade.history) == 1

    def test_sim_passed_to_killed(self):
        """Kill switch should work from SIM_PASSED."""
        trade = TradeStateMachine(trade_id="test-002")
        trade.transition_to(TradeState.SIMULATING)
        trade.transition_to(TradeState.SIM_PASSED)
        
        trade.kill(reason="Kill switch activated")
        assert trade.state == TradeState.KILLED
        assert trade.is_failed is True


class TestSimulateTradeExecution:
    """Tests for simulate_trade_execution dry-run stub."""

    def test_profitable_roundtrip_sim_passes(self):
        """Profitable roundtrip should pass simulation."""
        trade = TradeStateMachine(trade_id="rt-001")
        roundtrip = {
            "is_profitable": True,
            "net_pnl_bps": 5.0,
            "net_pnl_wei": "1000000000000000",
            "gas_cost_wei": "50000000000000",
        }
        
        result = simulate_trade_execution(trade, roundtrip_result=roundtrip)
        
        assert result["sim_passed"] is True
        assert result["final_state"] == "SIM_PASSED"
        # But execution blocked by kill switch
        assert result["would_execute"] is False
        assert result["blocker"] == "KILL_SWITCH_ACTIVE"

    def test_unprofitable_roundtrip_sim_fails(self):
        """Unprofitable roundtrip should fail simulation."""
        trade = TradeStateMachine(trade_id="rt-002")
        roundtrip = {
            "is_profitable": False,
            "net_pnl_bps": -3.0,
            "net_pnl_wei": "-500000000000000",
        }
        
        result = simulate_trade_execution(trade, roundtrip_result=roundtrip)
        
        assert result["sim_passed"] is False
        assert result["final_state"] == "SIM_FAILED"
        assert result["would_execute"] is False

    def test_eth_call_failure_blocks_sim(self):
        """Failed eth_call should fail simulation."""
        trade = TradeStateMachine(trade_id="rt-003")
        roundtrip = {"is_profitable": True}
        eth_call = {"success": False, "error": "execution reverted"}
        
        result = simulate_trade_execution(
            trade,
            roundtrip_result=roundtrip,
            eth_call_result=eth_call,
        )
        
        assert result["sim_passed"] is False
        assert result["final_state"] == "SIM_FAILED"

    def test_execution_context_in_result(self):
        """Result should include execution context."""
        trade = TradeStateMachine(trade_id="rt-004")
        
        result = simulate_trade_execution(trade)
        
        assert "execution_context" in result
        assert result["execution_context"]["kill_switch_active"] is True
        assert result["execution_context"]["mode"] == "DRY_RUN"
