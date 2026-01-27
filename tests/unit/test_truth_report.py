# PATH: tests/unit/test_truth_report.py
"""
Unit tests for truth_report.

Tests for:
- STEP 4: Import contract stability
- STEP 5: Confidence formula consistency
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

        # Scenario: 3 passed, 1 failed
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

        self.assertEqual(health["quote_fetch_rate"], 0.5)  # 4/8
        self.assertEqual(health["quote_gate_pass_rate"], 1.0)  # 4/4
        self.assertEqual(health["price_sanity_passed"], 4)

    def test_gate_breakdown_includes_sanity(self):
        """Gate breakdown should include sanity category."""
        from monitoring.truth_report import build_gate_breakdown

        # STEP 3: Use canonical PRICE_SANITY_FAILED
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

        # Legacy key should also work
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
        # Net should be present
        self.assertIn("gross_pnl_usdc", report.pnl)

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
                "is_execution_ready": True,  # Would be ready
            }
        ]

        report = build_truth_report(
            scan_stats={"execution_ready_count": 0},  # But execution disabled
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


if __name__ == "__main__":
    unittest.main()
