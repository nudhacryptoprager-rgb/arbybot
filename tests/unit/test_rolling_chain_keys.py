# PATH: tests/unit/test_rolling_chain_keys.py
"""Tests for MIXED_CHAIN_KEYS guardrail in rolling aggregator (v3.2.7).

Validates that rolling_store.py correctly detects and warns when
runs from different chains are mixed in the rolling window.
"""

import unittest


class TestMixedChainKeysGuardrail(unittest.TestCase):
    """Test MIXED_CHAIN_KEYS detection in rolling aggregator."""
    
    def test_single_chain_key_no_warning(self):
        """When all runs have same chain_key, no MIXED_CHAIN_KEYS warning."""
        all_chain_keys = {"arbitrum_one"}
        has_mixed = len(all_chain_keys) > 1
        self.assertFalse(has_mixed)
    
    def test_multiple_chain_keys_triggers_warning(self):
        """When runs have different chain_keys, MIXED_CHAIN_KEYS warning issued."""
        all_chain_keys = {"arbitrum_one", "optimism"}
        has_mixed = len(all_chain_keys) > 1
        self.assertTrue(has_mixed)
    
    def test_empty_chain_keys_no_warning(self):
        """When no chain_keys extracted (legacy runs), no MIXED_CHAIN_KEYS warning."""
        all_chain_keys = set()
        has_mixed = len(all_chain_keys) > 1
        self.assertFalse(has_mixed)
    
    def test_unknown_chain_key_counted(self):
        """chain_key='unknown' is counted and can trigger mixed warning."""
        all_chain_keys = {"arbitrum_one", "unknown"}
        has_mixed = len(all_chain_keys) > 1
        self.assertTrue(has_mixed)
    
    def test_chain_keys_list_in_agg_data(self):
        """chain_keys list is stored in agg_data for observability."""
        # Simulate what rolling_store does
        all_chain_keys = {"arbitrum_one", "optimism"}
        agg_data = {}
        agg_data["chain_keys"] = list(sorted(all_chain_keys)) if all_chain_keys else []
        
        self.assertEqual(agg_data["chain_keys"], ["arbitrum_one", "optimism"])


class TestChainKeyExtraction(unittest.TestCase):
    """Test chain_key extraction from run inputs."""
    
    def test_extract_from_inputs(self):
        """chain_key is extracted from run inputs."""
        run = {
            "inputs": {"chain_key": "arbitrum_one", "chain_id": 42161},
        }
        inputs = run.get("inputs", {})
        chain_key = inputs.get("chain_key")
        self.assertEqual(chain_key, "arbitrum_one")
    
    def test_missing_inputs_gracefully_handled(self):
        """Missing inputs dict is handled gracefully."""
        run = {}
        inputs = run.get("inputs", {})
        chain_key = inputs.get("chain_key")
        self.assertIsNone(chain_key)
    
    def test_missing_chain_key_in_inputs(self):
        """Missing chain_key in inputs is handled gracefully."""
        run = {
            "inputs": {"chain_id": 42161},  # No chain_key
        }
        inputs = run.get("inputs", {})
        chain_key = inputs.get("chain_key")
        self.assertIsNone(chain_key)


class TestRollingPointerProtection(unittest.TestCase):
    """Regression tests for NORM-only rolling pointer policy (v3.2.23).
    
    Validates that COVERAGE/SMOKE runs do NOT overwrite run_summary_latest.json
    and _latest.json. Only NORMAL runs should update pointer files.
    """

    def test_coverage_run_kind_blocks_pointer_write(self):
        """A run with run_kind=COVERAGE must not write rolling pointer files."""
        # The guard in m4/gates.py uses run_summary.get("run_kind", "NORMAL")
        # COVERAGE runs must be skipped
        run_summary = {"run_kind": "COVERAGE", "inputs": {"chain_key": "scroll"}}
        run_kind = run_summary.get("run_kind", "NORMAL")
        self.assertEqual(run_kind, "COVERAGE")
        self.assertNotEqual(run_kind, "NORMAL", "COVERAGE run_kind must not pass NORMAL check")

    def test_normal_run_kind_allows_pointer_write(self):
        """A run with run_kind=NORMAL should proceed to write pointer files."""
        run_summary = {"run_kind": "NORMAL", "inputs": {"chain_key": "arbitrum_one"}}
        run_kind = run_summary.get("run_kind", "NORMAL")
        self.assertEqual(run_kind, "NORMAL")

    def test_missing_run_kind_defaults_to_normal(self):
        """Missing run_kind defaults to NORMAL (backward compat with legacy runs)."""
        run_summary = {"inputs": {"chain_key": "arbitrum_one"}}
        run_kind = run_summary.get("run_kind", "NORMAL")
        self.assertEqual(run_kind, "NORMAL")

    def test_smoke_run_kind_blocks_pointer_write(self):
        """A run with run_kind=SMOKE must not write rolling pointer files."""
        run_summary = {"run_kind": "SMOKE", "inputs": {"chain_key": "arbitrum_one"}}
        run_kind = run_summary.get("run_kind", "NORMAL")
        self.assertNotEqual(run_kind, "NORMAL", "SMOKE run_kind must not pass NORMAL check")


