# PATH: strategy/execution/simulator_gate.py
"""
Simulator gate stub (STEP 10).

Pre-execution validation that checks:
- Price sanity passed
- Confidence threshold met
- Gas estimate available
- Slippage estimate acceptable

All checks return False in M4 (execution disabled).
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional


@dataclass
class GateResult:
    """Result of gate validation."""
    passed: bool
    reason: Optional[str] = None
    blockers: List[str] = None

    def __post_init__(self):
        if self.blockers is None:
            self.blockers = []


class SimulatorGate:
    """
    Pre-execution validation gate stub.
    
    M4: Always returns False (execution disabled).
    M5: Will implement real validation.
    """

    def __init__(
        self,
        enabled: bool = False,
        min_confidence: float = 0.5,
        max_gas_usdc: Decimal = Decimal("10.0"),
        max_slippage_bps: int = 100,
    ):
        self._enabled = enabled
        self._min_confidence = min_confidence
        self._max_gas_usdc = max_gas_usdc
        self._max_slippage_bps = max_slippage_bps

    @property
    def enabled(self) -> bool:
        return self._enabled

    def validate(self, opportunity: Dict[str, Any]) -> GateResult:
        """
        Validate opportunity for execution.
        
        M4: Always fails with EXECUTION_DISABLED_M4.
        """
        blockers = []

        if not self._enabled:
            blockers.append("EXECUTION_DISABLED_M4")
            return GateResult(passed=False, reason="Execution disabled", blockers=blockers)

        # M5: Real validation logic
        confidence = opportunity.get("confidence", 0.0)
        if confidence < self._min_confidence:
            blockers.append("LOW_CONFIDENCE")

        cost_model = opportunity.get("cost_model_available", False)
        if not cost_model:
            blockers.append("NO_COST_MODEL")

        gas_estimate = opportunity.get("gas_estimate_usdc")
        if gas_estimate is None:
            blockers.append("NO_GAS_ESTIMATE")
        elif Decimal(str(gas_estimate)) > self._max_gas_usdc:
            blockers.append("GAS_TOO_HIGH")

        price_sanity = opportunity.get("price_sanity_passed", False)
        if not price_sanity:
            blockers.append("PRICE_SANITY_FAILED")

        passed = len(blockers) == 0
        reason = None if passed else f"Blocked: {', '.join(blockers)}"

        return GateResult(passed=passed, reason=reason, blockers=blockers)

    def to_dict(self) -> dict:
        return {
            "enabled": self._enabled,
            "min_confidence": self._min_confidence,
            "max_gas_usdc": str(self._max_gas_usdc),
            "max_slippage_bps": self._max_slippage_bps,
        }
