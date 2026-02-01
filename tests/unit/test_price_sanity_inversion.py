# PATH: tests/unit/test_price_sanity_inversion.py
"""
Price sanity regression tests.

CONTRACTS VERIFIED:
1. inversion_applied = False (ALWAYS)
2. 5% deviation = exactly 500 bps (Decimal math)
3. capped deviation = 10000 with deviation_bps_capped=True
4. anchor_source parameter accepted
"""

import unittest
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class TestDeviationCalculation(unittest.TestCase):
    """Test calculate_deviation_bps with Decimal math."""

    def test_5_percent_deviation_is_exactly_500_bps(self):
        """5% deviation MUST be exactly 500 bps."""
        from core.validators import calculate_deviation_bps
        
        # 105 vs 100 = 5% deviation
        dev, raw, capped = calculate_deviation_bps(Decimal("105"), Decimal("100"))
        self.assertEqual(dev, 500, "5% deviation should be exactly 500 bps")
        self.assertEqual(raw, 500)
        self.assertFalse(capped)
        
        # Also test the other direction
        dev, raw, capped = calculate_deviation_bps(Decimal("95"), Decimal("100"))
        self.assertEqual(dev, 500, "5% deviation (down) should be exactly 500 bps")

    def test_1_percent_deviation_is_100_bps(self):
        """1% deviation = 100 bps."""
        from core.validators import calculate_deviation_bps
        
        dev, raw, capped = calculate_deviation_bps(Decimal("101"), Decimal("100"))
        self.assertEqual(dev, 100)

    def test_0_5_percent_deviation_is_50_bps(self):
        """0.5% deviation = 50 bps."""
        from core.validators import calculate_deviation_bps
        
        dev, raw, capped = calculate_deviation_bps(Decimal("100.5"), Decimal("100"))
        self.assertEqual(dev, 50)

    def test_capping_at_10000_bps(self):
        """Large deviation MUST be capped at 10000 bps."""
        from core.validators import calculate_deviation_bps, MAX_DEVIATION_BPS_CAP
        
        # 200% deviation = 20000 bps raw, should cap to 10000
        dev, raw, capped = calculate_deviation_bps(Decimal("300"), Decimal("100"))
        self.assertEqual(dev, MAX_DEVIATION_BPS_CAP)
        self.assertEqual(raw, 20000)
        self.assertTrue(capped)

    def test_exact_cap_boundary(self):
        """100% deviation = exactly 10000 bps (at cap, not capped)."""
        from core.validators import calculate_deviation_bps
        
        # 200 vs 100 = 100% deviation = 10000 bps
        dev, raw, capped = calculate_deviation_bps(Decimal("200"), Decimal("100"))
        self.assertEqual(dev, 10000)
        self.assertEqual(raw, 10000)
        self.assertFalse(capped)  # Exactly at cap, not over

    def test_weth_usdc_realistic_deviation(self):
        """Test realistic WETH/USDC deviation."""
        from core.validators import calculate_deviation_bps
        
        # 2730 vs 2600 anchor = 5% deviation
        dev, raw, capped = calculate_deviation_bps(Decimal("2730"), Decimal("2600"))
        self.assertEqual(dev, 500)

    def test_sushi_suspect_quote_deviation(self):
        """Test suspect quote from Sushi with huge deviation."""
        from core.validators import calculate_deviation_bps
        
        # 8.605 vs 2600 = ~99.67% deviation = ~9967 bps
        dev, raw, capped = calculate_deviation_bps(Decimal("8.605"), Decimal("2600"))
        self.assertGreater(raw, 9900)
        self.assertLess(raw, 10000)
        self.assertFalse(capped)  # Just under cap


class TestNormalizePriceInversion(unittest.TestCase):
    """Test normalize_price always has inversion_applied=False."""

    def test_inversion_applied_always_false(self):
        """inversion_applied MUST always be False."""
        from core.validators import normalize_price
        
        price, diag = normalize_price(
            amount_in_wei=10**18,
            amount_out_wei=2600 * 10**6,
            decimals_in=18,
            decimals_out=6,
            token_in="WETH",
            token_out="USDC",
        )
        
        self.assertIn("inversion_applied", diag)
        self.assertEqual(diag["inversion_applied"], False)

    def test_suspect_quote_detection(self):
        """Suspect quotes should be flagged."""
        from core.validators import normalize_price
        
        # Price way below expected (8.6 vs expected 1500-6000)
        price, diag = normalize_price(
            amount_in_wei=10**18,
            amount_out_wei=8_600_000,  # 8.6 USDC
            decimals_in=18,
            decimals_out=6,
            token_in="WETH",
            token_out="USDC",
        )
        
        self.assertIn("suspect_quote", diag)
        self.assertTrue(diag["suspect_quote"])
        self.assertEqual(diag["suspect_reason"], "way_below_expected")


