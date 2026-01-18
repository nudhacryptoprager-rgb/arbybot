# PATH: tests/integration/test_smoke_run.py
"""
Integration test for full SMOKE run.

Tests the complete flow from scanner to artifacts.
"""

import json
import tempfile
import unittest
from pathlib import Path


class TestFullSmokeRun(unittest.TestCase):
    """Integration test for complete SMOKE run."""
    
    def test_full_smoke_run(self):
        """Run full SMOKE cycle and verify all outputs."""
        from strategy.jobs.run_scan import run_scanner
        
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            
            # Run one cycle
            run_scanner(cycles=1, output_dir=output_dir)
            
            # Verify scan.log exists
            self.assertTrue(
                (output_dir / "scan.log").exists(),
                "scan.log should be created"
            )
            
            # Verify no crashes in log
            with open(output_dir / "scan.log") as f:
                log_content = f.read()
            
            self.assertNotIn("Traceback", log_content)
            self.assertNotIn("ValueError: Unknown format code", log_content)
            self.assertNotIn("TypeError: Logger._log() got an unexpected keyword", log_content)
            
            # Verify reports directory
            reports_dir = output_dir / "reports"
            self.assertTrue(reports_dir.exists())
            
            # Verify truth report
            truth_reports = list(reports_dir.glob("truth_report_*.json"))
            self.assertGreater(len(truth_reports), 0, "Should have truth report")
            
            # Validate truth report content
            with open(truth_reports[0]) as f:
                report = json.load(f)
            
            self.assertIn("schema_version", report)
            self.assertIn("health", report)
            self.assertIn("pnl", report)
            
            # Verify RPC consistency
            health = report["health"]
            rpc_total = health.get("rpc_total_requests", 0)
            rpc_failed = health.get("rpc_failed_requests", 0)
            
            # If we have failed requests, total should be > 0
            if rpc_failed > 0:
                self.assertGreater(rpc_total, 0,
                    "rpc_total_requests should be > 0 if rpc_failed_requests > 0")
            
            # Verify money fields are strings
            self.assertIsInstance(report["pnl"]["signal_pnl_usdc"], str)
            self.assertIsInstance(report["cumulative_pnl"]["total_usdc"], str)


if __name__ == "__main__":
    unittest.main()