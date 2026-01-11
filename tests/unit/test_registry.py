"""
tests/unit/test_registry.py - Registry tests.
"""

import pytest
from pathlib import Path
from io import StringIO

from discovery.registry import (
    IntentParser,
    IntentPair,
    TokenResolver,
    ResolvedPair,
    PoolRegistry,
    PoolCandidate,
)
from core.models import Token


@pytest.fixture
def sample_intent_content():
    return """# Comment line
# Another comment

arbitrum_one:WETH/USDC
arbitrum_one:WETH/WBTC
base:WETH/USDC
linea:WETH/USDT
"""


@pytest.fixture
def sample_chains_config():
    return {
        "arbitrum_one": {"chain_id": 42161, "enabled": True},
        "base": {"chain_id": 8453, "enabled": True},
        "linea": {"chain_id": 59144, "enabled": True},
    }


@pytest.fixture
def sample_tokens_config():
    return {
        "arbitrum_one": {
            "WETH": {"address": "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1", "decimals": 18},
            "USDC": {"address": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831", "decimals": 6},
            "WBTC": {"address": "0x2f2a2543B76A4166549F7aaB2e75Bef0aefC5B0f", "decimals": 8},
        },
        "base": {
            "WETH": {"address": "0x4200000000000000000000000000000000000006", "decimals": 18},
            "USDC": {"address": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913", "decimals": 6},
        },
        "linea": {
            "WETH": {"address": "0xe5D7C2a44FfDDf6b295A15c148167daaAf5Cf34f", "decimals": 18},
            "USDT": {"address": "0xA219439258ca9da29E9Cc4cE5596924745e12B93", "decimals": 6},
        },
    }


@pytest.fixture
def sample_dexes_config():
    return {
        "arbitrum_one": {
            "uniswap_v3": {
                "enabled": True,
                "verified_for_quoting": True,
                "adapter_type": "uniswap_v3",
                "quoter_v2": "0x61fFE014bA17989E743c5F6cB21bF9697530B21e",
                "fee_tiers": [100, 500, 3000],
                "priority": 1,
            },
            "sushiswap_v3": {
                "enabled": True,
                "verified_for_quoting": True,
                "adapter_type": "uniswap_v3",
                "quoter_v2": "0x0524E833cCD057e4d7A296e3aaAb9f7675964Ce1",
                "fee_tiers": [100, 500],
                "priority": 2,
            },
        },
        "base": {
            "uniswap_v3": {
                "enabled": True,
                "verified_for_quoting": True,
                "adapter_type": "uniswap_v3",
                "quoter_v2": "0x3d4e44Eb1374240CE5F1B871ab261CD16335B76a",
                "fee_tiers": [500, 3000],
                "priority": 1,
            },
        },
    }


class TestIntentParser:
    def test_parse_intent_file(self, tmp_path, sample_intent_content):
        intent_file = tmp_path / "intent.txt"
        intent_file.write_text(sample_intent_content)
        
        parser = IntentParser(intent_file)
        pairs = parser.parse()
        
        assert len(pairs) == 4
        assert pairs[0].chain_key == "arbitrum_one"
        assert pairs[0].base_symbol == "WETH"
        assert pairs[0].quote_symbol == "USDC"
    
    def test_skip_comments_and_empty(self, tmp_path):
        content = """# Full comment
        
arbitrum_one:WETH/USDC
# Another comment
"""
        intent_file = tmp_path / "intent.txt"
        intent_file.write_text(content)
        
        parser = IntentParser(intent_file)
        pairs = parser.parse()
        
        assert len(pairs) == 1
    
    def test_pair_id(self):
        pair = IntentPair(
            chain_key="arbitrum_one",
            base_symbol="WETH",
            quote_symbol="USDC",
        )
        assert pair.pair_id == "arbitrum_one:WETH/USDC"


class TestTokenResolver:
    def test_resolve_token(self, sample_tokens_config, sample_chains_config):
        resolver = TokenResolver(sample_tokens_config, sample_chains_config)
        
        token = resolver.resolve("arbitrum_one", "WETH")
        
        assert token is not None
        assert token.symbol == "WETH"
        assert token.chain_id == 42161
        assert token.decimals == 18
    
    def test_resolve_unknown_token(self, sample_tokens_config, sample_chains_config):
        resolver = TokenResolver(sample_tokens_config, sample_chains_config)
        
        token = resolver.resolve("arbitrum_one", "UNKNOWN")
        
        assert token is None
    
    def test_resolve_pair(self, sample_tokens_config, sample_chains_config):
        resolver = TokenResolver(sample_tokens_config, sample_chains_config)
        
        pair = IntentPair("arbitrum_one", "WETH", "USDC")
        resolved = resolver.resolve_pair(pair)
        
        assert resolved is not None
        assert resolved.base.symbol == "WETH"
        assert resolved.quote.symbol == "USDC"
        assert resolved.chain_id == 42161
    
    def test_resolve_pair_unknown_token(self, sample_tokens_config, sample_chains_config):
        resolver = TokenResolver(sample_tokens_config, sample_chains_config)
        
        pair = IntentPair("arbitrum_one", "WETH", "UNKNOWN")
        resolved = resolver.resolve_pair(pair)
        
        assert resolved is None


class TestPoolRegistry:
    def test_load_intent(
        self, tmp_path, sample_intent_content,
        sample_chains_config, sample_dexes_config, sample_tokens_config
    ):
        intent_file = tmp_path / "intent.txt"
        intent_file.write_text(sample_intent_content)
        
        registry = PoolRegistry(sample_chains_config, sample_dexes_config, sample_tokens_config)
        count = registry.load_intent(intent_file)
        
        assert count == 4  # All pairs should resolve
    
    def test_generate_candidates(
        self, tmp_path, sample_intent_content,
        sample_chains_config, sample_dexes_config, sample_tokens_config
    ):
        intent_file = tmp_path / "intent.txt"
        intent_file.write_text(sample_intent_content)
        
        registry = PoolRegistry(sample_chains_config, sample_dexes_config, sample_tokens_config)
        registry.load_intent(intent_file)
        candidates = registry.generate_pool_candidates()
        
        # arbitrum: 2 pairs x 2 DEXes x (3+2) fees = 10
        # base: 1 pair x 1 DEX x 2 fees = 2
        # linea: 1 pair but no DEX config = 0
        assert len(candidates) >= 10  # At least arbitrum
    
    def test_generate_candidates_for_chain(
        self, tmp_path, sample_intent_content,
        sample_chains_config, sample_dexes_config, sample_tokens_config
    ):
        intent_file = tmp_path / "intent.txt"
        intent_file.write_text(sample_intent_content)
        
        registry = PoolRegistry(sample_chains_config, sample_dexes_config, sample_tokens_config)
        registry.load_intent(intent_file)
        registry.generate_pool_candidates()
        
        arb_candidates = registry.get_candidates_for_chain("arbitrum_one")
        base_candidates = registry.get_candidates_for_chain("base")
        
        assert len(arb_candidates) > 0
        assert len(base_candidates) > 0
        
        # All arb candidates should have chain_id 42161
        for c in arb_candidates:
            assert c.pool.chain_id == 42161
    
    def test_get_summary(
        self, tmp_path, sample_intent_content,
        sample_chains_config, sample_dexes_config, sample_tokens_config
    ):
        intent_file = tmp_path / "intent.txt"
        intent_file.write_text(sample_intent_content)
        
        registry = PoolRegistry(sample_chains_config, sample_dexes_config, sample_tokens_config)
        registry.load_intent(intent_file)
        registry.generate_pool_candidates()
        
        summary = registry.get_summary()
        
        assert "total_resolved_pairs" in summary
        assert "total_pool_candidates" in summary
        assert "chains" in summary
        assert summary["total_resolved_pairs"] == 4
    
    def test_candidates_sorted_by_priority(
        self, tmp_path,
        sample_chains_config, sample_dexes_config, sample_tokens_config
    ):
        # Single pair to test priority sorting
        content = "arbitrum_one:WETH/USDC"
        intent_file = tmp_path / "intent.txt"
        intent_file.write_text(content)
        
        registry = PoolRegistry(sample_chains_config, sample_dexes_config, sample_tokens_config)
        registry.load_intent(intent_file)
        candidates = registry.generate_pool_candidates()
        
        # Check that candidates are sorted by priority
        priorities = [c.priority for c in candidates]
        assert priorities == sorted(priorities)
