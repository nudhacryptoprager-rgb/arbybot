# PATH: tests/unit/test_opportunity_engine.py
"""
Tests for engine/opportunity_engine.py

Tests the core opportunity evaluation logic:
- Gas cost calculation
- Spread/PnL calculation
- Gate application
- Quote-to-opportunity transformation
"""

import pytest
from decimal import Decimal

from engine.opportunity_engine import (
    GasConfig,
    Opportunity,
    OpportunityEngine,
    evaluate_quotes,
)


class TestGasConfig:
    """Test gas cost estimation."""
    
    def test_default_gas_cost(self):
        """Default gas config gives sensible estimate."""
        gc = GasConfig()
        cost = gc.gas_cost_usd()
        # On Arbitrum, gas should be cheap (<$1 typical)
        assert 0.01 < cost < 1.0
    
    def test_gas_cost_with_estimate(self):
        """Gas cost scales with estimate."""
        gc = GasConfig()
        base_cost = gc.gas_cost_usd(100_000)
        double_cost = gc.gas_cost_usd(200_000)
        # Doubled gas units should increase cost (not exactly double due to L1 data)
        assert double_cost > base_cost
    
    def test_gas_cost_wei(self):
        """Wei estimate is positive int."""
        gc = GasConfig()
        wei = gc.estimate_gas_cost_wei()
        assert isinstance(wei, int)
        assert wei > 0


class TestOpportunityEngine:
    """Test opportunity building and scoring."""
    
    def test_build_empty_quotes(self):
        """No quotes produces no opportunities."""
        engine = OpportunityEngine()
        opps = engine.build_opportunities([])
        assert opps == []
    
    def test_build_single_dex_no_arb(self):
        """Single DEX quotes cannot create cross-DEX arb."""
        engine = OpportunityEngine()
        quotes = [
            {"dex_id": "uniswap_v3", "token_in": "WETH", "token_out": "USDC", "price": "2000", "fee": 500},
        ]
        opps = engine.build_opportunities(quotes)
        assert opps == []
    
    def test_build_cross_dex_opportunity(self):
        """Cross-DEX quotes produce opportunity."""
        engine = OpportunityEngine()
        quotes = [
            {"dex_id": "uniswap_v3", "token_in": "WETH", "token_out": "USDC", 
             "price": "2000", "fee": 500, "usd_notional": 1000, "amount_in_wei": 500000000000000000},
            {"dex_id": "sushiswap_v3", "token_in": "WETH", "token_out": "USDC", 
             "price": "2010", "fee": 500, "usd_notional": 1000, "amount_in_wei": 500000000000000000},
        ]
        opps = engine.build_opportunities(quotes)
        assert len(opps) == 1
        
        opp = opps[0]
        assert opp.pair == "WETH/USDC"
        assert opp.buy_dex == "uniswap_v3"
        assert opp.sell_dex == "sushiswap_v3"
        assert opp.gross_spread_bps > 0
    
    def test_spread_calculation(self):
        """Spread is calculated correctly."""
        engine = OpportunityEngine()
        # 0.5% spread = 50 bps
        quotes = [
            {"dex_id": "dex_a", "token_in": "WETH", "token_out": "USDC", 
             "price": "2000", "fee": 500, "usd_notional": 1000, "amount_in_wei": 1},
            {"dex_id": "dex_b", "token_in": "WETH", "token_out": "USDC", 
             "price": "2010", "fee": 500, "usd_notional": 1000, "amount_in_wei": 1},
        ]
        opps = engine.build_opportunities(quotes)
        assert len(opps) == 1
        
        opp = opps[0]
        # (2010 - 2000) / 2000 * 10000 = 50 bps
        assert abs(opp.gross_spread_bps - Decimal("50")) < Decimal("0.1")
    
    def test_gas_cost_deducted(self):
        """Gas cost is deducted from net profit."""
        engine = OpportunityEngine()
        quotes = [
            {"dex_id": "dex_a", "token_in": "WETH", "token_out": "USDC", 
             "price": "2000", "fee": 500, "usd_notional": 1000, "amount_in_wei": 1},
            {"dex_id": "dex_b", "token_in": "WETH", "token_out": "USDC", 
             "price": "2100", "fee": 500, "usd_notional": 1000, "amount_in_wei": 1},
        ]
        opps = engine.build_opportunities(quotes)
        opp = opps[0]
        
        # Gross > Net due to gas
        assert opp.gross_profit_usd > opp.net_profit_usd
        assert opp.gas_cost_usd > 0
    
    def test_gate_min_profit(self):
        """Opportunities below min profit don't pass gate."""
        engine = OpportunityEngine(min_net_profit_usd=10.0)  # High threshold
        quotes = [
            {"dex_id": "dex_a", "token_in": "WETH", "token_out": "USDC", 
             "price": "2000", "fee": 500, "usd_notional": 100, "amount_in_wei": 1},
            {"dex_id": "dex_b", "token_in": "WETH", "token_out": "USDC", 
             "price": "2001", "fee": 500, "usd_notional": 100, "amount_in_wei": 1},
        ]
        opps = engine.build_opportunities(quotes)
        assert len(opps) == 1
        assert not opps[0].gate_passed
        assert "NET_PROFIT_TOO_LOW" in (opps[0].reject_reason or "")
    
    def test_fee_math_regression_500_tier(self):
        """M4.2 FIX: fee_tier 500 = 5 bps per leg = 10 bps total for both."""
        engine = OpportunityEngine(min_net_profit_usd=0.0)
        # 1% spread = 100 bps gross, fee_tier 500 each side = 10 bps total fees
        # net_spread = 100 - 10 = 90 bps
        quotes = [
            {"dex_id": "dex_a", "token_in": "WETH", "token_out": "USDC", 
             "price": "2000", "fee": 500, "usd_notional": 1000, "amount_in_wei": 1},
            {"dex_id": "dex_b", "token_in": "WETH", "token_out": "USDC", 
             "price": "2020", "fee": 500, "usd_notional": 1000, "amount_in_wei": 1},
        ]
        opps = engine.build_opportunities(quotes)
        opp = opps[0]
        
        # 1% spread = 100 bps
        assert abs(opp.gross_spread_bps - Decimal("100")) < Decimal("1")
        # Fee: 500 + 500 = 1000/100 = 10 bps
        assert opp.fee_cost_usd > 0
        # Net spread = 100 - 10 = 90 bps
        assert abs(opp.net_spread_bps - Decimal("90")) < Decimal("1")
    
    def test_fee_math_regression_3000_tier(self):
        """M4.2 FIX: fee_tier 3000 = 30 bps per leg = 60 bps total."""
        engine = OpportunityEngine(min_net_profit_usd=0.0)
        # 1% spread = 100 bps gross, fee_tier 3000 each side = 60 bps total fees
        # net_spread = 100 - 60 = 40 bps
        quotes = [
            {"dex_id": "dex_a", "token_in": "WETH", "token_out": "USDC", 
             "price": "2000", "fee": 3000, "usd_notional": 1000, "amount_in_wei": 1},
            {"dex_id": "dex_b", "token_in": "WETH", "token_out": "USDC", 
             "price": "2020", "fee": 3000, "usd_notional": 1000, "amount_in_wei": 1},
        ]
        opps = engine.build_opportunities(quotes)
        opp = opps[0]
        
        # Net spread = 100 - 60 = 40 bps
        assert abs(opp.net_spread_bps - Decimal("40")) < Decimal("1")
        # At $1000 notional, 40 bps = $4 gross profit (before gas)
        assert 3.0 < opp.gross_profit_usd < 5.0
    
    def test_filter_profitable(self):
        """Filter returns only profitable opportunities."""
        engine = OpportunityEngine()
        quotes = [
            # Profitable spread
            {"dex_id": "dex_a", "token_in": "WETH", "token_out": "USDC", 
             "price": "2000", "fee": 500, "usd_notional": 10000, "amount_in_wei": 1},
            {"dex_id": "dex_b", "token_in": "WETH", "token_out": "USDC", 
             "price": "2100", "fee": 500, "usd_notional": 10000, "amount_in_wei": 1},
        ]
        opps = engine.build_opportunities(quotes)
        profitable = engine.filter_profitable(opps)
        
        for opp in profitable:
            assert opp.is_profitable


