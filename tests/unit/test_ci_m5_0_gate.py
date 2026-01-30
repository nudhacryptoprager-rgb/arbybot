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
- Fixture creation

Run: python -m pytest tests/unit/test_ci_m5_0_gate.py -v
"""

import json
import tempfile
import unittest
from pathlib import Path

# Import gate functions directly (no heavy deps)
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.ci_m5_0_gate import (
    find_artifacts,
    check_schema_version,
    check_run_mode,
    check_block_pinned,
    check_quotes_metrics,
    check_dexes_active,
    check_price_sanity_metrics,
    check_reject_histogram,
    create_fixture_run_dir,
    VALID_SCHEMA_PATTERN,
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

    def test_create_fixture(self):
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
            self.assertGreater(scan_data["current_block"], 0)

            # Check truth report is valid
            with open(artifacts["truth_report"]) as f:
                truth = json.load(f)
            self.assertEqual(truth["schema_version"], "3.2.0")

        finally:
            # Cleanup
            import shutil

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
            import shutil

            shutil.rmtree(fixture_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
