# PATH: core/validators.py
"""
Unified validators for ARBY.

M5_0: Consolidates price sanity logic.

CONTRACTS:

1. PRICE ORIENTATION CONTRACT:
   - Price is ALWAYS "quote_token per 1 base_token"
   - For WETH/USDC: price = USDC per 1 WETH (~2600-3500)
   - base_token = token_in, quote_token = token_out

2. DEVIATION FORMULA CONTRACT:
   deviation_bps = int(round(abs(price - anchor) / anchor * 10000))
   
   CAP: MAX_DEVIATION_BPS_CAP = 10000 (100%)
   If raw > cap: deviation_bps = cap, deviation_bps_capped = True

3. NO AUTO-INVERSION:
   If quote returns wrong price, we REJECT it, not "fix" it.

API CONTRACT:
   check_price_sanity() accepts anchor_source (str) for diagnostics compatibility.
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

# Cap for deviation (100% = 10000 bps)
MAX_DEVIATION_BPS_CAP = 10000


# =============================================================================
# PRICE NORMALIZATION (NO AUTO-INVERSION)
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
    Normalize price from raw amounts.
    
    PRICE ORIENTATION CONTRACT:
    - Price is ALWAYS "token_out per 1 token_in" (quote_per_base)
    - For WETH/USDC: price ~ 2600-3500 (USDC per 1 WETH)
    
    NO AUTO-INVERSION:
    - If quoter returns obviously wrong price, we detect but DO NOT auto-fix.
    
    Returns:
        Tuple of (price, price_looks_inverted, diagnostics)
    """
    diagnostics: Dict[str, Any] = {
        "amount_in_wei": str(amount_in_wei),
        "amount_out_wei": str(amount_out_wei),
        "decimals_in": decimals_in,
        "decimals_out": decimals_out,
        "token_in": token_in,
        "token_out": token_out,
        "numeraire_side": f"{token_out}_per_{token_in}",
    }
    
    in_normalized = Decimal(amount_in_wei) / Decimal(10 ** decimals_in)
    out_normalized = Decimal(amount_out_wei) / Decimal(10 ** decimals_out)
    
    diagnostics["in_normalized"] = str(in_normalized)
    diagnostics["out_normalized"] = str(out_normalized)
    
    if in_normalized <= 0:
        diagnostics["error"] = "zero_input"
        return Decimal("0"), False, diagnostics
    
    # Calculate raw price (quote_per_base)
    raw_price = out_normalized / in_normalized
    diagnostics["raw_price_quote_per_base"] = str(raw_price)
    
    # Check if price looks obviously wrong (but DO NOT auto-fix)
    price_looks_inverted = False
    pair_key = (token_in, token_out)
    bounds = PRICE_SANITY_BOUNDS.get(pair_key)
    
    if bounds:
        diagnostics["expected_range"] = [str(bounds["min"]), str(bounds["max"])]
        
        # Check if raw price is WAY below expected
        if raw_price < bounds["min"] / Decimal("10"):
            price_looks_inverted = True
            diagnostics["price_anomaly"] = "way_below_expected"
            diagnostics["possible_cause"] = "quoter_returned_wrong_direction_or_bad_data"
            logger.warning(
                f"PRICE_ANOMALY: {token_in}/{token_out} raw_price={raw_price:.6f} "
                f"way below expected [{bounds['min']}, {bounds['max']}]"
            )
    
    diagnostics["price_looks_inverted"] = price_looks_inverted
    
    return raw_price, price_looks_inverted, diagnostics


# =============================================================================
# DEVIATION CALCULATION
# =============================================================================

def calculate_deviation_bps(
    price: Decimal, 
    anchor: Decimal, 
    cap: int = MAX_DEVIATION_BPS_CAP
) -> Tuple[int, int, bool]:
    """
    Calculate price deviation in basis points.
    
    DEVIATION FORMULA CONTRACT:
        raw_bps = int(round(abs(price - anchor) / anchor * 10000))
        if raw_bps > cap: return (cap, raw_bps, True)
        else: return (raw_bps, raw_bps, False)
    
    Args:
        price: Current price
        anchor: Reference/anchor price
        cap: Maximum deviation to return (default 10000 = 100%)
    
    Returns:
        Tuple of (deviation_bps, deviation_bps_raw, was_capped)
        - deviation_bps: Capped value (for gate decisions)
        - deviation_bps_raw: Raw value (for diagnostics)
        - was_capped: True if raw > cap
    """
    if anchor <= 0:
        raise ValueError(f"Anchor must be positive, got: {anchor}")
    
    # Calculate using Decimal for precision
    deviation = abs(price - anchor) / anchor * Decimal("10000")
    raw_bps = int(round(deviation))
    
    if raw_bps > cap:
        return cap, raw_bps, True
    return raw_bps, raw_bps, False


