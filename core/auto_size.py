"""Auto-size helper utilities for Milestone 5.

Provides minimal autosize rules: reduce on high impact/slippage and
restore after X good cycles. Values and thresholds are intentionally
simple and configurable by caller.
"""
from typing import Tuple


def clamp_size(size: float, min_size: float, max_size: float) -> float:
    return max(min_size, min(max_size, size))


def reduce_on_slippage(size: float, slippage_bps: float, ticks_crossed: int, s1: float, t1: int, min_size: float) -> float:
    """Reduce size by half when slippage or ticks thresholds exceeded."""
    if slippage_bps > s1 or ticks_crossed > t1:
        new_size = size * 0.5
    else:
        new_size = size
    return max(min_size, new_size)


def restore_size(size: float, consecutive_good: int, required: int, factor: float, max_size: float) -> float:
    """Restore size multiplicatively when `consecutive_good >= required`."""
    if consecutive_good >= required:
        new_size = size * factor
    else:
        new_size = size
    return min(max_size, new_size)
