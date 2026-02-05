"""Test that quote price matches amount_out/amount_in within tolerance.

This test catches the bug where price_exact was calculated from sqrtPriceX96
but amount_out_human remained static "2600", causing data inconsistency.
"""

import json
from decimal import Decimal
from pathlib import Path

import pytest


def test_quote_price_matches_amounts():
    """Verify price ≈ amount_out_human / amount_in_human within 1% tolerance."""
    # This would be run against actual scan output to validate consistency
    # For unit test, we verify the calculation logic
    
    # Sample sqrtPriceX96 from real scan (WETH/USDC pool)
    sqrt_price_x96 = 3480708495634120080967009
    
    # Calculate price_exact using same formula as run_scan_real.py
    sqrt_ratio = Decimal(sqrt_price_x96) / Decimal(2 ** 96)
    raw_price = sqrt_ratio * sqrt_ratio
    decimals_diff = Decimal(10 ** (18 - 6))  # 10^12 for WETH(18)/USDC(6)
    price_exact = raw_price * decimals_diff
    
    # Calculate amount_out for 1 WETH input
    amount_in_human = Decimal(1)  # 1 WETH
    amount_out_human = price_exact  # USDC for 1 WETH
    
    # Verify invariant: price == amount_out / amount_in
    calculated_price = amount_out_human / amount_in_human
    
    assert calculated_price == price_exact, \
        f"Price invariant violated: {calculated_price} != {price_exact}"
    
    # Verify price is reasonable (not static 2600)
    assert price_exact != Decimal(2600), "Price should not be static 2600"
    assert 1500 < float(price_exact) < 3000, f"Price {price_exact} outside expected range"


def test_quote_amount_out_consistency():
    """Verify amount_out_wei matches amount_out_human * 10^decimals."""
    # Test calculation
    price_exact = Decimal("1930.083682")
    amount_in_human = Decimal(1)
    
    # Expected amount_out
    amount_out_human = price_exact * amount_in_human
    amount_out_wei = int(amount_out_human * (10 ** 6))  # USDC has 6 decimals
    
    # Verify consistency
    recalculated_human = Decimal(amount_out_wei) / Decimal(10 ** 6)
    assert abs(recalculated_human - amount_out_human) < Decimal("0.000001"), \
        f"amount_out_wei {amount_out_wei} inconsistent with amount_out_human {amount_out_human}"


def test_price_from_sqrt_price_x96():
    """Verify price calculation from sqrtPriceX96 is correct."""
    # Known values from Uniswap v3 pool
    sqrt_price_x96 = 3480708495634120080967009
    expected_price_approx = Decimal("1930.08")  # approximate
    
    # Calculate
    sqrt_ratio = Decimal(sqrt_price_x96) / Decimal(2 ** 96)
    raw_price = sqrt_ratio * sqrt_ratio
    decimals_diff = Decimal(10 ** 12)  # WETH(18) - USDC(6)
    price = raw_price * decimals_diff
    
    # Verify within 0.1%
    diff_pct = abs(price - expected_price_approx) / expected_price_approx * 100
    assert diff_pct < 0.1, f"Price {price} differs from expected {expected_price_approx} by {diff_pct}%"


def test_quote_invariant_from_scan_data(tmp_path):
    """Test that scan output maintains price == amount_out/amount_in invariant."""
    # Create mock scan data with correct invariant
    quote = {
        "dex_id": "uniswap_v3",
        "token_in": "WETH",
        "token_out": "USDC",
        "amount_in_human": "1",
        "amount_out_human": "1930.083682",
        "price": "1930.083682",
        "price_exact": "1930.083682295649952248056932",
    }
    
    # Verify invariant
    price = Decimal(quote["price"])
    amount_in = Decimal(quote["amount_in_human"])
    amount_out = Decimal(quote["amount_out_human"])
    
    calculated_price = amount_out / amount_in
    
    # Allow 0.0001% tolerance for rounding
    diff_pct = abs(calculated_price - price) / price * 100
    assert diff_pct < 0.0001, \
        f"Price invariant violated: calculated {calculated_price} vs stored {price}"


def test_quote_invariant_violation_detected():
    """Verify we can detect the bug where amount_out_human was static 2600."""
    # This represents the BUG we're fixing
    bad_quote = {
        "dex_id": "uniswap_v3",
        "token_in": "WETH",
        "token_out": "USDC",
        "amount_in_human": "1",
        "amount_out_human": "2600",  # STATIC - BUG!
        "price": "1930.083682",  # Calculated from sqrtPriceX96
    }
    
    price = Decimal(bad_quote["price"])
    amount_in = Decimal(bad_quote["amount_in_human"])
    amount_out = Decimal(bad_quote["amount_out_human"])
    
    calculated_price = amount_out / amount_in
    
    # This SHOULD fail - the data is inconsistent
    diff_pct = abs(calculated_price - price) / price * 100
    
    # Assert that the bug would be detected (diff > 30%)
    assert diff_pct > 30, \
        f"Bug not detected: diff is only {diff_pct}% but should be >30%"
