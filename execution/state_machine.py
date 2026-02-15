# PATH: execution/state_machine.py
"""
ARBY M4 Execution State Machine.

EXECUTION STATE CONTRACT:
=========================

States (TradeState):
  PENDING     → trade created, not yet submitted
  SIMULATING  → running pre-trade simulation
  SIM_PASSED  → simulation passed, ready to submit
  SIM_FAILED  → simulation failed, will not submit
  SUBMITTING  → transaction submitted to network
  SUBMITTED   → transaction in mempool
  CONFIRMING  → waiting for confirmation
  CONFIRMED   → transaction confirmed on-chain
  FAILED      → transaction failed
  KILLED      → trade killed by kill switch

Transitions:
  PENDING     → SIMULATING  (start_simulation)
  SIMULATING  → SIM_PASSED  (simulation_passed)
  SIMULATING  → SIM_FAILED  (simulation_failed)
  SIM_PASSED  → SUBMITTING  (submit_transaction)
  SUBMITTING  → SUBMITTED   (transaction_submitted)
  SUBMITTED   → CONFIRMING  (start_confirmation)
  CONFIRMING  → CONFIRMED   (transaction_confirmed)
  CONFIRMING  → FAILED      (transaction_failed)
  *           → KILLED      (kill_switch activated)

=========================

v2.1.0: Added ExecutionContext with:
- DRY_RUN mode (default ON)
- kill_switch_active flag (default True)
- Global blockers list

NOTE: This is a skeleton for M4. Implementation will follow
after M3 closure.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


# =============================================================================
# v2.1.0 Step 9: Execution Context / Global Kill Switch
# =============================================================================

class ExecutionMode(str, Enum):
    """Execution modes for M4."""
    DRY_RUN = "DRY_RUN"  # Log only, no transactions
    SIMULATE = "SIMULATE"  # eth_call simulation only
    LIVE = "LIVE"  # Actual on-chain execution


@dataclass
class ExecutionContext:
    """
    Global execution context with safety controls.
    
    v2.1.0 CONTRACT:
    - kill_switch_active=True by default (M4 safety)
    - mode=DRY_RUN by default
    - All trades check is_execution_allowed() before submitting
    """
    mode: ExecutionMode = ExecutionMode.DRY_RUN
    kill_switch_active: bool = True  # v2.1.0: DEFAULT ON for safety
    blockers: List[str] = field(default_factory=lambda: ["EXECUTION_DISABLED_M5_0"])
    
    def is_execution_allowed(self) -> bool:
        """Check if real execution is allowed."""
        if self.kill_switch_active:
            return False
        if self.mode != ExecutionMode.LIVE:
            return False
        if self.blockers:
            return False
        return True
    
    def get_execution_blocker(self) -> Optional[str]:
        """Get the primary reason execution is blocked."""
        if self.kill_switch_active:
            return "KILL_SWITCH_ACTIVE"
        if self.mode != ExecutionMode.LIVE:
            return f"MODE_{self.mode.value}"
        if self.blockers:
            return self.blockers[0]
        return None
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize for logging/artifacts."""
        return {
            "mode": self.mode.value,
            "kill_switch_active": self.kill_switch_active,
            "blockers": self.blockers,
            "is_execution_allowed": self.is_execution_allowed(),
            "execution_blocker": self.get_execution_blocker(),
        }


# Global singleton context (v2.1.0 default: DRY_RUN + kill switch ON)
_execution_context = ExecutionContext()


def get_execution_context() -> ExecutionContext:
    """Get the global execution context."""
    return _execution_context


def set_execution_mode(mode: ExecutionMode) -> None:
    """Set the execution mode (for testing/configuration)."""
    _execution_context.mode = mode


def activate_kill_switch(reason: str = "Manual activation") -> None:
    """Activate the global kill switch."""
    _execution_context.kill_switch_active = True


