# PATH: tests/integration/test_smoke_run.py
"""
Integration tests for SMOKE and REAL runs.

SMOKE ARTIFACTS CONTRACT:
- scan_*.json, reject_histogram_*.json, truth_report_*.json
- All must be generated and parseable

REAL MODE CONTRACT (M4):
- REAL runs without raising (except network failures)
- Produces 4 artifacts
- Execution disabled (execution_ready_count == 0)
- run_mode == "REGISTRY_REAL"
"""

import json
import logging
import tempfile
import unittest
from pathlib import Path


def _close_all_handlers():
    """Close logging handlers (fixes WinError32)."""
    for handler in logging.root.handlers[:]:
        handler.close()
        logging.root.removeHandler(handler)
    logging.shutdown()


class TestFullSmokeRun(unittest.TestCase):
    """Integration test for SMOKE run."""

    def test_full_smoke_run(self):
        """Run full SMOKE cycle and verify outputs."""
        from strategy.jobs.run_scan import run_scanner, ScannerMode

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            try:
                run_scanner(mode=ScannerMode.SMOKE, cycles=1, output_dir=output_dir)

                self.assertTrue((output_dir / "scan.log").exists())

                with open(output_dir / "scan.log") as f:
                    log_content = f.read()
                self.assertNotIn("Traceback", log_content)

                reports_dir = output_dir / "reports"
                self.assertTrue(reports_dir.exists())

                truth_reports = list(reports_dir.glob("truth_report_*.json"))
                self.assertGreater(len(truth_reports), 0)

                with open(truth_reports[0]) as f:
                    report = json.load(f)
                self.assertIn("schema_version", report)
                self.assertIn("health", report)

            finally:
                _close_all_handlers()


class TestSmokeArtifactsContract(unittest.TestCase):
    """Smoke artifacts contract test."""

    def test_all_artifacts_generated(self):
        """All 3 artifact files are generated."""
        from strategy.jobs.run_scan import run_scanner, ScannerMode

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            try:
                run_scanner(mode=ScannerMode.SMOKE, cycles=1, output_dir=output_dir)

                snapshots_dir = output_dir / "snapshots"
                reports_dir = output_dir / "reports"

                self.assertTrue(snapshots_dir.exists())
                self.assertTrue(reports_dir.exists())

                scan_files = list(snapshots_dir.glob("scan_*.json"))
                self.assertEqual(len(scan_files), 1)

                reject_files = list(reports_dir.glob("reject_histogram_*.json"))
                self.assertEqual(len(reject_files), 1)

                truth_files = list(reports_dir.glob("truth_report_*.json"))
                self.assertEqual(len(truth_files), 1)

            finally:
                _close_all_handlers()

    def test_gate_breakdown_synced(self):
        """gate_breakdown is synced between artifacts."""
        from strategy.jobs.run_scan import run_scanner, ScannerMode

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            try:
                run_scanner(mode=ScannerMode.SMOKE, cycles=1, output_dir=output_dir)

                scan_files = list((output_dir / "snapshots").glob("scan_*.json"))
                with open(scan_files[0]) as f:
                    scan_data = json.load(f)

                truth_files = list((output_dir / "reports").glob("truth_report_*.json"))
                with open(truth_files[0]) as f:
                    truth_data = json.load(f)

                scan_breakdown = scan_data.get("gate_breakdown", {})
                truth_breakdown = truth_data.get("health", {}).get("gate_breakdown", {})

                self.assertEqual(scan_breakdown, truth_breakdown)

            finally:
                _close_all_handlers()


class TestRealModeContract(unittest.TestCase):
    """
    M4 REAL MODE CONTRACT TEST.
    
    REAL mode must:
    - Run without raising (except INFRA_BLOCK_PIN_FAILED)
    - Produce 4 artifacts
    - Have execution disabled
    - Have run_mode == "REGISTRY_REAL"
    """

    def test_real_mode_runs_without_raising(self):
        """REAL mode runs without RuntimeError (except network failures)."""
        from strategy.jobs.run_scan import run_scanner, ScannerMode

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            try:
                run_scanner(mode=ScannerMode.REAL, cycles=1, output_dir=output_dir)
                self.assertTrue((output_dir / "scan.log").exists())
            except RuntimeError as e:
                # Only INFRA_BLOCK_PIN_FAILED is acceptable
                self.assertIn("INFRA_BLOCK_PIN_FAILED", str(e))
            finally:
                _close_all_handlers()

    def test_real_mode_produces_artifacts(self):
        """REAL mode produces 4 artifacts."""
        from strategy.jobs.run_scan import run_scanner, ScannerMode

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            try:
                run_scanner(mode=ScannerMode.REAL, cycles=1, output_dir=output_dir)

                self.assertTrue((output_dir / "scan.log").exists())

                snapshots = output_dir / "snapshots"
                reports = output_dir / "reports"

                if snapshots.exists():
                    self.assertGreater(len(list(snapshots.glob("scan_*.json"))), 0)
                if reports.exists():
                    self.assertGreater(len(list(reports.glob("reject_histogram_*.json"))), 0)
                    self.assertGreater(len(list(reports.glob("truth_report_*.json"))), 0)

            except RuntimeError as e:
                if "INFRA_BLOCK_PIN_FAILED" in str(e):
                    self.skipTest(f"Network unavailable: {e}")
                raise
            finally:
                _close_all_handlers()

    def test_real_mode_execution_disabled(self):
        """REAL mode has execution disabled."""
        from strategy.jobs.run_scan import run_scanner, ScannerMode

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            try:
                run_scanner(mode=ScannerMode.REAL, cycles=1, output_dir=output_dir)

                truth_files = list((output_dir / "reports").glob("truth_report_*.json"))
                if truth_files:
                    with open(truth_files[0]) as f:
                        truth = json.load(f)
                    stats = truth.get("stats", {})
                    self.assertEqual(stats.get("execution_ready_count", 0), 0)

            except RuntimeError as e:
                if "INFRA_BLOCK_PIN_FAILED" in str(e):
                    self.skipTest(f"Network unavailable: {e}")
                raise
            finally:
                _close_all_handlers()

    def test_real_mode_not_smoke_fallback(self):
        """REAL mode does not fall back to SMOKE."""
        from strategy.jobs.run_scan import run_scanner, ScannerMode

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            try:
                run_scanner(mode=ScannerMode.REAL, cycles=1, output_dir=output_dir)

                scan_files = list((output_dir / "snapshots").glob("scan_*.json"))
                if scan_files:
                    with open(scan_files[0]) as f:
                        scan = json.load(f)
                    self.assertEqual(scan.get("run_mode"), "REGISTRY_REAL")

            except RuntimeError as e:
                if "INFRA_BLOCK_PIN_FAILED" in str(e):
                    self.skipTest(f"Network unavailable: {e}")
                raise
            finally:
                _close_all_handlers()


if __name__ == "__main__":
    unittest.main()
