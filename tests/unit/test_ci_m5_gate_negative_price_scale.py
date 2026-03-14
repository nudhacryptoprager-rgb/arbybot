# PATH: tests/unit/test_ci_m5_gate_negative_price_scale.py
"""Negative test: inverted price direction → strict FAIL.

Critical invariant test for price scale bugs where token0/token1
ordering causes prices to be orders of magnitude wrong.

Example: ARB/WETH = 17000 (wrong) vs ARB/WETH = 0.00035 (correct)
"""

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.ci_m5_0_gate import validate_price_scale, PRICE_SCALE_BOUNDS


class TestPriceScale_InvertedDirection(unittest.TestCase):
    """Strict FAIL when price is orders of magnitude wrong."""
    
    def test_arb_weth_inverted_fails_strict(self):
        """ARB/WETH = 17000 (inverted) with require_real=True → FAIL."""
        data = {
            "quotes_sample": [
                {
                    "token_in": "ARB",
                    "token_out": "WETH",
                    "price_exact": "17263.70",  # WRONG: should be ~0.00035
                }
            ]
        }
        ok, msg = validate_price_scale(data, require_real=True)
        self.assertFalse(ok)
        self.assertIn("PRICE_SCALE VIOLATION", msg)
        self.assertIn("ARB/WETH", msg)
    
    def test_arb_usdc_inverted_fails_strict(self):
        """ARB/USDC = 0.001 (too low) with require_real=True → FAIL."""
        data = {
            "quotes_sample": [
                {
                    "token_in": "ARB",
                    "token_out": "USDC",
                    "price_exact": "0.001",  # WRONG: should be ~0.70
                }
            ]
        }
        ok, msg = validate_price_scale(data, require_real=True)
        self.assertFalse(ok)
        self.assertIn("ARB/USDC", msg)
    
    def test_weth_usdc_too_low_fails_strict(self):
        """WETH/USDC = 10 (way too low) with require_real=True → FAIL."""
        data = {
            "quotes_sample": [
                {
                    "token_in": "WETH",
                    "token_out": "USDC",
                    "price_exact": "10.0",  # WRONG: should be ~2000
                }
            ]
        }
        ok, msg = validate_price_scale(data, require_real=True)
        self.assertFalse(ok)
        self.assertIn("WETH/USDC", msg)


class TestPriceScale_CorrectPrices(unittest.TestCase):
    """Valid prices should pass."""
    
    def test_arb_weth_correct_passes(self):
        """ARB/WETH = 0.00035 (correct) → PASS."""
        data = {
            "quotes_sample": [
                {
                    "token_in": "ARB",
                    "token_out": "WETH",
                    "price_exact": "0.00035",  # Correct range
                }
            ]
        }
        ok, msg = validate_price_scale(data, require_real=True)
        self.assertTrue(ok)
        self.assertIn("price_scale OK", msg)
    
    def test_arb_usdc_correct_passes(self):
        """ARB/USDC = 0.70 (correct) → PASS."""
        data = {
            "quotes_sample": [
                {
                    "token_in": "ARB",
                    "token_out": "USDC",
                    "price_exact": "0.70",  # Correct range
                }
            ]
        }
        ok, msg = validate_price_scale(data, require_real=True)
        self.assertTrue(ok)
    
    def test_weth_usdc_correct_passes(self):
        """WETH/USDC = 2000 (correct) → PASS."""
        data = {
            "quotes_sample": [
                {
                    "token_in": "WETH",
                    "token_out": "USDC",
                    "price_exact": "2000.0",  # Correct range
                }
            ]
        }
        ok, msg = validate_price_scale(data, require_real=True)
        self.assertTrue(ok)
    
    def test_wseth_weth_correct_passes(self):
        """wstETH/WETH = 1.15 (correct) → PASS."""
        data = {
            "quotes_sample": [
                {
                    "token_in": "wstETH",
                    "token_out": "WETH",
                    "price_exact": "1.15",  # Correct range
                }
            ]
        }
        ok, msg = validate_price_scale(data, require_real=True)
        self.assertTrue(ok)


