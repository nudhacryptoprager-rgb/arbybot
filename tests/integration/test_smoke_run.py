# PATH: tests/integration/test_smoke_run.py
"""
Integration test for full SMOKE run.

Tests the complete flow from scanner to artifacts.

SMOKE ARTIFACTS CONTRACT:
- scan_*.json: Snapshot with stats, rejects, opportunities
- reject_histogram_*.json: Reject breakdown by reason
- truth_report_*.json: Final truth report with health, stats, opps
All three files MUST be generated and parseable.

REAL MODE CONTRACT:
- Without explicit enable (--allow-real or --config): raises RuntimeError
- With explicit enable: runs live RPC pipeline (tested separately in ci_m4_gate.py)
"""

import json
import logging
import tempfile
import unittest
from pathlib import Path


def _close_all_handlers():
    """Close all logging handlers to release file locks (fixes WinError32)."""
    for handler in logging.root.handlers[:]:
        handler.close()
        logging.root.removeHandler(handler)
    logging.shutdown()


class TestFullSmokeRun(unittest.TestCase):
    """Integration test for complete SMOKE run."""

    def test_full_smoke_run(self):
        """Run full SMOKE cycle and verify all outputs."""
        from strategy.jobs.run_scan import run_scanner, ScannerMode

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            try:
                # Run one cycle in smoke mode
                run_scanner(mode=ScannerMode.SMOKE, cycles=1, output_dir=output_dir)

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

                if rpc_failed > 0:
                    self.assertGreater(rpc_total, 0, "rpc_total_requests should be > 0 if rpc_failed_requests > 0")

                # Verify money fields are strings
                self.assertIsInstance(report["pnl"]["signal_pnl_usdc"], str)
                self.assertIsInstance(report["cumulative_pnl"]["total_usdc"], str)

            finally:
                # CRITICAL: Close all handlers before tmpdir cleanup (fixes WinError32)
                _close_all_handlers()


class TestSmokeArtifactsContract(unittest.TestCase):
    """
    STEP 8: Smoke artifacts contract test.

    Verifies that all 3 required artifact files are generated and parseable.
    """

    def test_all_artifacts_generated(self):
        """All 3 artifact files are generated: scan, reject_histogram, truth_report."""
        from strategy.jobs.run_scan import run_scanner, ScannerMode

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            try:
                run_scanner(mode=ScannerMode.SMOKE, cycles=1, output_dir=output_dir)

                # Check snapshots directory
                snapshots_dir = output_dir / "snapshots"
                self.assertTrue(snapshots_dir.exists(), "snapshots directory must exist")

                # Check reports directory
                reports_dir = output_dir / "reports"
                self.assertTrue(reports_dir.exists(), "reports directory must exist")

                # 1. scan_*.json
                scan_files = list(snapshots_dir.glob("scan_*.json"))
                self.assertEqual(len(scan_files), 1, "Exactly one scan snapshot")

                with open(scan_files[0]) as f:
                    scan_data = json.load(f)
                self.assertIn("stats", scan_data)
                self.assertIn("reject_histogram", scan_data)
                self.assertIn("gate_breakdown", scan_data)

                # 2. reject_histogram_*.json
                reject_files = list(reports_dir.glob("reject_histogram_*.json"))
                self.assertEqual(len(reject_files), 1, "Exactly one reject histogram")

                with open(reject_files[0]) as f:
                    reject_data = json.load(f)
                self.assertIn("histogram", reject_data)
                self.assertIn("gate_breakdown", reject_data)

                # 3. truth_report_*.json
                truth_files = list(reports_dir.glob("truth_report_*.json"))
                self.assertEqual(len(truth_files), 1, "Exactly one truth report")

                with open(truth_files[0]) as f:
                    truth_data = json.load(f)
                self.assertIn("schema_version", truth_data)
                self.assertIn("health", truth_data)
                self.assertIn("stats", truth_data)
                self.assertIn("top_opportunities", truth_data)

            finally:
                _close_all_handlers()

    def test_gate_breakdown_synced(self):
        """gate_breakdown is identical between scan.json and truth_report.json."""
        from strategy.jobs.run_scan import run_scanner, ScannerMode

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            try:
                run_scanner(mode=ScannerMode.SMOKE, cycles=1, output_dir=output_dir)

                # Load scan
                scan_files = list((output_dir / "snapshots").glob("scan_*.json"))
                with open(scan_files[0]) as f:
                    scan_data = json.load(f)

                # Load truth report
                truth_files = list((output_dir / "reports").glob("truth_report_*.json"))
                with open(truth_files[0]) as f:
                    truth_data = json.load(f)

                scan_breakdown = scan_data.get("gate_breakdown", {})
                truth_breakdown = truth_data.get("health", {}).get("gate_breakdown", {})

                # Must be identical
                self.assertEqual(scan_breakdown, truth_breakdown,
                    "gate_breakdown must be synced between scan.json and truth_report.json")

            finally:
                _close_all_handlers()

    def test_dex_coverage_contract(self):
        """DEX coverage includes configured vs active."""
        from strategy.jobs.run_scan import run_scanner, ScannerMode

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            try:
                run_scanner(mode=ScannerMode.SMOKE, cycles=1, output_dir=output_dir)

                # Load scan
                scan_files = list((output_dir / "snapshots").glob("scan_*.json"))
                with open(scan_files[0]) as f:
                    scan_data = json.load(f)

                # Check dex_coverage
                dex_coverage = scan_data.get("dex_coverage", {})
                self.assertIn("configured", dex_coverage)
                self.assertIn("with_quotes", dex_coverage)
                self.assertIn("passed_gates", dex_coverage)

                # configured >= with_quotes >= passed_gates
                self.assertGreaterEqual(
                    len(dex_coverage["configured"]),
                    len(dex_coverage["with_quotes"]),
                )

            finally:
                _close_all_handlers()


