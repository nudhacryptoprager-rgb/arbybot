# PATH: tests/unit/test_execution_pnl_golden.py
"""
Golden tests for Clean PnL (execution_pnl) computation.

These tests lock the behavior of _compute_execution_pnl in strategy/artifacts.py
to prevent regressions in cost model breakdown.

Test coverage:
1. cost_model_available correctly set based on gas_usd_estimate and signals
2. Breakdown fields (gross_pnl_usdc, net_pnl_usdc) are computed correctly
3. cost_model_components includes gas_usd and slippage_bps
4. Invariant: signal_pnl_usdc == gross_pnl_usdc (same field, different name for migration)
5. filter_excluded behavior (execution_pnl vs execution_pnl_included)
"""

import unittest
from decimal import Decimal


class TestExecutionPnLGolden(unittest.TestCase):
    """Golden tests for Clean PnL computation."""

    def test_cost_model_available_with_gas_and_signals(self):
        """cost_model_available=True when gas_usd_estimate set and signals exist."""
        from strategy.artifacts import _compute_execution_pnl
        
        signals = [
            {"net_pnl_usdc_est": 10.5, "gross_pnl_usdc_est": 12.0, "is_net_positive_est": True},
            {"net_pnl_usdc_est": 5.2, "gross_pnl_usdc_est": 7.0, "is_net_positive_est": True},
        ]
        config = {"gas_usd_estimate": 0.05, "paper_slippage_bps": 10}
        
        result = _compute_execution_pnl(signals, config)
        
        self.assertTrue(result["cost_model_available"])
        self.assertEqual(result["cost_model_version"], "paper_gas_slippage_v1")
        self.assertIsNotNone(result["cost_model_components"])
        self.assertEqual(result["cost_model_components"]["gas_usd"], 0.05)
        self.assertEqual(result["cost_model_components"]["slippage_bps"], 10)

    def test_cost_model_unavailable_without_gas(self):
        """cost_model_available=False when no gas_usd_estimate."""
        from strategy.artifacts import _compute_execution_pnl
        
        signals = [
            {"net_pnl_usdc_est": 10.5, "gross_pnl_usdc_est": 12.0, "is_net_positive_est": True},
        ]
        config = {}  # No gas_usd_estimate
        
        result = _compute_execution_pnl(signals, config)
        
        self.assertFalse(result["cost_model_available"])
        self.assertIsNone(result["cost_model_version"])
        self.assertIsNone(result["cost_model_components"])

    def test_cost_model_unavailable_without_signals(self):
        """cost_model_available=False when no signals with estimates."""
        from strategy.artifacts import _compute_execution_pnl
        
        signals = []  # No signals
        config = {"gas_usd_estimate": 0.05}
        
        result = _compute_execution_pnl(signals, config)
        
        self.assertFalse(result["cost_model_available"])

    def test_gross_pnl_sum_invariant(self):
        """gross_pnl_usdc = sum of all signals' gross_pnl_usdc_est."""
        from strategy.artifacts import _compute_execution_pnl
        
        signals = [
            {"net_pnl_usdc_est": 10.5, "gross_pnl_usdc_est": 12.0, "is_net_positive_est": True},
            {"net_pnl_usdc_est": 5.2, "gross_pnl_usdc_est": 7.0, "is_net_positive_est": True},
            {"net_pnl_usdc_est": -2.0, "gross_pnl_usdc_est": 3.0, "is_net_positive_est": False},
        ]
        config = {"gas_usd_estimate": 0.05}
        
        result = _compute_execution_pnl(signals, config)
        
        expected_gross = 12.0 + 7.0 + 3.0  # 22.0
        self.assertEqual(float(result["gross_pnl_usdc"]), expected_gross)
        # signal_pnl_usdc should equal gross_pnl_usdc (migration alias)
        self.assertEqual(result["signal_pnl_usdc"], result["gross_pnl_usdc"])

    def test_net_pnl_only_positive_signals(self):
        """net_pnl_usdc = sum of only signals where is_net_positive_est=True."""
        from strategy.artifacts import _compute_execution_pnl
        
        signals = [
            {"net_pnl_usdc_est": 10.5, "gross_pnl_usdc_est": 12.0, "is_net_positive_est": True},
            {"net_pnl_usdc_est": 5.2, "gross_pnl_usdc_est": 7.0, "is_net_positive_est": True},
            {"net_pnl_usdc_est": -2.0, "gross_pnl_usdc_est": 3.0, "is_net_positive_est": False},
        ]
        config = {"gas_usd_estimate": 0.05}
        
        result = _compute_execution_pnl(signals, config)
        
        expected_net = 10.5 + 5.2  # 15.7, excludes the negative one
        self.assertAlmostEqual(float(result["net_pnl_usdc"]), expected_net, places=6)

    def test_filter_excluded_true(self):
        """filter_excluded=True excludes signals with is_excluded_spread=True."""
        from strategy.artifacts import _compute_execution_pnl
        
        signals = [
            {"net_pnl_usdc_est": 10.5, "gross_pnl_usdc_est": 12.0, "is_net_positive_est": True, "is_excluded_spread": False},
            {"net_pnl_usdc_est": 100.0, "gross_pnl_usdc_est": 150.0, "is_net_positive_est": True, "is_excluded_spread": True},  # Excluded!
        ]
        config = {"gas_usd_estimate": 0.05}
        
        result_all = _compute_execution_pnl(signals, config, filter_excluded=False)
        result_included = _compute_execution_pnl(signals, config, filter_excluded=True)
        
        # Without filter: includes excluded signal
        self.assertEqual(float(result_all["gross_pnl_usdc"]), 12.0 + 150.0)
        
        # With filter: excludes the excluded signal
        self.assertEqual(float(result_included["gross_pnl_usdc"]), 12.0)

    def test_would_execute_pnl_zero_when_no_positive(self):
        """would_execute_pnl_usdc = 0 when no signals are net positive."""
        from strategy.artifacts import _compute_execution_pnl
        
        signals = [
            {"net_pnl_usdc_est": -2.0, "gross_pnl_usdc_est": 3.0, "is_net_positive_est": False},
            {"net_pnl_usdc_est": -5.0, "gross_pnl_usdc_est": 2.0, "is_net_positive_est": False},
        ]
        config = {"gas_usd_estimate": 0.05}
        
        result = _compute_execution_pnl(signals, config)
        
        self.assertEqual(result["would_execute_pnl_usdc"], "0.000000")

    def test_golden_fixture_values(self):
        """Golden fixture: specific input should produce specific output.
        
        This is a regression lock - if this test fails, the cost model changed.
        """
        from strategy.artifacts import _compute_execution_pnl
        
        # Exact golden inputs
        signals = [
            {"net_pnl_usdc_est": 15.123456, "gross_pnl_usdc_est": 18.765432, "is_net_positive_est": True, "is_excluded_spread": False},
            {"net_pnl_usdc_est": 7.654321, "gross_pnl_usdc_est": 9.876543, "is_net_positive_est": True, "is_excluded_spread": False},
        ]
        config = {"gas_usd_estimate": 0.03, "paper_slippage_bps": 5}
        
        result = _compute_execution_pnl(signals, config)
        
        # Golden expected outputs (locked values)
        self.assertEqual(result["gross_pnl_usdc"], "28.641975")
        self.assertEqual(result["signal_pnl_usdc"], "28.641975")
        self.assertEqual(result["net_pnl_usdc"], "22.777777")  # 15.123456 + 7.654321
        self.assertEqual(result["would_execute_pnl_usdc"], "22.777777")
        self.assertTrue(result["cost_model_available"])
        self.assertEqual(result["cost_model_version"], "paper_gas_slippage_v1")
        self.assertEqual(result["cost_model_components"]["gas_usd"], 0.03)
        self.assertEqual(result["cost_model_components"]["slippage_bps"], 5)


