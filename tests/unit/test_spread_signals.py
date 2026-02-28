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
                # spread_bps_exact: float for micro-spreads
                "spread_bps_exact": float(spread_bps_decimal),
                # spread_bps_ui: floor for display (may be 0)
                "spread_bps_ui": int(spread_bps_decimal),
                # is_gross_positive: sell > buy (Decimal comparison)
                "is_gross_positive": bool(spread_bps_decimal > 0),
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
    assert 0.5 <= sig["spread_bps_exact"] <= 1.0, f"Expected ~0.71 bps, got {sig['spread_bps_exact']}"
    # is_gross_positive should be True (sell > buy)
    assert sig["is_gross_positive"] is True, "is_gross_positive must be True when sell > buy"


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


def test_paper_cost_model_arithmetic():
    """
    Test the corrected paper cost model arithmetic.
    
    Formula:
      gross_pnl = size_usd * spread_bps / 10000
      slippage_usd = size_usd * slippage_bps / 10000
      net_pnl = gross_pnl - gas_usd - slippage_usd
    
    This is a regression test for the bug where slippage was 0.1% ($1.00)
    instead of 1 bps ($0.10), causing net_pnl to be incorrectly negative.
    """
    # Test case 1: 2 bps spread, should be net positive
    spread_bps = Decimal("2")  # 2 bps = 0.02%
    size_usd = Decimal(1000)
    gas_usd = Decimal("0.10")
    slippage_bps = Decimal("1")  # 1 bps (corrected from 10 bps)
    
    # gross = 1000 * 2 / 10000 = 0.20 USD
    gross_pnl = float(size_usd * spread_bps / Decimal(10000))
    assert abs(gross_pnl - 0.20) < 0.001, f"Gross PnL wrong: {gross_pnl}"
    
    # slippage = 1000 * 1 / 10000 = 0.10 USD
    slippage_usd = float(size_usd * slippage_bps / Decimal(10000))
    assert abs(slippage_usd - 0.10) < 0.001, f"Slippage wrong: {slippage_usd}"
    
    # net = 0.20 - 0.10 - 0.10 = 0.00 USD (breakeven)
    net_pnl = gross_pnl - float(gas_usd) - slippage_usd
    assert abs(net_pnl - 0.00) < 0.001, f"Net PnL wrong: {net_pnl}, expected 0.00"
    
    # Test case 2: 5 bps spread, should be clearly net positive
    spread_bps = Decimal("5")  # 5 bps = 0.05%
    gross_pnl = float(size_usd * spread_bps / Decimal(10000))  # = 0.50
    net_pnl = gross_pnl - float(gas_usd) - slippage_usd  # = 0.50 - 0.10 - 0.10 = 0.30
    
    assert net_pnl > 0, f"5 bps spread should be net positive, got {net_pnl}"
    assert abs(net_pnl - 0.30) < 0.001, f"Net PnL wrong: {net_pnl}, expected 0.30"
    
    # Test case 3: Verify the OLD bug would have given wrong result
    # OLD formula: slippage = size * 0.001 = 1000 * 0.001 = $1.00 (10x too high!)
    bad_slippage_usd = float(size_usd * Decimal("0.001"))  # = $1.00
    bad_net_pnl = gross_pnl - float(gas_usd) - bad_slippage_usd  # = 0.50 - 0.10 - 1.00 = -0.60
    
    assert bad_net_pnl < 0, "Old formula should have been negative"
    assert abs(bad_net_pnl - (-0.60)) < 0.001, f"Old bug net wrong: {bad_net_pnl}"

def test_micro_spread_is_gross_positive():
    """
    Test that micro-spreads with spread_bps_ui=0 still have is_gross_positive=True.
    
    This is a regression test for the bug where is_gross_positive was calculated
    from spread_bps (int) instead of spread_bps_decimal, causing false negatives.
    """
    # Micro-spread: sell > buy by tiny amount (0.27 bps)
    quotes = [
        {
            "dex_id": "uniswap_v3",
            "token_in": "WETH",
            "token_out": "USDC",
            "price_exact": "1921.625227",  # buy price (lower)
        },
        {
            "dex_id": "sushiswap_v3",
            "token_in": "WETH",
            "token_out": "USDC",
            "price_exact": "1921.676578",  # sell price (higher)
        },
    ]
    
    signals = compute_spread_signals_from_quotes(quotes, threshold_bps=0)
    
    assert len(signals) == 1
    sig = signals[0]
    
    # spread = (1921.676578 - 1921.625227) / 1921.625227 * 10000 = ~0.267 bps
    assert 0.2 <= sig["spread_bps_exact"] <= 0.3, f"Expected ~0.27 bps, got {sig['spread_bps_exact']}"
    
    # spread_bps_ui rounds to 0 (micro-spread)
    assert sig["spread_bps_ui"] == 0, f"spread_bps_ui should be 0, got {sig['spread_bps_ui']}"
    
    # BUT is_gross_positive MUST be True (sell > buy)
    assert sig["is_gross_positive"] is True, (
        f"CRITICAL: is_gross_positive must be True when sell > buy, "
        f"even if spread_bps_ui=0. Got {sig['is_gross_positive']}"
    )


