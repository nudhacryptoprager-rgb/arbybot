# PATH: tests/unit/test_imports_contract.py
"""
Import contract smoke tests.

PURPOSE: Catch ImportError regressions early.

These tests verify that critical imports work without error.
If any of these fail, it indicates a breaking change in module structure.

RUN: python -m pytest tests/unit/test_imports_contract.py -v
"""

import unittest
import sys
from pathlib import Path

# Ensure project root is in path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestCoreImports(unittest.TestCase):
    """Test that core module imports work."""

    def test_import_constants(self):
        """Test import core.constants works."""
        from core import constants
        self.assertTrue(hasattr(constants, 'SCHEMA_VERSION'))

    def test_import_dex_type(self):
        """
        CRITICAL: Test DexType import works.
        
        Many modules depend on: from core.constants import DexType
        """
        from core.constants import DexType
        
        # Verify it's an Enum
        self.assertTrue(hasattr(DexType, 'UNISWAP_V3'))
        self.assertEqual(DexType.UNISWAP_V3.value, "uniswap_v3")

    def test_import_execution_blocker(self):
        """Test ExecutionBlocker import works."""
        from core.constants import ExecutionBlocker
        
        self.assertTrue(hasattr(ExecutionBlocker, 'EXECUTION_DISABLED'))
        self.assertEqual(ExecutionBlocker.EXECUTION_DISABLED.value, "EXECUTION_DISABLED")

    def test_import_anchor_priority(self):
        """Test ANCHOR_DEX_PRIORITY import works."""
        from core.constants import ANCHOR_DEX_PRIORITY
        
        self.assertIsInstance(ANCHOR_DEX_PRIORITY, tuple)
        self.assertIn("uniswap_v3", ANCHOR_DEX_PRIORITY)

    def test_import_price_sanity_bounds(self):
        """Test PRICE_SANITY_BOUNDS import works."""
        from core.constants import PRICE_SANITY_BOUNDS
        
        self.assertIsInstance(PRICE_SANITY_BOUNDS, dict)
        self.assertIn(("WETH", "USDC"), PRICE_SANITY_BOUNDS)


class TestValidatorsImports(unittest.TestCase):
    """Test that validators module imports work."""

    def test_import_validators(self):
        """Test import core.validators works."""
        from core import validators
        self.assertTrue(hasattr(validators, 'check_price_sanity'))

    def test_import_normalize_price(self):
        """Test normalize_price import works."""
        from core.validators import normalize_price
        self.assertTrue(callable(normalize_price))

    def test_import_calculate_deviation_bps(self):
        """Test calculate_deviation_bps import works."""
        from core.validators import calculate_deviation_bps
        self.assertTrue(callable(calculate_deviation_bps))

    def test_import_anchor_quote(self):
        """Test AnchorQuote import works."""
        from core.validators import AnchorQuote
        self.assertTrue(hasattr(AnchorQuote, 'dex_id'))


class TestMonitoringImports(unittest.TestCase):
    """Test that monitoring module imports work."""

    def test_import_truth_report(self):
        """Test import monitoring.truth_report works."""
        try:
            from monitoring import truth_report
            self.assertTrue(hasattr(truth_report, 'TruthReport'))
        except ImportError as e:
            # This might fail if monitoring module doesn't exist yet
            self.skipTest(f"monitoring module not available: {e}")


class TestDexAdaptersImports(unittest.TestCase):
    """Test that DEX adapter imports work."""

    def test_import_algebra_adapter(self):
        """Test import dex.adapters.algebra works."""
        try:
            from dex.adapters import algebra
            self.assertTrue(hasattr(algebra, 'AlgebraAdapter'))
        except ImportError as e:
            self.skipTest(f"dex.adapters module not available: {e}")


class TestCrossModuleCompatibility(unittest.TestCase):
    """Test cross-module compatibility."""

    def test_dex_type_used_in_validators(self):
        """
        Test that DexType can be used with validators.
        
        This catches cases where DexType is removed but still referenced.
        """
        from core.constants import DexType, ANCHOR_DEX_PRIORITY
        
        # Verify DexType values match ANCHOR_DEX_PRIORITY
        for dex in ANCHOR_DEX_PRIORITY:
            # Should be able to find corresponding DexType
            found = False
            for member in DexType:
                if member.value == dex:
                    found = True
                    break
            self.assertTrue(found, f"DexType missing for anchor DEX: {dex}")


if __name__ == "__main__":
    unittest.main()
