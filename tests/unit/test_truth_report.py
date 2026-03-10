# PATH: tests/unit/test_truth_report.py
"""
Unit tests for truth_report.

Tests for:
- STEP 3: Confidence factors consistency (price_stability sync)
- STEP 4: PnL contract (net_pnl_usdc=None when no cost model)
- STEP 5: Schema version frozen
- STEP 6: Truthful profit breakdown
- STEP 9: Execution semantics
"""

import unittest
from decimal import Decimal


class TestImportContract(unittest.TestCase):
    """STEP 4: Import contract tests."""

    def test_import_from_truth_report(self):
        """Can import calculate_confidence from monitoring.truth_report."""
        from monitoring.truth_report import calculate_confidence
        self.assertTrue(callable(calculate_confidence))

    def test_import_from_monitoring_package(self):
        """Can import calculate_confidence from monitoring package."""
        from monitoring import calculate_confidence
        self.assertTrue(callable(calculate_confidence))

    def test_import_rpc_health_metrics(self):
        """Can import RPCHealthMetrics."""
        from monitoring.truth_report import RPCHealthMetrics
        metrics = RPCHealthMetrics()
        self.assertEqual(metrics.rpc_success_count, 0)

    def test_import_truth_report_class(self):
        """Can import TruthReport class."""
        from monitoring.truth_report import TruthReport
        report = TruthReport()
        self.assertIsNotNone(report.timestamp)


class TestPriceStabilityFactor(unittest.TestCase):
    """STEP 5: Price stability factor consistency tests."""

    def test_stability_factor_not_zero_when_sanity_passed(self):
        """price_stability_factor cannot be 0 if price_sanity_passed > 0."""
        from monitoring.truth_report import calculate_price_stability_factor

        factor = calculate_price_stability_factor(
            price_sanity_passed=3,
            quotes_fetched=4,
            price_sanity_failed=1,
        )
        self.assertGreater(factor, 0.0)
        self.assertAlmostEqual(factor, 0.75, places=2)

    def test_stability_factor_zero_when_all_failed(self):
        """price_stability_factor should be 0 if all sanity checks failed."""
        from monitoring.truth_report import calculate_price_stability_factor

        factor = calculate_price_stability_factor(
            price_sanity_passed=0,
            quotes_fetched=4,
            price_sanity_failed=4,
        )
        self.assertEqual(factor, 0.0)

    def test_stability_factor_neutral_when_no_quotes(self):
        """price_stability_factor should be 0.5 (neutral) if no quotes."""
        from monitoring.truth_report import calculate_price_stability_factor

        factor = calculate_price_stability_factor(
            price_sanity_passed=0,
            quotes_fetched=0,
            price_sanity_failed=0,
        )
        self.assertEqual(factor, 0.5)

    def test_stability_factor_perfect_when_all_passed(self):
        """price_stability_factor should be 1.0 if all passed."""
        from monitoring.truth_report import calculate_price_stability_factor

        factor = calculate_price_stability_factor(
            price_sanity_passed=4,
            quotes_fetched=4,
            price_sanity_failed=0,
        )
        self.assertEqual(factor, 1.0)

    def test_health_section_includes_stability_factor(self):
        """build_health_section should include price_stability_factor."""
        from monitoring.truth_report import build_health_section

        scan_stats = {
            "quotes_fetched": 4,
            "quotes_total": 8,
            "gates_passed": 4,
            "price_sanity_passed": 3,
            "price_sanity_failed": 1,
        }

        health = build_health_section(
            scan_stats=scan_stats,
            reject_histogram={},
        )

        self.assertIn("price_stability_factor", health)
        self.assertGreater(health["price_stability_factor"], 0.0)


class TestConfidenceFactorsConsistency(unittest.TestCase):
    """STEP 3: Confidence factors sync with health.price_stability_factor."""

    def test_confidence_factors_synced_with_health(self):
        """confidence_factors.price_stability must equal health.price_stability_factor."""
        from monitoring.truth_report import build_truth_report

        all_spreads = [
            {
                "spread_id": "test_001",
                "gross_pnl_usdc": "5.000000",
                "is_profitable": True,
                "confidence": 0.8,
                "confidence_factors": {
                    "rpc_health": 1.0,
                    "quote_coverage": 1.0,
                    "price_stability": 0.0,  # Will be overwritten
                },
            }
        ]

        scan_stats = {
            "execution_ready_count": 0,
            "quotes_fetched": 4,
            "quotes_total": 4,
            "gates_passed": 3,
            "price_sanity_passed": 3,
            "price_sanity_failed": 1,
        }

        report = build_truth_report(
            scan_stats=scan_stats,
            reject_histogram={},
            opportunities=[],
            all_spreads=all_spreads,
            run_mode="REGISTRY_REAL",
            cost_model_available=False,
        )

        # health.price_stability_factor = 3 / (3+1) = 0.75
        health_psf = report.health["price_stability_factor"]
        self.assertAlmostEqual(health_psf, 0.75, places=2)

        # top_opportunities[0].confidence_factors.price_stability should match
        opp = report.top_opportunities[0]
        opp_psf = opp["confidence_factors"]["price_stability"]
        self.assertEqual(opp_psf, health_psf)


