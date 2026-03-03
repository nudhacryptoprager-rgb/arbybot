# PATH: tests/unit/test_artifact_completeness.py
"""Tests for runDir artifact completeness (v3.2.7).

Validates that runDirs contain all required artifacts regardless of status.
"""

import unittest
import tempfile
import json
from pathlib import Path


class TestArtifactCompleteness(unittest.TestCase):
    """Test that runDirs have complete artifact sets."""
    
    REQUIRED_ARTIFACTS = [
        "scan_*.json",
        "truth_report_*.json",
        "reject_histogram_*.json",
    ]
    
    def _create_rundir_with_artifacts(self, artifacts: list[str]) -> Path:
        """Create a temporary runDir with specified artifacts."""
        tmp = Path(tempfile.mkdtemp())
        reports_dir = tmp / "reports"
        reports_dir.mkdir(parents=True)
        
        for name in artifacts:
            (reports_dir / name).write_text("{}")
        
        return tmp
    
    def test_complete_rundir_passes(self):
        """A runDir with all required artifacts passes completeness check."""
        run_dir = self._create_rundir_with_artifacts([
            "scan_20260303_100000.json",
            "truth_report_20260303_100000.json",
            "reject_histogram_20260303_100000.json",
        ])
        
        reports_dir = run_dir / "reports"
        
        # All required patterns should match
        self.assertTrue(list(reports_dir.glob("scan_*.json")))
        self.assertTrue(list(reports_dir.glob("truth_report_*.json")))
        self.assertTrue(list(reports_dir.glob("reject_histogram_*.json")))
    
    def test_missing_scan_fails(self):
        """A runDir missing scan_*.json fails completeness check."""
        run_dir = self._create_rundir_with_artifacts([
            "truth_report_20260303_100000.json",
            "reject_histogram_20260303_100000.json",
        ])
        
        reports_dir = run_dir / "reports"
        
        # scan should be missing
        self.assertFalse(list(reports_dir.glob("scan_*.json")))
    
    def test_missing_truth_report_fails(self):
        """A runDir missing truth_report_*.json fails completeness check."""
        run_dir = self._create_rundir_with_artifacts([
            "scan_20260303_100000.json",
            "reject_histogram_20260303_100000.json",
        ])
        
        reports_dir = run_dir / "reports"
        
        # truth_report should be missing
        self.assertFalse(list(reports_dir.glob("truth_report_*.json")))
    
    def test_missing_reject_histogram_fails(self):
        """A runDir missing reject_histogram_*.json fails completeness check."""
        run_dir = self._create_rundir_with_artifacts([
            "scan_20260303_100000.json",
            "truth_report_20260303_100000.json",
        ])
        
        reports_dir = run_dir / "reports"
        
        # reject_histogram should be missing
        self.assertFalse(list(reports_dir.glob("reject_histogram_*.json")))


def check_rundir_completeness(run_dir: Path) -> tuple[bool, list[str]]:
    """
    Check if a runDir has all required artifacts.
    
    Args:
        run_dir: Path to runDir
        
    Returns:
        Tuple of (is_complete, missing_patterns)
    """
    reports_dir = run_dir / "reports"
    if not reports_dir.exists():
        return False, ["reports/ directory missing"]
    
    required_patterns = [
        "scan_*.json",
        "truth_report_*.json",
        "reject_histogram_*.json",
    ]
    
    missing = []
    for pattern in required_patterns:
        if not list(reports_dir.glob(pattern)):
            missing.append(pattern)
    
    return len(missing) == 0, missing


class TestCheckRunDirCompletenessFunction(unittest.TestCase):
    """Test the check_rundir_completeness helper function."""
    
    def test_complete_returns_true(self):
        """Complete runDir returns (True, [])."""
        tmp = Path(tempfile.mkdtemp())
        reports_dir = tmp / "reports"
        reports_dir.mkdir()
        (reports_dir / "scan_20260303_100000.json").write_text("{}")
        (reports_dir / "truth_report_20260303_100000.json").write_text("{}")
        (reports_dir / "reject_histogram_20260303_100000.json").write_text("{}")
        
        is_complete, missing = check_rundir_completeness(tmp)
        
        self.assertTrue(is_complete)
        self.assertEqual(missing, [])
    
    def test_missing_artifact_returns_false_with_list(self):
        """Incomplete runDir returns (False, [missing_patterns])."""
        tmp = Path(tempfile.mkdtemp())
        reports_dir = tmp / "reports"
        reports_dir.mkdir()
        (reports_dir / "scan_20260303_100000.json").write_text("{}")
        # Missing truth_report and reject_histogram
        
        is_complete, missing = check_rundir_completeness(tmp)
        
        self.assertFalse(is_complete)
        self.assertIn("truth_report_*.json", missing)
        self.assertIn("reject_histogram_*.json", missing)
    
    def test_no_reports_dir_returns_false(self):
        """RunDir without reports/ returns (False, [...])."""
        tmp = Path(tempfile.mkdtemp())
        
        is_complete, missing = check_rundir_completeness(tmp)
        
        self.assertFalse(is_complete)
        self.assertIn("reports/ directory missing", missing)


if __name__ == "__main__":
    unittest.main()
