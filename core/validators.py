# PATH: core/validators.py
"""
Unified validators for ARBY.

M5_0: Consolidates price sanity logic.

CONTRACTS:

1. PRICE ORIENTATION CONTRACT:
   - Price is ALWAYS "quote_token per 1 base_token"
   - For WETH/USDC: price = USDC per 1 WETH (~2600-3500)

2. DEVIATION FORMULA CONTRACT:
   deviation_bps = int(round(abs(price - anchor) / anchor * 10000))
   CAP: MAX_DEVIATION_BPS_CAP = 10000 (100%)

3. NO INVERSION:
   - We NEVER auto-invert prices
   - inversion_applied is ALWAYS False
   - Low prices (e.g., 8 USDC/WETH) are "suspect_quote" NOT "inverted"

API CONTRACT:
   check_price_sanity() accepts anchor_source (str) for compatibility.
"""

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from core.constants import (
    ANCHOR_DEX_PRIORITY,
    DEFAULT_ANCHOR_DEX,
    PRICE_SANITY_BOUNDS,
    PRICE_SANITY_MAX_DEVIATION_BPS,
)

logger = logging.getLogger("core.validators")

MAX_DEVIATION_BPS_CAP = 10000


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
    
    Returns:
        Tuple of (price, suspect_quote, diagnostics)
    """
    diagnostics: Dict[str, Any] = {
        "amount_in_wei": str(amount_in_wei),
        "amount_out_wei": str(amount_out_wei),
        "decimals_in": decimals_in,
        "decimals_out": decimals_out,
        "token_in": token_in,
        "token_out": token_out,
        "numeraire_side": f"{token_out}_per_{token_in}",
        "inversion_applied": False,  # ALWAYS False - we never invert
    }
    
    in_normalized = Decimal(amount_in_wei) / Decimal(10 ** decimals_in)
    out_normalized = Decimal(amount_out_wei) / Decimal(10 ** decimals_out)
    
    diagnostics["in_normalized"] = str(in_normalized)
    diagnostics["out_normalized"] = str(out_normalized)
    
    if in_normalized <= 0:
        diagnostics["error"] = "zero_input"
        return Decimal("0"), False, diagnostics
    
    raw_price = out_normalized / in_normalized
    diagnostics["raw_price_quote_per_base"] = str(raw_price)
    
    # Check if price looks suspect (NOT "inverted" - just bad data)
    suspect_quote = False
    pair_key = (token_in, token_out)
    bounds = PRICE_SANITY_BOUNDS.get(pair_key)
    
    if bounds:
        diagnostics["expected_range"] = [str(bounds["min"]), str(bounds["max"])]
        
        if raw_price < bounds["min"] / Decimal("10"):
            suspect_quote = True
            diagnostics["suspect_quote"] = True
            diagnostics["suspect_reason"] = "way_below_expected"
            diagnostics["possible_cause"] = "bad_pool_mapping_or_quoter_error"
            logger.warning(
                f"SUSPECT_QUOTE: {token_in}/{token_out} price={raw_price:.6f} "
                f"below expected [{bounds['min']}, {bounds['max']}]"
            )
        elif raw_price > bounds["max"] * Decimal("10"):
            suspect_quote = True
            diagnostics["suspect_quote"] = True
            diagnostics["suspect_reason"] = "way_above_expected"
    
    return raw_price, suspect_quote, diagnostics


def calculate_deviation_bps(
    price: Decimal, 
    anchor: Decimal, 
    cap: int = MAX_DEVIATION_BPS_CAP
) -> Tuple[int, int, bool]:
    """
    Calculate price deviation in basis points.
    
    Returns: (deviation_bps, deviation_bps_raw, was_capped)
    """
    if anchor <= 0:
        raise ValueError(f"Anchor must be positive, got: {anchor}")
    
    deviation = abs(price - anchor) / anchor * Decimal("10000")
    raw_bps = int(round(deviation))
    
    if raw_bps > cap:
        return cap, raw_bps, True
    return raw_bps, raw_bps, False


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
        return self.dex_id in ANCHOR_DEX_PRIORITY


def select_anchor(
    quotes: List[AnchorQuote],
    pair_key: Tuple[str, str],
) -> Optional[Tuple[Decimal, Dict[str, Any]]]:
    """Select best anchor from available quotes."""
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
    
    # Priority 1: anchor_dex
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
    
    # Priority 2: median
    valid_prices = sorted([q.price for q in quotes if q.price > 0])
    if valid_prices:
        n = len(valid_prices)
        median_price = valid_prices[n // 2] if n % 2 == 1 else (valid_prices[n // 2 - 1] + valid_prices[n // 2]) / 2
        return median_price, {"source": "median_quotes", "quotes_count": n}
    
    if bounds:
        return bounds.get("anchor", (bounds["min"] + bounds["max"]) / 2), {"source": "hardcoded_bounds"}
    
    return None


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
    anchor_source: Optional[str] = None,
) -> Tuple[bool, Optional[int], Optional[str], Dict[str, Any]]:
    """Check price sanity with DYNAMIC anchor."""
    pair_key = (token_in, token_out)
    bounds = PRICE_SANITY_BOUNDS.get(pair_key)
    max_deviation_bps = config.get("price_sanity_max_deviation_bps", PRICE_SANITY_MAX_DEVIATION_BPS)
    
    diagnostics: Dict[str, Any] = {
        "implied_price": str(price),
        "token_in": token_in,
        "token_out": token_out,
        "numeraire_side": f"{token_out}_per_{token_in}",
        "token_in_decimals": decimals_in,
        "token_out_decimals": decimals_out,
        "pool_fee": fee,
        "inversion_applied": False,  # ALWAYS False
    }
    
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
    
    # Calculate raw price for diagnostics
    if amount_in_wei and amount_out_wei and amount_in_wei > 0:
        in_norm = Decimal(amount_in_wei) / Decimal(10 ** decimals_in)
        out_norm = Decimal(amount_out_wei) / Decimal(10 ** decimals_out)
        if in_norm > 0:
            diagnostics["raw_price_quote_per_base"] = str(out_norm / in_norm)
    
    if not config.get("price_sanity_enabled", True):
        diagnostics["sanity_check"] = "disabled"
        return True, None, None, diagnostics
    
    if price <= 0:
        diagnostics["error"] = "zero_or_negative_price"
        return False, None, "Zero or negative price", diagnostics
    
    # Determine anchor
    anchor_price: Optional[Decimal] = None
    
    if dynamic_anchor and dynamic_anchor > 0:
        anchor_price = dynamic_anchor
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
    
    # Calculate deviation
    deviation_bps, deviation_bps_raw, was_capped = calculate_deviation_bps(price, anchor_price)
    
    diagnostics["deviation_bps"] = deviation_bps
    diagnostics["deviation_bps_raw"] = deviation_bps_raw
    diagnostics["deviation_bps_capped"] = was_capped
    diagnostics["max_deviation_bps"] = max_deviation_bps
    
    # Flag suspect quote (info only)
    if bounds and price < bounds["min"] / Decimal("10"):
        diagnostics["suspect_quote"] = True
        diagnostics["suspect_reason"] = "way_below_expected"
    elif bounds and price > bounds["max"] * Decimal("10"):
        diagnostics["suspect_quote"] = True
        diagnostics["suspect_reason"] = "way_above_expected"
    
    if deviation_bps > max_deviation_bps:
        if bounds and price < bounds["min"]:
            diagnostics["error"] = "below_minimum"
            error_msg = f"Price {price:.4f} below minimum {bounds['min']}"
        elif bounds and price > bounds["max"]:
            diagnostics["error"] = "above_maximum"
            error_msg = f"Price {price:.4f} above maximum {bounds['max']}"
        else:
            diagnostics["error"] = "deviation_exceeded"
            error_msg = f"Deviation {deviation_bps}bps exceeds max {max_deviation_bps}bps"
        return False, deviation_bps, error_msg, diagnostics
    
    diagnostics["sanity_check"] = "passed"
    return True, deviation_bps, None, diagnostics


def is_anchor_dex(dex_id: str) -> bool:
    return dex_id in ANCHOR_DEX_PRIORITY


def get_anchor_dex_priority(dex_id: str) -> int:
    try:
        return ANCHOR_DEX_PRIORITY.index(dex_id)
    except ValueError:
        return 999
