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

Run: python -m pytest tests/unit/test_ci_m5_0_gate.py -v
"""

import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.ci_m5_0_gate import (
    FIXTURE_BLOCK,
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
)


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

    def test_find_latest_prioritizes_run_scan_prefix(self):
        """Test prioritizes run_scan_ over generic directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)

            # Create lower priority first
            other_dir = self._create_valid_rundir(tmp_path, "some_other_dir")
            time.sleep(0.1)

            # Create higher priority later
            scan_dir = self._create_valid_rundir(tmp_path, "run_scan_001")

            result = find_latest_valid_rundir(tmp_path)
            self.assertEqual(result, scan_dir)

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

    def test_schema_not_string(self):
        """Test schema version not a string."""
        data = {"schema_version": 320}
        passed, errors = check_schema_version(data)
        self.assertFalse(passed)
        self.assertTrue(any("must be string" in e for e in errors))


class TestRunMode(unittest.TestCase):
    """Test run mode validation."""

    def test_valid_run_mode_both(self):
        """Test valid run mode in both artifacts."""
        scan = {"run_mode": "REGISTRY_REAL"}
        truth = {"run_mode": "REGISTRY_REAL"}
        passed, errors = check_run_mode(scan, truth)
        self.assertTrue(passed)
        self.assertEqual(len(errors), 0)

    def test_run_mode_in_stats(self):
        """Test run mode in stats.run_mode."""
        scan = {"stats": {"run_mode": "REGISTRY_REAL"}}
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

    def test_missing_run_mode(self):
        """Test missing run mode."""
        scan = {}
        truth = {}
        passed, errors = check_run_mode(scan, truth)
        self.assertFalse(passed)
        self.assertEqual(len(errors), 2)


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

    def test_fixture_marker_shown(self):
        """Test fixture marker is applied when is_fixture=True."""
        data = {"run_mode": "REGISTRY_REAL", "current_block": FIXTURE_BLOCK}
        # This test just ensures no crash; marker is printed to stdout
        passed, errors = check_block_pinned(data, is_fixture=True)
        self.assertTrue(passed)


class TestQuotesMetrics(unittest.TestCase):
    """Test quotes metrics validation."""

    def test_valid_quotes(self):
        """Test valid quotes metrics."""
        data = {"stats": {"quotes_total": 4, "quotes_fetched": 4, "gates_passed": 2}}
        passed, errors = check_quotes_metrics(data)
        self.assertTrue(passed)

    def test_zero_quotes_total(self):
        """Test zero quotes total (should fail)."""
        data = {"stats": {"quotes_total": 0, "quotes_fetched": 0, "gates_passed": 0}}
        passed, errors = check_quotes_metrics(data)
        self.assertFalse(passed)

    def test_invariant_violation_fetched_gt_total(self):
        """Test invariant: fetched > total."""
        data = {"stats": {"quotes_total": 2, "quotes_fetched": 4, "gates_passed": 1}}
        passed, errors = check_quotes_metrics(data)
        self.assertFalse(passed)
        self.assertTrue(any("INVARIANT" in e for e in errors))

    def test_invariant_violation_passed_gt_fetched(self):
        """Test invariant: passed > fetched."""
        data = {"stats": {"quotes_total": 4, "quotes_fetched": 2, "gates_passed": 4}}
        passed, errors = check_quotes_metrics(data)
        self.assertFalse(passed)
        self.assertTrue(any("INVARIANT" in e for e in errors))


class TestDexesActive(unittest.TestCase):
    """Test DEXes active validation."""

    def test_valid_dexes(self):
        """Test valid dexes active."""
        data = {"stats": {"dexes_active": 2}}
        passed, errors = check_dexes_active(data)
        self.assertTrue(passed)

    def test_zero_dexes(self):
        """Test zero dexes (should fail)."""
        data = {"stats": {"dexes_active": 0}}
        passed, errors = check_dexes_active(data)
        self.assertFalse(passed)


class TestPriceSanityMetrics(unittest.TestCase):
    """Test price sanity metrics validation."""

    def test_valid_price_sanity(self):
        """Test valid price sanity metrics."""
        data = {"stats": {"price_sanity_passed": 2, "price_sanity_failed": 2}}
        passed, errors = check_price_sanity_metrics(data)
        self.assertTrue(passed)

    def test_missing_passed(self):
        """Test missing price_sanity_passed."""
        data = {"stats": {"price_sanity_failed": 2}}
        passed, errors = check_price_sanity_metrics(data)
        self.assertFalse(passed)

    def test_missing_failed(self):
        """Test missing price_sanity_failed."""
        data = {"stats": {"price_sanity_passed": 2}}
        passed, errors = check_price_sanity_metrics(data)
        self.assertFalse(passed)


class TestRejectHistogram(unittest.TestCase):
    """Test reject histogram validation."""

    def test_valid_histogram(self):
        """Test valid histogram."""
        data = {"histogram": {"PRICE_SANITY_FAILED": 2}}
        passed, errors = check_reject_histogram(data)
        self.assertTrue(passed)

    def test_empty_histogram(self):
        """Test empty histogram (should pass - all gates passed)."""
        data = {"histogram": {}}
        passed, errors = check_reject_histogram(data)
        self.assertTrue(passed)

    def test_with_gate_breakdown(self):
        """Test histogram with gate breakdown."""
        data = {
            "histogram": {"PRICE_SANITY_FAILED": 2},
            "gate_breakdown": {"sanity": 2, "revert": 0},
        }
        passed, errors = check_reject_histogram(data)
        self.assertTrue(passed)


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

            # Check truth report is valid
            with open(artifacts["truth_report"]) as f:
                truth = json.load(f)
            self.assertEqual(truth["schema_version"], "3.2.0")
            self.assertTrue(truth.get("_fixture", False))

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

    def test_fixture_has_fixture_marker(self):
        """Test fixture data has _fixture: true marker."""
        fixture_dir = create_fixture_run_dir()

        try:
            artifacts = find_artifacts(fixture_dir)

            with open(artifacts["scan"]) as f:
                self.assertTrue(json.load(f).get("_fixture", False))

            with open(artifacts["truth_report"]) as f:
                self.assertTrue(json.load(f).get("_fixture", False))

            with open(artifacts["reject_histogram"]) as f:
                self.assertTrue(json.load(f).get("_fixture", False))

        finally:
            shutil.rmtree(fixture_dir, ignore_errors=True)


class TestIntegration(unittest.TestCase):
    """Integration tests using fixture."""

    def test_full_gate_with_fixture(self):
        """Test full gate run with fixture."""
        fixture_dir = create_fixture_run_dir()

        try:
            artifacts = find_artifacts(fixture_dir)

            # All artifacts present
            self.assertIsNotNone(artifacts["scan"])
            self.assertIsNotNone(artifacts["truth_report"])
            self.assertIsNotNone(artifacts["reject_histogram"])

            # Load and validate each
            with open(artifacts["scan"]) as f:
                scan = json.load(f)
            with open(artifacts["truth_report"]) as f:
                truth = json.load(f)
            with open(artifacts["reject_histogram"]) as f:
                histogram = json.load(f)

            # All checks should pass
            self.assertTrue(check_schema_version(truth)[0])
            self.assertTrue(check_run_mode(scan, truth)[0])
            self.assertTrue(check_block_pinned(scan)[0])
            self.assertTrue(check_quotes_metrics(scan)[0])
            self.assertTrue(check_dexes_active(scan)[0])
            self.assertTrue(check_price_sanity_metrics(scan)[0])
            self.assertTrue(check_reject_histogram(histogram)[0])

        finally:
            shutil.rmtree(fixture_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
