# PATH: tests/unit/test_price_sanity_inversion.py
"""
Price sanity validation tests.

CONTRACTS TESTED:
1. Price = quote_token per 1 base_token
2. inversion_applied is ALWAYS False
3. deviation_bps formula and cap semantics
4. AnchorQuote.dex_id is required
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
            decimals_in=18, decimals_out=6,
            token_in="WETH", token_out="USDC",
        )
        
        self.assertAlmostEqual(float(price), 2600.0, delta=1.0)
        self.assertFalse(suspect)
        self.assertEqual(diag["numeraire_side"], "USDC_per_WETH")
        self.assertEqual(diag["inversion_applied"], False)

    def test_inversion_applied_always_false(self):
        """CRITICAL: inversion_applied is ALWAYS False."""
        test_cases = [
            (2600 * 10**6, False),     # Normal
            (int(8.6 * 10**6), True),  # Suspect low
            (int(0.001 * 10**6), True),# Very low
            (50000 * 10**6, True),     # Suspect high
        ]
        
        for amount_out, _ in test_cases:
            _, _, diag = normalize_price(
                amount_in_wei=10**18,
                amount_out_wei=amount_out,
                decimals_in=18, decimals_out=6,
                token_in="WETH", token_out="USDC",
            )
            self.assertEqual(diag["inversion_applied"], False)

    def test_suspect_quote_flagged(self):
        """Test suspect quote flagged correctly."""
        price, suspect, diag = normalize_price(
            amount_in_wei=10**18,
            amount_out_wei=int(8.6 * 10**6),
            decimals_in=18, decimals_out=6,
            token_in="WETH", token_out="USDC",
        )
        
        self.assertTrue(suspect)
        self.assertEqual(diag["suspect_quote"], True)
        self.assertEqual(diag["suspect_reason"], "way_below_expected")
        self.assertEqual(diag["inversion_applied"], False)

    def test_raw_price_not_zero_placeholder(self):
        """Test raw_price is actual value, not "0"."""
        price, _, diag = normalize_price(
            amount_in_wei=10**18,
            amount_out_wei=2600 * 10**6,
            decimals_in=18, decimals_out=6,
            token_in="WETH", token_out="USDC",
        )
        
        raw = diag["raw_price_quote_per_base"]
        self.assertIsNotNone(raw)
        self.assertNotEqual(raw, "0")

    def test_raw_price_none_on_zero_input(self):
        """Test raw_price is None on zero input."""
        _, _, diag = normalize_price(
            amount_in_wei=0,
            amount_out_wei=2600 * 10**6,
            decimals_in=18, decimals_out=6,
            token_in="WETH", token_out="USDC",
        )
        
        self.assertIsNone(diag["raw_price_quote_per_base"])


class TestDeviationCalculation(unittest.TestCase):
    """Test deviation calculation."""

    def test_exact_deviation(self):
        """Test exact deviation."""
        dev, dev_raw, capped = calculate_deviation_bps(Decimal("900"), Decimal("1000"))
        self.assertEqual(dev, 1000)
        self.assertEqual(dev_raw, 1000)
        self.assertFalse(capped)

    def test_deviation_capping(self):
        """Test cap at 10000 bps."""
        dev, dev_raw, capped = calculate_deviation_bps(Decimal("3000"), Decimal("1000"))
        
        self.assertEqual(dev, MAX_DEVIATION_BPS_CAP)
        self.assertEqual(dev_raw, 20000)
        self.assertTrue(capped)

    def test_deviation_invariant(self):
        """INVARIANT: Same % gives same bps."""
        for scale in [1, 10, 100, 1000]:
            dev, _, _ = calculate_deviation_bps(Decimal(90 * scale), Decimal(100 * scale))
            self.assertEqual(dev, 1000)


class TestPriceSanity(unittest.TestCase):
    """Test price sanity check."""

    def test_sanity_passes_normal(self):
        """Normal price passes."""
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
        """Suspect quote fails."""
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


class TestAnchorQuote(unittest.TestCase):
    """Test AnchorQuote."""

    def test_dex_id_required(self):
        """Test dex_id is required."""
        quote = AnchorQuote(
            dex_id="uniswap_v3",
            price=Decimal("2600"),
            fee=500,
            pool_address="0x1234",
            block_number=100,
        )
        self.assertEqual(quote.dex_id, "uniswap_v3")

    def test_is_from_anchor_dex(self):
        """Test is_from_anchor_dex property."""
        quote = AnchorQuote(
            dex_id="uniswap_v3",
            price=Decimal("2600"),
            fee=500,
            pool_address="0x1234",
            block_number=100,
        )
        self.assertTrue(quote.is_from_anchor_dex)


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
    """Regression tests."""

    def test_sushi_v3_bad_quote(self):
        """Sushi v3 bad quote: 8.6 USDC per WETH."""
        price, suspect, norm_diag = normalize_price(
            amount_in_wei=10**18,
            amount_out_wei=int(8.605 * 10**6),
            decimals_in=18, decimals_out=6,
            token_in="WETH", token_out="USDC",
        )
        
        self.assertEqual(norm_diag["inversion_applied"], False)
        self.assertTrue(suspect)
        
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
