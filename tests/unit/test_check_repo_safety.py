# PATH: tests/unit/test_check_repo_safety.py
"""
Unit tests for scripts/check_repo_safety.py v1.1.0

Tests:
1. INFO messages for untracked files don't count as warnings
2. DANGER messages for tracked files cause FAIL
3. Untracked settings.json with autoApprove is INFO-only
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


if __name__ == "__main__":
    unittest.main()
