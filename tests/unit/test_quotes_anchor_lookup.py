# PATH: tests/unit/test_quotes_anchor_lookup.py
"""
Tests for case-insensitive anchor price lookup in quotes.py.

v3.2.24: Added to verify wstETH/WSTETH case normalization fix.
v3.2.25: Extended with lookup_token_usd_price_ci tests.
"""

import pytest
from strategy.quotes import lookup_anchor_price_ci, lookup_token_usd_price_ci


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


class TestLookupTokenUsdPriceCI:
    """Tests for lookup_token_usd_price_ci function (v3.2.25)."""
    
    def test_direct_match(self):
        """Test direct key match (fast path)."""
        usd_prices = {"WETH": 2100.0, "ARB": 0.105}
        
        assert lookup_token_usd_price_ci(usd_prices, "WETH") == 2100.0
        assert lookup_token_usd_price_ci(usd_prices, "ARB") == 0.105
    
    def test_case_insensitive_match(self):
        """Test case-insensitive matching for wstETH variants."""
        usd_prices = {"wstETH": 2444.0, "rETH": 2295.0}
        
        # Uppercase lookup should match mixed-case key
        assert lookup_token_usd_price_ci(usd_prices, "WSTETH") == 2444.0
        assert lookup_token_usd_price_ci(usd_prices, "wsteth") == 2444.0
        assert lookup_token_usd_price_ci(usd_prices, "RETH") == 2295.0
    
    def test_no_match_with_default(self):
        """Test when no matching key exists, returns default."""
        usd_prices = {"WETH": 2100.0}
        
        assert lookup_token_usd_price_ci(usd_prices, "UNKNOWN", default=1.0) == 1.0
        assert lookup_token_usd_price_ci(usd_prices, "ARB") is None  # No default = None
    
    def test_empty_dict(self):
        """Test empty USD price dictionary."""
        assert lookup_token_usd_price_ci({}, "WETH") is None
        assert lookup_token_usd_price_ci({}, "WETH", default=2100.0) == 2100.0
