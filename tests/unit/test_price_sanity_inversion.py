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

3. API CONTRACT:
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
    """Test price normalization without auto-inversion."""

    def test_normal_weth_usdc_price(self):
        """Test normal WETH/USDC price (~2600 USDC per WETH)."""
        price, looks_inverted, diag = normalize_price(
            amount_in_wei=10**18,  # 1 WETH
            amount_out_wei=2600 * 10**6,  # 2600 USDC
            decimals_in=18,
            decimals_out=6,
            token_in="WETH",
            token_out="USDC",
        )
        
        self.assertAlmostEqual(float(price), 2600.0, delta=1.0)
        self.assertFalse(looks_inverted)
        self.assertEqual(diag["numeraire_side"], "USDC_per_WETH")

    def test_anomaly_detection_low_price(self):
        """Test that obviously wrong prices are detected (but NOT auto-fixed)."""
        price, looks_inverted, diag = normalize_price(
            amount_in_wei=10**18,  # 1 WETH
            amount_out_wei=int(9.036857 * 10**6),  # ~9 USDC (WRONG!)
            decimals_in=18,
            decimals_out=6,
            token_in="WETH",
            token_out="USDC",
        )
        
        # Price should be returned AS-IS (no auto-fix)
        self.assertAlmostEqual(float(price), 9.036857, delta=0.01)
        
        # Anomaly should be detected
        self.assertTrue(looks_inverted)
        self.assertIn("price_anomaly", diag)

    def test_diagnostics_include_all_fields(self):
        """Test that diagnostics include all required fields."""
        price, looks_inverted, diag = normalize_price(
            amount_in_wei=10**18,
            amount_out_wei=3000 * 10**6,
            decimals_in=18,
            decimals_out=6,
            token_in="WETH",
            token_out="USDC",
        )
        
        required_fields = [
            "amount_in_wei", "amount_out_wei", "decimals_in", "decimals_out",
            "token_in", "token_out", "numeraire_side", "in_normalized",
            "out_normalized", "raw_price_quote_per_base", "price_looks_inverted",
        ]
        
        for field in required_fields:
            self.assertIn(field, diag, f"Missing field: {field}")


class TestDeviationCalculation(unittest.TestCase):
    """Test deviation calculation formula."""

    def test_deviation_formula_exact(self):
        """Test exact deviation calculation."""
        # 10% deviation: |900 - 1000| / 1000 * 10000 = 1000 bps
        dev, dev_raw, capped = calculate_deviation_bps(Decimal("900"), Decimal("1000"))
        self.assertEqual(dev, 1000)
        self.assertEqual(dev_raw, 1000)
        self.assertFalse(capped)

    def test_deviation_capping(self):
        """Test that deviation is capped at MAX_DEVIATION_BPS_CAP (10000)."""
        # Very large deviation (should cap)
        # |9 - 2600| / 2600 * 10000 ≈ 99.65% ≈ 9965 bps (under cap)
        # Let's use a case that definitely exceeds cap
        # |1 - 1000| / 1000 * 10000 = 999/1000 * 10000 = 9990 bps (still under)
        # |1 - 10000| / 10000 * 10000 = 9999/10000 * 10000 = 9999 bps
        # Need bigger: |1 - 100000| / 100000 * 10000 = 99999/100000 * 10000 = 9999.9 bps
        # Still under 10000. Let's try explicit over-cap:
        # |0.1 - 1000| / 1000 * 10000 = 999.9/1000 * 10000 = 9999 bps
        # We need raw > 10000:
        # |1 - 20000| / 20000 * 10000 = 19999/20000 * 10000 = 9999.5 bps
        # Still not > 10000. Let's calculate what we need:
        # For raw > 10000: abs(p-a)/a > 1 → |p-a| > a → p > 2a or p < 0
        # So: price=0 vs anchor=100 → |0-100|/100*10000 = 10000 bps (exactly cap)
        # price=-10 vs anchor=100 → |-10-100|/100*10000 = 110/100*10000 = 11000 bps > cap
        # But price can't be negative in our use case.
        # Let's use: price=0.01, anchor=100 → |0.01-100|/100*10000 = 99.99/100*10000 = 9999 bps
        # Need: price=1, anchor=10000 → |1-10000|/10000*10000 = 9999/10000*10000 = 9999 bps
        # To get > 10000: |price - anchor| > anchor → price < 0 or price > 2*anchor
        # Let's use: price=3*anchor → |3a - a|/a = 2a/a = 2 → 20000 bps > cap
        dev, dev_raw, capped = calculate_deviation_bps(Decimal("3000"), Decimal("1000"))
        # |3000 - 1000| / 1000 * 10000 = 2000/1000 * 10000 = 20000 bps
        self.assertEqual(dev, MAX_DEVIATION_BPS_CAP)  # Capped at 10000
        self.assertEqual(dev_raw, 20000)  # Raw is 20000
        self.assertTrue(capped)

    def test_deviation_invariant_scaled_prices(self):
        """INVARIANT: Same percentage deviation gives same bps at any scale."""
        scales = [1, 10, 100, 1000]
        base_price = Decimal("90")
        base_anchor = Decimal("100")
        
        deviations = []
        for scale in scales:
            dev, _, _ = calculate_deviation_bps(base_price * scale, base_anchor * scale)
            deviations.append(dev)
        
        # All should be equal (1000 bps = 10%)
        for dev in deviations:
            self.assertEqual(dev, 1000)

    def test_deviation_symmetric(self):
        """Test that deviation is symmetric above/below anchor."""
        dev_below, _, _ = calculate_deviation_bps(Decimal("900"), Decimal("1000"))
        dev_above, _, _ = calculate_deviation_bps(Decimal("1100"), Decimal("1000"))
        
        self.assertEqual(dev_below, dev_above)


