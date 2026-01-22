# PATH: tests/unit/test_confidence.py
"""
Unit tests for calculate_confidence function.

Tests confidence scoring for opportunities.
"""

import unittest
from monitoring.truth_report import calculate_confidence


class TestCalculateConfidence(unittest.TestCase):
    """Tests for calculate_confidence function."""
    
    def test_calculate_confidence_exists(self):
        """calculate_confidence is callable."""
        self.assertTrue(callable(calculate_confidence))
    
    def test_calculate_confidence_perfect_score(self):
        """All perfect inputs return 1.0."""
        score = calculate_confidence(
            quote_fetch_rate=1.0,
            quote_gate_pass_rate=1.0,
            rpc_success_rate=1.0,
            freshness_score=1.0,
            adapter_reliability=1.0,
        )
        self.assertEqual(score, 1.0)
    
    def test_calculate_confidence_zero_score(self):
        """All zero inputs return 0.0."""
        score = calculate_confidence(
            quote_fetch_rate=0.0,
            quote_gate_pass_rate=0.0,
            rpc_success_rate=0.0,
            freshness_score=0.0,
            adapter_reliability=0.0,
        )
        self.assertEqual(score, 0.0)
    
    def test_calculate_confidence_mixed_score(self):
        """Mixed inputs return weighted average."""
        score = calculate_confidence(
            quote_fetch_rate=0.5,
            quote_gate_pass_rate=0.5,
            rpc_success_rate=0.5,
            freshness_score=0.5,
            adapter_reliability=0.5,
        )
        self.assertEqual(score, 0.5)
    
    def test_calculate_confidence_clamped_high(self):
        """Scores above 1.0 are clamped to 1.0."""
        score = calculate_confidence(
            quote_fetch_rate=2.0,
            quote_gate_pass_rate=2.0,
            rpc_success_rate=2.0,
            freshness_score=2.0,
            adapter_reliability=2.0,
        )
        self.assertLessEqual(score, 1.0)
    
    def test_calculate_confidence_clamped_low(self):
        """Scores below 0.0 are clamped to 0.0."""
        score = calculate_confidence(
            quote_fetch_rate=-1.0,
            quote_gate_pass_rate=-1.0,
            rpc_success_rate=-1.0,
            freshness_score=-1.0,
            adapter_reliability=-1.0,
        )
        self.assertGreaterEqual(score, 0.0)
    
    def test_calculate_confidence_weights(self):
        """Weights are applied correctly."""
        # Only quote_fetch_rate = 1, others = 0
        # Weight for quote_fetch is 0.25
        score = calculate_confidence(
            quote_fetch_rate=1.0,
            quote_gate_pass_rate=0.0,
            rpc_success_rate=0.0,
            freshness_score=0.0,
            adapter_reliability=0.0,
        )
        self.assertAlmostEqual(score, 0.25, places=2)
    
    def test_calculate_confidence_default_args(self):
        """Default args for freshness and adapter work."""
        score = calculate_confidence(
            quote_fetch_rate=1.0,
            quote_gate_pass_rate=1.0,
            rpc_success_rate=1.0,
        )
        # Should work and return a valid score
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)
    
    def test_calculate_confidence_return_type(self):
        """Returns float."""
        score = calculate_confidence(0.5, 0.5, 0.5)
        self.assertIsInstance(score, float)


class TestCalculateConfidenceImport(unittest.TestCase):
    """Tests for calculate_confidence import compatibility."""
    
    def test_import_from_truth_report(self):
        """Can import calculate_confidence from monitoring.truth_report."""
        from monitoring.truth_report import calculate_confidence as conf_func
        self.assertTrue(callable(conf_func))
    
    def test_import_from_monitoring_package(self):
        """Can import calculate_confidence from monitoring package."""
        from monitoring import calculate_confidence as conf_func
        self.assertTrue(callable(conf_func))


if __name__ == "__main__":
    unittest.main()