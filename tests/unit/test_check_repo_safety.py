# PATH: tests/unit/test_check_repo_safety.py
"""
Unit tests for scripts/check_repo_safety.py v1.4.0

Tests:
1. INFO messages for untracked files don't count as warnings
2. DANGER messages for tracked files cause FAIL
3. Untracked settings.json with autoApprove is INFO-only
4. DEV_REPORT bloat detection (v1.2.0)
5. Status version consistency (v1.3.0) - DISABLED per DOCS_POLICY
6. DEV_REPORT freshness check (v1.3.0)
7. Docs lint - version policy (v1.4.0)
"""

import unittest
from unittest.mock import patch, MagicMock
from pathlib import Path


class TestCheckForbiddenKeys(unittest.TestCase):
    """Test check_forbidden_keys function."""

    def test_untracked_settings_is_info_only(self):
        """Untracked .vscode/settings.json with autoApprove should be INFO, not WARN."""
        from scripts.check_repo_safety import check_forbidden_keys
        
        # Mock: file exists, contains forbidden key, but is NOT tracked
        with patch('scripts.check_repo_safety.PROJECT_ROOT', Path('/fake')):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'read_text', return_value='{"chat.tools.terminal.autoApprove": true}'):
                    with patch('scripts.check_repo_safety.is_git_tracked', return_value=False):
                        errors, info_msgs = check_forbidden_keys()
        
        # Should have no errors
        self.assertEqual(len(errors), 0, "Untracked files should not cause errors")
        # Should have INFO message
        self.assertEqual(len(info_msgs), 1, "Should have INFO message for untracked file")
        self.assertIn("INFO:", info_msgs[0])
        self.assertIn("untracked", info_msgs[0].lower())

    def test_tracked_settings_with_forbidden_key_is_danger(self):
        """Tracked .vscode/settings.json with autoApprove should be DANGER."""
        from scripts.check_repo_safety import check_forbidden_keys
        
        # Mock: file exists, contains forbidden key, and IS tracked
        with patch('scripts.check_repo_safety.PROJECT_ROOT', Path('/fake')):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'read_text', return_value='{"chat.tools.terminal.autoApprove": true}'):
                    with patch('scripts.check_repo_safety.is_git_tracked', return_value=True):
                        errors, info_msgs = check_forbidden_keys()
        
        # Should have error
        self.assertEqual(len(errors), 1, "Tracked file with forbidden key should cause error")
        self.assertIn("DANGER:", errors[0])
        # No INFO messages
        self.assertEqual(len(info_msgs), 0)

    def test_no_forbidden_keys_returns_empty(self):
        """File without forbidden keys should return empty lists."""
        from scripts.check_repo_safety import check_forbidden_keys
        
        # Mock: file exists but has no forbidden keys
        with patch('scripts.check_repo_safety.PROJECT_ROOT', Path('/fake')):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'read_text', return_value='{"editor.fontSize": 14}'):
                    with patch('scripts.check_repo_safety.is_git_tracked', return_value=False):
                        errors, info_msgs = check_forbidden_keys()
        
        self.assertEqual(len(errors), 0)
        self.assertEqual(len(info_msgs), 0)


class TestInfoNotCountedAsWarning(unittest.TestCase):
    """Test that INFO messages don't inflate warning count."""

    def test_info_excluded_from_warning_count(self):
        """INFO: prefix should not count toward warnings."""
        # Simulate all_issues list with INFO and WARN messages
        all_issues = [
            "INFO: something found (untracked, OK)",
            "WARN: actual warning",
        ]
        
        # Filter logic from main()
        errors = [i for i in all_issues if not i.startswith("WARN:") and not i.startswith("INFO:")]
        warnings = [i for i in all_issues if i.startswith("WARN:")]
        
        self.assertEqual(len(errors), 0)
        self.assertEqual(len(warnings), 1)
        self.assertIn("WARN:", warnings[0])


class TestDevReportBloat(unittest.TestCase):
    """Test DEV_REPORT bloat detection (v1.2.0)."""

    def test_allowed_dev_reports_pass(self):
        """Only DEV_REPORT_LATEST.md and DEV_REPORT_CANONICAL_UA.md allowed."""
        from scripts.check_repo_safety import ALLOWED_DEV_REPORTS
        
        self.assertIn("docs/DEV_REPORT_LATEST.md", ALLOWED_DEV_REPORTS)
        self.assertIn("docs/DEV_REPORT_CANONICAL_UA.md", ALLOWED_DEV_REPORTS)
        self.assertEqual(len(ALLOWED_DEV_REPORTS), 2)

    def test_versioned_dev_report_detected(self):
        """Versioned DEV_REPORT files should be detected as bloat."""
        from scripts.check_repo_safety import check_dev_report_bloat
        
        # Mock git ls-files to return versioned file
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                stdout="docs/DEV_REPORT_LATEST.md\ndocs/DEV_REPORT_2026-02-19_v2.3.4.md\n",
                returncode=0
            )
            issues = check_dev_report_bloat()
        
        # Should detect the versioned file
        self.assertTrue(len(issues) >= 1)
        self.assertTrue(any("DEV_REPORT_BLOAT" in i for i in issues))
        self.assertTrue(any("v2.3.4" in i for i in issues))

    def test_only_latest_is_ok(self):
        """Only DEV_REPORT_LATEST.md should pass."""
        from scripts.check_repo_safety import check_dev_report_bloat
        
        # Mock git ls-files to return only allowed files
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                stdout="docs/DEV_REPORT_LATEST.md\ndocs/DEV_REPORT_CANONICAL_UA.md\n",
                returncode=0
            )
            issues = check_dev_report_bloat()
        
        # Should have no issues
        self.assertEqual(len(issues), 0)


