"""
strategy/gates.py - Quote validation gates.

Gates validate quotes before they become opportunities.
Each gate returns (passed: bool, reject_code: ErrorCode | None).
"""

from decimal import Decimal
from typing import NamedTuple

from core.models import Quote
from core.exceptions import ErrorCode
from core.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# GATE THRESHOLDS (configurable)
# =============================================================================

# Maximum slippage between sizes (in basis points)
MAX_SLIPPAGE_BPS = 500  # 5%

# Maximum gas estimate (base, can be adaptive)
MAX_GAS_ESTIMATE = 500_000

# Adaptive gas limits by amount_in tier (wei)
GAS_LIMITS_BY_SIZE = {
    10**17: 300_000,   # 0.1 ETH - tighter limit
    10**18: 500_000,   # 1 ETH - standard
    10**19: 800_000,   # 10 ETH - allow more for larger trades
}

# Maximum ticks crossed (V3) - base limit
MAX_TICKS_CROSSED = 10

# Adaptive ticks limits by amount_in tier
TICKS_LIMITS_BY_SIZE = {
    10**17: 5,    # 0.1 ETH - tight
    10**18: 10,   # 1 ETH - standard  
    10**19: 20,   # 10 ETH - allow more for large trades
}

# Price sanity: max deviation from anchor (in basis points)
# Increased from 1000 to 1500 to reduce false positives on volatile pairs
MAX_PRICE_DEVIATION_BPS = 1500  # 15% - anything beyond is suspicious

# Pairs with known high volatility get wider threshold
HIGH_VOLATILITY_PAIRS = {"WETH/LINK", "WETH/UNI", "WETH/GMX", "WETH/ARB"}
MAX_PRICE_DEVIATION_BPS_VOLATILE = 2500  # 25% for volatile pairs

# Anchor DEX for price reference (most reliable quotes)
ANCHOR_DEX = "uniswap_v3"


# =============================================================================
# GATE RESULT
# =============================================================================

class GateResult(NamedTuple):
    """Result of a gate check."""
    passed: bool
    reject_code: ErrorCode | None = None
    details: dict | None = None


# =============================================================================
# INDIVIDUAL GATES
# =============================================================================

def gate_zero_output(quote: Quote) -> GateResult:
    """Reject if amount_out is zero."""
    if quote.amount_out == 0:
        return GateResult(
            passed=False,
            reject_code=ErrorCode.QUOTE_ZERO_OUTPUT,
            details={"amount_in": quote.amount_in},
        )
    return GateResult(passed=True)


def gate_gas_estimate(quote: Quote, max_gas: int | None = None) -> GateResult:
    """
    Reject if gas estimate is too high.
    
    Uses adaptive limits based on trade size if max_gas not specified.
    """
    if max_gas is None:
        # Find appropriate limit based on amount_in
        amount_in = quote.amount_in
        for threshold, limit in sorted(GAS_LIMITS_BY_SIZE.items(), reverse=True):
            if amount_in >= threshold:
                max_gas = limit
                break
        else:
            max_gas = MAX_GAS_ESTIMATE  # Default
    
    if quote.gas_estimate > max_gas:
        return GateResult(
            passed=False,
            reject_code=ErrorCode.QUOTE_GAS_TOO_HIGH,
            details={
                "gas_estimate": quote.gas_estimate,
                "max_gas": max_gas,
                "amount_in": quote.amount_in,
            },
        )
    return GateResult(passed=True)


def gate_ticks_crossed(quote: Quote, max_ticks: int | None = None) -> GateResult:
    """
    Reject if too many ticks crossed (V3 only, skip for Algebra).
    
    Uses adaptive limits based on trade size if max_ticks not specified.
    """
    # Algebra doesn't report ticks_crossed - skip this gate
    if quote.ticks_crossed is None:
        return GateResult(passed=True)
    
    if max_ticks is None:
        # Find appropriate limit based on amount_in
        amount_in = quote.amount_in
        for threshold, limit in sorted(TICKS_LIMITS_BY_SIZE.items(), reverse=True):
            if amount_in >= threshold:
                max_ticks = limit
                break
        else:
            max_ticks = MAX_TICKS_CROSSED  # Default
    
    if quote.ticks_crossed > max_ticks:
        return GateResult(
            passed=False,
            reject_code=ErrorCode.TICKS_CROSSED_TOO_MANY,
            details={
                "ticks_crossed": quote.ticks_crossed,
                "max_ticks": max_ticks,
                "amount_in": quote.amount_in,
            },
        )
    return GateResult(passed=True)


