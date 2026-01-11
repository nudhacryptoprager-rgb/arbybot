"""
tests/unit/test_math.py - Tests for core/math.py

Critical tests for:
- No-float enforcement
- Wei/decimal conversions
- BPS calculations
- Price impact
"""

import pytest
from decimal import Decimal

from core.math import (
    # BPS
    bps_to_decimal,
    decimal_to_bps,
    calculate_bps_diff,
    # Wei conversions
    wei_to_eth,
    eth_to_wei,
    wei_to_gwei,
    gwei_to_wei,
    wei_to_human,
    human_to_wei,
    # Safe conversions
    safe_decimal,
    safe_int,
    validate_no_float,
    # PnL
    calculate_net_pnl,
    calculate_price_impact_bps,
    normalize_price,
    # Rounding
    round_down,
    round_up,
)
from core.exceptions import ValidationError


class TestNoFloatEnforcement:
    """Test that float values are rejected."""
    
    def test_safe_decimal_rejects_float(self):
        """safe_decimal must reject float input."""
        with pytest.raises(ValidationError) as exc_info:
            safe_decimal(1.5)
        assert "Float values are not allowed" in str(exc_info.value)
    
    def test_safe_decimal_accepts_int(self):
        """safe_decimal accepts int."""
        result = safe_decimal(100)
        assert result == Decimal("100")
    
    def test_safe_decimal_accepts_str(self):
        """safe_decimal accepts string."""
        result = safe_decimal("123.456")
        assert result == Decimal("123.456")
    
    def test_safe_decimal_accepts_decimal(self):
        """safe_decimal accepts Decimal."""
        result = safe_decimal(Decimal("99.99"))
        assert result == Decimal("99.99")
    
    def test_safe_int_rejects_float(self):
        """safe_int must reject float input."""
        with pytest.raises(ValidationError) as exc_info:
            safe_int(1.5)
        assert "Float values are not allowed" in str(exc_info.value)
    
    def test_safe_int_accepts_int(self):
        """safe_int accepts int."""
        result = safe_int(1000000)
        assert result == 1000000
    
    def test_safe_int_accepts_decimal(self):
        """safe_int accepts Decimal and truncates."""
        result = safe_int(Decimal("100.9"))
        assert result == 100  # ROUND_DOWN
    
    def test_validate_no_float_raises(self):
        """validate_no_float raises on any float."""
        with pytest.raises(ValidationError):
            validate_no_float(1, 2, 3.0, 4)
    
    def test_validate_no_float_passes(self):
        """validate_no_float passes with no floats."""
        validate_no_float(1, Decimal("2"), "3", None)  # Should not raise


class TestWeiConversions:
    """Test wei/ETH/gwei conversions."""
    
    def test_wei_to_eth(self):
        """Convert wei to ETH."""
        result = wei_to_eth(1_000_000_000_000_000_000)  # 1 ETH in wei
        assert result == Decimal("1")
    
    def test_wei_to_eth_fractional(self):
        """Convert fractional wei to ETH."""
        result = wei_to_eth(500_000_000_000_000_000)  # 0.5 ETH
        assert result == Decimal("0.5")
    
    def test_eth_to_wei(self):
        """Convert ETH to wei."""
        result = eth_to_wei(Decimal("1"))
        assert result == 1_000_000_000_000_000_000
    
    def test_eth_to_wei_string(self):
        """Convert ETH string to wei."""
        result = eth_to_wei("0.5")
        assert result == 500_000_000_000_000_000
    
    def test_wei_to_gwei(self):
        """Convert wei to gwei."""
        result = wei_to_gwei(1_000_000_000)  # 1 gwei
        assert result == Decimal("1")
    
    def test_gwei_to_wei(self):
        """Convert gwei to wei."""
        result = gwei_to_wei(10)
        assert result == 10_000_000_000


class TestTokenConversions:
    """Test token amount conversions."""
    
    def test_wei_to_human_usdc(self):
        """Convert USDC wei to human (6 decimals)."""
        result = wei_to_human(1_000_000, 6)  # 1 USDC
        assert result == Decimal("1")
    
    def test_wei_to_human_eth(self):
        """Convert ETH wei to human (18 decimals)."""
        result = wei_to_human(1_000_000_000_000_000_000, 18)
        assert result == Decimal("1")
    
    def test_human_to_wei_usdc(self):
        """Convert human USDC to wei."""
        result = human_to_wei(Decimal("100.50"), 6)
        assert result == 100_500_000
    
    def test_human_to_wei_eth(self):
        """Convert human ETH to wei."""
        result = human_to_wei("0.1", 18)
        assert result == 100_000_000_000_000_000
    
    def test_invalid_decimals_raises(self):
        """Invalid decimals should raise."""
        with pytest.raises(ValidationError):
            wei_to_human(1000, 19)  # > 18
        with pytest.raises(ValidationError):
            wei_to_human(1000, -1)  # < 0


