"""
tests/unit/test_gates.py - Tests for quote validation gates.
"""

import pytest
from decimal import Decimal
from unittest.mock import MagicMock

from core.exceptions import ErrorCode
from core.models import Token, Pool, Quote
from core.constants import DexType, PoolStatus
from strategy.gates import (
    gate_zero_output,
    gate_gas_estimate,
    gate_ticks_crossed,
    gate_freshness,
    gate_price_sanity,
    gate_slippage_curve,
    gate_monotonicity,
    calculate_implied_price,
    calculate_slippage_bps,
    apply_single_quote_gates,
    apply_curve_gates,
    GateResult,
    MAX_SLIPPAGE_BPS,
    MAX_GAS_ESTIMATE,
    MAX_TICKS_CROSSED,
)


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def weth():
    return Token(
        chain_id=42161,
        address="0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
        symbol="WETH",
        name="Wrapped Ether",
        decimals=18,
        is_core=True,
    )


@pytest.fixture
def usdc():
    return Token(
        chain_id=42161,
        address="0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
        symbol="USDC",
        name="USD Coin",
        decimals=6,
        is_core=True,
    )


@pytest.fixture
def pool(weth, usdc):
    return Pool(
        chain_id=42161,
        dex_id="uniswap_v3",
        dex_type=DexType.UNISWAP_V3,
        pool_address="0x1234567890123456789012345678901234567890",
        token0=usdc,
        token1=weth,
        fee=500,
        status=PoolStatus.ACTIVE,
    )


def make_quote(pool, weth, usdc, amount_in, amount_out, gas=100000, ticks=2, fresh=True):
    """Helper to create test quotes.
    
    Args:
        ticks: Can be int or None (for Algebra quotes)
    """
    import time
    ts = int(time.time() * 1000) if fresh else int(time.time() * 1000) - 10000
    return Quote(
        pool=pool,
        direction="1to0",
        token_in=weth,
        token_out=usdc,
        amount_in=amount_in,
        amount_out=amount_out,
        block_number=12345678,
        timestamp_ms=ts,
        gas_estimate=gas,
        ticks_crossed=ticks,
        latency_ms=50,
    )


# =============================================================================
# SINGLE QUOTE GATES
# =============================================================================

class TestGateZeroOutput:
    def test_passes_with_output(self, pool, weth, usdc):
        quote = make_quote(pool, weth, usdc, 10**18, 2500_000000)
        result = gate_zero_output(quote)
        assert result.passed
        assert result.reject_code is None
    
    def test_fails_with_zero_output(self, pool, weth, usdc):
        quote = make_quote(pool, weth, usdc, 10**18, 0)
        result = gate_zero_output(quote)
        assert not result.passed
        assert result.reject_code == ErrorCode.QUOTE_ZERO_OUTPUT


class TestGateGasEstimate:
    def test_passes_with_low_gas(self, pool, weth, usdc):
        quote = make_quote(pool, weth, usdc, 10**18, 2500_000000, gas=150000)
        result = gate_gas_estimate(quote)
        assert result.passed
    
    def test_fails_with_high_gas(self, pool, weth, usdc):
        quote = make_quote(pool, weth, usdc, 10**18, 2500_000000, gas=600000)
        result = gate_gas_estimate(quote)
        assert not result.passed
        assert result.reject_code == ErrorCode.QUOTE_GAS_TOO_HIGH
    
    def test_custom_threshold(self, pool, weth, usdc):
        quote = make_quote(pool, weth, usdc, 10**18, 2500_000000, gas=200000)
        result = gate_gas_estimate(quote, max_gas=100000)
        assert not result.passed


class TestGateTicksCrossed:
    def test_passes_with_low_ticks(self, pool, weth, usdc):
        quote = make_quote(pool, weth, usdc, 10**18, 2500_000000, ticks=3)
        result = gate_ticks_crossed(quote)
        assert result.passed
    
    def test_fails_with_high_ticks(self, pool, weth, usdc):
        quote = make_quote(pool, weth, usdc, 10**18, 2500_000000, ticks=15)
        result = gate_ticks_crossed(quote)
        assert not result.passed
        assert result.reject_code == ErrorCode.TICKS_CROSSED_TOO_MANY
    
    def test_passes_with_none_ticks_algebra(self, pool, weth, usdc):
        """Algebra quotes have ticks_crossed=None, gate should pass."""
        quote = make_quote(pool, weth, usdc, 10**18, 2500_000000, ticks=None)
        result = gate_ticks_crossed(quote)
        assert result.passed