def gate_freshness(quote: Quote) -> GateResult:
    """Reject if quote is stale."""
    if not quote.is_fresh:
        return GateResult(
            passed=False,
            reject_code=ErrorCode.QUOTE_STALE_BLOCK,
            details={"timestamp_ms": quote.timestamp_ms},
        )
    return GateResult(passed=True)


def gate_price_sanity(
    quote: Quote,
    anchor_price: Decimal | None,
    is_anchor_dex: bool = False,
    max_deviation_bps: int | None = None,
) -> GateResult:
    """
    Reject if price deviates too much from anchor.
    
    P0 FIX: Non-anchor quotes WITHOUT anchor_price are REJECTED.
    This prevents "phantom opportunities" where only one DEX quotes.
    
    Uses adaptive threshold for volatile pairs.
    
    This catches:
    - Invalid pool/fee tier combos that return garbage prices
    - Quoter bugs
    - Pools with no real liquidity returning synthetic prices
    - Single-DEX quotes that can't be validated
    
    Args:
        quote: Quote to validate
        anchor_price: Reference price from anchor DEX (e.g., Uniswap V3)
        is_anchor_dex: True if this quote is from the anchor DEX
        max_deviation_bps: Maximum allowed deviation (auto-detected if None)
    """
    # If this IS the anchor DEX, it sets the anchor - always pass
    if is_anchor_dex:
        return GateResult(passed=True)
    
    # P0 FIX: Non-anchor quote without anchor = REJECT
    # This prevents "phantom" opportunities from single-DEX quotes
    if anchor_price is None or anchor_price == 0:
        return GateResult(
            passed=False,
            reject_code=ErrorCode.PRICE_ANCHOR_MISSING,
            details={
                "reason": "no_anchor_price",
                "dex_id": quote.pool.dex_id,
                "fee": quote.pool.fee,
                "quote_price": str(calculate_implied_price(quote)),
            },
        )
    
    quote_price = calculate_implied_price(quote)
    
    if quote_price == 0:
        return GateResult(
            passed=False,
            reject_code=ErrorCode.PRICE_SANITY_FAILED,
            details={
                "reason": "zero_price",
                "quote_price": "0",
                "anchor_price": str(anchor_price),
            },
        )
    
    # Determine max deviation based on pair volatility
    if max_deviation_bps is None:
        pair = quote.pool.pair_key
        if pair in HIGH_VOLATILITY_PAIRS:
            max_deviation_bps = MAX_PRICE_DEVIATION_BPS_VOLATILE
        else:
            max_deviation_bps = MAX_PRICE_DEVIATION_BPS
    
    # Calculate deviation: |quote - anchor| / anchor * 10000
    deviation = abs(quote_price - anchor_price) / anchor_price * 10000
    deviation_bps = int(deviation)
    
    if deviation_bps > max_deviation_bps:
        return GateResult(
            passed=False,
            reject_code=ErrorCode.PRICE_SANITY_FAILED,
            details={
                "reason": "deviation_too_high",
                "pair": quote.pool.pair_key,
                "deviation_bps": deviation_bps,
                "max_deviation_bps": max_deviation_bps,
                "quote_price": str(quote_price),
                "anchor_price": str(anchor_price),
                "dex_id": quote.pool.dex_id,
                "fee": quote.pool.fee,
                "amount_in": quote.amount_in,
            },
        )
    
    return GateResult(passed=True)


# =============================================================================
# MULTI-SIZE GATES (slippage)
# =============================================================================

def calculate_implied_price(quote: Quote) -> Decimal:
    """
    Calculate implied price from quote.
    Returns amount_out per unit of amount_in (normalized by decimals).
    """
    if quote.amount_in == 0:
        return Decimal("0")
    
    # Normalize by decimals
    in_normalized = Decimal(quote.amount_in) / Decimal(10 ** quote.token_in.decimals)
    out_normalized = Decimal(quote.amount_out) / Decimal(10 ** quote.token_out.decimals)
    
    if in_normalized == 0:
        return Decimal("0")
    
    return out_normalized / in_normalized


