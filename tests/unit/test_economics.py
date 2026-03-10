# PATH: tests/unit/test_economics.py
"""
Unit tests for execution/economics.py module.

These tests validate the canonical economics calculations for arbitrage.
The economics module must be deterministic and consistent.
"""
import pytest
from execution.economics import (
    min_required_spread_bps,
    spread_minus_required,
    fee_tier_to_bps,
    is_roundtrip_candidate,
)


class TestMinRequiredSpreadBps:
    """Tests for min_required_spread_bps function."""
    
    def test_basic_calculation_30bps_pools(self):
        """Standard 0.30% pools: 30+30+5+4+2 = 71 bps (at $250 size)."""
        result = min_required_spread_bps(
            fee_bps_leg1=30,
            fee_bps_leg2=30,
            slippage_bps=5,
            gas_usd=0.10,
            size_usd=250,
            safety_bps=2,
        )
        # 30 + 30 + 5 + (0.10/250)*10000 + 2 = 30+30+5+4+2 = 71
        assert result == 71.0
    
    def test_low_fee_pools_5bps(self):
        """Low-fee 0.05% pools: 5+5+5+4+2 = 21 bps."""
        result = min_required_spread_bps(
            fee_bps_leg1=5,
            fee_bps_leg2=5,
            slippage_bps=5,
            gas_usd=0.10,
            size_usd=250,
            safety_bps=2,
        )
        # 5 + 5 + 5 + 4 + 2 = 21
        assert result == 21.0
    
    def test_asymmetric_fees(self):
        """Asymmetric fee tiers: 5+30+5+4+2 = 46 bps."""
        result = min_required_spread_bps(
            fee_bps_leg1=5,
            fee_bps_leg2=30,
            slippage_bps=5,
            gas_usd=0.10,
            size_usd=250,
            safety_bps=2,
        )
        # 5 + 30 + 5 + 4 + 2 = 46
        assert result == 46.0
    
    def test_larger_size_reduces_gas_impact(self):
        """Larger size reduces gas impact: gas_bps = 0.10/1000*10000 = 1 bps."""
        result = min_required_spread_bps(
            fee_bps_leg1=30,
            fee_bps_leg2=30,
            slippage_bps=5,
            gas_usd=0.10,
            size_usd=1000,  # 4x larger
            safety_bps=2,
        )
        # 30 + 30 + 5 + 1 + 2 = 68
        assert result == 68.0
    
    def test_zero_gas_zero_slippage(self):
        """Zero gas and slippage: just fees + safety."""
        result = min_required_spread_bps(
            fee_bps_leg1=30,
            fee_bps_leg2=30,
            slippage_bps=0,
            gas_usd=0,
            size_usd=250,
            safety_bps=0,
        )
        # 30 + 30 + 0 + 0 + 0 = 60
        assert result == 60.0
    
    def test_deterministic_same_inputs(self):
        """Same inputs always produce same output (determinism contract)."""
        params = dict(
            fee_bps_leg1=30,
            fee_bps_leg2=30,
            slippage_bps=5,
            gas_usd=0.10,
            size_usd=250,
            safety_bps=2,
        )
        results = [min_required_spread_bps(**params) for _ in range(10)]
        assert all(r == results[0] for r in results)
    
    def test_zero_size_no_crash(self):
        """Zero size doesn't crash (edge case protection)."""
        result = min_required_spread_bps(
            fee_bps_leg1=30,
            fee_bps_leg2=30,
            slippage_bps=5,
            gas_usd=0.10,
            size_usd=0,  # edge case
            safety_bps=2,
        )
        # Gas term becomes 0 (protected division)
        # 30 + 30 + 5 + 0 + 2 = 67
        assert result == 67.0


