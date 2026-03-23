"""R39g: Tests for coverage gate fix, blocker classification fix, and gate vs profit blocker RCA."""

from unittest import TestCase


class TestCoverageGateHotRequote(TestCase):
    """R39g step 7: hot_requote universe_source should use relaxed coverage thresholds."""

    def test_hot_requote_uses_relaxed_thresholds(self):
        """Verify that hot_requote uses min_pairs=1 like discovery_runtime."""
        from scripts.ci_m5_0_gate import validate_coverage

        # Simulate thin productive contour: 2 pairs, 4 pools
        data = {
            "quotes_sample": [
                {"token_in": "WETH", "token_out": "USDC", "pool_address": "0x1"},
                {"token_in": "WETH", "token_out": "USDC", "pool_address": "0x2"},
                {"token_in": "WETH", "token_out": "ARB", "pool_address": "0x3"},
                {"token_in": "WETH", "token_out": "ARB", "pool_address": "0x4"},
            ]
        }
        # With min_pairs=5 (old behavior for hot_requote), this would FAIL
        ok_strict, msg_strict = validate_coverage(data, min_pairs=5, min_pools=6)
        self.assertFalse(ok_strict)

        # With min_pairs=1 (new behavior for hot_requote), this should PASS
        ok_relaxed, msg_relaxed = validate_coverage(data, min_pairs=1, min_pools=2)
        self.assertTrue(ok_relaxed)
        self.assertIn("coverage OK", msg_relaxed)

    def test_validate_coverage_still_fails_on_empty(self):
        """Even with relaxed thresholds, 0 pairs should fail."""
        from scripts.ci_m5_0_gate import validate_coverage

        ok, msg = validate_coverage({"quotes_sample": []}, min_pairs=1, min_pools=2)
        self.assertFalse(ok)
        self.assertIn("COVERAGE FAIL", msg)


class TestBlockerClassificationR39g(TestCase):
    """R39g step 8: INFRA_FAIL / NO_SIGNAL should not apply when RT or OE data exists."""

    def test_infra_fail_bypassed_when_rt_exists(self):
        """Chain with high fail rate but RT data should NOT get INFRA_FAIL."""
        from strategy.chain_stats import _compute_blocker_evidence

        stats = {
            "profitable_roundtrips_total": 0,
            "runs": 7,
            "fail": 5,  # fail/runs = 0.71 > 0.5
            "roundtrip_evaluated_total": 4,
            "real_quote_count_total": 4,
            "included_signals_total": 0,
            "runs_with_sweep": 0,
            "last_cross_dex_pairs_count": 4,
            "last_quote_source_summary": {},
            "last_oe_rejection_funnel": {
                "total_opportunities": 17,
                "rejected_count": 13,
                "rejected_reasons": {"MIXED_SOURCE": 8, "NET_PROFIT_TOO_LOW": 4, "SUSPECT_SPREAD_HARD": 1},
            },
            "last_truth_verdict": None,
        }
        _compute_blocker_evidence(stats)
        self.assertNotEqual(stats["blocker_evidence"], "INFRA_FAIL")
        # Should fall through to MIXED_SOURCE (8/13 = 61.5% > 30%)
        self.assertEqual(stats["blocker_evidence"], "MIXED_SOURCE")

    def test_infra_fail_bypassed_when_oe_data_exists(self):
        """Chain with high fail rate and OE data but no RT should NOT get INFRA_FAIL."""
        from strategy.chain_stats import _compute_blocker_evidence

        stats = {
            "profitable_roundtrips_total": 0,
            "runs": 7,
            "fail": 7,  # 100% fail rate
            "roundtrip_evaluated_total": 0,
            "real_quote_count_total": 0,
            "included_signals_total": 0,
            "runs_with_sweep": 0,
            "last_cross_dex_pairs_count": 3,
            "last_quote_source_summary": {},
            "last_oe_rejection_funnel": {
                "total_opportunities": 6,
                "rejected_count": 6,
                "rejected_reasons": {"SUSPECT_SPREAD_HARD": 3, "NET_PROFIT_TOO_LOW": 3},
            },
            "last_truth_verdict": None,
        }
        _compute_blocker_evidence(stats)
        self.assertNotEqual(stats["blocker_evidence"], "INFRA_FAIL")
        # Should get QUOTE_PATH_CONSTRAINED (sig=0, rt=0, rq=0, xdex=3 <= 3)
        self.assertEqual(stats["blocker_evidence"], "QUOTE_PATH_CONSTRAINED")

    def test_infra_fail_assigned_when_no_data(self):
        """Chain with high fail rate and truly no data SHOULD get INFRA_FAIL."""
        from strategy.chain_stats import _compute_blocker_evidence

        stats = {
            "profitable_roundtrips_total": 0,
            "runs": 7,
            "fail": 6,
            "roundtrip_evaluated_total": 0,
            "real_quote_count_total": 0,
            "included_signals_total": 0,
            "runs_with_sweep": 0,
            "last_cross_dex_pairs_count": 0,
            "last_quote_source_summary": {},
            "last_oe_rejection_funnel": {"total_opportunities": 0, "rejected_count": 0, "rejected_reasons": {}},
            "last_truth_verdict": None,
        }
        _compute_blocker_evidence(stats)
        self.assertEqual(stats["blocker_evidence"], "INFRA_FAIL")

    def test_no_signal_bypassed_when_rt_exists(self):
        """Chain with 0 signals but RT data should NOT get NO_SIGNAL."""
        from strategy.chain_stats import _compute_blocker_evidence

        stats = {
            "profitable_roundtrips_total": 0,
            "runs": 7,
            "fail": 1,  # fail/runs < 0.5
            "roundtrip_evaluated_total": 2,
            "real_quote_count_total": 2,
            "included_signals_total": 0,
            "runs_with_sweep": 0,
            "last_cross_dex_pairs_count": 3,
            "last_quote_source_summary": {},
            "last_oe_rejection_funnel": {
                "total_opportunities": 10,
                "rejected_count": 6,
                "rejected_reasons": {"MIXED_SOURCE": 3, "SUSPECT_SPREAD_HARD": 3},
            },
            "last_truth_verdict": None,
        }
        _compute_blocker_evidence(stats)
        self.assertNotEqual(stats["blocker_evidence"], "NO_SIGNAL")
        self.assertNotEqual(stats["blocker_evidence"], "QUOTE_PATH_CONSTRAINED")
        # Falls through to OE rejection — MIXED_SOURCE 50% > 30%
        self.assertEqual(stats["blocker_evidence"], "MIXED_SOURCE")