def calculate_slippage_bps(price_small: Decimal, price_large: Decimal) -> int:
    """
    Calculate slippage in basis points.
    
    Slippage = (price_small - price_large) / price_small * 10000
    
    Positive slippage means price degrades for larger sizes (expected).
    Negative would mean price improves for larger sizes (suspicious).
    """
    if price_small == 0:
        return 0
    
    slippage = (price_small - price_large) / price_small * 10000
    return int(slippage)


def gate_slippage_curve(
    quotes: list[Quote],
    max_slippage_bps: int = MAX_SLIPPAGE_BPS,
) -> GateResult:
    """
    Check slippage across multiple quote sizes.
    
    Expects quotes sorted by amount_in ascending.
    Rejects if:
    - Slippage between any adjacent sizes exceeds threshold
    - Slippage is negative (price improves for larger size - suspicious)
    """
    if len(quotes) < 2:
        return GateResult(passed=True)
    
    # Sort by amount_in
    sorted_quotes = sorted(quotes, key=lambda q: q.amount_in)
    
    for i in range(1, len(sorted_quotes)):
        small = sorted_quotes[i - 1]
        large = sorted_quotes[i]
        
        price_small = calculate_implied_price(small)
        price_large = calculate_implied_price(large)
        
        slippage_bps = calculate_slippage_bps(price_small, price_large)
        
        # Negative slippage = price improves for larger size (suspicious)
        if slippage_bps < 0:
            return GateResult(
                passed=False,
                reject_code=ErrorCode.QUOTE_INCONSISTENT,
                details={
                    "slippage_bps": slippage_bps,
                    "reason": "negative_slippage",
                    "amount_in_small": small.amount_in,
                    "amount_in_large": large.amount_in,
                    "price_small": str(price_small),
                    "price_large": str(price_large),
                },
            )
        
        if slippage_bps > max_slippage_bps:
            return GateResult(
                passed=False,
                reject_code=ErrorCode.SLIPPAGE_TOO_HIGH,
                details={
                    "slippage_bps": slippage_bps,
                    "max_slippage_bps": max_slippage_bps,
                    "amount_in_small": small.amount_in,
                    "amount_in_large": large.amount_in,
                    "price_small": str(price_small),
                    "price_large": str(price_large),
                },
            )
    
    return GateResult(passed=True)


def gate_monotonicity(quotes: list[Quote]) -> GateResult:
    """
    Check that amount_out increases with amount_in.
    
    Non-monotonic behavior suggests:
    - ABI encoding bug
    - Decoding error
    - Pool state corruption
    """
    if len(quotes) < 2:
        return GateResult(passed=True)
    
    # Sort by amount_in
    sorted_quotes = sorted(quotes, key=lambda q: q.amount_in)
    
    for i in range(1, len(sorted_quotes)):
        prev = sorted_quotes[i - 1]
        curr = sorted_quotes[i]
        
        if curr.amount_out < prev.amount_out:
            return GateResult(
                passed=False,
                reject_code=ErrorCode.QUOTE_INCONSISTENT,
                details={
                    "prev_amount_in": prev.amount_in,
                    "prev_amount_out": prev.amount_out,
                    "curr_amount_in": curr.amount_in,
                    "curr_amount_out": curr.amount_out,
                    "reason": "amount_out decreased with increased amount_in",
                },
            )
    
    return GateResult(passed=True)


# =============================================================================
# COMBINED GATE
# =============================================================================

def apply_single_quote_gates(
    quote: Quote,
    anchor_price: Decimal | None = None,
    is_anchor_dex: bool = False,
) -> list[GateResult]:
    """
    Apply all single-quote gates.
    Returns list of failed gate results (empty if all passed).
    
    Args:
        quote: Quote to validate
        anchor_price: Reference price from anchor DEX (for sanity check)
        is_anchor_dex: True if this quote is from the anchor DEX
    """
    gates = [
        gate_zero_output(quote),
        gate_gas_estimate(quote),
        gate_ticks_crossed(quote),
        gate_freshness(quote),
        gate_price_sanity(quote, anchor_price, is_anchor_dex),
    ]
    
    return [g for g in gates if not g.passed]


def apply_curve_gates(quotes: list[Quote]) -> list[GateResult]:
    """
    Apply all curve-level gates.
    Returns list of failed gate results (empty if all passed).
    """
    gates = [
        gate_slippage_curve(quotes),
        gate_monotonicity(quotes),
    ]
    
    return [g for g in gates if not g.passed]
