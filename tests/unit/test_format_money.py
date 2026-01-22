# PATH: tests/unit/test_format_money.py
"""
Unit tests for format_money module.

Comprehensive tests for money formatting utilities.
"""

import unittest
from decimal import Decimal

from core.format_money import (
    format_money,
    format_money_short,
    format_bps,
    format_pct,
)


class TestFormatMoney(unittest.TestCase):
    """Tests for format_money function."""
    
    def test_format_string_input(self):
        """Formats string input correctly."""
        self.assertEqual(format_money("123.456789"), "123.456789")
        self.assertEqual(format_money("0"), "0.000000")
        self.assertEqual(format_money("1000"), "1000.000000")
    
    def test_format_decimal_input(self):
        """Formats Decimal input correctly."""
        self.assertEqual(format_money(Decimal("123.456789")), "123.456789")
        self.assertEqual(format_money(Decimal("0")), "0.000000")
    
    def test_format_int_input(self):
        """Formats int input correctly."""
        self.assertEqual(format_money(100), "100.000000")
        self.assertEqual(format_money(0), "0.000000")
    
    def test_format_float_input(self):
        """Formats float input correctly (legacy support)."""
        result = format_money(100.5)
        self.assertEqual(result, "100.500000")
    
    def test_format_none_input(self):
        """Returns zero for None input."""
        self.assertEqual(format_money(None), "0.000000")
    
    def test_format_empty_string(self):
        """Returns zero for empty string."""
        self.assertEqual(format_money(""), "0.000000")
        self.assertEqual(format_money("   "), "0.000000")
    
    def test_format_invalid_string(self):
        """Returns zero for invalid string."""
        self.assertEqual(format_money("not_a_number"), "0.000000")
        self.assertEqual(format_money("abc123"), "0.000000")
    
    def test_format_custom_decimals(self):
        """Respects custom decimal places."""
        self.assertEqual(format_money("123.456", decimals=2), "123.46")
        self.assertEqual(format_money("123.456", decimals=0), "123")
        self.assertEqual(format_money("123.456", decimals=4), "123.4560")
    
    def test_rounding_half_up(self):
        """Uses ROUND_HALF_UP rounding."""
        # 0.005 with 2 decimals should round to 0.01
        self.assertEqual(format_money(Decimal("0.005"), decimals=2), "0.01")
        self.assertEqual(format_money("0.005", decimals=2), "0.01")
        
        # 0.004 with 2 decimals should round to 0.00
        self.assertEqual(format_money(Decimal("0.004"), decimals=2), "0.00")
        
        # 0.015 with 2 decimals should round to 0.02
        self.assertEqual(format_money(Decimal("0.015"), decimals=2), "0.02")
        
        # 0.025 with 2 decimals should round to 0.03 (banker's rounding would give 0.02)
        self.assertEqual(format_money(Decimal("0.025"), decimals=2), "0.03")
    
    def test_negative_numbers(self):
        """Handles negative numbers correctly."""
        self.assertEqual(format_money("-123.45"), "-123.450000")
        self.assertEqual(format_money(Decimal("-0.005"), decimals=2), "-0.01")
    
    def test_large_numbers(self):
        """Handles large numbers correctly."""
        self.assertEqual(format_money("1000000000.123456"), "1000000000.123456")
    
    def test_small_numbers(self):
        """Handles small numbers correctly."""
        self.assertEqual(format_money("0.000001"), "0.000001")
        self.assertEqual(format_money("0.0000001", decimals=7), "0.0000001")


class TestFormatMoneyShort(unittest.TestCase):
    """Tests for format_money_short function."""
    
    def test_default_two_decimals(self):
        """Uses 2 decimal places by default."""
        self.assertEqual(format_money_short("123.456"), "123.46")
        self.assertEqual(format_money_short("123.454"), "123.45")
    
    def test_rounding_half_up(self):
        """Uses ROUND_HALF_UP."""
        self.assertEqual(format_money_short(Decimal("0.005")), "0.01")
        self.assertEqual(format_money_short("0.005"), "0.01")
    
    def test_custom_decimals(self):
        """Allows custom decimals."""
        self.assertEqual(format_money_short("123.456", decimals=1), "123.5")


class TestFormatBps(unittest.TestCase):
    """Tests for format_bps function."""
    
    def test_format_bps(self):
        """Formats basis points with 2 decimals."""
        self.assertEqual(format_bps("12.345"), "12.35")
        self.assertEqual(format_bps(50), "50.00")
        self.assertEqual(format_bps(Decimal("100.5")), "100.50")


class TestFormatPct(unittest.TestCase):
    """Tests for format_pct function."""
    
    def test_format_pct(self):
        """Formats percentage with 4 decimals."""
        self.assertEqual(format_pct("0.1234"), "0.1234")
        self.assertEqual(format_pct("1.23456"), "1.2346")
        self.assertEqual(format_pct(Decimal("0.00005")), "0.0001")


if __name__ == "__main__":
    unittest.main()