# PATH: tests/unit/test_intent_loader.py
"""
Unit tests for discovery/intent_loader.py (Roadmap Appendix A Step 1).

v2.2.0: Tests intent.txt parsing, canonical ordering, comments, errors.
"""

import pytest
from pathlib import Path
from discovery.intent_loader import (
    parse_intent_line,
    IntentPair,
    IntentUniverse,
    load_intent,
    get_intent_universe,
    clear_intent_cache,
)


class TestParseIntentLine:
    """Tests for parse_intent_line function."""
    
    def test_valid_line_simple(self):
        """Parse simple chain:PAIR format."""
        result = parse_intent_line("arbitrum_one:WETH/USDC")
        assert result is not None
        assert result.chain == "arbitrum_one"
        assert result.token_a == "WETH"
        assert result.token_b == "USDC"
    
    def test_valid_line_with_whitespace(self):
        """Handles leading/trailing whitespace."""
        result = parse_intent_line("  base:ETH/USDC  ")
        assert result is not None
        assert result.chain == "base"
        assert result.token_a == "ETH"
        assert result.token_b == "USDC"
    
    def test_comment_line(self):
        """Comment lines return None."""
        assert parse_intent_line("# This is a comment") is None
        assert parse_intent_line("  # Indented comment") is None
    
    def test_empty_line(self):
        """Empty lines return None."""
        assert parse_intent_line("") is None
        assert parse_intent_line("   ") is None
    
    def test_malformed_no_colon(self):
        """Malformed line without colon returns None."""
        assert parse_intent_line("arbitrum_one WETH/USDC") is None
    
    def test_malformed_no_slash(self):
        """Malformed pair without slash returns None."""
        assert parse_intent_line("arbitrum_one:WETHUSDC") is None
    
    def test_uppercase_normalization(self):
        """Tokens are normalized to uppercase."""
        result = parse_intent_line("base:weth/usdc")
        assert result.token_a == "WETH"
        assert result.token_b == "USDC"
    
    def test_chain_not_normalized(self):
        """Chain key is NOT uppercased (preserve snake_case)."""
        result = parse_intent_line("arbitrum_one:WETH/USDC")
        assert result.chain == "arbitrum_one"


class TestIntentUniverse:
    """Tests for IntentUniverse class."""
    
    def test_empty_universe(self):
        """Empty universe has no pairs."""
        universe = IntentUniverse()
        assert len(universe) == 0
        assert universe.get_pairs_for_chain("arbitrum_one") == []
    
    def test_add_pair(self):
        """Can add pairs to universe."""
        universe = IntentUniverse()
        pair = IntentPair(chain="arbitrum_one", token_a="WETH", token_b="USDC")
        universe.add_pair(pair)
        
        assert len(universe) == 1
        arbitrum_pairs = universe.get_pairs_for_chain("arbitrum_one")
        assert len(arbitrum_pairs) == 1
        assert arbitrum_pairs[0].token_a == "WETH"
    
    def test_duplicate_handling(self):
        """Multiple adds keep all (no dedup in add_pair)."""
        universe = IntentUniverse()
        pair = IntentPair(chain="arbitrum_one", token_a="WETH", token_b="USDC")
        universe.add_pair(pair)
        universe.add_pair(pair)
        
        # add_pair doesn't dedupe - that's load_intent's job
        assert len(universe) == 2
    
    def test_chain_filtering(self):
        """get_pairs_for_chain filters by chain."""
        universe = IntentUniverse()
        universe.add_pair(IntentPair(chain="arbitrum_one", token_a="WETH", token_b="USDC"))
        universe.add_pair(IntentPair(chain="base", token_a="ETH", token_b="USDC"))
        universe.add_pair(IntentPair(chain="arbitrum_one", token_a="ARB", token_b="WETH"))
        
        arbitrum_pairs = universe.get_pairs_for_chain("arbitrum_one")
        assert len(arbitrum_pairs) == 2
        
        base_pairs = universe.get_pairs_for_chain("base")
        assert len(base_pairs) == 1
    
    def test_chains_list(self):
        """get_all_chains returns unique chains."""
        universe = IntentUniverse()
        universe.add_pair(IntentPair(chain="arbitrum_one", token_a="WETH", token_b="USDC"))
        universe.add_pair(IntentPair(chain="base", token_a="ETH", token_b="USDC"))
        universe.add_pair(IntentPair(chain="arbitrum_one", token_a="ARB", token_b="WETH"))
        
        chains = universe.get_all_chains()
        assert set(chains) == {"arbitrum_one", "base"}


class TestLoadIntent:
    """Tests for load_intent function with real intent.txt."""
    
    def test_load_intent_returns_universe(self):
        """load_intent returns IntentUniverse."""
        universe = load_intent()
        assert isinstance(universe, IntentUniverse)
    
    def test_intent_has_pairs(self):
        """Intent file contains pairs."""
        universe = load_intent()
        # intent.txt should have at least some pairs
        assert len(universe) > 0
    
    def test_intent_has_arbitrum(self):
        """Intent file has Arbitrum pairs."""
        universe = load_intent()
        arbitrum_pairs = universe.get_pairs_for_chain("arbitrum_one")
        # Based on intent.txt, should have pairs
        assert len(arbitrum_pairs) >= 1


class TestSingleton:
    """Tests for singleton behavior."""
    
    def test_singleton_returns_same_instance(self):
        """get_intent_universe returns same instance."""
        clear_intent_cache()
        u1 = get_intent_universe()
        u2 = get_intent_universe()
        assert u1 is u2
    
    def test_reset_clears_singleton(self):
        """clear_intent_cache clears the singleton."""
        u1 = get_intent_universe()
        clear_intent_cache()
        u2 = get_intent_universe()
        # Should be a new instance (same content, different object)
        assert u1 is not u2


class TestCanonicalOrdering:
    """Tests for deterministic ordering."""
    
    def test_pairs_order_stable(self):
        """Pairs maintain stable insertion order."""
        universe = IntentUniverse()
        universe.add_pair(IntentPair(chain="arbitrum_one", token_a="WETH", token_b="USDC"))
        universe.add_pair(IntentPair(chain="arbitrum_one", token_a="ARB", token_b="WETH"))
        universe.add_pair(IntentPair(chain="arbitrum_one", token_a="LINK", token_b="WETH"))
        
        pairs = universe.get_pairs_for_chain("arbitrum_one")
        token_as = [p.token_a for p in pairs]
        # Should maintain insertion order
        assert token_as == ["WETH", "ARB", "LINK"]
