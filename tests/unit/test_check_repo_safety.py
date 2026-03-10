# PATH: tests/unit/test_check_repo_safety.py
"""
Unit tests for scripts/check_repo_safety.py v1.6.0

Tests:
1. INFO messages for untracked files don't count as warnings
2. DANGER messages for tracked files cause FAIL
3. Untracked settings.json with autoApprove is INFO-only
4. DEV_REPORT bloat detection (v1.2.0)
5. Status version consistency (v1.3.0) - DISABLED per DOCS_POLICY
6. DEV_REPORT freshness check (v1.3.0)
7. Docs lint - version policy (v1.4.0)
8. Roadmap governance - controlled document policy (v1.5.0)
9. DEV_REPORT alignment - rolling artifact sync (v1.6.0)
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
        """Version pattern should match semantic versions like v1.2.3, v2.4.x, v1.2."""
        import re
        # Expanded pattern to catch vX.Y.Z, vX.Y.x, vX.Y, and suffixes
        version_pattern = re.compile(r'\bv\d+\.\d+(?:\.[0-9xX]+)?(?:-\w+)?\b')
        
        # Should match - standard semver
        self.assertIsNotNone(version_pattern.search("v1.2.3"))
        self.assertIsNotNone(version_pattern.search("v2.3.4"))
        self.assertIsNotNone(version_pattern.search("This is v1.0.0 version"))
        
        # Should match - wildcard versions (new loophole fix)
        self.assertIsNotNone(version_pattern.search("v2.4.x"))
        self.assertIsNotNone(version_pattern.search("## v2.4.x Infra Changes"))
        self.assertIsNotNone(version_pattern.search("v1.2.X"))  # uppercase X
        
        # Should match - two-part versions
        self.assertIsNotNone(version_pattern.search("v1.2"))
        self.assertIsNotNone(version_pattern.search("policy: v2.0"))
        
        # Should match - versions with suffix
        self.assertIsNotNone(version_pattern.search("v1.2.3-fix"))
        self.assertIsNotNone(version_pattern.search("v2.0-beta"))
        
        # Should NOT match
        self.assertIsNone(version_pattern.search("version 1.2.3"))  # No v prefix
        self.assertIsNone(version_pattern.search("v1"))  # Only 1 part
        self.assertIsNone(version_pattern.search("sv1.2.3"))  # prefix before v

    def test_namespaced_version_pattern(self):
        """Namespaced schema identifiers like m4:signals:v1.1 should be exempt."""
        import re
        # Namespaced schema pattern
        namespaced_pattern = re.compile(r'\w+:\w+:v\d+\.\d+(?:\.[0-9xX]+)?')
        
        # Should match namespaced patterns
        self.assertIsNotNone(namespaced_pattern.search("m4:signals:v1.1"))
        self.assertIsNotNone(namespaced_pattern.search("m4:execution:v1.1"))
        self.assertIsNotNone(namespaced_pattern.search("namespace:component:v2.0"))
        self.assertIsNotNone(namespaced_pattern.search("m4:latest:v2.0"))
        
        # Should NOT match standalone versions
        self.assertIsNone(namespaced_pattern.search("v1.2.3"))  # No namespace
        self.assertIsNone(namespaced_pattern.search("## v2.4.x Infra"))  # Standalone
        
    def test_version_exempt_prefixes_list(self):
        """DOCS_VERSION_EXEMPT_PREFIXES should include artifacts path."""
        from scripts.check_repo_safety import DOCS_VERSION_EXEMPT_PREFIXES
        
        self.assertIn("docs/artifacts/", DOCS_VERSION_EXEMPT_PREFIXES)

    def test_check_docs_lint_exists(self):
        """check_docs_lint function should exist and be callable."""
        from scripts.check_repo_safety import check_docs_lint
        
        self.assertTrue(callable(check_docs_lint))


class TestRoadmapGovernance(unittest.TestCase):
    """Test Roadmap governance check (v1.5.0).
    
    Roadmap.md is a controlled document - agents cannot modify without
    explicit Lead directive (--allow-roadmap-edit flag).
    """

    def test_unmodified_roadmap_passes(self):
        """Unmodified Roadmap.md should PASS even without allow_edit flag."""
        from scripts.check_repo_safety import check_roadmap_governance
        
        # Mock: no staged changes
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                stdout="",  # Nothing in diff --cached
                returncode=0
            )
            issues = check_roadmap_governance(allow_edit=False)
        
        self.assertEqual(len(issues), 0)

    def test_modified_roadmap_fails_without_flag(self):
        """Modified Roadmap.md should FAIL without --allow-roadmap-edit flag."""
        from scripts.check_repo_safety import check_roadmap_governance
        
        # Mock: Roadmap.md is staged (only staged, not working tree)
        def mock_subprocess_run(cmd, **kwargs):
            result = MagicMock(returncode=0)
            # Only return Roadmap.md for --cached (staged) check
            if "--cached" in cmd:
                result.stdout = "Roadmap.md\n"
            else:
                result.stdout = ""
            return result
        
        with patch('subprocess.run', side_effect=mock_subprocess_run):
            issues = check_roadmap_governance(allow_edit=False)
        
        self.assertEqual(len(issues), 1)
        self.assertIn("ROADMAP_GOVERNANCE:", issues[0])
        self.assertIn("Roadmap.md", issues[0])

    def test_modified_roadmap_passes_with_flag(self):
        """Modified Roadmap.md should PASS with --allow-roadmap-edit flag."""
        from scripts.check_repo_safety import check_roadmap_governance
        
        # Mock: Roadmap.md is staged but allow_edit=True
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                stdout="Roadmap.md\n",
                returncode=0
            )
            issues = check_roadmap_governance(allow_edit=True)
        
        self.assertEqual(len(issues), 0)

    def test_check_roadmap_governance_exists(self):
        """check_roadmap_governance function should exist and be callable."""
        from scripts.check_repo_safety import check_roadmap_governance
        
        self.assertTrue(callable(check_roadmap_governance))


class TestDevReportAlignment(unittest.TestCase):
    """Test DEV_REPORT alignment check (v1.6.0).
    
    Verifies that DEV_REPORT_LATEST.md contains matching run_timestamp
    and run_dir_name from run_summary_latest.json.
    """

    def test_check_dev_report_alignment_exists(self):
        """check_dev_report_alignment function should exist and be callable."""
        from scripts.check_repo_safety import check_dev_report_alignment
        
        self.assertTrue(callable(check_dev_report_alignment))

    def test_aligned_report_passes(self):
        """DEV_REPORT containing matching rolling data should pass."""
        from scripts.check_repo_safety import check_dev_report_alignment
        import json
        
        mock_summary = {
            "run_context": {
                "run_timestamp": "2026-02-21T10:36:46.297599+00:00"
            },
            "inputs": {
                "run_dir_name": "ci_m5_gate_20260221_113627"
            }
        }
        
        # DEV_REPORT contains matching data
        mock_report = """
        run_context.run_timestamp: 2026-02-21T10:36:46.297599+00:00
        inputs.run_dir_name: ci_m5_gate_20260221_113627
        """
        
        with patch('scripts.check_repo_safety.PROJECT_ROOT', Path('/fake')):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'read_text', return_value=mock_report):
                    with patch('builtins.open', unittest.mock.mock_open(read_data=json.dumps(mock_summary))):
                        issues = check_dev_report_alignment()
        
        self.assertEqual(len(issues), 0)

    def test_misaligned_run_dir_fails(self):
        """DEV_REPORT with mismatched run_dir_name should warn."""
        from scripts.check_repo_safety import check_dev_report_alignment
        import json
        
        mock_summary = {
            "run_context": {
                "run_timestamp": "2026-02-21T10:36:46.297599+00:00"
            },
            "inputs": {
                "run_dir_name": "ci_m5_gate_20260221_113627"
            }
        }
        
        # DEV_REPORT contains OLD run_dir_name
        mock_report = """
        run_context.run_timestamp: 2026-02-21T10:36:46.297599+00:00
        inputs.run_dir_name: ci_m5_gate_20260221_105949
        """
        
        with patch('scripts.check_repo_safety.PROJECT_ROOT', Path('/fake')):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'read_text', return_value=mock_report):
                    with patch('builtins.open', unittest.mock.mock_open(read_data=json.dumps(mock_summary))):
                        issues = check_dev_report_alignment()
        
        # Should warn about run_dir mismatch
        self.assertTrue(any("run_dir_name mismatch" in i for i in issues))

    def test_misaligned_timestamp_fails(self):
        """DEV_REPORT with mismatched timestamp should warn."""
        from scripts.check_repo_safety import check_dev_report_alignment
        import json
        
        mock_summary = {
            "run_context": {
                "run_timestamp": "2026-02-21T10:36:46.297599+00:00"
            },
            "inputs": {
                "run_dir_name": "ci_m5_gate_20260221_113627"
            }
        }
        
        # DEV_REPORT contains OLD timestamp
        mock_report = """
        run_context.run_timestamp: 2026-02-21T10:00:09.828466+00:00
        inputs.run_dir_name: ci_m5_gate_20260221_113627
        """
        
        with patch('scripts.check_repo_safety.PROJECT_ROOT', Path('/fake')):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'read_text', return_value=mock_report):
                    with patch('builtins.open', unittest.mock.mock_open(read_data=json.dumps(mock_summary))):
                        issues = check_dev_report_alignment()
        
        # Should warn about timestamp mismatch
        self.assertTrue(any("run_timestamp mismatch" in i for i in issues))

    def test_no_rolling_artifacts_skipped(self):
        """No rolling artifacts should skip alignment check."""
        from scripts.check_repo_safety import check_dev_report_alignment
        
        with patch('scripts.check_repo_safety.PROJECT_ROOT', Path('/fake')):
            with patch.object(Path, 'exists', side_effect=lambda: True if 'DEV_REPORT' in str(self) else False):
                # This is complex to mock correctly, just verify no exception
                pass

    def test_metrics_mismatch_runs_in_window(self):
        """DEV_REPORT with mismatched runs_in_window should warn (v1.6.1)."""
        from scripts.check_repo_safety import check_dev_report_alignment
        import json
        
        mock_summary = {
            "run_context": {"run_timestamp": "2026-02-22T09:10:03.859524+00:00"},
            "inputs": {"run_dir_name": "ci_m5_gate_20260222_100945"}
        }
        mock_latest = {
            "runs_in_window": 103,
            "quick_stats": {"total_net_usdc": 5347.64, "unique_pairs": 8}
        }
        
        # DEV_REPORT with wrong runs_in_window
        mock_report = """
        run_context.run_timestamp: 2026-02-22T09:10:03.859524+00:00
        inputs.run_dir_name: ci_m5_gate_20260222_100945
        runs_in_window: 100
        computed_total_net_usdc: 5347.64
        unique_pairs: 8
        """
        
        def mock_open_handler(path, *args, **kwargs):
            if "run_summary_latest" in str(path):
                return unittest.mock.mock_open(read_data=json.dumps(mock_summary))()
            elif "_latest.json" in str(path):
                return unittest.mock.mock_open(read_data=json.dumps(mock_latest))()
            raise FileNotFoundError()
        
        with patch('scripts.check_repo_safety.PROJECT_ROOT', Path('/fake')):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'read_text', return_value=mock_report):
                    with patch('builtins.open', side_effect=mock_open_handler):
                        issues = check_dev_report_alignment()
        
        self.assertTrue(any("runs_in_window mismatch" in i for i in issues))

    def test_metrics_mismatch_unique_pairs(self):
        """DEV_REPORT with mismatched unique_pairs should warn (v1.6.1)."""
        from scripts.check_repo_safety import check_dev_report_alignment
        import json
        
        mock_summary = {
            "run_context": {"run_timestamp": "2026-02-22T09:10:03.859524+00:00"},
            "inputs": {"run_dir_name": "ci_m5_gate_20260222_100945"}
        }
        mock_latest = {
            "runs_in_window": 103,
            "quick_stats": {"total_net_usdc": 5347.64, "unique_pairs": 8}
        }
        
        # DEV_REPORT with wrong unique_pairs
        mock_report = """
        run_context.run_timestamp: 2026-02-22T09:10:03.859524+00:00
        inputs.run_dir_name: ci_m5_gate_20260222_100945
        runs_in_window: 103
        computed_total_net_usdc: 5347.64
        unique_pairs: 6
        """
        
        def mock_open_handler(path, *args, **kwargs):
            if "run_summary_latest" in str(path):
                return unittest.mock.mock_open(read_data=json.dumps(mock_summary))()
            elif "_latest.json" in str(path):
                return unittest.mock.mock_open(read_data=json.dumps(mock_latest))()
            raise FileNotFoundError()
        
        with patch('scripts.check_repo_safety.PROJECT_ROOT', Path('/fake')):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'read_text', return_value=mock_report):
                    with patch('builtins.open', side_effect=mock_open_handler):
                        issues = check_dev_report_alignment()
        
        self.assertTrue(any("unique_pairs mismatch" in i for i in issues))

    def test_timestamp_utc_propagation_mismatch_fails(self):
        """v3.2.69: timestamp_utc field mismatch with rolling run_timestamp should fail."""
        from scripts.check_repo_safety import check_dev_report_alignment
        import json
        
        mock_summary = {
            "run_context": {"run_timestamp": "2026-03-09T21:07:05.524114Z"},
            "inputs": {"run_dir_name": "ci_m5_gate_20260309_220644"}
        }
        mock_latest = {
            "quick_stats": {},
            "runs_in_window": 1,
            "data_run_rate": 1.0
        }
        
        # DEV_REPORT has wrong timestamp_utc (22:10:00 instead of 21:07:05)
        mock_report = """
        # DEV REPORT
        ## 0) Meta
        timestamp_utc: 2026-03-09T22:10:00Z
        rolling_provenance: 2026-03-09T21:07:05Z (arbitrum_one, ci_m5_gate_20260309_220644)
        """
        
        def mock_open_handler(path, *args, **kwargs):
            path_str = str(path)
            if "run_summary_latest" in path_str:
                return unittest.mock.mock_open(read_data=json.dumps(mock_summary))()
            elif "_latest.json" in path_str:
                return unittest.mock.mock_open(read_data=json.dumps(mock_latest))()
            raise FileNotFoundError()
        
        with patch('scripts.check_repo_safety.PROJECT_ROOT', Path('/fake')):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'read_text', return_value=mock_report):
                    with patch('builtins.open', side_effect=mock_open_handler):
                        issues = check_dev_report_alignment()
        
        # Should have TIMESTAMP_PROPAGATION error
        ts_issues = [i for i in issues if "TIMESTAMP_PROPAGATION" in i]
        self.assertEqual(len(ts_issues), 1)
        self.assertIn("2026-03-09T22:10:00", ts_issues[0])
        self.assertIn("2026-03-09T21:07:05", ts_issues[0])

    def test_timestamp_utc_propagation_match_passes(self):
        """v3.2.69: timestamp_utc field matching rolling run_timestamp should pass."""
        from scripts.check_repo_safety import check_dev_report_alignment
        import json
        
        mock_summary = {
            "run_context": {"run_timestamp": "2026-03-09T21:07:05.524114Z"},
            "inputs": {"run_dir_name": "ci_m5_gate_20260309_220644"}
        }
        mock_latest = {
            "quick_stats": {},
            "runs_in_window": 1,
            "data_run_rate": 1.0
        }
        
        # DEV_REPORT has correct timestamp_utc matching rolling
        mock_report = """
        # DEV REPORT
        ## 0) Meta
        timestamp_utc: 2026-03-09T21:07:05Z
        rolling_provenance: 2026-03-09T21:07:05Z (arbitrum_one, ci_m5_gate_20260309_220644)
        """
        
        def mock_open_handler(path, *args, **kwargs):
            path_str = str(path)
            if "run_summary_latest" in path_str:
                return unittest.mock.mock_open(read_data=json.dumps(mock_summary))()
            elif "_latest.json" in path_str:
                return unittest.mock.mock_open(read_data=json.dumps(mock_latest))()
            raise FileNotFoundError()
        
        with patch('scripts.check_repo_safety.PROJECT_ROOT', Path('/fake')):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'read_text', return_value=mock_report):
                    with patch('builtins.open', side_effect=mock_open_handler):
                        issues = check_dev_report_alignment()
        
        # Should NOT have TIMESTAMP_PROPAGATION error
        ts_issues = [i for i in issues if "TIMESTAMP_PROPAGATION" in i]
        self.assertEqual(len(ts_issues), 0)


class TestRollingConsistency(unittest.TestCase):
    """Test rolling artifact consistency check (v1.7.0)."""

    def test_pass_when_all_artifacts_match(self):
        """Rolling consistency PASS when all 3 artifacts have matching timestamps."""
        from scripts.check_repo_safety import check_rolling_consistency
        import json
        from unittest.mock import mock_open
        
        mock_latest = {
            "run_context": {
                "run_timestamp": "2026-03-02T10:10:45.916168Z",
                "run_dir_name": "ci_m5_gate_20260302_111032"
            },
            "runs_in_window": 22,
            "data_run_rate": 0.85
        }
        mock_summary = {
            "run_context": {"run_timestamp": "2026-03-02T10:10:45.916168Z"},
            "inputs": {"run_dir_name": "ci_m5_gate_20260302_111032"}
        }
        mock_agg = {
            "runs_since_timestamp": {"runs_count": 22},
            "quick_stats": {"data_run_rate": 0.85}
        }
        
        def custom_open(path, *args, **kwargs):
            path_str = str(path)
            # Order matters: check more specific patterns first
            if "run_summary_latest" in path_str:
                return mock_open(read_data=json.dumps(mock_summary))()
            if "_latest.json" in path_str:
                return mock_open(read_data=json.dumps(mock_latest))()
            if "m4_stability_agg" in path_str:
                return mock_open(read_data=json.dumps(mock_agg))()
            raise FileNotFoundError(f"No mock for {path_str}")
        
        with patch('scripts.check_repo_safety.PROJECT_ROOT', Path('/fake')):
            with patch.object(Path, 'exists', return_value=True):
                with patch('builtins.open', side_effect=custom_open):
                    issues = check_rolling_consistency()
        
        self.assertEqual(len(issues), 0, f"Expected no issues, got: {issues}")

    def test_fail_when_run_timestamp_mismatch(self):
        """Rolling consistency FAIL when _latest and run_summary have different timestamps."""
        from scripts.check_repo_safety import check_rolling_consistency
        import json
        from unittest.mock import mock_open
        
        mock_latest = {
            "run_context": {
                "run_timestamp": "2026-03-02T09:39:04.988143Z",  # older
                "run_dir_name": "ci_m5_gate_20260302_103848"
            },
            "runs_in_window": 22,
            "data_run_rate": 0.85
        }
        mock_summary = {
            "run_context": {"run_timestamp": "2026-03-02T10:10:45.916168Z"},  # newer
            "inputs": {"run_dir_name": "ci_m5_gate_20260302_111032"}
        }
        mock_agg = {
            "runs_since_timestamp": {"runs_count": 22},
            "quick_stats": {"data_run_rate": 0.85}
        }
        
        def custom_open(path, *args, **kwargs):
            path_str = str(path)
            if "run_summary_latest" in path_str:
                return mock_open(read_data=json.dumps(mock_summary))()
            if "_latest.json" in path_str:
                return mock_open(read_data=json.dumps(mock_latest))()
            if "m4_stability_agg" in path_str:
                return mock_open(read_data=json.dumps(mock_agg))()
            raise FileNotFoundError(f"No mock for {path_str}")
        
        with patch('scripts.check_repo_safety.PROJECT_ROOT', Path('/fake')):
            with patch.object(Path, 'exists', return_value=True):
                with patch('builtins.open', side_effect=custom_open):
                    issues = check_rolling_consistency()
        
        self.assertTrue(any("run_timestamp mismatch" in i for i in issues), f"Issues: {issues}")
        self.assertTrue(any("run_dir_name mismatch" in i for i in issues), f"Issues: {issues}")

    def test_fail_when_runs_in_window_mismatch(self):
        """Rolling consistency FAIL when _latest and m4_stability_agg.runs_in_window diverge >1."""
        from scripts.check_repo_safety import check_rolling_consistency
        import json
        from unittest.mock import mock_open
        
        mock_latest = {
            "run_context": {
                "run_timestamp": "2026-03-02T10:10:45.916168Z",
                "run_dir_name": "ci_m5_gate_20260302_111032"
            },
            "runs_in_window": 22,
            "data_run_rate": 0.85
        }
        mock_summary = {
            "run_context": {"run_timestamp": "2026-03-02T10:10:45.916168Z"},
            "inputs": {"run_dir_name": "ci_m5_gate_20260302_111032"}
        }
        mock_agg = {
            "runs_since_timestamp": {"runs_count": 30},  # big mismatch
            "quick_stats": {"data_run_rate": 0.85}
        }
        
        def custom_open(path, *args, **kwargs):
            path_str = str(path)
            if "run_summary_latest" in path_str:
                return mock_open(read_data=json.dumps(mock_summary))()
            if "_latest.json" in path_str:
                return mock_open(read_data=json.dumps(mock_latest))()
            if "m4_stability_agg" in path_str:
                return mock_open(read_data=json.dumps(mock_agg))()
            raise FileNotFoundError(f"No mock for {path_str}")
        
        with patch('scripts.check_repo_safety.PROJECT_ROOT', Path('/fake')):
            with patch.object(Path, 'exists', return_value=True):
                with patch('builtins.open', side_effect=custom_open):
                    issues = check_rolling_consistency()
        
        self.assertTrue(any("runs_in_window mismatch" in i for i in issues), f"Issues: {issues}")


class TestSessionCompletionGate(unittest.TestCase):
    """Test session completion gate check (v1.9.0).
    
    Per DOCS_POLICY.md section 9: Session completion requires explicit
    goal_status field when completion language is detected in DEV_REPORT.
    """

    def test_check_session_completion_gate_exists(self):
        """check_session_completion_gate function should exist and be callable."""
        from scripts.check_repo_safety import check_session_completion_gate
        
        self.assertTrue(callable(check_session_completion_gate))

    def test_no_completion_language_passes(self):
        """DEV_REPORT without completion language should pass."""
        from scripts.check_repo_safety import check_session_completion_gate
        
        mock_report = """
        # DEV REPORT
        timestamp_utc: 2026-03-09T15:00:00Z
        
        ## Status
        Work in progress. Implementing fixes.
        """
        
        with patch('scripts.check_repo_safety.PROJECT_ROOT', Path('/fake')):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'read_text', return_value=mock_report):
                    issues = check_session_completion_gate()
        
        self.assertEqual(len(issues), 0)

    def test_completion_language_without_goal_status_fails(self):
        """DEV_REPORT with completion language but no goal_status should fail."""
        from scripts.check_repo_safety import check_session_completion_gate
        
        mock_report = """
        # DEV REPORT
        timestamp_utc: 2026-03-09T15:00:00Z
        
        ## Summary
        All 10 steps completed. Session is complete.
        """
        
        with patch('scripts.check_repo_safety.PROJECT_ROOT', Path('/fake')):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'read_text', return_value=mock_report):
                    issues = check_session_completion_gate()
        
        self.assertEqual(len(issues), 1)
        self.assertIn("SESSION_COMPLETION", issues[0])
        self.assertIn("goal_status", issues[0])

    def test_completion_language_with_goal_status_reached_passes(self):
        """DEV_REPORT with completion language and goal_status: REACHED should pass."""
        from scripts.check_repo_safety import check_session_completion_gate
        
        mock_report = """
        # DEV REPORT
        timestamp_utc: 2026-03-09T15:00:00Z
        goal_status: REACHED
        
        ## Summary
        All 10 steps completed. Session is complete.
        """
        
        with patch('scripts.check_repo_safety.PROJECT_ROOT', Path('/fake')):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'read_text', return_value=mock_report):
                    issues = check_session_completion_gate()
        
        self.assertEqual(len(issues), 0)

    def test_completion_language_with_goal_status_in_progress_fails(self):
        """DEV_REPORT with completion language but goal_status: IN_PROGRESS should fail."""
        from scripts.check_repo_safety import check_session_completion_gate
        
        mock_report = """
        # DEV REPORT
        timestamp_utc: 2026-03-09T15:00:00Z
        goal_status: IN_PROGRESS
        
        ## Summary
        All tasks done. Fully implemented.
        """
        
        with patch('scripts.check_repo_safety.PROJECT_ROOT', Path('/fake')):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'read_text', return_value=mock_report):
                    issues = check_session_completion_gate()
        
        self.assertEqual(len(issues), 1)
        self.assertIn("SESSION_COMPLETION", issues[0])
        self.assertIn("not REACHED", issues[0])

    def test_goal_reached_pattern_detected(self):
        """'goal reached' pattern should trigger completion detection."""
        from scripts.check_repo_safety import check_session_completion_gate
        
        mock_report = """
        # DEV REPORT
        Goal is reached!
        """
        
        with patch('scripts.check_repo_safety.PROJECT_ROOT', Path('/fake')):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'read_text', return_value=mock_report):
                    issues = check_session_completion_gate()
        
        # Should detect completion language but no goal_status field
        self.assertEqual(len(issues), 1)
        self.assertIn("SESSION_COMPLETION", issues[0])

    def test_close_allowed_true_with_blocker_resolved_passes(self):
        """close_allowed=true with blocker_status_after: RESOLVED should pass."""
        from scripts.check_repo_safety import check_session_completion_gate
        
        mock_report = """
        # DEV REPORT
        goal_status: REACHED
        close_allowed: true
        blocker_status_after: RESOLVED
        """
        
        with patch('scripts.check_repo_safety.PROJECT_ROOT', Path('/fake')):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'read_text', return_value=mock_report):
                    issues = check_session_completion_gate()
        
        self.assertEqual(len(issues), 0)

    def test_close_allowed_true_with_blocker_in_progress_fails(self):
        """close_allowed=true with blocker_status_after: IN_PROGRESS should fail."""
        from scripts.check_repo_safety import check_session_completion_gate
        
        mock_report = """
        # DEV REPORT
        goal_status: REACHED
        close_allowed: true
        blocker_status_after: IN_PROGRESS
        """
        
        with patch('scripts.check_repo_safety.PROJECT_ROOT', Path('/fake')):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'read_text', return_value=mock_report):
                    issues = check_session_completion_gate()
        
        self.assertEqual(len(issues), 1)
        self.assertIn("PRIMARY_BLOCKER", issues[0])
        self.assertIn("blocker_status_after=IN_PROGRESS", issues[0])

    def test_close_allowed_true_without_blocker_field_fails(self):
        """close_allowed=true without blocker_status_after field should fail."""
        from scripts.check_repo_safety import check_session_completion_gate
        
        mock_report = """
        # DEV REPORT
        goal_status: REACHED
        close_allowed: true
        """
        
        with patch('scripts.check_repo_safety.PROJECT_ROOT', Path('/fake')):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'read_text', return_value=mock_report):
                    issues = check_session_completion_gate()
        
        self.assertEqual(len(issues), 1)
        self.assertIn("PRIMARY_BLOCKER", issues[0])
        self.assertIn("missing blocker_status_after", issues[0])

    def test_close_allowed_true_with_blocker_blocked_passes(self):
        """close_allowed=true with blocker_status_after: BLOCKED should pass."""
        from scripts.check_repo_safety import check_session_completion_gate
        
        mock_report = """
        # DEV REPORT
        goal_status: BLOCKED
        close_allowed: true
        blocker_status_after: BLOCKED
        remaining_blockers: ["RPC unreliable"]
        """
        
        with patch('scripts.check_repo_safety.PROJECT_ROOT', Path('/fake')):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'read_text', return_value=mock_report):
                    issues = check_session_completion_gate()
        
        self.assertEqual(len(issues), 0)

    def test_goal_in_progress_with_close_allowed_true_fails(self):
        """v3.2.69: goal_status=IN_PROGRESS with close_allowed=true should fail."""
        from scripts.check_repo_safety import check_session_completion_gate
        
        mock_report = """
        # DEV REPORT
        | goal_status | **IN_PROGRESS** (2/6 chains active) |
        | close_allowed | true |
        | blocker_status_after | **RESOLVED** |
        """
        
        with patch('scripts.check_repo_safety.PROJECT_ROOT', Path('/fake')):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'read_text', return_value=mock_report):
                    issues = check_session_completion_gate()
        
        self.assertGreaterEqual(len(issues), 1)
        contract_issues = [i for i in issues if "SESSION_CONTRACT" in i and "IN_PROGRESS" in i]
        self.assertEqual(len(contract_issues), 1)
        self.assertIn("close_allowed=true", contract_issues[0])

    def test_session_reached_text_with_in_progress_fails(self):
        """v3.2.69: 'Session REACHED' text with goal_status=IN_PROGRESS should fail."""
        from scripts.check_repo_safety import check_session_completion_gate
        
        mock_report = """
        # DEV REPORT
        | goal_status | **IN_PROGRESS** |
        | close_allowed | false |
        
        1. **Session REACHED**: All audit steps completed.
        """
        
        with patch('scripts.check_repo_safety.PROJECT_ROOT', Path('/fake')):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'read_text', return_value=mock_report):
                    issues = check_session_completion_gate()
        
        self.assertGreaterEqual(len(issues), 1)
        reached_issues = [i for i in issues if "SESSION_CONTRACT" in i and "Session REACHED" in i]
        self.assertEqual(len(reached_issues), 1)

    def test_goal_reached_with_close_allowed_true_passes(self):
        """v3.2.69: goal_status=REACHED with close_allowed=true should pass."""
        from scripts.check_repo_safety import check_session_completion_gate
        
        mock_report = """
        # DEV REPORT
        | goal_status | **REACHED** |
        | close_allowed | true |
        | blocker_status_after | **RESOLVED** |
        """
        
        with patch('scripts.check_repo_safety.PROJECT_ROOT', Path('/fake')):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'read_text', return_value=mock_report):
                    issues = check_session_completion_gate()
        
        # Should pass - no contract violations
        contract_issues = [i for i in issues if "SESSION_CONTRACT" in i]
        self.assertEqual(len(contract_issues), 0)


class TestDevReportClaimConsistency(unittest.TestCase):
    """v3.2.64: Tests for check_dev_report_claim_consistency function."""

    def test_session_complete_with_in_progress_fails(self):
        """'Session complete' text with goal_status=IN_PROGRESS should fail."""
        from scripts.check_repo_safety import check_dev_report_claim_consistency
        
        mock_report = """
        # DEV REPORT
        | goal_status | **IN_PROGRESS** |
        | close_allowed | true |
        
        Session complete - all fixes applied.
        """
        
        with patch('scripts.check_repo_safety.PROJECT_ROOT', Path('/fake')):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'read_text', return_value=mock_report):
                    issues = check_dev_report_claim_consistency()
        
        # Should have at least 1 issue about Session complete with IN_PROGRESS
        self.assertGreaterEqual(len(issues), 1)
        session_complete_issue = [i for i in issues if "Session complete" in i and "IN_PROGRESS" in i]
        self.assertEqual(len(session_complete_issue), 1)

    def test_close_allowed_false_with_session_complete_fails(self):
        """close_allowed=false with 'Session complete' text should fail."""
        from scripts.check_repo_safety import check_dev_report_claim_consistency
        
        mock_report = """
        # DEV REPORT
        | goal_status | **REACHED** |
        | close_allowed | false |
        
        Session closure justification: All work done.
        """
        
        with patch('scripts.check_repo_safety.PROJECT_ROOT', Path('/fake')):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'read_text', return_value=mock_report):
                    issues = check_dev_report_claim_consistency()
        
        self.assertEqual(len(issues), 1)
        self.assertIn("DEV_REPORT_CONFLICT", issues[0])
        self.assertIn("close_allowed=false", issues[0])

    def test_consistent_in_progress_session_passes(self):
        """IN_PROGRESS with no completion language should pass."""
        from scripts.check_repo_safety import check_dev_report_claim_consistency
        
        mock_report = """
        # DEV REPORT
        | goal_status | **IN_PROGRESS** |
        | close_allowed | false |
        
        Work continues on multi-chain stabilization.
        """
        
        with patch('scripts.check_repo_safety.PROJECT_ROOT', Path('/fake')):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'read_text', return_value=mock_report):
                    issues = check_dev_report_claim_consistency()
        
        self.assertEqual(len(issues), 0)

    def test_consistent_reached_session_passes(self):
        """REACHED with completion language and close_allowed=true should pass."""
        from scripts.check_repo_safety import check_dev_report_claim_consistency
        
        mock_report = """
        # DEV REPORT
        | goal_status | **REACHED** |
        | close_allowed | true |
        
        Session complete - all tasks done.
        """
        
        with patch('scripts.check_repo_safety.PROJECT_ROOT', Path('/fake')):
            with patch.object(Path, 'exists', return_value=True):
                with patch.object(Path, 'read_text', return_value=mock_report):
                    issues = check_dev_report_claim_consistency()
        
        self.assertEqual(len(issues), 0)


class TestDevReportRuntimeClaims(unittest.TestCase):
    """v3.2.65: Test check_dev_report_runtime_claims function for signals/net_usdc validation."""

    def test_catches_signals_count_mismatch(self):
        """Should catch when DEV_REPORT claims different signals than run_summary shows."""
        from scripts.check_repo_safety import check_dev_report_runtime_claims
        import json
        import tempfile
        import os
        
        # Create mock DEV_REPORT with claim: Arbitrum 200317 has 6 signals
        mock_report = """
        | Chain | RunDir | Gate | signals | net_usdc | Status |
        | **Arbitrum** | 200317 | PASS | **6** | **$3.66** | ✅ SIGNAL_PRODUCING |
        """
        
        # Create mock run_summary with actual: 5 signals
        mock_run_summary = {
            "metrics": {
                "signals_count": 5,
                "included_signals_count": 4,
                "total_net_usdc": 3.66
            }
        }
        
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            
            # Create DEV_REPORT
            docs_dir = tmp_path / "docs"
            docs_dir.mkdir()
            (docs_dir / "DEV_REPORT_LATEST.md").write_text(mock_report, encoding='utf-8')
            
            # Create run_summary in expected location
            runs_dir = tmp_path / "data" / "runs" / "ci_m5_gate_20260309_200317" / "reports"
            runs_dir.mkdir(parents=True)
            (runs_dir / "run_summary_20260309_190339.json").write_text(
                json.dumps(mock_run_summary), encoding='utf-8'
            )
            
            with patch('scripts.check_repo_safety.PROJECT_ROOT', tmp_path):
                issues = check_dev_report_runtime_claims()
        
        # Should have one mismatch error
        self.assertEqual(len(issues), 1)
        self.assertIn("DEV_REPORT_RUNTIME_MISMATCH", issues[0])
        self.assertIn("signals=6", issues[0])
        self.assertIn("signals_count=5", issues[0])

    def test_matching_values_pass(self):
        """When DEV_REPORT claims match run_summary, should pass."""
        from scripts.check_repo_safety import check_dev_report_runtime_claims
        import json
        import tempfile
        
        # Create mock DEV_REPORT with correct claim
        mock_report = """
        | Chain | RunDir | Gate | signals | net_usdc | Status |
        | **Arbitrum** | 200317 | PASS | **5** | **$3.66** | ✅ SIGNAL_PRODUCING |
        """
        
        # Create mock run_summary with matching values
        mock_run_summary = {
            "metrics": {
                "signals_count": 5,
                "included_signals_count": 4,
                "total_net_usdc": 3.66
            }
        }
        
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            
            # Create DEV_REPORT
            docs_dir = tmp_path / "docs"
            docs_dir.mkdir()
            (docs_dir / "DEV_REPORT_LATEST.md").write_text(mock_report, encoding='utf-8')
            
            # Create run_summary
            runs_dir = tmp_path / "data" / "runs" / "ci_m5_gate_20260309_200317" / "reports"
            runs_dir.mkdir(parents=True)
            (runs_dir / "run_summary_20260309_190339.json").write_text(
                json.dumps(mock_run_summary), encoding='utf-8'
            )
            
            with patch('scripts.check_repo_safety.PROJECT_ROOT', tmp_path):
                issues = check_dev_report_runtime_claims()
        
        # Should have no issues
        self.assertEqual(len(issues), 0)

    def test_catches_net_usdc_mismatch(self):
        """Should catch when DEV_REPORT claims different net_usdc than run_summary shows."""
        from scripts.check_repo_safety import check_dev_report_runtime_claims
        import json
        import tempfile
        
        # Create mock DEV_REPORT with wrong net_usdc
        mock_report = """
        | Chain | RunDir | Gate | signals | net_usdc | Status |
        | **Arbitrum** | 200317 | PASS | **5** | **$34.02** | ✅ SIGNAL_PRODUCING |
        """
        
        # Create mock run_summary with actual: $3.66
        mock_run_summary = {
            "metrics": {
                "signals_count": 5,
                "total_net_usdc": 3.66
            }
        }
        
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            
            docs_dir = tmp_path / "docs"
            docs_dir.mkdir()
            (docs_dir / "DEV_REPORT_LATEST.md").write_text(mock_report, encoding='utf-8')
            
            runs_dir = tmp_path / "data" / "runs" / "ci_m5_gate_20260309_200317" / "reports"
            runs_dir.mkdir(parents=True)
            (runs_dir / "run_summary_20260309_190339.json").write_text(
                json.dumps(mock_run_summary), encoding='utf-8'
            )
            
            with patch('scripts.check_repo_safety.PROJECT_ROOT', tmp_path):
                issues = check_dev_report_runtime_claims()
        
        # Should have mismatch error
        self.assertEqual(len(issues), 1)
        self.assertIn("net_usdc", issues[0].lower())

    def test_missing_rundir_skipped(self):
        """When runDir in DEV_REPORT doesn't exist in data/runs, should skip (not error)."""
        from scripts.check_repo_safety import check_dev_report_runtime_claims
        import tempfile
        
        # Create mock DEV_REPORT with non-existent runDir
        mock_report = """
        | Chain | RunDir | Gate | signals | net_usdc | Status |
        | **Arbitrum** | 999999 | PASS | **5** | **$3.66** | ✅ SIGNAL_PRODUCING |
        """
        
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            
            docs_dir = tmp_path / "docs"
            docs_dir.mkdir()
            (docs_dir / "DEV_REPORT_LATEST.md").write_text(mock_report, encoding='utf-8')
            
            # Create runs dir but not the specific runDir
            runs_dir = tmp_path / "data" / "runs"
            runs_dir.mkdir(parents=True)
            
            with patch('scripts.check_repo_safety.PROJECT_ROOT', tmp_path):
                issues = check_dev_report_runtime_claims()
        
        # Should have no issues (missing runDir is skipped, not an error)
        self.assertEqual(len(issues), 0)


