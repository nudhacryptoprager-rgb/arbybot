# PATH: tests/unit/test_quotes_anchor_lookup.py
"""
Tests for case-insensitive anchor price lookup in quotes.py.

v3.2.24: Added to verify wstETH/WSTETH case normalization fix.
"""

import pytest
from strategy.quotes import lookup_anchor_price_ci


class TestLookupAnchorPriceCI:
    """Tests for lookup_anchor_price_ci function."""
    
    def test_direct_match(self):
        """Test direct key match (fast path)."""
        anchors = {"WETH_USDC": 2100.0, "ARB_DAI": 0.40}
        
        assert lookup_anchor_price_ci(anchors, "WETH_USDC") == 2100.0
        assert lookup_anchor_price_ci(anchors, "ARB_DAI") == 0.40
    
    def test_case_insensitive_match(self):
        """Test case-insensitive matching for wstETH variants."""
        anchors = {"wstETH_WETH": 1.15, "rETH_USDC": 2268.0}
        
        # Uppercase lookup should match lowercase key
        assert lookup_anchor_price_ci(anchors, "WSTETH_WETH") == 1.15
        assert lookup_anchor_price_ci(anchors, "wstETH_WETH") == 1.15
        assert lookup_anchor_price_ci(anchors, "WSTETH_weth") == 1.15
        
        # Mixed case matching
        assert lookup_anchor_price_ci(anchors, "RETH_USDC") == 2268.0
        assert lookup_anchor_price_ci(anchors, "reth_usdc") == 2268.0
    
    def test_no_match(self):
        """Test when no matching key exists."""
        anchors = {"WETH_USDC": 2100.0}
        
        assert lookup_anchor_price_ci(anchors, "ARB_DAI") is None
        assert lookup_anchor_price_ci(anchors, "WBTC_TBTC") is None
    
    def test_empty_dict(self):
        """Test empty anchor dictionary."""
        assert lookup_anchor_price_ci({}, "WETH_USDC") is None
    
    def test_preserves_value(self):
        """Test that original value is returned unchanged."""
        anchors = {"WETH_USDC": 2100.12345}
        
        result = lookup_anchor_price_ci(anchors, "weth_usdc")
        assert result == 2100.12345
        assert isinstance(result, float)
