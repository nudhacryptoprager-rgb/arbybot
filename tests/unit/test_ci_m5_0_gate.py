# PATH: tests/unit/test_ci_m5_0_gate.py
"""Unit tests for ci_m5_0_gate.py v2.1.0."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.ci_m5_0_gate import (
    generate_fixture_artifacts,
    discover_artifacts,
    validate_artifacts,
    validate_schema_version,
    validate_health_metrics,
    main,
    __version__,
    validate_current_block,
)


class TestVersion(unittest.TestCase):
    def test_version_is_2_1_0(self):
        self.assertEqual(__version__, "2.1.0")


class TestModeExclusion(unittest.TestCase):
    def test_offline_and_online_together_error(self):
        """--offline + --online → argparse error."""
        with patch('sys.argv', ['ci_m5_0_gate.py', '--offline', '--online']):
            with self.assertRaises(SystemExit) as cm:
                main()
            self.assertEqual(cm.exception.code, 2)


class TestOfflineModeIgnoresEnv(unittest.TestCase):
    def test_offline_ignores_arby_run_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir)
            
            env_backup = os.environ.copy()
            os.environ["ARBY_RUN_DIR"] = "/nonexistent"
            
            try:
                with patch('sys.argv', ['ci_m5_0_gate.py', '--offline', '--output-root', str(output_root)]):
                    result = main()
                
                self.assertEqual(result, 0)
                dirs = list(output_root.glob("ci_m5_gate_offline_*"))
                self.assertEqual(len(dirs), 1)
            finally:
                os.environ.clear()
                os.environ.update(env_backup)


class TestFixtureGeneration(unittest.TestCase):
    def test_generate_creates_all_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            artifacts = generate_fixture_artifacts(Path(tmpdir), "20260201_120000")
            
            self.assertIn("scan", artifacts)
            self.assertIn("truth_report", artifacts)
            self.assertIn("reject_histogram", artifacts)
            
            for path in artifacts.values():
                self.assertTrue(path.exists())

    def test_fixture_has_schema_version(self):
        """All fixtures MUST have schema_version."""
        with tempfile.TemporaryDirectory() as tmpdir:
            artifacts = generate_fixture_artifacts(Path(tmpdir), "20260201_120000")
            
            for name, path in artifacts.items():
                with open(path) as f:
                    data = json.load(f)
                self.assertIn("schema_version", data, f"{name} missing schema_version")

    def test_fixture_has_top_level_metrics(self):
        """truth_report MUST have top-level metrics."""
        with tempfile.TemporaryDirectory() as tmpdir:
            artifacts = generate_fixture_artifacts(Path(tmpdir), "20260201_120000")
            
            with open(artifacts["truth_report"]) as f:
                data = json.load(f)
            
            self.assertIn("quotes_total", data)
            self.assertIn("dexes_active", data)


class TestDiscoverArtifacts(unittest.TestCase):
    def test_discover_from_reports(self):
        """Should find artifacts in reports/."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            generate_fixture_artifacts(run_dir, "20260201_120000")
            
            artifacts = discover_artifacts(run_dir)
            
            self.assertIsNotNone(artifacts["scan"])
            self.assertIsNotNone(artifacts["truth_report"])
            self.assertIsNotNone(artifacts["reject_histogram"])

    def test_discover_fallback_to_snapshots(self):
        """Should fallback to snapshots/ for scan if not in reports/."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            
            # Create scan only in snapshots/
            snapshots = run_dir / "snapshots"
            snapshots.mkdir()
            scan_data = {"schema_version": "3.2.0"}
            with open(snapshots / "scan_20260201.json", "w") as f:
                json.dump(scan_data, f)
            
            artifacts = discover_artifacts(run_dir)
            
            self.assertIsNotNone(artifacts["scan"])


class TestValidation(unittest.TestCase):
    def test_validate_schema_version_valid(self):
        ok, _ = validate_schema_version({"schema_version": "3.2.0"})
        self.assertTrue(ok)

    def test_validate_schema_version_missing(self):
        ok, msg = validate_schema_version({})
        self.assertFalse(ok)
        self.assertIn("Missing", msg)

    def test_validate_health_metrics_from_top_level(self):
        """Should accept metrics from top-level."""
        ok, _ = validate_health_metrics({"quotes_total": 10, "dexes_active": 2})
        self.assertTrue(ok)

    def test_validate_health_metrics_from_nested(self):
        """Should accept metrics from nested health."""
        ok, _ = validate_health_metrics({"health": {"quotes_total": 10, "dexes_active": 2}})
        self.assertTrue(ok)


class TestRequireReal(unittest.TestCase):
    def test_require_real_rejects_fixture(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            generate_fixture_artifacts(run_dir, "20260201_120000")
            
            with patch('sys.argv', ['ci_m5_0_gate.py', '--run-dir', str(run_dir), '--require-real']):
                result = main()
            
            self.assertEqual(result, 1)


class TestEnvVariables(unittest.TestCase):
    def test_arby_config_env(self):
        """ARBY_CONFIG should override default."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            generate_fixture_artifacts(run_dir, "20260201_120000")
            
            env_backup = os.environ.copy()
            os.environ["ARBY_CONFIG"] = "config/test.yaml"
            
            try:
                with patch('sys.argv', ['ci_m5_0_gate.py', '--run-dir', str(run_dir)]):
                    # Just check it doesn't crash
                    result = main()
                    self.assertIn(result, [0, 1])
            finally:
                os.environ.clear()
                os.environ.update(env_backup)


