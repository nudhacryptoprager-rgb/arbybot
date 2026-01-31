# PATH: tests/unit/test_ci_m5_0_gate.py
"""
Unit tests for ci_m5_0_gate.py v2.0.0.

KEY TESTS:
1. --offline + ENV set → still offline (IGNORES ALL ENV)
2. --online + ENV set → still online (IGNORES ARBY_RUN_DIR)
3. --offline and --online together → argparse error
4. CLI > ENV priority always
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
    validate_health_metrics,
    main,
    __version__,
)


class TestVersion(unittest.TestCase):
    """Test version."""
    
    def test_version_is_2_0_0(self):
        self.assertEqual(__version__, "2.0.0")


class TestModeExclusion(unittest.TestCase):
    """Test --offline and --online are mutually exclusive."""

    def test_offline_and_online_together_error(self):
        """--offline + --online → argparse error."""
        with patch('sys.argv', ['ci_m5_0_gate.py', '--offline', '--online']):
            with self.assertRaises(SystemExit) as cm:
                main()
            self.assertEqual(cm.exception.code, 2)


class TestOfflineModeIgnoresEnv(unittest.TestCase):
    """Test --offline ignores ALL ENV."""

    def test_offline_ignores_arby_run_dir(self):
        """--offline + ARBY_RUN_DIR set → still creates offline dir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir)
            
            env_backup = os.environ.copy()
            os.environ["ARBY_RUN_DIR"] = "/nonexistent/should/be/ignored"
            
            try:
                with patch('sys.argv', [
                    'ci_m5_0_gate.py', '--offline',
                    '--output-root', str(output_root)
                ]):
                    result = main()
                
                # Should PASS (ignores invalid ENV)
                self.assertEqual(result, 0)
                
                # Should create ci_m5_0_gate_offline_* dir
                dirs = list(output_root.glob("ci_m5_0_gate_offline_*"))
                self.assertEqual(len(dirs), 1)
            finally:
                os.environ.clear()
                os.environ.update(env_backup)

    def test_offline_ignores_arby_require_real(self):
        """--offline + ARBY_REQUIRE_REAL=1 → still PASS with fixture."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir)
            
            env_backup = os.environ.copy()
            os.environ["ARBY_REQUIRE_REAL"] = "1"
            
            try:
                with patch('sys.argv', [
                    'ci_m5_0_gate.py', '--offline',
                    '--output-root', str(output_root)
                ]):
                    result = main()
                
                # Should PASS (ignores ARBY_REQUIRE_REAL)
                self.assertEqual(result, 0)
            finally:
                os.environ.clear()
                os.environ.update(env_backup)


class TestOnlineModeIgnoresEnv(unittest.TestCase):
    """Test --online ignores ARBY_RUN_DIR."""

    def test_online_ignores_arby_run_dir(self):
        """--online + ARBY_RUN_DIR set → creates new runDir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir)
            
            env_backup = os.environ.copy()
            os.environ["ARBY_RUN_DIR"] = "/some/other/path"
            
            try:
                with patch('subprocess.run') as mock_run:
                    mock_run.return_value = MagicMock(returncode=0)
                    
                    with patch('sys.argv', [
                        'ci_m5_0_gate.py', '--online',
                        '--output-root', str(output_root)
                    ]):
                        main()
                    
                    # Verify subprocess called with output_root, NOT ARBY_RUN_DIR
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

    def test_online_calls_run_scan_real(self):
        """--online calls strategy.jobs.run_scan_real."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir)
            
            with patch('subprocess.run') as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                
                with patch('sys.argv', [
                    'ci_m5_0_gate.py', '--online',
                    '--output-root', str(output_root),
                    '--config', 'config/test.yaml'
                ]):
                    main()
                
                mock_run.assert_called_once()
                call_args = mock_run.call_args[0][0]
                self.assertIn("strategy.jobs.run_scan_real", " ".join(call_args))
                self.assertIn("--config", call_args)


class TestFixtureGeneration(unittest.TestCase):
    """Test fixture artifact generation."""

    def test_generate_creates_all_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            artifacts = generate_fixture_artifacts(output_dir, "20260131_120000")
            
            self.assertIn("scan", artifacts)
            self.assertIn("truth_report", artifacts)
            self.assertIn("reject_histogram", artifacts)
            
            for name, path in artifacts.items():
                self.assertTrue(path.exists())

    def test_fixture_has_fixture_offline_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            artifacts = generate_fixture_artifacts(output_dir, "20260131_120000")
            
            with open(artifacts["truth_report"]) as f:
                data = json.load(f)
            
            self.assertEqual(data["run_mode"], "FIXTURE_OFFLINE")

    def test_fixture_has_execution_disabled(self):
        """Fixture uses EXECUTION_DISABLED (not _M4)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            artifacts = generate_fixture_artifacts(output_dir, "20260131_120000")
            
            with open(artifacts["truth_report"]) as f:
                data = json.load(f)
            
            self.assertEqual(data["execution_blocker"], "EXECUTION_DISABLED")
            self.assertNotIn("M4", data["execution_blocker"])

    def test_fixture_has_m5_0_fields(self):
        """Fixture has inversion_applied, suspect_quote fields."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            artifacts = generate_fixture_artifacts(output_dir, "20260131_120000")
            
            with open(artifacts["reject_histogram"]) as f:
                data = json.load(f)
            
            if data["rejects"]:
                r = data["rejects"][0]
                self.assertIn("inversion_applied", r)
                self.assertEqual(r["inversion_applied"], False)
                self.assertIn("suspect_quote", r)


class TestValidation(unittest.TestCase):
    """Test artifact validation."""

    def test_validate_schema_version_valid(self):
        data = {"schema_version": "3.2.0"}
        ok, msg = validate_schema_version(data)
        self.assertTrue(ok)

    def test_validate_schema_version_invalid(self):
        data = {"schema_version": "invalid"}
        ok, msg = validate_schema_version(data)
        self.assertFalse(ok)

    def test_validate_health_metrics_valid(self):
        data = {"health": {"quotes_total": 10, "quotes_fetched": 10, "dexes_active": 2}}
        ok, msg = validate_health_metrics(data)
        self.assertTrue(ok)

    def test_validate_health_metrics_zero(self):
        data = {"health": {"quotes_total": 0, "quotes_fetched": 0, "dexes_active": 0}}
        ok, msg = validate_health_metrics(data)
        self.assertFalse(ok)


class TestRequireReal(unittest.TestCase):
    """Test --require-real flag."""

    def test_require_real_rejects_fixture(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            generate_fixture_artifacts(run_dir, "20260131_120000")
            
            with patch('sys.argv', [
                'ci_m5_0_gate.py', '--run-dir', str(run_dir), '--require-real'
            ]):
                result = main()
            
            self.assertEqual(result, 1)


class TestAdvancedMode(unittest.TestCase):
    """Test advanced/legacy mode."""

    def test_advanced_uses_run_dir_arg(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            generate_fixture_artifacts(run_dir, "20260131_120000")
            
            with patch('sys.argv', ['ci_m5_0_gate.py', '--run-dir', str(run_dir)]):
                result = main()
            
            self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