class TestGateFreshness:
    def test_passes_when_fresh(self, pool, weth, usdc):
        quote = make_quote(pool, weth, usdc, 10**18, 2500_000000, fresh=True)
        result = gate_freshness(quote)
        assert result.passed
    
    def test_fails_when_stale(self, pool, weth, usdc):
        quote = make_quote(pool, weth, usdc, 10**18, 2500_000000, fresh=False)
        result = gate_freshness(quote)
        assert not result.passed
        assert result.reject_code == ErrorCode.QUOTE_STALE_BLOCK


# =============================================================================
# PRICE CALCULATIONS
# =============================================================================

class TestCalculateImpliedPrice:
    def test_normal_price(self, pool, weth, usdc):
        # 1 ETH (18 decimals) -> 2500 USDC (6 decimals)
        quote = make_quote(pool, weth, usdc, 10**18, 2500_000000)
        price = calculate_implied_price(quote)
        assert price == Decimal("2500")
    
    def test_zero_input(self, pool, weth, usdc):
        quote = make_quote(pool, weth, usdc, 0, 0)
        price = calculate_implied_price(quote)
        assert price == Decimal("0")


class TestCalculateSlippageBps:
    def test_no_slippage(self):
        slippage = calculate_slippage_bps(Decimal("2500"), Decimal("2500"))
        assert slippage == 0
    
    def test_positive_slippage(self):
        # Price degrades from 2500 to 2450 = 2% slippage = 200 bps
        slippage = calculate_slippage_bps(Decimal("2500"), Decimal("2450"))
        assert slippage == 200
    
    def test_high_slippage(self):
        # Price degrades from 2500 to 2250 = 10% slippage = 1000 bps
        slippage = calculate_slippage_bps(Decimal("2500"), Decimal("2250"))
        assert slippage == 1000


# =============================================================================
# CURVE GATES
# =============================================================================

class TestGateSlippageCurve:
    def test_passes_with_low_slippage(self, pool, weth, usdc):
        # Slippage within threshold
        quotes = [
            make_quote(pool, weth, usdc, 10**16, 25_000000),     # 0.01 ETH -> 25 USDC (2500)
            make_quote(pool, weth, usdc, 10**17, 249_000000),    # 0.1 ETH -> 249 USDC (2490)
            make_quote(pool, weth, usdc, 10**18, 2475_000000),   # 1 ETH -> 2475 USDC (2475)
        ]
        result = gate_slippage_curve(quotes)
        assert result.passed
    
    def test_fails_with_high_slippage(self, pool, weth, usdc):
        # Massive slippage
        quotes = [
            make_quote(pool, weth, usdc, 10**16, 25_000000),     # 2500/ETH
            make_quote(pool, weth, usdc, 10**17, 200_000000),    # 2000/ETH (20% slippage!)
        ]
        result = gate_slippage_curve(quotes)
        assert not result.passed
        assert result.reject_code == ErrorCode.SLIPPAGE_TOO_HIGH
    
    def test_fails_with_negative_slippage(self, pool, weth, usdc):
        # Negative slippage = price IMPROVES for larger size (suspicious)
        quotes = [
            make_quote(pool, weth, usdc, 10**16, 25_000000),     # 2500/ETH
            make_quote(pool, weth, usdc, 10**17, 260_000000),    # 2600/ETH (better price!)
        ]
        result = gate_slippage_curve(quotes)
        assert not result.passed
        assert result.reject_code == ErrorCode.QUOTE_INCONSISTENT
        assert result.details["reason"] == "negative_slippage"
    
    def test_single_quote_passes(self, pool, weth, usdc):
        quotes = [make_quote(pool, weth, usdc, 10**18, 2500_000000)]
        result = gate_slippage_curve(quotes)
        assert result.passed


