"""Local V3 price estimation without eth_call (Step 9).

Computes approximate output amounts and cycle gross bps directly from on-chain
slot0 (sqrtPriceX96) and liquidity — no Quoter contract call needed.

This is used as a cheap pre-filter: cycles where estimated gross_bps is below
``min_spread_bps`` are skipped (or demoted to cold queue) before the expensive
Quoter eth_call is made.

Math:
    For a Uniswap V3 pool:
        price_raw = (sqrtPriceX96 / 2^96)^2  → token1_raw / token0_raw

    token0 is the lower address (Uniswap convention).

    For a closed cycle A→B→C→A the decimal adjustments cancel,
    so gross_ratio = product of per-hop price ratios (after fee).

Accuracy: ~±0.5% vs Quoter for small amounts. Sufficient for pre-filtering.
Not valid for large amounts relative to pool liquidity.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Dict, Optional

if TYPE_CHECKING:
    from m9.graph_arb.models import GraphCycle, GraphEdge
    from m9.graph_arb.pool_state_cache import PoolState

log = logging.getLogger(__name__)

# Pre-filter threshold: cycles where estimated gross_bps < this are skipped.
# Default -500 bps (very conservative — only filter clearly hopeless cycles).
_DEFAULT_SKIP_THRESHOLD_BPS: float = -500.0

# Force-quote sentinel: when the operator passes a min_spread_bps at or below this
# value (e.g. --prequote-min-bps -9999), the intent is "quote everything, do not
# pre-filter". In that mode should_skip_cycle never skips — not even known-empty
# pools — so the expensive quoter runs and surfaces the real reject reason
# (e.g. QUOTE_REVERT) instead of silently dropping the cycle at prequote time.
FORCE_QUOTE_THRESHOLD_BPS: float = -9000.0

# Adapters whose price follows the standard V3 sqrtPriceX96 convention.
_V3_COMPATIBLE_ADAPTERS = frozenset([
    "uniswap_v3",
    "pancakeswap_v3",
    "sushiswap_v3",
    "aerodrome_slipstream",
    "camelot_v3",
    "quickswap_v3",
])

_Q96 = 2 ** 96


def _price_ratio_for_edge(
    edge: "GraphEdge",
    sqrt_price_x96: int,
) -> Optional[float]:
    """Compute approximate output/input token ratio for one hop.

    Returns None if the computation is not possible or not applicable.

    The ratio is in raw token units (decimals not normalised) — that is fine
    because for a closed cycle the unit cancellations leave a dimensionless
    gross ratio.
    """
    if edge.adapter_type not in _V3_COMPATIBLE_ADAPTERS:
        # Non-V3 adapters: can't estimate from sqrtPriceX96
        return None

    if sqrt_price_x96 <= 0:
        return None

    # price_raw = token1_raw / token0_raw
    price_raw = (sqrt_price_x96 / _Q96) ** 2

    # Determine direction: is token_in == token0 (lower address)?
    zero_for_one = edge.token_in_addr.lower() < edge.token_out_addr.lower()

    if zero_for_one:
        # Buying token1 with token0: ratio = price_raw
        ratio = price_raw
    else:
        # Buying token0 with token1: ratio = 1 / price_raw
        if price_raw == 0:
            return None
        ratio = 1.0 / price_raw

    # Apply LP fee
    fee_fraction = edge.fee_bps / 10_000.0
    return ratio * (1.0 - fee_fraction)


def estimate_cycle_gross_bps(
    cycle: "GraphCycle",
    pool_states: "Dict[str, Optional[PoolState]]",
) -> Optional[float]:
    """Estimate gross bps for *cycle* using cached pool states.

    Returns:
        Float gross_bps if all pool states are available and V3-compatible.
        None if estimation is not possible (missing state, non-V3 adapter).
    """
    ratio = 1.0
    for edge in cycle.edges:
        key = edge.pool_address.lower()
        state = pool_states.get(key)
        if state is None:
            return None

        edge_ratio = _price_ratio_for_edge(edge, state.sqrt_price_x96)
        if edge_ratio is None:
            return None

        ratio *= edge_ratio

    return (ratio - 1.0) * 10_000.0


def cycle_has_empty_pool(
    cycle: "GraphCycle",
    pool_states: "Dict[str, Optional[PoolState]]",
) -> bool:
    """Return True if any pool in the cycle has zero liquidity or missing state."""
    for edge in cycle.edges:
        state = pool_states.get(edge.pool_address.lower())
        if state is None or state.is_empty():
            return True
    return False


def should_skip_cycle(
    cycle: "GraphCycle",
    pool_states: "Dict[str, Optional[PoolState]]",
    min_spread_bps: float = _DEFAULT_SKIP_THRESHOLD_BPS,
) -> bool:
    """True if the cycle can be skipped based on cheap prequote math.

    A cycle is skipped when:
    1. A pool state is KNOWN and has zero liquidity (Quoter will revert).
    2. All pool states are available AND estimated gross_bps < min_spread_bps.

    A cycle is NOT skipped when pool states are missing — we fall back to
    the expensive Quoter to avoid false negatives.
    """
    # Force-quote mode: an extremely permissive threshold means the operator
    # explicitly wants every cycle quoted (no economic OR empty-pool pre-filter).
    # Returning False here keeps prequote_skip_ratio < 1.0 and lets the quoter
    # produce a real reject_reason for otherwise-dropped cycles.
    if min_spread_bps <= FORCE_QUOTE_THRESHOLD_BPS:
        return False

    # Case 1: any pool state is present and shows zero liquidity — definitely skip
    for edge in cycle.edges:
        state = pool_states.get(edge.pool_address.lower())
        if state is not None and state.is_empty():
            return True  # known-empty pool

    # Case 2: estimate spread from available states (only if ALL are available)
    gross_bps = estimate_cycle_gross_bps(cycle, pool_states)
    if gross_bps is None:
        return False  # Can't estimate → don't skip

    return gross_bps < min_spread_bps


def prequote_priority_bonus(
    cycle: "GraphCycle",
    pool_states: "Dict[str, Optional[PoolState]]",
) -> float:
    """Return a priority bonus in bps for use by CyclePriorityScheduler.

    Positive = cycle looks promising.  Negative = cycle looks bad.
    Zero = no information available.
    """
    gross_bps = estimate_cycle_gross_bps(cycle, pool_states)
    if gross_bps is None:
        return 0.0
    # Clamp to [-50, +50] to avoid dominating the base score
    return max(-50.0, min(50.0, gross_bps))
