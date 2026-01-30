# PATH: core/validators.py
"""
Unified validators for ARBY.

M5_0: Consolidates price sanity logic from:
- strategy/gates.py (gate_price_sanity)
- strategy/jobs/run_scan_real.py (check_price_sanity, normalize_price)

CONTRACTS:
- normalize_price(): Always returns (price, was_inverted, diagnostics)
- check_price_sanity(): Backward compatible, dynamic_anchor=None default
- PriceSanityResult: Standardized result with full diagnostics

USAGE:
    from core.validators import normalize_price, check_price_sanity
    
    price, inverted, diag = normalize_price(...)
    passed, deviation, error, diagnostics = check_price_sanity(...)
"""

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from core.constants import (
    ANCHOR_DEX_PRIORITY,
    DEFAULT_ANCHOR_DEX,
    PRICE_SANITY_BOUNDS,
    PRICE_SANITY_MAX_DEVIATION_BPS,
)

logger = logging.getLogger("core.validators")


# =============================================================================
# PRICE NORMALIZATION (STEP 1-2)
# =============================================================================

def normalize_price(
    amount_in_wei: int,
    amount_out_wei: int,
    decimals_in: int,
    decimals_out: int,
    token_in: str,
    token_out: str,
) -> Tuple[Decimal, bool, Dict[str, Any]]:
    """
    Normalize price with inversion detection.
    
    PRICE CONTRACT:
    - Price is ALWAYS "token_out per 1 token_in"
    - For WETH/USDC: price ~ 3500 (USDC per 1 WETH)
    - If price < 100 for WETH/USDC, it's inverted and auto-corrected
    
    Args:
        amount_in_wei: Input amount in wei
        amount_out_wei: Output amount in wei
        decimals_in: Token in decimals
        decimals_out: Token out decimals
        token_in: Token in symbol
        token_out: Token out symbol
        
    Returns:
        Tuple of (normalized_price, was_inverted, diagnostics)
        - normalized_price: Decimal, token_out per 1 token_in
        - was_inverted: bool, True if price was auto-corrected
        - diagnostics: dict with raw_price, normalized_price, etc.
    """
    diagnostics: Dict[str, Any] = {
        "amount_in_wei": amount_in_wei,
        "amount_out_wei": amount_out_wei,
        "decimals_in": decimals_in,
        "decimals_out": decimals_out,
        "token_in": token_in,
        "token_out": token_out,
    }
    
    in_normalized = Decimal(amount_in_wei) / Decimal(10 ** decimals_in)
    out_normalized = Decimal(amount_out_wei) / Decimal(10 ** decimals_out)
    
    diagnostics["in_normalized"] = str(in_normalized)
    diagnostics["out_normalized"] = str(out_normalized)
    
    if in_normalized <= 0:
        diagnostics["error"] = "zero_input"
        return Decimal("0"), False, diagnostics
    
    raw_price = out_normalized / in_normalized
    diagnostics["raw_price"] = str(raw_price)
    
    was_inverted = False
    final_price = raw_price
    
    # STEP 1: Detect inverted price for known pairs
    # WETH/USDC should be ~3500, not ~0.0003
    if token_in == "WETH" and token_out in ("USDC", "USDT"):
        if raw_price < Decimal("100") and raw_price > 0:
            # Price is inverted (WETH per USDC instead of USDC per WETH)
            final_price = Decimal("1") / raw_price
            was_inverted = True
            logger.debug(f"Price inversion detected: {raw_price:.6f} -> {final_price:.2f}")
    
    elif token_in == "WBTC" and token_out in ("USDC", "USDT"):
        if raw_price < Decimal("1000") and raw_price > 0:
            final_price = Decimal("1") / raw_price
            was_inverted = True
    
    diagnostics["normalized_price"] = str(final_price)
    diagnostics["inversion_applied"] = was_inverted
    
    return final_price, was_inverted, diagnostics


# =============================================================================
# ANCHOR SELECTION (STEP 3 - improved)
# =============================================================================

@dataclass
class AnchorQuote:
    """Represents a quote that can be used as anchor."""
    dex_id: str
    price: Decimal
    fee: int
    pool_address: str
    block_number: int
    
    @property
    def is_from_anchor_dex(self) -> bool:
        """Check if quote is from a priority anchor DEX."""
        return self.dex_id in ANCHOR_DEX_PRIORITY


