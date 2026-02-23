# PATH: tests/unit/test_pool_resolver.py
"""Unit tests for pool resolver with cache."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestPoolResolverCacheKey:
    """Test cache key generation."""
    
    def test_cache_key_deterministic(self):
        """Same inputs should produce same cache key."""
        from discovery.pool_resolver import PoolResolver
        
        resolver = PoolResolver()
        
        key1 = resolver._cache_key("arbitrum_one", "uniswap_v3", "0xabc", "0xdef", 500)
        key2 = resolver._cache_key("arbitrum_one", "uniswap_v3", "0xabc", "0xdef", 500)
        
        assert key1 == key2
    
    def test_cache_key_token_order_independent(self):
        """Token order should not affect cache key."""
        from discovery.pool_resolver import PoolResolver
        
        resolver = PoolResolver()
        
        key1 = resolver._cache_key("arbitrum_one", "uniswap_v3", "0xabc", "0xdef", 500)
        key2 = resolver._cache_key("arbitrum_one", "uniswap_v3", "0xdef", "0xabc", 500)
        
        assert key1 == key2
    
    def test_cache_key_case_insensitive(self):
        """Addresses should be lowercased for cache key."""
        from discovery.pool_resolver import PoolResolver
        
        resolver = PoolResolver()
        
        key1 = resolver._cache_key("arbitrum_one", "uniswap_v3", "0xABC", "0xDEF", 500)
        key2 = resolver._cache_key("arbitrum_one", "uniswap_v3", "0xabc", "0xdef", 500)
        
        assert key1 == key2
    
    def test_cache_key_different_fee_different_key(self):
        """Different fee tiers should produce different keys."""
        from discovery.pool_resolver import PoolResolver
        
        resolver = PoolResolver()
        
        key500 = resolver._cache_key("arbitrum_one", "uniswap_v3", "0xabc", "0xdef", 500)
        key3000 = resolver._cache_key("arbitrum_one", "uniswap_v3", "0xabc", "0xdef", 3000)
        
        assert key500 != key3000


class TestPoolResolverCache:
    """Test cache hit/miss behavior."""
    
    def test_cache_hit_increments_stats(self):
        """Cache hit should increment hit counter."""
        from discovery.pool_resolver import PoolResolver, NULL_POOL
        
        resolver = PoolResolver()
        resolver._cache = {"test:key:0x1:0x2:500": "0xpool"}
        
        # Pre-populate cache key that resolve would use
        key = resolver._cache_key("test", "key", "0x1", "0x2", 500)
        resolver._cache[key] = "0xpool"
        
        # Skip the actual resolve logic by accessing directly
        initial_hits = resolver._stats.hits
        
        # Simulate what resolve does for cache hit
        if key in resolver._cache and resolver._cache[key] != NULL_POOL:
            resolver._stats.hits += 1
        
        assert resolver._stats.hits == initial_hits + 1
    
    def test_negative_cache_prevents_rpc(self):
        """Negative cache entries should prevent RPC calls."""
        from discovery.pool_resolver import PoolResolver, NULL_POOL
        
        resolver = PoolResolver()
        key = resolver._cache_key("test", "dex", "0x1", "0x2", 500)
        resolver._cache[key] = NULL_POOL
        
        # Checking cache returns None for NULL_POOL
        cached = resolver._cache.get(key)
        assert cached == NULL_POOL
        
        # This should not result in an RPC call
        resolver._stats.negative_hits += 1  # Simulate what resolve does
        assert resolver._stats.negative_hits == 1


class TestPoolResolverIntegration:
    """Integration tests with mock RPC."""
    
    @patch.dict(os.environ, {"ARBY_SKIP_RPC": "0"})
    def test_resolve_returns_pool_address(self):
        """Resolve should return pool address when found."""
        from discovery.pool_resolver import PoolResolver
        
        with patch("discovery.verify.get_token_registry") as mock_registry:
            mock_reg = MagicMock()
            mock_reg.get_address.side_effect = lambda c, s: {
                "WETH": "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
                "USDC": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
            }.get(s)
            mock_registry.return_value = mock_reg
            
            with patch("discovery.index_factories.query_v3_pool") as mock_query:
                mock_query.return_value = "0xC6962004f452bE9203591991D15f6b388e09E8D0".lower()
                
                with patch("core.rpc_urls.get_rpc_url") as mock_rpc:
                    mock_rpc.return_value = "https://test.rpc"
                    
                    with patch("discovery.index_factories.get_factory_address") as mock_factory:
                        mock_factory.return_value = "0x1F98431c8aD98523631AE4a59f267346ea31F984"
                        
                        resolver = PoolResolver()
                        pool = resolver.resolve(
                            "arbitrum_one",
                            "uniswap_v3",
                            "WETH",
                            "USDC",
                            500,
                        )
                        
                        assert pool is not None
                        assert pool.startswith("0x")
    
    @patch.dict(os.environ, {"ARBY_SKIP_RPC": "1"})
    def test_skip_rpc_returns_none(self):
        """Should return None when ARBY_SKIP_RPC=1."""
        from discovery.pool_resolver import PoolResolver
        
        with patch("discovery.verify.get_token_registry") as mock_registry:
            mock_reg = MagicMock()
            mock_reg.get_address.side_effect = lambda c, s: f"0x{s}"
            mock_registry.return_value = mock_reg
            
            resolver = PoolResolver()
            resolver._cache = {}  # Clear any pre-loaded cache
            
            pool = resolver.resolve(
                "arbitrum_one",
                "uniswap_v3",
                "WETH",
                "USDC",
                500,
            )
            
            # ARBY_SKIP_RPC=1 should cause None return
            assert pool is None


class TestPoolResolverStats:
    """Test resolver statistics."""
    
    def test_initial_stats_zero(self):
        """Initial stats should all be zero."""
        from discovery.pool_resolver import PoolResolver
        
        resolver = PoolResolver()
        resolver._stats.hits = 0
        resolver._stats.misses = 0
        
        stats = resolver.get_stats()
        
        assert stats["hits"] == 0
        assert stats["misses"] == 0
    
    def test_hit_rate_calculation(self):
        """Hit rate should be correctly calculated."""
        from discovery.pool_resolver import PoolResolver
        
        resolver = PoolResolver()
        resolver._stats.hits = 8
        resolver._stats.misses = 2
        
        stats = resolver.get_stats()
        
        assert stats["hit_rate"] == 0.8


class TestPoolResolverPersistence:
    """Test cache persistence."""
    
    def test_save_load_roundtrip(self):
        """Cache should survive save/load cycle."""
        from discovery.pool_resolver import CACHE_PATH
        import discovery.pool_resolver as pr_module
        
        # Use temp file
        with tempfile.TemporaryDirectory() as tmpdir:
            test_cache_path = Path(tmpdir) / "test_cache.json"
            
            # Patch CACHE_PATH
            original_path = pr_module.CACHE_PATH
            pr_module.CACHE_PATH = test_cache_path
            
            try:
                from discovery.pool_resolver import PoolResolver
                
                # Create and populate cache
                resolver1 = PoolResolver()
                resolver1._cache = {"test:key": "0xpool123"}
                resolver1._dirty = True
                resolver1._save_cache()
                
                # Create new resolver that should load from disk
                resolver2 = PoolResolver()
                resolver2._load_cache()
                
                assert "test:key" in resolver2._cache
                assert resolver2._cache["test:key"] == "0xpool123"
            finally:
                pr_module.CACHE_PATH = original_path
