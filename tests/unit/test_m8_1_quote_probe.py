"""M8.1 quote negative cache and productive metrics."""
from __future__ import annotations

from m8_1.stable_anchor.quote_negative_cache import QuoteNegativeCache, quote_cache_key


def test_quote_negative_cache_hit():
    cache = QuoteNegativeCache(ttl_s=60.0)
    key = quote_cache_key(
        route_id="uniswap_v3:f500",
        quoter="0x" + "c" * 40,
        token_in="0x" + "a" * 40,
        token_out="0x" + "b" * 40,
        size_usd=50.0,
        fee=500,
    )
    cache.put(key, "QUOTE_REVERT")
    assert cache.get(key) == "QUOTE_REVERT"
    assert cache.stats()["hits"] == 1
