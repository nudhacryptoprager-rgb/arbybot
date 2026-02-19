"""
Unit tests for discovery/index_factories.py pool discovery (v2.3.2).

These tests verify the factory-based pool discovery and verification logic.
"""
import os
import pytest
from unittest.mock import patch, MagicMock

from discovery.index_factories import (
    PoolIndex,
    DiscoveredPool,
    get_factory_address,
    FACTORY_ADDRESSES,
    V3_FEE_TIERS,
    verify_pool_exists,
    validate_pool_address,
    count_discovery_candidates,
)


class TestPoolIndex:
    """Tests for PoolIndex class."""

    def test_add_and_get_pool(self):
        """Test adding and retrieving pools."""
        index = PoolIndex()
        
        pool = DiscoveredPool(
            chain="arbitrum_one",
            dex="uniswap_v3",
            address="0x1234",
            token0="0xabc",
            token1="0xdef",
            token0_symbol="WETH",
            token1_symbol="USDC",
            fee_tier=500,
        )
        
        index.add_pool(pool)
        
        pools = index.get_pools("arbitrum_one")
        assert len(pools) == 1
        assert pools[0].address == "0x1234"
        assert pools[0].fee_tier == 500

    def test_get_pools_for_pair(self):
        """Test getting pools by pair symbols."""
        index = PoolIndex()
        
        pool1 = DiscoveredPool(
            chain="arbitrum_one", dex="uniswap_v3", address="0x111",
            token0="0xa", token1="0xb", token0_symbol="WETH", token1_symbol="USDC", fee_tier=500,
        )
        pool2 = DiscoveredPool(
            chain="arbitrum_one", dex="sushi", address="0x222",
            token0="0xa", token1="0xb", token0_symbol="WETH", token1_symbol="USDC", fee_tier=3000,
        )
        pool3 = DiscoveredPool(
            chain="arbitrum_one", dex="uniswap_v3", address="0x333",
            token0="0xc", token1="0xd", token0_symbol="WBTC", token1_symbol="WETH", fee_tier=500,
        )
        
        index.add_pool(pool1)
        index.add_pool(pool2)
        index.add_pool(pool3)
        
        weth_usdc_pools = index.get_pools_for_pair("arbitrum_one", "WETH", "USDC")
        assert len(weth_usdc_pools) == 2
        
        wbtc_weth_pools = index.get_pools_for_pair("arbitrum_one", "WBTC", "WETH")
        assert len(wbtc_weth_pools) == 1

    def test_mark_indexed_tracking(self):
        """Test indexed pair tracking."""
        index = PoolIndex()
        
        assert not index.is_indexed("arbitrum_one", "0xa", "0xb", "uniswap_v3")
        
        index.mark_indexed("arbitrum_one", "0xa", "0xb", "uniswap_v3")
        
        assert index.is_indexed("arbitrum_one", "0xa", "0xb", "uniswap_v3")
        assert index.is_indexed("arbitrum_one", "0xb", "0xa", "uniswap_v3")  # Order doesn't matter
        assert not index.is_indexed("arbitrum_one", "0xa", "0xb", "sushi")  # Different DEX

    def test_stats(self):
        """Test stats computation."""
        index = PoolIndex()
        
        index.add_pool(DiscoveredPool(
            chain="arbitrum_one", dex="uniswap_v3", address="0x1",
            token0="0xa", token1="0xb", token0_symbol="A", token1_symbol="B", fee_tier=500,
        ))
        index.add_pool(DiscoveredPool(
            chain="base", dex="aerodrome", address="0x2",
            token0="0xc", token1="0xd", token0_symbol="C", token1_symbol="D", fee_tier=None,
        ))
        
        stats = index.stats()
        assert "arbitrum_one" in stats["chains"]
        assert "base" in stats["chains"]
        assert stats["total_pools"] == 2


class TestFactoryAddresses:
    """Tests for factory address lookup."""

    def test_get_known_factory(self):
        """Test getting known factory addresses."""
        addr = get_factory_address("arbitrum_one", "uniswap_v3")
        assert addr == "0x1F98431c8aD98523631AE4a59f267346ea31F984"

    def test_get_unknown_factory(self):
        """Test unknown factory returns None."""
        addr = get_factory_address("arbitrum_one", "unknown_dex")
        assert addr is None

    def test_get_unknown_chain(self):
        """Test unknown chain returns None."""
        addr = get_factory_address("unknown_chain", "uniswap_v3")
        assert addr is None

    def test_v3_fee_tiers_standard(self):
        """Test V3 fee tiers are standard."""
        assert V3_FEE_TIERS == [100, 500, 3000, 10000]