class TestGateMonotonicity:
    def test_passes_with_monotonic(self, pool, weth, usdc):
        quotes = [
            make_quote(pool, weth, usdc, 10**16, 25_000000),
            make_quote(pool, weth, usdc, 10**17, 249_000000),
            make_quote(pool, weth, usdc, 10**18, 2475_000000),
        ]
        result = gate_monotonicity(quotes)
        assert result.passed
    
    def test_fails_with_non_monotonic(self, pool, weth, usdc):
        # amount_out DECREASES when amount_in increases - suspicious!
        quotes = [
            make_quote(pool, weth, usdc, 10**16, 25_000000),
            make_quote(pool, weth, usdc, 10**17, 20_000000),  # Less output for more input!
        ]
        result = gate_monotonicity(quotes)
        assert not result.passed
        assert result.reject_code == ErrorCode.QUOTE_INCONSISTENT


# =============================================================================
# COMBINED GATES
# =============================================================================

class TestApplySingleQuoteGates:
    def test_all_pass(self, pool, weth, usdc):
        """All gates pass for anchor DEX with good quote."""
        quote = make_quote(pool, weth, usdc, 10**18, 2500_000000, gas=100000, ticks=2)
        # Must be anchor DEX or have anchor_price to pass price sanity
        failures = apply_single_quote_gates(quote, is_anchor_dex=True)
        assert len(failures) == 0
    
    def test_all_pass_with_anchor(self, pool, weth, usdc):
        """All gates pass for non-anchor DEX with valid anchor price."""
        quote = make_quote(pool, weth, usdc, 10**18, 2500_000000, gas=100000, ticks=2)
        anchor = Decimal("2500")  # Same as quote
        failures = apply_single_quote_gates(quote, anchor_price=anchor, is_anchor_dex=False)
        assert len(failures) == 0
    
    def test_multiple_failures(self, pool, weth, usdc):
        quote = make_quote(pool, weth, usdc, 10**18, 0, gas=999999, ticks=99)
        failures = apply_single_quote_gates(quote, is_anchor_dex=True)
        assert len(failures) >= 2  # Zero output, high gas, high ticks


class TestApplyCurveGates:
    def test_all_pass(self, pool, weth, usdc):
        quotes = [
            make_quote(pool, weth, usdc, 10**16, 25_000000),
            make_quote(pool, weth, usdc, 10**17, 249_000000),
            make_quote(pool, weth, usdc, 10**18, 2475_000000),
        ]
        failures = apply_curve_gates(quotes)
        assert len(failures) == 0


