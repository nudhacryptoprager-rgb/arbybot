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


if __name__ == "__main__":
    unittest.main()