class TestPriceSanity(unittest.TestCase):
    """Test price sanity check."""

    def test_sanity_passes_normal_price(self):
        """Test that normal price passes sanity."""
        config = {"price_sanity_enabled": True, "price_sanity_max_deviation_bps": 5000}
        
        passed, dev, error, diag = check_price_sanity(
            token_in="WETH",
            token_out="USDC",
            price=Decimal("2800"),
            config=config,
            dynamic_anchor=Decimal("2600"),
        )
        
        self.assertTrue(passed)
        self.assertLess(dev, 1000)  # ~8% deviation
        self.assertEqual(diag["anchor_source"], "dynamic")

    def test_sanity_fails_wrong_price(self):
        """Test that obviously wrong price fails sanity."""
        config = {"price_sanity_enabled": True, "price_sanity_max_deviation_bps": 5000}
        
        # 9 USDC per WETH vs anchor 2600 = huge deviation
        # |9 - 2600| / 2600 * 10000 = 2591/2600 * 10000 ≈ 9965 bps
        passed, dev, error, diag = check_price_sanity(
            token_in="WETH",
            token_out="USDC",
            price=Decimal("9.036857"),
            config=config,
            dynamic_anchor=Decimal("2600"),
        )
        
        self.assertFalse(passed)
        # Raw deviation is ~9965 bps (under cap), not capped
        self.assertFalse(diag.get("deviation_bps_capped", False))
        self.assertIn("error", diag)

    def test_sanity_capped_deviation(self):
        """Test that huge deviations are capped and flagged."""
        config = {"price_sanity_enabled": True, "price_sanity_max_deviation_bps": 5000}
        
        # Price 10x higher than anchor → 900% deviation → capped at 100%
        passed, dev, error, diag = check_price_sanity(
            token_in="WETH",
            token_out="USDC",
            price=Decimal("26000"),  # 10x anchor
            config=config,
            dynamic_anchor=Decimal("2600"),
        )
        
        self.assertFalse(passed)
        self.assertEqual(dev, MAX_DEVIATION_BPS_CAP)  # Capped at 10000
        self.assertTrue(diag["deviation_bps_capped"])
        self.assertGreater(diag["deviation_bps_raw"], MAX_DEVIATION_BPS_CAP)

    def test_anchor_source_backward_compatible(self):
        """Test that anchor_source parameter is accepted (backward compatibility)."""
        config = {"price_sanity_enabled": True}
        
        # This call should NOT raise TypeError
        passed, dev, error, diag = check_price_sanity(
            token_in="WETH",
            token_out="USDC",
            price=Decimal("2600"),
            config=config,
            dynamic_anchor=Decimal("2600"),
            anchor_source="dynamic_first_quote",  # Backward compatible param
        )
        
        self.assertTrue(passed)
        self.assertEqual(diag["anchor_source"], "dynamic_first_quote")

    def test_anchor_info_takes_priority(self):
        """Test that anchor_info takes priority over anchor_source string."""
        config = {"price_sanity_enabled": True}
        anchor_info = {"source": "anchor_dex", "dex_id": "uniswap_v3"}
        
        passed, dev, error, diag = check_price_sanity(
            token_in="WETH",
            token_out="USDC",
            price=Decimal("2600"),
            config=config,
            dynamic_anchor=Decimal("2600"),
            anchor_info=anchor_info,
            anchor_source="ignored_string",  # Should be ignored
        )
        
        self.assertTrue(passed)
        # anchor_info.source takes priority
        self.assertEqual(diag["anchor_source"], "anchor_dex")
        self.assertEqual(diag["anchor_details"]["dex_id"], "uniswap_v3")