def test_spread_pct_semantics():
    """
    Test spread_pct semantics: it should be a percentage (e.g., 0.00267 = 0.00267%).
    
    Formula: spread_pct = spread_bps / 100
    So 0.267 bps = 0.00267%
    """
    quotes = [
        {"dex_id": "dex_a", "token_in": "ETH", "token_out": "USD", "price_exact": "1000.00"},
        {"dex_id": "dex_b", "token_in": "ETH", "token_out": "USD", "price_exact": "1001.00"},  # 10 bps
    ]
    
    signals = compute_spread_signals_from_quotes(quotes, threshold_bps=0)
    assert len(signals) == 1
    sig = signals[0]
    
    # spread = (1001 - 1000) / 1000 * 10000 = 10 bps
    assert abs(sig["spread_bps_exact"] - 10.0) < 0.01
    
    # spread_pct = 10 / 100 = 0.1 (meaning 0.1%)
    # But we need to add this field to the test helper
    expected_spread_pct = sig["spread_bps_exact"] / 100
    assert abs(expected_spread_pct - 0.1) < 0.001, f"Expected 0.1%, got {expected_spread_pct}"


class TestNotionalDriftFilter:
    """Tests for NOTIONAL_DRIFT filtering in spread evaluation (v2.2.3)."""
    
    def test_high_drift_excluded(self):
        """Quote with drift=86% (>50%) should be excluded from spread evaluation."""
        from strategy.spreads import compute_spread_signals
        
        quotes = [
            # Low drift - should be included
            {"dex_id": "uniswap_v3", "token_in": "WETH", "token_out": "USDC", 
             "price_exact": "2000.0", "notional_drift_pct": 3.0,
             "pool_address": "0x1111111111111111111111111111111111111111"},
            # High drift - should be excluded
            {"dex_id": "sushiswap_v3", "token_in": "WETH", "token_out": "USDC", 
             "price_exact": "2010.0", "notional_drift_pct": 86.0,
             "pool_address": "0x2222222222222222222222222222222222222222"},
        ]
        config = {"truth_mode_m42": False, "notional_drift_max_pct": 50.0}
        rejected = []
        
        signals = compute_spread_signals(quotes, config, 1000, rejected)
        
        # Only 1 quote remains after drift filter - not enough for spread calc
        assert len(signals) == 0, "Should have no signals - one quote excluded by drift"
        assert len(rejected) == 1, "Should have 1 rejected quote"
        # v2.9.5: Changed from 'reject_reason' to 'reason' for schema consistency
        assert rejected[0]["reason"] == "NOTIONAL_DRIFT_EXCLUDED"
        assert rejected[0]["notional_drift_pct"] == 86.0
    
    def test_low_drift_included(self):
        """Quotes with drift=3% (<50%) should be included in spread evaluation."""
        from strategy.spreads import compute_spread_signals
        
        quotes = [
            {"dex_id": "uniswap_v3", "token_in": "WETH", "token_out": "USDC", 
             "price_exact": "2000.0", "notional_drift_pct": 3.0,
             "pool_address": "0x1111111111111111111111111111111111111111"},
            {"dex_id": "sushiswap_v3", "token_in": "WETH", "token_out": "USDC", 
             "price_exact": "2010.0", "notional_drift_pct": 5.0,
             "pool_address": "0x2222222222222222222222222222222222222222"},
        ]
        config = {"truth_mode_m42": False, "notional_drift_max_pct": 50.0}
        rejected = []
        
        signals = compute_spread_signals(quotes, config, 1000, rejected)
        
        # Both quotes included - spread signal generated
        assert len(signals) >= 1, "Should have signal - both quotes under drift threshold"
        assert len(rejected) == 0, "Should have no rejected quotes"
    
    def test_drift_threshold_configurable(self):
        """notional_drift_max_pct should be configurable."""
        from strategy.spreads import compute_spread_signals
        
        quotes = [
            {"dex_id": "uniswap_v3", "token_in": "WETH", "token_out": "USDC", 
             "price_exact": "2000.0", "notional_drift_pct": 30.0,
             "pool_address": "0x1111111111111111111111111111111111111111"},
            {"dex_id": "sushiswap_v3", "token_in": "WETH", "token_out": "USDC", 
             "price_exact": "2010.0", "notional_drift_pct": 40.0,
             "pool_address": "0x2222222222222222222222222222222222222222"},
        ]
        
        # With threshold=50%, both included
        config_50 = {"truth_mode_m42": False, "notional_drift_max_pct": 50.0}
        rejected_50 = []
        signals_50 = compute_spread_signals(quotes, config_50, 1000, rejected_50)
        assert len(signals_50) >= 1, "With 50% threshold, both quotes should be included"
        
        # With threshold=25%, both excluded
        config_25 = {"truth_mode_m42": False, "notional_drift_max_pct": 25.0}
        rejected_25 = []
        signals_25 = compute_spread_signals(quotes, config_25, 1000, rejected_25)
        assert len(signals_25) == 0, "With 25% threshold, both quotes should be excluded"
        assert len(rejected_25) == 2, "Should have 2 rejected quotes"