class TestVerifyPoolExists:
    """Tests for verify_pool_exists function."""

    @patch.dict(os.environ, {"ARBY_SKIP_RPC": "1"})
    def test_skip_rpc_returns_none(self):
        """Test that ARBY_SKIP_RPC=1 returns None."""
        result = verify_pool_exists(
            chain="arbitrum_one",
            dex="uniswap_v3",
            token_a="0xabc",
            token_b="0xdef",
            fee_tier=500,
        )
        assert result is None

    @patch.dict(os.environ, {"ARBY_SKIP_RPC": ""}, clear=True)
    def test_no_rpc_url_returns_none(self):
        """Test that missing RPC URL (no env vars) returns None."""
        # When no RPC env vars are set and ARBY_SKIP_RPC is not set,
        # but no RPC URL is available, should return None
        result = verify_pool_exists(
            chain="unknown_chain",  # No RPC for this chain
            dex="uniswap_v3",
            token_a="0xabc",
            token_b="0xdef",
            fee_tier=500,
        )
        # Either None (no RPC) or actual pool if RPC is available
        # For unknown chain, should be None
        assert result is None

    @patch.dict(os.environ, {"ARBY_SKIP_RPC": ""})
    @patch("discovery.index_factories.query_v3_pool")
    def test_v3_pool_found_with_explicit_rpc(self, mock_query):
        """Test V3 pool found via factory with explicit RPC URL."""
        mock_query.return_value = "0xpool123"
        
        result = verify_pool_exists(
            chain="arbitrum_one",
            dex="uniswap_v3",
            token_a="0xabc",
            token_b="0xdef",
            fee_tier=500,
            rpc_url="https://explicit-rpc.example.com",  # Explicit RPC
        )
        
        assert result == "0xpool123"
        mock_query.assert_called_once()

    @patch.dict(os.environ, {"ARBY_SKIP_RPC": ""})
    @patch("discovery.index_factories.query_v3_pool")
    def test_sushi_alias_maps_to_sushiswap_v3(self, mock_query):
        """Test 'sushi' alias maps to 'sushiswap_v3'."""
        mock_query.return_value = "0xsushipool"
        
        result = verify_pool_exists(
            chain="arbitrum_one",
            dex="sushi",  # Alias
            token_a="0xabc",
            token_b="0xdef",
            fee_tier=500,
            rpc_url="https://explicit-rpc.example.com",
        )
        
        assert result == "0xsushipool"


class TestValidatePoolAddress:
    """Tests for validate_pool_address function."""

    @patch("discovery.index_factories.verify_pool_exists")
    def test_valid_address_matches(self, mock_verify):
        """Test valid address matches factory result."""
        mock_verify.return_value = "0xabc123"
        
        result = validate_pool_address(
            chain="arbitrum_one",
            dex="uniswap_v3",
            pool_address="0xABC123",  # Different case
            token_a="0x111",
            token_b="0x222",
            fee_tier=500,
        )
        
        assert result is True

    @patch("discovery.index_factories.verify_pool_exists")
    def test_invalid_address_mismatch(self, mock_verify):
        """Test invalid address doesn't match."""
        mock_verify.return_value = "0xabc123"
        
        result = validate_pool_address(
            chain="arbitrum_one",
            dex="uniswap_v3",
            pool_address="0xdef456",  # Different
            token_a="0x111",
            token_b="0x222",
            fee_tier=500,
        )
        
        assert result is False

    @patch("discovery.index_factories.verify_pool_exists")
    def test_pool_not_found_returns_false(self, mock_verify):
        """Test pool not found returns False."""
        mock_verify.return_value = None
        
        result = validate_pool_address(
            chain="arbitrum_one",
            dex="uniswap_v3",
            pool_address="0xabc123",
            token_a="0x111",
            token_b="0x222",
            fee_tier=500,
        )
        
        assert result is False


class TestCountDiscoveryCandidates:
    """Tests for count_discovery_candidates dry-run."""

    @patch("discovery.index_factories.get_intent_universe")
    @patch("discovery.index_factories.get_token_registry")
    def test_dry_run_counts(self, mock_registry, mock_universe):
        """Test dry-run candidate counting."""
        # Mock intent pairs
        mock_pair = MagicMock()
        mock_pair.token_a = "WETH"
        mock_pair.token_b = "USDC"
        
        mock_universe_instance = MagicMock()
        mock_universe_instance.get_pairs_for_chain.return_value = [mock_pair]
        mock_universe.return_value = mock_universe_instance
        
        # Mock token registry
        mock_registry_instance = MagicMock()
        mock_registry_instance.get_address.side_effect = lambda chain, symbol: f"0x{symbol}"
        mock_registry.return_value = mock_registry_instance
        
        result = count_discovery_candidates("arbitrum_one")
        
        assert result["chain"] == "arbitrum_one"
        assert result["intent_pairs_total"] == 1
        assert result["resolvable_pairs"] == 1
        assert result["unresolvable_pairs"] == 0