class TestTruthReportConsistency(unittest.TestCase):
    """Test truth_report consistency with scan_stats."""

    def test_build_health_uses_scan_stats(self):
        from monitoring.truth_report import build_health_section, RPCHealthMetrics

        scan_stats = {
            "quotes_fetched": 4,
            "quotes_total": 8,
            "gates_passed": 4,
            "chains_active": 1,
            "dexes_active": 2,
            "price_sanity_passed": 4,
            "price_sanity_failed": 0,
        }

        health = build_health_section(
            scan_stats=scan_stats,
            reject_histogram={},
            rpc_metrics=RPCHealthMetrics(),
        )

        self.assertEqual(health["quote_fetch_rate"], 0.5)
        self.assertEqual(health["quote_gate_pass_rate"], 1.0)
        self.assertEqual(health["price_sanity_passed"], 4)

    def test_gate_breakdown_includes_sanity(self):
        """Gate breakdown should include sanity category."""
        from monitoring.truth_report import build_gate_breakdown

        histogram = {
            "QUOTE_REVERT": 2,
            "INFRA_RPC_ERROR": 1,
            "PRICE_SANITY_FAILED": 3,
        }

        breakdown = build_gate_breakdown(histogram)

        self.assertEqual(breakdown["revert"], 2)
        self.assertEqual(breakdown["infra"], 1)
        self.assertEqual(breakdown["sanity"], 3)

    def test_gate_breakdown_legacy_price_sanity_fail(self):
        """Gate breakdown should handle legacy PRICE_SANITY_FAIL."""
        from monitoring.truth_report import build_gate_breakdown

        histogram = {
            "PRICE_SANITY_FAIL": 2,
        }

        breakdown = build_gate_breakdown(histogram)
        self.assertEqual(breakdown["sanity"], 2)


class TestProfitBreakdown(unittest.TestCase):
    """STEP 6: Truthful profit breakdown tests."""

    def test_truth_report_has_gross_pnl(self):
        """Truth report should have gross_pnl_usdc."""
        from monitoring.truth_report import build_truth_report

        all_spreads = [
            {
                "spread_id": "test_001",
                "gross_pnl_usdc": "5.000000",
                "is_profitable": True,
                "execution_blockers": ["EXECUTION_DISABLED_M4"],
            }
        ]

        report = build_truth_report(
            scan_stats={"execution_ready_count": 0, "spread_ids_profitable": 1},
            reject_histogram={},
            opportunities=[],
            all_spreads=all_spreads,
            run_mode="REGISTRY_REAL",
            cost_model_available=False,
        )

        pnl = report.pnl
        self.assertIn("gross_pnl_usdc", pnl)
        self.assertEqual(pnl["gross_pnl_usdc"], "5.000000")

    def test_net_pnl_none_without_cost_model(self):
        """net_pnl should be None if cost_model_available=False."""
        from monitoring.truth_report import build_truth_report

        all_spreads = [
            {
                "spread_id": "test_001",
                "gross_pnl_usdc": "5.000000",
                "is_profitable": True,
                "execution_blockers": ["EXECUTION_DISABLED_M4"],
            }
        ]

        report = build_truth_report(
            scan_stats={"execution_ready_count": 0},
            reject_histogram={},
            opportunities=[],
            all_spreads=all_spreads,
            run_mode="REGISTRY_REAL",
            cost_model_available=False,
        )

        self.assertFalse(report.cost_model_available)
        self.assertIsNone(report.pnl.get("net_pnl_usdc"))

    def test_net_pnl_none_in_top_opportunities_without_cost_model(self):
        """STEP 4: net_pnl_usdc in top_opportunities should be None when no cost model."""
        from monitoring.truth_report import build_truth_report

        all_spreads = [
            {
                "spread_id": "test_001",
                "gross_pnl_usdc": "5.000000",
                "is_profitable": True,
            }
        ]

        report = build_truth_report(
            scan_stats={"execution_ready_count": 0},
            reject_histogram={},
            opportunities=[],
            all_spreads=all_spreads,
            run_mode="REGISTRY_REAL",
            cost_model_available=False,
        )

        opp = report.top_opportunities[0]
        self.assertIsNone(opp.get("net_pnl_usdc"))

    def test_net_pnl_present_with_cost_model(self):
        """net_pnl should be calculated if cost_model_available=True."""
        from monitoring.truth_report import build_truth_report

        all_spreads = [
            {
                "spread_id": "test_001",
                "gross_pnl_usdc": "5.000000",
                "gas_estimate_usdc": "0.500000",
                "slippage_estimate_usdc": "0.100000",
                "net_pnl_usdc": "4.400000",
                "is_profitable": True,
                "execution_blockers": [],
            }
        ]

        report = build_truth_report(
            scan_stats={"execution_ready_count": 0},
            reject_histogram={},
            opportunities=[],
            all_spreads=all_spreads,
            run_mode="REGISTRY_REAL",
            cost_model_available=True,
        )

        self.assertTrue(report.cost_model_available)
        self.assertIn("gross_pnl_usdc", report.pnl)
        self.assertIsNotNone(report.pnl.get("net_pnl_usdc"))

    def test_no_cost_model_blocker_added(self):
        """NO_COST_MODEL blocker should be added when cost model unavailable."""
        from monitoring.truth_report import build_truth_report

        all_spreads = [
            {
                "spread_id": "test_001",
                "gross_pnl_usdc": "5.000000",
                "is_profitable": True,
            }
        ]

        report = build_truth_report(
            scan_stats={"execution_ready_count": 0},
            reject_histogram={},
            opportunities=[],
            all_spreads=all_spreads,
            run_mode="REGISTRY_REAL",
            cost_model_available=False,
        )

        opp = report.top_opportunities[0]
        self.assertIn("NO_COST_MODEL", opp["execution_blockers"])


