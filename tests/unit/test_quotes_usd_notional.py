# PATH: tests/unit/test_quotes_usd_notional.py
"""
Tests for USD-notional sizing in strategy/quotes.py

M4.2 CONTRACT:
- Quotes should use consistent USD notional (not "1 token")
- This makes profit comparisons valid across different token pairs
"""

import pytest
from strategy.quotes import calculate_amount_in_wei, DEFAULT_TOKEN_USD_PRICES


class TestUsdNotionalSizing:
    """Test USD-notional sizing logic."""
    
    def test_weth_sizing_1000_usd(self):
        """$1000 worth of WETH at $2000/ETH = 0.5 ETH."""
        amount = calculate_amount_in_wei("WETH", 18, 1000.0)
        # 0.5 ETH = 500000000000000000 wei
        assert amount == 500_000_000_000_000_000
    
    def test_usdc_sizing_1000_usd(self):
        """$1000 worth of USDC = 1000 USDC."""
        amount = calculate_amount_in_wei("USDC", 6, 1000.0)
        # 1000 USDC with 6 decimals = 1_000_000_000
        assert amount == 1_000_000_000
    
    def test_usdt_sizing_1000_usd(self):
        """$1000 worth of USDT = 1000 USDT."""
        amount = calculate_amount_in_wei("USDT", 6, 1000.0)
        assert amount == 1_000_000_000
    
    def test_arb_sizing(self):
        """ARB sizing uses correct USD price."""
        amount = calculate_amount_in_wei("ARB", 18, 1000.0)
        # ARB at $0.70 -> 1000/0.70 ≈ 1428.57 ARB
        expected = int(1000.0 / 0.70 * 10**18)
        assert amount == expected
    
    def test_wbtc_sizing(self):
        """WBTC sizing with 8 decimals."""
        amount = calculate_amount_in_wei("WBTC", 8, 1000.0)
        # WBTC at $34000 -> 1000/34000 ≈ 0.02941 WBTC
        expected = int(1000.0 / 34000.0 * 10**8)
        assert amount == expected
    
    def test_custom_price_override(self):
        """Custom prices override defaults."""
        custom_prices = {"WETH": 3000.0}  # Higher ETH price
        amount = calculate_amount_in_wei("WETH", 18, 1000.0, custom_prices)
        # At $3000/ETH, $1000 = 0.333 ETH
        expected = int(1000.0 / 3000.0 * 10**18)
        assert amount == expected
    
    def test_unknown_token_defaults_to_1_usd(self):
        """Unknown tokens default to $1 price."""
        amount = calculate_amount_in_wei("UNKNOWN_TOKEN", 18, 1000.0)
        # At $1/token, $1000 = 1000 tokens
        expected = int(1000 * 10**18)
        assert amount == expected
    
    def test_zero_notional(self):
        """Zero USD notional gives zero amount."""
        amount = calculate_amount_in_wei("WETH", 18, 0.0)
        assert amount == 0
    
    def test_large_notional(self):
        """Large USD notional works correctly."""
        amount = calculate_amount_in_wei("WETH", 18, 1_000_000.0)
        # $1M / $2000 = 500 ETH
        expected = int(500 * 10**18)
        assert amount == expected


class TestDefaultTokenPrices:
    """Test default token price mappings."""
    
    def test_major_tokens_have_prices(self):
        """Major tokens have default prices."""
        required = ["WETH", "USDC", "USDT", "WBTC", "ARB", "LINK"]
        for token in required:
            assert token in DEFAULT_TOKEN_USD_PRICES
            assert DEFAULT_TOKEN_USD_PRICES[token] > 0
    
    def test_stablecoin_prices(self):
        """Stablecoins are priced at $1."""
        for stable in ["USDC", "USDT", "DAI"]:
            assert DEFAULT_TOKEN_USD_PRICES[stable] == 1.0
    
    def test_eth_alias(self):
        """ETH is aliased to same price as WETH."""
        assert DEFAULT_TOKEN_USD_PRICES["ETH"] == DEFAULT_TOKEN_USD_PRICES["WETH"]
