# PATH: tests/unit/test_health_metrics.py
"""
Unit tests for RPCHealthMetrics contract.

API CONTRACT (M4):
- record_rpc_call(success, latency_ms): primary method used by run_scan_real.py
- record_success(latency_ms): legacy method
- record_failure(): legacy method
"""

import unittest


class TestRPCHealthMetrics(unittest.TestCase):
    """Test RPCHealthMetrics API contract."""

    def test_record_rpc_call_exists(self):
        """record_rpc_call method must exist."""
        from monitoring.truth_report import RPCHealthMetrics
        
        metrics = RPCHealthMetrics()
        self.assertTrue(hasattr(metrics, "record_rpc_call"))
        self.assertTrue(callable(metrics.record_rpc_call))

    def test_record_rpc_call_success_increments_success_count(self):
        """record_rpc_call(success=True) increments rpc_success_count."""
        from monitoring.truth_report import RPCHealthMetrics
        
        metrics = RPCHealthMetrics()
        self.assertEqual(metrics.rpc_success_count, 0)
        self.assertEqual(metrics.rpc_failed_count, 0)
        
        metrics.record_rpc_call(success=True, latency_ms=100)
        
        self.assertEqual(metrics.rpc_success_count, 1)
        self.assertEqual(metrics.rpc_failed_count, 0)
        self.assertEqual(metrics.rpc_total_requests, 1)
        self.assertEqual(metrics.total_latency_ms, 100)

    def test_record_rpc_call_failure_increments_failed_count(self):
        """record_rpc_call(success=False) increments rpc_failed_count."""
        from monitoring.truth_report import RPCHealthMetrics
        
        metrics = RPCHealthMetrics()
        
        metrics.record_rpc_call(success=False, latency_ms=0)
        
        self.assertEqual(metrics.rpc_success_count, 0)
        self.assertEqual(metrics.rpc_failed_count, 1)
        self.assertEqual(metrics.rpc_total_requests, 1)

    def test_record_rpc_call_accumulates_latency(self):
        """record_rpc_call accumulates latency for successful calls."""
        from monitoring.truth_report import RPCHealthMetrics
        
        metrics = RPCHealthMetrics()
        
        metrics.record_rpc_call(success=True, latency_ms=100)
        metrics.record_rpc_call(success=True, latency_ms=200)
        metrics.record_rpc_call(success=True, latency_ms=150)
        
        self.assertEqual(metrics.rpc_success_count, 3)
        self.assertEqual(metrics.total_latency_ms, 450)
        self.assertEqual(metrics.avg_latency_ms, 150)  # 450 // 3

    def test_record_rpc_call_handles_float_latency(self):
        """record_rpc_call handles float latency_ms (converts to int)."""
        from monitoring.truth_report import RPCHealthMetrics
        
        metrics = RPCHealthMetrics()
        
        metrics.record_rpc_call(success=True, latency_ms=123.456)
        
        self.assertEqual(metrics.total_latency_ms, 123)

    def test_rpc_success_rate_calculation(self):
        """rpc_success_rate is correctly calculated."""
        from monitoring.truth_report import RPCHealthMetrics
        
        metrics = RPCHealthMetrics()
        
        # 0/0 = 0
        self.assertEqual(metrics.rpc_success_rate, 0.0)
        
        # 3 success, 1 failure = 75%
        metrics.record_rpc_call(success=True, latency_ms=10)
        metrics.record_rpc_call(success=True, latency_ms=10)
        metrics.record_rpc_call(success=True, latency_ms=10)
        metrics.record_rpc_call(success=False, latency_ms=0)
        
        self.assertAlmostEqual(metrics.rpc_success_rate, 0.75, places=2)

    def test_avg_latency_zero_on_no_success(self):
        """avg_latency_ms is 0 when no successful calls."""
        from monitoring.truth_report import RPCHealthMetrics
        
        metrics = RPCHealthMetrics()
        
        metrics.record_rpc_call(success=False, latency_ms=0)
        metrics.record_rpc_call(success=False, latency_ms=0)
        
        self.assertEqual(metrics.avg_latency_ms, 0)

    def test_legacy_record_success_still_works(self):
        """Legacy record_success method still works."""
        from monitoring.truth_report import RPCHealthMetrics
        
        metrics = RPCHealthMetrics()
        
        metrics.record_success(latency_ms=50)
        
        self.assertEqual(metrics.rpc_success_count, 1)
        self.assertEqual(metrics.total_latency_ms, 50)
        self.assertEqual(metrics.quote_call_attempts, 1)

    def test_legacy_record_failure_still_works(self):
        """Legacy record_failure method still works."""
        from monitoring.truth_report import RPCHealthMetrics
        
        metrics = RPCHealthMetrics()
        
        metrics.record_failure()
        
        self.assertEqual(metrics.rpc_failed_count, 1)
        self.assertEqual(metrics.quote_call_attempts, 1)

    def test_to_dict_output(self):
        """to_dict returns expected structure."""
        from monitoring.truth_report import RPCHealthMetrics
        
        metrics = RPCHealthMetrics()
        metrics.record_rpc_call(success=True, latency_ms=100)
        metrics.record_rpc_call(success=False, latency_ms=0)
        
        result = metrics.to_dict()
        
        self.assertIn("rpc_success_rate", result)
        self.assertIn("rpc_avg_latency_ms", result)
        self.assertIn("rpc_total_requests", result)
        self.assertIn("rpc_failed_requests", result)
        self.assertEqual(result["rpc_total_requests"], 2)
        self.assertEqual(result["rpc_failed_requests"], 1)


if __name__ == "__main__":
    unittest.main()
