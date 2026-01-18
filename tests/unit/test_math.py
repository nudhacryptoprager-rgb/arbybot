# PATH: tests/unit/test_math.py
"""
Unit tests for core math utilities.
"""

import unittest
from decimal import Decimal

from core.math import (
    safe_decimal,
    bps_to_decimal,
    decimal_to_bps,
    calculate_pnl_bps,
    calculate_slippage_bps,
    normalize_to_decimals,
    denormalize_from_decimals,
)


class TestSafeDecimal(unittest.TestCase):
    """Tests for safe_decimal function."""
    
    def test_string_input(self):
        """Converts string to Decimal."""
        self.assertEqual(safe_decimal("123.45"), Decimal("123.45"))
    
    def test_int_input(self):
        """Converts int to Decimal."""
        self.assertEqual(safe_decimal(100), Decimal("100"))
    
    def test_decimal_input(self):
        """Passes through Decimal."""
        d = Decimal("123.45")
        self.assertEqual(safe_decimal(d), d)
    
    def test_none_input(self):
        """Returns default for None."""
        self.assertEqual(safe_decimal(None), Decimal("0"))
        self.assertEqual(safe_decimal(None, Decimal("10")), Decimal("10"))
    
    def test_invalid_input(self):
        """Returns default for invalid input."""
        self.assertEqual(safe_decimal("invalid"), Decimal("0"))


class TestBpsConversions(unittest.TestCase):
    """Tests for BPS conversion functions."""
    
    def test_bps_to_decimal(self):
        """Converts BPS to decimal fraction."""
        self.assertEqual(bps_to_decimal(100), Decimal("0.01"))
        self.assertEqual(bps_to_decimal(50), Decimal("0.005"))
        self.assertEqual(bps_to_decimal(10000), Decimal("1"))
    
    def test_decimal_to_bps(self):
        """Converts decimal fraction to BPS."""
        self.assertEqual(decimal_to_bps("0.01"), Decimal("100"))
        self.assertEqual(decimal_to_bps("0.005"), Decimal("50"))
        self.assertEqual(decimal_to_bps(Decimal("0.001")), Decimal("10"))


class TestCalculatePnlBps(unittest.TestCase):
    """Tests for calculate_pnl_bps function."""
    
    def test_positive_pnl(self):
        """Calculates positive PnL in BPS."""
        bps = calculate_pnl_bps("1", "100")
        self.assertEqual(bps, Decimal("100"))  # 1% = 100 bps
    
    def test_negative_pnl(self):
        """Calculates negative PnL in BPS."""
        bps = calculate_pnl_bps("-0.5", "100")
        self.assertEqual(bps, Decimal("-50"))
    
    def test_zero_notional(self):
        """Returns 0 for zero notional."""
        bps = calculate_pnl_bps("1", "0")
        self.assertEqual(bps, Decimal("0"))


class TestNormalization(unittest.TestCase):
    """Tests for token decimal normalization."""
    
    def test_normalize_to_decimals(self):
        """Normalizes wei to token units."""
        # 1e18 wei = 1 token for 18 decimals
        result = normalize_to_decimals("1000000000000000000", 18)
        self.assertEqual(result, Decimal("1"))
        
        # 1e6 units = 1 USDC for 6 decimals
        result = normalize_to_decimals("1000000", 6)
        self.assertEqual(result, Decimal("1"))
    
    def test_denormalize_from_decimals(self):
        """Denormalizes token units to wei."""
        # 1 token = 1e18 wei for 18 decimals
        result = denormalize_from_decimals("1", 18)
        self.assertEqual(result, 1000000000000000000)
        
        # 1 USDC = 1e6 units
        result = denormalize_from_decimals("1", 6)
        self.assertEqual(result, 1000000)


if __name__ == "__main__":
    unittest.main()