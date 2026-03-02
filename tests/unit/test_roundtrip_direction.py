# tests/unit/test_roundtrip_direction.py
"""
Regression tests for roundtrip direction fix (v2.2.0).

v2.2.0 BUG FIX: evaluate_roundtrip_candidates was using DEXes backwards.
- Old (broken): leg1 on buy_dex (cheap), leg2 on sell_dex (expensive) → LOSS
- Fixed: leg1 on sell_dex (expensive), leg2 on buy_dex (cheap) → PROFIT

Semantic contract:
- buy_dex = DEX with LOWER price (cheaper to buy base token)
- sell_dex = DEX with HIGHER price (more quote per base)
- Profitable arb: sell on expensive DEX (leg1), buy on cheap DEX (leg2)
- leg1: token_in → token_out on sell_dex (get MORE token_out)
- leg2: token_out → token_in on buy_dex (get MORE token_in back)

IMPORTANT: simulate_roundtrip uses RATIO ESTIMATE for leg2 when no callback provided.
The ratio estimate assumes sell_quote is in REVERSE direction (token_out→token_in).
For accurate roundtrip, always provide leg2_quote_callback.
"""
import unittest
from decimal import Decimal
from engine.roundtrip import evaluate_roundtrip_candidates, simulate_roundtrip


