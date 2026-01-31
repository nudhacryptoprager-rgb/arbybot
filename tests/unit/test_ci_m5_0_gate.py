# PATH: tests/unit/test_ci_m5_0_gate.py
"""
Unit tests for M5_0 CI Gate script.

Tests:
- Artifact discovery (nested and flat layouts)
- Schema version validation
- Run mode validation
- Block pinning validation
- Quotes metrics validation
- DEXes active validation
- Price sanity metrics validation
- Reject histogram validation
- Fixture creation in --out-dir
- Latest runDir selection (priority, mtime, artifacts)
- CLI > ENV > auto priority
- --require-real flag

Run: python -m pytest tests/unit/test_ci_m5_0_gate.py -v
"""

import json
import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.ci_m5_0_gate import (
    FIXTURE_BLOCK,
    EXIT_PASS,
    EXIT_FAIL,
    EXIT_ARTIFACTS_MISSING,
    EXIT_FIXTURE_REJECTED,
    find_artifacts,
    find_latest_valid_rundir,
    has_all_artifacts,
    check_schema_version,
    check_run_mode,
    check_block_pinned,
    check_quotes_metrics,
    check_dexes_active,
    check_price_sanity_metrics,
    check_reject_histogram,
    create_fixture_run_dir,
    run_gate,
    get_env_bool,
    get_env_str,
)


class TestEnvHelpers(unittest.TestCase):
    """Test environment variable helper functions."""

    def test_get_env_bool_true_values(self):
        """Test that true-ish values return True."""
        for val in ["1", "true", "True", "TRUE", "yes", "YES", "on", "ON"]:
            with mock.patch.dict(os.environ, {"TEST_VAR": val}):
                self.assertTrue(get_env_bool("TEST_VAR"))

    def test_get_env_bool_false_values(self):
        """Test that false-ish values return False."""
        for val in ["0", "false", "False", "FALSE", "no", "NO", "off", "OFF"]:
            with mock.patch.dict(os.environ, {"TEST_VAR": val}):
                self.assertFalse(get_env_bool("TEST_VAR"))

    def test_get_env_bool_default(self):
        """Test default value when env not set."""
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertFalse(get_env_bool("NONEXISTENT_VAR"))
            self.assertTrue(get_env_bool("NONEXISTENT_VAR", default=True))

    def test_get_env_str_value(self):
        """Test string value retrieval."""
        with mock.patch.dict(os.environ, {"TEST_VAR": "some_value"}):
            self.assertEqual(get_env_str("TEST_VAR"), "some_value")

    def test_get_env_str_empty(self):
        """Test empty string returns default."""
        with mock.patch.dict(os.environ, {"TEST_VAR": ""}):
            self.assertIsNone(get_env_str("TEST_VAR"))
            self.assertEqual(get_env_str("TEST_VAR", "default"), "default")


