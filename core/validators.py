# PATH: core/validators.py
"""Unified validators for ARBY."""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

from core.constants import (
    ANCHOR_DEX_PRIORITY,
    PRICE_SANITY_BOUNDS,
    PRICE_SANITY_MAX_DEVIATION_BPS,
)


@dataclass
class AnchorQuote:
    """Quote that can be used as anchor."""
    dex_id: str  # REQUIRED
    price: Decimal
    fee: int
    pool_address: str
    block_number: int
    
    def __post_init__(self):
        if not self.dex_id:
            raise ValueError("AnchorQuote.dex_id is required")


def check_price_sanity(
    token_in: str,
    token_out: str,
    price: Decimal,
    config: Dict[str, Any],
    dynamic_anchor: Optional[Decimal] = None,
    **kwargs,
) -> Tuple[bool, Optional[int], Optional[str], Dict[str, Any]]:
    """Check price sanity."""
    pair_key = (token_in, token_out)
    bounds = PRICE_SANITY_BOUNDS.get(pair_key)
    max_dev = config.get("price_sanity_max_deviation_bps", PRICE_SANITY_MAX_DEVIATION_BPS)
    
    diagnostics: Dict[str, Any] = {
        "implied_price": str(price),
        "inversion_applied": False,
    }
    
    if not config.get("price_sanity_enabled", True):
        return True, None, None, diagnostics
    
    if price <= 0:
        return False, None, "Zero or negative price", diagnostics
    
    anchor_price = dynamic_anchor
    if not anchor_price and bounds:
        anchor_price = bounds.get("anchor")
    
    if anchor_price is None:
        return True, None, None, diagnostics
    
    deviation = abs(price - anchor_price) / anchor_price * Decimal("10000")
    dev_bps = int(round(deviation))
    
    diagnostics["anchor_price"] = str(anchor_price)
    diagnostics["deviation_bps"] = dev_bps
    
    if dev_bps > max_dev:
        return False, dev_bps, f"Deviation {dev_bps}bps > {max_dev}bps", diagnostics
    
    return True, dev_bps, None, diagnostics
