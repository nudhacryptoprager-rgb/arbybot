# PATH: tests/unit/test_same_dex_policy.py
"""
Tests for same-dex policy tracking in spread signals.

v2.5.0: Tests that SAME_DEX_FEE_TIER and SAME_DEX_EXCLUDED are tracked correctly.
"""
import pytest
from decimal import Decimal


def make_quote(dex_id, price, fee=500, token_in="WETH", token_out="USDC"):
    """Helper to create a minimal quote dict."""
    return {
        "dex_id": dex_id,
        "token_in": token_in,
        "token_out": token_out,
        "price_exact": str(price),
        "fee": fee,
        "quote_source": "quoter_v2",
        "amount_in_wei": 1000000000000000000,
        "amount_out_wei": int(float(price) * 1000000),
        "gate_passed": True,
        "is_diagnostic_only": False,
        "pool_address": f"0xPool_{dex_id}_{fee}",  # Required by spread computation
    }


class TestSameDexDetection:
    """Tests for is_same_dex flag in spread signals."""
    
    def test_same_dex_detected(self):
        """is_same_dex=True when buy_dex == sell_dex."""
        from strategy.spreads import compute_spread_signals
        
        quotes = [
            make_quote("uniswap_v3", "1920.00", fee=500),
            make_quote("uniswap_v3", "1925.00", fee=3000),  # Same DEX, different fee
        ]
        config = {"require_cross_dex": False}
        
        signals = compute_spread_signals(quotes, config, 1000, [])
        
        assert len(signals) >= 1
        sig = signals[0]
        
        assert sig["is_same_dex"] is True
        assert "SAME_DEX_FEE_TIER" in sig["confidence_reasons"]
    
    def test_cross_dex_not_flagged(self):
        """is_same_dex=False when buy_dex != sell_dex."""
        from strategy.spreads import compute_spread_signals
        
        quotes = [
            make_quote("uniswap_v3", "1920.00", fee=500),
            make_quote("sushiswap_v3", "1925.00", fee=500),  # Different DEX
        ]
        config = {"require_cross_dex": False}
        
        signals = compute_spread_signals(quotes, config, 1000, [])
        
        assert len(signals) >= 1
        sig = signals[0]
        
        assert sig["is_same_dex"] is False
        assert "SAME_DEX_FEE_TIER" not in sig["confidence_reasons"]


class TestSameDexExclusion:
    """Tests for is_same_dex_excluded with require_cross_dex=True."""
    
    def test_same_dex_excluded_when_require_cross_dex(self):
        """is_same_dex_excluded=True when same-dex and require_cross_dex=True."""
        from strategy.spreads import compute_spread_signals
        
        quotes = [
            make_quote("uniswap_v3", "1920.00", fee=500),
            make_quote("uniswap_v3", "1925.00", fee=3000),  # Same DEX
        ]
        config = {"require_cross_dex": True}  # Enable cross-dex requirement
        
        signals = compute_spread_signals(quotes, config, 1000, [])
        
        assert len(signals) >= 1
        sig = signals[0]
        
        assert sig["is_same_dex"] is True
        assert sig["is_same_dex_excluded"] is True
        assert sig["is_excluded_spread"] is True  # Should be excluded
        assert "SAME_DEX_EXCLUDED" in sig["confidence_reasons"]
        assert sig["confidence"] == "suspect"
    
    def test_same_dex_not_excluded_when_require_cross_dex_false(self):
        """is_same_dex_excluded=False when require_cross_dex=False."""
        from strategy.spreads import compute_spread_signals
        
        quotes = [
            make_quote("uniswap_v3", "1920.00", fee=500),
            make_quote("uniswap_v3", "1925.00", fee=3000),  # Same DEX
        ]
        config = {"require_cross_dex": False}
        
        signals = compute_spread_signals(quotes, config, 1000, [])
        
        assert len(signals) >= 1
        sig = signals[0]
        
        assert sig["is_same_dex"] is True
        assert sig["is_same_dex_excluded"] is False
        assert "SAME_DEX_EXCLUDED" not in sig["confidence_reasons"]
    
    def test_cross_dex_not_affected_by_require_cross_dex(self):
        """Cross-DEX spreads not excluded even when require_cross_dex=True."""
        from strategy.spreads import compute_spread_signals
        
        quotes = [
            make_quote("uniswap_v3", "1920.00", fee=500),
            make_quote("sushiswap_v3", "1925.00", fee=500),  # Different DEX
        ]
        config = {"require_cross_dex": True}
        
        signals = compute_spread_signals(quotes, config, 1000, [])
        
        assert len(signals) >= 1
        sig = signals[0]
        
        assert sig["is_same_dex"] is False
        assert sig["is_same_dex_excluded"] is False
        assert "SAME_DEX_EXCLUDED" not in sig["confidence_reasons"]