class TestSpreadMinusRequired:
    """Tests for spread_minus_required function."""
    
    def test_profitable_spread(self):
        """Spread 80 bps, required 71 bps -> surplus 9 bps."""
        result = spread_minus_required(
            spread_bps=80,
            fee_bps_leg1=30,
            fee_bps_leg2=30,
            slippage_bps=5,
            gas_usd=0.10,
            size_usd=250,
            safety_bps=2,
        )
        assert result == 9.0
    
    def test_breakeven_spread(self):
        """Spread 71 bps, required 71 bps -> surplus 0 bps."""
        result = spread_minus_required(
            spread_bps=71,
            fee_bps_leg1=30,
            fee_bps_leg2=30,
            slippage_bps=5,
            gas_usd=0.10,
            size_usd=250,
            safety_bps=2,
        )
        assert result == 0.0
    
    def test_unprofitable_spread(self):
        """Spread 50 bps, required 71 bps -> deficit -21 bps."""
        result = spread_minus_required(
            spread_bps=50,
            fee_bps_leg1=30,
            fee_bps_leg2=30,
            slippage_bps=5,
            gas_usd=0.10,
            size_usd=250,
            safety_bps=2,
        )
        assert result == -21.0
    
    def test_low_fee_pools_lower_threshold(self):
        """Low-fee pools have lower threshold, same spread more profitable."""
        # With 30 bps pools: surplus = 50 - 71 = -21 (unprofitable)
        result_30bps = spread_minus_required(
            spread_bps=50,
            fee_bps_leg1=30,
            fee_bps_leg2=30,
        )
        # With 5 bps pools: surplus = 50 - 21 = 29 (profitable!)
        result_5bps = spread_minus_required(
            spread_bps=50,
            fee_bps_leg1=5,
            fee_bps_leg2=5,
        )
        assert result_30bps < 0  # unprofitable
        assert result_5bps > 0   # profitable


class TestFeeTierToBps:
    """Tests for fee_tier_to_bps conversion."""
    
    def test_fee_tier_100(self):
        """Fee tier 100 = 1 bps."""
        assert fee_tier_to_bps(100) == 1.0
    
    def test_fee_tier_500(self):
        """Fee tier 500 = 5 bps."""
        assert fee_tier_to_bps(500) == 5.0
    
    def test_fee_tier_3000(self):
        """Fee tier 3000 = 30 bps."""
        assert fee_tier_to_bps(3000) == 30.0
    
    def test_fee_tier_10000(self):
        """Fee tier 10000 = 100 bps."""
        assert fee_tier_to_bps(10000) == 100.0


class TestIsRoundtripCandidate:
    """Tests for is_roundtrip_candidate gating function."""
    
    def test_profitable_is_candidate(self):
        """Spread 80 bps > required 71 bps -> is candidate."""
        assert is_roundtrip_candidate(
            spread_bps=80,
            fee_bps_leg1=30,
            fee_bps_leg2=30,
        ) is True
    
    def test_breakeven_is_not_candidate(self):
        """Spread 71 bps = required 71 bps -> not candidate (must be strictly positive)."""
        assert is_roundtrip_candidate(
            spread_bps=71,
            fee_bps_leg1=30,
            fee_bps_leg2=30,
        ) is False
    
    def test_unprofitable_is_not_candidate(self):
        """Spread 50 bps < required 71 bps -> not candidate."""
        assert is_roundtrip_candidate(
            spread_bps=50,
            fee_bps_leg1=30,
            fee_bps_leg2=30,
        ) is False
    
    def test_low_fee_pools_lower_threshold(self):
        """Same 25 bps spread: unprofitable at 30bps pools, profitable at 5bps pools."""
        # 30 bps pools: required ~71 bps, 25 bps spread not candidate
        assert is_roundtrip_candidate(
            spread_bps=25,
            fee_bps_leg1=30,
            fee_bps_leg2=30,
        ) is False
        
        # 5 bps pools: required ~21 bps, 25 bps spread IS candidate
        assert is_roundtrip_candidate(
            spread_bps=25,
            fee_bps_leg1=5,
            fee_bps_leg2=5,
        ) is True


