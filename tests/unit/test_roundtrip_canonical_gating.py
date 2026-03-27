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


class TestSweepTruthPromotion(unittest.TestCase):
    """R39u: Dynamic sweep with measured_economics promotes profit_realism_status.

    CONTRACT: When measured_economics.available=true AND executable_evidence
    is SWEEP_GAP_TO_ZERO or SWEEP_PROFITABLE, profit_realism_status must NOT
    be ONE_LEG_ONLY_DIAGNOSTIC — even when evaluated_count=0.
    """

    def test_sweep_gap_to_zero_promotes_to_not_profitable(self):
        """Base-like case: sweep available, negative truth, eval=0 → ROUNDTRIP_NOT_PROFITABLE."""
        from strategy.artifacts import build_truth_data

        stats = build_minimal_stats(
            roundtrip={
                "enabled": True,
                "evaluated_count": 0,
                "profitable_count": 0,
                "real_quote_count": 0,
                "executable_evidence": "SWEEP_GAP_TO_ZERO",
                "dynamic_sweep": {
                    "enabled": True,
                    "best_pair": "USDC/DAI",
                    "best_net_pnl_bps": -8.64,
                    "best_size_usd": 75,
                    "gap_to_zero_bps": 8.64,
                    "best_gas_bps": 1.97,
                    "best_fee_bps": 6.0,
                    "best_slippage_bps": 4.15,
                    "best_total_cost_bps": 12.12,
                    "routes_swept": 3,
                },
            }
        )
        result = build_truth_data(
            config={"truth_mode_m42": True},
            current_block=43911218,
            spread_signals=[],
            suspect_examples=[],
            stats=stats,
            infra_payload={},
            raw_bps=0,
            spread_threshold_bps=5,
        )
        self.assertEqual(result["profit_realism_status"], "ROUNDTRIP_NOT_PROFITABLE")
        self.assertFalse(result["profit_is_diagnostic"])
        self.assertEqual(result["profit_truth_source"], "ROUNDTRIP_CANONICAL")

    def test_sweep_profitable_promotes_to_profitable(self):
        """Sweep profitable → ROUNDTRIP_PROFITABLE even with evaluated_count=0."""
        from strategy.artifacts import build_truth_data

        stats = build_minimal_stats(
            roundtrip={
                "enabled": True,
                "evaluated_count": 0,
                "profitable_count": 0,
                "real_quote_count": 0,
                "executable_evidence": "SWEEP_PROFITABLE",
                "dynamic_sweep": {
                    "enabled": True,
                    "best_pair": "USDC/DAI",
                    "best_net_pnl_bps": 2.5,
                    "best_size_usd": 100,
                    "gap_to_zero_bps": -2.5,
                    "best_gas_bps": 1.5,
                    "best_fee_bps": 3.0,
                    "best_slippage_bps": 1.0,
                    "best_total_cost_bps": 5.5,
                    "routes_swept": 2,
                },
            }
        )
        result = build_truth_data(
            config={"truth_mode_m42": True},
            current_block=43911218,
            spread_signals=[],
            suspect_examples=[],
            stats=stats,
            infra_payload={},
            raw_bps=0,
            spread_threshold_bps=5,
        )
        self.assertEqual(result["profit_realism_status"], "ROUNDTRIP_PROFITABLE")
        self.assertFalse(result["profit_is_diagnostic"])
        self.assertEqual(result["profit_truth_source"], "ROUNDTRIP_CANONICAL")

    def test_no_sweep_data_stays_diagnostic(self):
        """No sweep + no evaluated → still ONE_LEG_ONLY_DIAGNOSTIC."""
        from strategy.artifacts import build_truth_data

        stats = build_minimal_stats(
            roundtrip={
                "enabled": True,
                "evaluated_count": 0,
                "profitable_count": 0,
                "executable_evidence": "NO_SWEEP_DATA",
                "dynamic_sweep": {
                    "enabled": False,
                },
            }
        )
        result = build_truth_data(
            config={"truth_mode_m42": True},
            current_block=12345678,
            spread_signals=[],
            suspect_examples=[],
            stats=stats,
            infra_payload={},
            raw_bps=0,
            spread_threshold_bps=5,
        )
        self.assertEqual(result["profit_realism_status"], "ONE_LEG_ONLY_DIAGNOSTIC")
        self.assertTrue(result["profit_is_diagnostic"])
        self.assertEqual(result["profit_truth_source"], "ONE_LEG_DIAGNOSTIC")

    def test_sweep_enabled_but_no_results_stays_diagnostic(self):
        """Sweep enabled but best_net_pnl_bps=None → ONE_LEG_ONLY_DIAGNOSTIC."""
        from strategy.artifacts import build_truth_data

        stats = build_minimal_stats(
            roundtrip={
                "enabled": True,
                "evaluated_count": 0,
                "profitable_count": 0,
                "executable_evidence": "NO_SWEEP_DATA",
                "dynamic_sweep": {
                    "enabled": True,
                    "best_net_pnl_bps": None,
                },
            }
        )
        result = build_truth_data(
            config={"truth_mode_m42": True},
            current_block=12345678,
            spread_signals=[],
            suspect_examples=[],
            stats=stats,
            infra_payload={},
            raw_bps=0,
            spread_threshold_bps=5,
        )
        self.assertEqual(result["profit_realism_status"], "ONE_LEG_ONLY_DIAGNOSTIC")

    def test_legacy_profitable_still_works(self):
        """Legacy path (profitable_count>0 + real_quote_count>0) still promotes correctly."""
        from strategy.artifacts import build_truth_data

        stats = build_minimal_stats(
            roundtrip={
                "enabled": True,
                "evaluated_count": 5,
                "profitable_count": 2,
                "real_quote_count": 3,
            }
        )
        result = build_truth_data(
            config={"truth_mode_m42": True},
            current_block=12345678,
            spread_signals=[],
            suspect_examples=[],
            stats=stats,
            infra_payload={},
            raw_bps=0,
            spread_threshold_bps=5,
        )
        self.assertEqual(result["profit_realism_status"], "ROUNDTRIP_PROFITABLE")
        self.assertFalse(result["profit_is_diagnostic"])
        self.assertEqual(result["profit_truth_source"], "ROUNDTRIP_CANONICAL")

    def test_suspect_contamination_guard_intact(self):
        """profitable_count>0 but real_quote_count=0 must NOT promote (suspect guard)."""
        from strategy.artifacts import build_truth_data

        stats = build_minimal_stats(
            roundtrip={
                "enabled": True,
                "evaluated_count": 5,
                "profitable_count": 3,
                "real_quote_count": 0,
            }
        )
        result = build_truth_data(
            config={"truth_mode_m42": True},
            current_block=12345678,
            spread_signals=[],
            suspect_examples=[],
            stats=stats,
            infra_payload={},
            raw_bps=0,
            spread_threshold_bps=5,
        )
        self.assertNotEqual(result["profit_realism_status"], "ROUNDTRIP_PROFITABLE")
        self.assertTrue(result["profit_is_diagnostic"])
        self.assertNotEqual(result["profit_truth_source"], "ROUNDTRIP_CANONICAL")


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


