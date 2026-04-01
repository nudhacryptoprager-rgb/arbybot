"""
Uniswap V3 local swap math for single-tick pricing.

Computes exact swap output using on-chain pool state (sqrtPriceX96, tick,
liquidity) without requiring an RPC quoter call.  This is the fast
(< 1 ms) local-state-first pricing path for M7.A.5.20.

Limitations:
- Single-tick only: assumes the swap stays within the current tick range.
  If the swap would cross a tick boundary (amountIn too large relative to
  available liquidity at current tick), returns None.
- Does not simulate tick-bitmap traversal or cross-tick liquidity changes.
- V3 pools only (not V2 constant-product pools).

V2 constant-product math is also provided for pools with getReserves data.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("m7.orderflow.v3_math")

# Uniswap V3 fixed-point resolution
Q96 = 1 << 96
# Fee denominator (1_000_000 = 100%)
FEE_DENOMINATOR = 1_000_000
# Min/max sqrtPriceX96 from TickMath (prevents division by zero)
MIN_SQRT_RATIO = 4295128739
MAX_SQRT_RATIO = 1461446703485210103287273052203988822378723970342


def compute_v3_swap_amount_out(
    sqrt_price_x96: int,
    liquidity: int,
    amount_in: int,
    fee_pips: int,
    zero_for_one: bool,
) -> Optional[int]:
    """Compute V3 swap output for a single-tick swap.

    Args:
        sqrt_price_x96: Current pool sqrtPriceX96 (Q64.96 fixed-point).
        liquidity: Current tick liquidity (uint128).
        amount_in: Raw input amount in wei.
        fee_pips: Pool fee in pips (e.g. 500 = 0.05%, 3000 = 0.30%).
        zero_for_one: True if swapping token0→token1 (price decreases).

    Returns:
        Positive amount_out in wei, or None if swap cannot be computed
        (zero liquidity, overflow, or input exceeds single-tick capacity).
    """
    if liquidity <= 0 or sqrt_price_x96 <= 0 or amount_in <= 0:
        return None
    if sqrt_price_x96 < MIN_SQRT_RATIO or sqrt_price_x96 > MAX_SQRT_RATIO:
        return None
    if fee_pips < 0 or fee_pips >= FEE_DENOMINATOR:
        return None

    # Apply fee
    amount_in_after_fee = amount_in * (FEE_DENOMINATOR - fee_pips) // FEE_DENOMINATOR
    if amount_in_after_fee <= 0:
        return None

    try:
        if zero_for_one:
            return _swap_zero_for_one(sqrt_price_x96, liquidity, amount_in_after_fee)
        else:
            return _swap_one_for_zero(sqrt_price_x96, liquidity, amount_in_after_fee)
    except (OverflowError, ZeroDivisionError, ValueError):
        return None


def _swap_zero_for_one(
    sqrt_price_x96: int,
    liquidity: int,
    amount_in_after_fee: int,
) -> Optional[int]:
    """Swap token0 → token1 (price decreases).

    sqrtPriceNext = L * sqrtP / (L + amountIn * sqrtP / Q96)
    amount1Out = L * (sqrtP - sqrtPNext) / Q96
    """
    # numerator1 = L * Q96  (matches Solidity: uint256(liquidity) << 96)
    numerator1 = liquidity * Q96

    # denominator = L + amountIn * sqrtP / Q96  (round up to round down result)
    product = amount_in_after_fee * sqrt_price_x96
    denominator = numerator1 + product
    if denominator <= 0:
        return None

    # sqrtPriceNextX96 = ceil(numerator1 * sqrtP / denominator)
    # Round up sqrtPriceNext → smaller amount_out (conservative)
    sqrt_price_next = (numerator1 * sqrt_price_x96 + denominator - 1) // denominator

    if sqrt_price_next <= MIN_SQRT_RATIO:
        # Would cross below minimum — swap too large for single tick
        return None
    if sqrt_price_next >= sqrt_price_x96:
        # Price should decrease for zero_for_one
        return None

    # amount1_out = L * (sqrtP - sqrtPNext) / Q96  (round down)
    amount_out = liquidity * (sqrt_price_x96 - sqrt_price_next) // Q96

    return amount_out if amount_out > 0 else None


def _swap_one_for_zero(
    sqrt_price_x96: int,
    liquidity: int,
    amount_in_after_fee: int,
) -> Optional[int]:
    """Swap token1 → token0 (price increases).

    sqrtPriceNext = sqrtP + amountIn * Q96 / L
    amount0Out = L * Q96 * (sqrtPNext - sqrtP) / (sqrtP * sqrtPNext)
    """
    # sqrtPriceNextX96 = sqrtP + amountIn * Q96 / L  (round down quotient)
    quotient = (amount_in_after_fee * Q96) // liquidity
    sqrt_price_next = sqrt_price_x96 + quotient

    if sqrt_price_next >= MAX_SQRT_RATIO:
        # Would cross above maximum — swap too large for single tick
        return None
    if sqrt_price_next <= sqrt_price_x96:
        # Price should increase for one_for_zero
        return None

    # amount0_out = L * Q96 * (sqrtPNext - sqrtP) / (sqrtP * sqrtPNext)
    # Split to avoid intermediate overflow in Solidity, but fine in Python.
    numerator1 = liquidity * Q96
    numerator2 = sqrt_price_next - sqrt_price_x96
    denominator = sqrt_price_x96 * sqrt_price_next
    if denominator <= 0:
        return None

    # Round down for output
    amount_out = (numerator1 * numerator2) // denominator

    return amount_out if amount_out > 0 else None


def compute_algebra_swap_amount_out(
    sqrt_price_x96: int,
    liquidity: int,
    amount_in: int,
    fee_zto: int,
    fee_otz: int,
    zero_for_one: bool,
) -> Optional[int]:
    """Compute Algebra/Camelot V3 swap output using globalState.

    Algebra pools (Camelot V3, Chronos, Ramses) use ``globalState``
    instead of ``slot0`` and have **dynamic** per-direction fees stored
    in the pool state rather than immutable fee tiers.

    The math is identical to Uniswap V3 single-tick pricing — only the
    fee source differs.  ``fee_zto`` is the fee for zero→one; ``fee_otz``
    for one→zero (both in hundredths of a bip, i.e. same 1e6 scale as V3
    fee_pips).

    Args:
        sqrt_price_x96: Q64.96 price from globalState.
        liquidity: Active liquidity.
        amount_in: Raw input amount in wei.
        fee_zto: Fee (hundredths of a bip) for token0→token1.
        fee_otz: Fee (hundredths of a bip) for token1→token0.
        zero_for_one: Swap direction.

    Returns:
        Positive output amount, or None if swap can't be computed.
    """
    fee_pips = fee_zto if zero_for_one else fee_otz
    return compute_v3_swap_amount_out(
        sqrt_price_x96=sqrt_price_x96,
        liquidity=liquidity,
        amount_in=amount_in,
        fee_pips=fee_pips,
        zero_for_one=zero_for_one,
    )


def compute_v2_swap_amount_out(
    reserve_in: int,
    reserve_out: int,
    amount_in: int,
    fee_numerator: int = 997,
    fee_denominator: int = 1000,
) -> Optional[int]:
    """Compute V2 constant-product swap output.

    Uses the standard x*y=k formula with fee:
        amountOut = (amountIn * feeNum * reserveOut) /
                    (reserveIn * feeDenom + amountIn * feeNum)

    Args:
        reserve_in: Reserve of input token.
        reserve_out: Reserve of output token.
        amount_in: Raw input amount in wei.
        fee_numerator: Fee numerator (default 997 = 0.3% fee).
        fee_denominator: Fee denominator (default 1000).

    Returns:
        Positive amount_out in wei, or None if swap cannot be computed.
    """
    if reserve_in <= 0 or reserve_out <= 0 or amount_in <= 0:
        return None
    if fee_numerator <= 0 or fee_denominator <= 0:
        return None

    amount_in_with_fee = amount_in * fee_numerator
    numerator = amount_in_with_fee * reserve_out
    denominator = reserve_in * fee_denominator + amount_in_with_fee
    if denominator <= 0:
        return None

    amount_out = numerator // denominator
    return amount_out if amount_out > 0 else None


def attempt_local_pricing(
    candidate_pools: list,
    local_sim_states: dict,
    token_in_addr: str,
    token_out_addr: str,
    backrun_size_wei: int,
    registry_entries: Optional[list] = None,
) -> Optional[dict]:
    """Attempt local-state pricing across candidate pools.

    For each pool with full state (sqrtPriceX96 + liquidity > 0), compute
    local buy quote.  Then for best buy, compute sell quote.  Returns the
    best roundtrip result or None if no pool could be priced locally.

    M7.A.5.21: Supports V3, Algebra, and V2 adapter types when
    ``registry_entries`` are provided (from PoolRegistry).  V2 entries
    store reserve0/reserve1 in sqrt_price_x96/tick fields.

    Returns dict with:
        buy_amount: int
        sell_amount: int
        buy_venue: str  (pool address)
        sell_venue: str  (pool address)
        buy_fee: int
        sell_fee: int
        pricing_path: "v3_local" | "v2_local" | "algebra_local"
        pools_attempted: int
        pools_succeeded: int
    """
    if not candidate_pools or not local_sim_states:
        return None

    # Build adapter_type lookup from registry entries if available
    _adapter_map: dict = {}  # addr_lower -> adapter_type
    if registry_entries:
        for re in registry_entries:
            _adapter_map[re.address.lower()] = re.adapter_type

    # Determine token ordering for zero_for_one
    zero_for_one = token_in_addr.lower() < token_out_addr.lower()

    best_buy_amount = 0
    best_buy_pool = None
    best_buy_fee = 0
    best_buy_path = None
    pools_attempted = 0
    pools_succeeded = 0

    for cp in candidate_pools:
        addr = cp.get("address")
        if not addr:
            continue
        fee = cp.get("fee", 3000)
        state = local_sim_states.get(addr)
        if state is None:
            continue

        adapter = _adapter_map.get(addr.lower() if addr else "", "uniswap_v3")
        sqrt_price = state.get("sqrt_price_x96", 0)
        liq = state.get("liquidity", 0)

        if adapter == "uniswap_v2":
            # V2: sqrt_price_x96 = reserve0, tick = reserve1
            reserve0 = sqrt_price
            reserve1 = state.get("tick", 0)
            if reserve0 > 0 and reserve1 > 0:
                pools_attempted += 1
                # Determine which reserve is "in" vs "out"
                r_in = reserve0 if zero_for_one else reserve1
                r_out = reserve1 if zero_for_one else reserve0
                out = compute_v2_swap_amount_out(r_in, r_out, backrun_size_wei)
                if out is not None and out > best_buy_amount:
                    best_buy_amount = out
                    best_buy_pool = addr
                    best_buy_fee = fee
                    best_buy_path = "v2_local"
                    pools_succeeded += 1
        elif adapter == "algebra":
            # Algebra: same math as V3 but fee may be dynamic
            if sqrt_price > 0 and liq > 0:
                pools_attempted += 1
                # Algebra stores dynamic fee; use cp["fee"] if available, else 3000
                algebra_fee = fee if fee > 0 else 3000
                out = compute_v3_swap_amount_out(
                    sqrt_price_x96=sqrt_price,
                    liquidity=liq,
                    amount_in=backrun_size_wei,
                    fee_pips=algebra_fee,
                    zero_for_one=zero_for_one,
                )
                if out is not None and out > best_buy_amount:
                    best_buy_amount = out
                    best_buy_pool = addr
                    best_buy_fee = algebra_fee
                    best_buy_path = "algebra_local"
                    pools_succeeded += 1
        else:
            # V3 (default)
            if sqrt_price > 0 and liq > 0:
                pools_attempted += 1
                out = compute_v3_swap_amount_out(
                    sqrt_price_x96=sqrt_price,
                    liquidity=liq,
                    amount_in=backrun_size_wei,
                    fee_pips=fee,
                    zero_for_one=zero_for_one,
                )
                if out is not None and out > best_buy_amount:
                    best_buy_amount = out
                    best_buy_pool = addr
                    best_buy_fee = fee
                    best_buy_path = "v3_local"
                    pools_succeeded += 1

    if best_buy_amount <= 0 or best_buy_pool is None:
        return None

    # Sell pass: swap best_buy_amount back (reverse direction)
    best_sell_amount = 0
    best_sell_pool = None
    best_sell_fee = 0

    for cp in candidate_pools:
        addr = cp.get("address")
        if not addr:
            continue
        fee = cp.get("fee", 3000)
        state = local_sim_states.get(addr)
        if state is None:
            continue

        adapter = _adapter_map.get(addr.lower() if addr else "", "uniswap_v3")
        sqrt_price = state.get("sqrt_price_x96", 0)
        liq = state.get("liquidity", 0)

        if adapter == "uniswap_v2":
            reserve0 = sqrt_price
            reserve1 = state.get("tick", 0)
            if reserve0 > 0 and reserve1 > 0:
                # Reverse direction for sell
                r_in = reserve1 if zero_for_one else reserve0
                r_out = reserve0 if zero_for_one else reserve1
                out = compute_v2_swap_amount_out(r_in, r_out, best_buy_amount)
                if out is not None and out > best_sell_amount:
                    best_sell_amount = out
                    best_sell_pool = addr
                    best_sell_fee = fee
        elif adapter == "algebra":
            if sqrt_price > 0 and liq > 0:
                algebra_fee = fee if fee > 0 else 3000
                out = compute_v3_swap_amount_out(
                    sqrt_price_x96=sqrt_price,
                    liquidity=liq,
                    amount_in=best_buy_amount,
                    fee_pips=algebra_fee,
                    zero_for_one=not zero_for_one,
                )
                if out is not None and out > best_sell_amount:
                    best_sell_amount = out
                    best_sell_pool = addr
                    best_sell_fee = algebra_fee
        else:
            if sqrt_price > 0 and liq > 0:
                out = compute_v3_swap_amount_out(
                    sqrt_price_x96=sqrt_price,
                    liquidity=liq,
                    amount_in=best_buy_amount,
                    fee_pips=fee,
                    zero_for_one=not zero_for_one,
                )
                if out is not None and out > best_sell_amount:
                    best_sell_amount = out
                    best_sell_pool = addr
                    best_sell_fee = fee

    if best_sell_amount <= 0:
        return None

    return {
        "buy_amount": best_buy_amount,
        "sell_amount": best_sell_amount,
        "buy_venue": best_buy_pool,
        "sell_venue": best_sell_pool,
        "buy_fee": best_buy_fee,
        "sell_fee": best_sell_fee,
        "pricing_path": best_buy_path,
        "pools_attempted": pools_attempted,
        "pools_succeeded": pools_succeeded,
    }