class TestCurrentBlockValidation(unittest.TestCase):
    def test_validate_current_block_success(self):
        scan = {"current_block": 100}
        truth = {"current_block": 100}
        ok, msg = validate_current_block(scan, truth)
        self.assertTrue(ok)
        self.assertIn("current_block OK", msg)

    def test_validate_current_block_mismatch(self):
        scan = {"current_block": 10}
        truth = {"current_block": 11}
        ok, msg = validate_current_block(scan, truth)
        self.assertFalse(ok)
        self.assertIn("mismatch", msg)

    def test_validate_current_block_missing(self):
        scan = {"current_block": 10}
        truth = {}
        ok, msg = validate_current_block(scan, truth)
        self.assertFalse(ok)
        self.assertIn("Missing current_block", msg)


    def test_gate_fails_when_truth_missing_run_mode(self):
        # Create a run_dir with scan and truth_report missing run_mode
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            reports = run_dir / "reports"
            reports.mkdir(parents=True)
            now = "20260204_120000"
            scan = {"schema_version": "3.2.0", "run_mode": "REGISTRY_REAL", "current_block": 100, "quotes_total": 2, "dexes_active": 2}
            truth = {"schema_version": "3.2.0", "current_block": 100, "quotes_total": 2, "quotes_fetched": 2, "dexes_active": 2, "price_sanity_passed": 1, "price_sanity_failed": 0}
            # deliberately remove run_mode from truth to simulate bad generator
            if "run_mode" in truth:
                truth.pop("run_mode")

            with open(reports / f"scan_{now}.json", "w") as f:
                json.dump(scan, f)
            with open(reports / f"truth_report_{now}.json", "w") as f:
                json.dump(truth, f)
            with open(reports / f"reject_histogram_{now}.json", "w") as f:
                json.dump({"schema_version": "3.2.0", "rejects": []}, f)

            with patch('sys.argv', ['ci_m5_0_gate.py', '--run-dir', str(run_dir), '--require-real']):
                result = main()
            self.assertNotEqual(result, 0)

    def test_gate_fails_on_current_block_mismatch(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            reports = run_dir / "reports"
            reports.mkdir(parents=True)
            now = "20260204_120001"
            scan = {"schema_version": "3.2.0", "run_mode": "REGISTRY_REAL", "current_block": 100, "quotes_total": 2, "dexes_active": 2}
            truth = {"schema_version": "3.2.0", "run_mode": "REGISTRY_REAL", "current_block": 101, "quotes_total": 2, "quotes_fetched": 2, "dexes_active": 2, "price_sanity_passed": 1, "price_sanity_failed": 0}

            with open(reports / f"scan_{now}.json", "w") as f:
                json.dump(scan, f)
            with open(reports / f"truth_report_{now}.json", "w") as f:
                json.dump(truth, f)
            with open(reports / f"reject_histogram_{now}.json", "w") as f:
                json.dump({"schema_version": "3.2.0", "rejects": []}, f)

            with patch('sys.argv', ['ci_m5_0_gate.py', '--run-dir', str(run_dir), '--require-real']):
                result = main()
            self.assertNotEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