class TestAnchorSelection(unittest.TestCase):
    """Test anchor selection priority."""

    def test_anchor_dex_priority(self):
        """Test that anchor_dex has priority over others."""
        quotes = [
            AnchorQuote(dex_id="sushiswap_v3", price=Decimal("2500"), fee=3000, pool_address="0x111", block_number=100),
            AnchorQuote(dex_id="uniswap_v3", price=Decimal("2600"), fee=500, pool_address="0x222", block_number=100),
        ]
        
        result = select_anchor(quotes, ("WETH", "USDC"))
        self.assertIsNotNone(result)
        
        anchor_price, info = result
        self.assertEqual(float(anchor_price), 2600.0)
        self.assertEqual(info["source"], "anchor_dex")
        self.assertEqual(info["dex_id"], "uniswap_v3")

    def test_median_when_no_anchor_dex(self):
        """Test median selection when no priority DEX."""
        quotes = [
            AnchorQuote(dex_id="camelot", price=Decimal("2400"), fee=3000, pool_address="0x111", block_number=100),
            AnchorQuote(dex_id="velodrome", price=Decimal("2600"), fee=500, pool_address="0x222", block_number=100),
            AnchorQuote(dex_id="trader_joe", price=Decimal("2800"), fee=500, pool_address="0x333", block_number=100),
        ]
        
        result = select_anchor(quotes, ("WETH", "USDC"))
        self.assertIsNotNone(result)
        
        anchor_price, info = result
        self.assertEqual(float(anchor_price), 2600.0)  # Median
        self.assertEqual(info["source"], "median_quotes")

    def test_hardcoded_fallback_no_quotes(self):
        """Test hardcoded bounds fallback when no quotes."""
        result = select_anchor([], ("WETH", "USDC"))
        
        self.assertIsNotNone(result)
        anchor_price, info = result
        self.assertEqual(info["source"], "hardcoded_bounds")


class TestAPIContract(unittest.TestCase):
    """Test API contract stability."""

    def test_check_price_sanity_accepts_all_params(self):
        """Test that check_price_sanity accepts all documented parameters."""
        config = {"price_sanity_enabled": True}
        
        # All parameters should be accepted without TypeError
        passed, dev, error, diag = check_price_sanity(
            token_in="WETH",
            token_out="USDC",
            price=Decimal("2600"),
            config=config,
            dynamic_anchor=Decimal("2600"),
            fee=3000,
            decimals_in=18,
            decimals_out=6,
            dex_id="sushiswap_v3",
            pool_address="0xD1d5A4...",
            amount_in_wei=10**18,
            amount_out_wei=2600 * 10**6,
            anchor_info={"source": "anchor_dex", "dex_id": "uniswap_v3"},
            anchor_source="dynamic",  # Backward compatible
        )
        
        self.assertTrue(passed)

    def test_calculate_deviation_bps_returns_3_values(self):
        """Test that calculate_deviation_bps returns 3 values."""
        result = calculate_deviation_bps(Decimal("900"), Decimal("1000"))
        
        self.assertEqual(len(result), 3)
        dev, dev_raw, capped = result
        self.assertIsInstance(dev, int)
        self.assertIsInstance(dev_raw, int)
        self.assertIsInstance(capped, bool)


if __name__ == "__main__":
    unittest.main()
