"""M8 Phase 2 — Pre-execution slippage guard (paper-only, no signing).

Predicts price impact for a candidate trade against constant-product
(V2-style) reserves and enforces a conservative safety buffer.  Acts as
a hard pre-execution gate during Phase 2 paper soak and Phase 3 real
trial.

Mirrors ``docs/step_pivot.md`` Phase 2.2 В:

  * Constant-product slippage estimation from poll-time reserves.
  * Conservative buffer ``actual_max_slippage = predicted × buffer``.
  * Per-pool circuit breaker: blacklist if realized > circuit_breaker_x × predicted.

Public API
----------
- :func:`predict_slippage_bps` — constant-product slippage estimate
- :class:`SlippageGuardVerdict` — enum (ALLOW | REJECT)
- :class:`SlippageGuardResult`  — verdict + predicted/allowed bps + reason
- :class:`SlippageGuard`        — guard with ``check(...)`` and ``observe(...)``
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Tuple

__all__ = [
    "predict_slippage_bps",
    "SlippageGuardVerdict",
    "SlippageGuardResult",
    "SlippageGuard",
    "DEFAULT_MAX_SLIPPAGE_BPS",
    "DEFAULT_SAFETY_BUFFER",
    "DEFAULT_CIRCUIT_BREAKER_X",
]

DEFAULT_MAX_SLIPPAGE_BPS: float = 300.0
DEFAULT_SAFETY_BUFFER: float = 2.0
DEFAULT_CIRCUIT_BREAKER_X: float = 3.0


# ---------------------------------------------------------------------------
# Constant-product slippage math
# ---------------------------------------------------------------------------


def predict_slippage_bps(
    *,
    reserve_in: float,
    reserve_out: float,
    amount_in: float,
    fee_bps: float = 30.0,
) -> float:
    """Estimate slippage (bps) of swapping ``amount_in`` into a CP pool.

    Slippage = (mid_price - effective_price) / mid_price.

    Parameters
    ----------
    reserve_in / reserve_out:
        Pre-trade pool reserves in the same units as ``amount_in``.
    amount_in:
        Trade size (input token units).
    fee_bps:
        Pool fee in basis-points (V2 = 30, V3 0.05% pool = 5, etc.).

    Returns
    -------
    Slippage in bps (always >= 0).  Returns +inf if pool is empty.
    """
    if reserve_in <= 0 or reserve_out <= 0:
        return float("inf")
    if amount_in <= 0:
        return 0.0

    fee_mul = max(0.0, 1.0 - fee_bps / 10_000.0)
    amount_in_after_fee = amount_in * fee_mul

    # Constant-product: out = reserve_out * amount_in_after_fee / (reserve_in + amount_in_after_fee)
    amount_out = (reserve_out * amount_in_after_fee) / (reserve_in + amount_in_after_fee)
    effective_price = amount_out / amount_in
    mid_price = reserve_out / reserve_in
    if mid_price <= 0:
        return float("inf")

    slippage = max(0.0, (mid_price - effective_price) / mid_price)
    return slippage * 10_000.0  # to bps


# ---------------------------------------------------------------------------
# Guard types
# ---------------------------------------------------------------------------


class SlippageGuardVerdict(str, Enum):
    ALLOW = "ALLOW"
    REJECT = "REJECT"


@dataclass(frozen=True)
class SlippageGuardResult:
    verdict: SlippageGuardVerdict
    predicted_bps: float
    allowed_bps: float
    reason: Optional[str]
    pool_blacklisted: bool = False
    notes: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict.value,
            "predicted_bps": self.predicted_bps,
            "allowed_bps": self.allowed_bps,
            "reason": self.reason,
            "pool_blacklisted": self.pool_blacklisted,
            "notes": list(self.notes),
        }


# ---------------------------------------------------------------------------
# Guard
# ---------------------------------------------------------------------------


class SlippageGuard:
    """Pre-execution slippage gate with per-pool circuit breaker."""

    def __init__(
        self,
        *,
        max_slippage_bps: float = DEFAULT_MAX_SLIPPAGE_BPS,
        safety_buffer: float = DEFAULT_SAFETY_BUFFER,
        circuit_breaker_x: float = DEFAULT_CIRCUIT_BREAKER_X,
    ) -> None:
        if max_slippage_bps <= 0:
            raise ValueError("max_slippage_bps must be > 0")
        if safety_buffer < 1.0:
            raise ValueError("safety_buffer must be >= 1.0")
        if circuit_breaker_x < 1.0:
            raise ValueError("circuit_breaker_x must be >= 1.0")

        self.max_slippage_bps = float(max_slippage_bps)
        self.safety_buffer = float(safety_buffer)
        self.circuit_breaker_x = float(circuit_breaker_x)
        self._blacklist: set[str] = set()

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def is_blacklisted(self, pool: str) -> bool:
        return pool.lower() in self._blacklist

    def blacklist(self) -> Tuple[str, ...]:
        return tuple(sorted(self._blacklist))

    # ------------------------------------------------------------------
    # Pre-trade check
    # ------------------------------------------------------------------

    def check(
        self,
        *,
        pool: str,
        reserve_in: float,
        reserve_out: float,
        amount_in: float,
        fee_bps: float = 30.0,
    ) -> SlippageGuardResult:
        pool_key = (pool or "").lower()

        if pool_key in self._blacklist:
            return SlippageGuardResult(
                verdict=SlippageGuardVerdict.REJECT,
                predicted_bps=float("inf"),
                allowed_bps=self.max_slippage_bps,
                reason="POOL_BLACKLISTED",
                pool_blacklisted=True,
                notes=("blacklisted_circuit_breaker",),
            )

        predicted = predict_slippage_bps(
            reserve_in=reserve_in,
            reserve_out=reserve_out,
            amount_in=amount_in,
            fee_bps=fee_bps,
        )

        # Apply conservative buffer.
        adjusted = predicted * self.safety_buffer

        if adjusted > self.max_slippage_bps:
            return SlippageGuardResult(
                verdict=SlippageGuardVerdict.REJECT,
                predicted_bps=predicted,
                allowed_bps=self.max_slippage_bps,
                reason="PREDICTED_OVER_LIMIT",
                pool_blacklisted=False,
                notes=(f"adjusted_bps={adjusted:.2f}",),
            )

        return SlippageGuardResult(
            verdict=SlippageGuardVerdict.ALLOW,
            predicted_bps=predicted,
            allowed_bps=self.max_slippage_bps,
            reason=None,
            pool_blacklisted=False,
            notes=(f"adjusted_bps={adjusted:.2f}",),
        )

    # ------------------------------------------------------------------
    # Post-trade observation — feeds circuit breaker.
    # ------------------------------------------------------------------

    def observe(
        self,
        *,
        pool: str,
        predicted_bps: float,
        realized_bps: float,
    ) -> bool:
        """Record realized vs predicted slippage; return True if pool now blacklisted."""
        if predicted_bps <= 0 or realized_bps <= 0:
            return False
        ratio = realized_bps / predicted_bps
        if ratio >= self.circuit_breaker_x:
            self._blacklist.add((pool or "").lower())
            return True
        return False