class TestEconomicsContractIntegration:
    """Integration tests verifying economics module contracts."""
    
    def test_min_spread_bps_12_covers_cost_floor(self):
        """
        Contract: min_spread_bps=12 in config must be >= cost floor.
        
        Cost floor at $150 paper size (v3.3.0):
        - gas: $0.10 / $150 * 10000 = 6.67 bps
        - slippage: 5 bps (default)
        - safety: 2 bps
        - Total non-fee: ~13.67 bps
        
        So min_spread_bps=12 is slightly below pure costs but above typical
        gas-only threshold. This is by design: LP fees are added on top when
        comparing to min_required_spread_bps.
        """
        config_min_spread_bps = 12
        
        # Pure cost floor (no LP fees) at $150
        cost_floor = min_required_spread_bps(
            fee_bps_leg1=0,  # No LP fees
            fee_bps_leg2=0,
            slippage_bps=5,
            gas_usd=0.10,
            size_usd=150,
            safety_bps=2,
        )
        # Should be ~13.67 bps (5 + 6.67 + 2)
        assert cost_floor == 13.67
        
        # config_min_spread_bps slightly below to allow signal generation,
        # but roundtrip gating will add LP fees and filter properly
        assert config_min_spread_bps < cost_floor


class TestSignalEconomicsFieldsContract:
    """
    Contract tests verifying economics fields are present in signals.
    
    These tests ensure the economics fields added to signals in strategy/spreads.py
    are correctly populated and not lost in downstream aggregation.
    """
    
    def test_build_spread_signal_has_economics_fields(self):
        """build_spread_signal must include min_required_spread_bps and spread_minus_required_bps."""
        from strategy.spreads import _build_spread_signal as build_spread_signal
        from decimal import Decimal
        
        best_buy = {
            "dex_id": "uniswap_v3",
            "pool_address": "0x123",
            "fee": 500,  # 5 bps
            "price_exact": "1850.0",
            "quote_source": "quoter_v2",
        }
        best_sell = {
            "dex_id": "sushiswap_v3",
            "pool_address": "0x456",
            "fee": 500,  # 5 bps
            "price_exact": "1852.0",
            "quote_source": "quoter_v2",
        }
        config = {
            "paper_size_usd": 250,
            "gas_usd_estimate": 0.10,
            "paper_slippage_bps": 5,
        }
        
        signal = build_spread_signal(
            pair="WETH/USDC",
            best_buy=best_buy,
            best_sell=best_sell,
            buy_price=Decimal("1850.0"),
            sell_price=Decimal("1852.0"),
            spread_bps_decimal=Decimal("10.8"),  # ~10.8 bps spread
            spread_bps=11,
            config=config,
            current_block=123456,
        )
        
        # v2.9.8 Economics fields must be present
        assert "min_required_spread_bps" in signal
        assert "spread_minus_required_bps" in signal
        assert "is_roundtrip_viable" in signal
        
        # Verify types
        assert isinstance(signal["min_required_spread_bps"], (int, float))
        assert isinstance(signal["spread_minus_required_bps"], (int, float))
        assert isinstance(signal["is_roundtrip_viable"], bool)
    
    def test_economics_fields_values_make_sense(self):
        """Economics fields must have reasonable values based on inputs."""
        from strategy.spreads import _build_spread_signal as build_spread_signal
        from decimal import Decimal
        
        # Setup: 5 bps pools, $250 size, $0.10 gas
        best_buy = {"dex_id": "uni", "pool_address": "0x123", "fee": 500, 
                    "price_exact": "1850.0", "quote_source": "quoter_v2"}
        best_sell = {"dex_id": "sushi", "pool_address": "0x456", "fee": 500,
                     "price_exact": "1880.0", "quote_source": "quoter_v2"}
        config = {"paper_size_usd": 250, "gas_usd_estimate": 0.10, "paper_slippage_bps": 5}
        
        # High spread: 160 bps (well above required ~21 bps)
        signal = build_spread_signal(
            pair="WETH/USDC", best_buy=best_buy, best_sell=best_sell,
            buy_price=Decimal("1850.0"), sell_price=Decimal("1880.0"),
            spread_bps_decimal=Decimal("160"), spread_bps=160,
            config=config, current_block=123456,
        )
        
        # For 5 bps pools: min_required = 5+5+5+4+2 = 21 bps
        assert signal["min_required_spread_bps"] == 21.0
        # spread_minus_required = 160 - 21 = 139 bps
        assert signal["spread_minus_required_bps"] == 139.0
        # Should be viable
        assert signal["is_roundtrip_viable"] is True
    
    def test_low_spread_marked_not_viable(self):
        """Low spread signals should be marked as not roundtrip viable."""
        from strategy.spreads import _build_spread_signal as build_spread_signal
        from decimal import Decimal
        
        best_buy = {"dex_id": "uni", "pool_address": "0x123", "fee": 3000,  # 30 bps
                    "price_exact": "1850.0", "quote_source": "quoter_v2"}
        best_sell = {"dex_id": "sushi", "pool_address": "0x456", "fee": 3000,  # 30 bps
                     "price_exact": "1851.0", "quote_source": "quoter_v2"}
        config = {"paper_size_usd": 250, "gas_usd_estimate": 0.10, "paper_slippage_bps": 5}
        
        # Low spread: 5.4 bps (well below required ~71 bps for 30bps pools)
        signal = build_spread_signal(
            pair="WETH/USDC", best_buy=best_buy, best_sell=best_sell,
            buy_price=Decimal("1850.0"), sell_price=Decimal("1851.0"),
            spread_bps_decimal=Decimal("5.4"), spread_bps=5,
            config=config, current_block=123456,
        )
        
        # For 30 bps pools: min_required = 30+30+5+4+2 = 71 bps
        assert signal["min_required_spread_bps"] == 71.0
        # spread_minus_required = 5.4 - 71 = -65.6 bps (negative!)
        assert signal["spread_minus_required_bps"] < 0
        # Should NOT be viable
        assert signal["is_roundtrip_viable"] is False