class TestExecutionSemantics(unittest.TestCase):
    """STEP 9: Execution semantics tests."""

    def test_execution_enabled_field_present(self):
        """TruthReport should have execution_enabled field."""
        from monitoring.truth_report import build_truth_report

        report = build_truth_report(
            scan_stats={"execution_ready_count": 0},
            reject_histogram={},
            opportunities=[],
            run_mode="REGISTRY_REAL",
        )

        self.assertIn("execution_enabled", report.to_dict())
        self.assertEqual(report.execution_enabled, False)

    def test_execution_blocker_field_present(self):
        """TruthReport should have execution_blocker when disabled."""
        from monitoring.truth_report import build_truth_report

        report = build_truth_report(
            scan_stats={"execution_ready_count": 0},
            reject_histogram={},
            opportunities=[],
            run_mode="REGISTRY_REAL",
        )

        self.assertEqual(report.execution_blocker, "EXECUTION_DISABLED_M4")

    def test_is_actionable_false_when_disabled(self):
        """is_actionable should be False when execution disabled."""
        from monitoring.truth_report import build_truth_report

        all_spreads = [
            {
                "spread_id": "test_001",
                "gross_pnl_usdc": "5.000000",
                "is_profitable": True,
                "is_execution_ready": True,
            }
        ]

        report = build_truth_report(
            scan_stats={"execution_ready_count": 0},
            reject_histogram={},
            opportunities=[],
            all_spreads=all_spreads,
            run_mode="REGISTRY_REAL",
        )

        opp = report.top_opportunities[0]
        self.assertFalse(opp["is_actionable"])


class TestRPCHealthMetrics(unittest.TestCase):
    """Test RPCHealthMetrics."""

    def test_record_rpc_call_success(self):
        from monitoring.truth_report import RPCHealthMetrics

        metrics = RPCHealthMetrics()
        metrics.record_rpc_call(success=True, latency_ms=100)

        self.assertEqual(metrics.rpc_success_count, 1)
        self.assertEqual(metrics.rpc_failed_count, 0)
        self.assertEqual(metrics.total_latency_ms, 100)

    def test_record_rpc_call_failure(self):
        from monitoring.truth_report import RPCHealthMetrics

        metrics = RPCHealthMetrics()
        metrics.record_rpc_call(success=False, latency_ms=0)

        self.assertEqual(metrics.rpc_success_count, 0)
        self.assertEqual(metrics.rpc_failed_count, 1)


class TestSchemaVersion(unittest.TestCase):
    """Test schema version is frozen."""

    def test_schema_version_is_3_2_0(self):
        from monitoring.truth_report import SCHEMA_VERSION
        self.assertEqual(SCHEMA_VERSION, "3.2.0")


class TestProfitIsDiagnosticSemantics(unittest.TestCase):
    """v2.3.2: profit_is_diagnostic semantics tests."""

    def _make_minimal_stats(self, roundtrip_profitable_count=0, roundtrip_evaluated_count=0):
        """Create minimal stats dict for build_truth_data."""
        return {
            "roundtrip": {
                "profitable_count": roundtrip_profitable_count,
                "evaluated_count": roundtrip_evaluated_count,
            },
            "quotes_fetched": 10,
            "quotes_total": 10,
            "dexes_active": ["uniswap_v3"],
            "price_sanity_passed": 10,
            "price_sanity_failed": 0,
            "gates_passed": 10,
            "price_stability_factor": 1.0,
            "rpc_errors": 0,
            "rpc_success_rate": 1.0,
        }

    def test_profit_is_diagnostic_false_when_roundtrip_profitable(self):
        """profit_is_diagnostic=False when roundtrip.profitable_count > 0, even with truth_mode_m42=True."""
        from strategy.artifacts import build_truth_data
        
        config = {"truth_mode_m42": True}
        stats = self._make_minimal_stats(roundtrip_profitable_count=2, roundtrip_evaluated_count=5)
        
        truth_data = build_truth_data(
            config=config,
            stats=stats,
            current_block=12345,
            spread_signals=[],
            suspect_examples=[],
            infra_payload={},
            raw_bps=100,
            spread_threshold_bps=50,
        )
        
        # v2.3.2 FIX: roundtrip.profitable_count > 0 makes profit CANONICAL
        self.assertFalse(truth_data["profit_is_diagnostic"])
        self.assertEqual(truth_data["profit_truth_source"], "ROUNDTRIP_CANONICAL")

    def test_profit_is_diagnostic_true_when_no_roundtrip_profit(self):
        """profit_is_diagnostic=True when roundtrip.profitable_count == 0."""
        from strategy.artifacts import build_truth_data
        
        config = {"truth_mode_m42": False}
        stats = self._make_minimal_stats(roundtrip_profitable_count=0, roundtrip_evaluated_count=5)
        
        truth_data = build_truth_data(
            config=config,
            stats=stats,
            current_block=12345,
            spread_signals=[],
            suspect_examples=[],
            infra_payload={},
            raw_bps=100,
            spread_threshold_bps=50,
        )
        
        self.assertTrue(truth_data["profit_is_diagnostic"])

    def test_profit_truth_source_roundtrip_canonical(self):
        """profit_truth_source=ROUNDTRIP_CANONICAL when profitable."""
        from strategy.artifacts import build_truth_data
        
        config = {}
        stats = self._make_minimal_stats(roundtrip_profitable_count=1)
        
        truth_data = build_truth_data(
            config=config,
            stats=stats,
            current_block=12345,
            spread_signals=[],
            suspect_examples=[],
            infra_payload={},
            raw_bps=100,
            spread_threshold_bps=50,
        )
        
        self.assertEqual(truth_data["profit_truth_source"], "ROUNDTRIP_CANONICAL")