class TestRealModeRaises(unittest.TestCase):
    """
    Test that --mode real WITHOUT explicit enable raises RuntimeError.
    
    REAL MODE CONTRACT:
    - Without --allow-real AND without --config: raises RuntimeError
    - Error message must contain "requires explicit enable"
    - This prevents accidental live RPC calls in tests/CI
    """

    def test_real_mode_raises_runtime_error_without_explicit_enable(self):
        """
        --mode real without explicit enable should raise RuntimeError.
        
        This is the SAFETY CONTRACT for REAL mode:
        - Calling run_scanner(mode=ScannerMode.REAL) without allow_real=True
          or config_path must raise RuntimeError.
        - The error message must indicate how to enable REAL mode.
        """
        from strategy.jobs.run_scan import run_scanner, ScannerMode

        with self.assertRaises(RuntimeError) as ctx:
            # Call WITHOUT explicit enable - should raise
            run_scanner(mode=ScannerMode.REAL, cycles=1)

        error_message = str(ctx.exception).lower()
        
        # Error message must indicate this is about explicit enable
        self.assertTrue(
            "requires explicit enable" in error_message or
            "explicit" in error_message or
            "--allow-real" in error_message or
            "--config" in error_message,
            f"Error message should mention explicit enable requirement. Got: {ctx.exception}"
        )

    def test_real_mode_with_allow_real_does_not_raise_immediately(self):
        """
        --mode real WITH --allow-real should not raise RuntimeError about explicit enable.
        
        Note: This may still fail due to network/RPC issues, but NOT due to
        the "requires explicit enable" check.
        """
        from strategy.jobs.run_scan import run_scanner, ScannerMode
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)

            try:
                # Call WITH explicit enable - should NOT raise "requires explicit enable"
                # May still fail due to network, but that's a different error
                run_scanner(
                    mode=ScannerMode.REAL,
                    cycles=1,
                    output_dir=output_dir,
                    allow_real=True,  # Explicit enable
                )
            except RuntimeError as e:
                # If it raises, it should NOT be about explicit enable
                error_message = str(e).lower()
                self.assertFalse(
                    "requires explicit enable" in error_message,
                    f"With allow_real=True, should not get 'requires explicit enable' error. Got: {e}"
                )
            except Exception:
                # Other exceptions (network, etc.) are acceptable
                pass
            finally:
                _close_all_handlers()


if __name__ == "__main__":
    unittest.main()
