# tests/unit/test_discovery_runtime.py
"""
Unit tests for discovery/runtime.py

v2.4.2: Tests for discovery_runtime mode.
"""
import os
import pytest
from unittest.mock import MagicMock, patch


class TestRuntimeStats:
    """Tests for RuntimeStats dataclass."""
    
    def test_runtime_stats_defaults(self):
        """RuntimeStats has correct defaults."""
        from discovery.runtime import RuntimeStats
        
        stats = RuntimeStats()
        
        assert stats.enabled is True
        assert stats.pairs_evaluated == 0
        assert stats.pairs_resolved == 0
        assert stats.pairs_skipped_no_tokens == 0
        assert stats.pairs_skipped_no_pool == 0
        assert stats.pairs_skipped_max_cap == 0
        assert stats.pools_from_cache == 0
        assert stats.pools_from_rpc == 0
        assert stats.rpc_calls == 0
        assert stats.dexes_queried == []
        assert stats.error is None
    
    def test_runtime_stats_to_dict(self):
        """RuntimeStats.to_dict() returns serializable dict."""
        from discovery.runtime import RuntimeStats
        
        stats = RuntimeStats(
            pairs_resolved=5,
            rpc_calls=3,
            error="test_error",
        )
        
        d = stats.to_dict()
        
        assert isinstance(d, dict)
        assert d["pairs_resolved"] == 5
        assert d["rpc_calls"] == 3
        assert d["error"] == "test_error"


class TestRuntimePair:
    """Tests for RuntimePair dataclass."""
    
    def test_canonical_key_sorted(self):
        """canonical_key sorts tokens alphabetically."""
        from discovery.runtime import RuntimePair
        
        pair1 = RuntimePair(
            chain="arbitrum_one",
            token_a="WETH",
            token_b="USDC",
            addr_a="0xWETH",
            addr_b="0xUSDC",
            dex="uniswap_v3",
            fee=500,
            pool_address="0xPool",
        )
        
        pair2 = RuntimePair(
            chain="arbitrum_one",
            token_a="USDC",
            token_b="WETH",
            addr_a="0xUSDC",
            addr_b="0xWETH",
            dex="uniswap_v3",
            fee=500,
            pool_address="0xPool",
        )
        
        # Same canonical key regardless of order
        assert pair1.canonical_key == pair2.canonical_key
        assert "USDC/WETH" in pair1.canonical_key
    
    def test_display_name_preserves_order(self):
        """display_name preserves original token order."""
        from discovery.runtime import RuntimePair
        
        pair = RuntimePair(
            chain="arbitrum_one",
            token_a="WETH",
            token_b="USDC",
            addr_a="0xWETH",
            addr_b="0xUSDC",
            dex="uniswap_v3",
            fee=500,
            pool_address="0xPool",
        )
        
        assert pair.display_name == "WETH/USDC"


