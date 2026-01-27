# PATH: strategy/execution/__init__.py
"""
Execution layer skeleton for ARBY (STEP 10).

All components are disabled by default.
M5 will enable them incrementally.
"""

from strategy.execution.state_machine import ExecutionState, ExecutionStateMachine
from strategy.execution.simulator_gate import SimulatorGate
from strategy.execution.accounting import AccountingStub
from strategy.execution.kill_switch import KillSwitch

__all__ = [
    "ExecutionState",
    "ExecutionStateMachine",
    "SimulatorGate",
    "AccountingStub",
    "KillSwitch",
]
