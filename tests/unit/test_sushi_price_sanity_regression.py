"""
Regression tests for Sushi PRICE_SANITY failures (v2.3.2).

These tests capture real-world regression cases from production runs
where Sushi pools had extreme prices (tick near MAX_TICK / MIN_TICK).

Issue context:
- Sushi V3 pools on Arbitrum can report extreme sqrtPriceX96 values
- tick=887271 (MAX_TICK) produces price_exact ~ 3.4e28 for WBTC/WETH
- PRICE_SANITY gate must reject such outliers with 5000bps threshold

Evidence runDir: ci_m5_gate_20260219_144126
"""
import pytest
from decimal import Decimal

from core.validators import check_price_sanity


class TestSushiPriceSanityRegression:
    """Regression tests for Sushi pools with outlier prices."""

    # Real cases from production (generalized values)
    REAL_CASES = [
        # (pair, dex_id, fee_tier, observed_price, anchor_price, expected_pass)
        ("WBTC/WETH", "sushi", 500, Decimal("3.4e28"), Decimal("35.0"), False),
        ("WETH/USDC", "sushi", 500, Decimal("1.2e25"), Decimal("3500.0"), False),
        ("WBTC/USDC", "sushi", 3000, Decimal("87000.0"), Decimal("97500.0"), True),  # normal
        ("WETH/USDC", "sushi", 3000, Decimal("3450.0"), Decimal("3500.0"), True),  # normal
        # Edge case: price near zero (should fail)
        ("ARB/WETH", "sushi", 3000, Decimal("1e-30"), Decimal("0.0005"), False),
    ]

    @pytest.mark.parametrize("pair,dex_id,fee_tier,observed,anchor,expected_pass", REAL_CASES)
    def test_real_case_regression(self, pair, dex_id, fee_tier, observed, anchor, expected_pass):
        """Test real Sushi price sanity cases."""
        passed, dev_bps, err, diag = check_price_sanity(
            price=observed,
            anchor_price=anchor,
            pair=pair,
            dex_id=dex_id,
            fee_tier=fee_tier,
            max_deviation_bps=5000,  # 50% max deviation
        )
        
        assert passed == expected_pass, (
            f"{pair}@{dex_id} fee={fee_tier}: expected_pass={expected_pass}, got={passed}, "
            f"err={err}, dev_bps={dev_bps}"
        )
        
        # Verify diagnostic fields exist
        assert "deviation_bps" in diag
        assert "deviation_bps_raw" in diag
        assert "deviation_bps_capped" in diag
        assert diag["inversion_applied"] is False  # Contract: never invert

    def test_extreme_tick_max_produces_rejection(self):
        """Extreme tick (MAX_TICK) must produce PRICE_SANITY_FAILED."""
        # tick=887271 (MAX_TICK) for WBTC/WETH
        extreme_price = Decimal("3.4e28")
        anchor = Decimal("35.0")  # Realistic WBTC/WETH anchor
        
        passed, dev_bps, err, diag = check_price_sanity(
            price=extreme_price,
            anchor_price=anchor,
            pair="WBTC/WETH",
            dex_id="sushi",
            fee_tier=500,
            max_deviation_bps=5000,
        )
        
        assert passed is False
        assert "deviation" in err.lower() or "exceeded" in err.lower()
        assert diag["deviation_bps_capped"] is True  # Raw > cap

    def test_extreme_tick_min_produces_rejection(self):
        """Extreme tick (MIN_TICK) must produce PRICE_SANITY_FAILED."""
        # tick=-887272 (MIN_TICK) produces extremely small price
        extreme_price = Decimal("1e-35")
        anchor = Decimal("0.0005")  # Realistic ARB/WETH anchor
        
        passed, dev_bps, err, diag = check_price_sanity(
            price=extreme_price,
            anchor_price=anchor,
            pair="ARB/WETH",
            dex_id="sushi",
            fee_tier=3000,
            max_deviation_bps=5000,
        )
        
        assert passed is False
        assert diag["deviation_bps_capped"] is True

    def test_normal_price_within_threshold_passes(self):
        """Normal prices within 50% deviation should pass."""
        price = Decimal("3300.0")  # 5.7% below anchor
        anchor = Decimal("3500.0")
        
        passed, dev_bps, err, diag = check_price_sanity(
            price=price,
            anchor_price=anchor,
            pair="WETH/USDC",
            dex_id="sushi",
            fee_tier=500,
            max_deviation_bps=5000,
        )
        
        assert passed is True
        assert err is None
        assert dev_bps < 5000

    def test_diagnostic_fields_populated(self):
        """Verify all diagnostic fields are populated correctly."""
        passed, dev_bps, err, diag = check_price_sanity(
            price=Decimal("100.0"),
            anchor_price=Decimal("100.0"),
            pair="TEST/TEST",
            dex_id="sushi",
            fee_tier=3000,
            max_deviation_bps=5000,
            anchor_source="pyth_feed",
            pool_address="0x1234",
        )
        
        assert passed is True
        assert diag["pair"] == "TEST/TEST"
        assert diag["dex_id"] == "sushi"
        assert diag["fee_tier"] == 3000
        assert diag["pool_address"] == "0x1234"
        assert diag["anchor_source"] == "pyth_feed"
        assert diag["inversion_applied"] is False
        assert diag["deviation_bps_capped"] is False
        assert "implied_price" in diag
        assert "anchor_price" in diag


class TestSushiSpecificBehavior:
    """Sushi-specific regression tests."""

    def test_sushi_fee_tiers_all_validated(self):
        """All Sushi fee tiers (100, 500, 3000, 10000) use same sanity check."""
        fee_tiers = [100, 500, 3000, 10000]
        anchor = Decimal("3500.0")
        
        for fee_tier in fee_tiers:
            passed, _, _, diag = check_price_sanity(
                price=Decimal("3550.0"),  # 1.4% deviation
                anchor_price=anchor,
                pair="WETH/USDC",
                dex_id="sushi",
                fee_tier=fee_tier,
                max_deviation_bps=5000,
            )
            assert passed is True, f"fee_tier={fee_tier} should pass"
            assert diag["fee_tier"] == fee_tier

    def test_sushi_uni_same_logic(self):
        """Sushi and Uniswap use same price sanity logic (no special casing)."""
        price = Decimal("3.4e28")  # Extreme
        anchor = Decimal("35.0")
        
        sushi_result = check_price_sanity(
            price=price, anchor_price=anchor,
            pair="WBTC/WETH", dex_id="sushi", fee_tier=500,
            max_deviation_bps=5000,
        )
        
        uni_result = check_price_sanity(
            price=price, anchor_price=anchor,
            pair="WBTC/WETH", dex_id="uniswap_v3", fee_tier=500,
            max_deviation_bps=5000,
        )
        
        # Both should fail identically
        assert sushi_result[0] == uni_result[0] == False
        assert sushi_result[1] == uni_result[1]  # Same dev_bps
