# PATH: tests/unit/test_truth_report.py
"""
Unit tests for truth_report module.

Tests TruthReport, RPCHealthMetrics, and health building functions.
"""

import json
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from monitoring.truth_report import (
    TruthReport,
    RPCHealthMetrics,
    calculate_confidence,
    build_truth_report,
    build_health_section,
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
        
        # No failures recorded, but rejects show errors
        metrics.reconcile_with_rejects({"INFRA_RPC_ERROR": 5})
        
        self.assertEqual(metrics.rpc_failed_count, 5)
        self.assertEqual(metrics.rpc_total_requests, 5)
    
    def test_reconcile_with_rejects_preserves_higher(self):
        """Reconciliation preserves higher failure count."""
        metrics = RPCHealthMetrics()
        
        # Record 10 failures
        for _ in range(10):
            metrics.record_failure()
        
        # Rejects show only 5 errors
        metrics.reconcile_with_rejects({"INFRA_RPC_ERROR": 5})
        
        # Should keep 10, not reduce to 5
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
        rpc_metrics = RPCHealthMetrics()  # No calls recorded
        
        health = build_health_section(scan_stats, reject_histogram, rpc_metrics)
        
        # Should have non-zero requests due to reconciliation
        self.assertGreater(health["rpc_total_requests"], 0)
        self.assertGreaterEqual(health["rpc_failed_requests"], 10)


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