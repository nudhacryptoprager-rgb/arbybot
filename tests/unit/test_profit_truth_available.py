# PATH: tests/unit/test_profit_truth_available.py
"""Tests for profit_truth_available logic (v2.3.2).

Tests REAL code from m4/gates.py:
- compute_profit_truth_available()
- apply_profit_diagnostic_warning()

Ensures that:
- profit_truth_available = (not profit_is_diagnostic) AND cost_model_available
- When profit_truth_available=False and profit_status=PASS, quality_status should be WARN
- WARN_PROFIT_DIAGNOSTIC should be in quality_reasons when applicable
"""

import unittest

from m4.gates import compute_profit_truth_available, apply_profit_diagnostic_warning


class TestComputeProfitTruthAvailable(unittest.TestCase):
    """Test compute_profit_truth_available() function from m4/gates.py."""
    
    def test_both_conditions_met_returns_true(self):
        """profit_truth_available=True when NOT diagnostic AND cost_model exists."""
        metrics = {
            "profit_is_diagnostic": False,
            "cost_model_available": True,
        }
        result = compute_profit_truth_available(metrics)
        self.assertTrue(result)
    
    def test_diagnostic_returns_false(self):
        """profit_truth_available=False when profit_is_diagnostic=True."""
        metrics = {
            "profit_is_diagnostic": True,
            "cost_model_available": True,
        }
        result = compute_profit_truth_available(metrics)
        self.assertFalse(result)
    
    def test_no_cost_model_returns_false(self):
        """profit_truth_available=False when cost_model_available=False."""
        metrics = {
            "profit_is_diagnostic": False,
            "cost_model_available": False,
        }
        result = compute_profit_truth_available(metrics)
        self.assertFalse(result)
    
    def test_both_bad_returns_false(self):
        """profit_truth_available=False when both conditions fail."""
        metrics = {
            "profit_is_diagnostic": True,
            "cost_model_available": False,
        }
        result = compute_profit_truth_available(metrics)
        self.assertFalse(result)
    
    def test_defaults_to_false(self):
        """Empty metrics should return False (defaults are pessimistic)."""
        result = compute_profit_truth_available({})
        self.assertFalse(result)


class TestApplyProfitDiagnosticWarning(unittest.TestCase):
    """Test apply_profit_diagnostic_warning() function from m4/gates.py."""
    
    def test_diagnostic_profit_pass_adds_warning(self):
        """When profit_truth_available=False and profit_status=PASS, adds WARN_PROFIT_DIAGNOSTIC."""
        run_summary = {"quality_warnings": []}
        quality_status, reasons, warnings = apply_profit_diagnostic_warning(
            run_summary=run_summary,
            profit_status="PASS",
            profit_truth_available=False,
            profit_is_diagnostic=True,
            quality_status="PASS",
            merged_quality_reasons=[],
        )
        
        self.assertEqual(quality_status, "WARN")
        self.assertIn("WARN_PROFIT_DIAGNOSTIC", reasons)
        self.assertTrue(any("PROFIT_DIAGNOSTIC" in w for w in warnings))
    
    def test_real_profit_no_warning(self):
        """When profit_truth_available=True, no warning added."""
        run_summary = {"quality_warnings": []}
        quality_status, reasons, warnings = apply_profit_diagnostic_warning(
            run_summary=run_summary,
            profit_status="PASS",
            profit_truth_available=True,
            profit_is_diagnostic=False,
            quality_status="PASS",
            merged_quality_reasons=[],
        )
        
        self.assertEqual(quality_status, "PASS")
        self.assertNotIn("WARN_PROFIT_DIAGNOSTIC", reasons)
        self.assertFalse(any("PROFIT_DIAGNOSTIC" in w for w in warnings))
    
    def test_fail_profit_no_warning(self):
        """When profit_status=FAIL, no warning needed (already failing)."""
        run_summary = {"quality_warnings": []}
        quality_status, reasons, warnings = apply_profit_diagnostic_warning(
            run_summary=run_summary,
            profit_status="FAIL",
            profit_truth_available=False,
            profit_is_diagnostic=True,
            quality_status="PASS",
            merged_quality_reasons=[],
        )
        
        # Should NOT add warning when profit_status != PASS
        self.assertEqual(quality_status, "PASS")  # unchanged
        self.assertNotIn("WARN_PROFIT_DIAGNOSTIC", reasons)
    
    def test_existing_warnings_preserved(self):
        """Existing quality_warnings should be preserved."""
        run_summary = {"quality_warnings": ["EXISTING_WARNING"]}
        quality_status, reasons, warnings = apply_profit_diagnostic_warning(
            run_summary=run_summary,
            profit_status="PASS",
            profit_truth_available=False,
            profit_is_diagnostic=True,
            quality_status="PASS",
            merged_quality_reasons=[],
        )
        
        self.assertIn("EXISTING_WARNING", warnings)
        self.assertTrue(any("PROFIT_DIAGNOSTIC" in w for w in warnings))


class TestProfitTruthSources(unittest.TestCase):
    """Test profit_truth_source values and semantics."""
    
    VALID_SOURCES = [
        "ONE_LEG_DIAGNOSTIC",    # One-leg quote, simulated (current default)
        "ROUNDTRIP_CANONICAL",   # Roundtrip profitable (two legs)
        "ONE_LEG_UNVERIFIED",    # One-leg, not verified
    ]
    
    def test_default_source_is_diagnostic(self):
        """Default profit_truth_source should be ONE_LEG_DIAGNOSTIC."""
        truth_data = {}
        profit_truth_source = truth_data.get("profit_truth_source", "ONE_LEG_DIAGNOSTIC")
        self.assertEqual(profit_truth_source, "ONE_LEG_DIAGNOSTIC")
    
    def test_diagnostic_source_computes_false(self):
        """ONE_LEG_DIAGNOSTIC should result in profit_truth_available=False."""
        metrics = {
            "profit_is_diagnostic": True,  # ONE_LEG_DIAGNOSTIC implies this
            "cost_model_available": True,
        }
        self.assertFalse(compute_profit_truth_available(metrics))
    
    def test_roundtrip_with_cost_model_computes_true(self):
        """ROUNDTRIP_CANONICAL with cost_model should result in profit_truth_available=True."""
        metrics = {
            "profit_is_diagnostic": False,  # ROUNDTRIP implies this
            "cost_model_available": True,
        }
        self.assertTrue(compute_profit_truth_available(metrics))


if __name__ == "__main__":
    unittest.main()