# =============================================================================
# ANCHOR SELECTION
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
    
    Priority:
    1. Quote from anchor_dex (uniswap_v3 > pancakeswap_v3 > sushiswap_v3)
    2. Median of valid quotes
    3. Hardcoded bounds (fallback)
    
    Returns:
        Tuple of (anchor_price, anchor_info) or None
    """
    bounds = PRICE_SANITY_BOUNDS.get(pair_key)
    
    if not quotes:
        if bounds:
            anchor_price = bounds.get("anchor", (bounds["min"] + bounds["max"]) / 2)
            return anchor_price, {
                "source": "hardcoded_bounds",
                "dex_id": None,
                "bounds": [str(bounds["min"]), str(bounds["max"])],
            }
        return None
    
    # Filter quotes within reasonable range
    if bounds:
        reasonable_quotes = [
            q for q in quotes 
            if q.price >= bounds["min"] / 2 and q.price <= bounds["max"] * 2
        ]
        if reasonable_quotes:
            quotes = reasonable_quotes
    
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
    
    # Fallback to hardcoded
    if bounds:
        anchor_price = bounds.get("anchor", (bounds["min"] + bounds["max"]) / 2)
        return anchor_price, {
            "source": "hardcoded_bounds",
            "dex_id": None,
        }
    
    return None


# =============================================================================
# PRICE SANITY CHECK
# =============================================================================

def check_price_sanity(
    token_in: str,
    token_out: str,
    price: Decimal,
    config: Dict[str, Any],
    dynamic_anchor: Optional[Decimal] = None,
    fee: int = 0,
    decimals_in: int = 18,
    decimals_out: int = 6,
    dex_id: Optional[str] = None,
    pool_address: Optional[str] = None,
    amount_in_wei: Optional[int] = None,
    amount_out_wei: Optional[int] = None,
    anchor_info: Optional[Dict[str, Any]] = None,
    # BACKWARD COMPATIBLE: anchor_source for run_scan_real.py compatibility
    anchor_source: Optional[str] = None,
) -> Tuple[bool, Optional[int], Optional[str], Dict[str, Any]]:
    """
    Check price sanity with DYNAMIC anchor.
    
    DEVIATION FORMULA (documented):
        deviation_bps = int(round(abs(price - anchor) / anchor * 10000))
        CAP = 10000 bps (100%)
    
    API CONTRACT:
        - anchor_source: str | None - for diagnostics/compatibility
        - anchor_info: dict | None - detailed anchor info
    
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
        anchor_info: Info about anchor source (for diagnostics)
        anchor_source: String anchor source (for backward compatibility)
    
    Returns:
        Tuple of (passed, deviation_bps, error_message, diagnostics)
    """
    pair_key = (token_in, token_out)
    bounds = PRICE_SANITY_BOUNDS.get(pair_key)
    max_deviation_bps = config.get(
        "price_sanity_max_deviation_bps",
        PRICE_SANITY_MAX_DEVIATION_BPS
    )
    
    # Build diagnostics
    diagnostics: Dict[str, Any] = {
        "implied_price": str(price),
        "token_in": token_in,
        "token_out": token_out,
        "numeraire_side": f"{token_out}_per_{token_in}",
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
        diagnostics["amount_in_wei"] = str(amount_in_wei)
    if amount_out_wei is not None:
        diagnostics["amount_out_wei"] = str(amount_out_wei)
    if bounds:
        diagnostics["expected_range"] = [str(bounds["min"]), str(bounds["max"])]
    
    # Check if sanity is disabled
    if not config.get("price_sanity_enabled", True):
        diagnostics["sanity_check"] = "disabled"
        return True, None, None, diagnostics
    
    # Check for zero/negative price
    if price <= 0:
        diagnostics["error"] = "zero_or_negative_price"
        return False, None, "Zero or negative price", diagnostics
    
    # Determine anchor price
    anchor_price: Optional[Decimal] = None
    
    if dynamic_anchor and dynamic_anchor > 0:
        anchor_price = dynamic_anchor
        
        # Set anchor_source from multiple sources (priority: anchor_info > anchor_source > default)
        if anchor_info:
            diagnostics["anchor_source"] = anchor_info.get("source", "dynamic")
            diagnostics["anchor_details"] = anchor_info
        elif anchor_source:
            diagnostics["anchor_source"] = anchor_source
        else:
            diagnostics["anchor_source"] = "dynamic"
            
    elif bounds:
        anchor_price = bounds.get("anchor", (bounds["min"] + bounds["max"]) / 2)
        diagnostics["anchor_source"] = "hardcoded_bounds"
    
    if anchor_price is None:
        diagnostics["sanity_check"] = "no_anchor_available"
        return True, None, None, diagnostics
    
    diagnostics["anchor_price"] = str(anchor_price)
    
    # Calculate deviation with cap
    deviation_bps, deviation_bps_raw, was_capped = calculate_deviation_bps(
        price, anchor_price, cap=MAX_DEVIATION_BPS_CAP
    )
    
    diagnostics["deviation_bps"] = deviation_bps
    diagnostics["deviation_bps_raw"] = deviation_bps_raw
    diagnostics["deviation_bps_capped"] = was_capped
    diagnostics["max_deviation_bps"] = max_deviation_bps
    
    # Check deviation against threshold
    if deviation_bps > max_deviation_bps:
        # Determine specific error message
        if bounds and price < bounds["min"]:
            error_msg = f"Price {price:.4f} below minimum {bounds['min']}"
            diagnostics["error"] = "below_minimum"
        elif bounds and price > bounds["max"]:
            error_msg = f"Price {price:.4f} above maximum {bounds['max']}"
            diagnostics["error"] = "above_maximum"
        else:
            error_msg = f"Deviation {deviation_bps}bps exceeds max {max_deviation_bps}bps"
            diagnostics["error"] = "deviation_exceeded"
        
        return False, deviation_bps, error_msg, diagnostics
    
    diagnostics["sanity_check"] = "passed"
    return True, deviation_bps, None, diagnostics


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def is_anchor_dex(dex_id: str) -> bool:
    """Check if DEX is in the anchor priority list."""
    return dex_id in ANCHOR_DEX_PRIORITY


def get_anchor_dex_priority(dex_id: str) -> int:
    """Get priority of DEX for anchoring (lower = higher priority)."""
    try:
        return ANCHOR_DEX_PRIORITY.index(dex_id)
    except ValueError:
        return 999