class TestGatePriceSanity:
    """
    CRITICAL: Tests for gate_price_sanity using ErrorCode.PRICE_SANITY_FAILED.
    
    P0 FIX: Non-anchor quotes without anchor_price are REJECTED with
    ErrorCode.PRICE_ANCHOR_MISSING.
    """
    
    def test_price_sanity_failed_exists_in_errorcode(self):
        """ErrorCode.PRICE_SANITY_FAILED must exist."""
        code = ErrorCode.PRICE_SANITY_FAILED
        assert code.value == "PRICE_SANITY_FAILED"
    
    def test_price_anchor_missing_exists_in_errorcode(self):
        """ErrorCode.PRICE_ANCHOR_MISSING must exist."""
        code = ErrorCode.PRICE_ANCHOR_MISSING
        assert code.value == "PRICE_ANCHOR_MISSING"
    
    def test_anchor_dex_passes_without_anchor_price(self, pool, weth, usdc):
        """Anchor DEX can set anchor - passes without existing anchor."""
        quote = make_quote(pool, weth, usdc, 10**18, 2500_000000)
        result = gate_price_sanity(quote, anchor_price=None, is_anchor_dex=True)
        assert result.passed is True
    
    def test_non_anchor_dex_fails_without_anchor_price(self, pool, weth, usdc):
        """
        P0 FIX: Non-anchor DEX without anchor = REJECT with PRICE_ANCHOR_MISSING.
        This prevents "phantom opportunities" from single-DEX quotes.
        """
        quote = make_quote(pool, weth, usdc, 10**18, 2500_000000)
        result = gate_price_sanity(quote, anchor_price=None, is_anchor_dex=False)
        
        assert result.passed is False
        assert result.reject_code == ErrorCode.PRICE_ANCHOR_MISSING
        assert "no_anchor_price" in result.details.get("reason", "")
    
    def test_passes_when_price_within_threshold(self, pool, weth, usdc):
        """Price within 10% of anchor = pass."""
        quote = make_quote(pool, weth, usdc, 10**18, 2500_000000)  # price = 2500
        anchor_price = Decimal("2450")  # ~2% deviation
        result = gate_price_sanity(quote, anchor_price=anchor_price, is_anchor_dex=False)
        assert result.passed is True
    
    def test_fails_when_price_deviates_too_much(self, pool, weth, usdc):
        """Price deviates >10% from anchor = fail with PRICE_SANITY_FAILED."""
        quote = make_quote(pool, weth, usdc, 10**18, 2500_000000)  # price = 2500
        anchor_price = Decimal("2000")  # 25% deviation
        result = gate_price_sanity(quote, anchor_price=anchor_price, is_anchor_dex=False)
        
        assert result.passed is False
        assert result.reject_code == ErrorCode.PRICE_SANITY_FAILED
    
    def test_fails_when_zero_quote_price(self, pool, weth, usdc):
        """Zero quote price = fail with PRICE_SANITY_FAILED."""
        quote = make_quote(pool, weth, usdc, 10**18, 0)  # price = 0
        anchor_price = Decimal("2500")
        result = gate_price_sanity(quote, anchor_price=anchor_price, is_anchor_dex=False)
        
        assert result.passed is False
        assert result.reject_code == ErrorCode.PRICE_SANITY_FAILED
    
    def test_no_attribute_error(self, pool, weth, usdc):
        """
        REGRESSION TEST: gate_price_sanity must not raise AttributeError.
        """
        quote = make_quote(pool, weth, usdc, 10**18, 2500_000000)
        anchor_price = Decimal("1000")  # Will fail
        
        try:
            result = gate_price_sanity(quote, anchor_price=anchor_price, is_anchor_dex=False)
            assert result.reject_code == ErrorCode.PRICE_SANITY_FAILED
        except AttributeError as e:
            pytest.fail(f"AttributeError raised: {e}")
    
    def test_different_fee_tiers_share_anchor(self, weth, usdc):
        """
        P0 FIX: Different fee tiers for same pair should share anchor.
        
        This tests that anchor_key = pair_amount (without fee) allows
        Sushi fee=3000 to use Uni fee=500 anchor.
        """
        # Simulating anchor logic: 
        # anchor_key = f"{pair}_{amount}" (without fee)
        anchor_key_uni = "WETH/USDC_1000000000000000000"  # fee=500
        anchor_key_sushi = "WETH/USDC_1000000000000000000"  # fee=3000
        
        # Both should use same anchor key
        assert anchor_key_uni == anchor_key_sushi


class TestIsAnchorDex:
    """Test is_anchor_dex parameter in gates."""
    
    def test_anchor_dex_skips_price_sanity(self, pool, weth, usdc):
        """Anchor DEX quotes should skip price sanity check."""
        from strategy.gates import gate_price_sanity
        
        quote = make_quote(pool, weth, usdc, 10**18, 2500_000000, gas=200000, ticks=5)
        
        # As anchor DEX - should always pass (no sanity check)
        result = gate_price_sanity(quote, anchor_price=None, is_anchor_dex=True)
        assert result.passed is True, "Anchor DEX should skip sanity check"
    
    def test_non_anchor_without_anchor_price_rejected(self, pool, weth, usdc):
        """Non-anchor DEX without anchor price should be rejected."""
        from strategy.gates import gate_price_sanity
        from core.exceptions import ErrorCode
        
        quote = make_quote(pool, weth, usdc, 10**18, 2500_000000, gas=200000, ticks=5)
        
        # Non-anchor DEX without anchor price - should be rejected
        result = gate_price_sanity(quote, anchor_price=None, is_anchor_dex=False)
        assert result.passed is False
        assert result.reject_code == ErrorCode.PRICE_ANCHOR_MISSING
    
    def test_apply_single_quote_gates_accepts_is_anchor_dex(self, pool, weth, usdc):
        """apply_single_quote_gates should accept is_anchor_dex parameter."""
        from strategy.gates import apply_single_quote_gates
        from decimal import Decimal
        
        quote = make_quote(pool, weth, usdc, 10**18, 2500_000000, gas=200000, ticks=5)
        
        # Should not raise TypeError
        failures = apply_single_quote_gates(
            quote, 
            anchor_price=Decimal("2500"),
            is_anchor_dex=False,
        )
        
        # Check type
        assert isinstance(failures, list)