class TestComputeExecutionPnl(unittest.TestCase):
    """v2.3.2: _compute_execution_pnl tests."""

    def test_uses_gross_pnl_usdc_est_field(self):
        """_compute_execution_pnl uses gross_pnl_usdc_est (not spread_usdc).
        
        v3.2.58: would_execute_pnl_usdc is now computed as gross - total_cost,
        not the sum of net_pnl_usdc_est from signals.
        """
        from strategy.artifacts import _compute_execution_pnl
        
        spread_signals = [
            {"gross_pnl_usdc_est": 1.5, "net_pnl_usdc_est": 1.2, "is_net_positive_est": True},
            {"gross_pnl_usdc_est": 0.8, "net_pnl_usdc_est": 0.5, "is_net_positive_est": True},
        ]
        config = {"gas_usd_estimate": 0.1, "paper_size_usd": 100, "paper_slippage_bps": 0}
        
        result = _compute_execution_pnl(spread_signals, config)
        
        # Total gross should be 1.5 + 0.8 = 2.3
        self.assertEqual(float(result["gross_pnl_usdc"]), 2.3)
        # v3.2.58: net = gross - total_cost = 2.3 - (0.1 * 2) = 2.1
        self.assertEqual(float(result["would_execute_pnl_usdc"]), 2.1)

    def test_cost_model_available_true_with_gas_estimate(self):
        """cost_model_available=True when gas_usd_estimate > 0 and signals exist."""
        from strategy.artifacts import _compute_execution_pnl
        
        spread_signals = [
            {"gross_pnl_usdc_est": 1.0, "net_pnl_usdc_est": 0.8, "is_net_positive_est": True},
        ]
        config = {"gas_usd_estimate": 0.15}
        
        result = _compute_execution_pnl(spread_signals, config)
        
        self.assertTrue(result["cost_model_available"])
        self.assertEqual(result["cost_model_version"], "paper_gas_slippage_l1_v3")

    def test_cost_model_available_false_without_gas_estimate(self):
        """cost_model_available=False when gas_usd_estimate is 0."""
        from strategy.artifacts import _compute_execution_pnl
        
        spread_signals = [
            {"gross_pnl_usdc_est": 1.0, "net_pnl_usdc_est": 0.8, "is_net_positive_est": True},
        ]
        config = {"gas_usd_estimate": 0}
        
        result = _compute_execution_pnl(spread_signals, config)
        
        self.assertFalse(result["cost_model_available"])
        self.assertIsNone(result["cost_model_version"])

    def test_ignores_nonexistent_spread_usdc_field(self):
        """Verifies no reliance on old spread_usdc field."""
        from strategy.artifacts import _compute_execution_pnl
        
        # Signal with spread_usdc (wrong field) but no gross_pnl_usdc_est
        spread_signals = [
            {"spread_usdc": 999.0, "net_pnl_usdc_est": 0.5, "is_net_positive_est": True},
        ]
        config = {"gas_usd_estimate": 0.1}
        
        result = _compute_execution_pnl(spread_signals, config)
        
        # Should NOT use spread_usdc (should be 0, not 999)
        self.assertEqual(float(result["gross_pnl_usdc"]), 0.0)


class TestExecutionPnlIncludedContract(unittest.TestCase):
    """v2.3.2: execution_pnl_included filters excluded signals.
    
    v3.2.58: Updated for position-based cost model where net = gross - total_cost.
    """

    def test_filter_excluded_true_excludes_suspect_spreads(self):
        """filter_excluded=True must exclude is_excluded_spread=True signals.
        
        v3.2.58: would_execute_pnl = gross - (gas * num_signals).
        """
        from strategy.artifacts import _compute_execution_pnl
        
        spread_signals = [
            {"gross_pnl_usdc_est": 100.0, "net_pnl_usdc_est": 90.0, "is_net_positive_est": True, "is_excluded_spread": False},
            {"gross_pnl_usdc_est": 500.0, "net_pnl_usdc_est": 400.0, "is_net_positive_est": True, "is_excluded_spread": True},  # Excluded
            {"gross_pnl_usdc_est": 50.0, "net_pnl_usdc_est": 40.0, "is_net_positive_est": True, "is_excluded_spread": False},
        ]
        config = {"gas_usd_estimate": 0.1, "paper_size_usd": 100, "paper_slippage_bps": 0}
        
        # Without filter - should include all
        result_all = _compute_execution_pnl(spread_signals, config, filter_excluded=False)
        self.assertEqual(float(result_all["gross_pnl_usdc"]), 650.0)  # 100 + 500 + 50
        # v3.2.58: would_execute = 650 - (0.1 * 3) = 649.7
        self.assertAlmostEqual(float(result_all["would_execute_pnl_usdc"]), 649.7, places=2)
        
        # With filter - should exclude the 500/400 signal
        result_included = _compute_execution_pnl(spread_signals, config, filter_excluded=True)
        self.assertEqual(float(result_included["gross_pnl_usdc"]), 150.0)  # 100 + 50
        # v3.2.58: would_execute = 150 - (0.1 * 2) = 149.8
        self.assertAlmostEqual(float(result_included["would_execute_pnl_usdc"]), 149.8, places=2)

    def test_filter_excluded_matches_run_summary_semantics(self):
        """execution_pnl_included should match run_summary.total_net_usdc semantics.
        
        v3.2.58: Net is now computed from gross - cost, not signal estimates.
        """
        from strategy.artifacts import _compute_execution_pnl
        
        # Simulate a real scenario: some signals excluded
        spread_signals = [
            {"gross_pnl_usdc_est": 10.0, "net_pnl_usdc_est": 8.0, "is_net_positive_est": True, "is_excluded_spread": False},
            {"gross_pnl_usdc_est": 800.0, "net_pnl_usdc_est": 750.0, "is_net_positive_est": True, "is_excluded_spread": True},  # SUSPECT_SPREAD
        ]
        config = {"gas_usd_estimate": 0.1, "paper_size_usd": 100, "paper_slippage_bps": 0}
        
        # Included-only should return the non-excluded sum
        result = _compute_execution_pnl(spread_signals, config, filter_excluded=True)
        
        # v3.2.58: net = gross - cost = 10 - 0.1 = 9.9 (1 signal)
        expected_net = 10.0 - 0.1  # 9.9
        self.assertAlmostEqual(float(result["would_execute_pnl_usdc"]), expected_net, places=2)

    def test_filter_excluded_handles_missing_flag_as_included(self):
        """Signals without is_excluded_spread flag should be treated as included.
        
        v3.2.58: Updated for position-based cost model.
        """
        from strategy.artifacts import _compute_execution_pnl
        
        spread_signals = [
            {"gross_pnl_usdc_est": 10.0, "net_pnl_usdc_est": 8.0, "is_net_positive_est": True},  # No flag
            {"gross_pnl_usdc_est": 20.0, "net_pnl_usdc_est": 15.0, "is_net_positive_est": True, "is_excluded_spread": False},
        ]
        config = {"gas_usd_estimate": 0.1, "paper_size_usd": 100, "paper_slippage_bps": 0}
        
        result = _compute_execution_pnl(spread_signals, config, filter_excluded=True)
        
        # Both should be included (missing flag defaults to False)
        self.assertEqual(float(result["gross_pnl_usdc"]), 30.0)
        # v3.2.58: net = 30 - (0.1 * 2) = 29.8
        self.assertAlmostEqual(float(result["would_execute_pnl_usdc"]), 29.8, places=2)


