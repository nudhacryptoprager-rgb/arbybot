# PATH: execution/__init__.py
"""
ARBY M4 Execution Layer.

This module contains the execution layer components:
- state_machine: Trade state machine with transitions
- simulator: Pre-trade simulation gate
- dex_dex_executor: DEX-DEX arbitrage executor

R28.15: Real implementations with tx build, signing policy,
receipts, fill parsing, gas accounting, and realized PnL.
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
from execution.economics import (
    min_required_spread_bps,
    spread_minus_required,
    fee_tier_to_bps,
    is_roundtrip_candidate,
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
    # Economics
    "min_required_spread_bps",
    "spread_minus_required",
    "fee_tier_to_bps",
    "is_roundtrip_candidate",
]