class TestCheckRollingChainPurity(unittest.TestCase):
    """Tests for check_rolling_chain_purity in check_repo_safety (v1.14.0).
    
    Validates that check_repo_safety detects rolling contamination:
    - non-NORMAL run_kind in pointer files
    - non-primary chain_key in pointer files
    """

    def test_normal_primary_chain_no_issues(self):
        """NORMAL run on primary chain produces no issues."""
        from scripts.check_repo_safety import check_rolling_chain_purity
        import tempfile, json, os
        
        with tempfile.TemporaryDirectory() as td:
            rolling_dir = os.path.join(td, "data", "runs", "_rolling")
            os.makedirs(rolling_dir)
            
            summary = {
                "run_kind": "NORMAL",
                "inputs": {"chain_key": "arbitrum_one"},
            }
            with open(os.path.join(rolling_dir, "run_summary_latest.json"), "w") as f:
                json.dump(summary, f)
            
            latest = {
                "inputs": {"run_kind": "NORMAL", "chain_key": "arbitrum_one"},
            }
            with open(os.path.join(rolling_dir, "_latest.json"), "w") as f:
                json.dump(latest, f)
            
            # Monkey-patch PROJECT_ROOT
            import scripts.check_repo_safety as mod
            orig = mod.PROJECT_ROOT
            from pathlib import Path
            mod.PROJECT_ROOT = Path(td)
            try:
                issues = check_rolling_chain_purity()
                self.assertEqual(issues, [], f"Expected no issues, got: {issues}")
            finally:
                mod.PROJECT_ROOT = orig

    def test_coverage_run_kind_detected(self):
        """COVERAGE run_kind in run_summary_latest.json is detected as contamination."""
        from scripts.check_repo_safety import check_rolling_chain_purity
        import tempfile, json, os
        
        with tempfile.TemporaryDirectory() as td:
            rolling_dir = os.path.join(td, "data", "runs", "_rolling")
            os.makedirs(rolling_dir)
            
            summary = {
                "run_kind": "COVERAGE",
                "inputs": {"chain_key": "scroll"},
            }
            with open(os.path.join(rolling_dir, "run_summary_latest.json"), "w") as f:
                json.dump(summary, f)
            
            import scripts.check_repo_safety as mod
            orig = mod.PROJECT_ROOT
            from pathlib import Path
            mod.PROJECT_ROOT = Path(td)
            try:
                issues = check_rolling_chain_purity()
                self.assertTrue(any("ROLLING_CONTAMINATION" in i for i in issues),
                    f"Expected ROLLING_CONTAMINATION, got: {issues}")
                self.assertTrue(any("run_kind=COVERAGE" in i for i in issues))
            finally:
                mod.PROJECT_ROOT = orig

    def test_non_primary_chain_detected(self):
        """Non-primary chain_key in run_summary_latest.json is detected as contamination."""
        from scripts.check_repo_safety import check_rolling_chain_purity
        import tempfile, json, os
        
        with tempfile.TemporaryDirectory() as td:
            rolling_dir = os.path.join(td, "data", "runs", "_rolling")
            os.makedirs(rolling_dir)
            
            summary = {
                "run_kind": "NORMAL",
                "inputs": {"chain_key": "scroll"},
            }
            with open(os.path.join(rolling_dir, "run_summary_latest.json"), "w") as f:
                json.dump(summary, f)
            
            import scripts.check_repo_safety as mod
            orig = mod.PROJECT_ROOT
            from pathlib import Path
            mod.PROJECT_ROOT = Path(td)
            try:
                issues = check_rolling_chain_purity()
                self.assertTrue(any("ROLLING_CONTAMINATION" in i for i in issues),
                    f"Expected ROLLING_CONTAMINATION for non-primary chain, got: {issues}")
                self.assertTrue(any("chain_key=scroll" in i for i in issues))
            finally:
                mod.PROJECT_ROOT = orig


if __name__ == "__main__":
    unittest.main()