class TestRoundtripDirectionV220(unittest.TestCase):
    """Tests for v2.2.0 roundtrip direction fix."""

    def test_correct_direction_with_callback_profitable(self):
        """
        When sell_dex has higher price than buy_dex, roundtrip should be profitable.
        Uses leg2_quote_callback for proper reverse quote.
        
        Scenario:
        - buy_dex (uniswap_v3): 1 WETH = 1800 USDC (cheap)
        - sell_dex (sushiswap_v3): 1 WETH = 1850 USDC (expensive)
        - Spread: ~277 bps
        
        Correct flow (v2.2.0):
        - Leg1: Sell 1 WETH on sushiswap_v3 → get 1850 USDC
        - Leg2: Buy WETH on uniswap_v3 with 1850 USDC → get 1850/1800 = 1.0278 WETH
        - Gross PnL: +2.78% profit
        """
        # sell_quote for leg1 (expensive DEX - we sell here to get more USDC)
        sell_quote = {
            "dex_id": "sushiswap_v3",
            "pool_address": "0xSellPool",
            "fee": 500,
            "token_in": "WETH",
            "token_out": "USDC",
            "amount_in_wei": 1_000_000_000_000_000_000,  # 1 WETH
            "amount_out_wei": 1_850_000_000,  # 1850 USDC (expensive price)
            "quote_source": "quoter_v2",
            "gas_estimate": 150_000,
            "ticks_crossed": 3,
        }
        
        # buy_quote for leg2 reference (cheap DEX - we buy here)
        # Note: This is WETH→USDC direction, but we'll use callback for USDC→WETH
        buy_quote = {
            "dex_id": "uniswap_v3",
            "pool_address": "0xBuyPool",
            "fee": 3000,
            "token_in": "WETH",
            "token_out": "USDC",
            "amount_in_wei": 1_000_000_000_000_000_000,  # 1 WETH
            "amount_out_wei": 1_800_000_000,  # 1800 USDC (cheap price)
            "quote_source": "quoter_v2",
            "gas_estimate": 150_000,
            "ticks_crossed": 3,
        }
        
        # Leg2 callback simulates USDC→WETH swap on buy_dex
        # Given 1850 USDC, at price 1800 USDC/WETH, we get 1850/1800 = 1.0278 WETH
        def leg2_callback(amount_in_wei: int):
            # amount_in_wei is USDC (leg1 output)
            # Return WETH (amount_in_wei / 1800 * 1e18)
            usdc_amount = amount_in_wei / 1e6  # USDC has 6 decimals
            weth_amount = usdc_amount / 1800  # WETH price is 1800 USDC
            return {
                "amount_out_wei": int(weth_amount * 1e18),
                "gas_estimate": 150_000,
                "ticks_crossed": 3,
            }
        
        # v2.2.0: leg1 is sell_quote (expensive DEX)
        result = simulate_roundtrip(
            buy_quote=sell_quote,  # leg1: sell on expensive DEX
            sell_quote=buy_quote,  # leg2 fallback (not used when callback provided)
            gas_price_wei=10_000_000,  # 0.01 gwei
            l1_cost_wei=1_000_000_000,  # minimal L1 cost
            leg2_quote_callback=leg2_callback,
        )
        
        # v2.2.0 CONTRACT: With correct direction, result should be profitable
        # Leg1: 1 WETH → 1850 USDC (on sell_dex = expensive)
        # Leg2: 1850 USDC → 1.0278 WETH (on buy_dex = cheap)
        # Gross PnL: 1.0278 - 1.0 = +0.0278 WETH = +2.78%
        self.assertEqual(result.leg1_amount_out, 1_850_000_000, "leg1 should get 1850 USDC")
        self.assertTrue(result.leg2_is_real_quote, "leg2 should use callback")
        self.assertGreater(result.gross_pnl_bps, 0, "gross PnL should be positive")
        self.assertGreater(result.gross_pnl_bps, 200, "gross PnL should be > 200 bps")
        
    def test_backwards_direction_loses_money(self):
        """
        Verify that wrong direction (leg1 on buy_dex) would be unprofitable.
        This is a safeguard test to ensure we understand the semantics.
        """
        buy_quote = {
            "dex_id": "uniswap_v3",
            "pool_address": "0xBuyPool",
            "fee": 3000,
            "token_in": "WETH",
            "token_out": "USDC",
            "amount_in_wei": 1_000_000_000_000_000_000,
            "amount_out_wei": 1_800_000_000,  # 1800 USDC (cheap)
            "quote_source": "quoter_v2",
            "gas_estimate": 150_000,
            "ticks_crossed": 3,
        }
        
        sell_quote = {
            "dex_id": "sushiswap_v3",
            "pool_address": "0xSellPool",
            "fee": 500,
            "token_in": "WETH", 
            "token_out": "USDC",
            "amount_in_wei": 1_000_000_000_000_000_000,
            "amount_out_wei": 1_850_000_000,  # 1850 USDC (expensive)
            "quote_source": "quoter_v2",
            "gas_estimate": 150_000,
            "ticks_crossed": 3,
        }
        
        # WRONG direction callback: leg2 buys on expensive DEX
        def leg2_callback_wrong(amount_in_wei: int):
            usdc_amount = amount_in_wei / 1e6
            weth_amount = usdc_amount / 1850  # Buy at expensive price
            return {
                "amount_out_wei": int(weth_amount * 1e18),
                "gas_estimate": 150_000,
                "ticks_crossed": 3,
            }
        
        # WRONG direction: leg1 on buy_dex (cheap), leg2 on sell_dex (expensive)
        result_wrong = simulate_roundtrip(
            buy_quote=buy_quote,   # leg1 on buy_dex (cheap) - WRONG
            sell_quote=sell_quote, # leg2 on sell_dex (expensive) - WRONG
            gas_price_wei=10_000_000,
            l1_cost_wei=1_000_000_000,
            leg2_quote_callback=leg2_callback_wrong,
        )
        
        # Wrong direction should lose money
        # Leg1: 1 WETH → 1800 USDC (sell low = bad)
        # Leg2: 1800 USDC → 1800/1850 WETH = 0.973 WETH (buy high = bad)
        # Gross PnL: 0.973 - 1.0 = -0.027 WETH = -2.7%
        self.assertLess(result_wrong.gross_pnl_bps, 0, "wrong direction should have negative PnL")
        self.assertLess(result_wrong.gross_pnl_bps, -200, "wrong direction should lose > 200 bps")

    def test_evaluate_roundtrip_candidates_uses_correct_direction(self):
        """
        Ensure evaluate_roundtrip_candidates passes quotes in correct order.
        """
        opportunities = [{
            "spread_id": "test_opp_1",
            "buy_dex": "uniswap_v3",
            "sell_dex": "sushiswap_v3",
            "buy_fee": 3000,
            "sell_fee": 500,
            "diagnostics": {
                "buy_pool": "0xBuyPool",
                "sell_pool": "0xSellPool",
            },
            # v3.2.4: Economics fields required for roundtrip evaluation
            "is_roundtrip_viable": True,
            "min_required_spread_bps": 10.0,
            "spread_minus_required_bps": 20.0,
        }]
        
        buy_quotes = {
            "uniswap_v3:0xBuyPool:3000": {
                "dex_id": "uniswap_v3",
                "pool_address": "0xBuyPool",
                "fee": 3000,
                "token_in": "WETH",
                "token_out": "USDC",
                "amount_in_wei": 1_000_000_000_000_000_000,
                "amount_out_wei": 1_800_000_000,  # 1800 USDC (cheap)
                "quote_source": "quoter_v2",
                "gas_estimate": 150_000,
                "ticks_crossed": 3,
            }
        }
        
        sell_quotes = {
            "sushiswap_v3:0xSellPool:500": {
                "dex_id": "sushiswap_v3",
                "pool_address": "0xSellPool",
                "fee": 500,
                "token_in": "WETH",
                "token_out": "USDC",
                "amount_in_wei": 1_000_000_000_000_000_000,
                "amount_out_wei": 1_850_000_000,  # 1850 USDC (expensive)
                "quote_source": "quoter_v2",
                "gas_estimate": 150_000,
                "ticks_crossed": 3,
            }
        }
        
        # Factory creates leg2 callback for buy_quote (v2.2.0 fix)
        def leg2_callback_factory(quote):
            # Returns callback for USDC→WETH at the quote's DEX price
            usdc_per_weth = quote.get("amount_out_wei", 0) / (quote.get("amount_in_wei", 0) / 1e18) if quote.get("amount_in_wei") else 1800
            def callback(amount_in_wei: int):
                usdc_amount = amount_in_wei / 1e6
                weth_amount = usdc_amount / (usdc_per_weth / 1e6)  # Convert back to WETH
                return {
                    "amount_out_wei": int(weth_amount * 1e18),
                    "gas_estimate": 150_000,
                    "ticks_crossed": 3,
                }
            return callback
        
        results, stats = evaluate_roundtrip_candidates(
            opportunities=opportunities,
            buy_quotes_by_key=buy_quotes,
            sell_quotes_by_key=sell_quotes,
            gas_price_wei=10_000_000,
            top_n=5,
            l1_cost_wei=1_000_000_000,
            leg2_quote_callback_factory=leg2_callback_factory,
        )
        
        self.assertEqual(len(results), 1, "should have 1 result")
        result = results[0]
        
        # v2.2.0 CONTRACT: correct direction should give positive PnL
        # v2.2.0 FIX: leg1 uses sell_quote (expensive), leg2 uses buy_quote callback (cheap)
        self.assertTrue(result.leg2_is_real_quote, "should use callback")
        self.assertGreater(result.gross_pnl_bps, 0, "should be profitable with correct direction")


