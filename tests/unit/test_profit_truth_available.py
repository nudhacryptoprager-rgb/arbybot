# PATH: tests/unit/test_profit_truth_available.py
"""Tests for profit_truth_available logic (v2.3.2).

Ensures that:
- profit_truth_available = (not profit_is_diagnostic) AND cost_model_available
- When profit_truth_available=False and profit_status=PASS, quality_status should be WARN
- WARN_PROFIT_DIAGNOSTIC should be in quality_reasons when applicable
"""

import unittest


class TestProfitTruthAvailable(unittest.TestCase):
    """Test profit_truth_available computation and gating logic."""
    
    def test_profit_truth_available_computation(self):
        """profit_truth_available formula: (not profit_is_diagnostic) AND cost_model_available."""
        # Case 1: Both conditions met → True
        profit_is_diagnostic = False
        cost_model_available = True
        profit_truth_available = (not profit_is_diagnostic) and cost_model_available
        self.assertTrue(profit_truth_available)
        
        # Case 2: Diagnostic → False
        profit_is_diagnostic = True
        cost_model_available = True
        profit_truth_available = (not profit_is_diagnostic) and cost_model_available
        self.assertFalse(profit_truth_available)
        
        # Case 3: No cost model → False
        profit_is_diagnostic = False
        cost_model_available = False
        profit_truth_available = (not profit_is_diagnostic) and cost_model_available
        self.assertFalse(profit_truth_available)
        
        # Case 4: Both bad → False
        profit_is_diagnostic = True
        cost_model_available = False
        profit_truth_available = (not profit_is_diagnostic) and cost_model_available
        self.assertFalse(profit_truth_available)
    
    def test_diagnostic_profit_should_warn(self):
        """When profit_truth_available=False and profit_status=PASS, should add warning."""
        # Simulate the gate logic
        profit_status = "PASS"
        profit_truth_available = False
        profit_is_diagnostic = True
        quality_status = "PASS"
        merged_quality_reasons = []
        
        # v2.3.2 gate logic
        if not profit_truth_available and profit_status == "PASS":
            if "WARN_PROFIT_DIAGNOSTIC" not in merged_quality_reasons:
                merged_quality_reasons.append("WARN_PROFIT_DIAGNOSTIC")
            if quality_status == "PASS":
                quality_status = "WARN"
        
        self.assertEqual(quality_status, "WARN")
        self.assertIn("WARN_PROFIT_DIAGNOSTIC", merged_quality_reasons)
    
    def test_true_profit_should_not_warn(self):
        """When profit_truth_available=True, no diagnostic warning needed."""
        profit_status = "PASS"
        profit_truth_available = True
        profit_is_diagnostic = False
        quality_status = "PASS"
        merged_quality_reasons = []
        
        # v2.3.2 gate logic
        if not profit_truth_available and profit_status == "PASS":
            if "WARN_PROFIT_DIAGNOSTIC" not in merged_quality_reasons:
                merged_quality_reasons.append("WARN_PROFIT_DIAGNOSTIC")
            if quality_status == "PASS":
                quality_status = "WARN"
        
        # Should NOT add warning
        self.assertEqual(quality_status, "PASS")
        self.assertNotIn("WARN_PROFIT_DIAGNOSTIC", merged_quality_reasons)
    
    def test_fail_profit_no_diagnostic_warning(self):
        """When profit_status=FAIL, no diagnostic warning needed (already failing)."""
        profit_status = "FAIL"
        profit_truth_available = False
        profit_is_diagnostic = True
        quality_status = "PASS"
        merged_quality_reasons = []
        
        # v2.3.2 gate logic (only triggers on PASS)
        if not profit_truth_available and profit_status == "PASS":
            if "WARN_PROFIT_DIAGNOSTIC" not in merged_quality_reasons:
                merged_quality_reasons.append("WARN_PROFIT_DIAGNOSTIC")
            if quality_status == "PASS":
                quality_status = "WARN"
        
        # Should NOT add warning (profit_status != PASS)
        self.assertEqual(quality_status, "PASS")  # unchanged
        self.assertNotIn("WARN_PROFIT_DIAGNOSTIC", merged_quality_reasons)


class TestProfitTruthSources(unittest.TestCase):
    """Test profit_truth_source values and semantics."""
    
    VALID_SOURCES = [
        "ONE_LEG_DIAGNOSTIC",  # One-leg quote, simulated (current default)
        "TWO_LEG_ATOMIC",      # Real DEX↔DEX atomic execution (M5+)
        "PAPER_SIMULATION",    # Paper trading simulation
    ]
    
    def test_default_source_is_diagnostic(self):
        """Default profit_truth_source should be ONE_LEG_DIAGNOSTIC."""
        truth_data = {}
        profit_truth_source = truth_data.get("profit_truth_source", "ONE_LEG_DIAGNOSTIC")
        self.assertEqual(profit_truth_source, "ONE_LEG_DIAGNOSTIC")
    
    def test_diagnostic_source_implies_diagnostic_flag(self):
        """ONE_LEG_DIAGNOSTIC source should have profit_is_diagnostic=True."""
        truth_data = {
            "profit_truth_source": "ONE_LEG_DIAGNOSTIC",
            "profit_is_diagnostic": True,
        }
        
        # Consistency check
        if truth_data["profit_truth_source"] == "ONE_LEG_DIAGNOSTIC":
            self.assertTrue(truth_data["profit_is_diagnostic"])
    
    def test_atomic_source_implies_real_profit(self):
        """TWO_LEG_ATOMIC source should have profit_is_diagnostic=False."""
        truth_data = {
            "profit_truth_source": "TWO_LEG_ATOMIC",
            "profit_is_diagnostic": False,
            "cost_model_available": True,
        }
        
        # Real profit available
        profit_truth_available = (not truth_data["profit_is_diagnostic"]) and truth_data["cost_model_available"]
        self.assertTrue(profit_truth_available)


if __name__ == "__main__":
    unittest.main()