class TestArtifactDiscovery(unittest.TestCase):
    """Test artifact discovery functions."""

    def test_find_artifacts_nested_layout(self):
        """Test finding artifacts in nested layout (M4 style)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            snapshots = tmp_path / "snapshots"
            reports = tmp_path / "reports"
            snapshots.mkdir()
            reports.mkdir()

            # Create artifacts
            (snapshots / "scan_20260130_120000.json").write_text("{}")
            (reports / "truth_report_20260130_120000.json").write_text("{}")
            (reports / "reject_histogram_20260130_120000.json").write_text("{}")

            artifacts = find_artifacts(tmp_path)

            self.assertIsNotNone(artifacts["scan"])
            self.assertIsNotNone(artifacts["truth_report"])
            self.assertIsNotNone(artifacts["reject_histogram"])

    def test_find_artifacts_flat_layout(self):
        """Test finding artifacts in flat layout."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            # Create artifacts in root
            (tmp_path / "scan_20260130_120000.json").write_text("{}")
            (tmp_path / "truth_report_20260130_120000.json").write_text("{}")
            (tmp_path / "reject_histogram_20260130_120000.json").write_text("{}")

            artifacts = find_artifacts(tmp_path)

            self.assertIsNotNone(artifacts["scan"])
            self.assertIsNotNone(artifacts["truth_report"])
            self.assertIsNotNone(artifacts["reject_histogram"])

    def test_find_artifacts_missing(self):
        """Test handling missing artifacts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            artifacts = find_artifacts(tmp_path)

            self.assertIsNone(artifacts["scan"])
            self.assertIsNone(artifacts["truth_report"])
            self.assertIsNone(artifacts["reject_histogram"])

    def test_has_all_artifacts_true(self):
        """Test has_all_artifacts returns True when all present."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            (tmp_path / "scan_001.json").write_text("{}")
            (tmp_path / "truth_report_001.json").write_text("{}")
            (tmp_path / "reject_histogram_001.json").write_text("{}")

            self.assertTrue(has_all_artifacts(tmp_path))

    def test_has_all_artifacts_false(self):
        """Test has_all_artifacts returns False when some missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            (tmp_path / "scan_001.json").write_text("{}")
            # Missing truth_report and histogram

            self.assertFalse(has_all_artifacts(tmp_path))


class TestLatestRunDirSelection(unittest.TestCase):
    """Test latest runDir selection logic."""

    def _create_valid_rundir(self, base_dir: Path, name: str) -> Path:
        """Helper to create a valid runDir with all 3 artifacts."""
        run_dir = base_dir / name
        snapshots = run_dir / "snapshots"
        reports = run_dir / "reports"
        snapshots.mkdir(parents=True)
        reports.mkdir()
        (snapshots / "scan_001.json").write_text("{}")
        (reports / "truth_report_001.json").write_text("{}")
        (reports / "reject_histogram_001.json").write_text("{}")
        return run_dir

    def test_find_latest_no_dirs(self):
        """Test returns None when no directories exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            self.assertIsNone(find_latest_valid_rundir(tmp_path))

    def test_find_latest_no_valid_dirs(self):
        """Test returns None when dirs exist but none have all artifacts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            (tmp_path / "invalid_dir").mkdir()
            (tmp_path / "invalid_dir" / "scan_001.json").write_text("{}")
            # Missing truth_report and histogram

            self.assertIsNone(find_latest_valid_rundir(tmp_path))

    def test_find_latest_single_valid(self):
        """Test finds single valid runDir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            valid_dir = self._create_valid_rundir(tmp_path, "run_scan_001")

            result = find_latest_valid_rundir(tmp_path)
            self.assertEqual(result, valid_dir)

    def test_find_latest_prioritizes_m5_gate_prefix(self):
        """Test prioritizes ci_m5_0_gate_ prefix over others."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            # Create older but higher priority
            m5_dir = self._create_valid_rundir(tmp_path, "ci_m5_0_gate_001")
            time.sleep(0.1)

            # Create newer but lower priority
            other_dir = self._create_valid_rundir(tmp_path, "other_run_002")

            result = find_latest_valid_rundir(tmp_path)
            self.assertEqual(result, m5_dir)

    def test_find_latest_uses_mtime_within_same_priority(self):
        """Test uses mtime when priority is equal."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            # Create older
            old_dir = self._create_valid_rundir(tmp_path, "run_scan_001")
            time.sleep(0.1)

            # Create newer
            new_dir = self._create_valid_rundir(tmp_path, "run_scan_002")

            result = find_latest_valid_rundir(tmp_path)
            self.assertEqual(result, new_dir)

    def test_find_latest_ignores_invalid_dirs(self):
        """Test ignores directories without all 3 artifacts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            # Create invalid (newer)
            invalid_dir = tmp_path / "ci_m5_0_gate_new"
            invalid_dir.mkdir()
            (invalid_dir / "scan_001.json").write_text("{}")
            # Missing other artifacts
            time.sleep(0.1)

            # Create valid (older)
            valid_dir = self._create_valid_rundir(tmp_path, "run_scan_old")

            result = find_latest_valid_rundir(tmp_path)
            self.assertEqual(result, valid_dir)


class TestSchemaVersion(unittest.TestCase):
    """Test schema version validation."""

    def test_valid_schema_version(self):
        """Test valid schema version."""
        data = {"schema_version": "3.2.0"}
        passed, errors = check_schema_version(data)
        self.assertTrue(passed)
        self.assertEqual(len(errors), 0)

    def test_missing_schema_version(self):
        """Test missing schema version."""
        data = {}
        passed, errors = check_schema_version(data)
        self.assertFalse(passed)
        self.assertIn("Missing: schema_version", errors)

    def test_invalid_schema_format(self):
        """Test invalid schema format."""
        data = {"schema_version": "invalid"}
        passed, errors = check_schema_version(data)
        self.assertFalse(passed)
        self.assertTrue(any("invalid format" in e for e in errors))


class TestRunMode(unittest.TestCase):
    """Test run mode validation."""

    def test_valid_run_mode_both(self):
        """Test valid run mode in both artifacts."""
        scan = {"run_mode": "REGISTRY_REAL"}
        truth = {"run_mode": "REGISTRY_REAL"}
        passed, errors = check_run_mode(scan, truth)
        self.assertTrue(passed)

    def test_run_mode_mismatch(self):
        """Test run mode mismatch."""
        scan = {"run_mode": "SMOKE_SIMULATOR"}
        truth = {"run_mode": "REGISTRY_REAL"}
        passed, errors = check_run_mode(scan, truth)
        self.assertFalse(passed)
        self.assertTrue(any("mismatch" in e for e in errors))


class TestBlockPinned(unittest.TestCase):
    """Test block pinning validation."""

    def test_valid_block_real_mode(self):
        """Test valid block in REAL mode."""
        data = {"run_mode": "REGISTRY_REAL", "current_block": 275000000}
        passed, errors = check_block_pinned(data)
        self.assertTrue(passed)

    def test_zero_block_real_mode(self):
        """Test zero block in REAL mode (should fail)."""
        data = {"run_mode": "REGISTRY_REAL", "current_block": 0}
        passed, errors = check_block_pinned(data)
        self.assertFalse(passed)

    def test_any_block_smoke_mode(self):
        """Test any block in SMOKE mode (always passes)."""
        data = {"run_mode": "SMOKE_SIMULATOR", "current_block": 0}
        passed, errors = check_block_pinned(data)
        self.assertTrue(passed)


class TestQuotesMetrics(unittest.TestCase):
    """Test quotes metrics validation."""

    def test_valid_quotes(self):
        """Test valid quotes metrics."""
        data = {"stats": {"quotes_total": 4, "quotes_fetched": 4, "gates_passed": 2}}
        passed, errors = check_quotes_metrics(data)
        self.assertTrue(passed)

    def test_invariant_violation_fetched_gt_total(self):
        """Test invariant: fetched > total."""
        data = {"stats": {"quotes_total": 2, "quotes_fetched": 4, "gates_passed": 1}}
        passed, errors = check_quotes_metrics(data)
        self.assertFalse(passed)
        self.assertTrue(any("INVARIANT" in e for e in errors))


class TestRequireReal(unittest.TestCase):
    """Test --require-real flag."""

    def test_fixture_rejected_when_require_real(self):
        """Test that fixture data is rejected when require_real=True."""
        fixture_dir = create_fixture_run_dir()

        try:
            exit_code = run_gate(fixture_dir, is_fixture=True, require_real=True)
            self.assertEqual(exit_code, EXIT_FIXTURE_REJECTED)
        finally:
            shutil.rmtree(fixture_dir, ignore_errors=True)

    def test_fixture_accepted_when_not_require_real(self):
        """Test that fixture data is accepted when require_real=False."""
        fixture_dir = create_fixture_run_dir()

        try:
            exit_code = run_gate(fixture_dir, is_fixture=True, require_real=False)
            self.assertEqual(exit_code, EXIT_PASS)
        finally:
            shutil.rmtree(fixture_dir, ignore_errors=True)


class TestFixtureCreation(unittest.TestCase):
    """Test fixture creation."""

    def test_create_fixture_default_location(self):
        """Test fixture creation creates valid structure."""
        fixture_dir = create_fixture_run_dir()

        try:
            # Check structure
            self.assertTrue((fixture_dir / "snapshots").exists())
            self.assertTrue((fixture_dir / "reports").exists())

            # Check artifacts exist
            artifacts = find_artifacts(fixture_dir)
            self.assertIsNotNone(artifacts["scan"])
            self.assertIsNotNone(artifacts["truth_report"])
            self.assertIsNotNone(artifacts["reject_histogram"])

            # Check scan data is valid
            with open(artifacts["scan"]) as f:
                scan_data = json.load(f)
            self.assertEqual(scan_data["run_mode"], "REGISTRY_REAL")
            self.assertEqual(scan_data["current_block"], FIXTURE_BLOCK)
            self.assertTrue(scan_data.get("_fixture", False))

        finally:
            shutil.rmtree(fixture_dir, ignore_errors=True)

    def test_create_fixture_custom_out_dir(self):
        """Test fixture creation in custom --out-dir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out_dir = Path(tmpdir) / "my_custom_fixture"
            fixture_dir = create_fixture_run_dir(out_dir=out_dir)

            self.assertEqual(fixture_dir, out_dir)
            self.assertTrue((fixture_dir / "snapshots").exists())
            self.assertTrue((fixture_dir / "reports").exists())
            self.assertTrue(has_all_artifacts(fixture_dir))


class TestIntegration(unittest.TestCase):
    """Integration tests using fixture."""

    def test_full_gate_with_fixture(self):
        """Test full gate run with fixture."""
        fixture_dir = create_fixture_run_dir()

        try:
            exit_code = run_gate(fixture_dir, is_fixture=True)
            self.assertEqual(exit_code, EXIT_PASS)
        finally:
            shutil.rmtree(fixture_dir, ignore_errors=True)

    def test_gate_returns_artifacts_missing_for_empty_dir(self):
        """Test gate returns EXIT_ARTIFACTS_MISSING for empty directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            exit_code = run_gate(Path(tmpdir))
            self.assertEqual(exit_code, EXIT_ARTIFACTS_MISSING)


if __name__ == "__main__":
    unittest.main()
