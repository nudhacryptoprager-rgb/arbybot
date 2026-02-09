# PATH: strategy/compat.py
"""
Compatibility layer for Quote types.

Provides QuoteCompat dataclass and QuoteAdapter for core.models.Quote.
Extracted from run_scan_real.py for modularity.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class QuoteCompat:
    """
    Compatibility Quote dataclass used by integration tests.
    
    Provides legacy signature support while enabling new fields.
    """
    dex_id: str = ""
    pool_address: str = ""
    token_in: str = ""
    token_out: str = ""
    fee: int = 0
    amount_in_wei: int = 0
    amount_out_wei: int = 0
    amount_in_human: str = "0"
    amount_out_human: str = "0"
    price: Any = None
    latency_ms: int = 0
    block_number: int = 0
    rpc_success: bool = True
    gate_passed: bool = True
    # v3 provenance fields (on-chain state markers)
    tick: int | None = None
    sqrt_price_x96: int | None = None


def create_quote_class():
    """
    Create Quote class with compatibility layer.
    
    Returns:
        Quote class (either core.models.Quote with adapter or QuoteCompat)
    """
    try:
        from core.models import Quote as CoreQuote
    except Exception:
        return QuoteCompat
    
    class QuoteAdapter:
        """Adapter that maps legacy kwargs to core.models.Quote."""
        
        def __init__(self, *args, **kwargs):
            # Map legacy kw names to core.models.Quote expected names
            if "dex_id" in kwargs and "dex" not in kwargs:
                kwargs["dex"] = kwargs.pop("dex_id")
            if "fee" in kwargs and "fee_tier" not in kwargs:
                kwargs["fee_tier"] = kwargs.pop("fee")
            if "amount_in_wei" in kwargs and "amount_in" not in kwargs:
                kwargs["amount_in"] = kwargs.pop("amount_in_wei")
            if "amount_out_wei" in kwargs and "amount_out" not in kwargs:
                kwargs["amount_out"] = kwargs.pop("amount_out_wei")

            # Extract scanner-only flags that core Quote may not accept
            self.rpc_success = kwargs.pop("rpc_success", True)
            self.gate_passed = kwargs.pop("gate_passed", True)

            # Ensure price is a string for core Quote
            if "price" in kwargs and not isinstance(kwargs["price"], str):
                try:
                    kwargs["price"] = str(kwargs["price"])
                except Exception:
                    pass

            # Remove legacy human-readable amount fields not accepted by core Quote
            kwargs.pop("amount_in_human", None)
            kwargs.pop("amount_out_human", None)

            # forward positional args/kwargs to core Quote
            self._inner = CoreQuote(*args, **kwargs)

        def __getattr__(self, name):
            return getattr(self._inner, name)

        def to_dict(self):
            try:
                return self._inner.to_dict()
            except Exception:
                return self.__dict__

    return QuoteAdapter


# Export Quote class for use
Quote = create_quote_class()