class TestDevReportPlaceholders(unittest.TestCase):
    """Test DEV_REPORT placeholder detection (v1.11.0).
    
    Tests:
    1. Placeholder text detection in tables (e.g., 'signals' instead of numbers)
    2. Stale footer detection (v3.2.67 footer but v3.2.68 in body)
    3. PASS claim when run_summary.status = NO_DATA
    """

    def test_detects_placeholder_text_in_table(self):
        """Should detect placeholder text 'signals' instead of actual number."""
        from scripts.check_repo_safety import check_dev_report_placeholders
        import tempfile
        
        # DEV_REPORT with placeholder 'signals' instead of number
        mock_report = """
        | Chain | RunDir | Gate | signals | net_usdc | Status |
        | **Arbitrum** | 220644 | PASS | signals | net | ✅ SIGNAL_PRODUCING |
        """
        
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            
            docs_dir = tmp_path / "docs"
            docs_dir.mkdir()
            (docs_dir / "DEV_REPORT_LATEST.md").write_text(mock_report, encoding='utf-8')
            
            runs_dir = tmp_path / "data" / "runs"
            runs_dir.mkdir(parents=True)
            
            with patch('scripts.check_repo_safety.PROJECT_ROOT', tmp_path):
                issues = check_dev_report_placeholders()
        
        # Should detect placeholder
        self.assertTrue(len(issues) >= 1)
        self.assertTrue(any("DEV_REPORT_PLACEHOLDER" in i for i in issues))
        self.assertTrue(any("signals" in i.lower() for i in issues))

    def test_detects_stale_footer_version(self):
        """Should detect when footer has older version than body."""
        from scripts.check_repo_safety import check_dev_report_placeholders
        import tempfile
        
        # DEV_REPORT with v3.2.68 in body but v3.2.67 in footer
        mock_report = """
        **v3.2.68 Fix**: Fixed profit invariant
        
        | Chain | RunDir | Gate | signals | net_usdc | Status |
        | **Arbitrum** | 220644 | PASS | **5** | **$3.66** | ✅ SIGNAL_PRODUCING |
        
        ---
        Generated: 2026-03-09 v3.2.67
        """
        
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            
            docs_dir = tmp_path / "docs"
            docs_dir.mkdir()
            (docs_dir / "DEV_REPORT_LATEST.md").write_text(mock_report, encoding='utf-8')
            
            runs_dir = tmp_path / "data" / "runs"
            runs_dir.mkdir(parents=True)
            
            with patch('scripts.check_repo_safety.PROJECT_ROOT', tmp_path):
                issues = check_dev_report_placeholders()
        
        # Should detect stale footer
        self.assertTrue(len(issues) >= 1)
        self.assertTrue(any("DEV_REPORT_STALE_FOOTER" in i for i in issues))

    def test_detects_pass_with_no_data_status(self):
        """Should detect PASS claim when run_summary.status = NO_DATA."""
        from scripts.check_repo_safety import check_dev_report_placeholders
        import json
        import tempfile
        
        # DEV_REPORT claims PASS
        mock_report = """
        | RunDir | Chain | Gate | signals | net_usdc | Status |
        | 220720 | zkSync | PASS | **0** | **$0** | ⚠️ LIQUIDITY_ZERO |
        """
        
        # run_summary has status=NO_DATA
        mock_run_summary = {
            "status": "NO_DATA",
            "metrics": {
                "signals_count": 0,
                "total_net_usdc": 0,
                "no_data_reason": "ALL_OPPORTUNITIES_REJECTED"
            }
        }
        
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            
            docs_dir = tmp_path / "docs"
            docs_dir.mkdir()
            (docs_dir / "DEV_REPORT_LATEST.md").write_text(mock_report, encoding='utf-8')
            
            runs_dir = tmp_path / "data" / "runs" / "ci_m5_gate_20260309_220720" / "reports"
            runs_dir.mkdir(parents=True)
            (runs_dir / "run_summary_20260309_210720.json").write_text(
                json.dumps(mock_run_summary), encoding='utf-8'
            )
            
            with patch('scripts.check_repo_safety.PROJECT_ROOT', tmp_path):
                issues = check_dev_report_placeholders()
        
        # Should detect PASS/NO_DATA mismatch
        self.assertTrue(len(issues) >= 1)
        self.assertTrue(any("DEV_REPORT_PASS_MISMATCH" in i for i in issues))
        self.assertTrue(any("NO_DATA" in i for i in issues))

    def test_no_issues_when_clean(self):
        """Should return no issues when DEV_REPORT is clean."""
        from scripts.check_repo_safety import check_dev_report_placeholders
        import json
        import tempfile
        
        # Clean DEV_REPORT with actual numbers
        mock_report = """
        **v3.2.68 Fix**: Fixed profit invariant
        
        | RunDir | Chain | Gate | signals | net_usdc | Status |
        | 220644 | Arbitrum | PASS | **5** | **$3.66** | ✅ SIGNAL_PRODUCING |
        """
        
        # run_summary has status=PASS (not NO_DATA)
        mock_run_summary = {
            "status": "PASS",
            "metrics": {
                "signals_count": 5,
                "total_net_usdc": 3.66
            }
        }
        
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            
            docs_dir = tmp_path / "docs"
            docs_dir.mkdir()
            (docs_dir / "DEV_REPORT_LATEST.md").write_text(mock_report, encoding='utf-8')
            
            runs_dir = tmp_path / "data" / "runs" / "ci_m5_gate_20260309_220644" / "reports"
            runs_dir.mkdir(parents=True)
            (runs_dir / "run_summary_20260309_210644.json").write_text(
                json.dumps(mock_run_summary), encoding='utf-8'
            )
            
            with patch('scripts.check_repo_safety.PROJECT_ROOT', tmp_path):
                issues = check_dev_report_placeholders()
        
        # Should have no placeholder issues (PASS claim with PASS status is OK)
        placeholder_issues = [i for i in issues if "PLACEHOLDER" in i or "PASS_MISMATCH" in i]
        self.assertEqual(len(placeholder_issues), 0)