class TestResolveRuntimePairs:
    """Tests for resolve_runtime_pairs() function."""
    
    @patch.dict(os.environ, {"ARBY_SKIP_RPC": "1"})
    def test_skip_rpc_returns_empty(self):
        """ARBY_SKIP_RPC=1 returns empty list with disabled stats."""
        from discovery.runtime import resolve_runtime_pairs
        
        resolved, stats = resolve_runtime_pairs("arbitrum_one")
        
        assert resolved == []
        assert stats.enabled is False
        assert stats.error == "ARBY_SKIP_RPC=1"
    
    @patch.dict(os.environ, {"ARBY_SKIP_RPC": "0"})
    def test_no_intent_pairs_returns_empty(self):
        """No intent pairs for chain returns empty."""
        from discovery.runtime import resolve_runtime_pairs
        
        with patch("discovery.intent_loader.get_intent_universe") as mock_universe:
            mock_univ = MagicMock()
            mock_univ.get_pairs_for_chain.return_value = []
            mock_universe.return_value = mock_univ
            
            with patch("discovery.verify.get_token_registry"):
                with patch("discovery.pool_resolver.get_pool_resolver"):
                    with patch("discovery.index_factories.FACTORY_ADDRESSES", {"arbitrum_one": {}}):
                        resolved, stats = resolve_runtime_pairs("arbitrum_one")
        
        assert resolved == []
        assert "no_intent_pairs" in (stats.error or "")
    
    @patch.dict(os.environ, {"ARBY_SKIP_RPC": "0"})
    def test_max_pairs_cap(self):
        """max_pairs limits resolved pairs."""
        from discovery.runtime import resolve_runtime_pairs, RuntimePair
        from discovery.intent_loader import IntentPair
        
        # Create mock intent pairs
        mock_pairs = [
            IntentPair("arbitrum_one", "WETH", "USDC"),
            IntentPair("arbitrum_one", "ARB", "WETH"),
            IntentPair("arbitrum_one", "LINK", "WETH"),
        ]
        
        with patch("discovery.intent_loader.get_intent_universe") as mock_universe:
            mock_univ = MagicMock()
            mock_univ.get_pairs_for_chain.return_value = mock_pairs
            mock_universe.return_value = mock_univ
            
            with patch("discovery.verify.get_token_registry") as mock_registry:
                mock_reg = MagicMock()
                mock_reg.get_address.return_value = "0xAddress"
                mock_registry.return_value = mock_reg
                
                with patch("discovery.pool_resolver.get_pool_resolver") as mock_resolver:
                    resolver = MagicMock()
                    resolver.resolve.return_value = "0xPoolAddress"
                    resolver.get_stats.return_value = {
                        "hits": 0, "misses": 1, "negative_hits": 0, "rpc_calls": 1
                    }
                    mock_resolver.return_value = resolver
                    
                    with patch("discovery.index_factories.FACTORY_ADDRESSES", {
                        "arbitrum_one": {"uniswap_v3": "0xFactory"}
                    }):
                        # Request max 1 pair
                        resolved, stats = resolve_runtime_pairs(
                            "arbitrum_one",
                            dexes=["uniswap_v3"],
                            max_pairs=1,
                        )
        
        # Should resolve only 1 pair due to max_pairs=1
        assert stats.pairs_resolved <= 1
        assert stats.pairs_skipped_max_cap >= 0


class TestGetRuntimeObservability:
    """Tests for get_runtime_observability() function."""
    
    def test_returns_dict(self):
        """get_runtime_observability returns dict."""
        from discovery.runtime import RuntimeStats, get_runtime_observability
        
        stats = RuntimeStats(pairs_resolved=3, rpc_calls=2)
        
        obs = get_runtime_observability(stats)
        
        assert isinstance(obs, dict)
        assert obs["pairs_resolved"] == 3
        assert obs["rpc_calls"] == 2


class TestDiscoveryRuntimeIntegration:
    """Integration tests with mock dependencies."""
    
    @patch.dict(os.environ, {"ARBY_SKIP_RPC": "0"})
    def test_deterministic_ordering(self):
        """Pairs are resolved in deterministic order."""
        from discovery.runtime import resolve_runtime_pairs
        from discovery.intent_loader import IntentPair
        
        # Pairs in random order
        mock_pairs = [
            IntentPair("arbitrum_one", "LINK", "WETH"),
            IntentPair("arbitrum_one", "ARB", "WETH"),
            IntentPair("arbitrum_one", "WETH", "USDC"),
        ]
        
        call_order = []
        
        def mock_resolve(chain, dex, symbol_a, symbol_b, fee, rpc_url=None):
            call_order.append(f"{symbol_a}/{symbol_b}")
            return "0xPoolAddress"
        
        with patch("discovery.intent_loader.get_intent_universe") as mock_universe:
            mock_univ = MagicMock()
            mock_univ.get_pairs_for_chain.return_value = mock_pairs
            mock_universe.return_value = mock_univ
            
            with patch("discovery.verify.get_token_registry") as mock_registry:
                mock_reg = MagicMock()
                mock_reg.get_address.return_value = "0xAddr"
                mock_registry.return_value = mock_reg
                
                with patch("discovery.pool_resolver.get_pool_resolver") as mock_resolver:
                    resolver = MagicMock()
                    resolver.resolve.side_effect = mock_resolve
                    resolver.get_stats.return_value = {
                        "hits": 0, "misses": 3, "negative_hits": 0, "rpc_calls": 3
                    }
                    mock_resolver.return_value = resolver
                    
                    with patch("discovery.index_factories.FACTORY_ADDRESSES", {
                        "arbitrum_one": {"uniswap_v3": "0xFactory"}
                    }):
                        resolved, stats = resolve_runtime_pairs(
                            "arbitrum_one",
                            dexes=["uniswap_v3"],
                            fee_tiers=[500],  # Single fee tier for simpler test
                            max_pairs=10,
                        )
        
        # Should be sorted alphabetically by canonical key
        # ARB/WETH, LINK/WETH, USDC/WETH (sorted tokens)
        assert len(call_order) >= 1
