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

NOTE: This is a skeleton for M4. Implementation will follow
after M3 closure.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


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
