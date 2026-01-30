# PATH: tests/unit/test_error_codes.py
"""
Unit tests for ErrorCode contract.

M5_0: Ensures all ErrorCode values used in codebase actually exist in the enum.
Prevents runtime crashes from typos or missing codes.

Run: python -m pytest tests/unit/test_error_codes.py -v
"""

import ast
import re
import unittest
from pathlib import Path
from typing import Set

from core.exceptions import ErrorCode


class TestErrorCodeContract(unittest.TestCase):
    """Test that all ErrorCode usages in codebase are valid."""
    
    # Files to scan for ErrorCode usage
    SCAN_PATTERNS = [
        "strategy/**/*.py",
        "monitoring/**/*.py",
        "core/**/*.py",
        "dex/**/*.py",
    ]
    
    # Known string codes used directly (not via enum)
    KNOWN_STRING_CODES = {
        "PRICE_SANITY_FAILED",
        "PRICE_SANITY_FAIL",  # Legacy
        "INVALID_SIZE",
        "GATE_FAIL",
        "MINIMUM_REALISM_FAIL",
        "INFRA_RPC_ERROR",
        "QUOTE_REVERT",
    }
    
    def get_all_error_codes(self) -> Set[str]:
        """Get all valid ErrorCode values."""
        return {code.value for code in ErrorCode}
    
    def find_errorcode_usages(self, filepath: Path) -> Set[str]:
        """
        Find all ErrorCode.XXXX usages in a file.
        
        Returns set of code names (e.g., "INFRA_RPC_ERROR")
        """
        usages = set()
        
        try:
            content = filepath.read_text()
        except Exception:
            return usages
        
        # Pattern: ErrorCode.SOMETHING
        pattern = r'ErrorCode\.([A-Z_]+)'
        matches = re.findall(pattern, content)
        usages.update(matches)
        
        return usages
    
    def find_string_code_usages(self, filepath: Path) -> Set[str]:
        """
        Find string error codes used directly.
        
        Returns set of string codes like "PRICE_SANITY_FAILED"
        """
        usages = set()
        
        try:
            content = filepath.read_text()
        except Exception:
            return usages
        
        # Pattern: error_code = "SOMETHING" or reject_reason = "SOMETHING"
        patterns = [
            r'error_code\s*=\s*["\']([A-Z_]+)["\']',
            r'reject_reason\s*=\s*["\']([A-Z_]+)["\']',
            r'"reject_reason":\s*["\']([A-Z_]+)["\']',
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, content)
            usages.update(matches)
        
        return usages
    
    def test_all_errorcode_enum_usages_exist(self):
        """Verify all ErrorCode.XXXX usages reference valid enum members."""
        project_root = Path(__file__).parent.parent.parent
        valid_codes = self.get_all_error_codes()
        
        # Also include enum member names (not just values)
        valid_names = {code.name for code in ErrorCode}
        
        all_usages = set()
        files_scanned = 0
        
        for pattern in self.SCAN_PATTERNS:
            for filepath in project_root.glob(pattern):
                if "__pycache__" in str(filepath):
                    continue
                usages = self.find_errorcode_usages(filepath)
                all_usages.update(usages)
                files_scanned += 1
        
        # Check each usage exists
        invalid_usages = all_usages - valid_names
        
        self.assertEqual(
            invalid_usages,
            set(),
            f"Invalid ErrorCode usages found: {invalid_usages}\n"
            f"Valid codes: {sorted(valid_names)}"
        )
        
        # Sanity check: we actually scanned some files
        self.assertGreater(files_scanned, 0, "No files scanned!")
    
    def test_common_string_codes_exist_in_enum(self):
        """Verify common string codes have corresponding enum values."""
        valid_codes = self.get_all_error_codes()
        
        # These string codes SHOULD exist in ErrorCode enum
        required_codes = {
            "PRICE_SANITY_FAILED",
            "INFRA_RPC_ERROR",
            "QUOTE_REVERT",
            "QUOTE_EMPTY",
            "SLIPPAGE_TOO_HIGH",
            "INFRA_BLOCK_PIN_FAILED",
        }
        
        missing = required_codes - valid_codes
        
        self.assertEqual(
            missing,
            set(),
            f"Required error codes missing from ErrorCode enum: {missing}"
        )
    
    def test_no_duplicate_error_code_values(self):
        """Verify no duplicate values in ErrorCode enum."""
        values = [code.value for code in ErrorCode]
        duplicates = [v for v in values if values.count(v) > 1]
        
        self.assertEqual(
            duplicates,
            [],
            f"Duplicate ErrorCode values: {set(duplicates)}"
        )
    
    def test_errorcode_values_are_uppercase(self):
        """Verify all ErrorCode values follow UPPER_SNAKE_CASE."""
        for code in ErrorCode:
            self.assertEqual(
                code.value,
                code.value.upper(),
                f"ErrorCode.{code.name} value should be uppercase: {code.value}"
            )
            self.assertRegex(
                code.value,
                r'^[A-Z][A-Z0-9_]+$',
                f"ErrorCode.{code.name} value should be UPPER_SNAKE_CASE: {code.value}"
            )
    
    def test_error_to_gate_category_mapping(self):
        """Verify ERROR_TO_GATE_CATEGORY maps only valid codes."""
        from monitoring.truth_report import ERROR_TO_GATE_CATEGORY
        
        valid_codes = self.get_all_error_codes()
        known_string_codes = self.KNOWN_STRING_CODES
        
        for code in ERROR_TO_GATE_CATEGORY.keys():
            is_valid = code in valid_codes or code in known_string_codes
            self.assertTrue(
                is_valid,
                f"ERROR_TO_GATE_CATEGORY contains unknown code: {code}"
            )


class TestErrorCodeCompleteness(unittest.TestCase):
    """Test ErrorCode enum has all needed codes."""
    
    def test_has_price_sanity_codes(self):
        """Verify price sanity related codes exist."""
        codes = {code.value for code in ErrorCode}
        
        self.assertIn("PRICE_SANITY_FAILED", codes)
        self.assertIn("PRICE_ANCHOR_MISSING", codes)
    
    def test_has_infrastructure_codes(self):
        """Verify infrastructure related codes exist."""
        codes = {code.value for code in ErrorCode}
        
        self.assertIn("INFRA_RPC_ERROR", codes)
        self.assertIn("INFRA_RPC_TIMEOUT", codes)
        self.assertIn("INFRA_RATE_LIMIT", codes)
        self.assertIn("INFRA_BLOCK_PIN_FAILED", codes)
    
    def test_has_quote_codes(self):
        """Verify quote related codes exist."""
        codes = {code.value for code in ErrorCode}
        
        self.assertIn("QUOTE_REVERT", codes)
        self.assertIn("QUOTE_TIMEOUT", codes)
        self.assertIn("QUOTE_EMPTY", codes)
        self.assertIn("QUOTE_ZERO_OUTPUT", codes)


if __name__ == "__main__":
    unittest.main()