class TestBuildTruthDataExecutionPnL(unittest.TestCase):
    """Test execution_pnl integration in build_truth_data."""

    def _make_valid_stats(self) -> dict:
        """Create a valid stats dict with all required fields."""
        return {
            "pairs_active": 3,
            "pairs_total": 5,
            "quotes_total": 10,
            "quotes_fetched": 8,
            "dexes_active": 2,
            "price_sanity_passed": 8,
            "price_sanity_failed": 0,
            "gates_passed": 5,
            "price_stability_factor": 1.0,
            "rpc_errors": 0,
            "rpc_success_rate": 1.0,
            "suspect_quotes": 0,
            "suspect_reasons": {},
            "opportunity_engine": {},
            "roundtrip": {"enabled": False, "evaluated_count": 0, "profitable_count": 0},
        }

    def test_truth_data_includes_execution_pnl(self):
        """build_truth_data should include execution_pnl section."""
        from strategy.artifacts import build_truth_data
        
        config = {"gas_usd_estimate": 0.05}
        stats = self._make_valid_stats()
        spread_signals = [
            {"net_pnl_usdc_est": 10.5, "gross_pnl_usdc_est": 12.0, "is_net_positive_est": True, "is_excluded_spread": False},
        ]
        infra_payload = {}
        
        result = build_truth_data(
            config=config,
            stats=stats,
            current_block=123456,
            spread_signals=spread_signals,
            suspect_examples=[],
            infra_payload=infra_payload,
            raw_bps=5,
            spread_threshold_bps=5,
        )
        
        self.assertIn("execution_pnl", result)
        self.assertIn("execution_pnl_included", result)
        self.assertTrue(result["execution_pnl"]["cost_model_available"])

    def test_truth_data_execution_pnl_included_excludes_suspect(self):
        """execution_pnl_included should exclude is_excluded_spread=True signals."""
        from strategy.artifacts import build_truth_data
        
        config = {"gas_usd_estimate": 0.05}
        stats = self._make_valid_stats()
        spread_signals = [
            {"net_pnl_usdc_est": 10.0, "gross_pnl_usdc_est": 12.0, "is_net_positive_est": True, "is_excluded_spread": False},
            {"net_pnl_usdc_est": 1000.0, "gross_pnl_usdc_est": 1500.0, "is_net_positive_est": True, "is_excluded_spread": True},  # Excluded
        ]
        infra_payload = {}
        
        result = build_truth_data(
            config=config,
            stats=stats,
            current_block=123456,
            spread_signals=spread_signals,
            suspect_examples=[],
            infra_payload=infra_payload,
            raw_bps=5,
            spread_threshold_bps=5,
        )
        
        # execution_pnl includes all (gross_pnl = 12 + 1500 = 1512)
        self.assertEqual(float(result["execution_pnl"]["gross_pnl_usdc"]), 1512.0)
        
        # execution_pnl_included excludes the excluded one (gross_pnl = 12)
        self.assertEqual(float(result["execution_pnl_included"]["gross_pnl_usdc"]), 12.0)


if __name__ == "__main__":
    unittest.main()