class TestSpreadSignalInvariants(unittest.TestCase):
    """Test spread_signal schema invariants for audit trail.
    
    v2.3.0: Validates that spread signals have required fields for
    DEX selection verification and price direction correctness.
    """

    def test_spread_signal_has_signal_id(self):
        """signal_id must be present for correlation with execution_report."""
        from strategy.spreads import compute_spread_signals
        
        quotes = [
            {"token_in": "WETH", "token_out": "USDC", "price": 2000.0, "price_exact": "2000.0",
             "dex_id": "uniswap_v3", "pool_address": "0x111", "fee": 500, "quote_source": "quoter_v2"},
            {"token_in": "WETH", "token_out": "USDC", "price": 2010.0, "price_exact": "2010.0",
             "dex_id": "sushiswap_v3", "pool_address": "0x222", "fee": 500, "quote_source": "quoter_v2"},
        ]
        config = {"min_spread_bps": 0, "paper_size_usd": 250}
        
        signals = compute_spread_signals(quotes, config, 1000, [])
        
        self.assertGreater(len(signals), 0)
        for sig in signals:
            self.assertIn("signal_id", sig)
            self.assertTrue(sig["signal_id"].startswith("signal_"))

    def test_spread_signal_has_exact_prices(self):
        """buy_price_exact and sell_price_exact must be present for audit."""
        from strategy.spreads import compute_spread_signals
        
        quotes = [
            {"token_in": "WETH", "token_out": "USDC", "price": 2000.0, "price_exact": "2000.123456789",
             "dex_id": "uniswap_v3", "pool_address": "0x111", "fee": 500, "quote_source": "quoter_v2"},
            {"token_in": "WETH", "token_out": "USDC", "price": 2010.0, "price_exact": "2010.987654321",
             "dex_id": "sushiswap_v3", "pool_address": "0x222", "fee": 500, "quote_source": "quoter_v2"},
        ]
        config = {"min_spread_bps": 0, "paper_size_usd": 250}
        
        signals = compute_spread_signals(quotes, config, 1000, [])
        
        self.assertGreater(len(signals), 0)
        for sig in signals:
            self.assertIn("buy_price_exact", sig)
            self.assertIn("sell_price_exact", sig)
            # Exact prices should preserve full precision
            self.assertIn(".", sig["buy_price_exact"])
            self.assertIn(".", sig["sell_price_exact"])

    def test_spread_signal_price_direction_correct(self):
        """buy_price must be less than sell_price for positive spread."""
        from strategy.spreads import compute_spread_signals
        from decimal import Decimal
        
        quotes = [
            {"token_in": "WETH", "token_out": "USDC", "price": 2000.0, "price_exact": "2000.0",
             "dex_id": "uniswap_v3", "pool_address": "0x111", "fee": 500, "quote_source": "quoter_v2"},
            {"token_in": "WETH", "token_out": "USDC", "price": 2010.0, "price_exact": "2010.0",
             "dex_id": "sushiswap_v3", "pool_address": "0x222", "fee": 500, "quote_source": "quoter_v2"},
        ]
        config = {"min_spread_bps": 0, "paper_size_usd": 250}
        
        signals = compute_spread_signals(quotes, config, 1000, [])
        
        self.assertGreater(len(signals), 0)
        for sig in signals:
            buy = Decimal(sig["buy_price_exact"])
            sell = Decimal(sig["sell_price_exact"])
            spread_bps = sig.get("spread_bps_exact", 0)
            # For positive spread, sell > buy
            if spread_bps > 0:
                self.assertGreater(sell, buy, f"sell_price should > buy_price for positive spread: {sig['pair']}")

    def test_spread_signal_has_notional_drift_fields(self):
        """buy_notional_drift_pct and sell_notional_drift_pct must be present when quotes have drift."""
        from strategy.spreads import compute_spread_signals
        
        quotes = [
            {"token_in": "WETH", "token_out": "USDC", "price": 2000.0, "price_exact": "2000.0",
             "dex_id": "uniswap_v3", "pool_address": "0x111", "fee": 500, "quote_source": "quoter_v2",
             "notional_drift_pct": 5.0},
            {"token_in": "WETH", "token_out": "USDC", "price": 2010.0, "price_exact": "2010.0",
             "dex_id": "sushiswap_v3", "pool_address": "0x222", "fee": 500, "quote_source": "quoter_v2",
             "notional_drift_pct": 3.0},
        ]
        config = {"min_spread_bps": 0, "paper_size_usd": 250}
        
        signals = compute_spread_signals(quotes, config, 1000, [])
        
        self.assertGreater(len(signals), 0)
        for sig in signals:
            # When quotes have drift, signals should propagate it
            self.assertIn("buy_notional_drift_pct", sig)
            self.assertIn("sell_notional_drift_pct", sig)


