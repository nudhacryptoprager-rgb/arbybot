# PATH: tests/unit/test_ci_m5_0_gate.py
"""
Unit tests for ci_m5_0_gate.py v2.0.0.

TESTS:
1. --offline mode creates fixture in data/runs, ignores ENV
2. --online mode creates runDir and calls runner (mocked)
3. --offline and --online are mutually exclusive
4. CLI > ENV priority (but --offline/--online ignore ENV)
5. Artifact validation works correctly
"""

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
    validate_run_mode,
    validate_health_metrics,
    validate_price_sanity_metrics,
    get_run_dir_candidates,
    main,
    __version__,
)


class TestFixtureGeneration(unittest.TestCase):
    """Test fixture artifact generation."""

    def test_generate_fixture_creates_all_artifacts(self):
        """Test that fixture generation creates all 3 artifacts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "test_run"
            output_dir.mkdir()
            
            artifacts = generate_fixture_artifacts(output_dir, "20260131_120000")
            
            self.assertIn("scan", artifacts)
            self.assertIn("truth_report", artifacts)
            self.assertIn("reject_histogram", artifacts)
            
            for name, path in artifacts.items():
                self.assertTrue(path.exists(), f"{name} should exist")

    def test_fixture_artifacts_are_valid_json(self):
        """Test that fixture artifacts are valid JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "test_run"
            output_dir.mkdir()
            
            artifacts = generate_fixture_artifacts(output_dir, "20260131_120000")
            
            for name, path in artifacts.items():
                with open(path) as f:
                    data = json.load(f)
                
                self.assertIn("schema_version", data)
                self.assertIn("run_mode", data)
                self.assertEqual(data["run_mode"], "FIXTURE_OFFLINE")

    def test_fixture_has_correct_m5_0_structure(self):
        """Test that fixture has correct M5_0 structure."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "test_run"
            output_dir.mkdir()
            
            artifacts = generate_fixture_artifacts(output_dir, "20260131_120000")
            
            # Truth report must have health metrics
            with open(artifacts["truth_report"]) as f:
                truth = json.load(f)
            
            self.assertIn("health", truth)
            self.assertIn("quotes_total", truth["health"])
            self.assertIn("price_sanity_passed", truth["health"])
            
            # Reject histogram must have M5_0 fields
            with open(artifacts["reject_histogram"]) as f:
                reject = json.load(f)
            
            self.assertIn("rejects", reject)
            if reject["rejects"]:
                r = reject["rejects"][0]
                self.assertIn("inversion_applied", r)
                self.assertEqual(r["inversion_applied"], False)


class TestArtifactDiscovery(unittest.TestCase):
    """Test artifact discovery."""

    def test_discover_finds_all_artifacts(self):
        """Test discovery finds all artifacts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "test_run"
            output_dir.mkdir()
            
            generate_fixture_artifacts(output_dir, "20260131_120000")
            
            artifacts = discover_artifacts(output_dir)
            
            self.assertIsNotNone(artifacts["scan"])
            self.assertIsNotNone(artifacts["truth_report"])
            self.assertIsNotNone(artifacts["reject_histogram"])

    def test_discover_returns_none_for_missing(self):
        """Test discovery returns None for missing artifacts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir) / "empty_run"
            output_dir.mkdir()
            (output_dir / "reports").mkdir()
            
            artifacts = discover_artifacts(output_dir)
            
            self.assertIsNone(artifacts["scan"])
            self.assertIsNone(artifacts["truth_report"])
            self.assertIsNone(artifacts["reject_histogram"])


class TestValidation(unittest.TestCase):
    """Test artifact validation."""

    def test_validate_schema_version_valid(self):
        """Test schema version validation with valid version."""
        data = {"schema_version": "3.2.0"}
        ok, msg = validate_schema_version(data)
        self.assertTrue(ok)

    def test_validate_schema_version_invalid(self):
        """Test schema version validation with invalid version."""
        data = {"schema_version": "invalid"}
        ok, msg = validate_schema_version(data)
        self.assertFalse(ok)

    def test_validate_schema_version_missing(self):
        """Test schema version validation with missing version."""
        data = {}
        ok, msg = validate_schema_version(data)
        self.assertFalse(ok)

    def test_validate_run_mode_valid(self):
        """Test run mode validation."""
        data = {"run_mode": "REGISTRY_REAL"}
        ok, msg = validate_run_mode(data)
        self.assertTrue(ok)

    def test_validate_health_metrics_valid(self):
        """Test health metrics validation."""
        data = {
            "health": {
                "quotes_total": 10,
                "quotes_fetched": 10,
                "dexes_active": 2,
            }
        }
        ok, msg = validate_health_metrics(data)
        self.assertTrue(ok)

    def test_validate_health_metrics_zero_quotes(self):
        """Test health metrics validation with zero quotes."""
        data = {
            "health": {
                "quotes_total": 0,
                "quotes_fetched": 0,
                "dexes_active": 0,
            }
        }
        ok, msg = validate_health_metrics(data)
        self.assertFalse(ok)

    def test_validate_price_sanity_metrics_valid(self):
        """Test price sanity metrics validation."""
        data = {
            "health": {
                "price_sanity_passed": 9,
                "price_sanity_failed": 1,
            }
        }
        ok, msg = validate_price_sanity_metrics(data)
        self.assertTrue(ok)


class TestModeExclusion(unittest.TestCase):
    """Test that --offline and --online are mutually exclusive."""

    def test_offline_and_online_mutually_exclusive(self):
        """Test argparse raises error when both modes used."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('sys.argv', ['ci_m5_0_gate.py', '--offline', '--online']):
                with self.assertRaises(SystemExit) as cm:
                    main()
                self.assertEqual(cm.exception.code, 2)


