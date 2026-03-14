# PATH: tests/unit/test_execution_pnl_golden.py
"""
Golden tests for Clean PnL (execution_pnl) computation.

These tests lock the behavior of _compute_execution_pnl in strategy/artifacts.py
to prevent regressions in cost model breakdown.

Test coverage:
1. cost_model_available correctly set based on gas_usd_estimate and signals
2. Breakdown fields (gross_pnl_usdc, net_pnl_usdc) are computed correctly
3. cost_model_components includes gas_usd, slippage, L1 cost, and total_cost
4. Invariant: signal_pnl_usdc == gross_pnl_usdc (same field, different name for migration)
5. filter_excluded behavior (execution_pnl vs execution_pnl_included)
6. v3.2.57: Cost breakdown invariant: total_cost_usd = gas_usd + slippage_usd + l1_cost_usd
"""

import unittest
from decimal import Decimal


class TestExecutionPnLGolden(unittest.TestCase):
    """Golden tests for Clean PnL computation.
    
    v3.2.58: Updated for position-based slippage and per-signal cost aggregation.
    Canonical cost model: gas and slippage are per-signal, net = gross - total_cost.
    """

    def test_cost_model_available_with_gas_and_signals(self):
        """cost_model_available=True when gas_usd_estimate set and signals exist."""
        from strategy.artifacts import _compute_execution_pnl
        
        signals = [
            {"net_pnl_usdc_est": 10.5, "gross_pnl_usdc_est": 12.0, "is_net_positive_est": True},
            {"net_pnl_usdc_est": 5.2, "gross_pnl_usdc_est": 7.0, "is_net_positive_est": True},
        ]
        # v3.2.58: paper_size_usd required for slippage calculation
        config = {"gas_usd_estimate": 0.05, "paper_slippage_bps": 10, "paper_size_usd": 100}
        
        result = _compute_execution_pnl(signals, config)
        
        self.assertTrue(result["cost_model_available"])
        self.assertEqual(result["cost_model_version"], "paper_gas_slippage_l1_v3")
        self.assertIsNotNone(result["cost_model_components"])
        # v3.2.58: gas_usd is per-signal total: 0.05 * 2 = 0.10
        self.assertEqual(result["cost_model_components"]["gas_usd"], 0.10)
        self.assertEqual(result["cost_model_components"]["slippage_bps"], 10)
        # v3.2.58: slippage is position-based: (100 * 10 / 10000) * 2 signals = $0.20
        self.assertAlmostEqual(result["cost_model_components"]["slippage_usd"], 0.20, places=6)
        self.assertEqual(result["cost_model_components"]["num_signals"], 2)

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
        """v3.2.58: net_pnl_usdc = gross - total_cost (canonical formula).
        
        Unlike v3.2.57 which summed signal estimates, v3.2.58 uses:
        net = gross - (gas * num_signals + slippage * num_signals + l1_cost)
        """
        from strategy.artifacts import _compute_execution_pnl
        
        signals = [
            {"net_pnl_usdc_est": 10.5, "gross_pnl_usdc_est": 12.0, "is_net_positive_est": True},
            {"net_pnl_usdc_est": 5.2, "gross_pnl_usdc_est": 7.0, "is_net_positive_est": True},
            {"net_pnl_usdc_est": -2.0, "gross_pnl_usdc_est": 3.0, "is_net_positive_est": False},
        ]
        config = {"gas_usd_estimate": 0.05, "paper_size_usd": 100, "paper_slippage_bps": 0}
        
        result = _compute_execution_pnl(signals, config)
        
        # v3.2.58: gross = 22.0, total_cost = 0.05 * 3 + 0 = 0.15, net = 21.85
        expected_gross = 12.0 + 7.0 + 3.0  # 22.0
        expected_cost = 0.05 * 3  # 0.15 (gas only, no slippage)
        expected_net = expected_gross - expected_cost  # 21.85
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
        """would_execute_pnl_usdc = 0 when net_pnl_usdc <= 0.
        
        v3.2.58: would_execute_pnl is 0 when computed net (gross - cost) is <= 0.
        """
        from strategy.artifacts import _compute_execution_pnl
        
        signals = [
            {"net_pnl_usdc_est": -2.0, "gross_pnl_usdc_est": 3.0, "is_net_positive_est": False},
            {"net_pnl_usdc_est": -5.0, "gross_pnl_usdc_est": 2.0, "is_net_positive_est": False},
        ]
        # High gas cost so net becomes negative: gross=5, cost=10*2=20, net=-15
        config = {"gas_usd_estimate": 10.0, "paper_size_usd": 100, "paper_slippage_bps": 0}
        
        result = _compute_execution_pnl(signals, config)
        
        # gross=5.0, cost=10*2=20, net=5-20=-15 -> would_execute=0
        self.assertEqual(result["would_execute_pnl_usdc"], "0.000000")

    def test_golden_fixture_values(self):
        """Golden fixture: specific input should produce specific output.
        
        This is a regression lock - if this test fails, the cost model changed.
        v3.2.58: Updated for position-based slippage and per-signal cost aggregation.
        
        Canonical formula:
        - gas_usd = gas_usd_estimate * num_signals = 0.03 * 2 = 0.06
        - slippage_usd = (paper_size_usd * bps / 10000) * num_signals = (100 * 5 / 10000) * 2 = 0.10
        - total_cost = gas + slippage + l1 = 0.06 + 0.10 + 0 = 0.16
        - net = gross - total_cost = 28.641975 - 0.16 = 28.481975
        """
        from strategy.artifacts import _compute_execution_pnl
        
        # Exact golden inputs
        signals = [
            {"net_pnl_usdc_est": 15.123456, "gross_pnl_usdc_est": 18.765432, "is_net_positive_est": True, "is_excluded_spread": False},
            {"net_pnl_usdc_est": 7.654321, "gross_pnl_usdc_est": 9.876543, "is_net_positive_est": True, "is_excluded_spread": False},
        ]
        config = {"gas_usd_estimate": 0.03, "paper_slippage_bps": 5, "paper_size_usd": 100}
        
        result = _compute_execution_pnl(signals, config)
        
        # Golden expected outputs (locked values) v3.2.58
        self.assertEqual(result["gross_pnl_usdc"], "28.641975")
        self.assertEqual(result["signal_pnl_usdc"], "28.641975")
        # v3.2.58: net = gross - total_cost = 28.641975 - 0.16 = 28.481975
        self.assertEqual(result["net_pnl_usdc"], "28.481975")
        self.assertEqual(result["would_execute_pnl_usdc"], "28.481975")
        self.assertTrue(result["cost_model_available"])
        self.assertEqual(result["cost_model_version"], "paper_gas_slippage_l1_v3")
        # v3.2.58: gas is per-signal total
        self.assertEqual(result["cost_model_components"]["gas_usd"], 0.06)
        self.assertEqual(result["cost_model_components"]["slippage_bps"], 5)
        # v3.2.58: slippage is position-based per-signal total
        self.assertAlmostEqual(result["cost_model_components"]["slippage_usd"], 0.10, places=6)
        self.assertEqual(result["cost_model_components"]["num_signals"], 2)


