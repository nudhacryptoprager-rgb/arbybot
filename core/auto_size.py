"""Auto-size helper utilities for Milestone 5.

Provides minimal autosize rules: reduce on high impact/slippage and
restore after X good cycles. Values and thresholds are intentionally
simple and configurable by caller.
"""
from typing import Tuple, Dict, Any


def clamp_size(size: float, min_size: float, max_size: float) -> float:
    return max(min_size, min(max_size, size))


def autosize_step(
    current_size: float,
    last_slippage_bps: float,
    last_ticks_crossed: int,
    min_size: float,
    max_size: float,
    s1: float = 50.0,
    t1: int = 2,
    restore_required: int = 3,
    restore_factor: float = 1.2,
    state: Dict[str, Any] = None,
) -> Tuple[float, Dict[str, Any], str]:
    """Compute autosize step with cooldown state.

    state is a dict that may contain:
      - 'cooldown': int (cycles remaining before restore)
      - 'consecutive_good': int

    Returns (new_size, new_state, reason)
    """
    if state is None:
        state = {"cooldown": 0, "consecutive_good": 0}

    reason = "no_change"
    new_size = float(current_size)

    # reduce on slippage/ticks
    if (last_slippage_bps or 0) > s1 or (last_ticks_crossed or 0) > t1:
        # apply reduction and set cooldown
        new_size = max(min_size, current_size * 0.5)
        state["cooldown"] = 2  # do not restore for 2 cycles
        state["consecutive_good"] = 0
        reason = "reduced_on_slippage_or_ticks"
        return clamp_size(new_size, min_size, max_size), state, reason

    # if in cooldown, decrement and do not restore
    if state.get("cooldown", 0) > 0:
        state["cooldown"] = max(0, state["cooldown"] - 1)
        reason = "cooldown"
        return clamp_size(new_size, min_size, max_size), state, reason

    # good cycle -> increment consecutive_good
    state["consecutive_good"] = state.get("consecutive_good", 0) + 1
    if state["consecutive_good"] >= restore_required:
        # restore multiplicatively
        new_size = min(max_size, current_size * restore_factor)
        state["consecutive_good"] = 0
        reason = "restored_after_good_cycles"

    return clamp_size(new_size, min_size, max_size), state, reason