class TestCheckPriceSanityContract(unittest.TestCase):
    """Test check_price_sanity contract."""

    def test_anchor_source_parameter_accepted(self):
        """check_price_sanity MUST accept anchor_source parameter."""
        from core.validators import check_price_sanity
        
        passed, dev, err, diag = check_price_sanity(
            price=Decimal("2600"),
            anchor_price=Decimal("2600"),
            pair="WETH/USDC",
            dex_id="uniswap_v3",
            anchor_source="uniswap_v3_500",
        )
        
        self.assertTrue(passed)
        self.assertEqual(diag.get("anchor_source"), "uniswap_v3_500")

    def test_deviation_bps_capped_flag_exists(self):
        """deviation_bps_capped MUST be in diagnostics."""
        from core.validators import check_price_sanity
        
        passed, dev, err, diag = check_price_sanity(
            price=Decimal("2600"),
            anchor_price=Decimal("2600"),
            pair="WETH/USDC",
            dex_id="uniswap_v3",
        )
        
        self.assertIn("deviation_bps_capped", diag)
        self.assertFalse(diag["deviation_bps_capped"])

    def test_capped_deviation_has_flag_true(self):
        """When deviation > cap, deviation_bps_capped MUST be True."""
        from core.validators import check_price_sanity
        
        # Huge deviation that will be capped
        passed, dev, err, diag = check_price_sanity(
            price=Decimal("8000"),
            anchor_price=Decimal("2600"),
            pair="WETH/USDC",
            dex_id="sushiswap_v3",
            max_deviation_bps=5000,
        )
        
        self.assertFalse(passed)
        self.assertIn("deviation_bps_capped", diag)
        # Raw deviation is >10000 for this extreme case, so it will be capped
        # Actually 8000 vs 2600 = ~208% deviation = ~20769 bps
        self.assertTrue(diag["deviation_bps_capped"])

    def test_inversion_applied_always_false_in_sanity(self):
        """inversion_applied MUST be False in check_price_sanity."""
        from core.validators import check_price_sanity
        
        passed, dev, err, diag = check_price_sanity(
            price=Decimal("2600"),
            anchor_price=Decimal("2600"),
            pair="WETH/USDC",
            dex_id="uniswap_v3",
        )
        
        self.assertIn("inversion_applied", diag)
        self.assertEqual(diag["inversion_applied"], False)


class TestSushiFee3000SuspectQuote(unittest.TestCase):
    """Regression test for Sushi fee=3000 suspect quote issue."""

    def test_sushi_3000_deviation_detection(self):
        """Sushi fee=3000 bad quote should be flagged correctly."""
        from core.validators import check_price_sanity, normalize_price
        
        # Simulate the bad Sushi quote: WETH->USDC returns 8.6 USDC
        price, norm_diag = normalize_price(
            amount_in_wei=10**18,
            amount_out_wei=8_605_000,  # 8.605 USDC
            decimals_in=18,
            decimals_out=6,
            token_in="WETH",
            token_out="USDC",
        )
        
        # Should be flagged as suspect
        self.assertTrue(norm_diag.get("suspect_quote", False))
        
        # Run sanity check
        passed, dev, err, sanity_diag = check_price_sanity(
            price=price,
            anchor_price=Decimal("2600"),
            pair="WETH/USDC",
            dex_id="sushiswap_v3",
            fee_tier=3000,
            max_deviation_bps=5000,
            anchor_source="uniswap_v3_500",
        )
        
        # Should fail sanity check
        self.assertFalse(passed)
        self.assertIsNotNone(err)
        # Error message contains "Deviation" and "> max"
        self.assertIn("deviation", err.lower())
        self.assertEqual(sanity_diag.get("error"), "deviation_exceeded")


if __name__ == "__main__":
    unittest.main()