class TestCostBreakdownInvariants(unittest.TestCase):
    """v3.2.58: Tests for full cost breakdown invariants with position-based slippage."""

    def test_total_cost_invariant(self):
        """total_cost_usd = gas_usd + slippage_usd + l1_cost_usd."""
        from strategy.artifacts import _compute_execution_pnl
        
        signals = [
            {"net_pnl_usdc_est": 10.0, "gross_pnl_usdc_est": 15.0, "is_net_positive_est": True},
        ]
        config = {
            "gas_usd_estimate": 0.05,
            "paper_size_usd": 100,
            "paper_slippage_bps": 10,  # 0.1% of position
            "l1_data_gas_units": 2000,
            "l1_gas_price_gwei": 30,
            "tokens_usd_price": {"WETH": 3000.0},
        }
        
        result = _compute_execution_pnl(signals, config)
        
        components = result["cost_model_components"]
        # Verify invariant: total = gas + slippage + l1
        expected_total = components["gas_usd"] + components["slippage_usd"] + components["l1_cost_usd"]
        self.assertAlmostEqual(components["total_cost_usd"], expected_total, places=6)
        
    def test_slippage_usd_calculation(self):
        """v3.2.58: slippage_usd = paper_size_usd * slippage_bps / 10000 * num_signals."""
        from strategy.artifacts import _compute_execution_pnl
        
        signals = [
            {"net_pnl_usdc_est": 10.0, "gross_pnl_usdc_est": 100.0, "is_net_positive_est": True},
        ]
        config = {
            "gas_usd_estimate": 0.01,
            "paper_size_usd": 100,  # Position size
            "paper_slippage_bps": 50,  # 0.5%
        }
        
        result = _compute_execution_pnl(signals, config)
        
        components = result["cost_model_components"]
        # v3.2.58: slippage_usd = 100.0 * 50 / 10000 * 1 = 0.5
        self.assertAlmostEqual(components["slippage_usd"], 0.5, places=6)

    def test_l1_cost_usd_calculation(self):
        """l1_cost_usd = (l1_data_gas_units * l1_gas_price_gwei * 1e-9) * eth_price."""
        from strategy.artifacts import _compute_execution_pnl
        
        signals = [
            {"net_pnl_usdc_est": 10.0, "gross_pnl_usdc_est": 15.0, "is_net_positive_est": True},
        ]
        config = {
            "gas_usd_estimate": 0.01,
            "paper_size_usd": 100,
            "l1_data_gas_units": 2000,
            "l1_gas_price_gwei": 30,
            "tokens_usd_price": {"WETH": 3000.0},
        }
        
        result = _compute_execution_pnl(signals, config)
        
        components = result["cost_model_components"]
        # l1_cost_usd = (2000 * 30 * 1e-9) * 3000 = 0.00006 * 3000 = 0.18
        expected_l1_cost = (2000 * 30 * 1e-9) * 3000.0
        self.assertAlmostEqual(components["l1_cost_usd"], expected_l1_cost, places=6)

    def test_zero_l1_cost_when_not_configured(self):
        """l1_cost_usd = 0 when l1_data_gas_units not in config."""
        from strategy.artifacts import _compute_execution_pnl
        
        signals = [
            {"net_pnl_usdc_est": 10.0, "gross_pnl_usdc_est": 15.0, "is_net_positive_est": True},
        ]
        config = {
            "gas_usd_estimate": 0.05,
            # No l1_data_gas_units or l1_gas_price_gwei
        }
        
        result = _compute_execution_pnl(signals, config)
        
        components = result["cost_model_components"]
        self.assertEqual(components["l1_cost_usd"], 0.0)

    def test_explicit_zero_l1_for_zkrollups(self):
        """zk-rollups should have l1_cost_usd = 0 when explicitly configured."""
        from strategy.artifacts import _compute_execution_pnl
        
        signals = [
            {"net_pnl_usdc_est": 10.0, "gross_pnl_usdc_est": 15.0, "is_net_positive_est": True},
        ]
        # zkSync/Scroll config pattern: l1_data_gas_units: 0
        config = {
            "gas_usd_estimate": 0.01,
            "l1_data_gas_units": 0,
            "l1_gas_price_gwei": 0,
        }
        
        result = _compute_execution_pnl(signals, config)
        
        components = result["cost_model_components"]
        self.assertEqual(components["l1_cost_usd"], 0.0)
        self.assertEqual(components["l1_data_gas_units"], 0)
        self.assertEqual(components["l1_gas_price_gwei"], 0)

    def test_full_cost_breakdown_fields_present(self):
        """All cost breakdown fields must be present in cost_model_components."""
        from strategy.artifacts import _compute_execution_pnl
        
        signals = [
            {"net_pnl_usdc_est": 10.0, "gross_pnl_usdc_est": 15.0, "is_net_positive_est": True},
        ]
        config = {"gas_usd_estimate": 0.05, "paper_size_usd": 100}
        
        result = _compute_execution_pnl(signals, config)
        
        # v3.2.58: Added paper_size_usd and num_signals to required fields
        required_fields = [
            "gas_usd",
            "slippage_bps",
            "slippage_usd",
            "l1_data_gas_units",
            "l1_gas_price_gwei",
            "l1_cost_usd",
            "total_cost_usd",
            "eth_price_usd",
            "paper_size_usd",  # v3.2.58
            "num_signals",  # v3.2.58
        ]
        components = result["cost_model_components"]
        for field in required_fields:
            self.assertIn(field, components, f"Missing required field: {field}")


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

    def test_net_pnl_bps_computed_when_cost_model_available(self):
        """net_pnl_bps = (net_pnl_usdc / total_notional) * 10000."""
        from strategy.artifacts import _compute_execution_pnl

        signals = [
            {"net_pnl_usdc_est": 10.0, "gross_pnl_usdc_est": 12.0, "is_net_positive_est": True},
        ]
        config = {"gas_usd_estimate": 0.05, "paper_slippage_bps": 0, "paper_size_usd": 100}

        result = _compute_execution_pnl(signals, config)

        self.assertTrue(result["cost_model_available"])
        # gross = 12.0, cost = 0.05 (gas), net = 11.95
        # total_notional = 100 * 1 = 100
        # net_pnl_bps = (11.95 / 100) * 10000 = 1195.0
        self.assertIsNotNone(result["net_pnl_bps"])
        self.assertAlmostEqual(result["net_pnl_bps"], 1195.0, places=1)

    def test_net_pnl_bps_none_when_cost_model_unavailable(self):
        """net_pnl_bps=None when cost model is not available."""
        from strategy.artifacts import _compute_execution_pnl

        signals = [
            {"net_pnl_usdc_est": 10.0, "gross_pnl_usdc_est": 12.0, "is_net_positive_est": True},
        ]
        config = {}  # No gas_usd_estimate

        result = _compute_execution_pnl(signals, config)

        self.assertFalse(result["cost_model_available"])
        self.assertIsNone(result["net_pnl_bps"])

    def test_net_pnl_bps_none_when_no_signals(self):
        """net_pnl_bps=None when there are no signals (avoids division by zero)."""
        from strategy.artifacts import _compute_execution_pnl

        signals = []
        config = {"gas_usd_estimate": 0.05}

        result = _compute_execution_pnl(signals, config)

        self.assertIsNone(result["net_pnl_bps"])

    def test_net_pnl_bps_with_multiple_signals(self):
        """net_pnl_bps correct with multiple signals and slippage."""
        from strategy.artifacts import _compute_execution_pnl

        signals = [
            {"net_pnl_usdc_est": 5.0, "gross_pnl_usdc_est": 6.0, "is_net_positive_est": True},
            {"net_pnl_usdc_est": 3.0, "gross_pnl_usdc_est": 4.0, "is_net_positive_est": True},
        ]
        config = {"gas_usd_estimate": 0.05, "paper_slippage_bps": 10, "paper_size_usd": 100}

        result = _compute_execution_pnl(signals, config)

        # gross = 6 + 4 = 10, gas = 0.05*2 = 0.10, slippage = (100*10/10000)*2 = 0.20
        # total_cost = 0.10 + 0.20 = 0.30, net = 10 - 0.30 = 9.70
        # total_notional = 100 * 2 = 200
        # net_pnl_bps = (9.70 / 200) * 10000 = 485.0
        self.assertAlmostEqual(result["net_pnl_bps"], 485.0, places=1)


if __name__ == "__main__":
    unittest.main()
