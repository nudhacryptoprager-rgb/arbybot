# PATH: tests/unit/test_price_sanity_inversion.py
"""
Tests for price sanity validation.

M5_0 CONTRACTS:

1. PRICE ORIENTATION:
   - Price is ALWAYS "quote_token per 1 base_token"
   - For WETH/USDC: price = USDC per 1 WETH (~2600-3500)

2. DEVIATION FORMULA:
   deviation_bps = int(round(abs(price - anchor) / anchor * 10000))
   CAP = 10000 bps (100%)

3. NO INVERSION:
   - inversion_applied is ALWAYS False (we never auto-invert)
   - Bad quotes (e.g., 8 USDC per WETH) are "suspect_quote", NOT "inverted"

API CONTRACT:
   check_price_sanity() accepts anchor_source (str) for backward compatibility.
   calculate_deviation_bps() returns (deviation_bps, deviation_bps_raw, was_capped).
"""

import unittest
from decimal import Decimal
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.validators import (
    normalize_price,
    check_price_sanity,
    select_anchor,
    calculate_deviation_bps,
    AnchorQuote,
    MAX_DEVIATION_BPS_CAP,
)
from core.constants import PRICE_SANITY_BOUNDS


class TestPriceNormalization(unittest.TestCase):
    """Test price normalization."""

    def test_normal_weth_usdc_price(self):
        """Test normal WETH/USDC price."""
        price, suspect, diag = normalize_price(
            amount_in_wei=10**18,
            amount_out_wei=2600 * 10**6,
            decimals_in=18,
            decimals_out=6,
            token_in="WETH",
            token_out="USDC",
        )
        
        self.assertAlmostEqual(float(price), 2600.0, delta=1.0)
        self.assertFalse(suspect)
        self.assertEqual(diag["numeraire_side"], "USDC_per_WETH")
        # CRITICAL: inversion_applied is ALWAYS False
        self.assertEqual(diag["inversion_applied"], False)

    def test_suspect_quote_low_price(self):
        """
        Test suspect quote detection (NOT inversion).
        
        Real case: Sushi v3 returns 8.6 USDC per 1 WETH (should be ~2600).
        This is a SUSPECT QUOTE, not inversion.
        """
        price, suspect, diag = normalize_price(
            amount_in_wei=10**18,
            amount_out_wei=int(8.605 * 10**6),  # ~8.6 USDC (BAD!)
            decimals_in=18,
            decimals_out=6,
            token_in="WETH",
            token_out="USDC",
        )
        
        # Price returned AS-IS
        self.assertAlmostEqual(float(price), 8.605, delta=0.01)
        
        # Should be suspect, NOT inverted
        self.assertTrue(suspect)
        self.assertEqual(diag["suspect_quote"], True)
        self.assertEqual(diag["suspect_reason"], "way_below_expected")
        
        # CRITICAL: inversion_applied is ALWAYS False
        self.assertEqual(diag["inversion_applied"], False)

    def test_inversion_applied_always_false(self):
        """Test that inversion_applied is ALWAYS False."""
        test_cases = [
            (2600 * 10**6, False),  # Normal price
            (int(8.6 * 10**6), True),  # Suspect low
            (int(0.001 * 10**6), True),  # Very low
            (50000 * 10**6, True),  # Suspect high
        ]
        
        for amount_out, expected_suspect in test_cases:
            _, suspect, diag = normalize_price(
                amount_in_wei=10**18,
                amount_out_wei=amount_out,
                decimals_in=18,
                decimals_out=6,
                token_in="WETH",
                token_out="USDC",
            )
            
            # inversion_applied MUST be False always
            self.assertEqual(diag["inversion_applied"], False,
                f"inversion_applied should be False for amount_out={amount_out}")


class TestDeviationCalculation(unittest.TestCase):
    """Test deviation calculation."""

    def test_exact_deviation(self):
        """Test exact deviation calculation."""
        dev, dev_raw, capped = calculate_deviation_bps(Decimal("900"), Decimal("1000"))
        self.assertEqual(dev, 1000)
        self.assertEqual(dev_raw, 1000)
        self.assertFalse(capped)

    def test_deviation_capping(self):
        """Test deviation cap at 10000 bps."""
        dev, dev_raw, capped = calculate_deviation_bps(Decimal("3000"), Decimal("1000"))
        self.assertEqual(dev, MAX_DEVIATION_BPS_CAP)
        self.assertEqual(dev_raw, 20000)
        self.assertTrue(capped)

    def test_deviation_invariant(self):
        """Same % gives same bps at any scale."""
        for scale in [1, 10, 100, 1000]:
            dev, _, _ = calculate_deviation_bps(Decimal(90 * scale), Decimal(100 * scale))
            self.assertEqual(dev, 1000)