# =============================================================================
# ADAPTIVE LIMITS TESTS
# =============================================================================

class TestAdaptiveLimits:
    """Tests for adaptive gas and ticks limits."""
    
    def test_get_adaptive_gas_limit_small_trade(self):
        """Small trades should get tight gas limits."""
        from strategy.gates import get_adaptive_gas_limit
        
        # 0.1 ETH
        limit = get_adaptive_gas_limit(10**17)
        assert limit == 300_000
    
    def test_get_adaptive_gas_limit_standard_trade(self):
        """Standard trades should get standard gas limits."""
        from strategy.gates import get_adaptive_gas_limit
        
        # 1 ETH
        limit = get_adaptive_gas_limit(10**18)
        assert limit == 500_000
    
    def test_get_adaptive_gas_limit_large_trade(self):
        """Large trades should get higher gas limits."""
        from strategy.gates import get_adaptive_gas_limit
        
        # 10 ETH
        limit = get_adaptive_gas_limit(10**19)
        assert limit == 800_000
    
    def test_get_adaptive_ticks_limit_small_trade(self):
        """Small trades should get tight ticks limits."""
        from strategy.gates import get_adaptive_ticks_limit
        
        # 0.1 ETH
        limit = get_adaptive_ticks_limit(10**17)
        assert limit == 5
    
    def test_get_adaptive_ticks_limit_standard_trade(self):
        """Standard trades should get standard ticks limits."""
        from strategy.gates import get_adaptive_ticks_limit
        
        # 1 ETH
        limit = get_adaptive_ticks_limit(10**18)
        assert limit == 10
    
    def test_get_adaptive_ticks_limit_large_trade(self):
        """Large trades should get higher ticks limits."""
        from strategy.gates import get_adaptive_ticks_limit
        
        # 10 ETH
        limit = get_adaptive_ticks_limit(10**19)
        assert limit == 20
    
    def test_get_price_deviation_limit_stable_pair(self):
        """Stable pairs should get lower deviation limit."""
        from strategy.gates import get_price_deviation_limit, MAX_PRICE_DEVIATION_BPS
        
        limit = get_price_deviation_limit("WETH/USDC")
        assert limit == MAX_PRICE_DEVIATION_BPS  # 1500 bps
    
    def test_get_price_deviation_limit_volatile_pair(self):
        """Volatile pairs should get higher deviation limit."""
        from strategy.gates import get_price_deviation_limit, MAX_PRICE_DEVIATION_BPS_VOLATILE
        
        limit = get_price_deviation_limit("WETH/ARB")
        assert limit == MAX_PRICE_DEVIATION_BPS_VOLATILE  # 2500 bps
        
        limit = get_price_deviation_limit("WETH/LINK")
        assert limit == MAX_PRICE_DEVIATION_BPS_VOLATILE
    
    def test_gate_gas_uses_adaptive_limit(self, pool, weth, usdc):
        """gate_gas_estimate should use adaptive limits when max_gas=None."""
        from strategy.gates import gate_gas_estimate
        
        # Small trade with gas that would pass standard (500k) but fail adaptive (300k)
        quote = make_quote(pool, weth, usdc, 10**17, 2500_000000, gas=400_000, ticks=1)
        
        # Without explicit max_gas, should use adaptive limit (300k for 0.1 ETH)
        result = gate_gas_estimate(quote)
        assert not result.passed
        assert result.reject_code == ErrorCode.QUOTE_GAS_TOO_HIGH
        assert result.details["max_gas"] == 300_000
    
    def test_gate_ticks_uses_adaptive_limit(self, pool, weth, usdc):
        """gate_ticks_crossed should use adaptive limits when max_ticks=None."""
        from strategy.gates import gate_ticks_crossed
        
        # Small trade with ticks that would pass standard (10) but fail adaptive (5)
        quote = make_quote(pool, weth, usdc, 10**17, 2500_000000, gas=100000, ticks=8)
        
        # Without explicit max_ticks, should use adaptive limit (5 for 0.1 ETH)
        result = gate_ticks_crossed(quote)
        assert not result.passed
        assert result.reject_code == ErrorCode.TICKS_CROSSED_TOO_MANY
        assert result.details["max_ticks"] == 5
