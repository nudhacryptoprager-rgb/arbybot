"""Unit tests for the edge-level TTL quote cache in M9 quoter.

Step 9 (GPT directive): Add TTLCache[edge_key → QuoteResult] keyed by
(pool_address_lower, token_in_addr_lower, amount_in) with TTL ~2 s.
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from m9.graph_arb.quoter import (
    _EdgeQuoteCache,
    _edge_cache_key,
    _probe_leg,
    edge_quote_cache,
    BACKEND_RAW_HTTP,
    BACKEND_DIRECT_HTTP,
)
from m9.graph_arb.models import GraphEdge
from m8_1.stable_anchor.pairs import TokenInfo
from m8_1.stable_anchor.pool_discovery import DexRoute
from m8_1.stable_anchor.quote_probe import QuoteResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_edge(pool_address: str = "0xpool0000000000000000000000000000000000001") -> GraphEdge:
    return GraphEdge(
        token_in_sym="USDC",
        token_out_sym="WETH",
        token_in_addr="0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
        token_out_addr="0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
        token_in_decimals=6,
        token_out_decimals=18,
        route_id="route_usdc_weth",
        dex_id="uniswap_v3",
        adapter_type="uniswap_v3",
        fee=500,
        tick_spacing=10,
        quoter_addr="0xdeadbeef" + "0" * 32,
        pool_address=pool_address,
        fee_bps=0.05,
        factory_class="uniswap_v3",
        pair_id="USDC_WETH",
    )


def _make_route() -> DexRoute:
    return DexRoute(
        dex_id="uniswap_v3",
        adapter_type="uniswap_v3",
        quoter="0xdeadbeef" + "0" * 32,
        fee=500,
        tick_spacing=10,
        curve_coin0_sym=None,
    )


def _make_token(sym: str, addr: str, decimals: int) -> TokenInfo:
    return TokenInfo(symbol=sym, address=addr, decimals=decimals)


def _make_quote_result(ok: bool = True, amount_out: int = 500_000) -> QuoteResult:
    return QuoteResult(
        route_id="route_usdc_weth",
        size_usd=1000.0,
        amount_in=1_000_000,
        amount_out=amount_out,
        ok=ok,
        reject_reason=None if ok else "QUOTE_REVERT",
        gas_estimate=None,
        raw_error=None,
    )


# ---------------------------------------------------------------------------
# _EdgeQuoteCache unit tests
# ---------------------------------------------------------------------------

class TestEdgeQuoteCacheBasic:
    def test_get_miss_returns_none(self):
        cache = _EdgeQuoteCache(ttl_s=2.0)
        assert cache.get(("0xpool", "0xtoken", 1000)) is None

    def test_put_then_get_returns_result(self):
        cache = _EdgeQuoteCache(ttl_s=2.0)
        result = _make_quote_result()
        key = ("0xpool", "0xtoken", 1000)
        cache.put(key, result)
        assert cache.get(key) is result

    def test_expired_entry_returns_none(self):
        cache = _EdgeQuoteCache(ttl_s=0.05)  # 50 ms TTL
        result = _make_quote_result()
        key = ("0xpool", "0xtoken", 1000)
        cache.put(key, result)
        time.sleep(0.1)  # wait for expiry
        assert cache.get(key) is None

    def test_clear_removes_all_entries(self):
        cache = _EdgeQuoteCache(ttl_s=5.0)
        cache.put(("a", "b", 1), _make_quote_result())
        cache.put(("c", "d", 2), _make_quote_result())
        assert cache.size() == 2
        cache.clear()
        assert cache.size() == 0

    def test_size_returns_live_entries(self):
        cache = _EdgeQuoteCache(ttl_s=5.0)
        assert cache.size() == 0
        cache.put(("p1", "t1", 100), _make_quote_result())
        assert cache.size() == 1

    def test_different_amounts_are_different_keys(self):
        cache = _EdgeQuoteCache(ttl_s=5.0)
        r1 = _make_quote_result(amount_out=100)
        r2 = _make_quote_result(amount_out=200)
        cache.put(("0xp", "0xt", 100), r1)
        cache.put(("0xp", "0xt", 200), r2)
        assert cache.get(("0xp", "0xt", 100)) is r1
        assert cache.get(("0xp", "0xt", 200)) is r2

    def test_keys_are_lowercase(self):
        """Cache key helper must normalise to lowercase."""
        edge = _make_edge(pool_address="0xPOOL000000000000000000000000000000000001")
        key = _edge_cache_key(edge, 1_000_000)
        pool_in_key, token_in_key, _ = key
        assert pool_in_key == pool_in_key.lower()
        assert token_in_key == token_in_key.lower()


# ---------------------------------------------------------------------------
# _probe_leg cache integration tests
# ---------------------------------------------------------------------------

class TestProbeLegCacheIntegration:
    """Verify that _probe_leg reads from / writes to edge_quote_cache."""

    def setup_method(self):
        edge_quote_cache.clear()

    def teardown_method(self):
        edge_quote_cache.clear()

    def test_cache_hit_skips_rpc(self):
        """Second call with same edge+amount must NOT call the backend again."""
        edge = _make_edge()
        route = _make_route()
        tok_in = _make_token("USDC", edge.token_in_addr, 6)
        tok_out = _make_token("WETH", edge.token_out_addr, 18)
        cached_result = _make_quote_result(amount_out=500_000)
        amount_in = 1_000_000
        key = _edge_cache_key(edge, amount_in)
        edge_quote_cache.put(key, cached_result)

        # _probe_leg should return the cached result without calling any backend
        with patch("m9.graph_arb.quoter.probe_quote") as mock_probe:
            result = _probe_leg(
                w3=None, route=route, token_in=tok_in, token_out=tok_out,
                amount_in=amount_in, quote_backend=BACKEND_DIRECT_HTTP,
                edge=edge, use_cache=True,
            )
        mock_probe.assert_not_called()
        assert result is cached_result

    def test_cache_miss_calls_backend_and_stores(self):
        """On cache miss, backend is called and result is stored."""
        edge = _make_edge()
        route = _make_route()
        tok_in = _make_token("USDC", edge.token_in_addr, 6)
        tok_out = _make_token("WETH", edge.token_out_addr, 18)
        fresh_result = _make_quote_result(amount_out=987_654)
        amount_in = 1_000_000

        with patch("m9.graph_arb.quoter.probe_quote", return_value=fresh_result) as mock_probe:
            result = _probe_leg(
                w3=MagicMock(), route=route, token_in=tok_in, token_out=tok_out,
                amount_in=amount_in, quote_backend=BACKEND_DIRECT_HTTP,
                edge=edge, use_cache=True,
            )
        mock_probe.assert_called_once()
        assert result is fresh_result
        # verify stored in cache
        key = _edge_cache_key(edge, amount_in)
        assert edge_quote_cache.get(key) is fresh_result

    def test_use_cache_false_always_calls_backend(self):
        """use_cache=False must bypass cache even if entry exists."""
        edge = _make_edge()
        route = _make_route()
        tok_in = _make_token("USDC", edge.token_in_addr, 6)
        tok_out = _make_token("WETH", edge.token_out_addr, 18)
        stale = _make_quote_result(amount_out=111)
        fresh = _make_quote_result(amount_out=222)
        amount_in = 1_000_000

        key = _edge_cache_key(edge, amount_in)
        edge_quote_cache.put(key, stale)

        with patch("m9.graph_arb.quoter.probe_quote", return_value=fresh):
            result = _probe_leg(
                w3=MagicMock(), route=route, token_in=tok_in, token_out=tok_out,
                amount_in=amount_in, quote_backend=BACKEND_DIRECT_HTTP,
                edge=edge, use_cache=False,
            )
        assert result is fresh

    def test_no_edge_no_cache_interaction(self):
        """When edge=None, cache is never consulted or written."""
        route = _make_route()
        tok_in = _make_token("USDC", "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48", 6)
        tok_out = _make_token("WETH", "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2", 18)
        fresh = _make_quote_result()

        with patch("m9.graph_arb.quoter.probe_quote", return_value=fresh):
            result = _probe_leg(
                w3=MagicMock(), route=route, token_in=tok_in, token_out=tok_out,
                amount_in=1_000_000, quote_backend=BACKEND_DIRECT_HTTP,
                edge=None, use_cache=True,
            )
        assert result is fresh
        assert edge_quote_cache.size() == 0  # nothing stored

    def test_module_cache_is_shared_instance(self):
        """edge_quote_cache should be a module-level shared _EdgeQuoteCache instance."""
        assert isinstance(edge_quote_cache, _EdgeQuoteCache)