class TestPriceSanity(unittest.TestCase):
    """Test price sanity check."""

    def test_sanity_passes_normal(self):
        """Normal price passes sanity."""
        config = {"price_sanity_enabled": True, "price_sanity_max_deviation_bps": 5000}
        
        passed, dev, error, diag = check_price_sanity(
            token_in="WETH", token_out="USDC",
            price=Decimal("2800"),
            config=config,
            dynamic_anchor=Decimal("2600"),
        )
        
        self.assertTrue(passed)
        self.assertEqual(diag["inversion_applied"], False)

    def test_sanity_fails_suspect_quote(self):
        """Suspect quote fails sanity with clear diagnostics."""
        config = {"price_sanity_enabled": True, "price_sanity_max_deviation_bps": 5000}
        
        passed, dev, error, diag = check_price_sanity(
            token_in="WETH", token_out="USDC",
            price=Decimal("8.605"),
            config=config,
            dynamic_anchor=Decimal("2600"),
            dex_id="sushiswap_v3",
            fee=3000,
        )
        
        self.assertFalse(passed)
        self.assertIn("error", diag)
        # CRITICAL: No false inversion claim
        self.assertEqual(diag["inversion_applied"], False)
        # Should flag as suspect
        self.assertEqual(diag.get("suspect_quote"), True)

    def test_anchor_source_backward_compat(self):
        """anchor_source parameter accepted."""
        config = {"price_sanity_enabled": True}
        
        passed, _, _, diag = check_price_sanity(
            token_in="WETH", token_out="USDC",
            price=Decimal("2600"),
            config=config,
            dynamic_anchor=Decimal("2600"),
            anchor_source="dynamic_first_quote",
        )
        
        self.assertTrue(passed)
        self.assertEqual(diag["anchor_source"], "dynamic_first_quote")


class TestAnchorSelection(unittest.TestCase):
    """Test anchor selection."""

    def test_anchor_dex_priority(self):
        """anchor_dex has priority."""
        quotes = [
            AnchorQuote(dex_id="sushiswap_v3", price=Decimal("2500"), fee=3000, pool_address="0x111", block_number=100),
            AnchorQuote(dex_id="uniswap_v3", price=Decimal("2600"), fee=500, pool_address="0x222", block_number=100),
        ]
        
        anchor_price, info = select_anchor(quotes, ("WETH", "USDC"))
        self.assertEqual(float(anchor_price), 2600.0)
        self.assertEqual(info["dex_id"], "uniswap_v3")


class TestRealWorldRegression(unittest.TestCase):
    """Regression tests for real cases."""

    def test_sushi_v3_suspect_quote(self):
        """
        Sushi v3 bad quote: 8.6 USDC per WETH.
        
        This is NOT inversion - it's bad adapter/registry data.
        """
        # Normalize
        price, suspect, norm_diag = normalize_price(
            amount_in_wei=10**18,
            amount_out_wei=int(8.605 * 10**6),
            decimals_in=18,
            decimals_out=6,
            token_in="WETH",
            token_out="USDC",
        )
        
        # NOT inverted - just suspect
        self.assertEqual(norm_diag["inversion_applied"], False)
        self.assertTrue(suspect)
        
        # Sanity fails
        config = {"price_sanity_enabled": True, "price_sanity_max_deviation_bps": 5000}
        passed, dev, error, diag = check_price_sanity(
            token_in="WETH", token_out="USDC",
            price=price,
            config=config,
            dynamic_anchor=Decimal("2600"),
            dex_id="sushiswap_v3",
            fee=3000,
        )
        
        self.assertFalse(passed)
        self.assertEqual(diag["dex_id"], "sushiswap_v3")
        self.assertEqual(diag["inversion_applied"], False)


if __name__ == "__main__":
    unittest.main()