class TestEconomicsFieldsInSpreadSignals(unittest.TestCase):
    """
    v3.0.0: Economics fields must be present in spread_signals.
    
    These fields enable roundtrip profitability analysis and economics-based gating.
    """
    
    def test_spread_signal_has_economics_fields(self):
        """spread_signals must contain min_required_spread_bps, spread_minus_required_bps, is_roundtrip_viable."""
        from strategy.spreads import compute_spread_signals
        
        quotes = [
            {"token_in": "WETH", "token_out": "USDC", "price": 2000.0, "price_exact": "2000.0",
             "dex_id": "uniswap_v3", "pool_address": "0x111", "fee": 500, "quote_source": "quoter_v2"},
            {"token_in": "WETH", "token_out": "USDC", "price": 2020.0, "price_exact": "2020.0",
             "dex_id": "sushiswap_v3", "pool_address": "0x222", "fee": 500, "quote_source": "quoter_v2"},
        ]
        config = {"min_spread_bps": 0, "paper_size_usd": 250, "gas_usd_estimate": 0.10, "paper_slippage_bps": 5}
        
        signals = compute_spread_signals(quotes, config, 1000, [])
        
        self.assertGreater(len(signals), 0, "Should have at least one signal")
        
        for sig in signals:
            # v3.0.0 Contract: economics fields are mandatory
            self.assertIn("min_required_spread_bps", sig, "min_required_spread_bps must be present")
            self.assertIn("spread_minus_required_bps", sig, "spread_minus_required_bps must be present")
            self.assertIn("is_roundtrip_viable", sig, "is_roundtrip_viable must be present")
            
            # Type checks
            self.assertIsInstance(sig["min_required_spread_bps"], (int, float))
            self.assertIsInstance(sig["spread_minus_required_bps"], (int, float))
            self.assertIsInstance(sig["is_roundtrip_viable"], bool)
    
    def test_roundtrip_viable_semantics(self):
        """is_roundtrip_viable must be True when spread_minus_required_bps > 0."""
        from strategy.spreads import compute_spread_signals
        
        # Large spread to ensure profitability
        quotes = [
            {"token_in": "WETH", "token_out": "USDC", "price": 1900.0, "price_exact": "1900.0",
             "dex_id": "uniswap_v3", "pool_address": "0x111", "fee": 500, "quote_source": "quoter_v2"},
            {"token_in": "WETH", "token_out": "USDC", "price": 2000.0, "price_exact": "2000.0",
             "dex_id": "sushiswap_v3", "pool_address": "0x222", "fee": 500, "quote_source": "quoter_v2"},
        ]
        config = {"min_spread_bps": 0, "paper_size_usd": 250, "gas_usd_estimate": 0.10, "paper_slippage_bps": 5}
        
        signals = compute_spread_signals(quotes, config, 1000, [])
        
        for sig in signals:
            # When spread_minus_required > 0, is_roundtrip_viable should be True
            if sig["spread_minus_required_bps"] > 0:
                self.assertTrue(sig["is_roundtrip_viable"], 
                    f"is_roundtrip_viable should be True when spread_minus_required={sig['spread_minus_required_bps']}")
            else:
                self.assertFalse(sig["is_roundtrip_viable"],
                    f"is_roundtrip_viable should be False when spread_minus_required={sig['spread_minus_required_bps']}")


class TestNoDataReasonArtifactContract(unittest.TestCase):
    """v3.2.55: Artifact contract for no_data_reason consistency.
    
    These tests verify that compute_no_data_reason() produces correct values
    to satisfy the artifact contract. The contract states:
    - If total_opportunities > 0 and signals_count == 0, reason must be ALL_OPPORTUNITIES_REJECTED
    - If total_opportunities == 0 and signals_count == 0, reason should be NO_SPREAD_SIGNALS
    """
    
    def test_compute_no_data_reason_opps_exist_returns_all_rejected(self):
        """When opportunities exist but signals_count == 0, compute_no_data_reason returns ALL_OPPORTUNITIES_REJECTED."""
        from core.no_data import compute_no_data_reason
        
        result = compute_no_data_reason(
            quotes_total=49,
            quotes_fetched=49,
            spread_signals_count=0,  # No signals passed
            total_opportunities=66,  # Opportunities were evaluated
        )
        
        self.assertEqual(
            result, "ALL_OPPORTUNITIES_REJECTED",
            "When total_opportunities > 0 and spread_signals_count == 0, "
            "no_data_reason must be ALL_OPPORTUNITIES_REJECTED"
        )
    
    def test_all_opportunities_rejected_valid_when_opps_exist(self):
        """ALL_OPPORTUNITIES_REJECTED is valid when opportunities were found but all rejected."""
        artifact = {
            "opportunity_engine": {
                "summary": {
                    "total_opportunities": 66,
                    "profitable_count": 0,
                }
            },
            "metrics": {
                "signals_count": 0,
                "no_data_reason": "ALL_OPPORTUNITIES_REJECTED",  # CORRECT
            },
        }
        
        total_opps = artifact["opportunity_engine"]["summary"]["total_opportunities"]
        signals_count = artifact["metrics"]["signals_count"]
        no_data_reason = artifact["metrics"]["no_data_reason"]
        
        # This is valid: opportunities exist, none passed, reason is ALL_OPPORTUNITIES_REJECTED
        if total_opps > 0 and signals_count == 0:
            self.assertEqual(no_data_reason, "ALL_OPPORTUNITIES_REJECTED")
    
    def test_no_spread_signals_valid_when_no_opportunities(self):
        """NO_SPREAD_SIGNALS is valid when no opportunities were found at all."""
        artifact = {
            "opportunity_engine": {
                "summary": {
                    "total_opportunities": 0,  # No opportunities evaluated
                }
            },
            "metrics": {
                "signals_count": 0,
                "no_data_reason": "NO_SPREAD_SIGNALS",  # CORRECT - true market absence
            },
        }
        
        total_opps = artifact["opportunity_engine"]["summary"]["total_opportunities"]
        signals_count = artifact["metrics"]["signals_count"]
        no_data_reason = artifact["metrics"]["no_data_reason"]
        
        # This is valid: no opportunities at all means true market absence
        if total_opps == 0 and signals_count == 0:
            self.assertEqual(no_data_reason, "NO_SPREAD_SIGNALS")


