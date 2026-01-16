"""
strategy/gates.py - Quote validation gates.

Gates validate quotes before they become opportunities.
Each gate returns (passed: bool, reject_code: ErrorCode | None).

Team Lead M3_P1 v2 directives:
- Amount-ladder adaptive per pool fitness
- Ticks thresholds by token type (volatile vs stable)
- 2-level PRICE_SANITY check
- Plausibility as function, not constant
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

# Default maximum gas estimate (fallback)
MAX_GAS_ESTIMATE = 500_000

# Default maximum ticks crossed (V3)
MAX_TICKS_CROSSED = 10

# Price sanity: max deviation from anchor (in basis points)
# Level 1: coarse filter
MAX_PRICE_DEVIATION_BPS_L1 = 2500       # 25% - Level 1 (soft reject)
MAX_PRICE_DEVIATION_BPS_VOLATILE_L1 = 4000  # 40% for volatile - Level 1

# Level 2: requires second anchor confirmation
MAX_PRICE_DEVIATION_BPS_L2 = 1500       # 15% - Level 2 (hard reject if no 2nd anchor)
MAX_PRICE_DEVIATION_BPS_VOLATILE_L2 = 2500  # 25% for volatile - Level 2

# Legacy aliases for backwards compatibility
MAX_PRICE_DEVIATION_BPS = MAX_PRICE_DEVIATION_BPS_L2
MAX_PRICE_DEVIATION_BPS_VOLATILE = MAX_PRICE_DEVIATION_BPS_VOLATILE_L2

# Token type classification
HIGH_VOLATILITY_PAIRS = {
    "WETH/LINK", "WETH/UNI", "WETH/GMX", "WETH/ARB", "WETH/MAGIC", "WETH/RDNT",
    "WETH/PENDLE", "WETH/GNS", "WETH/GRAIL", "WETH/JOE", "WETH/DPX",
    "ARB/WETH", "LINK/WETH", "UNI/WETH", "GMX/WETH",
}

STABLE_PAIRS = {
    "USDC/USDT", "USDT/USDC", "USDC/DAI", "DAI/USDC", "USDT/DAI", "DAI/USDT",
    "FRAX/USDC", "USDC/FRAX", "LUSD/USDC", "USDC/LUSD", "USDE/USDC", "USDC/USDE",
}

# Anchor DEX for price reference (most reliable quotes)
ANCHOR_DEX = "uniswap_v3"


# =============================================================================
# ADAPTIVE LIMITS (by trade size AND token type) - Team Lead Крок 2, 3
# =============================================================================

# Gas limits by amount_in (wei) - smaller trades need tighter limits
GAS_LIMITS_BY_SIZE = {
    10**16: 200_000,   # 0.01 ETH - very tight (for retry smaller)
    10**17: 300_000,   # 0.1 ETH - tight
    10**18: 500_000,   # 1 ETH - standard
    10**19: 800_000,   # 10 ETH - larger trades allowed more gas
}

# Ticks limits by amount_in (wei) for VOLATILE pairs
TICKS_LIMITS_VOLATILE = {
    10**16: 5,     # 0.01 ETH - allow more for volatile
    10**17: 8,     # 0.1 ETH
    10**18: 15,    # 1 ETH
    10**19: 25,    # 10 ETH
}

# Ticks limits by amount_in (wei) for STABLE pairs (tighter)
TICKS_LIMITS_STABLE = {
    10**16: 2,     # 0.01 ETH - very tight for stables
    10**17: 3,     # 0.1 ETH
    10**18: 5,     # 1 ETH
    10**19: 10,    # 10 ETH
}

# Ticks limits by amount_in (wei) for NORMAL pairs
TICKS_LIMITS_BY_SIZE = {
    10**16: 3,    # 0.01 ETH - ultra tight (for retry smaller)
    10**17: 5,    # 0.1 ETH - very tight
    10**18: 10,   # 1 ETH - standard
    10**19: 20,   # 10 ETH - more impact allowed for larger trades
}


# =============================================================================
# ADAPTIVE AMOUNT SIZING
# =============================================================================

# Standard test amounts (wei)
STANDARD_AMOUNTS = [
    10**16,   # 0.01 ETH - micro
    10**17,   # 0.1 ETH - small
    10**18,   # 1 ETH - standard
]


def suggest_smaller_amount(
    current_amount: int,
    reject_reason: str,
) -> int | None:
    """
    Suggest a smaller amount based on rejection reason.
    
    Team Lead directive:
    "Gas gate: зробити адаптивний amount_in (менше amount → менше ticks → менше gas)
    або separate bucket 'too expensive, retry smaller'."
    
    Returns:
        Smaller amount to try, or None if already at minimum
    """
    # Find current bracket (largest std_amount <= current_amount)
    bracket_idx = -1
    for i, std_amount in enumerate(STANDARD_AMOUNTS):
        if current_amount >= std_amount:
            bracket_idx = i
    
    # If found a bracket and it's not the minimum, suggest one step down
    if bracket_idx > 0:
        return STANDARD_AMOUNTS[bracket_idx - 1]
    
    # Already at minimum or below
    return None


def get_retry_amounts(base_amount: int) -> list[int]:
    """
    Get list of amounts to try if base_amount fails gates.
    
    Returns amounts from base down to minimum, excluding base.
    """
    retry = []
    for std_amount in reversed(STANDARD_AMOUNTS):
        if std_amount < base_amount:
            retry.append(std_amount)
    return retry


def get_adaptive_gas_limit(amount_in: int) -> int:
    """
    Get gas limit based on trade size.
    Larger trades can tolerate higher gas costs as a proportion of value.
    """
    for size_threshold, gas_limit in sorted(GAS_LIMITS_BY_SIZE.items(), reverse=True):
        if amount_in >= size_threshold:
            return gas_limit
    # Smallest trades get tightest limit
    return min(GAS_LIMITS_BY_SIZE.values())


def get_pair_type(pair: str | None) -> str:
    """
    Classify pair as 'volatile', 'stable', or 'normal'.
    
    Team Lead Крок 3: "max_ticks має залежати від типу токена (volatile vs stable)"
    """
    if not pair:
        return "normal"
    
    # Normalize pair for lookup
    pair_upper = pair.upper()
    pair_reversed = "/".join(reversed(pair_upper.split("/")))
    
    if pair_upper in STABLE_PAIRS or pair_reversed in STABLE_PAIRS:
        return "stable"
    
    if pair_upper in HIGH_VOLATILITY_PAIRS or pair_reversed in HIGH_VOLATILITY_PAIRS:
        return "volatile"
    
    return "normal"


def get_adaptive_ticks_limit(amount_in: int, pair: str | None = None) -> int:
    """
    Get ticks limit based on trade size AND pair type.
    
    Team Lead Крок 3:
    "max_ticks має залежати від amount_in та типу токена (volatile vs stable),
    інакше ти просто відсікаєш половину світу 'заради чистоти'."
    
    Args:
        amount_in: Trade size in wei
        pair: Pair string like "WETH/ARB" for type detection
    
    Returns:
        Maximum allowed ticks crossed
    """
    pair_type = get_pair_type(pair)
    
    # Select appropriate limits table
    if pair_type == "volatile":
        limits = TICKS_LIMITS_VOLATILE
    elif pair_type == "stable":
        limits = TICKS_LIMITS_STABLE
    else:
        limits = TICKS_LIMITS_BY_SIZE
    
    for size_threshold, ticks_limit in sorted(limits.items(), reverse=True):
        if amount_in >= size_threshold:
            return ticks_limit
    
    # Smallest trades get tightest limit
    return min(limits.values())


def get_price_deviation_limit(pair: str | None = None, level: int = 2) -> int:
    """
    Get price deviation limit based on pair volatility and check level.
    
    Team Lead Крок 4: 2-level price sanity check
    - Level 1: coarse filter (25%/40%) - soft reject, flag for second anchor
    - Level 2: hard filter (15%/25%) - reject if no second anchor confirms
    
    Args:
        pair: Pair string for volatility detection
        level: 1 or 2 (default 2 for backwards compatibility)
    
    Returns:
        Maximum deviation in basis points
    """
    pair_type = get_pair_type(pair)
    is_volatile = pair_type == "volatile"
    
    if level == 1:
        # Level 1: coarse filter
        return MAX_PRICE_DEVIATION_BPS_VOLATILE_L1 if is_volatile else MAX_PRICE_DEVIATION_BPS_L1
    else:
        # Level 2: hard filter (default)
        return MAX_PRICE_DEVIATION_BPS_VOLATILE_L2 if is_volatile else MAX_PRICE_DEVIATION_BPS_L2


def get_price_deviation_limits(pair: str | None = None) -> tuple[int, int]:
    """
    Get both price deviation limits for 2-level checking.
    
    Returns:
        Tuple of (level1_limit, level2_limit)
    """
    return (
        get_price_deviation_limit(pair, level=1),
        get_price_deviation_limit(pair, level=2),
    )


# =============================================================================
# POOL FITNESS TRACKING (Team Lead Крок 2)
# =============================================================================

class PoolFitness:
    """
    Track pool fitness for adaptive amount selection.
    
    Team Lead Крок 2:
    "якщо QUOTE_GAS_TOO_HIGH на малому amount — pool не годиться;
    якщо тільки на великому — зменшувати max amount для цього pool/pair/fee"
    """
    
    def __init__(self):
        # pool_key -> max_working_amount (wei)
        self._max_amounts: dict[str, int] = {}
        # pool_key -> failure count at minimum amount
        self._min_amount_failures: dict[str, int] = {}
    
    @staticmethod
    def _make_key(pair: str, dex_id: str, fee: int) -> str:
        return f"{pair}_{dex_id}_{fee}"
    
    def record_success(self, pair: str, dex_id: str, fee: int, amount: int) -> None:
        """Record successful quote at given amount."""
        key = self._make_key(pair, dex_id, fee)
        current_max = self._max_amounts.get(key, 0)
        if amount > current_max:
            self._max_amounts[key] = amount
    
    def record_failure(
        self,
        pair: str,
        dex_id: str,
        fee: int,
        amount: int,
        reason: str,
    ) -> None:
        """
        Record failure and adjust max amount if needed.
        
        If failure at minimum amount, track for pool exclusion.
        If failure at larger amount, reduce max_amount for pool.
        """
        key = self._make_key(pair, dex_id, fee)
        min_amount = min(STANDARD_AMOUNTS)
        
        if amount <= min_amount:
            # Failure at minimum = pool may be unfit
            self._min_amount_failures[key] = self._min_amount_failures.get(key, 0) + 1
        else:
            # Failure at larger amount = reduce max
            current_max = self._max_amounts.get(key, amount)
            if amount <= current_max:
                # Find next smaller standard amount
                for std in reversed(STANDARD_AMOUNTS):
                    if std < amount:
                        self._max_amounts[key] = std
                        break
    
    def get_max_amount(self, pair: str, dex_id: str, fee: int) -> int | None:
        """
        Get maximum working amount for pool.
        
        Returns:
            Max amount in wei, or None if pool appears unfit
        """
        key = self._make_key(pair, dex_id, fee)
        
        # Check if pool is marked as unfit
        if self._min_amount_failures.get(key, 0) >= 3:
            return None  # Pool is unfit, should be skipped
        
        return self._max_amounts.get(key)
    
    def is_pool_unfit(self, pair: str, dex_id: str, fee: int) -> bool:
        """Check if pool is marked as unfit (too many min-amount failures)."""
        key = self._make_key(pair, dex_id, fee)
        return self._min_amount_failures.get(key, 0) >= 3


# Singleton instance
_pool_fitness: PoolFitness | None = None


def get_pool_fitness() -> PoolFitness:
    """Get singleton pool fitness tracker."""
    global _pool_fitness
    if _pool_fitness is None:
        _pool_fitness = PoolFitness()
    return _pool_fitness


def reset_pool_fitness() -> None:
    """Reset pool fitness tracker (for testing)."""
    global _pool_fitness
    _pool_fitness = None


# =============================================================================
# GATE RESULT
# =============================================================================

class GateResult(NamedTuple):
    """Result of a gate check."""
    passed: bool
    reject_code: ErrorCode | None = None
    details: dict | None = None
    # Team Lead Крок 4: flag for second anchor requirement
    requires_second_anchor: bool = False


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
    
    Uses adaptive limits based on amount_in if max_gas not specified.
    Larger trades can tolerate higher gas costs proportionally.
    """
    # Use adaptive limit if not explicitly provided
    if max_gas is None:
        max_gas = get_adaptive_gas_limit(quote.amount_in)
    
    if quote.gas_estimate > max_gas:
        # Team Lead Крок 7: Better telemetry
        # Calculate gas cost in approximate terms
        # Using rough estimates: 0.01 gwei gas price on L2, ~$3000/ETH
        gas_price_gwei = 0.01  # Conservative L2 estimate
        gas_cost_eth = (quote.gas_estimate * gas_price_gwei) / 10**9
        gas_cost_usdc = gas_cost_eth * 3000  # Rough ETH price
        
        max_gas_cost_eth = (max_gas * gas_price_gwei) / 10**9
        threshold_usdc = max_gas_cost_eth * 3000
        
        return GateResult(
            passed=False,
            reject_code=ErrorCode.QUOTE_GAS_TOO_HIGH,
            details={
                "gas_estimate": quote.gas_estimate,
                "max_gas": max_gas,
                "amount_in": quote.amount_in,
                # Team Lead Крок 7: Additional telemetry
                "gas_price_gwei": gas_price_gwei,
                "gas_cost_eth": round(gas_cost_eth, 8),
                "gas_cost_usdc": round(gas_cost_usdc, 4),
                "threshold_usdc": round(threshold_usdc, 4),
                "dex_id": quote.pool.dex_id,
                "fee": quote.pool.fee,
                "pair": f"{quote.token_in.symbol}/{quote.token_out.symbol}",
            },
        )
    return GateResult(passed=True)


