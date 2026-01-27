# PATH: strategy/execution/kill_switch.py
"""
Kill switch stub (STEP 10).

Emergency stop configuration:
- Manual kill switch
- Loss limit trigger
- Error rate trigger
- Time-based pause

All triggers are active in M4 (execution always stopped).
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional


@dataclass
class KillSwitchTrigger:
    """Kill switch trigger event."""
    timestamp: str
    reason: str
    details: Optional[str] = None


class KillSwitch:
    """
    Kill switch for emergency execution stop.
    
    M4: Kill switch is always ACTIVE (execution disabled).
    M5+: Can be configured and released.
    """

    def __init__(
        self,
        enabled: bool = True,  # Default: ON (safe)
        max_loss_usdc: Decimal = Decimal("100.0"),
        max_error_rate: float = 0.5,
        cooldown_minutes: int = 60,
    ):
        self._enabled = enabled
        self._active = True  # M4: Always active
        self._max_loss_usdc = max_loss_usdc
        self._max_error_rate = max_error_rate
        self._cooldown_minutes = cooldown_minutes
        self._triggers: List[KillSwitchTrigger] = []
        self._total_loss = Decimal("0")
        self._error_count = 0
        self._total_attempts = 0

        # M4: Auto-trigger
        if self._enabled:
            self._trigger("EXECUTION_DISABLED_M4", "Execution disabled in M4")

    @property
    def is_active(self) -> bool:
        """Check if kill switch is triggered."""
        return self._active

    @property
    def can_execute(self) -> bool:
        """Check if execution is allowed."""
        return not self._active

    def _trigger(self, reason: str, details: Optional[str] = None) -> None:
        """Trigger the kill switch."""
        self._active = True
        self._triggers.append(KillSwitchTrigger(
            timestamp=datetime.now(timezone.utc).isoformat(),
            reason=reason,
            details=details,
        ))

    def check_loss_limit(self, loss_usdc: Decimal) -> bool:
        """Check if loss exceeds limit."""
        self._total_loss += loss_usdc
        if self._total_loss >= self._max_loss_usdc:
            self._trigger("LOSS_LIMIT", f"Total loss ${self._total_loss} >= ${self._max_loss_usdc}")
            return False
        return True

    def check_error_rate(self, success: bool) -> bool:
        """Check if error rate exceeds limit."""
        self._total_attempts += 1
        if not success:
            self._error_count += 1

        if self._total_attempts >= 10:  # Minimum sample
            rate = self._error_count / self._total_attempts
            if rate >= self._max_error_rate:
                self._trigger("ERROR_RATE", f"Error rate {rate:.1%} >= {self._max_error_rate:.1%}")
                return False
        return True

    def manual_trigger(self, reason: str = "MANUAL") -> None:
        """Manually trigger kill switch."""
        self._trigger(reason, "Manually triggered")

    def release(self, force: bool = False) -> bool:
        """
        Release kill switch.
        
        M4: Cannot release (execution disabled).
        """
        if not force:
            # Check if safe to release
            if self._total_loss >= self._max_loss_usdc:
                return False
            if self._total_attempts >= 10:
                rate = self._error_count / self._total_attempts
                if rate >= self._max_error_rate:
                    return False

        self._active = False
        return True

    def reset_counters(self) -> None:
        """Reset loss and error counters."""
        self._total_loss = Decimal("0")
        self._error_count = 0
        self._total_attempts = 0

    def get_status(self) -> Dict[str, Any]:
        return {
            "enabled": self._enabled,
            "active": self._active,
            "can_execute": self.can_execute,
            "total_loss_usdc": str(self._total_loss),
            "error_count": self._error_count,
            "total_attempts": self._total_attempts,
            "error_rate": self._error_count / max(1, self._total_attempts),
            "max_loss_usdc": str(self._max_loss_usdc),
            "max_error_rate": self._max_error_rate,
            "triggers": [
                {"timestamp": t.timestamp, "reason": t.reason, "details": t.details}
                for t in self._triggers[-5:]  # Last 5 triggers
            ],
        }