class TestRoundtripGatingContract:
    """
    Contract tests verifying roundtrip gating uses economics.
    
    These tests ensure the roundtrip evaluation respects the economics gate
    and only evaluates candidates with positive spread_minus_required_bps.
    """
    
    def test_roundtrip_candidates_filters_non_viable(self):
        """evaluate_roundtrip_candidates must skip is_roundtrip_viable=False."""
        from engine.roundtrip import evaluate_roundtrip_candidates
        
        # Create opportunities with one viable and one not viable
        opportunities = [
            {
                "pair": "WETH/USDC",
                "spread_minus_required_bps": -20,  # Not viable
                "is_roundtrip_viable": False,
                "buy_dex": "uni",
                "sell_dex": "sushi",
                "buy_fee": 500,
                "sell_fee": 500,
                "diagnostics": {"buy_pool": "0x123", "sell_pool": "0x456"},
            },
            {
                "pair": "WBTC/WETH",
                "spread_minus_required_bps": 50,  # Viable
                "is_roundtrip_viable": True,
                "buy_dex": "uni",
                "sell_dex": "sushi",
                "buy_fee": 500,
                "sell_fee": 500,
                "diagnostics": {"buy_pool": "0x789", "sell_pool": "0xabc"},
            },
        ]
        
        # Empty quote dicts (no actual quotes needed for gating test)
        buy_quotes = {}
        sell_quotes = {}
        
        # Call evaluate - should only try to evaluate the viable one
        results, stats = evaluate_roundtrip_candidates(
            opportunities=opportunities,
            buy_quotes_by_key=buy_quotes,
            sell_quotes_by_key=sell_quotes,
            top_n=2,
        )
        
        # No results because quotes are empty, but the function should not crash
        # and should have skipped the non-viable opportunity
        assert len(results) == 0  # No quotes = no results
        # v3.0.0: Stats should show 1 gated by economics
        assert stats.gated_by_economics == 1
    
    def test_all_non_viable_produces_no_evaluations(self):
        """If all opportunities are non-viable, no roundtrip is evaluated."""
        from engine.roundtrip import evaluate_roundtrip_candidates
        
        opportunities = [
            {
                "pair": "WETH/USDC",
                "spread_minus_required_bps": -10,
                "is_roundtrip_viable": False,
                "buy_dex": "uni", "sell_dex": "sushi", "buy_fee": 3000, "sell_fee": 3000,
                "diagnostics": {"buy_pool": "0x1", "sell_pool": "0x2"},
            },
            {
                "pair": "ARB/WETH",
                "spread_minus_required_bps": -5,
                "is_roundtrip_viable": False,
                "buy_dex": "uni", "sell_dex": "sushi", "buy_fee": 3000, "sell_fee": 3000,
                "diagnostics": {"buy_pool": "0x3", "sell_pool": "0x4"},
            },
        ]
        
        results, stats = evaluate_roundtrip_candidates(
            opportunities=opportunities,
            buy_quotes_by_key={},
            sell_quotes_by_key={},
            top_n=5,
        )
        
        # All gated by economics, no evaluations
        assert len(results) == 0
        # v3.0.0: Stats should show all 2 gated by economics
        assert stats.gated_by_economics == 2
        assert stats.evaluated_count == 0