class TestBpsCalculations:
    """Test basis points calculations."""
    
    def test_bps_to_decimal(self):
        """Convert bps to decimal."""
        assert bps_to_decimal(100) == Decimal("0.01")  # 1%
        assert bps_to_decimal(50) == Decimal("0.005")  # 0.5%
        assert bps_to_decimal(1) == Decimal("0.0001")  # 0.01%
    
    def test_decimal_to_bps(self):
        """Convert decimal to bps."""
        assert decimal_to_bps(Decimal("0.01")) == Decimal("100")
        assert decimal_to_bps(Decimal("0.005")) == Decimal("50")
    
    def test_calculate_bps_diff(self):
        """Calculate bps difference."""
        # 10% increase: (110 - 100) / 100 * 10000 = 1000 bps
        result = calculate_bps_diff(Decimal("110"), Decimal("100"))
        assert result == Decimal("1000")
    
    def test_calculate_bps_diff_negative(self):
        """Calculate negative bps difference."""
        # 5% decrease: (95 - 100) / 100 * 10000 = -500 bps
        result = calculate_bps_diff(Decimal("95"), Decimal("100"))
        assert result == Decimal("-500")
    
    def test_calculate_bps_diff_zero_base(self):
        """Zero base returns zero."""
        result = calculate_bps_diff(Decimal("100"), Decimal("0"))
        assert result == Decimal("0")


class TestPriceImpact:
    """Test price impact calculations."""
    
    def test_price_impact_positive(self):
        """Larger trade has worse price (positive impact)."""
        # Small trade: 100 in -> 99 out (price = 0.99)
        # Large trade: 1000 in -> 980 out (price = 0.98)
        # Impact = (0.99 - 0.98) / 0.99 * 10000 ≈ 101 bps
        result = calculate_price_impact_bps(
            amount_in=1000,
            amount_out=980,
            amount_in_small=100,
            amount_out_small=99,
        )
        assert result > Decimal("100")  # ~101 bps
        assert result < Decimal("102")
    
    def test_price_impact_zero(self):
        """Same price ratio = zero impact."""
        result = calculate_price_impact_bps(
            amount_in=1000,
            amount_out=990,
            amount_in_small=100,
            amount_out_small=99,
        )
        assert result == Decimal("0")
    
    def test_price_impact_zero_inputs(self):
        """Zero inputs return zero."""
        result = calculate_price_impact_bps(1000, 980, 0, 0)
        assert result == Decimal("0")


class TestNormalizePrice:
    """Test price normalization across different decimals."""
    
    def test_same_decimals(self):
        """Different decimals, normalized ratio."""
        # 1000 USDC -> 1 ETH
        # Normalized: 1 ETH / 1000 USDC = 0.001 ETH per USDC
        result = normalize_price(
            amount_in=1000_000_000,  # 1000 USDC (6 dec)
            amount_out=1_000_000_000_000_000_000,  # 1 ETH (18 dec)
            decimals_in=6,
            decimals_out=18,
        )
        assert result == Decimal("0.001")  # 0.001 ETH per USDC
    
    def test_different_decimals(self):
        """Different decimals normalized correctly."""
        # 100 USDC (6 dec) -> 50 DAI (18 dec)
        result = normalize_price(
            amount_in=100_000_000,  # 100 USDC
            amount_out=50_000_000_000_000_000_000,  # 50 DAI
            decimals_in=6,
            decimals_out=18,
        )
        assert result == Decimal("0.5")  # 0.5 DAI per USDC


class TestRounding:
    """Test rounding functions."""
    
    def test_round_down(self):
        """Round down to decimals."""
        assert round_down(Decimal("1.999"), 2) == Decimal("1.99")
        assert round_down(Decimal("1.991"), 2) == Decimal("1.99")
    
    def test_round_up(self):
        """Round up to decimals."""
        assert round_up(Decimal("1.001"), 2) == Decimal("1.01")
        assert round_up(Decimal("1.999"), 2) == Decimal("2.00")


class TestNetPnL:
    """Test net PnL calculation."""
    
    def test_calculate_net_pnl_profit(self):
        """Calculate positive PnL."""
        result = calculate_net_pnl(
            revenue_wei=110_000_000,  # 110 USDC
            cost_wei=100_000_000,  # 100 USDC
            gas_cost_wei=500_000,  # 0.5 USDC
            decimals=6,
        )
        assert result == Decimal("9.5")  # 110 - 100 - 0.5 = 9.5
    
    def test_calculate_net_pnl_loss(self):
        """Calculate negative PnL."""
        result = calculate_net_pnl(
            revenue_wei=95_000_000,
            cost_wei=100_000_000,
            gas_cost_wei=500_000,
            decimals=6,
        )
        assert result == Decimal("-5.5")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
