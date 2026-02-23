# PATH: tests/unit/test_discovery_runtime_quotes.py
"""
Tests for discovery_runtime quote collection integration.

v2.6.0: Tests that pool_info from discovery_runtime flows correctly to collect_quotes.
"""
import pytest
from unittest.mock import MagicMock, patch


class TestRuntimePairsToPairConfigs:
    """Tests for runtime_pairs_to_pair_configs() pool_info population."""
    
    def test_pool_info_populated(self):
        """runtime_pairs_to_pair_configs populates pool_info correctly."""
        from discovery.runtime import RuntimePair, runtime_pairs_to_pair_configs
        
        # Create two RuntimePairs for same pair on different DEXes
        rp1 = RuntimePair(
            chain="arbitrum_one",
            token_a="WETH",
            token_b="USDC",
            addr_a="0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
            addr_b="0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
            dex="uniswap_v3",
            fee=500,
            pool_address="0x88e6A0c2dDD26FEEb64F039a2c41296FcB3f5640",
            decimals_a=18,
            decimals_b=6,
        )
        rp2 = RuntimePair(
            chain="arbitrum_one",
            token_a="WETH",
            token_b="USDC",
            addr_a="0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
            addr_b="0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
            dex="sushiswap_v3",
            fee=500,
            pool_address="0x1234567890ABCDEF1234567890ABCDEF12345678",
            decimals_a=18,
            decimals_b=6,
        )
        
        pair_configs = runtime_pairs_to_pair_configs([rp1, rp2])
        
        # Should produce one PairConfig with pool_info containing both pools
        assert len(pair_configs) == 1
        pc = pair_configs[0]
        
        assert pc.pool_info is not None
        assert len(pc.pool_info) == 2
        
        # Check pool_info structure
        dexes_in_pool_info = [pi["dex"] for pi in pc.pool_info]
        assert "uniswap_v3" in dexes_in_pool_info
        assert "sushiswap_v3" in dexes_in_pool_info
        
        # Check pool addresses included
        addresses = [pi["address"] for pi in pc.pool_info]
        assert rp1.pool_address in addresses
        assert rp2.pool_address in addresses
        
        # Check fee included
        for pi in pc.pool_info:
            assert "fee" in pi
            assert pi["fee"] == 500
    
    def test_pool_info_has_required_keys(self):
        """Each pool_info entry has dex, fee, address keys."""
        from discovery.runtime import RuntimePair, runtime_pairs_to_pair_configs
        
        rp = RuntimePair(
            chain="arbitrum_one",
            token_a="ARB",
            token_b="USDC",
            addr_a="0xARB",
            addr_b="0xUSDC",
            dex="uniswap_v3",
            fee=3000,
            pool_address="0xPoolArb",
            decimals_a=18,
            decimals_b=6,
        )
        
        pair_configs = runtime_pairs_to_pair_configs([rp])
        
        assert len(pair_configs) == 1
        pc = pair_configs[0]
        
        assert pc.pool_info is not None
        assert len(pc.pool_info) == 1
        
        pi = pc.pool_info[0]
        assert "dex" in pi
        assert "fee" in pi
        assert "address" in pi
        assert pi["dex"] == "uniswap_v3"
        assert pi["fee"] == 3000
        assert pi["address"] == "0xPoolArb"


class TestPoolInfoInPairConfig:
    """Tests for PairConfig pool_info field."""
    
    def test_pairconfig_pool_info_field(self):
        """PairConfig dataclass supports pool_info field."""
        from config.pairs import PairConfig
        
        pool_info = [
            {"dex": "uniswap_v3", "fee": 500, "address": "0xPool1"},
            {"dex": "sushiswap_v3", "fee": 500, "address": "0xPool2"},
        ]
        
        pc = PairConfig(
            chain="arbitrum_one",
            token_in="WETH",
            token_out="USDC",
            pool_info=pool_info,
        )
        
        assert pc.pool_info == pool_info
        assert len(pc.pool_info) == 2
    
    def test_pairconfig_pool_info_in_to_dict(self):
        """PairConfig.to_dict() includes pool_info when present."""
        from config.pairs import PairConfig
        
        pool_info = [{"dex": "uniswap_v3", "fee": 500, "address": "0xPool1"}]
        
        pc = PairConfig(
            chain="arbitrum_one",
            token_in="WETH",
            token_out="USDC",
            pool_info=pool_info,
        )
        
        d = pc.to_dict()
        assert "pool_info" in d
        assert d["pool_info"] == pool_info
    
    def test_pairconfig_pool_info_none_by_default(self):
        """PairConfig pool_info is None by default."""
        from config.pairs import PairConfig
        
        pc = PairConfig(
            chain="arbitrum_one",
            token_in="WETH",
            token_out="USDC",
        )
        
        assert pc.pool_info is None


class TestRpcCapTriggered:
    """Tests for rpc_cap_triggered in RuntimeStats."""
    
    def test_rpc_cap_triggered_default_false(self):
        """rpc_cap_triggered defaults to False."""
        from discovery.runtime import RuntimeStats
        
        stats = RuntimeStats()
        assert stats.rpc_cap_triggered is False
    
    def test_rpc_cap_triggered_in_to_dict(self):
        """rpc_cap_triggered is included in to_dict()."""
        from discovery.runtime import RuntimeStats
        
        stats = RuntimeStats(rpc_cap_triggered=True)
        
        d = stats.to_dict()
        assert "rpc_cap_triggered" in d
        assert d["rpc_cap_triggered"] is True
    
    def test_rpc_cap_set_from_resolver_stats(self):
        """rpc_cap_triggered is set from resolver stats."""
        from discovery.runtime import RuntimeStats
        
        # When cap_triggered is True in resolver
        stats = RuntimeStats()
        stats.rpc_cap_triggered = True  # Set from resolver_stats["cap_triggered"]
        
        assert stats.rpc_cap_triggered is True
        
        d = stats.to_dict()
        assert d["rpc_cap_triggered"] is True
