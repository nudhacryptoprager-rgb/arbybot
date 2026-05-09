"""E1.69 Wave reviewer fix step 6 — CLMM in-range liquidity helpers.

Production-size routing must respect the fact that Uniswap V3 / Algebra /
Aerodrome Slipstream pools concentrate liquidity in a tick range.  A
pool with $10M total TVL but only 3% of liquidity in-range at the
current tick behaves like a $300k pool for the next swap.

Pure functions (no I/O) so they are unit-testable and safe to call in
tight loops.  The orderflow scorer is expected to weight TVL by
``in_range_fraction(...)`` before sizing.
"""

from __future__ import annotations

import math
from typing import Optional


def tick_to_sqrt_price_ratio(tick: int) -> float:
    """sqrtPrice ratio at the given tick.

    sqrtPrice(tick) = 1.0001 ** (tick / 2)
    """
    return math.pow(1.0001, tick / 2.0)


def in_range_fraction(
    sqrt_price_x96: int,
    liquidity: int,
    tick_lower: Optional[int] = None,
    tick_upper: Optional[int] = None,
    tick_spacing: int = 60,
) -> float:
    """Estimate the fraction of TVL active at the current swap.

    Parameters
    ----------
    sqrt_price_x96 : int
        Pool's current ``sqrtPriceX96`` (slot0).
    liquidity : int
        Pool's current active liquidity (``liquidity()`` view).
    tick_lower, tick_upper : Optional[int]
        Active tick range.  When omitted, uses the standard tick spacing
        window around the current tick (``tick_spacing`` wide).
    tick_spacing : int
        Pool tick spacing (60 for 0.3% pools, 10 for 0.05%, 1 for 0.01%).

    Returns
    -------
    float
        Fraction in ``[0.0, 1.0]``.  ``1.0`` means all locked liquidity
        contributes to the next tick of trading.  ``0.0`` means we
        cannot estimate; callers should treat that as production-blocked.
    """
    if sqrt_price_x96 <= 0 or liquidity <= 0:
        return 0.0
    # Derive current tick: tick = log_{1.0001}(price) where
    # price = (sqrtPriceX96 / 2**96) ** 2.
    try:
        sp = float(sqrt_price_x96) / (2 ** 96)
        if sp <= 0:
            return 0.0
        price = sp * sp
        cur_tick = int(math.log(price) / math.log(1.0001))
    except (ValueError, ZeroDivisionError):
        return 0.0
    if tick_lower is None:
        tick_lower = (cur_tick // tick_spacing) * tick_spacing
    if tick_upper is None:
        tick_upper = tick_lower + tick_spacing
    if tick_upper <= tick_lower:
        return 0.0
    width = tick_upper - tick_lower
    # Heuristic: the active tick contributes a 1-tick slice of the
    # active range; production callers should prefer richer position
    # readers when available.
    if width <= 0:
        return 0.0
    return max(0.0, min(1.0, 1.0 / float(width)))


def discount_tvl_by_in_range(
    tvl_usd: float,
    sqrt_price_x96: int,
    liquidity: int,
    tick_lower: Optional[int] = None,
    tick_upper: Optional[int] = None,
    tick_spacing: int = 60,
    floor_fraction: float = 0.01,
) -> float:
    """Return the production-size effective TVL for routing.

    Floors the discount at ``floor_fraction`` so completely
    out-of-range pools are still ranked but heavily penalized.
    """
    frac = in_range_fraction(
        sqrt_price_x96=sqrt_price_x96,
        liquidity=liquidity,
        tick_lower=tick_lower,
        tick_upper=tick_upper,
        tick_spacing=tick_spacing,
    )
    if frac < floor_fraction:
        frac = floor_fraction
    if tvl_usd <= 0:
        return 0.0
    return tvl_usd * frac


__all__ = [
    "tick_to_sqrt_price_ratio",
    "in_range_fraction",
    "discount_tvl_by_in_range",
]
