"""M8 Phase 2 — Sniper exit strategy (paper-only).

3-layer exit strategy matching ``docs/step_pivot.md`` Phase 2.2 Б:

    1. Time-based     — hard ``max_hold_blocks`` ceiling.
    2. TWAP/profit-take — partial exit on realized profit ≥ target.
    3. Emergency       — full dump on any revert / honeypot trigger.

Pure, side-effect-free.  No signing, no broadcast.  Decisions are
returned as :class:`ExitDecision` objects which the runtime later
translates into paper-execution telemetry.

Public API
----------
- :class:`ExitTrigger`     — enum (NONE | TIME | PROFIT_TAKE | EMERGENCY)
- :class:`ExitAction`      — enum (HOLD | PARTIAL_SELL | FULL_SELL)
- :class:`ExitDecision`    — verdict + sell_fraction + reason + notes
- :class:`ExitStateInput`  — current state of an open paper-position
- :class:`SniperExitStrategy` — strategy with ``evaluate(state)``
- ``make_default_strategy()`` — conservative defaults
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional, Tuple

__all__ = [
    "ExitTrigger",
    "ExitAction",
    "ExitDecision",
    "ExitStateInput",
    "SniperExitStrategy",
    "make_default_strategy",
    "DEFAULT_MAX_HOLD_BLOCKS",
    "DEFAULT_PROFIT_TAKE_BPS",
    "DEFAULT_PROFIT_TAKE_FRACTION",
]

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

# Base block-time ≈ 2 s.  200 blocks ≈ 400 s — primary safety net.
DEFAULT_MAX_HOLD_BLOCKS: int = 200
DEFAULT_PROFIT_TAKE_BPS: float = 80.0
DEFAULT_PROFIT_TAKE_FRACTION: float = 0.5


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class ExitTrigger(str, Enum):
    NONE = "NONE"
    TIME = "TIME"
    PROFIT_TAKE = "PROFIT_TAKE"
    EMERGENCY = "EMERGENCY"


class ExitAction(str, Enum):
    HOLD = "HOLD"
    PARTIAL_SELL = "PARTIAL_SELL"
    FULL_SELL = "FULL_SELL"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExitStateInput:
    """Snapshot of an open paper-position used to evaluate exit."""

    entry_block: int
    current_block: int
    realized_pnl_bps: float
    position_fraction_remaining: float = 1.0  # 1.0 = nothing sold yet
    revert_observed: bool = False
    honeypot_trigger: bool = False


@dataclass(frozen=True)
class ExitDecision:
    trigger: ExitTrigger
    action: ExitAction
    sell_fraction: float
    reason: str
    notes: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trigger": self.trigger.value,
            "action": self.action.value,
            "sell_fraction": self.sell_fraction,
            "reason": self.reason,
            "notes": list(self.notes),
        }


# ---------------------------------------------------------------------------
# Strategy
# ---------------------------------------------------------------------------


class SniperExitStrategy:
    """3-layer exit strategy (stateless)."""

    def __init__(
        self,
        *,
        max_hold_blocks: int = DEFAULT_MAX_HOLD_BLOCKS,
        profit_take_bps: float = DEFAULT_PROFIT_TAKE_BPS,
        profit_take_fraction: float = DEFAULT_PROFIT_TAKE_FRACTION,
    ) -> None:
        if max_hold_blocks <= 0:
            raise ValueError("max_hold_blocks must be > 0")
        if profit_take_bps < 0:
            raise ValueError("profit_take_bps must be >= 0")
        if not (0.0 < profit_take_fraction <= 1.0):
            raise ValueError("profit_take_fraction must be in (0, 1]")

        self.max_hold_blocks = int(max_hold_blocks)
        self.profit_take_bps = float(profit_take_bps)
        self.profit_take_fraction = float(profit_take_fraction)

    def evaluate(self, state: ExitStateInput) -> ExitDecision:
        notes: list = []

        if state.current_block < state.entry_block:
            raise ValueError("current_block < entry_block")

        # Layer 3 — Emergency exit (highest priority).
        if state.honeypot_trigger or state.revert_observed:
            reason = "HONEYPOT_TRIGGER" if state.honeypot_trigger else "REVERT_OBSERVED"
            notes.append(f"emergency:{reason.lower()}")
            return ExitDecision(
                trigger=ExitTrigger.EMERGENCY,
                action=ExitAction.FULL_SELL,
                sell_fraction=1.0,
                reason=reason,
                notes=tuple(notes),
            )

        # Layer 1 — Time-based hard ceiling.
        held = state.current_block - state.entry_block
        if held >= self.max_hold_blocks:
            notes.append(f"time:held={held}>=max={self.max_hold_blocks}")
            return ExitDecision(
                trigger=ExitTrigger.TIME,
                action=ExitAction.FULL_SELL,
                sell_fraction=1.0,
                reason="MAX_HOLD_REACHED",
                notes=tuple(notes),
            )

        # Layer 2 — Profit-take partial.
        if (
            state.realized_pnl_bps >= self.profit_take_bps
            and state.position_fraction_remaining > self.profit_take_fraction + 1e-9
        ):
            notes.append(
                f"profit_take:bps={state.realized_pnl_bps:.1f}>={self.profit_take_bps}"
            )
            return ExitDecision(
                trigger=ExitTrigger.PROFIT_TAKE,
                action=ExitAction.PARTIAL_SELL,
                sell_fraction=self.profit_take_fraction,
                reason="PROFIT_TARGET_HIT",
                notes=tuple(notes),
            )

        notes.append(f"hold:held={held}/{self.max_hold_blocks},pnl_bps={state.realized_pnl_bps:.1f}")
        return ExitDecision(
            trigger=ExitTrigger.NONE,
            action=ExitAction.HOLD,
            sell_fraction=0.0,
            reason="NO_EXIT_CONDITION",
            notes=tuple(notes),
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def make_default_strategy() -> SniperExitStrategy:
    return SniperExitStrategy()
