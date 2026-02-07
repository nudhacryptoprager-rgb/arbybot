# PATH: tests/unit/test_ci_m5_gate_negative_anti_placeholder.py
"""Negative test: pool_address=null → strict FAIL.

Critical invariant test per BLOCKER bug where fake quotes with null pool_address
created cosmic spread signals (574B bps, $57.5B PnL).
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.ci_m5_0_gate import validate_anti_placeholder


class TestAntiPlaceholder_NegativePoolAddress(unittest.TestCase):
    """Strict FAIL when any quote has pool_address=null."""
    
    def test_null_pool_address_fails_strict(self):
        """pool_address=None with require_real=True → FAIL."""
        data = {
            "quotes_sample": [
                {
                    "dex_id": "uniswap_v3",
                    "token_in": "WETH",
                    "token_out": "USDC",
                    "pool_address": None,  # BLOCKER: null pool
                    "tick": -200000,
                    "sqrt_price_x96": 123456789,
                }
            ]
        }
        ok, msg = validate_anti_placeholder(data, require_real=True)
        self.assertFalse(ok)
        self.assertIn("ANTI_PLACEHOLDER VIOLATION", msg)
        self.assertIn("pool_address=null", msg)
    
    def test_empty_pool_address_fails_strict(self):
        """pool_address='' with require_real=True → FAIL."""
        data = {
            "quotes_sample": [
                {
                    "dex_id": "sushiswap_v3",
                    "token_in": "WETH",
                    "token_out": "USDT",
                    "pool_address": "",  # Empty string
                    "tick": -200000,
                    "sqrt_price_x96": 123456789,
                }
            ]
        }
        ok, msg = validate_anti_placeholder(data, require_real=True)
        self.assertFalse(ok)
        self.assertIn("pool_address=null", msg)
    
    def test_zero_address_fails_strict(self):
        """pool_address=0x000...000 with require_real=True → FAIL."""
        data = {
            "quotes_sample": [
                {
                    "dex_id": "uniswap_v3",
                    "token_in": "ARB",
                    "token_out": "WETH",
                    "pool_address": "0x0000000000000000000000000000000000000000",
                    "tick": -80000,
                    "sqrt_price_x96": 987654321,
                }
            ]
        }
        ok, msg = validate_anti_placeholder(data, require_real=True)
        self.assertFalse(ok)
        self.assertIn("pool_address=null", msg)


class TestAntiPlaceholder_NegativeV3Fields(unittest.TestCase):
    """V3 pools require tick and sqrt_price_x96."""
    
    def test_null_tick_v3_fails_strict(self):
        """tick=None for v3 pool with require_real=True → FAIL."""
        data = {
            "quotes_sample": [
                {
                    "dex_id": "uniswap_v3",
                    "token_in": "WETH",
                    "token_out": "USDC",
                    "pool_address": "0x1234567890abcdef1234567890abcdef12345678",
                    "tick": None,  # Missing tick
                    "sqrt_price_x96": 123456789,
                }
            ]
        }
        ok, msg = validate_anti_placeholder(data, require_real=True)
        self.assertFalse(ok)
        self.assertIn("tick=null", msg)
    
    def test_null_sqrt_price_v3_fails_strict(self):
        """sqrt_price_x96=None for v3 pool with require_real=True → FAIL."""
        data = {
            "quotes_sample": [
                {
                    "dex_id": "sushiswap_v3",
                    "token_in": "ARB",
                    "token_out": "USDC",
                    "pool_address": "0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef",
                    "tick": -200000,
                    "sqrt_price_x96": None,  # Missing sqrt_price
                }
            ]
        }
        ok, msg = validate_anti_placeholder(data, require_real=True)
        self.assertFalse(ok)
        self.assertIn("sqrt_price_x96=null", msg)


class TestAntiPlaceholder_PositiveCase(unittest.TestCase):
    """Valid quotes should pass."""
    
    def test_valid_quote_passes(self):
        """Complete quote with all fields → PASS."""
        data = {
            "quotes_sample": [
                {
                    "dex_id": "uniswap_v3",
                    "token_in": "WETH",
                    "token_out": "USDC",
                    "pool_address": "0xC6962004f452bE9203591991D15f6b388e09E8D0",
                    "tick": -200000,
                    "sqrt_price_x96": 2934587234958723495872,
                }
            ]
        }
        ok, msg = validate_anti_placeholder(data, require_real=True)
        self.assertTrue(ok)
        self.assertIn("anti_placeholder OK", msg)
    
    def test_empty_quotes_sample_passes(self):
        """No quotes_sample → PASS (nothing to check)."""
        data = {"quotes_sample": []}
        ok, msg = validate_anti_placeholder(data, require_real=True)
        self.assertTrue(ok)
    
    def test_missing_quotes_sample_passes(self):
        """No quotes_sample key → PASS."""
        data = {}
        ok, msg = validate_anti_placeholder(data, require_real=True)
        self.assertTrue(ok)


class TestAntiPlaceholder_OfflineWarning(unittest.TestCase):
    """Offline mode (require_real=False) should warn but not fail."""
    
    def test_null_pool_address_warns_offline(self):
        """pool_address=None with require_real=False → WARN, OK."""
        data = {
            "quotes_sample": [
                {
                    "dex_id": "uniswap_v3",
                    "token_in": "WETH",
                    "token_out": "USDC",
                    "pool_address": None,
                }
            ]
        }
        ok, msg = validate_anti_placeholder(data, require_real=False)
        self.assertTrue(ok)  # Passes but warns
        self.assertIn("WARN", msg)


if __name__ == "__main__":
    unittest.main()
