# PATH: core/validators.py
"""
Unified validators for ARBY.

CONTRACTS:
1. Price = quote_token per 1 base_token (ALWAYS)
2. deviation_bps via Decimal math, ROUND_HALF_UP
3. inversion_applied = False (ALWAYS)
4. AnchorQuote.dex_id is REQUIRED
5. check_price_sanity accepts anchor_source
6. deviation capped to MAX_DEVIATION_BPS_CAP with capped flag
"""

import logging
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, List, Optional, Tuple

from core.constants import (
    ANCHOR_DEX_PRIORITY,
    PRICE_SANITY_BOUNDS,
    PRICE_SANITY_MAX_DEVIATION_BPS,
)

logger = logging.getLogger("core.validators")

# =============================================================================
# CRITICAL CONSTANT - MUST BE 10000
# =============================================================================

MAX_DEVIATION_BPS_CAP = 10000


# =============================================================================
# ANCHOR QUOTE DATACLASS
# =============================================================================

@dataclass(frozen=True)
class AnchorQuote:
    """
    Quote that can be used as anchor.
    
    CONTRACT: dex_id is REQUIRED.
    """
    dex_id: str  # REQUIRED
    price: Decimal
    fee: int
    pool_address: str
    block_number: int
    
    timestamp: Optional[int] = None
    token_in: str = ""
    token_out: str = ""
    
    def __post_init__(self):
        if not self.dex_id:
            raise ValueError("AnchorQuote.dex_id is required")
    
    @property
    def is_from_anchor_dex(self) -> bool:
        """Check if quote is from priority anchor DEX."""
        for priority in ANCHOR_DEX_PRIORITY:
            if self.dex_id.startswith(priority):
                return True
        return False


# =============================================================================
# DEVIATION CALCULATION (Decimal math, ROUND_HALF_UP)
# =============================================================================

