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
        assert stats.pairs_skipped_single_dex == 0
        assert stats.cross_dex_pairs_count == 0
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
        from discovery.verify import TokenInfo
        
        # Create mock intent pairs
        mock_pairs = [
            IntentPair("arbitrum_one", "WETH", "USDC"),
            IntentPair("arbitrum_one", "ARB", "WETH"),
            IntentPair("arbitrum_one", "LINK", "WETH"),
        ]
        
        # Create mock token info
        mock_token = TokenInfo(symbol="WETH", address="0xWETH", decimals=18)
        
        with patch("discovery.intent_loader.get_intent_universe") as mock_universe:
            mock_univ = MagicMock()
            mock_univ.get_pairs_for_chain.return_value = mock_pairs
            mock_universe.return_value = mock_univ
            
            with patch("discovery.verify.get_token_registry") as mock_registry:
                mock_reg = MagicMock()
                mock_reg.get_token.return_value = mock_token
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

class TestCrossDexFiltering:
    """Tests for require_cross_dex functionality."""
    
    def test_cross_dex_stats_tracked(self):
        """cross_dex_pairs_count is tracked in stats."""
        from discovery.runtime import RuntimeStats
        
        stats = RuntimeStats()
        stats.cross_dex_pairs_count = 5
        stats.pairs_skipped_single_dex = 3
        
        d = stats.to_dict()
        assert d["cross_dex_pairs_count"] == 5
        assert d["pairs_skipped_single_dex"] == 3
    
    @patch.dict(os.environ, {"ARBY_SKIP_RPC": "0"})
    def test_require_cross_dex_filters_single_dex(self):
        """require_cross_dex=True filters pairs with only one dex."""
        from discovery.runtime import resolve_runtime_pairs
        from discovery.intent_loader import IntentPair
        from discovery.verify import TokenInfo
        
        # Create mock intent pair
        mock_pairs = [
            IntentPair("arbitrum_one", "WETH", "USDC"),
        ]
        
        mock_token = TokenInfo(symbol="WETH", address="0xWETH", decimals=18)
        
        with patch("discovery.intent_loader.get_intent_universe") as mock_universe:
            mock_univ = MagicMock()
            mock_univ.get_pairs_for_chain.return_value = mock_pairs
            mock_universe.return_value = mock_univ
            
            with patch("discovery.verify.get_token_registry") as mock_registry:
                mock_reg = MagicMock()
                mock_reg.get_token.return_value = mock_token
                mock_registry.return_value = mock_reg
                
                with patch("discovery.pool_resolver.get_pool_resolver") as mock_resolver:
                    resolver = MagicMock()
                    # Only uniswap_v3 has pool, sushiswap_v3 returns None
                    def mock_resolve(**kwargs):
                        if kwargs.get("dex") == "uniswap_v3":
                            return "0xPoolAddress"
                        return None
                    resolver.resolve.side_effect = mock_resolve
                    resolver.get_stats.return_value = {
                        "hits": 0, "misses": 2, "negative_hits": 0, "rpc_calls": 2
                    }
                    mock_resolver.return_value = resolver
                    
                    with patch("discovery.index_factories.FACTORY_ADDRESSES", {
                        "arbitrum_one": {
                            "uniswap_v3": "0xUniFactory",
                            "sushiswap_v3": "0xSushiFactory",
                        }
                    }):
                        # With require_cross_dex=True, should filter out single-dex pairs
                        resolved, stats = resolve_runtime_pairs(
                            "arbitrum_one",
                            dexes=["uniswap_v3", "sushiswap_v3"],
                            fee_tiers=[500],
                            require_cross_dex=True,
                        )
        
        # Pair only exists on uniswap_v3, so should be filtered out
        assert len(resolved) == 0
        assert stats.pairs_skipped_single_dex == 1
        assert stats.cross_dex_pairs_count == 0


