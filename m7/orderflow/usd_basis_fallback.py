"""E1.69 reviewer fix step 7 — USD basis fallback paths.

When a candidate trade's token_in is not a stablecoin and not WETH, the
primary `_quote_implied_size_usd` path returns ``None`` and the trade
is rejected as ``USD_BASIS_MISSING`` even though the swap is otherwise
profitable.  This module supplies a lightweight, fail-soft fallback:
operators may seed approximate USD anchors for production tokens via
``ARBY_USD_BASIS_FALLBACK_JSON`` (path to JSON file) **or** the env
var ``ARBY_USD_BASIS_FALLBACK`` (inline JSON object mapping symbol to
USD price).

The module is pure — no I/O at import time.  Callers explicitly invoke
``load_fallback_table()`` at startup and ``fallback_usd_for_amount(...)``
when the primary path fails.

Default table covers the highest-volume Base production assets that
the 2h soak observed bouncing on USD_BASIS_MISSING:

- AERO  ~ $0.50
- VIRTUAL ~ $1.50
- CBBTC ~ $66000
- BRETT ~ $0.05

These defaults are intentionally rough; operators should override
them via the env vars above for live trading.
"""

from __future__ import annotations

import json
import os
from typing import Dict, Optional


_DEFAULT_TABLE: Dict[str, float] = {
    "AERO": 0.50,
    "VIRTUAL": 1.50,
    "CBBTC": 66000.0,
    "BRETT": 0.05,
    "DEGEN": 0.005,
    "TOSHI": 0.0001,
}


def load_fallback_table() -> Dict[str, float]:
    """Return symbol -> USD price overrides, fail-soft."""
    out = dict(_DEFAULT_TABLE)
    inline = os.environ.get("ARBY_USD_BASIS_FALLBACK", "").strip()
    if inline:
        try:
            obj = json.loads(inline)
            if isinstance(obj, dict):
                for k, v in obj.items():
                    try:
                        out[str(k).upper()] = float(v)
                    except (TypeError, ValueError):
                        continue
        except Exception:
            pass
    path = os.environ.get("ARBY_USD_BASIS_FALLBACK_JSON", "").strip()
    if path and os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                obj = json.load(fh)
            if isinstance(obj, dict):
                for k, v in obj.items():
                    try:
                        out[str(k).upper()] = float(v)
                    except (TypeError, ValueError):
                        continue
        except Exception:
            pass
    return out


def fallback_usd_for_amount(
    *,
    symbol: Optional[str],
    amount_wei: int,
    decimals: Optional[int],
    table: Optional[Dict[str, float]] = None,
) -> Optional[float]:
    """Approximate USD value of ``amount_wei`` using fallback table.

    Returns ``None`` when no fallback price is known.  Intentionally
    keeps a 6-decimal precision so it behaves like the primary
    ``_quote_implied_size_usd`` rounding semantics.
    """
    if not symbol or amount_wei <= 0:
        return None
    sym = symbol.upper()
    src = table if table is not None else load_fallback_table()
    price = src.get(sym)
    if price is None or price <= 0:
        return None
    dec = decimals if decimals is not None else 18
    try:
        return round((amount_wei / (10 ** dec)) * float(price), 6)
    except (TypeError, ValueError, OverflowError):
        return None


__all__ = ["load_fallback_table", "fallback_usd_for_amount"]
