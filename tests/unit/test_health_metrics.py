# PATH: tests/unit/test_health_metrics.py
"""
Tests for RPC health metrics and consistency.

Per Issue #3 AC (D): RPC health must be consistent with reject histogram.
"""

import unittest
from monitoring.truth_report import RPCHealthMetrics, build_health_section


class TestRPCHealthMetricsBasic(unittest.TestCase):
    """Basic tests for RPCHealthMetrics."""
    
    def test_initial_state(self):
        """Fresh metrics have zero counts."""
        m = RPCHealthMetrics()
        
        self.assertEqual(m.rpc_success_count, 0)
        self.assertEqual(m.rpc_failed_count, 0)
        self.assertEqual(m.quote_call_attempts, 0)
        self.assertEqual(m.total_latency_ms, 0)
    
    def test_record_success(self):
        """Recording success updates counters."""
        m = RPCHealthMetrics()
        
        m.record_success(latency_ms=100)
        
        self.assertEqual(m.rpc_success_count, 1)
        self.assertEqual(m.quote_call_attempts, 1)
        self.assertEqual(m.total_latency_ms, 100)
    
    def test_record_failure(self):
        """Recording failure updates counters."""
        m = RPCHealthMetrics()
        
        m.record_failure()
        
        self.assertEqual(m.rpc_failed_count, 1)
        self.assertEqual(m.quote_call_attempts, 1)
    
    def test_rpc_total_requests(self):
        """Total requests = success + failed."""
        m = RPCHealthMetrics()
        
        m.record_success()
        m.record_success()
        m.record_failure()
        
        self.assertEqual(m.rpc_total_requests, 3)
    
    def test_success_rate(self):
        """Success rate calculated correctly."""
        m = RPCHealthMetrics()
        
        m.record_success()
        m.record_success()
        m.record_success()
        m.record_failure()
        
        self.assertAlmostEqual(m.rpc_success_rate, 0.75)
    
    def test_success_rate_zero_requests(self):
        """Success rate is 0 with no requests."""
        m = RPCHealthMetrics()
        
        self.assertEqual(m.rpc_success_rate, 0.0)
    
    def test_avg_latency(self):
        """Average latency calculated correctly."""
        m = RPCHealthMetrics()
        
        m.record_success(latency_ms=100)
        m.record_success(latency_ms=200)
        m.record_success(latency_ms=300)
        
        self.assertEqual(m.avg_latency_ms, 200)
    
    def test_avg_latency_zero_success(self):
        """Average latency is 0 with no successful requests."""
        m = RPCHealthMetrics()
        m.record_failure()
        
        self.assertEqual(m.avg_latency_ms, 0)


class TestRPCHealthReconciliation(unittest.TestCase):
    """Tests for reconcile_with_rejects method."""
    
    def test_reconcile_adds_missing_failures(self):
        """Reconciliation adds INFRA_RPC_ERROR count to failures."""
        m = RPCHealthMetrics()
        # No failures tracked
        
        m.reconcile_with_rejects({"INFRA_RPC_ERROR": 10})
        
        self.assertEqual(m.rpc_failed_count, 10)
        self.assertEqual(m.rpc_total_requests, 10)
    
    def test_reconcile_preserves_higher_count(self):
        """Reconciliation doesn't reduce existing failure count."""
        m = RPCHealthMetrics()
        
        # Track 20 failures
        for _ in range(20):
            m.record_failure()
        
        # Rejects show only 10
        m.reconcile_with_rejects({"INFRA_RPC_ERROR": 10})
        
        # Should keep 20
        self.assertEqual(m.rpc_failed_count, 20)
    
    def test_reconcile_with_no_errors(self):
        """Reconciliation does nothing with no INFRA_RPC_ERROR."""
        m = RPCHealthMetrics()
        
        m.reconcile_with_rejects({"QUOTE_REVERT": 10, "SLIPPAGE_TOO_HIGH": 5})
        
        self.assertEqual(m.rpc_failed_count, 0)
    
    def test_reconcile_updates_quote_attempts(self):
        """Reconciliation ensures quote_call_attempts >= rpc_total."""
        m = RPCHealthMetrics()
        
        m.reconcile_with_rejects({"INFRA_RPC_ERROR": 5})
        
        self.assertGreaterEqual(m.quote_call_attempts, m.rpc_total_requests)


class TestHealthSectionConsistency(unittest.TestCase):
    """Tests that build_health_section maintains RPC consistency."""
    
    def test_health_reconciles_automatically(self):
        """build_health_section calls reconcile internally."""
        scan_stats = {}
        reject_histogram = {"INFRA_RPC_ERROR": 15}
        rpc_metrics = RPCHealthMetrics()  # No calls recorded
        
        health = build_health_section(scan_stats, reject_histogram, rpc_metrics)
        
        # Should have reconciled
        self.assertGreater(health["rpc_total_requests"], 0)
        self.assertGreaterEqual(health["rpc_failed_requests"], 15)
    
    def test_health_without_rpc_metrics(self):
        """build_health_section works without rpc_metrics arg."""
        health = build_health_section(
            scan_stats={},
            reject_histogram={"INFRA_RPC_ERROR": 5}
        )
        
        # Should still reconcile with default metrics
        self.assertGreater(health["rpc_total_requests"], 0)
    
    def test_health_structure(self):
        """Health section has required fields."""
        health = build_health_section({}, {})
        
        required_fields = [
            "rpc_success_rate",
            "rpc_avg_latency_ms",
            "rpc_total_requests",
            "rpc_failed_requests",
            "quote_fetch_rate",
            "quote_gate_pass_rate",
            "chains_active",
            "dexes_active",
            "pairs_covered",
            "pools_scanned",
            "top_reject_reasons",
        ]
        
        for field in required_fields:
            self.assertIn(field, health, f"Missing field: {field}")
    
    def test_top_reject_reasons_sorted(self):
        """Top reject reasons are sorted by count descending."""
        reject_histogram = {
            "A": 5,
            "B": 20,
            "C": 10,
        }
        
        health = build_health_section({}, reject_histogram)
        
        top_reasons = health["top_reject_reasons"]
        counts = [r[1] for r in top_reasons]
        
        self.assertEqual(counts, sorted(counts, reverse=True))


if __name__ == "__main__":
    unittest.main()