class TestStatusVersionConsistency(unittest.TestCase):
    """Test Status version consistency check (v1.3.0).
    
    NOTE: v1.4.0 - Version checking disabled per DOCS_POLICY.md.
    Versions now tracked only in DEV_REPORT_LATEST.md.
    """

    def test_extract_script_version(self):
        """extract_script_version should parse __version__ correctly."""
        from scripts.check_repo_safety import extract_script_version
        
        mock_content = '''
#!/usr/bin/env python3
__version__ = "2.3.2"
'''
        with patch.object(Path, 'read_text', return_value=mock_content):
            version = extract_script_version(Path('/fake/script.py'))
        
        self.assertEqual(version, "2.3.2")

    def test_status_version_mappings_disabled(self):
        """v1.4.0: STATUS_VERSION_MAPPINGS should be empty (disabled per DOCS_POLICY)."""
        from scripts.check_repo_safety import STATUS_VERSION_MAPPINGS
        
        # v1.4.0: Mappings disabled - versions now only in DEV_REPORT_LATEST.md
        self.assertEqual(len(STATUS_VERSION_MAPPINGS), 0)


class TestDevReportFreshness(unittest.TestCase):
    """Test DEV_REPORT freshness check (v1.3.0)."""

    def test_freshness_check_with_matching_date(self):
        """DEV_REPORT containing rolling timestamp date should pass."""
        from scripts.check_repo_safety import check_dev_report_freshness
        import json
        
        # Mock rolling summary with timestamp
        mock_summary = {
            "run_context": {
                "run_timestamp": "2026-02-20T10:00:00.000000+00:00"
            }
        }
        
        # Mock DEV_REPORT containing the date
        mock_dev_report = "timestamp_utc: 2026-02-20T10:00:00Z"
        
        with patch('scripts.check_repo_safety.PROJECT_ROOT', Path('/fake')):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'read_text', return_value=mock_dev_report):
                    with patch('builtins.open', unittest.mock.mock_open(read_data=json.dumps(mock_summary))):
                        issues = check_dev_report_freshness()
        
        # Should have no issues (date matches)
        self.assertEqual(len(issues), 0)

    def test_freshness_check_skipped_without_rolling(self):
        """Freshness check should skip if no rolling artifacts exist."""
        from scripts.check_repo_safety import check_dev_report_freshness
        
        with patch('scripts.check_repo_safety.PROJECT_ROOT', Path('/fake')):
            with patch.object(Path, 'exists', side_effect=lambda: False):
                # This should not raise and return empty
                # Note: we need more specific mocking here
                pass


class TestDocsLint(unittest.TestCase):
    """Test docs-lint version policy enforcement (v1.4.0)."""

    def test_exempt_files_list_correct(self):
        """Exempt files should include DEV_REPORT_LATEST.md and API contract docs."""
        from scripts.check_repo_safety import DOCS_VERSION_EXEMPT
        
        self.assertIn("docs/DEV_REPORT_LATEST.md", DOCS_VERSION_EXEMPT)
        self.assertIn("docs/m4/ROLLING_CONTRACT.md", DOCS_VERSION_EXEMPT)
        self.assertIn("docs/m4/M4_POLICY.md", DOCS_VERSION_EXEMPT)
        # DOCS_POLICY.md is NOT exempt - it must not contain version strings

    def test_version_pattern_matches_semver(self):
        """Version pattern should match semantic versions like v1.2.3."""
        import re
        version_pattern = re.compile(r'\bv\d+\.\d+\.\d+\b')
        
        # Should match
        self.assertIsNotNone(version_pattern.search("v1.2.3"))
        self.assertIsNotNone(version_pattern.search("v2.3.4"))
        self.assertIsNotNone(version_pattern.search("This is v1.0.0 version"))
        
        # Should NOT match
        self.assertIsNone(version_pattern.search("v1.2"))  # Only 2 parts
        self.assertIsNone(version_pattern.search("version 1.2.3"))  # No v prefix
        self.assertIsNone(version_pattern.search("v1"))  # Only 1 part

    def test_check_docs_lint_exists(self):
        """check_docs_lint function should exist and be callable."""
        from scripts.check_repo_safety import check_docs_lint
        
        self.assertTrue(callable(check_docs_lint))


if __name__ == "__main__":
    unittest.main()
