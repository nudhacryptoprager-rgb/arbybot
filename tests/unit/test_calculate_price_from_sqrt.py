# PATH: tests/unit/test_calculate_price_from_sqrt.py
"""
Tests for calculate_price_from_sqrt in strategy/quotes.py

v2.1.0-fix: Ensures WBTC decimals don't cause overflow
"""

import pytest
from decimal import Decimal
from strategy.quotes import calculate_price_from_sqrt


class TestCalculatePriceFromSqrt:
    """Tests for sqrtPriceX96 to price calculation."""

    def test_weth_usdc_price(self):
        """Test WETH/USDC price calculation (18 vs 6 decimals)."""
        # WETH = 18 decimals, USDC = 6 decimals
        # Assume WETH price ~$2600
        # sqrtPriceX96 example for ~2600 price
        # sqrtPrice = sqrt(2600 * 10^(18-6)) * 2^96 = sqrt(2600e12) * 2^96
        # sqrt(2600e12) ≈ 1.612e6
        # But Uniswap stores price as token1/token0, so depends on order
        
        # Use a simplified test with known values
        # sqrtPriceX96 = 79228162514264337593543950336 = 2^96 (price = 1)
        sqrt_price = 2 ** 96
        
        # Same decimals - price should be 1
        weth_addr = "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1"
        usdc_addr = "0xaf88d065e77c8cC2239327C5EDb3A432268e5831"
        
        price = calculate_price_from_sqrt(
            sqrt_price,
            weth_addr,  # token_in (higher address = "token1")
            usdc_addr,  # token_out (lower address = "token0")
            18,  # WETH decimals
            6,   # USDC decimals
        )
        
        assert price is not None
        # The exact value depends on token order, but should be finite
        assert price > Decimal(0)
        assert price < Decimal(1e20)  # Sanity check

    def test_wbtc_weth_no_overflow(self):
        """v2.1.0-fix: WBTC/WETH must not overflow with 8 vs 18 decimals."""
        # WBTC = 8 decimals, WETH = 18 decimals
        # This is the pair that was causing decimal.InvalidOperation
        
        # sqrtPriceX96 = 2^96 (price = 1 before decimal adjustment)
        sqrt_price = 2 ** 96
        
        # WBTC address (lower hex = token0)
        wbtc_addr = "0x2f2a2543B76A4166549F7aaB2e75Bef0aefC5B0f"
        # WETH address (higher hex = token1)
        weth_addr = "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1"
        
        # This should NOT raise decimal.InvalidOperation
        price = calculate_price_from_sqrt(
            sqrt_price,
            wbtc_addr,  # token_in (lower = token0)
            weth_addr,  # token_out (higher = token1)
            8,   # WBTC decimals
            18,  # WETH decimals
        )
        
        assert price is not None
        # Price should be finite and reasonable
        assert price > Decimal(0)
        # With 8-18 = -10 decimals diff, raw_price * 10^-10 should be small
        assert price < Decimal(1e20)

    def test_wbtc_usdc_extreme_decimals(self):
        """Test extreme decimal difference (8 vs 6 = small positive diff)."""
        sqrt_price = 2 ** 96
        
        wbtc_addr = "0x2f2a2543B76A4166549F7aaB2e75Bef0aefC5B0f"
        usdc_addr = "0xaf88d065e77c8cC2239327C5EDb3A432268e5831"
        
        price = calculate_price_from_sqrt(
            sqrt_price,
            wbtc_addr,
            usdc_addr,
            8,
            6,
        )
        
        assert price is not None
        assert price > Decimal(0)

    def test_negative_decimal_diff(self):
        """Test that negative decimal differences work correctly."""
        sqrt_price = 2 ** 96
        
        # Force a -10 decimal diff (simulating WBTC token_in with WETH token_out)
        token_in = "0x1111111111111111111111111111111111111111"  # Lower = token0
        token_out = "0x2222222222222222222222222222222222222222"  # Higher = token1
        
        price = calculate_price_from_sqrt(
            sqrt_price,
            token_in,
            token_out,
            8,   # Low decimals
            18,  # High decimals
        )
        
        # Should use Decimal(10) ** -10 without overflow
        assert price is not None
        # The price should be 10^-10 (very small)
        assert price == Decimal('0.0000000001')

    def test_zero_sqrt_price_returns_none(self):
        """Zero sqrt price should return None."""
        price = calculate_price_from_sqrt(
            0,
            "0x1111111111111111111111111111111111111111",
            "0x2222222222222222222222222222222222222222",
            18,
            18,
        )
        assert price is None

    def test_none_sqrt_price_returns_none(self):
        """None sqrt price should return None."""
        price = calculate_price_from_sqrt(
            None,
            "0x1111111111111111111111111111111111111111",
            "0x2222222222222222222222222222222222222222",
            18,
            18,
        )
        assert price is None