class TestSuspectSpreadConfigPropagation(unittest.TestCase):
    """v3.2.64: Test suspect_spread_bps_hard config propagation to artifacts."""

    def test_build_truth_data_includes_suspect_spread_bps_hard(self):
        """build_truth_data должен включать suspect_spread_bps_hard в config_params."""
        from strategy.artifacts import build_truth_data
        
        config = {
            "chain": "zksync",
            "chain_id": 324,
            "suspect_spread_bps_hard": 1000,  # Custom threshold
            "paper_size_usd": 100,
        }
        stats = {
            "quotes_total": 10,
            "quotes_fetched": 8,
            "dexes_active": 2,
            "price_sanity_passed": 7,
            "price_sanity_failed": 1,
            "gates_passed": 7,
        }
        
        truth_data = build_truth_data(
            config=config,
            stats=stats,
            current_block=12345678,
            spread_signals=[],
            suspect_examples=[],
            infra_payload={},
            raw_bps=100,
            spread_threshold_bps=3,
        )
        
        # Перевіряємо, що suspect_spread_bps_hard є в config_params
        self.assertIn("suspect_spread_bps_hard", truth_data["config_params"])
        self.assertEqual(truth_data["config_params"]["suspect_spread_bps_hard"], 1000)

    def test_build_truth_data_suspect_spread_bps_hard_none_when_not_set(self):
        """suspect_spread_bps_hard має бути None, коли не встановлено в config."""
        from strategy.artifacts import build_truth_data
        
        config = {
            "chain": "arbitrum_one",
            "chain_id": 42161,
            # No suspect_spread_bps_hard - uses default
        }
        stats = {
            "quotes_total": 10,
            "quotes_fetched": 8,
            "dexes_active": 2,
            "price_sanity_passed": 7,
            "price_sanity_failed": 1,
            "gates_passed": 7,
        }
        
        truth_data = build_truth_data(
            config=config,
            stats=stats,
            current_block=12345678,
            spread_signals=[],
            suspect_examples=[],
            infra_payload={},
            raw_bps=100,
            spread_threshold_bps=3,
        )
        
        # suspect_spread_bps_hard має бути None (default з policy)
        self.assertIsNone(truth_data["config_params"]["suspect_spread_bps_hard"])

    def test_opportunity_engine_summary_includes_threshold(self):
        """OpportunityEngine summary має включати suspect_spread_bps_hard_threshold."""
        from engine.opportunity_engine import evaluate_quotes, GasConfig
        
        quotes = [
            {
                "token_in": "WETH",
                "token_out": "USDC",
                "dex": "uniswap_v3",
                "amount_in": 1000000000000000000,
                "amount_out": 2500000000,
                "fee_tier": 3000,
                "source": "quoter_v2",
            },
            {
                "token_in": "WETH",
                "token_out": "USDC",
                "dex": "pancakeswap_v3",
                "amount_in": 1000000000000000000,
                "amount_out": 2510000000,
                "fee_tier": 2500,
                "source": "quoter_v2",
            },
        ]
        
        gas_config = GasConfig(eth_usd_price=3000.0)
        
        # Test with custom threshold
        _, summary = evaluate_quotes(
            quotes,
            max_gross_spread_bps=1000,
            gas_config=gas_config,
        )
        
        self.assertIn("suspect_spread_bps_hard_threshold", summary)
        self.assertEqual(summary["suspect_spread_bps_hard_threshold"], 1000)

    def test_opportunity_engine_uses_default_threshold_when_none(self):
        """OpportunityEngine повинен використовувати default з policy, коли threshold=None."""
        from engine.opportunity_engine import evaluate_quotes, GasConfig
        from m4.policy import Thresholds
        
        quotes = []  # Empty for simplicity
        gas_config = GasConfig(eth_usd_price=3000.0)
        
        # Test with None - should use default
        _, summary = evaluate_quotes(
            quotes,
            max_gross_spread_bps=None,
            gas_config=gas_config,
        )
        
        self.assertIn("suspect_spread_bps_hard_threshold", summary)
        self.assertEqual(
            summary["suspect_spread_bps_hard_threshold"],
            float(Thresholds.SUSPECT_SPREAD_BPS_HARD)
        )