def gate_ticks_crossed(
    quote: Quote,
    max_ticks: int | None = None,
    pair: str | None = None,
) -> GateResult:
    """
    Reject if too many ticks crossed (V3 only, skip for Algebra).
    
    Team Lead Крок 3: Uses adaptive limits based on amount_in AND pair type.
    Volatile pairs get more tolerance, stable pairs get less.
    
    Args:
        quote: Quote to validate
        max_ticks: Override limit (if not provided, uses adaptive)
        pair: Pair string for type detection (e.g. "WETH/ARB")
    """
    # Algebra doesn't report ticks_crossed - skip this gate
    if quote.ticks_crossed is None:
        return GateResult(passed=True)
    
    # Derive pair from quote if not provided
    if pair is None:
        pair = f"{quote.token_in.symbol}/{quote.token_out.symbol}"
    
    # Use adaptive limit if not explicitly provided
    if max_ticks is None:
        max_ticks = get_adaptive_ticks_limit(quote.amount_in, pair)
    
    if quote.ticks_crossed > max_ticks:
        return GateResult(
            passed=False,
            reject_code=ErrorCode.TICKS_CROSSED_TOO_MANY,
            details={
                "ticks_crossed": quote.ticks_crossed,
                "max_ticks": max_ticks,
                "amount_in": quote.amount_in,
                "pair": pair,
                "pair_type": get_pair_type(pair),
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
    pair: str | None = None,
    second_anchor_price: Decimal | None = None,
) -> GateResult:
    """
    2-level price sanity check.
    
    Team Lead Крок 4:
    "рівень 1: грубий фільтр (25% як у тебе),
     рівень 2: якщо відхилення велике, але spread виглядає 'казково' — 
     вимагати підтвердження другим anchor"
    
    Level 1: Coarse filter (25%/40% for volatile)
    - If deviation > L1, always reject
    
    Level 2: Fine filter (15%/25% for volatile)
    - If deviation > L2 but <= L1, flag requires_second_anchor
    - If second_anchor_price provided and confirms, pass
    - Otherwise soft-reject with requires_second_anchor=True
    
    Args:
        quote: Quote to validate
        anchor_price: Primary reference price from anchor DEX
        is_anchor_dex: True if this quote is from the anchor DEX
        max_deviation_bps: Override limit (uses adaptive if None)
        pair: Pair string for volatility detection
        second_anchor_price: Optional second anchor for confirmation
    """
    # If this IS the anchor DEX, it sets the anchor - always pass
    if is_anchor_dex:
        return GateResult(passed=True)
    
    # Derive pair from quote if not provided
    if pair is None:
        pair = f"{quote.token_in.symbol}/{quote.token_out.symbol}"
    
    # Get 2-level limits
    limit_l1, limit_l2 = get_price_deviation_limits(pair)
    
    # Override with explicit limit if provided (for backwards compatibility)
    if max_deviation_bps is not None:
        limit_l2 = max_deviation_bps
    
    # P0 FIX: Non-anchor quote without anchor = REJECT
    if anchor_price is None or anchor_price == 0:
        return GateResult(
            passed=False,
            reject_code=ErrorCode.PRICE_ANCHOR_MISSING,
            details={
                "reason": "no_anchor_price",
                "pair": pair,
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
                "pair": pair,
                "quote_price": "0",
                "anchor_price": str(anchor_price),
            },
        )
    
    # Calculate deviation: |quote - anchor| / anchor * 10000
    deviation = abs(quote_price - anchor_price) / anchor_price * 10000
    deviation_bps = int(deviation)
    
    # LEVEL 1: Coarse filter - hard reject if beyond L1
    if deviation_bps > limit_l1:
        return GateResult(
            passed=False,
            reject_code=ErrorCode.PRICE_SANITY_FAILED,
            details={
                "reason": "deviation_too_high_L1",
                "pair": pair,
                "deviation_bps": deviation_bps,
                "max_deviation_bps_L1": limit_l1,
                "max_deviation_bps_L2": limit_l2,
                "quote_price": str(quote_price),
                "anchor_price": str(anchor_price),
                "dex_id": quote.pool.dex_id,
                "fee": quote.pool.fee,
                "amount_in": quote.amount_in,
            },
        )
    
    # LEVEL 2: Fine filter - check if within L2
    if deviation_bps <= limit_l2:
        # Within L2 tolerance - pass
        return GateResult(passed=True)
    
    # Between L1 and L2: requires second anchor confirmation
    if second_anchor_price is not None and second_anchor_price > 0:
        # Check if quote is closer to second anchor
        deviation_to_second = abs(quote_price - second_anchor_price) / second_anchor_price * 10000
        deviation_to_second_bps = int(deviation_to_second)
        
        # If second anchor confirms (within L2), pass
        if deviation_to_second_bps <= limit_l2:
            return GateResult(
                passed=True,
                details={
                    "confirmed_by_second_anchor": True,
                    "deviation_to_primary": deviation_bps,
                    "deviation_to_second": deviation_to_second_bps,
                },
            )
    
    # Between L1 and L2 without second anchor confirmation
    # Return soft-reject with flag
    return GateResult(
        passed=False,
        reject_code=ErrorCode.PRICE_SANITY_FAILED,
        requires_second_anchor=True,
        details={
            "reason": "deviation_between_L1_L2",
            "pair": pair,
            "deviation_bps": deviation_bps,
            "max_deviation_bps_L1": limit_l1,
            "max_deviation_bps_L2": limit_l2,
            "quote_price": str(quote_price),
            "anchor_price": str(anchor_price),
            "dex_id": quote.pool.dex_id,
            "fee": quote.pool.fee,
            "amount_in": quote.amount_in,
            "needs_second_anchor": True,
        },
    )


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
