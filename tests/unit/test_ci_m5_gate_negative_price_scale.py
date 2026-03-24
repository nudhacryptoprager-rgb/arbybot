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
        self.assertIn("DIRECTION BUG", msg)
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
    """Offline mode (require_real=False) should warn but not fail for outliers.
    
    R39g+: Per-pair majority logic. If a pair has only bad quotes,
    it's a direction bug → FAIL regardless of require_real.
    """
    
    def test_inverted_price_all_bad_fails_even_offline(self):
        """All-bad pair is a direction bug → FAIL even in offline mode."""
        data = {
            "quotes_sample": [
                {
                    "token_in": "ARB",
                    "token_out": "WETH",
                    "price_exact": "17000",  # Wrong, and no good quotes
                }
            ]
        }
        ok, msg = validate_price_scale(data, require_real=False)
        self.assertFalse(ok)
        self.assertIn("DIRECTION BUG", msg)


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
    """Regression: Linea PRICE_SCALE violations from low-liquidity extreme fee-tier pools.
    
    R39g+: Per-pair majority logic. If WETH/USDC has good quotes (~2050) AND
    bad quotes (0.001476 from 10000-fee pool), the bad ones are data quality
    outliers since the pair has good quotes → PASS with WARN.
    Only FAIL if ALL quotes for a pair are outside bounds (directi bug).
    """
    
    def test_linea_inverted_weth_usdc_only_bad_fails(self):
        """WETH/USDC=0.001476 with NO good quotes → FAIL (direction bug)."""
        data = {
            "quotes_sample": [
                {"token_in": "WETH", "token_out": "USDC", "price_exact": "0.001476"},
            ]
        }
        ok, msg = validate_price_scale(data, require_real=True)
        self.assertFalse(ok)
        self.assertIn("WETH/USDC", msg)
    
    def test_linea_weth_usdt_below_range_only_bad_fails(self):
        """WETH/USDT=93.0456 (below 100 min) with NO good quotes → FAIL."""
        data = {
            "quotes_sample": [
                {"token_in": "WETH", "token_out": "USDT", "price_exact": "93.0456"},
            ]
        }
        ok, msg = validate_price_scale(data, require_real=True)
        self.assertFalse(ok)
        self.assertIn("WETH/USDT", msg)
    
    def test_linea_outlier_with_good_quotes_passes(self):
        """R39g+: 1 bad WETH/USDC quote + 4 good ones → PASS (data quality warn)."""
        data = {
            "quotes_sample": [
                {"token_in": "WETH", "token_out": "USDC", "price_exact": "2050.0"},
                {"token_in": "WETH", "token_out": "USDC", "price_exact": "2060.0"},
                {"token_in": "WETH", "token_out": "USDC", "price_exact": "2040.0"},
                {"token_in": "WETH", "token_out": "USDC", "price_exact": "2055.0"},
                {"token_in": "WETH", "token_out": "USDC", "price_exact": "0.01476"},  # outlier from 10000 fee pool
            ]
        }
        ok, msg = validate_price_scale(data, require_real=True)
        self.assertTrue(ok)
        self.assertIn("WARN", msg)
        self.assertIn("data quality", msg)
    
    def test_linea_mixed_pairs_bad_and_good(self):
        """R39g+: Mixed scenario - WETH/USDC has outlier (OK), WETH/USDT all bad (FAIL)."""
        data = {
            "quotes_sample": [
                {"token_in": "WETH", "token_out": "USDC", "price_exact": "2050.0"},  # good
                {"token_in": "WETH", "token_out": "USDC", "price_exact": "0.001476"},  # bad outlier
                {"token_in": "WETH", "token_out": "USDT", "price_exact": "93.0456"},  # bad, no good USDT quotes
            ]
        }
        ok, msg = validate_price_scale(data, require_real=True)
        self.assertFalse(ok)  # WETH/USDT has only bad quotes = direction bug
        self.assertIn("WETH/USDT", msg)
    
    def test_linea_real_scenario_passes(self):
        """R39g+: Real linea scenario - 4 good WETH/USDC + 1 bad → all OK."""
        good_quotes = [
            {"token_in": "WETH", "token_out": "USDC", "price_exact": "2160.6"},
            {"token_in": "WETH", "token_out": "USDC", "price_exact": "2158.9"},
            {"token_in": "WETH", "token_out": "USDC", "price_exact": "1882.9"},
            {"token_in": "WETH", "token_out": "USDC", "price_exact": "2159.3"},
        ]
        bad_quotes = [
            {"token_in": "WETH", "token_out": "USDC", "price_exact": "0.01476"},
        ]
        # Also include unrelated pairs
        other = [
            {"token_in": "WBTC", "token_out": "USDC", "price_exact": "70489.0"},
            {"token_in": "WETH", "token_out": "WBTC", "price_exact": "0.029"},
        ]
        data = {"quotes_sample": good_quotes + bad_quotes + other}
        ok, msg = validate_price_scale(data, require_real=True)
        self.assertTrue(ok)


if __name__ == "__main__":
    unittest.main()
