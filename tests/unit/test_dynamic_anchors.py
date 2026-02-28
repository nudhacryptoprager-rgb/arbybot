# PATH: tests/unit/test_dynamic_anchors.py
"""
Unit tests for dynamic anchors with direction-awareness (v2.9.0).

Tests the fix for PRICE_SANITY_FAILED bug where anchors were stored
without direction normalization, causing ARB/WETH and LINK/WETH to fail
price sanity checks.
"""

import time
from unittest import mock

import pytest

from strategy.dynamic_anchors import (
    DynamicAnchorManager,
    canonicalize_pair,
    canonicalize_pair_with_direction,
    reset_anchor_manager,
)


class TestCanonicalizePair:
    """Tests for canonicalize_pair function."""
    
    def test_alphabetical_sort(self):
        """Pair tokens should be sorted alphabetically."""
        assert canonicalize_pair("WETH/USDC") == "USDC/WETH"
        assert canonicalize_pair("ARB/WETH") == "ARB/WETH"
        assert canonicalize_pair("LINK/WETH") == "LINK/WETH"
        assert canonicalize_pair("WBTC/USDC") == "USDC/WBTC"
    
    def test_already_canonical(self):
        """Already canonical pairs should be unchanged."""
        assert canonicalize_pair("ARB/WETH") == "ARB/WETH"
        assert canonicalize_pair("LINK/USDC") == "LINK/USDC"
    
    def test_invalid_pair(self):
        """Invalid pairs should be returned unchanged."""
        assert canonicalize_pair("WETH") == "WETH"
        assert canonicalize_pair("A/B/C") == "A/B/C"


class TestCanonicalizePairWithDirection:
    """Tests for canonicalize_pair_with_direction function."""
    
    def test_detects_inversion_when_tokens_swapped(self):
        """Should detect when pair direction is inverted after canonicalization."""
        # WETH/USDC -> USDC/WETH (inverted, WETH moved from first to second)
        canonical, is_inverted = canonicalize_pair_with_direction("WETH/USDC")
        assert canonical == "USDC/WETH"
        assert is_inverted is True
    
    def test_no_inversion_when_already_canonical(self):
        """Should not be inverted when already in canonical order."""
        # ARB/WETH -> ARB/WETH (not inverted, ARB < WETH alphabetically)
        canonical, is_inverted = canonicalize_pair_with_direction("ARB/WETH")
        assert canonical == "ARB/WETH"
        assert is_inverted is False
    
    def test_arb_weth_direction(self):
        """ARB/WETH specific test - was the failing case."""
        # ARB/WETH is already canonical (ARB < WETH alphabetically)
        canonical, is_inverted = canonicalize_pair_with_direction("ARB/WETH")
        assert canonical == "ARB/WETH"
        assert is_inverted is False
        
        # WETH/ARB needs inversion
        canonical, is_inverted = canonicalize_pair_with_direction("WETH/ARB")
        assert canonical == "ARB/WETH"
        assert is_inverted is True
    
    def test_link_weth_direction(self):
        """LINK/WETH specific test - was the failing case."""
        # LINK/WETH is already canonical (LINK < WETH alphabetically)
        canonical, is_inverted = canonicalize_pair_with_direction("LINK/WETH")
        assert canonical == "LINK/WETH"
        assert is_inverted is False
        
        # WETH/LINK needs inversion
        canonical, is_inverted = canonicalize_pair_with_direction("WETH/LINK")
        assert canonical == "LINK/WETH"
        assert is_inverted is True