class TestOfflineMode(unittest.TestCase):
    """Test --offline mode."""

    def test_offline_creates_fixture_in_output_root(self):
        """Test --offline creates fixture in specified output root."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir)
            
            with patch('sys.argv', [
                'ci_m5_0_gate.py', 
                '--offline', 
                '--output-root', str(output_root)
            ]):
                result = main()
            
            self.assertEqual(result, 0)
            
            dirs = list(output_root.glob("ci_m5_0_gate_offline_*"))
            self.assertEqual(len(dirs), 1)
            
            artifacts = discover_artifacts(dirs[0])
            self.assertIsNotNone(artifacts["scan"])
            self.assertIsNotNone(artifacts["truth_report"])
            self.assertIsNotNone(artifacts["reject_histogram"])

    def test_offline_ignores_env(self):
        """Test --offline ignores ARBY_RUN_DIR and ARBY_REQUIRE_REAL."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir)
            
            env_backup = os.environ.copy()
            os.environ["ARBY_RUN_DIR"] = "/nonexistent/path"
            os.environ["ARBY_REQUIRE_REAL"] = "1"
            
            try:
                with patch('sys.argv', [
                    'ci_m5_0_gate.py', 
                    '--offline', 
                    '--output-root', str(output_root)
                ]):
                    result = main()
                
                self.assertEqual(result, 0)
            finally:
                os.environ.clear()
                os.environ.update(env_backup)


class TestOnlineMode(unittest.TestCase):
    """Test --online mode."""

    def test_online_calls_run_scan_real(self):
        """Test --online calls strategy.jobs.run_scan_real."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir)
            
            with patch('subprocess.run') as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                
                with patch('sys.argv', [
                    'ci_m5_0_gate.py', 
                    '--online', 
                    '--output-root', str(output_root),
                    '--config', 'config/real_minimal.yaml'
                ]):
                    result = main()
                
                mock_run.assert_called_once()
                call_args = mock_run.call_args[0][0]
                self.assertIn("strategy.jobs.run_scan_real", " ".join(call_args))

    def test_online_ignores_arby_run_dir(self):
        """Test --online ignores ARBY_RUN_DIR."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir)
            
            env_backup = os.environ.copy()
            os.environ["ARBY_RUN_DIR"] = "/some/other/path"
            
            try:
                with patch('subprocess.run') as mock_run:
                    mock_run.return_value = MagicMock(returncode=0)
                    
                    with patch('sys.argv', [
                        'ci_m5_0_gate.py', 
                        '--online', 
                        '--output-root', str(output_root)
                    ]):
                        main()
                    
                    call_args = mock_run.call_args[0][0]
                    output_dir_arg = None
                    for i, arg in enumerate(call_args):
                        if arg == "--output-dir" and i + 1 < len(call_args):
                            output_dir_arg = call_args[i + 1]
                            break
                    
                    self.assertIsNotNone(output_dir_arg)
                    self.assertIn(str(output_root), output_dir_arg)
                    self.assertNotIn("/some/other/path", output_dir_arg)
            finally:
                os.environ.clear()
                os.environ.update(env_backup)


class TestLegacyMode(unittest.TestCase):
    """Test legacy mode (no --offline or --online)."""

    def test_legacy_uses_run_dir_arg(self):
        """Test legacy mode uses --run-dir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "test_run"
            run_dir.mkdir()
            
            generate_fixture_artifacts(run_dir, "20260131_120000")
            
            with patch('sys.argv', [
                'ci_m5_0_gate.py', 
                '--run-dir', str(run_dir)
            ]):
                result = main()
            
            self.assertEqual(result, 0)

    def test_legacy_uses_env_when_no_run_dir(self):
        """Test legacy mode uses ARBY_RUN_DIR when no --run-dir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "test_run"
            run_dir.mkdir()
            
            generate_fixture_artifacts(run_dir, "20260131_120000")
            
            env_backup = os.environ.copy()
            os.environ["ARBY_RUN_DIR"] = str(run_dir)
            
            try:
                with patch('sys.argv', ['ci_m5_0_gate.py']):
                    result = main()
                
                self.assertEqual(result, 0)
            finally:
                os.environ.clear()
                os.environ.update(env_backup)


class TestRequireReal(unittest.TestCase):
    """Test --require-real flag."""

    def test_require_real_rejects_fixture(self):
        """Test --require-real rejects fixture artifacts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "test_run"
            run_dir.mkdir()
            
            generate_fixture_artifacts(run_dir, "20260131_120000")
            
            with patch('sys.argv', [
                'ci_m5_0_gate.py', 
                '--run-dir', str(run_dir),
                '--require-real'
            ]):
                result = main()
            
            self.assertEqual(result, 1)


class TestVersion(unittest.TestCase):
    """Test version."""

    def test_version_is_2_0_0(self):
        """Test version is 2.0.0."""
        self.assertEqual(__version__, "2.0.0")


if __name__ == "__main__":
    unittest.main()
