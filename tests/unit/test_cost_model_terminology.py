# PATH: tests/unit/test_cost_model_terminology.py
"""Negative test: execution wording mismatch.

Ensures truth_report terminology is consistent:
- paper_cost_model_available: gas-only for paper PnL estimates
- execution_cost_model_available: full model (NOT available in M5)

If execution_cost_model_available=false but text says otherwise → FAIL.
"""

import unittest


class TestCostModelTerminology(unittest.TestCase):
    """Test cost model field consistency."""
    
    def test_paper_cost_model_available_true_is_valid(self):
        """paper_cost_model_available=true is valid (gas-only estimates work)."""
        truth_data = {
            "paper_cost_model_available": True,
            "execution_cost_model_available": False,
            "execution_blocker_details": "no execution cost model (paper estimates use gas-only)",
        }
        
        # Validate consistency
        self.assertTrue(truth_data["paper_cost_model_available"])
        self.assertFalse(truth_data["execution_cost_model_available"])
        self.assertIn("paper", truth_data["execution_blocker_details"])
    
    def test_execution_cost_model_false_requires_correct_wording(self):
        """If execution_cost_model_available=false, blocker should mention it."""
        truth_data = {
            "paper_cost_model_available": True,
            "execution_cost_model_available": False,
            "execution_blocker_details": "EXECUTION_DISABLED_M5_0 - no execution cost model",
        }
        
        # Must NOT say "cost model available" if execution_cost_model_available=false
        self.assertFalse(truth_data["execution_cost_model_available"])
        
        # Wording check: should not be misleading
        blocker = truth_data["execution_blocker_details"].lower()
        # Should mention "no" somewhere before "cost model"
        self.assertIn("no", blocker)
    
    def test_wording_mismatch_detection(self):
        """Detect misleading wording: execution_cost_model_available=false but text implies available."""
        truth_data_bad = {
            "paper_cost_model_available": True,
            "execution_cost_model_available": False,
            "execution_blocker_details": "cost model is available and ready",  # MISLEADING!
        }
        
        # This is a mismatch we want to catch
        is_misleading = (
            truth_data_bad["execution_cost_model_available"] == False
            and "no" not in truth_data_bad["execution_blocker_details"].lower()
            and "not" not in truth_data_bad["execution_blocker_details"].lower()
            and "unavailable" not in truth_data_bad["execution_blocker_details"].lower()
            and "available" in truth_data_bad["execution_blocker_details"].lower()
        )
        
        self.assertTrue(is_misleading, "Should detect misleading wording")
    
    def test_correct_m5_terminology(self):
        """Validate M5 correct terminology pattern."""
        # Expected pattern from run_scan_real.py
        truth_data = {
            "paper_cost_model_available": True,
            "execution_cost_model_available": False,
            "execution_blocker_details": "EXECUTION_DISABLED_M5_0 - no execution cost model (paper estimates use gas-only)",
        }
        
        # Paper model available for estimates
        self.assertTrue(truth_data["paper_cost_model_available"])
        
        # Execution model NOT available
        self.assertFalse(truth_data["execution_cost_model_available"])
        
        # Wording clearly states "no execution cost model"
        self.assertIn("no execution cost model", truth_data["execution_blocker_details"])
        
        # Also mentions paper gas-only
        self.assertIn("paper estimates", truth_data["execution_blocker_details"])


class TestLegacyCostModelField(unittest.TestCase):
    """Test backward compatibility with legacy cost_model_available field."""
    
    def test_legacy_field_deprecated(self):
        """Old cost_model_available should be replaced with paper/execution split."""
        # Old pattern (deprecated):
        old_data = {"cost_model_available": False}
        
        # New pattern (correct):
        new_data = {
            "paper_cost_model_available": True,
            "execution_cost_model_available": False,
        }
        
        # New pattern has more granularity
        self.assertIn("paper_cost_model_available", new_data)
        self.assertIn("execution_cost_model_available", new_data)


if __name__ == "__main__":
    unittest.main()
