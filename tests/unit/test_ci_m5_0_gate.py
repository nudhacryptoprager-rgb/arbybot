# PATH: tests/unit/test_ci_m5_0_gate.py
"""Unit tests for ci_m5_0_gate.py v2.0.0."""

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
    validate_artifacts,
    main,
    __version__,
)


class TestVersion(unittest.TestCase):
    def test_version_is_2_0_0(self):
        self.assertEqual(__version__, "2.0.0")


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
                dirs = list(output_root.glob("ci_m5_0_gate_offline_*"))
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

    def test_fixture_has_execution_disabled(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            artifacts = generate_fixture_artifacts(Path(tmpdir), "20260201_120000")
            
            with open(artifacts["truth_report"]) as f:
                data = json.load(f)
            
            self.assertEqual(data["execution_blocker"], "EXECUTION_DISABLED")


class TestRequireReal(unittest.TestCase):
    def test_require_real_rejects_fixture(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            generate_fixture_artifacts(run_dir, "20260201_120000")
            
            with patch('sys.argv', ['ci_m5_0_gate.py', '--run-dir', str(run_dir), '--require-real']):
                result = main()
            
            self.assertEqual(result, 1)


class TestAdvancedMode(unittest.TestCase):
    def test_advanced_uses_run_dir_arg(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            generate_fixture_artifacts(run_dir, "20260201_120000")
            
            with patch('sys.argv', ['ci_m5_0_gate.py', '--run-dir', str(run_dir)]):
                result = main()
            
            self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