class TestEvaluateQuotes:
    """Test convenience function."""
    
    def test_returns_dicts_and_summary(self):
        """evaluate_quotes returns dicts and summary."""
        quotes = [
            {"dex_id": "dex_a", "token_in": "A", "token_out": "B", 
             "price": "100", "fee": 500, "usd_notional": 1000, "amount_in_wei": 1},
            {"dex_id": "dex_b", "token_in": "A", "token_out": "B", 
             "price": "101", "fee": 500, "usd_notional": 1000, "amount_in_wei": 1},
        ]
        
        opps, summary = evaluate_quotes(quotes)
        
        assert isinstance(opps, list)
        assert isinstance(summary, dict)
        assert "total_opportunities" in summary
        assert "profitable_count" in summary
        assert "best_net_profit_usd" in summary


class TestOpportunityModel:
    """Test Opportunity dataclass."""
    
    def test_to_dict(self):
        """to_dict serializes all fields."""
        opp = Opportunity(
            spread_id="spread_1_20260214_120000_0",
            pair="WETH/USDC",
            buy_dex="uniswap_v3",
            sell_dex="sushiswap_v3",
            buy_fee=500,
            sell_fee=500,
            buy_price=Decimal("2000"),
            sell_price=Decimal("2010"),
            amount_in_wei=1000000000000000000,
            gross_spread_bps=Decimal("50"),
            net_profit_usd=1.50,
            gate_passed=True,
        )
        
        d = opp.to_dict()
        assert d["spread_id"] == "spread_1_20260214_120000_0"
        assert d["pair"] == "WETH/USDC"
        assert d["buy_dex"] == "uniswap_v3"
        assert d["gate_passed"] is True
    
    def test_is_profitable(self):
        """is_profitable checks net_profit_usd > 0."""
        opp_profitable = Opportunity(
            spread_id="x", pair="A/B", buy_dex="d1", sell_dex="d2",
            buy_fee=0, sell_fee=0, buy_price=Decimal("1"), sell_price=Decimal("1"),
            amount_in_wei=1, net_profit_usd=0.01, gate_passed=True,
        )
        assert opp_profitable.is_profitable
        
        opp_not_profitable = Opportunity(
            spread_id="x", pair="A/B", buy_dex="d1", sell_dex="d2",
            buy_fee=0, sell_fee=0, buy_price=Decimal("1"), sell_price=Decimal("1"),
            amount_in_wei=1, net_profit_usd=-0.01, gate_passed=False,
        )
        assert not opp_not_profitable.is_profitable