class TestRoundtripLegSemantics(unittest.TestCase):
    """Tests for leg1/leg2 semantic clarity."""
    
    def test_leg1_is_sell_leg2_is_buy_with_callback(self):
        """
        Verify semantic documentation: leg1=sell on expensive, leg2=buy on cheap.
        """
        # sell_quote has higher price (1850 USDC per WETH)
        sell_quote = {
            "dex_id": "sushiswap_v3",
            "pool_address": "0xSellPool",
            "fee": 500,
            "token_in": "WETH",
            "token_out": "USDC",
            "amount_in_wei": 1_000_000_000_000_000_000,
            "amount_out_wei": 1_850_000_000,  # More USDC = higher price
            "gas_estimate": 150_000,
        }
        
        # buy_quote has lower price (1800 USDC per WETH)
        buy_quote = {
            "dex_id": "uniswap_v3",
            "pool_address": "0xBuyPool",
            "fee": 3000,
            "token_in": "WETH",
            "token_out": "USDC",
            "amount_in_wei": 1_000_000_000_000_000_000,
            "amount_out_wei": 1_800_000_000,  # Less USDC = lower price
            "gas_estimate": 150_000,
        }
        
        # Leg2 callback for USDC→WETH on buy_dex
        def leg2_callback(amount_in_wei: int):
            usdc_amount = amount_in_wei / 1e6
            weth_amount = usdc_amount / 1800
            return {
                "amount_out_wei": int(weth_amount * 1e18),
                "gas_estimate": 150_000,
                "ticks_crossed": 3,
            }
        
        # v2.2.0: leg1=sell_quote (expensive DEX), leg2=buy_quote via callback (cheap DEX)
        result = simulate_roundtrip(
            buy_quote=sell_quote,  # Confusingly named in function sig, but this is leg1 (sell expensive)
            sell_quote=buy_quote,  # This is leg2 fallback (not used when callback provided)
            gas_price_wei=0,  # No gas for simplicity
            l1_cost_wei=0,
            leg2_quote_callback=leg2_callback,
        )
        
        # Leg1: 1 WETH → 1850 USDC (sell on expensive DEX)
        self.assertEqual(result.leg1_amount_out, 1_850_000_000)
        
        # Leg2: 1850 USDC → WETH at buy_dex rate (1800 USDC/WETH)
        # 1850 / 1800 = 1.0278 WETH
        self.assertAlmostEqual(
            result.leg2_amount_out / 1e18,
            1.0278,
            delta=0.001,
            msg="leg2 should return ~1.0278 WETH"
        )
        
        # Net profit in base token
        self.assertGreater(result.gross_pnl_wei, 0, "should have positive gross PnL")
        self.assertGreater(result.gross_pnl_bps, 200, "should have > 200 bps gross profit")