def deactivate_kill_switch() -> None:
    """Deactivate the global kill switch (requires explicit call)."""
    _execution_context.kill_switch_active = False


# =============================================================================
# Trade States
# =============================================================================


class TradeState(str, Enum):
    """Trade execution states."""
    PENDING = "PENDING"
    SIMULATING = "SIMULATING"
    SIM_PASSED = "SIM_PASSED"
    SIM_FAILED = "SIM_FAILED"
    SUBMITTING = "SUBMITTING"
    SUBMITTED = "SUBMITTED"
    CONFIRMING = "CONFIRMING"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"
    KILLED = "KILLED"


# Valid state transitions
VALID_TRANSITIONS: Dict[TradeState, List[TradeState]] = {
    TradeState.PENDING: [TradeState.SIMULATING, TradeState.KILLED],
    TradeState.SIMULATING: [TradeState.SIM_PASSED, TradeState.SIM_FAILED, TradeState.KILLED],
    TradeState.SIM_PASSED: [TradeState.SUBMITTING, TradeState.KILLED],
    TradeState.SIM_FAILED: [],  # Terminal state
    TradeState.SUBMITTING: [TradeState.SUBMITTED, TradeState.FAILED, TradeState.KILLED],
    TradeState.SUBMITTED: [TradeState.CONFIRMING, TradeState.FAILED, TradeState.KILLED],
    TradeState.CONFIRMING: [TradeState.CONFIRMED, TradeState.FAILED, TradeState.KILLED],
    TradeState.CONFIRMED: [],  # Terminal state
    TradeState.FAILED: [],  # Terminal state
    TradeState.KILLED: [],  # Terminal state
}


@dataclass
class StateTransition:
    """Record of a state transition."""
    from_state: TradeState
    to_state: TradeState
    timestamp: str = ""
    reason: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()


class InvalidTransitionError(Exception):
    """Raised when an invalid state transition is attempted."""
    pass


@dataclass
class TradeStateMachine:
    """
    State machine for trade execution.
    
    Tracks current state and transition history.
    """
    trade_id: str
    state: TradeState = TradeState.PENDING
    history: List[StateTransition] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def can_transition_to(self, new_state: TradeState) -> bool:
        """Check if transition to new_state is valid."""
        valid_next = VALID_TRANSITIONS.get(self.state, [])
        return new_state in valid_next

    def transition_to(
        self,
        new_state: TradeState,
        reason: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> StateTransition:
        """
        Transition to a new state.
        
        Raises InvalidTransitionError if transition is not valid.
        """
        if not self.can_transition_to(new_state):
            raise InvalidTransitionError(
                f"Cannot transition from {self.state.value} to {new_state.value}. "
                f"Valid transitions: {[s.value for s in VALID_TRANSITIONS.get(self.state, [])]}"
            )
        
        transition = StateTransition(
            from_state=self.state,
            to_state=new_state,
            reason=reason,
            metadata=metadata or {},
        )
        
        self.history.append(transition)
        self.state = new_state
        
        return transition

    def kill(self, reason: str = "Kill switch activated") -> StateTransition:
        """
        Activate kill switch.
        
        This is always a valid transition (from any non-terminal state).
        """
        if self.state in (TradeState.CONFIRMED, TradeState.FAILED, TradeState.KILLED, TradeState.SIM_FAILED):
            raise InvalidTransitionError(
                f"Cannot kill trade in terminal state {self.state.value}"
            )
        
        return self.transition_to(TradeState.KILLED, reason=reason)

    @property
    def is_terminal(self) -> bool:
        """Check if current state is terminal."""
        return len(VALID_TRANSITIONS.get(self.state, [])) == 0

    @property
    def is_success(self) -> bool:
        """Check if trade completed successfully."""
        return self.state == TradeState.CONFIRMED

    @property
    def is_failed(self) -> bool:
        """Check if trade failed."""
        return self.state in (TradeState.FAILED, TradeState.SIM_FAILED, TradeState.KILLED)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "trade_id": self.trade_id,
            "state": self.state.value,
            "is_terminal": self.is_terminal,
            "is_success": self.is_success,
            "is_failed": self.is_failed,
            "created_at": self.created_at,
            "history": [
                {
                    "from_state": t.from_state.value,
                    "to_state": t.to_state.value,
                    "timestamp": t.timestamp,
                    "reason": t.reason,
                    "metadata": t.metadata,
                }
                for t in self.history
            ],
            "metadata": self.metadata,
        }


