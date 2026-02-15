"""
Unit tests for v2.1.0 execution state machine.

Tests:
- ExecutionContext with kill switch
- Execution mode gating
- State transitions
"""
import unittest


class TestExecutionContext(unittest.TestCase):
    """Tests for ExecutionContext and kill switch."""
    
    def test_imports(self):
        """ExecutionContext imports correctly."""
        from execution.state_machine import (
            ExecutionContext,
            ExecutionMode,
            get_execution_context,
        )
        ctx = get_execution_context()
        self.assertIsInstance(ctx, ExecutionContext)
    
    def test_default_mode_is_dry_run(self):
        """Default mode is DRY_RUN for safety."""
        from execution.state_machine import ExecutionContext, ExecutionMode
        ctx = ExecutionContext()
        self.assertEqual(ctx.mode, ExecutionMode.DRY_RUN)
    
    def test_default_kill_switch_active(self):
        """Kill switch is ON by default."""
        from execution.state_machine import ExecutionContext
        ctx = ExecutionContext()
        self.assertTrue(ctx.kill_switch_active)
    
    def test_execution_not_allowed_with_kill_switch(self):
        """Execution blocked when kill switch active."""
        from execution.state_machine import ExecutionContext, ExecutionMode
        ctx = ExecutionContext(mode=ExecutionMode.LIVE, kill_switch_active=True)
        self.assertFalse(ctx.is_execution_allowed())
        self.assertEqual(ctx.get_execution_blocker(), "KILL_SWITCH_ACTIVE")
    
    def test_execution_not_allowed_in_dry_run(self):
        """Execution blocked in DRY_RUN mode."""
        from execution.state_machine import ExecutionContext, ExecutionMode
        ctx = ExecutionContext(mode=ExecutionMode.DRY_RUN, kill_switch_active=False, blockers=[])
        self.assertFalse(ctx.is_execution_allowed())
        self.assertEqual(ctx.get_execution_blocker(), "MODE_DRY_RUN")
    
    def test_execution_not_allowed_with_blockers(self):
        """Execution blocked when blockers present."""
        from execution.state_machine import ExecutionContext, ExecutionMode
        ctx = ExecutionContext(
            mode=ExecutionMode.LIVE,
            kill_switch_active=False,
            blockers=["EXECUTION_DISABLED_M5_0"]
        )
        self.assertFalse(ctx.is_execution_allowed())
        self.assertEqual(ctx.get_execution_blocker(), "EXECUTION_DISABLED_M5_0")
    
    def test_execution_allowed_when_all_clear(self):
        """Execution allowed only when all checks pass."""
        from execution.state_machine import ExecutionContext, ExecutionMode
        ctx = ExecutionContext(
            mode=ExecutionMode.LIVE,
            kill_switch_active=False,
            blockers=[]
        )
        self.assertTrue(ctx.is_execution_allowed())
        self.assertIsNone(ctx.get_execution_blocker())
    
    def test_to_dict_serialization(self):
        """ExecutionContext serializes correctly."""
        from execution.state_machine import ExecutionContext, ExecutionMode
        ctx = ExecutionContext()
        d = ctx.to_dict()
        
        self.assertIn("mode", d)
        self.assertIn("kill_switch_active", d)
        self.assertIn("blockers", d)
        self.assertIn("is_execution_allowed", d)
        self.assertIn("execution_blocker", d)
        
        self.assertEqual(d["mode"], "DRY_RUN")
        self.assertTrue(d["kill_switch_active"])


class TestStateMachineKillSwitch(unittest.TestCase):
    """Tests for TradeStateMachine kill switch integration."""
    
    def test_kill_switch_from_any_state(self):
        """Kill switch can be triggered from most states."""
        from execution.state_machine import TradeStateMachine, TradeState
        
        for start_state in [TradeState.PENDING, TradeState.SIMULATING, 
                           TradeState.SIM_PASSED, TradeState.SUBMITTING]:
            sm = TradeStateMachine(trade_id="test")
            sm.state = start_state
            
            transition = sm.kill("Test kill")
            self.assertEqual(sm.state, TradeState.KILLED)
            self.assertEqual(transition.reason, "Test kill")
    
    def test_cannot_kill_terminal_state(self):
        """Cannot kill from terminal states."""
        from execution.state_machine import TradeStateMachine, TradeState, InvalidTransitionError
        
        terminal_states = [TradeState.CONFIRMED, TradeState.FAILED, 
                          TradeState.KILLED, TradeState.SIM_FAILED]
        
        for terminal in terminal_states:
            sm = TradeStateMachine(trade_id="test")
            sm.state = terminal
            
            with self.assertRaises(InvalidTransitionError):
                sm.kill("Should fail")


class TestTradeStateTransitions(unittest.TestCase):
    """Tests for trade state transitions."""
    
    def test_happy_path(self):
        """Normal execution flow: PENDING -> CONFIRMED."""
        from execution.state_machine import TradeStateMachine, TradeState
        
        sm = TradeStateMachine(trade_id="happy_trade")
        self.assertEqual(sm.state, TradeState.PENDING)
        
        sm.transition_to(TradeState.SIMULATING, reason="Starting sim")
        self.assertEqual(sm.state, TradeState.SIMULATING)
        
        sm.transition_to(TradeState.SIM_PASSED, reason="Sim passed")
        self.assertEqual(sm.state, TradeState.SIM_PASSED)
        
        sm.transition_to(TradeState.SUBMITTING, reason="Submitting")
        sm.transition_to(TradeState.SUBMITTED, reason="In mempool")
        sm.transition_to(TradeState.CONFIRMING, reason="Waiting")
        sm.transition_to(TradeState.CONFIRMED, reason="Success!")
        
        self.assertTrue(sm.is_success)
        self.assertTrue(sm.is_terminal)
        self.assertFalse(sm.is_failed)
        self.assertEqual(len(sm.history), 6)
    
    def test_invalid_transition_raises(self):
        """Invalid transitions raise InvalidTransitionError."""
        from execution.state_machine import TradeStateMachine, TradeState, InvalidTransitionError
        
        sm = TradeStateMachine(trade_id="test")
        
        with self.assertRaises(InvalidTransitionError):
            sm.transition_to(TradeState.CONFIRMED)  # Can't go PENDING -> CONFIRMED
    
    def test_to_dict_includes_history(self):
        """to_dict includes state history."""
        from execution.state_machine import TradeStateMachine, TradeState
        
        sm = TradeStateMachine(trade_id="serializable")
        sm.transition_to(TradeState.SIMULATING)
        sm.transition_to(TradeState.SIM_FAILED, reason="Revert detected")
        
        d = sm.to_dict()
        
        self.assertEqual(d["trade_id"], "serializable")
        self.assertEqual(d["state"], "SIM_FAILED")
        self.assertTrue(d["is_terminal"])
        self.assertTrue(d["is_failed"])
        self.assertEqual(len(d["history"]), 2)


if __name__ == "__main__":
    unittest.main()
