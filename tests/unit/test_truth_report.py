# PATH: tests/unit/test_truth_report.py
"""
Unit tests for truth_report module.

Tests TruthReport, RPCHealthMetrics, and health building functions.
Includes regression tests for schema contract stability.
"""

import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from monitoring.truth_report import (
    TruthReport,
    RPCHealthMetrics,
    SCHEMA_VERSION,
    calculate_confidence,
    build_truth_report,
    build_health_section,
    build_gate_breakdown,
    build_scan_stats,
)


class TestRPCHealthMetrics(unittest.TestCase):
    """Tests for RPCHealthMetrics class."""

    def test_initial_state(self):
        """Initial state has zero counts."""
        metrics = RPCHealthMetrics()
        self.assertEqual(metrics.rpc_success_count, 0)
        self.assertEqual(metrics.rpc_failed_count, 0)
        self.assertEqual(metrics.quote_call_attempts, 0)
        self.assertEqual(metrics.rpc_total_requests, 0)
        self.assertEqual(metrics.rpc_success_rate, 0.0)

    def test_record_success(self):
        """Recording success updates counts."""
        metrics = RPCHealthMetrics()
        metrics.record_success(latency_ms=100)
        metrics.record_success(latency_ms=200)

        self.assertEqual(metrics.rpc_success_count, 2)
        self.assertEqual(metrics.quote_call_attempts, 2)
        self.assertEqual(metrics.avg_latency_ms, 150)

    def test_record_failure(self):
        """Recording failure updates counts."""
        metrics = RPCHealthMetrics()
        metrics.record_failure()
        metrics.record_failure()

        self.assertEqual(metrics.rpc_failed_count, 2)
        self.assertEqual(metrics.quote_call_attempts, 2)

    def test_success_rate_calculation(self):
        """Success rate is calculated correctly."""
        metrics = RPCHealthMetrics()
        metrics.record_success()
        metrics.record_success()
        metrics.record_failure()

        self.assertAlmostEqual(metrics.rpc_success_rate, 0.6667, places=3)

    def test_reconcile_with_rejects_adds_missing(self):
        """Reconciliation adds INFRA_RPC_ERROR to failed count."""
        metrics = RPCHealthMetrics()
        metrics.reconcile_with_rejects({"INFRA_RPC_ERROR": 5})

        self.assertEqual(metrics.rpc_failed_count, 5)
        self.assertEqual(metrics.rpc_total_requests, 5)

    def test_reconcile_with_rejects_preserves_higher(self):
        """Reconciliation preserves higher failure count."""
        metrics = RPCHealthMetrics()
        for _ in range(10):
            metrics.record_failure()
        metrics.reconcile_with_rejects({"INFRA_RPC_ERROR": 5})
        self.assertEqual(metrics.rpc_failed_count, 10)

    def test_to_dict(self):
        """to_dict returns proper structure."""
        metrics = RPCHealthMetrics()
        metrics.record_success(100)
        metrics.record_failure()
        d = metrics.to_dict()

        self.assertIn("rpc_success_rate", d)
        self.assertIn("rpc_total_requests", d)
        self.assertIn("rpc_failed_requests", d)
        self.assertIn("quote_call_attempts", d)


