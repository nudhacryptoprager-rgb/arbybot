# PATH: tests/unit/test_confidence.py
"""
Unit tests for calculate_confidence function.

STEP 4: Import contract stability tests.
STEP 5: Confidence formula consistency tests.
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
    """STEP 4: Import contract tests."""

    def test_import_from_truth_report(self):
        """Can import calculate_confidence from monitoring.truth_report."""
        from monitoring.truth_report import calculate_confidence as conf_func
        self.assertTrue(callable(conf_func))

    def test_import_from_monitoring_package(self):
        """Can import calculate_confidence from monitoring package."""
        from monitoring import calculate_confidence as conf_func
        self.assertTrue(callable(conf_func))

    def test_import_contract_explicit(self):
        """
        STEP 4: Explicit import contract verification.
        
        This test explicitly verifies the import contract that must be stable.
        If this test fails, the module API has been broken.
        """
        # These imports MUST work
        from monitoring.truth_report import calculate_confidence
        from monitoring.truth_report import RPCHealthMetrics
        from monitoring.truth_report import TruthReport
        from monitoring.truth_report import build_truth_report
        from monitoring.truth_report import build_health_section
        from monitoring.truth_report import print_truth_report
        
        # Verify all are callable/classes
        self.assertTrue(callable(calculate_confidence))
        self.assertTrue(callable(build_truth_report))
        self.assertTrue(callable(build_health_section))
        self.assertTrue(callable(print_truth_report))
        
        # Verify classes can be instantiated
        metrics = RPCHealthMetrics()
        self.assertIsInstance(metrics, RPCHealthMetrics)
        
        report = TruthReport()
        self.assertIsInstance(report, TruthReport)


class TestPriceStabilityConsistency(unittest.TestCase):
    """STEP 5: Price stability factor consistency."""

    def test_stability_never_zero_when_passed(self):
        """
        STEP 5: Regression test for confidence consistency.
        
        If price_sanity_passed > 0, the price_stability_factor
        used in confidence scoring must not be 0.0.
        """
        from monitoring.truth_report import calculate_price_stability_factor

        # Scenario that previously caused bug: passed > 0 but factor = 0
        test_cases = [
            (1, 4, 3),   # 1 passed, 3 failed
            (2, 4, 2),   # 2 passed, 2 failed
            (3, 4, 1),   # 3 passed, 1 failed
            (4, 4, 0),   # 4 passed, 0 failed
            (1, 1, 0),   # 1 passed, 0 failed
        ]

        for passed, fetched, failed in test_cases:
            with self.subTest(passed=passed, fetched=fetched, failed=failed):
                factor = calculate_price_stability_factor(passed, fetched, failed)
                self.assertGreater(
                    factor, 0.0,
                    f"Factor must be > 0 when passed={passed}, but got {factor}"
                )


if __name__ == "__main__":
    unittest.main()
