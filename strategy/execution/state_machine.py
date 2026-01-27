# PATH: strategy/execution/state_machine.py
"""
Execution state machine stub (STEP 10).

States:
- IDLE: Not running
- SCANNING: Discovering opportunities
- VALIDATING: Pre-execution checks
- EXECUTING: Trade execution (DISABLED in M4)
- COOLING_DOWN: Post-trade cooldown

All transitions are disabled in M4.
"""

from enum import Enum, auto
from typing import Optional


class ExecutionState(Enum):
    """Execution state machine states."""
    IDLE = auto()
    SCANNING = auto()
    VALIDATING = auto()
    EXECUTING = auto()
    COOLING_DOWN = auto()
    ERROR = auto()


class ExecutionStateMachine:
    """
    Execution state machine stub.
    
    M4: All transitions except IDLE -> SCANNING are disabled.
    M5: Will enable VALIDATING state.
    M6: Will enable EXECUTING state.
    """

    def __init__(self, enabled: bool = False):
        self._state = ExecutionState.IDLE
        self._enabled = enabled
        self._error_reason: Optional[str] = None

    @property
    def state(self) -> ExecutionState:
        return self._state

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def error_reason(self) -> Optional[str]:
        return self._error_reason

    def can_transition_to(self, target: ExecutionState) -> bool:
        """Check if transition is allowed."""
        if not self._enabled:
            # M4: Only allow IDLE -> SCANNING
            if self._state == ExecutionState.IDLE and target == ExecutionState.SCANNING:
                return True
            if self._state == ExecutionState.SCANNING and target == ExecutionState.IDLE:
                return True
            return False

        # M5+: Full state machine
        valid_transitions = {
            ExecutionState.IDLE: [ExecutionState.SCANNING],
            ExecutionState.SCANNING: [ExecutionState.VALIDATING, ExecutionState.IDLE],
            ExecutionState.VALIDATING: [ExecutionState.EXECUTING, ExecutionState.SCANNING, ExecutionState.IDLE],
            ExecutionState.EXECUTING: [ExecutionState.COOLING_DOWN, ExecutionState.ERROR],
            ExecutionState.COOLING_DOWN: [ExecutionState.SCANNING, ExecutionState.IDLE],
            ExecutionState.ERROR: [ExecutionState.IDLE],
        }

        return target in valid_transitions.get(self._state, [])

    def transition_to(self, target: ExecutionState) -> bool:
        """Attempt state transition."""
        if not self.can_transition_to(target):
            self._error_reason = f"Invalid transition: {self._state} -> {target}"
            return False

        self._state = target
        self._error_reason = None
        return True

    def reset(self) -> None:
        """Reset to IDLE state."""
        self._state = ExecutionState.IDLE
        self._error_reason = None

    def to_dict(self) -> dict:
        return {
            "state": self._state.name,
            "enabled": self._enabled,
            "error_reason": self._error_reason,
        }