def select_anchor(
    quotes: List[AnchorQuote],
    pair_key: Tuple[str, str],
) -> Optional[Tuple[Decimal, Dict[str, Any]]]:
    """
    Select best anchor from available quotes.
    
    M5_0: Improved anchor selection - NOT "first success"
    
    Priority:
    1. Quote from anchor_dex (uniswap_v3 > pancakeswap_v3 > sushiswap_v3)
    2. Median of valid quotes (if no anchor_dex)
    3. Hardcoded bounds (fallback)
    
    Args:
        quotes: List of valid quotes for the pair
        pair_key: (token_in, token_out) tuple
        
    Returns:
        Tuple of (anchor_price, anchor_info) or None
    """
    if not quotes:
        # Fallback to hardcoded bounds
        bounds = PRICE_SANITY_BOUNDS.get(pair_key)
        if bounds:
            anchor_price = bounds.get("anchor", (bounds["min"] + bounds["max"]) / 2)
            return anchor_price, {
                "source": "hardcoded_bounds",
                "dex_id": None,
                "bounds": [str(bounds["min"]), str(bounds["max"])],
            }
        return None
    
    # Priority 1: Quote from anchor_dex
    for priority_dex in ANCHOR_DEX_PRIORITY:
        for q in quotes:
            if q.dex_id == priority_dex and q.price > 0:
                return q.price, {
                    "source": "anchor_dex",
                    "dex_id": q.dex_id,
                    "pool_address": q.pool_address,
                    "fee": q.fee,
                    "block_number": q.block_number,
                }
    
    # Priority 2: Median of valid quotes
    valid_prices = sorted([q.price for q in quotes if q.price > 0])
    if valid_prices:
        n = len(valid_prices)
        if n % 2 == 1:
            median_price = valid_prices[n // 2]
        else:
            median_price = (valid_prices[n // 2 - 1] + valid_prices[n // 2]) / 2
        
        return median_price, {
            "source": "median_quotes",
            "quotes_count": n,
            "prices": [str(p) for p in valid_prices],
        }
    
    return None


# =============================================================================
# PRICE SANITY CHECK (STEP 6)
# =============================================================================

@dataclass
class PriceSanityResult:
    """
    Result of price sanity check with full diagnostics.
    
    DIAGNOSTIC CONTRACT (STEP 4 - expanded):
    - Always includes: implied_price, anchor_price
    - On failure: amount_in_wei, amount_out_wei, decimals, raw_price, etc.
    """
    passed: bool
    deviation_bps: Optional[int] = None
    error_message: Optional[str] = None
    diagnostics: Dict[str, Any] = field(default_factory=dict)


def check_price_sanity(
    token_in: str,
    token_out: str,
    price: Decimal,
    config: Dict[str, Any],
    dynamic_anchor: Optional[Decimal] = None,  # BACKWARD COMPATIBLE
    fee: int = 0,
    decimals_in: int = 18,
    decimals_out: int = 6,
    dex_id: Optional[str] = None,
    pool_address: Optional[str] = None,
    amount_in_wei: Optional[int] = None,
    amount_out_wei: Optional[int] = None,
    anchor_source: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, Optional[int], Optional[str], Dict[str, Any]]:
    """
    Check price sanity with DYNAMIC anchor.
    
    BACKWARD COMPATIBLE: dynamic_anchor defaults to None.
    
    DIAGNOSTIC CONTRACT (STEP 4 - expanded):
    diagnostics always includes:
    - implied_price, anchor_price (always)
    - amount_in_wei, amount_out_wei, decimals_in/out (when provided)
    - raw_price, normalized_price, inversion_applied (when applicable)
    - pool_fee, pool_address, dex_id (when provided)
    
    Priority:
    1. Use dynamic_anchor if available (from anchor_dex or median)
    2. Fall back to hardcoded bounds
    
    Args:
        token_in: Input token symbol
        token_out: Output token symbol
        price: Normalized price to check
        config: Config dict with price_sanity_enabled, etc.
        dynamic_anchor: Price from anchor selection (default None)
        fee: Pool fee tier
        decimals_in: Token in decimals
        decimals_out: Token out decimals
        dex_id: DEX identifier (for diagnostics)
        pool_address: Pool address (for diagnostics)
        amount_in_wei: Raw input amount (for diagnostics)
        amount_out_wei: Raw output amount (for diagnostics)
        anchor_source: Info about anchor source (for diagnostics)
        
    Returns:
        Tuple of (passed, deviation_bps, error_message, diagnostics)
    """
    # STEP 4: Extended diagnostics
    diagnostics: Dict[str, Any] = {
        "implied_price": str(price),
        "token_in": token_in,
        "token_out": token_out,
        "token_in_decimals": decimals_in,
        "token_out_decimals": decimals_out,
        "pool_fee": fee,
    }
    
    # Add optional diagnostics
    if dex_id:
        diagnostics["dex_id"] = dex_id
    if pool_address:
        diagnostics["pool_address"] = pool_address
    if amount_in_wei is not None:
        diagnostics["amount_in_wei"] = amount_in_wei
    if amount_out_wei is not None:
        diagnostics["amount_out_wei"] = amount_out_wei
    if anchor_source:
        diagnostics["anchor_source_info"] = anchor_source
    
    # Check if sanity is disabled
    if not config.get("price_sanity_enabled", True):
        diagnostics["sanity_check"] = "disabled"
        diagnostics["anchor_price"] = "N/A"
        return True, None, None, diagnostics
    
    # Check for zero/negative price
    if price <= 0:
        diagnostics["error"] = "zero_or_negative_price"
        diagnostics["anchor_price"] = "N/A"
        return False, None, "Zero or negative price", diagnostics
    
    pair_key = (token_in, token_out)
    bounds = PRICE_SANITY_BOUNDS.get(pair_key)
    max_deviation_bps = config.get(
        "price_sanity_max_deviation_bps", 
        PRICE_SANITY_MAX_DEVIATION_BPS
    )
    
    # STEP 6: Use dynamic anchor if available
    if dynamic_anchor and dynamic_anchor > 0:
        diagnostics["anchor_source"] = "dynamic"
        diagnostics["anchor_price"] = str(dynamic_anchor)
        
        deviation_bps = int(abs(price - dynamic_anchor) / dynamic_anchor * Decimal("10000"))
        diagnostics["deviation_bps"] = deviation_bps
        diagnostics["max_deviation_bps"] = max_deviation_bps
        
        if deviation_bps > max_deviation_bps:
            diagnostics["error"] = "deviation_from_anchor"
            return (
                False,
                deviation_bps,
                f"Deviation {deviation_bps}bps from anchor {dynamic_anchor:.2f}",
                diagnostics,
            )
        
        diagnostics["sanity_check"] = "passed_dynamic"
        return True, deviation_bps, None, diagnostics
    
    # Fallback: hardcoded bounds
    if not bounds:
        diagnostics["sanity_check"] = "no_anchor_for_pair"
        diagnostics["anchor_price"] = "N/A"
        return True, None, None, diagnostics
    
    # BACKWARD COMPATIBLE: always set anchor_price
    anchor_price = bounds.get("anchor", (bounds["min"] + bounds["max"]) / 2)
    diagnostics["anchor_source"] = "hardcoded_bounds"
    diagnostics["anchor_price"] = str(anchor_price)
    diagnostics["price_bounds"] = [str(bounds["min"]), str(bounds["max"])]
    
    if price < bounds["min"] or price > bounds["max"]:
        deviation_bps = int(abs(price - anchor_price) / anchor_price * Decimal("10000"))
        diagnostics["deviation_bps"] = deviation_bps
        diagnostics["error"] = "outside_bounds"
        return (
            False,
            deviation_bps,
            f"Price {price:.2f} outside [{bounds['min']}, {bounds['max']}]",
            diagnostics,
        )
    
    diagnostics["sanity_check"] = "passed_bounds"
    return True, None, None, diagnostics


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def is_anchor_dex(dex_id: str) -> bool:
    """Check if DEX is in the anchor priority list."""
    return dex_id in ANCHOR_DEX_PRIORITY


def get_anchor_dex_priority(dex_id: str) -> int:
    """
    Get priority of DEX for anchoring (lower = higher priority).
    
    Returns 999 if not in priority list.
    """
    try:
        return ANCHOR_DEX_PRIORITY.index(dex_id)
    except ValueError:
        return 999