class TestBuildHealthSection(unittest.TestCase):
    """Tests for build_health_section function."""

    def test_basic_health_section(self):
        """Builds basic health section."""
        scan_stats = {
            "quote_fetch_rate": 0.9,
            "quote_gate_pass_rate": 0.8,
            "chains_active": 2,
            "dexes_active": 4,
            "pairs_covered": 10,
            "pools_scanned": 50,
        }
        reject_histogram = {"QUOTE_REVERT": 5, "SLIPPAGE_TOO_HIGH": 3}

        health = build_health_section(scan_stats, reject_histogram)

        self.assertAlmostEqual(health["quote_fetch_rate"], 0.9, places=2)
        self.assertEqual(health["chains_active"], 2)
        self.assertEqual(len(health["top_reject_reasons"]), 2)

    def test_rpc_consistency_with_errors(self):
        """Health section reconciles RPC metrics with rejects."""
        scan_stats = {}
        reject_histogram = {"INFRA_RPC_ERROR": 10}
        rpc_metrics = RPCHealthMetrics()

        health = build_health_section(scan_stats, reject_histogram, rpc_metrics)

        self.assertGreater(health["rpc_total_requests"], 0)
        self.assertGreaterEqual(health["rpc_failed_requests"], 10)

    def test_gate_breakdown_included(self):
        """Health section includes gate_breakdown."""
        reject_histogram = {
            "QUOTE_REVERT": 5,
            "SLIPPAGE_TOO_HIGH": 3,
            "INFRA_RPC_ERROR": 2,
        }
        health = build_health_section({}, reject_histogram)

        self.assertIn("gate_breakdown", health)
        self.assertEqual(health["gate_breakdown"]["revert"], 5)
        self.assertEqual(health["gate_breakdown"]["slippage"], 3)
        self.assertEqual(health["gate_breakdown"]["infra"], 2)


class TestBuildGateBreakdown(unittest.TestCase):
    """Tests for build_gate_breakdown function."""

    def test_gate_breakdown_categories(self):
        """Gate breakdown categorizes rejects correctly."""
        reject_histogram = {
            "QUOTE_REVERT": 10,
            "SLIPPAGE_TOO_HIGH": 5,
            "INFRA_RPC_ERROR": 3,
            "OTHER_REASON": 2,
        }
        breakdown = build_gate_breakdown(reject_histogram)

        self.assertEqual(breakdown["revert"], 10)
        self.assertEqual(breakdown["slippage"], 5)
        self.assertEqual(breakdown["infra"], 3)
        self.assertEqual(breakdown["other"], 2)


class TestBuildScanStats(unittest.TestCase):
    """Tests for build_scan_stats function."""

    def test_scan_stats_structure(self):
        """build_scan_stats returns proper structure."""
        stats = build_scan_stats(
            cycle=1,
            timestamp_iso="2026-01-22T12:00:00Z",
            run_mode="SMOKE_SIMULATOR",
            current_block=150000000,
            chain_id=42161,
        )

        self.assertEqual(stats["cycle"], 1)
        self.assertEqual(stats["run_mode"], "SMOKE_SIMULATOR")
        self.assertEqual(stats["chain_id"], 42161)
        self.assertEqual(stats["quotes_fetched"], 0)
        self.assertEqual(stats["quotes_total"], 0)


