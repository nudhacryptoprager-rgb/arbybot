# PATH: tests/unit/test_truth_report.py
"""
Unit tests for truth_report.

Tests for:
- STEP 1: Price sanity gate
- STEP 3-4: PnL split (signal vs would_execute)
- STEP 5: Dynamic confidence
"""

import unittest
from decimal import Decimal


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

        histogram = {
            "QUOTE_REVERT": 2,
            "INFRA_RPC_ERROR": 1,
            "PRICE_SANITY_FAIL": 3,
        }

        breakdown = build_gate_breakdown(histogram)

        self.assertEqual(breakdown["revert"], 2)
        self.assertEqual(breakdown["infra"], 1)
        self.assertEqual(breakdown["sanity"], 3)


class TestPnLSplit(unittest.TestCase):
    """STEP 3-4: PnL split tests."""

    def test_truth_report_has_both_pnl_types(self):
        """Truth report should have signal_pnl and would_execute_pnl."""
        from monitoring.truth_report import build_truth_report

        all_spreads = [
            {
                "spread_id": "test_001",
                "dex_buy": "uniswap_v3",
                "dex_sell": "sushiswap_v3",
                "pool_buy": "0x123",
                "pool_sell": "0x456",
                "token_in": "WETH",
                "token_out": "USDC",
                "signal_pnl_usdc": "5.000000",
                "signal_pnl_bps": "14.28",
                "would_execute_pnl_usdc": "4.500000",
                "would_execute_pnl_bps": "12.85",
                "amount_in_numeraire": "1.0",
                "confidence": 0.82,
                "confidence_factors": {"rpc_health": 1.0},
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
        )

        # Check PnL section
        pnl = report.pnl
        self.assertIn("signal_pnl_usdc", pnl)
        self.assertIn("would_execute_pnl_usdc", pnl)
        self.assertEqual(pnl["signal_pnl_usdc"], "5.000000")

        # Check top opportunities
        opp = report.top_opportunities[0]
        self.assertIn("signal_pnl_usdc", opp)
        self.assertIn("would_execute_pnl_usdc", opp)

    def test_pnl_aggregation_across_spreads(self):
        """Total PnL should be sum of all spreads."""
        from monitoring.truth_report import build_truth_report

        all_spreads = [
            {
                "spread_id": "test_001",
                "signal_pnl_usdc": "5.000000",
                "would_execute_pnl_usdc": "4.500000",
                "is_profitable": True,
                "execution_blockers": ["EXECUTION_DISABLED_M4"],
            },
            {
                "spread_id": "test_002",
                "signal_pnl_usdc": "3.000000",
                "would_execute_pnl_usdc": "2.500000",
                "is_profitable": True,
                "execution_blockers": ["EXECUTION_DISABLED_M4"],
            },
        ]

        report = build_truth_report(
            scan_stats={"execution_ready_count": 0},
            reject_histogram={},
            opportunities=[],
            all_spreads=all_spreads,
            run_mode="REGISTRY_REAL",
        )

        # Total should be 5 + 3 = 8
        pnl = report.pnl
        self.assertEqual(pnl["signal_pnl_usdc"], "8.000000")


class TestConfidenceFactors(unittest.TestCase):
    """STEP 5: Dynamic confidence scoring tests."""

    def test_confidence_factors_preserved(self):
        """Confidence factors should be preserved in truth_report."""
        from monitoring.truth_report import build_truth_report

        all_spreads = [
            {
                "spread_id": "test_001",
                "signal_pnl_usdc": "5.000000",
                "confidence": 0.82,
                "confidence_factors": {
                    "rpc_health": 1.0,
                    "quote_coverage": 0.9,
                    "price_stability": 0.85,
                    "spread_quality": 0.75,
                    "dex_diversity": 1.0,
                },
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
        )

        opp = report.top_opportunities[0]
        self.assertEqual(opp["confidence"], 0.82)
        self.assertIn("confidence_factors", opp)
        self.assertEqual(opp["confidence_factors"]["rpc_health"], 1.0)


class TestRPCHealthMetrics(unittest.TestCase):
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
    """Test schema version is bumped for PnL split."""

    def test_schema_version_is_3_1_0(self):
        from monitoring.truth_report import SCHEMA_VERSION

        self.assertEqual(SCHEMA_VERSION, "3.1.0")


if __name__ == "__main__":
    unittest.main()
