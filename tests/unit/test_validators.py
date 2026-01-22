# PATH: tests/unit/test_validators.py
"""
Tests for validation utilities.
"""

import unittest
from decimal import Decimal

from utils.validators import (
    is_valid_address,
    is_valid_money_string,
    validate_no_float,
    safe_decimal,
    clamp,
)


class TestIsValidAddress(unittest.TestCase):
    """Tests for is_valid_address."""
    
    def test_valid_address(self):
        """Valid address returns True."""
        self.assertTrue(is_valid_address("0x1234567890abcdef1234567890abcdef12345678"))
        self.assertTrue(is_valid_address("0xABCDEF1234567890ABCDEF1234567890ABCDEF12"))
    
    def test_invalid_address_no_prefix(self):
        """Address without 0x prefix is invalid."""
        self.assertFalse(is_valid_address("1234567890abcdef1234567890abcdef12345678"))
    
    def test_invalid_address_wrong_length(self):
        """Address with wrong length is invalid."""
        self.assertFalse(is_valid_address("0x1234"))
        self.assertFalse(is_valid_address("0x" + "a" * 50))
    
    def test_invalid_address_non_hex(self):
        """Address with non-hex chars is invalid."""
        self.assertFalse(is_valid_address("0xGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGGG"))
    
    def test_non_string_input(self):
        """Non-string input returns False."""
        self.assertFalse(is_valid_address(None))
        self.assertFalse(is_valid_address(123))


class TestIsValidMoneyString(unittest.TestCase):
    """Tests for is_valid_money_string."""
    
    def test_valid_money_strings(self):
        """Valid money strings return True."""
        self.assertTrue(is_valid_money_string("123.456"))
        self.assertTrue(is_valid_money_string("0.000001"))
        self.assertTrue(is_valid_money_string("-100.50"))
        self.assertTrue(is_valid_money_string("0"))
    
    def test_invalid_money_strings(self):
        """Invalid strings return False."""
        self.assertFalse(is_valid_money_string("abc"))
        self.assertFalse(is_valid_money_string(""))
        self.assertFalse(is_valid_money_string("12.34.56"))
    
    def test_non_string_input(self):
        """Non-string input returns False."""
        self.assertFalse(is_valid_money_string(None))
        self.assertFalse(is_valid_money_string(123.45))


class TestValidateNoFloat(unittest.TestCase):
    """Tests for validate_no_float."""
    
    def test_no_floats(self):
        """Object with no floats returns empty list."""
        obj = {
            "string": "hello",
            "int": 123,
            "decimal": Decimal("1.5"),
            "nested": {"a": "b", "c": 1},
            "list": [1, 2, "three"],
        }
        
        self.assertEqual(validate_no_float(obj), [])
    
    def test_float_in_dict(self):
        """Float in dict is detected."""
        obj = {"value": 1.5}
        
        paths = validate_no_float(obj)
        self.assertEqual(paths, ["value"])
    
    def test_float_in_nested_dict(self):
        """Float in nested dict is detected."""
        obj = {"outer": {"inner": 1.5}}
        
        paths = validate_no_float(obj)
        self.assertEqual(paths, ["outer.inner"])
    
    def test_float_in_list(self):
        """Float in list is detected."""
        obj = {"items": [1, 2.5, 3]}
        
        paths = validate_no_float(obj)
        self.assertEqual(paths, ["items[1]"])


class TestSafeDecimal(unittest.TestCase):
    """Tests for safe_decimal."""
    
    def test_string_input(self):
        """Converts string to Decimal."""
        self.assertEqual(safe_decimal("123.45"), Decimal("123.45"))
    
    def test_int_input(self):
        """Converts int to Decimal."""
        self.assertEqual(safe_decimal(100), Decimal("100"))
    
    def test_decimal_input(self):
        """Passes through Decimal."""
        d = Decimal("1.5")
        self.assertEqual(safe_decimal(d), d)
    
    def test_none_input(self):
        """Returns None for None input (default)."""
        self.assertIsNone(safe_decimal(None))
    
    def test_none_with_default(self):
        """Returns default for None input."""
        self.assertEqual(safe_decimal(None, Decimal("0")), Decimal("0"))
    
    def test_invalid_input(self):
        """Returns default for invalid input."""
        self.assertIsNone(safe_decimal("invalid"))
        self.assertEqual(safe_decimal("invalid", Decimal("0")), Decimal("0"))


class TestClamp(unittest.TestCase):
    """Tests for clamp."""
    
    def test_value_in_range(self):
        """Value in range is unchanged."""
        self.assertEqual(clamp(0.5, 0.0, 1.0), 0.5)
    
    def test_value_below_min(self):
        """Value below min is clamped."""
        self.assertEqual(clamp(-1.0, 0.0, 1.0), 0.0)
    
    def test_value_above_max(self):
        """Value above max is clamped."""
        self.assertEqual(clamp(2.0, 0.0, 1.0), 1.0)


if __name__ == "__main__":
    unittest.main()