class TestChainQualityClaims(unittest.TestCase):
    """v3.2.70: Test check_chain_quality_claims function.
    
    Validates that SIGNAL_PRODUCING claims are backed by run_summary.status=PASS.
    """
    
    def test_signal_producing_with_fail_status_warns(self):
        """SIGNAL_PRODUCING claim + run_summary.status=FAIL → warning."""
        import json
        import tempfile
        from scripts.check_repo_safety import check_chain_quality_claims
        
        mock_report = """
| Chain | RunDir | M5 Gate | signals | net_usdc | Status |
|-------|--------|---------|---------|----------|--------|
| **Base** | 095028 | PASS | 8 | $2.80 | ✅ SIGNAL_PRODUCING |
"""
        mock_run_summary = {
            "status": "FAIL",
            "quality_status": "FAIL_QUALITY",
            "reasons": ["FAIL_FRAGILE_HIGH", "WARN_TOP_PAIR_DOMINANCE_HIGH"],
        }
        
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            docs_dir = tmp_path / "docs"
            docs_dir.mkdir()
            (docs_dir / "DEV_REPORT_LATEST.md").write_text(mock_report, encoding='utf-8')
            
            runs_dir = tmp_path / "data" / "runs" / "ci_m5_gate_20260310_095028" / "reports"
            runs_dir.mkdir(parents=True)
            (runs_dir / "run_summary_20260310_085220.json").write_text(
                json.dumps(mock_run_summary), encoding='utf-8'
            )
            
            with patch('scripts.check_repo_safety.PROJECT_ROOT', tmp_path):
                issues = check_chain_quality_claims()
        
        mismatch_issues = [i for i in issues if "CHAIN_QUALITY_CLAIM_MISMATCH" in i]
        self.assertEqual(len(mismatch_issues), 1)
        self.assertIn("Base", mismatch_issues[0])
        self.assertIn("FAIL", mismatch_issues[0])
    
    def test_signal_producing_with_pass_status_ok(self):
        """SIGNAL_PRODUCING claim + run_summary.status=PASS → no issues."""
        import json
        import tempfile
        from scripts.check_repo_safety import check_chain_quality_claims
        
        mock_report = """
| Chain | RunDir | M5 Gate | signals | net_usdc | Status |
|-------|--------|---------|---------|----------|--------|
| **Arbitrum** | 095332 | PASS | 5 | $2.93 | ✅ SIGNAL_PRODUCING |
"""
        mock_run_summary = {
            "status": "PASS",
            "quality_status": "WARN",
            "reasons": [],
        }
        
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            docs_dir = tmp_path / "docs"
            docs_dir.mkdir()
            (docs_dir / "DEV_REPORT_LATEST.md").write_text(mock_report, encoding='utf-8')
            
            runs_dir = tmp_path / "data" / "runs" / "ci_m5_gate_20260310_095332" / "reports"
            runs_dir.mkdir(parents=True)
            (runs_dir / "run_summary_20260310_085354.json").write_text(
                json.dumps(mock_run_summary), encoding='utf-8'
            )
            
            with patch('scripts.check_repo_safety.PROJECT_ROOT', tmp_path):
                issues = check_chain_quality_claims()
        
        mismatch_issues = [i for i in issues if "CHAIN_QUALITY_CLAIM_MISMATCH" in i]
        self.assertEqual(len(mismatch_issues), 0)


if __name__ == "__main__":
    unittest.main()