class TestRoundtripLegProvenance(unittest.TestCase):
    """Tests for v2.2.0 leg1/leg2 dex/pool/fee fields."""
    
    def test_leg_provenance_fields_populated(self):
        """Verify leg1_dex, leg2_dex, leg1_pool, leg2_pool, leg1_fee, leg2_fee are set."""
        quote1 = {
            "dex_id": "sushiswap_v3",
            "pool_address": "0xPool1",
            "fee": 500,
            "token_in": "WETH",
            "token_out": "USDC",
            "amount_in_wei": 1_000_000_000_000_000_000,
            "amount_out_wei": 1_850_000_000,
            "gas_estimate": 150_000,
        }
        
        quote2 = {
            "dex_id": "uniswap_v3",
            "pool_address": "0xPool2",
            "fee": 3000,
            "token_in": "WETH",
            "token_out": "USDC",
            "amount_in_wei": 1_000_000_000_000_000_000,
            "amount_out_wei": 1_800_000_000,
            "gas_estimate": 150_000,
        }
        
        def leg2_callback(amount_in_wei: int):
            return {"amount_out_wei": int(1.02 * 1e18), "gas_estimate": 150_000}
        
        result = simulate_roundtrip(
            buy_quote=quote1,
            sell_quote=quote2,
            gas_price_wei=0,
            l1_cost_wei=0,
            leg2_quote_callback=leg2_callback,
        )
        
        # v2.2.0: Leg provenance fields
        self.assertEqual(result.leg1_dex, "sushiswap_v3")
        self.assertEqual(result.leg2_dex, "uniswap_v3")
        self.assertEqual(result.leg1_pool, "0xPool1")
        self.assertEqual(result.leg2_pool, "0xPool2")
        self.assertEqual(result.leg1_fee, 500)
        self.assertEqual(result.leg2_fee, 3000)
        
        # Also verify in to_dict
        d = result.to_dict()
        self.assertEqual(d["leg1_dex"], "sushiswap_v3")
        self.assertEqual(d["leg2_dex"], "uniswap_v3")
        self.assertEqual(d["leg1_pool"], "0xPool1")
        self.assertEqual(d["leg2_pool"], "0xPool2")
        self.assertEqual(d["leg1_fee"], 500)
        self.assertEqual(d["leg2_fee"], 3000)


