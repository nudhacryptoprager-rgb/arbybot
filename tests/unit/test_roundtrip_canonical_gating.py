"""
Unit tests for M4.2 roundtrip canonical gating.

v2.1.0: Ensures that when truth_mode_m42=true:
- One-leg profit is DIAGNOSTIC only
- Roundtrip is canonical for gating decisions
- ROUNDTRIP_NOT_PROFITABLE must block "profit proven" claims
"""
import unittest


def build_minimal_stats(**overrides):
    """Build minimal stats dict required by build_truth_data."""
    base = {
        "quotes_total": 10,
        "quotes_fetched": 8,
        "dexes_active": 2,
        "price_sanity_passed": 6,
        "price_sanity_failed": 2,
        "gates_passed": 4,
        "roundtrip": {
            "enabled": True,
            "evaluated_count": 0,
            "profitable_count": 0,
        },
    }
    base.update(overrides)
    return base


class TestRoundtripCanonicalGating(unittest.TestCase):
    """Tests for roundtrip as canonical profit source in M4.2."""
    
    def test_profit_realism_status_roundtrip_not_profitable(self):
        """When roundtrip evaluated but none profitable -> ROUNDTRIP_NOT_PROFITABLE."""
        from strategy.artifacts import build_truth_data
        
        config = {"truth_mode_m42": True}
        stats = build_minimal_stats(
            roundtrip={
                "enabled": True,
                "evaluated_count": 3,
                "profitable_count": 0,  # None profitable
                "real_quote_count": 2,
                "best_net_pnl_bps": -65.0,
            }
        )
        
        result = build_truth_data(
            config=config,
            current_block=12345678,
            spread_signals=[],
            suspect_examples=[],
            stats=stats,
            infra_payload={},
            raw_bps=0,
            spread_threshold_bps=5,
        )
        
        self.assertEqual(result["profit_realism_status"], "ROUNDTRIP_NOT_PROFITABLE")
        self.assertEqual(result["truth_mode_m42"], True)
    
    def test_profit_realism_status_roundtrip_profitable(self):
        """When roundtrip shows profitable -> ROUNDTRIP_PROFITABLE."""
        from strategy.artifacts import build_truth_data
        
        config = {"truth_mode_m42": True}
        stats = build_minimal_stats(
            roundtrip={
                "enabled": True,
                "evaluated_count": 3,
                "profitable_count": 1,  # One profitable
                "real_quote_count": 2,
                "best_net_pnl_bps": 15.5,
            }
        )
        
        result = build_truth_data(
            config=config,
            current_block=12345678,
            spread_signals=[],
            suspect_examples=[],
            stats=stats,
            infra_payload={},
            raw_bps=0,
            spread_threshold_bps=5,
        )
        
        self.assertEqual(result["profit_realism_status"], "ROUNDTRIP_PROFITABLE")
    
    def test_profit_realism_status_one_leg_only(self):
        """When no roundtrip evaluated -> ONE_LEG_ONLY_DIAGNOSTIC."""
        from strategy.artifacts import build_truth_data
        
        config = {"truth_mode_m42": True}
        stats = build_minimal_stats(
            roundtrip={
                "enabled": False,
                "evaluated_count": 0,
                "profitable_count": 0,
            }
        )
        
        result = build_truth_data(
            config=config,
            current_block=12345678,
            spread_signals=[],
            suspect_examples=[],
            stats=stats,
            infra_payload={},
            raw_bps=0,
            spread_threshold_bps=5,
        )
        
        self.assertEqual(result["profit_realism_status"], "ONE_LEG_ONLY_DIAGNOSTIC")
    
    def test_truth_mode_m42_disables_one_leg_canonical(self):
        """When truth_mode_m42=True, one-leg profit must be diagnostic only.
        
        CONTRACT: M4.2 specifies that one-leg spread profit is NOT canonical
        when roundtrip mode is enabled. This test ensures that even if one-leg
        shows profit, the roundtrip result takes precedence.
        """
        from strategy.artifacts import build_truth_data
        
        config = {"truth_mode_m42": True}
        
        # One-leg signals show profit (old-style)
        spread_signals = [
            {
                "spread_id": "spread_1",
                "spread_bps": 50,
                "net_usdc": 10.0,  # One-leg shows profit
            }
        ]
        
        # But roundtrip shows loss
        stats = build_minimal_stats(
            roundtrip={
                "enabled": True,
                "evaluated_count": 1,
                "profitable_count": 0,  # Roundtrip NOT profitable
                "best_net_pnl_bps": -30.0,
            }
        )
        
        result = build_truth_data(
            config=config,
            current_block=12345678,
            spread_signals=spread_signals,
            suspect_examples=[],
            stats=stats,
            infra_payload={},
            raw_bps=0,
            spread_threshold_bps=5,
        )
        
        # Even though one-leg shows profit, profit_realism_status must be NOT_PROFITABLE
        self.assertEqual(result["profit_realism_status"], "ROUNDTRIP_NOT_PROFITABLE")
        
        # This documents the contract: roundtrip is canonical when truth_mode_m42=True
        self.assertIn("truth_mode_m42", result)
        self.assertTrue(result["truth_mode_m42"])
    
    def test_roundtrip_summary_in_truth_report(self):
        """roundtrip_summary must be present in truth_report."""
        from strategy.artifacts import build_truth_data
        
        config = {}
        stats = build_minimal_stats(
            roundtrip={
                "enabled": True,
                "evaluated_count": 5,
                "profitable_count": 2,
                "real_quote_count": 4,
                "best_net_pnl_bps": 25.5,
                "l1_cost_wei": 123456789,
                "l1_cost_source": "onchain",
                "gas_price_wei_used": 100000000,
                "best_measured_spread_gap_bps": -42.3,
            }
        )
        
        result = build_truth_data(
            config=config,
            current_block=12345678,
            spread_signals=[],
            suspect_examples=[],
            stats=stats,
            infra_payload={},
            raw_bps=0,
            spread_threshold_bps=5,
        )
        
        self.assertIn("roundtrip_summary", result)
        
        rs = result["roundtrip_summary"]
        self.assertEqual(rs["enabled"], True)
        self.assertEqual(rs["evaluated_count"], 5)
        self.assertEqual(rs["profitable_count"], 2)
        self.assertEqual(rs["real_quote_count"], 4)
        self.assertEqual(rs["best_net_pnl_bps"], 25.5)
        # v2.1.0-fix: New fields for execution readiness
        self.assertEqual(rs["l1_cost_wei"], 123456789)
        self.assertEqual(rs["l1_cost_source"], "onchain")
        self.assertEqual(rs["gas_price_wei_used"], 100000000)
        # M4.2 blocker metric
        self.assertAlmostEqual(rs["best_measured_spread_gap_bps"], -42.3)


