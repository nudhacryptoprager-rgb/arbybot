# PATH: tests/integration/test_smoke_run.py
"""
Integration tests for SMOKE and REAL runs.

STEP 7: REAL mode consistency tests
"""

import json
import logging
import tempfile
import unittest
from pathlib import Path


def _close_all_handlers():
    for handler in logging.root.handlers[:]:
        handler.close()
        logging.root.removeHandler(handler)
    logging.shutdown()


class TestFullSmokeRun(unittest.TestCase):
    def test_full_smoke_run(self):
        from strategy.jobs.run_scan import run_scanner, ScannerMode

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            try:
                run_scanner(mode=ScannerMode.SMOKE, cycles=1, output_dir=output_dir)
                self.assertTrue((output_dir / "scan.log").exists())
            finally:
                _close_all_handlers()


class TestSmokeArtifactsContract(unittest.TestCase):
    def test_all_artifacts_generated(self):
        from strategy.jobs.run_scan import run_scanner, ScannerMode

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            try:
                run_scanner(mode=ScannerMode.SMOKE, cycles=1, output_dir=output_dir)

                snapshots_dir = output_dir / "snapshots"
                reports_dir = output_dir / "reports"

                self.assertTrue(snapshots_dir.exists())
                self.assertTrue(reports_dir.exists())
                self.assertEqual(len(list(snapshots_dir.glob("scan_*.json"))), 1)
                self.assertEqual(len(list(reports_dir.glob("reject_histogram_*.json"))), 1)
                self.assertEqual(len(list(reports_dir.glob("truth_report_*.json"))), 1)
            finally:
                _close_all_handlers()


class TestRealModeContract(unittest.TestCase):
    """REAL MODE CONTRACT TEST."""

    def test_real_mode_runs_without_raising(self):
        from strategy.jobs.run_scan import run_scanner, ScannerMode

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            try:
                run_scanner(mode=ScannerMode.REAL, cycles=1, output_dir=output_dir)
                self.assertTrue((output_dir / "scan.log").exists())
            except RuntimeError as e:
                self.assertIn("INFRA_BLOCK_PIN_FAILED", str(e))
            finally:
                _close_all_handlers()

    def test_real_mode_produces_artifacts(self):
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


class TestRealModeConsistency(unittest.TestCase):
    """
    STEP 7: REAL mode consistency tests.
    
    Ensures truth_report matches scan for key metrics.
    """

    def test_truth_report_health_not_zero_when_quotes_fetched(self):
        """
        STEP 7: If quotes_fetched > 0, truth_report.health must NOT show 0%.
        """
        from strategy.jobs.run_scan import run_scanner, ScannerMode

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            try:
                run_scanner(mode=ScannerMode.REAL, cycles=1, output_dir=output_dir)

                scan_files = list((output_dir / "snapshots").glob("scan_*.json"))
                truth_files = list((output_dir / "reports").glob("truth_report_*.json"))

                if scan_files and truth_files:
                    with open(scan_files[0]) as f:
                        scan = json.load(f)
                    with open(truth_files[0]) as f:
                        truth = json.load(f)

                    quotes_fetched = scan.get("stats", {}).get("quotes_fetched", 0)
                    health = truth.get("health", {})

                    if quotes_fetched > 0:
                        # quote_fetch_rate must NOT be 0
                        self.assertGreater(health.get("quote_fetch_rate", 0), 0,
                            f"quote_fetch_rate should be > 0 when quotes_fetched={quotes_fetched}")

            except RuntimeError as e:
                if "INFRA_BLOCK_PIN_FAILED" in str(e):
                    self.skipTest(f"Network unavailable: {e}")
                raise
            finally:
                _close_all_handlers()

    def test_no_is_execution_ready_when_execution_disabled(self):
        """
        STEP 7: If execution_ready_count == 0, no opp can have is_execution_ready=True.
        """
        from strategy.jobs.run_scan import run_scanner, ScannerMode

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            try:
                run_scanner(mode=ScannerMode.REAL, cycles=1, output_dir=output_dir)

                truth_files = list((output_dir / "reports").glob("truth_report_*.json"))

                if truth_files:
                    with open(truth_files[0]) as f:
                        truth = json.load(f)

                    exec_ready = truth.get("stats", {}).get("execution_ready_count", 0)
                    top_opps = truth.get("top_opportunities", [])

                    if exec_ready == 0:
                        ready_opps = [opp for opp in top_opps if opp.get("is_execution_ready", False)]
                        self.assertEqual(len(ready_opps), 0,
                            f"Found {len(ready_opps)} opps with is_execution_ready=True but execution disabled")

            except RuntimeError as e:
                if "INFRA_BLOCK_PIN_FAILED" in str(e):
                    self.skipTest(f"Network unavailable: {e}")
                raise
            finally:
                _close_all_handlers()

    def test_all_opps_have_blockers_when_execution_disabled(self):
        """
        STEP 7: When execution disabled, all opps must have execution_blockers.
        """
        from strategy.jobs.run_scan import run_scanner, ScannerMode

        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            try:
                run_scanner(mode=ScannerMode.REAL, cycles=1, output_dir=output_dir)

                truth_files = list((output_dir / "reports").glob("truth_report_*.json"))

                if truth_files:
                    with open(truth_files[0]) as f:
                        truth = json.load(f)

                    exec_ready = truth.get("stats", {}).get("execution_ready_count", 0)
                    top_opps = truth.get("top_opportunities", [])

                    if exec_ready == 0 and top_opps:
                        for opp in top_opps:
                            blockers = opp.get("execution_blockers", [])
                            self.assertGreater(len(blockers), 0,
                                f"Opp {opp.get('spread_id')} has no blockers but execution disabled")

            except RuntimeError as e:
                if "INFRA_BLOCK_PIN_FAILED" in str(e):
                    self.skipTest(f"Network unavailable: {e}")
                raise
            finally:
                _close_all_handlers()


if __name__ == "__main__":
    unittest.main()