class TestBuildRoundtripSummary(unittest.TestCase):
    """Contract tests for _build_roundtrip_summary sweep integration."""

    def test_includes_sweep_when_enabled(self):
        """roundtrip_summary includes dynamic_sweep sub-block when sweep ran."""
        from strategy.artifacts import _build_roundtrip_summary

        stats = {
            "roundtrip": {
                "enabled": True,
                "evaluated_count": 2,
                "profitable_count": 0,
                "real_quote_count": 2,
                "best_net_pnl_bps": -20.98,
                "l1_cost_wei": 9550350000,
                "l1_cost_source": "onchain",
                "gas_price_wei_used": 20000000,
                "best_measured_spread_gap_bps": -3.71,
                "dynamic_sweep": {
                    "enabled": True,
                    "routes_swept": 3,
                    "best_pair": "WBTC/WETH",
                    "best_size_usd": 50,
                    "best_net_pnl_bps": -13.44,
                    "best_frontier_reason": "BEST_NEG",
                    "results": [
                        {"pair": "WBTC/WETH", "sizes_evaluated": 7, "best_size_usd": 50},
                    ],
                },
            }
        }
        summary = _build_roundtrip_summary(stats)
        self.assertIn("dynamic_sweep", summary)
        ds = summary["dynamic_sweep"]
        self.assertTrue(ds["enabled"])
        self.assertEqual(ds["sweep_best_size_usd"], 50)
        self.assertEqual(ds["sweep_best_net_pnl_bps"], -13.44)
        self.assertEqual(ds["frontier_pair"], "WBTC/WETH")
        self.assertEqual(ds["sizes_evaluated"], 7)
        self.assertEqual(ds["sweep_best_frontier_reason"], "BEST_NEG")
        self.assertEqual(ds["routes_swept"], 3)

    def test_omits_sweep_when_not_enabled(self):
        """roundtrip_summary has NO dynamic_sweep key when sweep didn't run."""
        from strategy.artifacts import _build_roundtrip_summary

        stats = {
            "roundtrip": {
                "enabled": True,
                "evaluated_count": 1,
                "profitable_count": 0,
                "real_quote_count": 1,
                "best_net_pnl_bps": -30.0,
                "l1_cost_wei": 0,
                "l1_cost_source": "none",
                "gas_price_wei_used": 0,
                "best_measured_spread_gap_bps": -10.0,
            }
        }
        summary = _build_roundtrip_summary(stats)
        self.assertNotIn("dynamic_sweep", summary)

    def test_baseline_fields_always_present(self):
        """Fixed-baseline fields are always in roundtrip_summary."""
        from strategy.artifacts import _build_roundtrip_summary

        stats = {"roundtrip": {"enabled": True, "evaluated_count": 0}}
        summary = _build_roundtrip_summary(stats)
        for key in [
            "enabled", "evaluated_count", "profitable_count",
            "real_quote_count", "best_net_pnl_bps", "l1_cost_wei",
            "l1_cost_source", "gas_price_wei_used", "best_measured_spread_gap_bps",
        ]:
            self.assertIn(key, summary, f"Missing baseline field: {key}")

    def test_gap_to_zero_bps_in_sweep_block(self):
        """gap_to_zero_bps surfaces in roundtrip_summary.dynamic_sweep."""
        from strategy.artifacts import _build_roundtrip_summary

        stats = {
            "roundtrip": {
                "enabled": True,
                "dynamic_sweep": {
                    "enabled": True,
                    "routes_swept": 1,
                    "best_pair": "A/B",
                    "best_size_usd": 50,
                    "best_net_pnl_bps": -10.0,
                    "best_frontier_reason": "BEST_NEG",
                    "gap_to_zero_bps": 10.0,
                    "results": [{"sizes_evaluated": 3}],
                },
            }
        }
        summary = _build_roundtrip_summary(stats)
        self.assertEqual(summary["dynamic_sweep"]["gap_to_zero_bps"], 10.0)

    def test_measured_economics_in_sweep_block(self):
        """Measured cost decomposition surfaces in roundtrip_summary.dynamic_sweep."""
        from strategy.artifacts import _build_roundtrip_summary

        stats = {
            "roundtrip": {
                "enabled": True,
                "dynamic_sweep": {
                    "enabled": True,
                    "routes_swept": 1,
                    "best_pair": "WBTC/USDC",
                    "best_size_usd": 50,
                    "best_net_pnl_bps": -12.5,
                    "best_frontier_reason": "BEST_NEG",
                    "gap_to_zero_bps": 12.5,
                    "best_gas_bps": 3.2,
                    "best_fee_bps": 60.0,
                    "best_slippage_bps": 1.5,
                    "best_total_cost_bps": 64.7,
                    "results": [{"sizes_evaluated": 7}],
                },
            }
        }
        summary = _build_roundtrip_summary(stats)
        ds = summary["dynamic_sweep"]
        self.assertEqual(ds["measured_gas_bps"], 3.2)
        self.assertEqual(ds["measured_fee_bps"], 60.0)
        self.assertEqual(ds["measured_slippage_bps"], 1.5)
        self.assertEqual(ds["measured_total_cost_bps"], 64.7)

    def test_frontier_curves_in_truth_report(self):
        """Full frontier curves stored in truth_report dynamic_sweep."""
        from strategy.artifacts import _build_roundtrip_summary

        results = [
            {"pair": "A/B", "buy_dex": "d1", "sell_dex": "d2",
             "sizes_evaluated": 3, "points": [
                 {"size_usd": 50, "net_pnl_bps": -10, "fee_bps": 30.0},
                 {"size_usd": 100, "net_pnl_bps": -15, "fee_bps": 30.0},
             ]},
        ]
        stats = {
            "roundtrip": {
                "enabled": True,
                "dynamic_sweep": {
                    "enabled": True,
                    "routes_swept": 1,
                    "best_pair": "A/B",
                    "best_size_usd": 50,
                    "best_net_pnl_bps": -10,
                    "best_frontier_reason": "BEST_NEG",
                    "gap_to_zero_bps": 10.0,
                    "results": results,
                },
            }
        }
        summary = _build_roundtrip_summary(stats)
        self.assertIn("frontier_curves", summary["dynamic_sweep"])
        self.assertEqual(len(summary["dynamic_sweep"]["frontier_curves"]), 1)
        self.assertEqual(summary["dynamic_sweep"]["frontier_curves"][0]["pair"], "A/B")


if __name__ == "__main__":
    unittest.main()
