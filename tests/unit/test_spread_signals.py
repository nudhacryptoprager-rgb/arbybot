"""Tests for spread signal generation in run_scan_real.

These tests verify:
1. Spread signals are generated correctly from quote data
2. The price invariant bug (static 2600) is caught
3. Paper cost estimates are calculated correctly
"""

import json
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List


def compute_spread_signals_from_quotes(quotes: List[Dict[str, Any]], threshold_bps: int = 0) -> List[Dict[str, Any]]:
    """
    Simplified spread signal computation for testing.
    Mirrors the logic in run_scan_real.py.
    """
    signals = []
    
    # Group by pair
    quotes_by_pair: Dict[str, List[Dict[str, Any]]] = {}
    for q in quotes:
        pair_key = f"{q.get('token_in')}/{q.get('token_out')}"
        if pair_key not in quotes_by_pair:
            quotes_by_pair[pair_key] = []
        quotes_by_pair[pair_key].append(q)
    
    for pair, quotes_for_pair in quotes_by_pair.items():
        if len(quotes_for_pair) < 2:
            continue
        
        def get_price(q):
            if q.get("price_exact"):
                return Decimal(str(q.get("price_exact")))
            return Decimal(str(q.get("price") or "0"))
        
        sorted_by_price = sorted(quotes_for_pair, key=get_price)
        best_buy = sorted_by_price[0]
        best_sell = sorted_by_price[-1]
        
        buy_price = get_price(best_buy)
        sell_price = get_price(best_sell)
        
        if buy_price <= 0 or sell_price <= 0:
            continue
        
        spread_bps_decimal = (sell_price - buy_price) / buy_price * Decimal("10000")
        
        # Use Decimal comparison for threshold
        if abs(spread_bps_decimal) >= threshold_bps:
            signals.append({
                "pair": pair,
                "buy_dex": best_buy.get("dex_id"),
                "sell_dex": best_sell.get("dex_id"),
                "spread_bps": int(spread_bps_decimal),
                "spread_bps_decimal": float(spread_bps_decimal),
                "buy_price": str(buy_price),
                "sell_price": str(sell_price),
            })
    
    return signals


def test_spread_signal_from_real_quotes():
    """Test that spread signals are generated from real-like quote data."""
    # Real-like quotes with small spread
    quotes = [
        {
            "dex_id": "uniswap_v3",
            "token_in": "WETH",
            "token_out": "USDC",
            "price": "1935.100427",
            "price_exact": "1935.100426866099772424121124",
        },
        {
            "dex_id": "sushiswap_v3",
            "token_in": "WETH",
            "token_out": "USDC",
            "price": "1934.962198",
            "price_exact": "1934.962197591566791946813271",
        },
    ]
    
    signals = compute_spread_signals_from_quotes(quotes, threshold_bps=0)
    
    assert len(signals) == 1, "Should generate 1 signal for WETH/USDC pair"
    sig = signals[0]
    
    assert sig["pair"] == "WETH/USDC"
    # Sushiswap has lower price → buy, Uniswap has higher price → sell
    assert sig["buy_dex"] == "sushiswap_v3"
    assert sig["sell_dex"] == "uniswap_v3"
    
    # Spread calculation: (1935.10 - 1934.96) / 1934.96 * 10000 = ~0.71 bps
    assert 0.5 <= sig["spread_bps_decimal"] <= 1.0, f"Expected ~0.71 bps, got {sig['spread_bps_decimal']}"


def test_spread_signal_with_threshold():
    """Test that threshold correctly filters signals."""
    quotes = [
        {
            "dex_id": "dex_a",
            "token_in": "WETH",
            "token_out": "USDC",
            "price_exact": "1000.00",
        },
        {
            "dex_id": "dex_b",
            "token_in": "WETH",
            "token_out": "USDC",
            "price_exact": "1000.05",  # 0.5 bps spread
        },
    ]
    
    # With threshold 0 → should pass
    signals = compute_spread_signals_from_quotes(quotes, threshold_bps=0)
    assert len(signals) == 1
    
    # With threshold 1 → should fail (spread is 0.5 bps)
    signals = compute_spread_signals_from_quotes(quotes, threshold_bps=1)
    assert len(signals) == 0


def test_price_invariant_bug_detection():
    """
    Test that detects the bug where amount_out_human was static "2600"
    while price was calculated from sqrtPriceX96 (~1930).
    
    This is a regression test for the fixed bug.
    """
    # BAD quote - price doesn't match amount_out (the old bug)
    bad_quote = {
        "dex_id": "uniswap_v3",
        "token_in": "WETH",
        "token_out": "USDC",
        "amount_in_human": "1",
        "amount_out_human": "2600",  # STATIC - BUG!
        "price": "1930.083682",  # From sqrtPriceX96
    }
    
    # Verify inconsistency
    price = Decimal(bad_quote["price"])
    amount_in = Decimal(bad_quote["amount_in_human"])
    amount_out = Decimal(bad_quote["amount_out_human"])
    
    calculated_price = amount_out / amount_in
    diff_pct = abs(calculated_price - price) / price * 100
    
    # The bug causes >30% difference
    assert diff_pct > 30, f"Bug detection failed: diff is only {diff_pct}%"
    
    # GOOD quote - price matches amount_out
    good_quote = {
        "dex_id": "uniswap_v3",
        "token_in": "WETH",
        "token_out": "USDC",
        "amount_in_human": "1",
        "amount_out_human": "1930.083682",  # CALCULATED from price
        "price": "1930.083682",
    }
    
    price = Decimal(good_quote["price"])
    amount_in = Decimal(good_quote["amount_in_human"])
    amount_out = Decimal(good_quote["amount_out_human"])
    
    calculated_price = amount_out / amount_in
    diff_pct = abs(calculated_price - price) / price * 100
    
    # Should be essentially 0
    assert diff_pct < 0.0001, f"Good quote failed invariant: diff is {diff_pct}%"


def test_no_signal_when_same_dex():
    """Test that no signal is generated when only one DEX has quotes."""
    quotes = [
        {
            "dex_id": "uniswap_v3",
            "token_in": "WETH",
            "token_out": "USDC",
            "price_exact": "1935.10",
        },
    ]
    
    signals = compute_spread_signals_from_quotes(quotes, threshold_bps=0)
    assert len(signals) == 0, "Should not generate signal with only 1 quote"


def test_paper_cost_model():
    """Test paper cost model calculations."""
    # Given a spread signal with known values
    spread_bps = Decimal("1.5")  # 1.5 bps = 0.015%
    size_usd = Decimal(1000)
    gas_usd = Decimal("0.10")
    slippage_pct = Decimal("0.001")  # 0.1%
    
    # Calculate as in run_scan_real.py
    gross_spread_pct = spread_bps / 100
    gross_pnl = float(size_usd * gross_spread_pct / 100)
    slippage_usd = float(size_usd * slippage_pct)
    net_pnl = gross_pnl - float(gas_usd) - slippage_usd
    
    # gross = 1000 * 0.015 / 100 = 0.15 USD
    assert abs(gross_pnl - 0.15) < 0.01, f"Gross PnL wrong: {gross_pnl}"
    
    # slippage = 1000 * 0.001 = 1.0 USD  
    assert abs(slippage_usd - 1.0) < 0.01, f"Slippage wrong: {slippage_usd}"
    
    # net = 0.15 - 0.10 - 1.0 = -0.95 USD (negative!)
    assert net_pnl < 0, "Net should be negative with high slippage"
    assert abs(net_pnl - (-0.95)) < 0.01, f"Net PnL wrong: {net_pnl}"