# =============================================================================
# v2.1.0-fix Step 9: Execution Dry-Run Stub
# =============================================================================


def simulate_trade_execution(
    trade_sm: TradeStateMachine,
    roundtrip_result: Optional[Dict[str, Any]] = None,
    eth_call_result: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    M4.3 dry-run simulation stub.
    
    This function simulates the execution flow WITHOUT submitting any
    real transactions. Used for M4 validation of the execution path.
    
    v2.1.0 CONTRACT:
    - Always checks ExecutionContext before any action
    - Default: DRY_RUN mode + kill_switch_active=True
    - Records simulation results in trade metadata
    - Never submits real transactions in M4
    
    Args:
        trade_sm: TradeStateMachine for this trade
        roundtrip_result: RoundTripResult.to_dict() with PnL estimate
        eth_call_result: Optional eth_call simulation result
        
    Returns:
        Dict with simulation summary:
        - state: Final trade state
        - would_execute: True if execution would proceed (but blocked)
        - blocker: Why execution is blocked (if any)
        - pnl_estimate: PnL estimate from roundtrip
    """
    ctx = get_execution_context()
    result = {
        "trade_id": trade_sm.trade_id,
        "initial_state": trade_sm.state.value,
        "execution_context": ctx.to_dict(),
        "roundtrip_result": roundtrip_result,
        "eth_call_result": eth_call_result,
    }
    
    # Transition to SIMULATING
    if trade_sm.state == TradeState.PENDING:
        trade_sm.transition_to(
            TradeState.SIMULATING,
            reason="M4.3 dry-run simulation started",
        )
    
    # Check roundtrip profitability
    is_profitable = False
    pnl_estimate = None
    if roundtrip_result:
        is_profitable = roundtrip_result.get("is_profitable", False)
        pnl_estimate = {
            "net_pnl_bps": roundtrip_result.get("net_pnl_bps", 0),
            "net_pnl_wei": roundtrip_result.get("net_pnl_wei", "0"),
            "gas_cost_wei": roundtrip_result.get("gas_cost_wei", "0"),
        }
    
    # Check eth_call success (if provided)
    eth_call_success = True
    if eth_call_result:
        eth_call_success = eth_call_result.get("success", False)
    
    # Determine simulation result
    sim_passed = is_profitable and eth_call_success
    
    if sim_passed:
        trade_sm.transition_to(
            TradeState.SIM_PASSED,
            reason="Simulation passed: profitable and eth_call OK",
            metadata={"pnl_estimate": pnl_estimate},
        )
    else:
        reasons = []
        if not is_profitable:
            reasons.append("NOT_PROFITABLE")
        if not eth_call_success:
            reasons.append("ETH_CALL_FAILED")
        trade_sm.transition_to(
            TradeState.SIM_FAILED,
            reason=f"Simulation failed: {', '.join(reasons)}",
        )
    
    # Check if execution would be allowed
    would_execute = trade_sm.state == TradeState.SIM_PASSED and ctx.is_execution_allowed()
    blocker = ctx.get_execution_blocker()
    
    result.update({
        "final_state": trade_sm.state.value,
        "sim_passed": sim_passed,
        "would_execute": would_execute,
        "blocker": blocker,
        "pnl_estimate": pnl_estimate,
        "trade_history": trade_sm.to_dict()["history"],
    })
    
    return result