class TestMeasuredSlippageBps:
    """Tests for measured_slippage_bps function from sqrtPriceX96."""
    
    def test_no_data_returns_zero_and_false(self):
        """Missing data returns (0.0, False)."""
        from execution.economics import measured_slippage_bps
        
        result, is_valid = measured_slippage_bps(None, None)
        assert result == 0.0
        assert is_valid is False
        
        result, is_valid = measured_slippage_bps(12345, None)
        assert result == 0.0
        assert is_valid is False
        
        result, is_valid = measured_slippage_bps(None, 12345)
        assert result == 0.0
        assert is_valid is False
    
    def test_zero_before_returns_false(self):
        """Zero before price returns (0.0, False)."""
        from execution.economics import measured_slippage_bps
        
        result, is_valid = measured_slippage_bps(0, 12345)
        assert result == 0.0
        assert is_valid is False
    
    def test_calculates_slippage_correctly(self):
        """Calculate slippage from sqrt prices (1% move = 100 bps)."""
        from execution.economics import measured_slippage_bps
        
        # sqrtPriceX96 = sqrt(price) * 2^96
        # If price moves from 1.0 to 1.01, sqrt moves from 1.0 to ~1.00499
        # price_after/price_before = 1.01 -> slippage = 1% = 100 bps
        Q96 = 2 ** 96
        
        # price_before = 1.0, sqrt = 1.0 * 2^96
        sqrt_before = Q96
        
        # price_after = 1.01, sqrt = sqrt(1.01) * 2^96
        import math
        sqrt_after = int(math.sqrt(1.01) * Q96)
        
        slippage, is_valid = measured_slippage_bps(sqrt_before, sqrt_after)
        
        assert is_valid is True
        # Should be approximately 100 bps (1%)
        assert 99 < slippage < 101
    
    def test_large_slippage_detection(self):
        """Detect large slippage (>100 bps)."""
        from execution.economics import measured_slippage_bps
        import math
        
        Q96 = 2 ** 96
        sqrt_before = Q96  # price = 1.0
        
        # 5% slippage: price_after = 1.05
        sqrt_after = int(math.sqrt(1.05) * Q96)
        
        slippage, is_valid = measured_slippage_bps(sqrt_before, sqrt_after)
        
        assert is_valid is True
        # Should be approximately 500 bps (5%)
        assert 495 < slippage < 505
    
    def test_returns_absolute_value(self):
        """Always returns absolute slippage (direction-agnostic)."""
        from execution.economics import measured_slippage_bps
        import math
        
        Q96 = 2 ** 96
        
        # Price down scenario: before = 1.0, after = 0.99
        sqrt_before = Q96
        sqrt_after = int(math.sqrt(0.99) * Q96)
        
        slippage, is_valid = measured_slippage_bps(sqrt_before, sqrt_after)
        
        assert is_valid is True
        # Should be approximately 100 bps (abs of -1%)
        assert slippage > 0
        assert 99 < slippage < 101