class TestRoundtripResultSlippageSource(unittest.TestCase):
    """Tests for slippage source tracking in RoundTripResult."""
    
    def test_slippage_source_field_exists(self):
        """RoundTripResult must have slippage_source field."""
        from engine.roundtrip import RoundTripResult
        
        result = RoundTripResult(
            pair="WETH/USDC",
            buy_dex="uniswap_v3",
            sell_dex="sushiswap_v3",
            amount_in_wei=int(1e18),
            token_in="WETH",
            token_out="USDC",
            leg1_amount_out=1000_000000,
        )
        
        self.assertTrue(hasattr(result, "slippage_source"))
        # Default should be ticks_heuristic
        self.assertEqual(result.slippage_source, "ticks_heuristic")
    
    def test_slippage_source_in_to_dict(self):
        """slippage_source must be serialized in to_dict()."""
        from engine.roundtrip import RoundTripResult
        
        result = RoundTripResult(
            pair="WETH/USDC",
            buy_dex="uniswap_v3",
            sell_dex="sushiswap_v3",
            amount_in_wei=int(1e18),
            token_in="WETH",
            token_out="USDC",
            leg1_amount_out=1000_000000,
            slippage_source="sqrtPriceAfter",
        )
        
        d = result.to_dict()
        self.assertIn("slippage_source", d)
        self.assertEqual(d["slippage_source"], "sqrtPriceAfter")


if __name__ == "__main__":
    unittest.main()