class TestTruthReport(unittest.TestCase):
    """Tests for TruthReport class."""

    def test_create_truth_report(self):
        """Can create TruthReport."""
        report = TruthReport()
        self.assertIsNotNone(report.timestamp)
        self.assertEqual(report.mode, "REGISTRY")

    def test_to_dict(self):
        """to_dict includes all fields."""
        report = TruthReport(mode="DISCOVERY")
        d = report.to_dict()

        self.assertEqual(d["schema_version"], "3.0.0")
        self.assertEqual(d["mode"], "DISCOVERY")
        self.assertIn("health", d)
        self.assertIn("pnl_normalized", d)

    def test_to_json(self):
        """to_json produces valid JSON."""
        report = TruthReport()
        json_str = report.to_json()
        parsed = json.loads(json_str)
        self.assertIn("schema_version", parsed)

    def test_save_report(self):
        """Can save report to file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            report = TruthReport()
            path = Path(tmpdir) / "test_report.json"
            report.save(path)

            self.assertTrue(path.exists())
            with open(path) as f:
                loaded = json.load(f)
            self.assertEqual(loaded["schema_version"], "3.0.0")


class TestSchemaVersionPolicy(unittest.TestCase):
    """
    Tests for schema_version policy.
    
    POLICY: schema_version MUST NOT change without explicit bump.
    This test ensures SCHEMA_VERSION is the single source of truth.
    """

    def test_schema_version_is_constant(self):
        """SCHEMA_VERSION is defined as constant."""
        self.assertEqual(SCHEMA_VERSION, "3.0.0")

    def test_schema_version_in_report(self):
        """TruthReport uses SCHEMA_VERSION constant."""
        report = TruthReport()
        d = report.to_dict()
        self.assertEqual(d["schema_version"], SCHEMA_VERSION)

    def test_schema_version_format(self):
        """schema_version follows semver format."""
        import re
        pattern = r"^\d+\.\d+\.\d+$"
        self.assertRegex(SCHEMA_VERSION, pattern)

    def test_build_truth_report_uses_constant(self):
        """build_truth_report uses SCHEMA_VERSION constant."""
        report = build_truth_report({}, {}, [])
        d = report.to_dict()
        self.assertEqual(d["schema_version"], SCHEMA_VERSION)


class TestRunModeInReport(unittest.TestCase):
    """
    Tests for run_mode field in TruthReport.
    
    Ensures run_mode is always present and valid.
    """

    def test_default_run_mode(self):
        """Default run_mode is SMOKE_SIMULATOR."""
        report = TruthReport()
        self.assertEqual(report.run_mode, "SMOKE_SIMULATOR")

    def test_run_mode_in_dict(self):
        """run_mode is included in to_dict output."""
        report = TruthReport(run_mode="REGISTRY_REAL")
        d = report.to_dict()
        self.assertIn("run_mode", d)
        self.assertEqual(d["run_mode"], "REGISTRY_REAL")

    def test_build_truth_report_run_mode(self):
        """build_truth_report passes through run_mode."""
        report = build_truth_report({}, {}, [], run_mode="SMOKE_SIMULATOR")
        self.assertEqual(report.run_mode, "SMOKE_SIMULATOR")

        report_real = build_truth_report({}, {}, [], run_mode="REGISTRY_REAL")
        self.assertEqual(report_real.run_mode, "REGISTRY_REAL")


class TestTopRejectReasonsFormat(unittest.TestCase):
    """
    Tests for top_reject_reasons format.
    
    Format must be [[reason, count], ...] for backward compatibility.
    """

    def test_top_reject_reasons_is_list(self):
        """top_reject_reasons is a list."""
        reject_histogram = {"QUOTE_REVERT": 5, "SLIPPAGE_TOO_HIGH": 3}
        health = build_health_section({}, reject_histogram)
        
        self.assertIsInstance(health["top_reject_reasons"], list)

    def test_top_reject_reasons_format(self):
        """Each entry is [reason, count] format."""
        reject_histogram = {"QUOTE_REVERT": 5, "SLIPPAGE_TOO_HIGH": 3}
        health = build_health_section({}, reject_histogram)
        
        for entry in health["top_reject_reasons"]:
            self.assertIsInstance(entry, list)
            self.assertEqual(len(entry), 2)
            self.assertIsInstance(entry[0], str)
            self.assertIsInstance(entry[1], int)

    def test_top_reject_reasons_sorted_descending(self):
        """top_reject_reasons are sorted by count descending."""
        reject_histogram = {"A": 1, "B": 5, "C": 3}
        health = build_health_section({}, reject_histogram)
        
        counts = [entry[1] for entry in health["top_reject_reasons"]]
        self.assertEqual(counts, sorted(counts, reverse=True))

    def test_top_reject_reasons_max_5(self):
        """top_reject_reasons has max 5 entries."""
        reject_histogram = {f"REASON_{i}": i for i in range(10)}
        health = build_health_section({}, reject_histogram)
        
        self.assertLessEqual(len(health["top_reject_reasons"]), 5)


class TestExecutableTerminology(unittest.TestCase):
    """
    Tests for executable terminology clarity.
    
    TERMINOLOGY:
    - paper_executable_spreads: passed gates, PnL > 0, would paper-execute
    - execution_ready_count: actually ready for on-chain (0 in SMOKE)
    """

    def test_stats_has_both_fields(self):
        """Stats includes both paper_executable_spreads and execution_ready_count."""
        scan_stats = {
            "spread_ids_total": 10,
            "spread_ids_profitable": 5,
            "spread_ids_executable": 2,
            "execution_ready_count": 0,
        }
        report = build_truth_report(scan_stats, {}, [])

        self.assertIn("paper_executable_spreads", report.stats)
        self.assertIn("execution_ready_count", report.stats)
        self.assertEqual(
            report.stats["paper_executable_spreads"],
            report.stats["spread_ids_executable"]
        )

    def test_opportunities_have_execution_blockers(self):
        """Opportunities include execution_blockers field."""
        opportunities = [{"spread_id": "s1", "net_pnl_usdc": "1.00"}]
        report = build_truth_report({}, {}, opportunities, run_mode="SMOKE_SIMULATOR")

        for opp in report.top_opportunities:
            self.assertIn("execution_blockers", opp)
            self.assertIn("is_execution_ready", opp)
            self.assertIn("SMOKE_MODE_NO_EXECUTION", opp["execution_blockers"])


class TestNoAmountInAmbiguity(unittest.TestCase):
    """
    Tests for amount_in field clarity.
    
    RULE: Use amount_in_numeraire, NOT ambiguous amount_in.
    """

    def test_opportunities_use_numeraire_only(self):
        """Opportunities should NOT have ambiguous amount_in field."""
        opportunities = [
            {
                "spread_id": "s1",
                "net_pnl_usdc": "1.00",
                "amount_in_numeraire": "100.00",
            }
        ]
        report = build_truth_report({}, {}, opportunities)

        for opp in report.top_opportunities:
            self.assertIn("amount_in_numeraire", opp)
            self.assertNotIn("amount_in", opp)


class TestBuildTruthReport(unittest.TestCase):
    """Tests for build_truth_report function."""

    def test_build_complete_report(self):
        """Builds complete report from scan data."""
        scan_stats = {
            "spread_ids_total": 10,
            "spread_ids_profitable": 5,
            "spread_ids_executable": 2,
        }
        reject_histogram = {"QUOTE_REVERT": 3}
        opportunities = [
            {"spread_id": "s1", "net_pnl_usdc": "1.00"},
            {"spread_id": "s2", "net_pnl_usdc": "0.50"},
        ]
        paper_stats = {
            "total_pnl_usdc": "1.500000",
            "notion_capital_usdc": "10000.000000",
        }

        report = build_truth_report(
            scan_stats=scan_stats,
            reject_histogram=reject_histogram,
            opportunities=opportunities,
            paper_session_stats=paper_stats,
        )

        self.assertEqual(report.stats["spread_ids_total"], 10)
        self.assertEqual(len(report.top_opportunities), 2)
        self.assertEqual(report.pnl["would_execute_pnl_usdc"], "1.500000")

    def test_pnl_fields_are_strings(self):
        """All PnL fields are strings (no float)."""
        report = build_truth_report({}, {}, [])
        d = report.to_dict()

        self.assertIsInstance(d["cumulative_pnl"]["total_usdc"], str)
        self.assertIsInstance(d["pnl"]["signal_pnl_usdc"], str)
        self.assertIsInstance(d["pnl_normalized"]["notion_capital_numeraire"], str)

    def test_top_opportunities_have_chain_id(self):
        """Top opportunities include chain_id."""
        opportunities = [{"spread_id": "s1", "net_pnl_usdc": "1.00", "chain_id": 42161}]
        report = build_truth_report({}, {}, opportunities)

        for opp in report.top_opportunities:
            self.assertIn("chain_id", opp)


class TestCalculateConfidence(unittest.TestCase):
    """Tests for calculate_confidence function."""

    def test_all_ones(self):
        """All 1.0 inputs returns 1.0."""
        score = calculate_confidence(1.0, 1.0, 1.0, 1.0, 1.0)
        self.assertEqual(score, 1.0)

    def test_all_zeros(self):
        """All 0.0 inputs returns 0.0."""
        score = calculate_confidence(0.0, 0.0, 0.0, 0.0, 0.0)
        self.assertEqual(score, 0.0)

    def test_returns_float(self):
        """Returns float type."""
        score = calculate_confidence(0.5, 0.5, 0.5)
        self.assertIsInstance(score, float)


if __name__ == "__main__":
    unittest.main()
