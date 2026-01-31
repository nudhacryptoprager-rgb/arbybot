# PATH: tests/unit/test_price_sanity_inversion.py
"""
Tests for price sanity validation.

M5_0 CONTRACTS TESTED:

1. PRICE ORIENTATION:
   - Price is ALWAYS "quote_token per 1 base_token"
   - For WETH/USDC: price = USDC per 1 WETH (~2600-3500)

2. NO INVERSION:
   - inversion_applied is ALWAYS False
   - Bad quotes are "suspect_quote", not "inverted"
   - This helps identify adapter bugs, not mask them

3. DEVIATION FORMULA:
   deviation_bps = int(round(abs(price - anchor) / anchor * 10000))
   
   CAP SEMANTICS:
   - MAX_DEVIATION_BPS_CAP = 10000 (100%)
   - deviation_bps_raw is ALWAYS uncapped
   - deviation_bps is capped for gate decisions
   - deviation_bps_capped=True when raw > cap

4. DIAGNOSTICS CONTRACT:
   - raw_price_quote_per_base: actual ratio (not "0")
   - final_price_used_for_sanity: same as implied_price
   - suspect_quote: True if price is obviously wrong
   - Never use "0" as placeholder

5. API CONTRACT:
   - check_price_sanity() accepts anchor_source (str)
   - calculate_deviation_bps() returns 3 values

NOTE: Tests use INVARIANTS, not live prices.
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
        self.assertEqual(diag["inversion_applied"], False)

    def test_inversion_applied_always_false(self):
        """CRITICAL: inversion_applied is ALWAYS False."""
        test_cases = [
            (2600 * 10**6, False),   # Normal
            (int(8.6 * 10**6), True),   # Suspect low
            (int(0.001 * 10**6), True), # Very low
            (50000 * 10**6, True),      # Suspect high
        ]
        
        for amount_out, _ in test_cases:
            _, _, diag = normalize_price(
                amount_in_wei=10**18,
                amount_out_wei=amount_out,
                decimals_in=18,
                decimals_out=6,
                token_in="WETH",
                token_out="USDC",
            )
            self.assertEqual(diag["inversion_applied"], False,
                f"inversion_applied must be False for amount_out={amount_out}")

    def test_suspect_quote_flagged(self):
        """Test that obviously wrong prices are flagged as suspect."""
        price, suspect, diag = normalize_price(
            amount_in_wei=10**18,
            amount_out_wei=int(8.6 * 10**6),  # ~8.6 USDC (BAD!)
            decimals_in=18,
            decimals_out=6,
            token_in="WETH",
            token_out="USDC",
        )
        
        self.assertTrue(suspect)
        self.assertEqual(diag["suspect_quote"], True)
        self.assertEqual(diag["suspect_reason"], "way_below_expected")
        # NOT inverted
        self.assertEqual(diag["inversion_applied"], False)

    def test_raw_price_not_zero_placeholder(self):
        """Test that raw_price is not "0" placeholder."""
        price, _, diag = normalize_price(
            amount_in_wei=10**18,
            amount_out_wei=2600 * 10**6,
            decimals_in=18,
            decimals_out=6,
            token_in="WETH",
            token_out="USDC",
        )
        
        # raw_price must be actual value, not "0"
        raw = diag["raw_price_quote_per_base"]
        self.assertIsNotNone(raw)
        self.assertNotEqual(raw, "0")
        self.assertAlmostEqual(float(raw), 2600.0, delta=1.0)

    def test_raw_price_none_on_zero_input(self):
        """Test that raw_price is None (not "0") on zero input."""
        _, _, diag = normalize_price(
            amount_in_wei=0,  # Zero input
            amount_out_wei=2600 * 10**6,
            decimals_in=18,
            decimals_out=6,
            token_in="WETH",
            token_out="USDC",
        )
        
        # Should be None, not "0"
        self.assertIsNone(diag["raw_price_quote_per_base"])

    def test_final_price_matches_implied(self):
        """Test final_price_used_for_sanity equals implied_price."""
        price, _, diag = normalize_price(
            amount_in_wei=10**18,
            amount_out_wei=2600 * 10**6,
            decimals_in=18,
            decimals_out=6,
            token_in="WETH",
            token_out="USDC",
        )
        
        self.assertEqual(diag["final_price_used_for_sanity"], diag["raw_price_quote_per_base"])


class TestDeviationCalculation(unittest.TestCase):
    """Test deviation calculation."""

    def test_exact_deviation(self):
        """Test exact deviation calculation."""
        dev, dev_raw, capped = calculate_deviation_bps(Decimal("900"), Decimal("1000"))
        self.assertEqual(dev, 1000)
        self.assertEqual(dev_raw, 1000)
        self.assertFalse(capped)

    def test_deviation_capping(self):
        """Test deviation cap at 10000 bps (100%)."""
        # 200% deviation -> capped at 100%
        dev, dev_raw, capped = calculate_deviation_bps(Decimal("3000"), Decimal("1000"))
        
        self.assertEqual(dev, MAX_DEVIATION_BPS_CAP)  # 10000
        self.assertEqual(dev_raw, 20000)  # Uncapped
        self.assertTrue(capped)

    def test_deviation_bps_raw_always_uncapped(self):
        """Test that deviation_bps_raw is ALWAYS uncapped."""
        test_cases = [
            (Decimal("900"), Decimal("1000"), 1000, False),    # Under cap
            (Decimal("3000"), Decimal("1000"), 20000, True),   # Over cap (200%)
            (Decimal("10000"), Decimal("1000"), 90000, True),  # Way over (900%)
        ]
        
        for price, anchor, expected_raw, expected_capped in test_cases:
            dev, dev_raw, capped = calculate_deviation_bps(price, anchor)
            
            self.assertEqual(dev_raw, expected_raw,
                f"dev_raw should be {expected_raw} for {price}/{anchor}")
            self.assertEqual(capped, expected_capped)
            
            if capped:
                self.assertEqual(dev, MAX_DEVIATION_BPS_CAP)
            else:
                self.assertEqual(dev, dev_raw)

    def test_deviation_invariant(self):
        """INVARIANT: Same % gives same bps at any scale."""
        for scale in [1, 10, 100, 1000]:
            dev, _, _ = calculate_deviation_bps(Decimal(90 * scale), Decimal(100 * scale))
            self.assertEqual(dev, 1000)  # 10% = 1000 bps


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
        """Suspect quote fails sanity."""
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
        self.assertEqual(diag["inversion_applied"], False)
        self.assertEqual(diag.get("suspect_quote"), True)

    def test_diagnostics_include_final_price(self):
        """Test final_price_used_for_sanity in diagnostics."""
        config = {"price_sanity_enabled": True}
        
        _, _, _, diag = check_price_sanity(
            token_in="WETH", token_out="USDC",
            price=Decimal("2600"),
            config=config,
            dynamic_anchor=Decimal("2600"),
        )
        
        self.assertIn("final_price_used_for_sanity", diag)
        self.assertEqual(diag["final_price_used_for_sanity"], "2600")

    def test_diagnostics_cap_semantics(self):
        """Test cap semantics in diagnostics."""
        config = {"price_sanity_enabled": True, "price_sanity_max_deviation_bps": 5000}
        
        # Huge deviation (should cap)
        _, _, _, diag = check_price_sanity(
            token_in="WETH", token_out="USDC",
            price=Decimal("26000"),  # 10x anchor
            config=config,
            dynamic_anchor=Decimal("2600"),
        )
        
        self.assertEqual(diag["deviation_bps"], MAX_DEVIATION_BPS_CAP)
        self.assertGreater(diag["deviation_bps_raw"], MAX_DEVIATION_BPS_CAP)
        self.assertEqual(diag["deviation_bps_capped"], True)

    def test_anchor_source_backward_compat(self):
        """Test anchor_source parameter accepted."""
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
        """Test anchor_dex has priority."""
        quotes = [
            AnchorQuote(dex_id="sushiswap_v3", price=Decimal("2500"), fee=3000, pool_address="0x111", block_number=100),
            AnchorQuote(dex_id="uniswap_v3", price=Decimal("2600"), fee=500, pool_address="0x222", block_number=100),
        ]
        
        anchor_price, info = select_anchor(quotes, ("WETH", "USDC"))
        self.assertEqual(float(anchor_price), 2600.0)
        self.assertEqual(info["dex_id"], "uniswap_v3")


class TestRealWorldRegression(unittest.TestCase):
    """Regression tests for real cases."""

    def test_sushi_v3_bad_quote(self):
        """
        Sushi v3 bad quote: 8.6 USDC per WETH.
        
        This is NOT inversion - it's bad adapter data.
        Gate should REJECT with clear diagnostics.
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
        
        # NOT inverted
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
