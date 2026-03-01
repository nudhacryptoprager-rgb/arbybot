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
        """_compute_execution_pnl uses gross_pnl_usdc_est (not spread_usdc)."""
        from strategy.artifacts import _compute_execution_pnl
        
        spread_signals = [
            {"gross_pnl_usdc_est": 1.5, "net_pnl_usdc_est": 1.2, "is_net_positive_est": True},
            {"gross_pnl_usdc_est": 0.8, "net_pnl_usdc_est": 0.5, "is_net_positive_est": True},
        ]
        config = {"gas_usd_estimate": 0.1}
        
        result = _compute_execution_pnl(spread_signals, config)
        
        # Total gross should be 1.5 + 0.8 = 2.3
        self.assertEqual(float(result["gross_pnl_usdc"]), 2.3)
        # Total net should be 1.2 + 0.5 = 1.7
        self.assertEqual(float(result["would_execute_pnl_usdc"]), 1.7)

    def test_cost_model_available_true_with_gas_estimate(self):
        """cost_model_available=True when gas_usd_estimate > 0 and signals exist."""
        from strategy.artifacts import _compute_execution_pnl
        
        spread_signals = [
            {"gross_pnl_usdc_est": 1.0, "net_pnl_usdc_est": 0.8, "is_net_positive_est": True},
        ]
        config = {"gas_usd_estimate": 0.15}
        
        result = _compute_execution_pnl(spread_signals, config)
        
        self.assertTrue(result["cost_model_available"])
        self.assertEqual(result["cost_model_version"], "paper_gas_slippage_v1")

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
    """v2.3.2: execution_pnl_included filters excluded signals."""

    def test_filter_excluded_true_excludes_suspect_spreads(self):
        """filter_excluded=True must exclude is_excluded_spread=True signals."""
        from strategy.artifacts import _compute_execution_pnl
        
        spread_signals = [
            {"gross_pnl_usdc_est": 100.0, "net_pnl_usdc_est": 90.0, "is_net_positive_est": True, "is_excluded_spread": False},
            {"gross_pnl_usdc_est": 500.0, "net_pnl_usdc_est": 400.0, "is_net_positive_est": True, "is_excluded_spread": True},  # Excluded
            {"gross_pnl_usdc_est": 50.0, "net_pnl_usdc_est": 40.0, "is_net_positive_est": True, "is_excluded_spread": False},
        ]
        config = {"gas_usd_estimate": 0.1}
        
        # Without filter - should include all
        result_all = _compute_execution_pnl(spread_signals, config, filter_excluded=False)
        self.assertEqual(float(result_all["gross_pnl_usdc"]), 650.0)  # 100 + 500 + 50
        self.assertEqual(float(result_all["would_execute_pnl_usdc"]), 530.0)  # 90 + 400 + 40
        
        # With filter - should exclude the 500/400 signal
        result_included = _compute_execution_pnl(spread_signals, config, filter_excluded=True)
        self.assertEqual(float(result_included["gross_pnl_usdc"]), 150.0)  # 100 + 50
        self.assertEqual(float(result_included["would_execute_pnl_usdc"]), 130.0)  # 90 + 40

    def test_filter_excluded_matches_run_summary_semantics(self):
        """execution_pnl_included should match run_summary.total_net_usdc semantics."""
        from strategy.artifacts import _compute_execution_pnl
        
        # Simulate a real scenario: some signals excluded
        spread_signals = [
            {"gross_pnl_usdc_est": 10.0, "net_pnl_usdc_est": 8.0, "is_net_positive_est": True, "is_excluded_spread": False},
            {"gross_pnl_usdc_est": 800.0, "net_pnl_usdc_est": 750.0, "is_net_positive_est": True, "is_excluded_spread": True},  # SUSPECT_SPREAD
        ]
        config = {"gas_usd_estimate": 0.1}
        
        # Included-only should return the non-excluded sum
        result = _compute_execution_pnl(spread_signals, config, filter_excluded=True)
        
        # This should match what run_summary.metrics.total_net_usdc would compute
        expected_net = 8.0  # Only the included signal
        self.assertEqual(float(result["would_execute_pnl_usdc"]), expected_net)

    def test_filter_excluded_handles_missing_flag_as_included(self):
        """Signals without is_excluded_spread flag should be treated as included."""
        from strategy.artifacts import _compute_execution_pnl
        
        spread_signals = [
            {"gross_pnl_usdc_est": 10.0, "net_pnl_usdc_est": 8.0, "is_net_positive_est": True},  # No flag
            {"gross_pnl_usdc_est": 20.0, "net_pnl_usdc_est": 15.0, "is_net_positive_est": True, "is_excluded_spread": False},
        ]
        config = {"gas_usd_estimate": 0.1}
        
        result = _compute_execution_pnl(spread_signals, config, filter_excluded=True)
        
        # Both should be included (missing flag defaults to False)
        self.assertEqual(float(result["gross_pnl_usdc"]), 30.0)
        self.assertEqual(float(result["would_execute_pnl_usdc"]), 23.0)


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


if __name__ == "__main__":
    unittest.main()