class TestDeriveProfitBlocker(TestCase):
    """R39g step 9: _derive_profit_blocker returns correct label from trace and truth."""

    def test_all_rt_negative(self):
        from scripts.pair_level_rca import _derive_profit_blocker

        trace = [
            {"pair": "ARB/USDC", "rt_evaluated": 1, "rt_best_net_pnl_bps": -254},
            {"pair": "WETH/ARB", "rt_evaluated": 1, "rt_best_net_pnl_bps": -442},
        ]
        truth = {"oe_rejection_funnel": {"rejected_count": 0, "rejected_reasons": {}}}
        result = _derive_profit_blocker(trace, truth)
        self.assertIn("OE_ECONOMICS", result)

    def test_profitable_rt_exists(self):
        from scripts.pair_level_rca import _derive_profit_blocker

        trace = [
            {"pair": "WETH/VIRTUAL", "rt_evaluated": 1, "rt_best_net_pnl_bps": 100},
        ]
        truth = {}
        result = _derive_profit_blocker(trace, truth)
        self.assertIn("NONE", result)

    def test_no_rt_with_oe_rejections(self):
        from scripts.pair_level_rca import _derive_profit_blocker

        trace = [
            {"pair": "WETH/USDC", "spread_signals": 5, "rt_evaluated": 0},
        ]
        truth = {
            "oe_rejection_funnel": {
                "rejected_count": 6,
                "rejected_reasons": {"SUSPECT_SPREAD_HARD": 3, "NET_PROFIT_TOO_LOW": 3},
            }
        }
        result = _derive_profit_blocker(trace, truth)
        self.assertIn("SUSPECT_SPREAD_HARD", result)

    def test_signal_dry(self):
        from scripts.pair_level_rca import _derive_profit_blocker

        trace = [{"pair": "X/Y", "spread_signals": 0, "rt_evaluated": 0}]
        truth = {"oe_rejection_funnel": {"rejected_count": 0, "rejected_reasons": {}}}
        result = _derive_profit_blocker(trace, truth)
        self.assertIn("SIGNAL_DRY", result)