class TestBestNetPnlBpsSaneFiltering(unittest.TestCase):
    """R28.19: best_net_pnl_bps must come from sane-filtered universe.

    CONTRACT: profitable_count=0 must NEVER coexist with absurd positive
    best_net_pnl_bps. The scanner's sane filter (SANE_RT_PNL_MAX=500)
    must gate the value before it reaches stats or truth report.
    """

    def test_all_insane_roundtrips_yields_none(self):
        """When ALL roundtrip results have absurd PnL, best_net_pnl_bps=None."""
        from strategy.artifacts import build_truth_data

        config = {"truth_mode_m42": True}
        stats = build_minimal_stats(
            roundtrip={
                "enabled": True,
                "evaluated_count": 3,
                "profitable_count": 0,
                "suspect_profitable_count": 3,
                "real_quote_count": 0,
                "best_net_pnl_bps": None,  # Scanner already filtered
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

        rs = result["roundtrip_summary"]
        self.assertIsNone(rs["best_net_pnl_bps"])
        self.assertEqual(result["profit_realism_status"], "ROUNDTRIP_NOT_PROFITABLE")

    def test_mixed_sane_and_insane_uses_sane_best(self):
        """When mix of sane/insane, best_net_pnl_bps reflects only the sane max."""
        from strategy.artifacts import build_truth_data

        config = {"truth_mode_m42": True}
        # Scanner should have computed: sane best = 45.0 (the insane 8e16 is filtered)
        stats = build_minimal_stats(
            roundtrip={
                "enabled": True,
                "evaluated_count": 4,
                "profitable_count": 1,
                "suspect_profitable_count": 1,
                "real_quote_count": 2,
                "best_net_pnl_bps": 45.0,  # From sane-filtered max
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

        rs = result["roundtrip_summary"]
        self.assertEqual(rs["best_net_pnl_bps"], 45.0)
        self.assertEqual(result["profit_realism_status"], "ROUNDTRIP_PROFITABLE")

    def test_zero_profitable_with_none_best_pnl(self):
        """profitable_count=0 with best_net_pnl_bps=None is valid (no contamination)."""
        from strategy.artifacts import build_truth_data

        config = {"truth_mode_m42": True}
        stats = build_minimal_stats(
            roundtrip={
                "enabled": True,
                "evaluated_count": 5,
                "profitable_count": 0,
                "suspect_profitable_count": 2,
                "real_quote_count": 3,
                "best_net_pnl_bps": None,
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

        rs = result["roundtrip_summary"]
        self.assertIsNone(rs["best_net_pnl_bps"])
        self.assertEqual(result["profit_realism_status"], "ROUNDTRIP_NOT_PROFITABLE")

    def test_sane_negative_best_preserved(self):
        """Negative but sane best_net_pnl_bps is preserved (not forced to None)."""
        from strategy.artifacts import build_truth_data

        config = {"truth_mode_m42": True}
        stats = build_minimal_stats(
            roundtrip={
                "enabled": True,
                "evaluated_count": 3,
                "profitable_count": 0,
                "real_quote_count": 2,
                "best_net_pnl_bps": -42.5,
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

        rs = result["roundtrip_summary"]
        self.assertEqual(rs["best_net_pnl_bps"], -42.5)


class TestUpdateChainStatsSaneGuard(unittest.TestCase):
    """R28.17/R28.19: update_chain_stats must reject insane best_net_pnl_bps.

    The secondary guard in start.py prevents contaminated values from
    accumulating even if the scanner's primary filter is bypassed.
    """

    def _make_chain_stats(self):
        """Fresh per-chain stats dict matching new_chain_stats()."""
        from start import new_chain_stats
        return new_chain_stats()

    def test_absurd_positive_rejected(self):
        """best_net_pnl_bps > SANE_MAX is not accumulated."""
        from start import update_chain_stats, SANE_ROUNDTRIP_PNL_BPS_MAX

        cs = self._make_chain_stats()
        summary = {
            "metrics": {
                "roundtrip": {
                    "evaluated_count": 2,
                    "profitable_count": 0,
                    "real_quote_count": 1,
                    "best_net_pnl_bps": 8.2e16,  # Absurd value from old bug
                },
            },
        }
        update_chain_stats(cs, exit_code=0, run_dir=None, summary=summary)
        # Must NOT have accumulated the absurd value
        self.assertIsNone(cs.get("best_roundtrip_net_bps"))
        self.assertEqual(cs.get("_suspect_accounting_count", 0), 1)

    def test_sane_value_accumulated(self):
        """best_net_pnl_bps within sane range IS accumulated."""
        from start import update_chain_stats

        cs = self._make_chain_stats()
        summary = {
            "metrics": {
                "roundtrip": {
                    "evaluated_count": 2,
                    "profitable_count": 1,
                    "real_quote_count": 2,
                    "best_net_pnl_bps": 45.0,
                },
            },
        }
        update_chain_stats(cs, exit_code=0, run_dir=None, summary=summary)
        self.assertEqual(cs["best_roundtrip_net_bps"], 45.0)
        self.assertEqual(cs.get("_suspect_accounting_count", 0), 0)

    def test_none_pnl_no_accumulation(self):
        """best_net_pnl_bps=None (all insane at scanner) does not accumulate."""
        from start import update_chain_stats

        cs = self._make_chain_stats()
        summary = {
            "metrics": {
                "roundtrip": {
                    "evaluated_count": 3,
                    "profitable_count": 0,
                    "real_quote_count": 1,
                    "best_net_pnl_bps": None,
                },
            },
        }
        update_chain_stats(cs, exit_code=0, run_dir=None, summary=summary)
        self.assertIsNone(cs.get("best_roundtrip_net_bps"))
        self.assertEqual(cs.get("_suspect_accounting_count", 0), 0)

    def test_classify_suspect_accounting_after_absurd(self):
        """classify_chain_profit_state returns SUSPECT_ACCOUNTING when absurd values leaked."""
        from start import update_chain_stats, classify_chain_profit_state

        cs = self._make_chain_stats()

        # First: a sane profitable run (builds up profitable count)
        summary_good = {
            "metrics": {
                "roundtrip": {
                    "evaluated_count": 2,
                    "profitable_count": 1,
                    "real_quote_count": 2,
                    "best_net_pnl_bps": 30.0,
                },
            },
        }
        update_chain_stats(cs, exit_code=0, run_dir=None, summary=summary_good)

        # Second: an absurd run (contaminates accounting)
        summary_bad = {
            "metrics": {
                "roundtrip": {
                    "evaluated_count": 1,
                    "profitable_count": 1,
                    "real_quote_count": 1,
                    "best_net_pnl_bps": 9999.0,
                },
            },
        }
        update_chain_stats(cs, exit_code=0, run_dir=None, summary=summary_bad)

        state = classify_chain_profit_state(cs)
        self.assertEqual(state, "SUSPECT_ACCOUNTING")


class TestLegSourceSummaryInTruthReport(unittest.TestCase):
    """R39i++: leg_source_summary must propagate through roundtrip_summary."""

    def test_leg_source_summary_in_roundtrip_summary(self):
        """leg_source_summary flows from stats through roundtrip_summary."""
        from strategy.artifacts import build_truth_data

        config = {}
        stats = build_minimal_stats(
            roundtrip={
                "enabled": True,
                "evaluated_count": 3,
                "profitable_count": 0,
                "real_quote_count": 1,
                "best_net_pnl_bps": -15.0,
                "leg_source_summary": {
                    "leg1": {"quoter_v2": 2, "slot0": 1},
                    "leg2": {"quoter_v2": 1, "slot0": 2},
                    "both_quoter_v2": 1,
                    "both_slot0": 1,
                    "mixed_source": 1,
                    "total": 3,
                },
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

        rs = result["roundtrip_summary"]
        self.assertIn("leg_source_summary", rs)
        lss = rs["leg_source_summary"]
        self.assertEqual(lss["both_quoter_v2"], 1)
        self.assertEqual(lss["mixed_source"], 1)
        self.assertEqual(lss["total"], 3)

    def test_leg_source_summary_absent_when_not_provided(self):
        """leg_source_summary is None when roundtrip stats don't provide it."""
        from strategy.artifacts import build_truth_data

        config = {}
        stats = build_minimal_stats(
            roundtrip={
                "enabled": True,
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

        rs = result["roundtrip_summary"]
        self.assertIn("leg_source_summary", rs)
        self.assertIsNone(rs["leg_source_summary"])


class TestAggregateLegSources(unittest.TestCase):
    """R39i++: Tests for aggregate_leg_sources helper."""

    def test_all_quoter_v2(self):
        from engine.roundtrip import aggregate_leg_sources
        from engine.roundtrip import RoundTripResult

        results = [
            RoundTripResult(
                pair="WETH/USDC", buy_dex="uni", sell_dex="sushi",
                amount_in_wei=1, token_in="W", token_out="U",
                leg1_amount_out=1, leg1_source="quoter_v2", leg2_source="quoter_v2",
            ),
            RoundTripResult(
                pair="WETH/USDC", buy_dex="uni", sell_dex="sushi",
                amount_in_wei=1, token_in="W", token_out="U",
                leg1_amount_out=1, leg1_source="quoter_v2", leg2_source="quoter_v2",
            ),
        ]
        agg = aggregate_leg_sources(results)
        self.assertEqual(agg["both_quoter_v2"], 2)
        self.assertEqual(agg["mixed_source"], 0)
        self.assertEqual(agg["total"], 2)

    def test_mixed_source_counted(self):
        from engine.roundtrip import aggregate_leg_sources
        from engine.roundtrip import RoundTripResult

        results = [
            RoundTripResult(
                pair="WETH/USDC", buy_dex="uni", sell_dex="sushi",
                amount_in_wei=1, token_in="W", token_out="U",
                leg1_amount_out=1, leg1_source="quoter_v2", leg2_source="slot0",
            ),
        ]
        agg = aggregate_leg_sources(results)
        self.assertEqual(agg["mixed_source"], 1)
        self.assertEqual(agg["both_quoter_v2"], 0)

    def test_empty_results(self):
        from engine.roundtrip import aggregate_leg_sources

        agg = aggregate_leg_sources([])
        self.assertEqual(agg["total"], 0)


class TestBlockerEvidenceRqZeroNotEconomics(unittest.TestCase):
    """R39i++: Chain with real_quote_count_total=0 cannot be OE_ECONOMICS.

    CONTRACT: If no real quotes were obtained (rq=0), the chain is either
    QUOTE_PATH_BLOCKED (quoter failures) or NO_SIGNAL, never OE_ECONOMICS.
    A diagnostic sweep with rq=0 does NOT prove the executable path works.
    """

    def test_rq_zero_with_oe_reject_is_quote_path_blocked(self):
        """rq=0 + OE mixed/slot0 rejects → QUOTE_PATH_BLOCKED, not OE_ECONOMICS."""
        from strategy.chain_stats import _compute_blocker_evidence

        stats = {
            "profitable_roundtrips_total": 0,
            "runs": 10,
            "fail": 0,
            "included_signals_total": 50,
            "roundtrip_evaluated_total": 5,
            "real_quote_count_total": 0,
            "runs_with_sweep": 2,
            "last_cross_dex_pairs_count": 9,
            "last_quote_source_summary": {
                "quotes_fetched_executable": 0,
                "quotes_fetched_diagnostic": 80,
                "quoter_v2_failed_count": 50,
            },
            "last_oe_rejection_funnel": {
                "total_opportunities": 30,
                "rejected_count": 25,
                "rejected_reasons": {
                    "SLOT0_DIAGNOSTIC": 15,
                    "MIXED_SOURCE": 5,
                    "NET_PROFIT_TOO_LOW": 5,
                },
            },
            "last_truth_verdict": None,
        }
        _compute_blocker_evidence(stats)
        # With rq=0 and >50% quoter failure → QUOTE_PATH_BLOCKED
        self.assertEqual(stats["blocker_evidence"], "QUOTE_PATH_BLOCKED")

    def test_rq_positive_with_economics_is_oe_economics(self):
        """rq>0 + OE economics rejects → OE_ECONOMICS (quote path works)."""
        from strategy.chain_stats import _compute_blocker_evidence

        stats = {
            "profitable_roundtrips_total": 0,
            "runs": 10,
            "fail": 0,
            "included_signals_total": 50,
            "roundtrip_evaluated_total": 5,
            "real_quote_count_total": 3,
            "runs_with_sweep": 2,
            "last_cross_dex_pairs_count": 9,
            "last_quote_source_summary": {
                "quotes_fetched_executable": 20,
                "quotes_fetched_diagnostic": 40,
                "quoter_v2_failed_count": 10,
            },
            "last_oe_rejection_funnel": {
                "total_opportunities": 30,
                "rejected_count": 25,
                "rejected_reasons": {
                    "NET_PROFIT_TOO_LOW": 20,
                    "MIXED_SOURCE": 3,
                    "SLOT0_DIAGNOSTIC": 2,
                },
            },
            "last_truth_verdict": None,
            "_sweep_gap_values": [],
        }
        _compute_blocker_evidence(stats)
        self.assertEqual(stats["blocker_evidence"], "OE_ECONOMICS")


class TestTruthLaneReranking(unittest.TestCase):
    """R39v: Truth-lane reranking demotes toxic one-leg routes.

    CONTRACT: When truth_mode_m42=true, top_opportunities must be ranked by
    measured economics (spread_minus_required_bps from spread_signals), NOT by
    paper net_profit_usd.  A WETH/USDC route with positive paper PnL but deeply
    negative measured surplus (-282 bps) must NOT outrank a USDC/DAI route with
    smaller paper PnL but much better measured surplus (-17 bps).
    """

    @staticmethod
    def _rank_truth_lane(spread_signals):
        """Replicate the truth-lane ranking from run_scan_real.py."""
        actionable = [s for s in spread_signals if not s.get("is_diagnostic_only")]
        return sorted(
            actionable,
            key=lambda s: s.get("spread_minus_required_bps", -9999),
            reverse=True,
        )[:5]

    def test_toxic_weth_demoted_below_stable_pair(self):
        """WETH/USDC one-leg positive + measured negative → NOT top truth-lane candidate."""
        signals = [
            # Toxic: positive paper PnL but deeply negative measured economics
            {"pair": "WETH/USDC", "route": "pancakeswap_v3->uniswap_v3",
             "spread_minus_required_bps": -281.94, "net_pnl_usdc_est": 0.877,
             "effective_slippage_bps": 359.39, "is_diagnostic_only": False},
            {"pair": "WETH/USDC", "route": "pancakeswap_v3->sushiswap_v3",
             "spread_minus_required_bps": -291.51, "net_pnl_usdc_est": 0.849,
             "effective_slippage_bps": 359.33, "is_diagnostic_only": False},
            # Stable: small paper PnL but much better measured margin
            {"pair": "USDC/DAI", "route": "uniswap_v3->sushiswap_v3",
             "spread_minus_required_bps": -17.29, "net_pnl_usdc_est": -0.046,
             "effective_slippage_bps": 5.0, "is_diagnostic_only": False},
            {"pair": "USDC/DAI", "route": "uniswap_v3->pancakeswap_v3",
             "spread_minus_required_bps": -17.31, "net_pnl_usdc_est": -0.047,
             "effective_slippage_bps": 5.0, "is_diagnostic_only": False},
        ]
        ranked = self._rank_truth_lane(signals)
        # USDC/DAI (-17 bps) must rank above WETH/USDC (-282 bps)
        self.assertEqual(ranked[0]["pair"], "USDC/DAI")
        self.assertEqual(ranked[1]["pair"], "USDC/DAI")
        self.assertEqual(ranked[2]["pair"], "WETH/USDC")
        self.assertEqual(ranked[3]["pair"], "WETH/USDC")

    def test_stable_pair_survives_truth_lane_ordering(self):
        """USDC/DAI or USDC/USDT with better measured margin → top truth-lane candidate."""
        signals = [
            {"pair": "WETH/USDC", "route": "sushiswap_v3->uniswap_v3",
             "spread_minus_required_bps": -708.53, "net_pnl_usdc_est": 4.35,
             "effective_slippage_bps": 1481.28, "is_diagnostic_only": False},
            {"pair": "USDC/USDT", "route": "pancakeswap_v3->sushiswap_v3",
             "spread_minus_required_bps": -79.02, "net_pnl_usdc_est": 0.20,
             "effective_slippage_bps": 20.25, "is_diagnostic_only": False},
            {"pair": "USDC/DAI", "route": "uniswap_v3->sushiswap_v3",
             "spread_minus_required_bps": -17.29, "net_pnl_usdc_est": -0.05,
             "effective_slippage_bps": 5.0, "is_diagnostic_only": False},
        ]
        ranked = self._rank_truth_lane(signals)
        # Stable pair (USDC/DAI) is closest to zero → #1
        self.assertEqual(ranked[0]["pair"], "USDC/DAI")
        # USDC/USDT → #2
        self.assertEqual(ranked[1]["pair"], "USDC/USDT")
        # Toxic WETH/USDC → #3 (last)
        self.assertEqual(ranked[2]["pair"], "WETH/USDC")

    def test_diagnostic_only_excluded_from_truth_lane(self):
        """Diagnostic-only signals must NOT appear in truth-lane ranking."""
        signals = [
            {"pair": "WETH/USDC", "route": "slot0_diag",
             "spread_minus_required_bps": -10.0, "is_diagnostic_only": True},
            {"pair": "USDC/DAI", "route": "uniswap_v3->sushiswap_v3",
             "spread_minus_required_bps": -17.29, "is_diagnostic_only": False},
        ]
        ranked = self._rank_truth_lane(signals)
        self.assertEqual(len(ranked), 1)
        self.assertEqual(ranked[0]["pair"], "USDC/DAI")

    def test_truth_lane_empty_when_no_actionable_signals(self):
        """All diagnostic → truth-lane is empty."""
        signals = [
            {"pair": "WETH/USDC", "spread_minus_required_bps": -10.0, "is_diagnostic_only": True},
        ]
        ranked = self._rank_truth_lane(signals)
        self.assertEqual(ranked, [])

    def test_paper_top_preserved_separately(self):
        """Paper-ranked OE opps are preserved as _paper_top_opportunities when truth_mode_m42."""
        # Simulate what run_scan_real.py does
        opps_list = [
            {"pair": "WETH/USDC", "net_profit_usd": 0.17, "gate_passed": True,
             "measured_spread_minus_required_bps": -282},
        ]
        spread_signals = [
            {"pair": "USDC/DAI", "spread_minus_required_bps": -17.29, "is_diagnostic_only": False},
        ]
        truth_mode_m42 = True

        _paper_top = opps_list[:5]
        if truth_mode_m42 and spread_signals:
            _actionable = [s for s in spread_signals if not s.get("is_diagnostic_only")]
            _truth_lane_top = sorted(
                _actionable,
                key=lambda s: s.get("spread_minus_required_bps", -9999),
                reverse=True,
            )[:5]
        else:
            _truth_lane_top = None

        top_opps = _truth_lane_top if _truth_lane_top is not None else _paper_top
        paper_diag = _paper_top if _truth_lane_top is not None else []

        # top_opportunities should be truth-lane (USDC/DAI)
        self.assertEqual(top_opps[0]["pair"], "USDC/DAI")
        # _paper_top_opportunities preserved for diagnostics
        self.assertEqual(paper_diag[0]["pair"], "WETH/USDC")


if __name__ == "__main__":
    unittest.main()
