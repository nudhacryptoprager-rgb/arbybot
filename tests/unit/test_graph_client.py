# PATH: tests/unit/test_graph_client.py
"""
Unit tests for discovery/graph_client.py — Graph API pool discovery.
"""

import pytest
from unittest.mock import patch, MagicMock

from discovery.graph_client import (
    GraphPool,
    _get_graph_url,
    graph_pools_to_intent_pairs,
    discover_graph_pools,
    _HOSTED_FALLBACKS,
)


class TestGraphPool:
    def test_pair_key_canonical(self):
        pool = GraphPool(
            chain="base", protocol="uniswap_v3", pool_address="0xabc",
            token0_address="0x1", token0_symbol="WETH", token0_decimals=18,
            token1_address="0x2", token1_symbol="USDC", token1_decimals=6,
            fee_tier=500, tvl_usd=1_000_000, volume_usd_24h=500_000,
        )
        # Canonical: sorted alphabetically
        assert pool.pair_key == "USDC/WETH"

    def test_pair_key_already_sorted(self):
        pool = GraphPool(
            chain="base", protocol="uniswap_v3", pool_address="0xabc",
            token0_address="0x1", token0_symbol="AERO", token0_decimals=18,
            token1_address="0x2", token1_symbol="USDC", token1_decimals=6,
            fee_tier=3000, tvl_usd=500_000, volume_usd_24h=100_000,
        )
        assert pool.pair_key == "AERO/USDC"


class TestGetGraphUrl:
    def test_hosted_fallback_no_api_key(self):
        with patch.dict("os.environ", {}, clear=True):
            url = _get_graph_url("base", "uniswap_v3")
            assert url is not None
            assert "studio.thegraph.com" in url or "gateway.thegraph.com" in url

    def test_with_api_key(self):
        with patch.dict("os.environ", {"GRAPH_API_KEY": "test-key-123"}):
            url = _get_graph_url("base", "uniswap_v3")
            assert url is not None
            assert "test-key-123" in url
            assert "gateway.thegraph.com" in url

    def test_unknown_chain(self):
        url = _get_graph_url("unknown_chain", "uniswap_v3")
        assert url is None

    def test_unknown_protocol(self):
        url = _get_graph_url("base", "unknown_dex")
        assert url is None


class TestGraphPoolsToIntentPairs:
    def test_basic_conversion(self):
        pools = [
            GraphPool(
                chain="base", protocol="uniswap_v3", pool_address="0x1",
                token0_address="0xa", token0_symbol="WETH", token0_decimals=18,
                token1_address="0xb", token1_symbol="USDC", token1_decimals=6,
                fee_tier=500, tvl_usd=1_000_000, volume_usd_24h=500_000,
            ),
        ]
        lines = graph_pools_to_intent_pairs(pools)
        assert "base:USDC/WETH" in lines

    def test_deduplication(self):
        """Same pair from different fee tiers should deduplicate."""
        pools = [
            GraphPool(
                chain="base", protocol="uniswap_v3", pool_address="0x1",
                token0_address="0xa", token0_symbol="WETH", token0_decimals=18,
                token1_address="0xb", token1_symbol="USDC", token1_decimals=6,
                fee_tier=500, tvl_usd=1_000_000, volume_usd_24h=500_000,
            ),
            GraphPool(
                chain="base", protocol="uniswap_v3", pool_address="0x2",
                token0_address="0xa", token0_symbol="WETH", token0_decimals=18,
                token1_address="0xb", token1_symbol="USDC", token1_decimals=6,
                fee_tier=3000, tvl_usd=800_000, volume_usd_24h=400_000,
            ),
        ]
        lines = graph_pools_to_intent_pairs(pools)
        assert len(lines) == 1

    def test_known_tokens_filter(self):
        """Only include pools where both tokens are known."""
        pools = [
            GraphPool(
                chain="base", protocol="uniswap_v3", pool_address="0x1",
                token0_address="0xa", token0_symbol="WETH", token0_decimals=18,
                token1_address="0xb", token1_symbol="USDC", token1_decimals=6,
                fee_tier=500, tvl_usd=1_000_000, volume_usd_24h=500_000,
            ),
            GraphPool(
                chain="base", protocol="uniswap_v3", pool_address="0x2",
                token0_address="0xc", token0_symbol="UNKNOWN", token0_decimals=18,
                token1_address="0xb", token1_symbol="USDC", token1_decimals=6,
                fee_tier=500, tvl_usd=500_000, volume_usd_24h=200_000,
            ),
        ]
        known = {"WETH", "USDC"}
        lines = graph_pools_to_intent_pairs(pools, known_tokens=known)
        assert len(lines) == 1
        assert "base:USDC/WETH" in lines

    def test_empty_symbol_skipped(self):
        pools = [
            GraphPool(
                chain="base", protocol="uniswap_v3", pool_address="0x1",
                token0_address="0xa", token0_symbol="", token0_decimals=18,
                token1_address="0xb", token1_symbol="USDC", token1_decimals=6,
                fee_tier=500, tvl_usd=1_000_000, volume_usd_24h=500_000,
            ),
        ]
        lines = graph_pools_to_intent_pairs(pools)
        assert len(lines) == 0


class TestDiscoverGraphPools:
    @patch("discovery.graph_client._query_uniswap_v3_pools")
    @patch("discovery.graph_client._query_aerodrome_pools")
    def test_combines_protocols(self, mock_aero, mock_uni):
        mock_uni.return_value = [
            GraphPool(
                chain="base", protocol="uniswap_v3", pool_address="0x1",
                token0_address="0xa", token0_symbol="WETH", token0_decimals=18,
                token1_address="0xb", token1_symbol="USDC", token1_decimals=6,
                fee_tier=500, tvl_usd=2_000_000, volume_usd_24h=1_000_000,
            ),
        ]
        mock_aero.return_value = [
            GraphPool(
                chain="base", protocol="aerodrome", pool_address="0x2",
                token0_address="0xa", token0_symbol="WETH", token0_decimals=18,
                token1_address="0xc", token1_symbol="AERO", token1_decimals=18,
                fee_tier=0, tvl_usd=500_000, volume_usd_24h=200_000,
            ),
        ]
        pools = discover_graph_pools("base")
        assert len(pools) == 2
        # Should be sorted by TVL descending
        assert pools[0].tvl_usd >= pools[1].tvl_usd

    @patch("discovery.graph_client._query_uniswap_v3_pools")
    @patch("discovery.graph_client._query_aerodrome_pools")
    def test_deduplicates_by_address(self, mock_aero, mock_uni):
        same_pool = GraphPool(
            chain="base", protocol="uniswap_v3", pool_address="0xABC",
            token0_address="0xa", token0_symbol="WETH", token0_decimals=18,
            token1_address="0xb", token1_symbol="USDC", token1_decimals=6,
            fee_tier=500, tvl_usd=1_000_000, volume_usd_24h=500_000,
        )
        mock_uni.return_value = [same_pool]
        mock_aero.return_value = [same_pool]
        pools = discover_graph_pools("base")
        assert len(pools) == 1

    def test_unsupported_chain_returns_empty(self):
        pools = discover_graph_pools("unsupported_chain")
        assert pools == []