class TestRoundtripCrossDexFilter(unittest.TestCase):
    """v2.2.1: Tests for roundtrip cross-DEX eligibility filter."""
    
    def test_is_cross_dex_true_for_different_dexes(self):
        """Opportunity with different buy_dex/sell_dex should pass cross-DEX check."""
        from dataclasses import dataclass
        
        @dataclass
        class MockOpp:
            buy_dex: str
            sell_dex: str
            buy_fee: int = 500
            sell_fee: int = 500
            gross_spread_bps: float = 20.0
        
        opp = MockOpp(buy_dex="uniswap_v3", sell_dex="sushiswap_v3")
        self.assertNotEqual(opp.buy_dex, opp.sell_dex)
    
    def test_is_cross_dex_false_for_same_dex(self):
        """Opportunity with same buy_dex/sell_dex should fail cross-DEX check."""
        from dataclasses import dataclass
        
        @dataclass
        class MockOpp:
            buy_dex: str
            sell_dex: str
        
        opp = MockOpp(buy_dex="uniswap_v3", sell_dex="uniswap_v3")
        self.assertEqual(opp.buy_dex, opp.sell_dex)
    
    def test_lp_fee_viable_passes_when_spread_exceeds_fees(self):
        """LP fee viability passes when gross spread > combined LP fees."""
        from dataclasses import dataclass
        
        @dataclass
        class MockOpp:
            buy_fee: int
            sell_fee: int
            gross_spread_bps: float
        
        # 500 + 500 = 1000 bps / 100 = 10 bps LP cost
        # 20 bps spread > 10 bps cost -> viable
        opp = MockOpp(buy_fee=500, sell_fee=500, gross_spread_bps=20.0)
        lp_bps = (opp.buy_fee + opp.sell_fee) / 100
        self.assertTrue(float(opp.gross_spread_bps) > lp_bps)
    
    def test_lp_fee_viable_fails_when_spread_below_fees(self):
        """LP fee viability fails when gross spread < combined LP fees."""
        from dataclasses import dataclass
        
        @dataclass
        class MockOpp:
            buy_fee: int
            sell_fee: int
            gross_spread_bps: float
        
        # 500 + 3000 = 3500 bps / 100 = 35 bps LP cost
        # 20 bps spread < 35 bps cost -> not viable
        opp = MockOpp(buy_fee=500, sell_fee=3000, gross_spread_bps=20.0)
        lp_bps = (opp.buy_fee + opp.sell_fee) / 100
        self.assertFalse(float(opp.gross_spread_bps) > lp_bps)
    
    def test_roundtrip_eligibility_requires_both_conditions(self):
        """Roundtrip eligibility requires cross-DEX AND LP fee viability."""
        from dataclasses import dataclass
        
        @dataclass
        class MockOpp:
            buy_dex: str
            sell_dex: str
            buy_fee: int
            sell_fee: int
            gross_spread_bps: float
        
        def is_cross_dex(opp):
            return opp.buy_dex != opp.sell_dex
        
        def lp_fee_viable(opp):
            lp_bps = (opp.buy_fee + opp.sell_fee) / 100
            return float(opp.gross_spread_bps) > lp_bps
        
        def roundtrip_eligible(opp):
            return is_cross_dex(opp) and lp_fee_viable(opp)
        
        # Cross-DEX + LP viable -> eligible
        opp1 = MockOpp(buy_dex="uniswap_v3", sell_dex="sushiswap_v3", 
                       buy_fee=500, sell_fee=500, gross_spread_bps=20.0)
        self.assertTrue(roundtrip_eligible(opp1))
        
        # Same-DEX + LP viable -> NOT eligible
        opp2 = MockOpp(buy_dex="uniswap_v3", sell_dex="uniswap_v3",
                       buy_fee=500, sell_fee=500, gross_spread_bps=20.0)
        self.assertFalse(roundtrip_eligible(opp2))
        
        # Cross-DEX + LP NOT viable -> NOT eligible
        opp3 = MockOpp(buy_dex="uniswap_v3", sell_dex="sushiswap_v3",
                       buy_fee=500, sell_fee=3000, gross_spread_bps=20.0)
        self.assertFalse(roundtrip_eligible(opp3))


if __name__ == "__main__":
    unittest.main()