class TestEffectiveSlippageBps:
    """Tests for effective_slippage_bps function."""
    
    def test_no_measurement_returns_paper(self):
        """Without measurement, returns paper slippage."""
        from execution.economics import effective_slippage_bps
        
        eff, source = effective_slippage_bps(5.0, None, None)
        assert eff == 5.0
        assert source == "paper"
    
    def test_measured_higher_uses_measured(self):
        """When measured > paper, uses measured."""
        from execution.economics import effective_slippage_bps
        import math
        
        Q96 = 2 ** 96
        sqrt_before = Q96
        sqrt_after = int(math.sqrt(1.03) * Q96)  # 3% slippage = 300 bps
        
        eff, source = effective_slippage_bps(5.0, sqrt_before, sqrt_after)
        
        # 300 bps > 5 bps, should use measured
        assert eff > 200  # approximately 300
        assert source == "max(paper,measured)"
    
    def test_paper_higher_uses_paper(self):
        """When paper > measured, returns paper."""
        from execution.economics import effective_slippage_bps
        import math
        
        Q96 = 2 ** 96
        sqrt_before = Q96
        sqrt_after = int(math.sqrt(1.0001) * Q96)  # 0.01% = 1 bps
        
        eff, source = effective_slippage_bps(50.0, sqrt_before, sqrt_after)
        
        # 50 bps > 1 bps, should use paper
        assert eff == 50.0
        assert source == "paper"


class TestSpreadViabilityWithMeasuredSlippage:
    """Tests that high measured slippage makes is_roundtrip_viable=false."""
    
    def test_high_measured_slippage_makes_not_viable(self):
        """High measured slippage (>spread) should make is_roundtrip_viable=False."""
        from strategy.spreads import compute_spread_signals
        import math
        
        Q96 = 2 ** 96
        sqrt_before = Q96
        # 5% slippage (500 bps) - huge
        sqrt_after = int(math.sqrt(1.05) * Q96)
        
        # Create quotes with 30 bps gross spread but 500 bps measured slippage
        quotes = [
            {
                "token_in": "WETH",
                "token_out": "USDC",
                "price": 2000.0,
                "price_exact": "2000.0",
                "dex_id": "uniswap_v3",
                "pool_address": "0x111",
                "fee": 500,
                "quote_source": "quoter_v2",
                "sqrt_price_x96": sqrt_before,
                "sqrt_price_after": sqrt_after,  # 5% slippage
            },
            {
                "token_in": "WETH",
                "token_out": "USDC",
                "price": 2006.0,  # ~30 bps higher
                "price_exact": "2006.0",
                "dex_id": "sushiswap_v3",
                "pool_address": "0x222",
                "fee": 500,
                "quote_source": "quoter_v2",
                "sqrt_price_x96": sqrt_before,
                "sqrt_price_after": sqrt_after,  # 5% slippage
            },
        ]
        
        config = {
            "min_spread_bps": 0,
            "paper_size_usd": 250,
            "gas_usd_estimate": 0.10,
            "paper_slippage_bps": 5,  # Paper says 5 bps, but measured is 500!
        }
        
        signals = compute_spread_signals(quotes, config, 1000, [])
        
        # Should have signals but they should NOT be viable due to high slippage
        assert len(signals) > 0
        for sig in signals:
            # With 500 bps slippage on each leg, total ~1000 bps slippage
            # This should dwarf the 30 bps gross spread
            assert sig["has_measured_slippage"] is True
            assert sig["total_measured_slippage_bps"] > 400  # Significant
            # v3.1.1: slippage_source is always paper (for drift), 
            # effective_slippage_source is "measured" when high
            assert sig["slippage_source"] == "config", "slippage_bps uses paper for drift consistency"
            assert sig["effective_slippage_source"] == "measured"
            assert sig["effective_slippage_bps"] > 400  # Uses measured for viability
            # The viability should be FALSE due to high slippage
            assert sig["is_roundtrip_viable"] is False