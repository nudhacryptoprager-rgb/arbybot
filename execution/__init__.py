# PATH: execution/__init__.py
"""
ARBY M4 Execution Layer.

This module contains the execution layer components:
- state_machine: Trade state machine with transitions
- simulator: Pre-trade simulation gate
- dex_dex_executor: DEX-DEX arbitrage executor

NOTE: This is a skeleton for M4. Full implementation will follow
after M3 closure.
"""

from execution.state_machine import (
    TradeState,
    TradeStateMachine,
    StateTransition,
    InvalidTransitionError,
    VALID_TRANSITIONS,
)
from execution.simulator import (
    SimulationResult,
    SimulationBlocker,
    SimulatorConfig,
    PreTradeSimulator,
)
from execution.dex_dex_executor import (
    ExecutionMethod,
    ExecutionBlocker,
    ExecutionResult,
    ExecutorConfig,
    DexDexExecutor,
)

__all__ = [
    # State machine
    "TradeState",
    "TradeStateMachine",
    "StateTransition",
    "InvalidTransitionError",
    "VALID_TRANSITIONS",
    # Simulator
    "SimulationResult",
    "SimulationBlocker",
    "SimulatorConfig",
    "PreTradeSimulator",
    # Executor
    "ExecutionMethod",
    "ExecutionBlocker",
    "ExecutionResult",
    "ExecutorConfig",
    "DexDexExecutor",
]
