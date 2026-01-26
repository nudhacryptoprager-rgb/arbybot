# PATH: tests/unit/test_truth_report.py
"""
Unit tests for truth_report consistency contract.

STEP 6: Tests that truth_report_health_matches_scan_stats
"""

import unittest
from decimal import Decimal


class TestTruthReportConsistency(unittest.TestCase):
    """Test truth_report consistency with scan_stats."""

    def test_build_health_uses_scan_stats_for_rates(self):
        """STEP 6: health uses scan_stats for quote_fetch_rate and quote_gate_pass_rate."""
        from monitoring.truth_report import build_health_section, RPCHealthMetrics

        # scan_stats with 4/4 quotes
        scan_stats = {
            "quotes_fetched": 4,
            "quotes_total": 4,
            "gates_passed": 4,
            "chains_active": 1,
            "dexes_active": 1,
            "pairs_covered": 2,
            "pools_scanned": 4,
        }

        health = build_health_section(
            scan_stats=scan_stats,
            reject_histogram={},
            rpc_metrics=RPCHealthMetrics(),
        )

        # quote_fetch_rate should be 1.0 (4/4)
        self.assertEqual(health["quote_fetch_rate"], 1.0)
        # quote_gate_pass_rate should be 1.0 (4/4)
        self.assertEqual(health["quote_gate_pass_rate"], 1.0)
        # quotes_fetched and quotes_total should be in health
        self.assertEqual(health["quotes_fetched"], 4)
        self.assertEqual(health["quotes_total"], 4)

    def test_build_health_uses_rpc_stats_for_rpc_rate(self):
        """health uses rpc_stats (from RPCClient) for rpc_success_rate."""
        from monitoring.truth_report import build_health_section, RPCHealthMetrics

        scan_stats = {
            "quotes_fetched": 4,
            "quotes_total": 4,
            "gates_passed": 4,
        }

        rpc_stats = {
            "total_requests": 10,
            "total_success": 8,
            "total_failure": 2,
            "success_rate": 0.8,
        }

        health = build_health_section(
            scan_stats=scan_stats,
            reject_histogram={},
            rpc_metrics=RPCHealthMetrics(),
            rpc_stats=rpc_stats,
        )

        # rpc_success_rate should come from rpc_stats
        self.assertEqual(health["rpc_success_rate"], 0.8)
        self.assertEqual(health["rpc_total_requests"], 10)
        self.assertEqual(health["rpc_failed_requests"], 2)

    def test_blocker_histogram_built_from_spreads(self):
        """STEP 4: health includes blocker_histogram from all_spreads."""
        from monitoring.truth_report import build_health_section

        all_spreads = [
            {"execution_blockers": ["EXECUTION_DISABLED_M4"]},
            {"execution_blockers": ["EXECUTION_DISABLED_M4"]},
            {"execution_blockers": ["EXECUTION_DISABLED_M4", "LOW_CONFIDENCE"]},
        ]

        health = build_health_section(
            scan_stats={"quotes_fetched": 3, "quotes_total": 3, "gates_passed": 3},
            reject_histogram={},
            all_spreads=all_spreads,
        )

        self.assertIn("blocker_histogram", health)
        self.assertEqual(health["blocker_histogram"]["EXECUTION_DISABLED_M4"], 3)
        self.assertEqual(health["blocker_histogram"]["LOW_CONFIDENCE"], 1)


class TestExecutionBlockersContract(unittest.TestCase):
    """Test execution_blockers preservation contract."""

    def test_execution_blockers_preserved_from_spread(self):
        """STEP 3: Existing execution_blockers are preserved, not recomputed."""
        from monitoring.truth_report import build_truth_report

        scan_stats = {
            "quotes_fetched": 1,
            "quotes_total": 1,
            "gates_passed": 1,
            "execution_ready_count": 0,
        }

        all_spreads = [
            {
                "spread_id": "test_001",
                "net_pnl_usdc": "0.50",
                "confidence": 0.9,
                "is_profitable": True,
                "execution_blockers": ["EXECUTION_DISABLED_M4"],
                "is_execution_ready": False,
            }
        ]

        report = build_truth_report(
            scan_stats=scan_stats,
            reject_histogram={},
            opportunities=[],
            all_spreads=all_spreads,
            run_mode="REGISTRY_REAL",
        )

        top_opp = report.top_opportunities[0]
        # Blockers must be preserved from spread
        self.assertEqual(top_opp["execution_blockers"], ["EXECUTION_DISABLED_M4"])
        # Must be False when blockers exist
        self.assertFalse(top_opp["is_execution_ready"])

    def test_no_execution_ready_when_execution_disabled(self):
        """If execution_ready_count == 0, no opp can be is_execution_ready=True."""
        from monitoring.truth_report import build_truth_report

        scan_stats = {
            "quotes_fetched": 1,
            "quotes_total": 1,
            "gates_passed": 1,
            "execution_ready_count": 0,  # Execution disabled
        }

        # Even if spread claims is_execution_ready=True, it should be forced to False
        all_spreads = [
            {
                "spread_id": "test_001",
                "net_pnl_usdc": "0.50",
                "confidence": 0.9,
                "is_profitable": True,
                "execution_blockers": [],  # No blockers
                "is_execution_ready": True,  # Claims ready
            }
        ]

        report = build_truth_report(
            scan_stats=scan_stats,
            reject_histogram={},
            opportunities=[],
            all_spreads=all_spreads,
            run_mode="REGISTRY_REAL",
        )

        top_opp = report.top_opportunities[0]
        # Must be False because execution_ready_count == 0
        self.assertFalse(top_opp["is_execution_ready"])
        # Should have blocker added
        self.assertIn("EXECUTION_DISABLED_M4", top_opp["execution_blockers"])


class TestRPCHealthMetrics(unittest.TestCase):
    """Test RPCHealthMetrics API contract."""

    def test_record_rpc_call_exists(self):
        from monitoring.truth_report import RPCHealthMetrics

        metrics = RPCHealthMetrics()
        self.assertTrue(hasattr(metrics, "record_rpc_call"))

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


if __name__ == "__main__":
    unittest.main()