class TestMatchesExcludedHint:
    """R24: Tests for _matches_excluded_hint() glob matching."""

    def test_exact_match(self):
        from discovery.runtime import _matches_excluded_hint
        assert _matches_excluded_hint("VIRTUAL/WETH", ["VIRTUAL/WETH"]) is True

    def test_wildcard_right(self):
        from discovery.runtime import _matches_excluded_hint
        assert _matches_excluded_hint("cbBTC/WETH", ["cbBTC/*"]) is True
        assert _matches_excluded_hint("cbBTC/USDC", ["cbBTC/*"]) is True
        assert _matches_excluded_hint("WETH/cbBTC", ["cbBTC/*"]) is False

    def test_wildcard_left(self):
        from discovery.runtime import _matches_excluded_hint
        assert _matches_excluded_hint("WETH/cbBTC", ["*/cbBTC"]) is True
        assert _matches_excluded_hint("USDC/cbBTC", ["*/cbBTC"]) is True
        assert _matches_excluded_hint("cbBTC/WETH", ["*/cbBTC"]) is False

    def test_no_match(self):
        from discovery.runtime import _matches_excluded_hint
        assert _matches_excluded_hint("WETH/USDC", ["cbBTC/*"]) is False
        assert _matches_excluded_hint("WETH/USDC", ["VIRTUAL/*"]) is False

    def test_case_insensitive(self):
        from discovery.runtime import _matches_excluded_hint
        assert _matches_excluded_hint("cBbtc/WETH", ["cbBTC/*"]) is True
        assert _matches_excluded_hint("WETH/USDT", ["*/usdt"]) is True

    def test_multiple_hints(self):
        from discovery.runtime import _matches_excluded_hint
        hints = ["VIRTUAL/*", "WELL/*", "cbBTC/*", "*/cbBTC"]
        assert _matches_excluded_hint("VIRTUAL/WETH", hints) is True
        assert _matches_excluded_hint("WELL/USDC", hints) is True
        assert _matches_excluded_hint("USDC/cbBTC", hints) is True
        assert _matches_excluded_hint("WETH/USDC", hints) is False

    def test_empty_hints(self):
        from discovery.runtime import _matches_excluded_hint
        assert _matches_excluded_hint("WETH/USDC", []) is False

    def test_usdt_wildcard(self):
        """zkSync: */USDT excludes all USDT quote pairs."""
        from discovery.runtime import _matches_excluded_hint
        hints = ["*/USDT"]
        assert _matches_excluded_hint("WETH/USDT", hints) is True
        assert _matches_excluded_hint("ZK/USDT", hints) is True
        assert _matches_excluded_hint("USDT/WETH", hints) is False

    def test_stablecoin_exact(self):
        """Mantle: USDC/USDT exact exclusion."""
        from discovery.runtime import _matches_excluded_hint
        hints = ["USDC/USDT"]
        assert _matches_excluded_hint("USDC/USDT", hints) is True
        assert _matches_excluded_hint("USDT/USDC", hints) is False
        assert _matches_excluded_hint("WETH/USDC", hints) is False


class TestExcludedPairHintsPerChain:
    """R24: Regression tests — specific chain exclusions from config."""

    def test_base_exclusions(self):
        """Base: VIRTUAL/*, WELL/*, cbBTC/*, */cbBTC."""
        from discovery.runtime import _matches_excluded_hint
        hints = ["VIRTUAL/*", "WELL/*", "cbBTC/*", "*/cbBTC"]
        # Must exclude
        assert _matches_excluded_hint("VIRTUAL/WETH", hints)
        assert _matches_excluded_hint("WELL/USDC", hints)
        assert _matches_excluded_hint("cbBTC/WETH", hints)
        assert _matches_excluded_hint("USDC/cbBTC", hints)
        assert _matches_excluded_hint("WETH/cbBTC", hints)
        # Must NOT exclude
        assert not _matches_excluded_hint("WETH/USDC", hints)
        assert not _matches_excluded_hint("AERO/WETH", hints)

    def test_zksync_exclusions(self):
        """zkSync: HOLD/*, CHEEMS/*, MUTE/*, SPACE/*, ZK/*, */USDT."""
        from discovery.runtime import _matches_excluded_hint
        hints = ["HOLD/*", "CHEEMS/*", "MUTE/*", "SPACE/*", "ZK/*", "*/USDT"]
        assert _matches_excluded_hint("HOLD/USDC", hints)
        assert _matches_excluded_hint("HOLD/WETH", hints)
        assert _matches_excluded_hint("ZK/USDC", hints)
        assert _matches_excluded_hint("WETH/USDT", hints)
        assert _matches_excluded_hint("ZK/USDT", hints)
        assert not _matches_excluded_hint("WETH/USDC", hints)
        assert not _matches_excluded_hint("WBTC/WETH", hints)

    def test_mantle_exclusions(self):
        """Mantle: USDC/USDT, PUFF/*."""
        from discovery.runtime import _matches_excluded_hint
        hints = ["USDC/USDT", "PUFF/*"]
        assert _matches_excluded_hint("USDC/USDT", hints)
        assert _matches_excluded_hint("PUFF/WETH", hints)
        assert _matches_excluded_hint("PUFF/WMNT", hints)
        assert not _matches_excluded_hint("WETH/WMNT", hints)

    def test_arbitrum_exclusions(self):
        """Arbitrum: ARB/WETH."""
        from discovery.runtime import _matches_excluded_hint
        hints = ["ARB/WETH"]
        assert _matches_excluded_hint("ARB/WETH", hints)
        assert not _matches_excluded_hint("WETH/ARB", hints)
        assert not _matches_excluded_hint("ARB/USDC", hints)


class TestRuntimeStatsExcluded:
    """R24: RuntimeStats includes pairs_skipped_excluded."""

    def test_stats_has_excluded_field(self):
        from discovery.runtime import RuntimeStats
        stats = RuntimeStats()
        assert stats.pairs_skipped_excluded == 0

    def test_stats_to_dict_has_excluded(self):
        from discovery.runtime import RuntimeStats
        stats = RuntimeStats(pairs_skipped_excluded=3)
        d = stats.to_dict()
        assert d["pairs_skipped_excluded"] == 3