class TestPriceScale_OfflineWarning(unittest.TestCase):
    """Offline mode (require_real=False) should warn but not fail."""
    
    def test_inverted_price_warns_offline(self):
        """Inverted price with require_real=False → WARN, OK."""
        data = {
            "quotes_sample": [
                {
                    "token_in": "ARB",
                    "token_out": "WETH",
                    "price_exact": "17000",  # Wrong
                }
            ]
        }
        ok, msg = validate_price_scale(data, require_real=False)
        self.assertTrue(ok)  # Passes but warns
        self.assertIn("WARN", msg)


class TestPriceScale_Bounds(unittest.TestCase):
    """Verify bounds are sensible."""
    
    def test_bounds_exist_for_key_pairs(self):
        """Key pairs should have bounds defined."""
        self.assertIn("ARB/WETH", PRICE_SCALE_BOUNDS)
        self.assertIn("ARB/USDC", PRICE_SCALE_BOUNDS)
        self.assertIn("WETH/USDC", PRICE_SCALE_BOUNDS)
        self.assertIn("wstETH/WETH", PRICE_SCALE_BOUNDS)
    
    def test_bounds_exist_for_real_expanded_pairs(self):
        """v2.0.9: All extended pairs must have bounds."""
        # Extended pairs
        required_pairs = [
            "WETH/USDC", "WETH/USDT", "wstETH/WETH",
            "ARB/WETH", "LINK/WETH", "GMX/WETH",
            "ARB/USDC", "LINK/USDC", "ARB/USDT", "GMX/USDC",
        ]
        for pair in required_pairs:
            with self.subTest(pair=pair):
                self.assertIn(pair, PRICE_SCALE_BOUNDS, f"Missing bounds for {pair}")


class TestPriceScale_LineaRegression(unittest.TestCase):
    """Regression: Linea PRICE_SCALE 11.8% violation (runDir 095809).
    
    Linea pancakeswap_v3 produced:
    - WETH/USDC fee=2500: price=0.001476 (inverted, expected ~2050)
    - WETH/USDT fee=500: price=93.0456 (below [100, 50000] range)
    2/17 quotes = 11.8% > 10% threshold → FAIL.
    """
    
    def test_linea_inverted_weth_usdc_fails(self):
        """WETH/USDC=0.001476 (inverted) → violation detected."""
        data = {
            "quotes_sample": [
                {"token_in": "WETH", "token_out": "USDC", "price_exact": "0.001476"},
            ]
        }
        ok, msg = validate_price_scale(data, require_real=True)
        self.assertFalse(ok)
        self.assertIn("WETH/USDC", msg)
    
    def test_linea_weth_usdt_below_range_fails(self):
        """WETH/USDT=93.0456 (below 100 min) → violation detected."""
        data = {
            "quotes_sample": [
                {"token_in": "WETH", "token_out": "USDT", "price_exact": "93.0456"},
            ]
        }
        ok, msg = validate_price_scale(data, require_real=True)
        self.assertFalse(ok)
        self.assertIn("WETH/USDT", msg)
    
    def test_linea_violation_rate_above_10pct(self):
        """2 bad quotes out of 17 = 11.8% > 10% threshold → FAIL in real mode."""
        good_quotes = [
            {"token_in": "WETH", "token_out": "USDC", "price_exact": "2050.0"},
        ] * 15
        bad_quotes = [
            {"token_in": "WETH", "token_out": "USDC", "price_exact": "0.001476"},
            {"token_in": "WETH", "token_out": "USDT", "price_exact": "93.0456"},
        ]
        data = {"quotes_sample": good_quotes + bad_quotes}
        ok, msg = validate_price_scale(data, require_real=True)
        self.assertFalse(ok)
        self.assertIn("PRICE_SCALE VIOLATION", msg)
    
    def test_linea_violation_rate_at_10pct_passes(self):
        """Exactly 10% violation rate (2/20) → PASS (≤10% tolerant)."""
        good_quotes = [
            {"token_in": "WETH", "token_out": "USDC", "price_exact": "2050.0"},
        ] * 18
        bad_quotes = [
            {"token_in": "WETH", "token_out": "USDC", "price_exact": "0.001476"},
            {"token_in": "WETH", "token_out": "USDT", "price_exact": "93.0456"},
        ]
        data = {"quotes_sample": good_quotes + bad_quotes}
        ok, msg = validate_price_scale(data, require_real=True)
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