class TestAnchorDirectionAwareness:
    """
    Tests that anchor prices are stored and retrieved with correct direction.
    
    This is the critical fix for the PRICE_SANITY_FAILED bug where:
    - ARB/WETH had anchor_price=20210.73 but price_exact=0.000049
    - The anchor was inverted relative to the price direction
    """
    
    def setup_method(self):
        """Reset anchor manager before each test."""
        reset_anchor_manager()
        self.manager = DynamicAnchorManager(load_cache=False)
    
    def test_record_and_get_same_direction(self):
        """Recording and getting with same direction should return same price."""
        # Record a price for ARB/WETH (0.000049 WETH per ARB)
        self.manager.record_quote("ARB/WETH", 0.000049, "uniswap_v3", 500, 12345)
        self.manager.record_quote("ARB/WETH", 0.000050, "uniswap_v3", 500, 12346)
        self.manager.record_quote("ARB/WETH", 0.000051, "uniswap_v3", 500, 12347)
        
        # Get anchor for same direction
        anchor, source = self.manager.get_anchor("ARB/WETH")
        assert source == "dynamic"
        assert anchor is not None
        # Should be close to median of [0.000049, 0.000050, 0.000051] = 0.000050
        assert abs(anchor - 0.000050) < 0.00001
    
    def test_record_and_get_inverted_direction(self):
        """Recording in one direction and getting inverted should return inverted price."""
        # Record a price for ARB/WETH (0.000049 WETH per ARB)
        self.manager.record_quote("ARB/WETH", 0.000049, "uniswap_v3", 500, 12345)
        self.manager.record_quote("ARB/WETH", 0.000050, "uniswap_v3", 500, 12346)
        self.manager.record_quote("ARB/WETH", 0.000051, "uniswap_v3", 500, 12347)
        
        # Get anchor for INVERTED direction (WETH/ARB)
        anchor, source = self.manager.get_anchor("WETH/ARB")
        assert source == "dynamic"
        assert anchor is not None
        # Should be inverted: 1 / 0.000050 = 20000
        assert abs(anchor - 20000) < 500  # Allow some tolerance
    
    def test_record_inverted_get_canonical(self):
        """Recording in inverted direction should store correctly for canonical retrieval."""
        # Record a price for WETH/ARB (20000 ARB per WETH)
        # This should be stored as ARB/WETH = 1/20000 = 0.00005 WETH per ARB
        self.manager.record_quote("WETH/ARB", 20000, "uniswap_v3", 500, 12345)
        self.manager.record_quote("WETH/ARB", 20500, "uniswap_v3", 500, 12346)
        self.manager.record_quote("WETH/ARB", 21000, "uniswap_v3", 500, 12347)
        
        # Get anchor for canonical direction (ARB/WETH)
        anchor, source = self.manager.get_anchor("ARB/WETH")
        assert source == "dynamic"
        assert anchor is not None
        # Should be close to 1/20500 = 0.0000488
        assert abs(anchor - 0.0000488) < 0.00001
    
    def test_mixed_direction_quotes_combine_correctly(self):
        """Quotes from both directions should combine correctly."""
        # Record some ARB/WETH quotes (0.00005 WETH per ARB)
        self.manager.record_quote("ARB/WETH", 0.00005, "uniswap_v3", 500, 12345)
        self.manager.record_quote("ARB/WETH", 0.00005, "sushiswap_v3", 500, 12346)
        
        # Record some WETH/ARB quotes (20000 ARB per WETH = 0.00005 WETH per ARB)
        self.manager.record_quote("WETH/ARB", 20000, "uniswap_v3", 3000, 12347)
        
        # All should be stored as ~0.00005 in ARB/WETH direction
        anchor, source = self.manager.get_anchor("ARB/WETH")
        assert source == "dynamic"
        assert anchor is not None
        # Median should be 0.00005
        assert abs(anchor - 0.00005) < 0.00001
    
    def test_price_sanity_scenario_arb_weth(self):
        """
        Reproduce the bug scenario: ARB/WETH anchor was 20210.73 but price was 0.000049.
        
        After fix, anchor should be in same direction as price_exact.
        """
        # Simulate: someone recorded WETH/ARB price (20210.73 ARB per WETH)
        # but the quote request is for ARB/WETH (0.000049 WETH per ARB)
        price_weth_per_arb = 0.000049
        price_arb_per_weth = 1.0 / price_weth_per_arb  # ~20408
        
        # Record as WETH/ARB direction
        self.manager.record_quote("WETH/ARB", price_arb_per_weth, "uniswap_v3", 500, 12345)
        self.manager.record_quote("WETH/ARB", price_arb_per_weth, "uniswap_v3", 500, 12346)
        self.manager.record_quote("WETH/ARB", price_arb_per_weth, "uniswap_v3", 500, 12347)
        
        # Now get anchor for ARB/WETH direction (what price_exact uses)
        anchor, source = self.manager.get_anchor("ARB/WETH")
        assert source == "dynamic"
        assert anchor is not None
        
        # Anchor should be close to price_exact (0.000049), NOT the inverted 20408
        assert abs(anchor - price_weth_per_arb) < 0.0001
        
        # Price sanity check: |anchor - price| / anchor should be small
        deviation = abs(anchor - price_weth_per_arb) / anchor
        assert deviation < 0.01  # Less than 1% deviation


class TestAnchorDetailedDirectionAwareness:
    """Tests for get_anchor_detailed with direction awareness."""
    
    def setup_method(self):
        """Reset anchor manager before each test."""
        reset_anchor_manager()
        self.manager = DynamicAnchorManager(load_cache=False)
    
    def test_get_anchor_detailed_inverted(self):
        """get_anchor_detailed should also respect direction."""
        # Record ARB/WETH quotes
        self.manager.record_quote("ARB/WETH", 0.00005, "uniswap_v3", 500, 12345)
        self.manager.record_quote("ARB/WETH", 0.00005, "uniswap_v3", 500, 12346)
        self.manager.record_quote("ARB/WETH", 0.00005, "uniswap_v3", 500, 12347)
        
        # Get detailed for inverted direction
        details = self.manager.get_anchor_detailed("WETH/ARB")
        assert details["anchor_source"] == "dynamic"
        assert details["anchor_value"] is not None
        # Should be inverted: 1/0.00005 = 20000
        assert abs(details["anchor_value"] - 20000) < 500
