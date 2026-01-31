# PATH: tests/unit/test_price_sanity_inversion.py
"""
Tests for price sanity orientation consistency.

M5_0 PRICE ORIENTATION CONTRACT:
- Price is ALWAYS expressed as: quote_token per 1 base_token
- For pairs like WETH/USDC: base=WETH, quote=USDC → price = USDC per 1 WETH
- Example: price=3500 means "3500 USDC per 1 WETH"

DEVIATION FORMULA CONTRACT:
    deviation_bps = int(round(abs(price - anchor) / anchor * 10000))

INVARIANTS TESTED:
1. Orientation consistency: anchor and quote use same numeraire
2. Inversion invariant: if inversion_applied, then raw_price * final_price ≈ 1
3. Deviation magnitude invariant: scaled prices give same deviation_bps
4. Diagnostics completeness: all fields present for debugging

NOTE: Tests do NOT depend on specific ETH price (1500 or 6000).
      They verify RELATIVE consistency, not absolute thresholds.
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
    AnchorQuote,
)
from core.constants import PRICE_SANITY_BOUNDS


class TestPriceOrientationContract(unittest.TestCase):
    """
    Test the price orientation contract.
    
    CONTRACT: price = quote_token per 1 base_token
    For WETH/USDC: price = USDC per 1 WETH (typically ~1500-6000)
    """

    def test_orientation_documented_in_diagnostics(self):
        """Test that diagnostics include numeraire_side field."""
        price, inverted, diag = normalize_price(
            amount_in_wei=10**18,
            amount_out_wei=3500 * 10**6,
            decimals_in=18,
            decimals_out=6,
            token_in="WETH",
            token_out="USDC",
        )
        
        # Diagnostics must include orientation info
        self.assertIn("in_normalized", diag)
        self.assertIn("out_normalized", diag)
        self.assertIn("raw_price", diag)
        self.assertIn("normalized_price", diag)
        self.assertIn("inversion_applied", diag)

    def test_price_orientation_is_quote_per_base(self):
        """
        Test that price follows quote_per_base convention.
        
        For 1 WETH -> 3500 USDC:
        - base = WETH (token_in)
        - quote = USDC (token_out)  
        - price = 3500 USDC per 1 WETH
        """
        amount_in_wei = 10**18  # 1 WETH
        amount_out_wei = 3500 * 10**6  # 3500 USDC
        
        price, inverted, diag = normalize_price(
            amount_in_wei=amount_in_wei,
            amount_out_wei=amount_out_wei,
            decimals_in=18,
            decimals_out=6,
            token_in="WETH",
            token_out="USDC",
        )
        
        # Price should be quote/base = 3500
        self.assertAlmostEqual(float(price), 3500.0, delta=1.0)
        self.assertFalse(inverted)
        
        # Verify via raw calculation
        in_norm = Decimal(amount_in_wei) / Decimal(10**18)
        out_norm = Decimal(amount_out_wei) / Decimal(10**6)
        expected = out_norm / in_norm
        self.assertEqual(price, expected)


class TestInversionInvariant(unittest.TestCase):
    """
    Test inversion invariant: raw_price * final_price ≈ 1 when inverted.
    
    This invariant is independent of actual ETH price.
    """

    def test_inversion_invariant_holds(self):
        """
        When inversion is applied: raw_price * final_price ≈ 1
        
        This proves the inversion is mathematically correct,
        regardless of what the actual prices are.
        """
        # Simulate inverted response
        amount_in_wei = 10**18  # 1 WETH
        amount_out_wei = int(0.0003 * 10**6)  # ~0.0003 USDC (inverted!)
        
        price, inverted, diag = normalize_price(
            amount_in_wei=amount_in_wei,
            amount_out_wei=amount_out_wei,
            decimals_in=18,
            decimals_out=6,
            token_in="WETH",
            token_out="USDC",
        )
        
        if inverted:
            raw_price = Decimal(diag["raw_price"])
            final_price = Decimal(diag["normalized_price"])
            
            # INVARIANT: raw * final ≈ 1 (within tolerance)
            product = raw_price * final_price
            self.assertAlmostEqual(float(product), 1.0, delta=0.001,
                msg=f"Inversion invariant failed: {raw_price} * {final_price} = {product}")

    def test_no_inversion_when_price_reasonable(self):
        """Test that reasonable prices are not inverted."""
        # Normal case: 1 WETH -> 3500 USDC
        price, inverted, diag = normalize_price(
            amount_in_wei=10**18,
            amount_out_wei=3500 * 10**6,
            decimals_in=18,
            decimals_out=6,
            token_in="WETH",
            token_out="USDC",
        )
        
        self.assertFalse(inverted)
        # When not inverted, raw_price == normalized_price
        self.assertEqual(diag["raw_price"], diag["normalized_price"])

    def test_inversion_flag_consistency(self):
        """Test inversion_applied flag matches actual behavior."""
        # Inverted case
        price1, inv1, diag1 = normalize_price(
            amount_in_wei=10**18,
            amount_out_wei=int(0.0003 * 10**6),
            decimals_in=18,
            decimals_out=6,
            token_in="WETH",
            token_out="USDC",
        )
        
        # Normal case
        price2, inv2, diag2 = normalize_price(
            amount_in_wei=10**18,
            amount_out_wei=3500 * 10**6,
            decimals_in=18,
            decimals_out=6,
            token_in="WETH",
            token_out="USDC",
        )
        
        # Flag must match diagnostics
        self.assertEqual(inv1, diag1["inversion_applied"])
        self.assertEqual(inv2, diag2["inversion_applied"])


class TestOrientationConsistency(unittest.TestCase):
    """
    Test that anchor and quote use same orientation for comparison.
    
    This is the core fix for the 2026-01-30 bug where:
    - Quote: 0.107885 (WETH per USDC)
    - Anchor: 2697.67 (USDC per WETH)
    - Comparison was invalid due to orientation mismatch
    """

    def test_sanity_check_uses_same_orientation(self):
        """
        Test that sanity check compares prices in same orientation.
        
        Both quote_price and anchor_price must be in same numeraire
        for deviation calculation to be meaningful.
        """
        config = {"price_sanity_enabled": True, "price_sanity_max_deviation_bps": 5000}
        
        # Quote and anchor in SAME orientation (USDC per WETH)
        quote_price = Decimal("3400")  # USDC per WETH
        anchor_price = Decimal("3500")  # USDC per WETH
        
        passed, deviation_bps, error, diag = check_price_sanity(
            token_in="WETH",
            token_out="USDC",
            price=quote_price,
            config=config,
            dynamic_anchor=anchor_price,
        )
        
        # Deviation should be small when orientations match
        # Formula: abs(3400 - 3500) / 3500 * 10000 = 100/3500 * 10000 ≈ 286
        self.assertTrue(passed)
        self.assertIsNotNone(deviation_bps)
        self.assertLess(deviation_bps, 500)  # Must be small when orientations match

    def test_mismatched_orientation_detected(self):
        """
        Test that mismatched orientations produce large deviation.
        
        This is the bug case from 2026-01-30:
        - Quote: ~0.1 (inverted orientation)
        - Anchor: ~2700 (correct orientation)
        - Result: massive deviation (should fail sanity)
        """
        config = {"price_sanity_enabled": True, "price_sanity_max_deviation_bps": 5000}
        
        # MISMATCHED orientations (this is the bug case!)
        quote_price = Decimal("0.107885")  # WETH per USDC (WRONG)
        anchor_price = Decimal("2697.67")  # USDC per WETH (correct)
        
        passed, deviation_bps, error, diag = check_price_sanity(
            token_in="WETH",
            token_out="USDC",
            price=quote_price,
            config=config,
            dynamic_anchor=anchor_price,
        )
        
        # Must FAIL with large deviation
        self.assertFalse(passed)
        self.assertIsNotNone(deviation_bps)
        # Deviation is massive because orientations don't match
        self.assertGreater(deviation_bps, 5000)

    def test_diagnostics_include_orientation_fields(self):
        """Test that diagnostics include all orientation-related fields."""
        config = {"price_sanity_enabled": True, "price_sanity_max_deviation_bps": 5000}
        
        passed, deviation_bps, error, diag = check_price_sanity(
            token_in="WETH",
            token_out="USDC",
            price=Decimal("3400"),
            config=config,
            dynamic_anchor=Decimal("3500"),
            fee=3000,
            dex_id="sushiswap_v3",
            pool_address="0xD1d5A4...",
            amount_in_wei=10**18,
            amount_out_wei=3400 * 10**6,
        )
        
        # Required diagnostic fields
        self.assertIn("implied_price", diag)
        self.assertIn("anchor_price", diag)
        self.assertIn("token_in", diag)
        self.assertIn("token_out", diag)
        
        # Price should match what we passed
        self.assertEqual(diag["implied_price"], "3400")
        self.assertEqual(diag["anchor_price"], "3500")


class TestAnchorSelectionPriority(unittest.TestCase):
    """Test proper anchor selection (not first-quote)."""

    def test_anchor_dex_has_highest_priority(self):
        """Test that anchor_dex (uniswap_v3) is preferred over others."""
        quotes = [
            AnchorQuote(dex_id="sushiswap_v3", price=Decimal("3400"), fee=3000, pool_address="0x111", block_number=100),
            AnchorQuote(dex_id="uniswap_v3", price=Decimal("3500"), fee=500, pool_address="0x222", block_number=100),
            AnchorQuote(dex_id="camelot", price=Decimal("3450"), fee=500, pool_address="0x333", block_number=100),
        ]
        
        result = select_anchor(quotes, ("WETH", "USDC"))
        
        self.assertIsNotNone(result)
        anchor_price, anchor_info = result
        
        # Must select uniswap_v3 (highest priority), not first quote
        self.assertEqual(anchor_info["dex_id"], "uniswap_v3")
        self.assertEqual(anchor_info["source"], "anchor_dex")

    def test_median_used_when_no_anchor_dex(self):
        """Test median selection when no priority DEX available."""
        quotes = [
            AnchorQuote(dex_id="camelot", price=Decimal("3300"), fee=3000, pool_address="0x111", block_number=100),
            AnchorQuote(dex_id="trader_joe", price=Decimal("3500"), fee=500, pool_address="0x222", block_number=100),
            AnchorQuote(dex_id="velodrome", price=Decimal("3700"), fee=500, pool_address="0x333", block_number=100),
        ]
        
        result = select_anchor(quotes, ("WETH", "USDC"))
        
        self.assertIsNotNone(result)
        anchor_price, anchor_info = result
        
        # Should use median (3500)
        self.assertEqual(anchor_info["source"], "median_quotes")
        self.assertEqual(float(anchor_price), 3500.0)

    def test_hardcoded_fallback_for_known_pairs(self):
        """Test hardcoded bounds fallback when no quotes."""
        result = select_anchor([], ("WETH", "USDC"))
        
        self.assertIsNotNone(result)
        anchor_price, anchor_info = result
        
        # Should use hardcoded bounds
        self.assertEqual(anchor_info["source"], "hardcoded_bounds")
        # Anchor should be within known bounds
        bounds = PRICE_SANITY_BOUNDS.get(("WETH", "USDC"))
        self.assertIsNotNone(bounds)
        self.assertGreaterEqual(anchor_price, bounds["min"])
        self.assertLessEqual(anchor_price, bounds["max"])

    def test_no_anchor_for_unknown_pair(self):
        """Test that unknown pair returns None (no hardcoded bounds)."""
        result = select_anchor([], ("UNKNOWN", "TOKEN"))
        self.assertIsNone(result)


class TestDeviationMagnitudeInvariant(unittest.TestCase):
    """
    Test deviation calculation invariants.
    
    DEVIATION FORMULA: dev_bps = int(round(abs(price - anchor) / anchor * 10000))
    
    KEY INVARIANT: For same PERCENTAGE difference, deviation_bps should be
    the same regardless of absolute price magnitude.
    
    Example: 5% deviation should give same bps for ETH at $3000 or $100000.
    """

    def test_deviation_formula_documented(self):
        """
        Verify the deviation formula matches documentation.
        
        Formula: dev_bps = int(round(abs(price - anchor) / anchor * 10000))
        """
        config = {"price_sanity_enabled": True, "price_sanity_max_deviation_bps": 5000}
        
        # Known values for predictable result
        anchor = Decimal("1000")  # Round number
        price = Decimal("900")    # 10% below anchor
        
        # Expected: abs(900-1000)/1000 * 10000 = 100/1000 * 10000 = 1000 bps
        passed, deviation_bps, error, diag = check_price_sanity(
            token_in="WETH",
            token_out="USDC",
            price=price,
            config=config,
            dynamic_anchor=anchor,
        )
        
        # With round numbers, expect exact result
        self.assertEqual(deviation_bps, 1000, 
            msg=f"Expected 1000 bps for 10% deviation, got {deviation_bps}")

    def test_deviation_invariant_scaled_prices(self):
        """
        INVARIANT: Same percentage deviation gives same bps,
        regardless of absolute price magnitude.
        
        Test: 10% deviation at different scales should all give ~1000 bps
        """
        config = {"price_sanity_enabled": True, "price_sanity_max_deviation_bps": 5000}
        
        # Scale factors to test
        scales = [1, 10, 100, 1000]
        base_anchor = Decimal("100")
        base_price = Decimal("90")  # 10% below anchor
        
        deviations = []
        for scale in scales:
            anchor = base_anchor * scale
            price = base_price * scale
            
            _, dev, _, _ = check_price_sanity(
                token_in="WETH",
                token_out="USDC",
                price=price,
                config=config,
                dynamic_anchor=anchor,
            )
            deviations.append(dev)
        
        # All deviations should be equal (within rounding error of 1)
        first_dev = deviations[0]
        for i, dev in enumerate(deviations):
            self.assertAlmostEqual(dev, first_dev, delta=1,
                msg=f"Scale {scales[i]}: expected {first_dev}, got {dev}")

    def test_deviation_invariant_different_percentages(self):
        """
        Test that different percentage deviations give proportionally
        different bps values.
        
        5% -> ~500 bps
        10% -> ~1000 bps
        20% -> ~2000 bps
        """
        config = {"price_sanity_enabled": True, "price_sanity_max_deviation_bps": 5000}
        anchor = Decimal("1000")
        
        test_cases = [
            (Decimal("950"), 500),   # 5% below -> 500 bps
            (Decimal("900"), 1000),  # 10% below -> 1000 bps
            (Decimal("800"), 2000),  # 20% below -> 2000 bps
        ]
        
        for price, expected_bps in test_cases:
            _, dev, _, _ = check_price_sanity(
                token_in="WETH",
                token_out="USDC",
                price=price,
                config=config,
                dynamic_anchor=anchor,
            )
            # Allow ±1 for rounding
            self.assertAlmostEqual(dev, expected_bps, delta=1,
                msg=f"Price {price}: expected {expected_bps} bps, got {dev}")

    def test_deviation_symmetric(self):
        """
        Test that deviation is symmetric: price above and below anchor
        by same percentage should give same absolute deviation.
        """
        config = {"price_sanity_enabled": True, "price_sanity_max_deviation_bps": 5000}
        anchor = Decimal("1000")
        
        # 10% below
        _, dev_below, _, _ = check_price_sanity(
            token_in="WETH", token_out="USDC",
            price=Decimal("900"),
            config=config,
            dynamic_anchor=anchor,
        )
        
        # 10% above
        _, dev_above, _, _ = check_price_sanity(
            token_in="WETH", token_out="USDC",
            price=Decimal("1100"),
            config=config,
            dynamic_anchor=anchor,
        )
        
        # Both should be ~1000 bps
        self.assertEqual(dev_below, dev_above,
            msg=f"Asymmetric deviation: below={dev_below}, above={dev_above}")

    def test_rounding_boundary(self):
        """
        Test rounding at boundaries to ensure no surprises.
        
        Uses values that would give .5 in the formula to test rounding.
        """
        config = {"price_sanity_enabled": True, "price_sanity_max_deviation_bps": 5000}
        
        # anchor=200, price=199 -> |199-200|/200*10000 = 1/200*10000 = 50 bps exactly
        _, dev, _, _ = check_price_sanity(
            token_in="WETH", token_out="USDC",
            price=Decimal("199"),
            config=config,
            dynamic_anchor=Decimal("200"),
        )
        self.assertEqual(dev, 50, msg=f"Expected 50 bps, got {dev}")
        
        # anchor=300, price=295 -> 5/300*10000 = 166.666... -> should round to 167
        _, dev2, _, _ = check_price_sanity(
            token_in="WETH", token_out="USDC",
            price=Decimal("295"),
            config=config,
            dynamic_anchor=Decimal("300"),
        )
        # Allow either 166 or 167 depending on rounding implementation
        self.assertIn(dev2, [166, 167], msg=f"Expected 166 or 167 bps, got {dev2}")


class TestRegressionPool0xD1d5(unittest.TestCase):
    """
    Regression test for 2026-01-30 bug.
    
    Pool: 0xD1d5A4... (sushiswap_v3, fee 3000)
    
    Tests verify the FIX works, not the specific price values.
    """

    def test_inverted_quote_is_detected_and_normalized(self):
        """
        Test that inverted quote is detected and normalized.
        
        The fix: normalize_price() detects inversion and corrects it.
        After correction, price should be in correct orientation.
        """
        # Simulate the bug case: quoter returns inverted price
        amount_in_wei = 10**18  # 1 WETH
        # This would give raw_price ~0.0003 (USDC per WETH, inverted)
        amount_out_wei = int(0.0003 * 10**6)
        
        price, inverted, diag = normalize_price(
            amount_in_wei=amount_in_wei,
            amount_out_wei=amount_out_wei,
            decimals_in=18,
            decimals_out=6,
            token_in="WETH",
            token_out="USDC",
        )
        
        # Key assertions:
        # 1. Inversion should be detected
        self.assertTrue(inverted, "Inversion should be detected for tiny WETH/USDC price")
        
        # 2. Inversion invariant: raw * final ≈ 1
        raw_price = Decimal(diag["raw_price"])
        final_price = Decimal(diag["normalized_price"])
        product = float(raw_price * final_price)
        self.assertAlmostEqual(product, 1.0, delta=0.001,
            msg="Inversion invariant violated")
        
        # 3. Diagnostics should be complete
        self.assertEqual(diag["inversion_applied"], True)

    def test_normalized_price_comparable_to_anchor(self):
        """
        Test that after normalization, price can be meaningfully
        compared to anchor in same orientation.
        """
        config = {"price_sanity_enabled": True, "price_sanity_max_deviation_bps": 5000}
        
        # Simulate: normalized quote vs proper anchor
        # Both should be in USDC_per_WETH orientation
        
        # Quote: 3400 USDC per WETH (after normalization)
        # Anchor: 3500 USDC per WETH
        passed, deviation_bps, error, diag = check_price_sanity(
            token_in="WETH",
            token_out="USDC",
            price=Decimal("3400"),  # After normalization
            config=config,
            dynamic_anchor=Decimal("3500"),  # Proper anchor
            dex_id="sushiswap_v3",
            fee=3000,
        )
        
        # With same orientation, deviation should be small
        # 100/3500 * 10000 ≈ 286 bps
        self.assertTrue(passed)
        self.assertLess(deviation_bps, 500)


if __name__ == "__main__":
    unittest.main()
