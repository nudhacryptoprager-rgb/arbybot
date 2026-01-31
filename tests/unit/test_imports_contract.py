# PATH: tests/unit/test_imports_contract.py
"""
Import contract smoke tests.

PURPOSE: Catch ImportError regressions EARLY.

RUN FIRST: python -m pytest tests/unit/test_imports_contract.py -v

CRITICAL CONTRACTS:
- DexType MUST be importable from core.constants
- TokenStatus MUST be importable from core.constants
- ExecutionBlocker MUST be importable from core.constants
- AnchorQuote.dex_id MUST be a required field
"""

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestCoreConstantsImports(unittest.TestCase):
    """Test core.constants imports."""

    def test_import_module(self):
        """Test import core.constants works."""
        from core import constants
        self.assertTrue(hasattr(constants, 'SCHEMA_VERSION'))

    def test_import_dex_type(self):
        """CRITICAL: Test DexType import."""
        from core.constants import DexType
        
        self.assertTrue(hasattr(DexType, 'UNISWAP_V3'))
        self.assertTrue(hasattr(DexType, 'SUSHISWAP_V3'))
        self.assertEqual(DexType.UNISWAP_V3.value, "uniswap_v3")

    def test_import_token_status(self):
        """CRITICAL: Test TokenStatus import."""
        from core.constants import TokenStatus
        
        self.assertTrue(hasattr(TokenStatus, 'ACTIVE'))
        self.assertTrue(hasattr(TokenStatus, 'BLACKLISTED'))
        self.assertEqual(TokenStatus.ACTIVE.value, "active")

    def test_import_execution_blocker(self):
        """Test ExecutionBlocker import."""
        from core.constants import ExecutionBlocker
        
        self.assertTrue(hasattr(ExecutionBlocker, 'EXECUTION_DISABLED'))
        self.assertEqual(ExecutionBlocker.EXECUTION_DISABLED.value, "EXECUTION_DISABLED")

    def test_import_current_execution_blocker(self):
        """Test CURRENT_EXECUTION_BLOCKER is EXECUTION_DISABLED."""
        from core.constants import CURRENT_EXECUTION_BLOCKER, ExecutionBlocker
        
        self.assertEqual(CURRENT_EXECUTION_BLOCKER, ExecutionBlocker.EXECUTION_DISABLED)

    def test_import_anchor_priority(self):
        """Test ANCHOR_DEX_PRIORITY import."""
        from core.constants import ANCHOR_DEX_PRIORITY
        
        self.assertIsInstance(ANCHOR_DEX_PRIORITY, tuple)
        self.assertIn("uniswap_v3", ANCHOR_DEX_PRIORITY)

    def test_import_price_sanity_bounds(self):
        """Test PRICE_SANITY_BOUNDS import."""
        from core.constants import PRICE_SANITY_BOUNDS
        
        self.assertIsInstance(PRICE_SANITY_BOUNDS, dict)
        self.assertIn(("WETH", "USDC"), PRICE_SANITY_BOUNDS)

    def test_dex_type_from_string(self):
        """Test DexType.from_string() works."""
        from core.constants import DexType
        
        result = DexType.from_string("uniswap_v3")
        self.assertEqual(result, DexType.UNISWAP_V3)


class TestCoreValidatorsImports(unittest.TestCase):
    """Test core.validators imports."""

    def test_import_module(self):
        """Test import core.validators works."""
        from core import validators
        self.assertTrue(hasattr(validators, 'check_price_sanity'))

    def test_import_normalize_price(self):
        """Test normalize_price import."""
        from core.validators import normalize_price
        self.assertTrue(callable(normalize_price))

    def test_import_calculate_deviation_bps(self):
        """Test calculate_deviation_bps import."""
        from core.validators import calculate_deviation_bps
        self.assertTrue(callable(calculate_deviation_bps))

    def test_import_anchor_quote(self):
        """Test AnchorQuote import."""
        from core.validators import AnchorQuote
        self.assertTrue(hasattr(AnchorQuote, 'dex_id'))
        self.assertTrue(hasattr(AnchorQuote, 'price'))

    def test_anchor_quote_dex_id_required(self):
        """CRITICAL: Test AnchorQuote.dex_id is required."""
        from core.validators import AnchorQuote
        from decimal import Decimal
        
        # Should work with dex_id
        quote = AnchorQuote(
            dex_id="uniswap_v3",
            price=Decimal("2600"),
            fee=500,
            pool_address="0x1234",
            block_number=100,
        )
        self.assertEqual(quote.dex_id, "uniswap_v3")

    def test_anchor_quote_is_from_anchor_dex(self):
        """Test AnchorQuote.is_from_anchor_dex property."""
        from core.validators import AnchorQuote
        from decimal import Decimal
        
        quote = AnchorQuote(
            dex_id="uniswap_v3",
            price=Decimal("2600"),
            fee=500,
            pool_address="0x1234",
            block_number=100,
        )
        self.assertTrue(quote.is_from_anchor_dex)


class TestCrossModuleCompat(unittest.TestCase):
    """Test cross-module compatibility."""

    def test_dex_type_in_anchor_priority(self):
        """Test DexType values match ANCHOR_DEX_PRIORITY."""
        from core.constants import DexType, ANCHOR_DEX_PRIORITY
        
        for dex in ANCHOR_DEX_PRIORITY:
            found = any(m.value == dex for m in DexType)
            self.assertTrue(found, f"DexType missing: {dex}")

    def test_execution_blocker_stage_agnostic(self):
        """Test CURRENT_EXECUTION_BLOCKER is stage-agnostic."""
        from core.constants import CURRENT_EXECUTION_BLOCKER
        
        # Should NOT contain M4 or M5 in the value
        val = CURRENT_EXECUTION_BLOCKER.value
        self.assertEqual(val, "EXECUTION_DISABLED")
        self.assertNotIn("M4", val)


if __name__ == "__main__":
    unittest.main()