def calculate_deviation_bps(
    price: Decimal,
    anchor: Decimal,
    cap: int = MAX_DEVIATION_BPS_CAP,
) -> Tuple[int, int, bool]:
    """
    Calculate price deviation in basis points.
    
    Args:
        price: Price to check
        anchor: Anchor/reference price
        cap: Maximum cap for deviation (default 10000)
    
    Returns:
        (capped_bps, raw_bps, was_capped)
        
    CONTRACT:
    - Uses Decimal math with ROUND_HALF_UP
    - 5% deviation → exactly 500 bps
    - raw > cap → returns (cap, raw, True)
    """
    if anchor <= 0:
        raise ValueError(f"Anchor must be positive, got: {anchor}")
    
    # Ensure we're working with Decimal
    price = Decimal(str(price))
    anchor = Decimal(str(anchor))
    
    # Calculate deviation using pure Decimal math
    deviation_ratio = abs(price - anchor) / anchor
    raw_bps_decimal = deviation_ratio * Decimal("10000")
    
    # Round to nearest integer with ROUND_HALF_UP
    raw_bps = int(raw_bps_decimal.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    
    # Apply cap
    if raw_bps > cap:
        return cap, raw_bps, True
    
    return raw_bps, raw_bps, False


# =============================================================================
# PRICE NORMALIZATION (no inversion, quote per base)
# =============================================================================

def normalize_price(
    amount_in_wei: int,
    amount_out_wei: int,
    decimals_in: int,
    decimals_out: int,
    token_in: str,
    token_out: str,
    *,
    bounds: Optional[Dict] = None,
) -> Tuple[Decimal, Dict[str, Any]]:
    """
    Normalize price from raw amounts.
    
    Returns:
        (normalized_price, diagnostics)
        
    CONTRACT:
    - Price = quote_token per 1 base_token (ALWAYS)
    - inversion_applied = False (ALWAYS)
    - suspect_quote flag for out-of-range prices
    """
    if bounds is None:
        bounds = PRICE_SANITY_BOUNDS
    
    diagnostics: Dict[str, Any] = {
        "amount_in_wei": str(amount_in_wei),
        "amount_out_wei": str(amount_out_wei),
        "decimals_in": decimals_in,
        "decimals_out": decimals_out,
        "token_in": token_in,
        "token_out": token_out,
        "numeraire_side": f"{token_out}_per_{token_in}",
        "inversion_applied": False,  # ALWAYS False
    }
    
    # Normalize amounts
    if decimals_in >= 0:
        in_normalized = Decimal(amount_in_wei) / Decimal(10 ** decimals_in)
    else:
        in_normalized = Decimal("0")
    
    if decimals_out >= 0:
        out_normalized = Decimal(amount_out_wei) / Decimal(10 ** decimals_out)
    else:
        out_normalized = Decimal("0")
    
    diagnostics["in_normalized"] = str(in_normalized)
    diagnostics["out_normalized"] = str(out_normalized)
    
    # Handle zero input
    if in_normalized <= 0:
        diagnostics["error"] = "zero_input"
        diagnostics["raw_price_quote_per_base"] = None
        diagnostics["suspect_quote"] = True
        diagnostics["suspect_reason"] = "zero_input"
        return Decimal("0"), diagnostics
    
    # Calculate price: quote per base (NO INVERSION)
    raw_price = out_normalized / in_normalized
    diagnostics["raw_price_quote_per_base"] = str(raw_price)
    
    if raw_price > 0:
        diagnostics["raw_price_base_per_quote"] = str(Decimal("1") / raw_price)
    
    diagnostics["final_price_used_for_sanity"] = str(raw_price)
    
    # Check for suspect quotes
    pair_key = (token_in, token_out)
    pair_bounds = bounds.get(pair_key)
    
    diagnostics["suspect_quote"] = False
    diagnostics["suspect_reason"] = None
    
    if pair_bounds:
        diagnostics["expected_range"] = [str(pair_bounds["min"]), str(pair_bounds["max"])]
        
        if raw_price < pair_bounds["min"] / Decimal("10"):
            diagnostics["suspect_quote"] = True
            diagnostics["suspect_reason"] = "way_below_expected"
            diagnostics["possible_cause"] = "bad_pool_mapping_or_adapter_error"
        elif raw_price > pair_bounds["max"] * Decimal("10"):
            diagnostics["suspect_quote"] = True
            diagnostics["suspect_reason"] = "way_above_expected"
            diagnostics["possible_cause"] = "bad_pool_mapping_or_adapter_error"
    
    return raw_price, diagnostics


# =============================================================================
# ANCHOR SELECTION
# =============================================================================

def select_anchor(
    quotes: List[AnchorQuote],
    pair: str,
    anchor_priority: Tuple[str, ...] = ANCHOR_DEX_PRIORITY,
) -> Tuple[Optional[AnchorQuote], Dict[str, Any]]:
    """
    Select best anchor quote from list.
    
    CONTRACT:
    - Priority by dex_id (allows prefix match: uniswap_v3_*)
    - Falls back to median if no priority match
    - Falls back to hardcoded bounds if no quotes
    """
    diagnostics: Dict[str, Any] = {
        "pair": pair,
        "quotes_count": len(quotes),
        "anchor_priority": list(anchor_priority),
    }
    
    # Parse pair for bounds lookup
    parts = pair.replace("/", "_").replace("-", "_").upper().split("_")
    pair_key = (parts[0], parts[1]) if len(parts) >= 2 else None
    
    bounds = PRICE_SANITY_BOUNDS.get(pair_key) if pair_key else None
    
    if not quotes:
        if bounds:
            diagnostics["source"] = "hardcoded_bounds"
            diagnostics["anchor_price"] = str(bounds["anchor"])
            return None, diagnostics
        diagnostics["source"] = "no_quotes_no_bounds"
        return None, diagnostics
    
    # Filter obviously bad quotes
    if bounds:
        min_thresh = bounds["min"] / Decimal("2")
        max_thresh = bounds["max"] * Decimal("2")
        reasonable = [q for q in quotes if min_thresh <= q.price <= max_thresh]
        if reasonable:
            quotes = reasonable
            diagnostics["filtered_to_reasonable"] = len(quotes)
    
    # Try priority DEXes (supports prefix match)
    for priority in anchor_priority:
        for q in quotes:
            if q.dex_id.startswith(priority) and q.price > 0:
                diagnostics["source"] = "anchor_dex"
                diagnostics["selected_dex_id"] = q.dex_id
                diagnostics["anchor_price"] = str(q.price)
                return q, diagnostics
    
    # Fallback to median
    valid_quotes = [q for q in quotes if q.price > 0]
    if valid_quotes:
        sorted_quotes = sorted(valid_quotes, key=lambda q: q.price)
        n = len(sorted_quotes)
        median_quote = sorted_quotes[n // 2]
        diagnostics["source"] = "median_quotes"
        diagnostics["median_index"] = n // 2
        diagnostics["anchor_price"] = str(median_quote.price)
        return median_quote, diagnostics
    
    # Last resort: hardcoded bounds
    if bounds:
        diagnostics["source"] = "hardcoded_bounds_fallback"
        diagnostics["anchor_price"] = str(bounds["anchor"])
        return None, diagnostics
    
    diagnostics["source"] = "no_valid_anchor"
    return None, diagnostics


# =============================================================================
# PRICE SANITY CHECK
# =============================================================================

def check_price_sanity(
    price: Decimal,
    anchor_price: Decimal,
    pair: str,
    dex_id: str,
    fee_tier: Optional[int] = None,
    *,
    max_deviation_bps: int = PRICE_SANITY_MAX_DEVIATION_BPS,
    anchor_source: Optional[str] = None,
    pool_address: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, int, Optional[str], Dict[str, Any]]:
    """
    Check if price passes sanity check.
    
    Args:
        price: Price to check
        anchor_price: Reference/anchor price
        pair: Pair string
        dex_id: DEX identifier
        fee_tier: Optional fee tier
        max_deviation_bps: Maximum allowed deviation
        anchor_source: Optional anchor source description
        pool_address: Optional pool address
        config: Optional config dict (for backward compat)
    
    Returns:
        (passed, deviation_bps, error_message, diagnostics)
        
    CONTRACT:
    - deviation_bps_capped = True if raw > cap
    - inversion_applied = False (ALWAYS)
    - anchor_source included if provided
    """
    # Handle legacy config parameter
    if config is not None:
        if config.get("price_sanity_enabled") is False:
            return True, 0, None, {"sanity_check": "disabled", "inversion_applied": False}
        max_deviation_bps = config.get("price_sanity_max_deviation_bps", max_deviation_bps)
    
    diagnostics: Dict[str, Any] = {
        "pair": pair,
        "dex_id": dex_id,
        "implied_price": str(price),
        "anchor_price": str(anchor_price),
        "max_deviation_bps": max_deviation_bps,
        "inversion_applied": False,  # ALWAYS False
    }
    
    if fee_tier is not None:
        diagnostics["fee_tier"] = fee_tier
    if pool_address:
        diagnostics["pool_address"] = pool_address
    if anchor_source:
        diagnostics["anchor_source"] = anchor_source
    
    # Ensure Decimal
    price = Decimal(str(price))
    anchor_price = Decimal(str(anchor_price))
    
    # Check for invalid prices
    if price <= 0:
        diagnostics["error"] = "zero_or_negative_price"
        diagnostics["deviation_bps"] = 0
        diagnostics["deviation_bps_raw"] = 0
        diagnostics["deviation_bps_capped"] = False
        return False, 0, "Zero or negative price", diagnostics
    
    if anchor_price <= 0:
        diagnostics["error"] = "invalid_anchor"
        diagnostics["deviation_bps"] = 0
        diagnostics["deviation_bps_raw"] = 0
        diagnostics["deviation_bps_capped"] = False
        return False, 0, "Invalid anchor price", diagnostics
    
    # Calculate deviation
    try:
        dev_bps, dev_raw, capped = calculate_deviation_bps(price, anchor_price, MAX_DEVIATION_BPS_CAP)
    except ValueError as e:
        diagnostics["error"] = str(e)
        diagnostics["deviation_bps"] = 0
        diagnostics["deviation_bps_raw"] = 0
        diagnostics["deviation_bps_capped"] = False
        return False, 0, str(e), diagnostics
    
    diagnostics["deviation_bps"] = dev_bps
    diagnostics["deviation_bps_raw"] = dev_raw
    diagnostics["deviation_bps_capped"] = capped
    
    # Check against threshold
    if dev_bps > max_deviation_bps:
        diagnostics["error"] = "deviation_exceeded"
        error_msg = f"Deviation {dev_bps}bps > max {max_deviation_bps}bps"
        if capped:
            error_msg += f" (raw: {dev_raw}bps, capped to {MAX_DEVIATION_BPS_CAP})"
        return False, dev_bps, error_msg, diagnostics
    
    diagnostics["sanity_check"] = "passed"
    return True, dev_bps, None, diagnostics


# =============================================================================
# LEGACY COMPATIBILITY WRAPPER (for run_scan_real.py)
# =============================================================================

def check_price_sanity_legacy(
    token_in: str,
    token_out: str,
    price: Decimal,
    config: Dict[str, Any],
    dynamic_anchor: Optional[Decimal] = None,
    fee: int = 0,
    dex_id: Optional[str] = None,
    pool_address: Optional[str] = None,
    anchor_source: Optional[str] = None,
    **kwargs,
) -> Tuple[bool, Optional[int], Optional[str], Dict[str, Any]]:
    """Legacy wrapper for check_price_sanity."""
    pair = f"{token_in}/{token_out}"
    
    # Get anchor price
    if dynamic_anchor and dynamic_anchor > 0:
        anchor = dynamic_anchor
        source = anchor_source or "dynamic"
    else:
        pair_key = (token_in, token_out)
        bounds = PRICE_SANITY_BOUNDS.get(pair_key)
        if bounds:
            anchor = bounds.get("anchor", (bounds["min"] + bounds["max"]) / 2)
            source = "hardcoded_bounds"
        else:
            return True, None, None, {
                "sanity_check": "no_anchor_available",
                "inversion_applied": False,
            }
    
    return check_price_sanity(
        price=price,
        anchor_price=anchor,
        pair=pair,
        dex_id=dex_id or "unknown",
        fee_tier=fee,
        max_deviation_bps=config.get("price_sanity_max_deviation_bps", PRICE_SANITY_MAX_DEVIATION_BPS),
        anchor_source=source,
        pool_address=pool_address,
        config=config,
    )


# =============================================================================
# HELPERS
# =============================================================================

def is_anchor_dex(dex_id: str) -> bool:
    """Check if dex_id is a priority anchor DEX."""
    for priority in ANCHOR_DEX_PRIORITY:
        if dex_id.startswith(priority):
            return True
    return False


def get_anchor_dex_priority(dex_id: str) -> int:
    """Get priority index for dex_id (999 if not found)."""
    for i, priority in enumerate(ANCHOR_DEX_PRIORITY):
        if dex_id.startswith(priority):
            return i
    return 999
