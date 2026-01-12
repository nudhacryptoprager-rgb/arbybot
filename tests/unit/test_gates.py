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
        quote = make_quote(pool, weth, usdc, 10**18, 2500_000000, gas=100000, ticks=2)
        failures = apply_single_quote_gates(quote)
        assert len(failures) == 0
    
    def test_multiple_failures(self, pool, weth, usdc):
        quote = make_quote(pool, weth, usdc, 10**18, 0, gas=999999, ticks=99)
        failures = apply_single_quote_gates(quote)
        assert len(failures) >= 3  # Zero output, high gas, high ticks


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
    
    These tests ensure PRICE_SANITY_FAILED exists in ErrorCode enum and
    does not cause AttributeError.
    """
    
    def test_price_sanity_failed_exists_in_errorcode(self):
        """ErrorCode.PRICE_SANITY_FAILED must exist."""
        # This will raise AttributeError if missing
        code = ErrorCode.PRICE_SANITY_FAILED
        assert code.value == "PRICE_SANITY_FAILED"
    
    def test_passes_when_no_anchor(self, pool, weth, usdc):
        """No anchor price = pass (first quote sets anchor)."""
        quote = make_quote(pool, weth, usdc, 10**18, 2500_000000)
        result = gate_price_sanity(quote, anchor_price=None)
        assert result.passed is True
    
    def test_passes_when_price_within_threshold(self, pool, weth, usdc):
        """Price within 10% of anchor = pass."""
        quote = make_quote(pool, weth, usdc, 10**18, 2500_000000)  # price = 2500
        anchor_price = Decimal("2450")  # ~2% deviation
        result = gate_price_sanity(quote, anchor_price=anchor_price)
        assert result.passed is True
    
    def test_fails_when_price_deviates_too_much(self, pool, weth, usdc):
        """Price deviates >10% from anchor = fail with PRICE_SANITY_FAILED."""
        quote = make_quote(pool, weth, usdc, 10**18, 2500_000000)  # price = 2500
        anchor_price = Decimal("2000")  # 25% deviation
        result = gate_price_sanity(quote, anchor_price=anchor_price)
        
        assert result.passed is False
        assert result.reject_code == ErrorCode.PRICE_SANITY_FAILED
    
    def test_fails_when_zero_quote_price(self, pool, weth, usdc):
        """Zero quote price = fail with PRICE_SANITY_FAILED."""
        quote = make_quote(pool, weth, usdc, 10**18, 0)  # price = 0
        anchor_price = Decimal("2500")
        result = gate_price_sanity(quote, anchor_price=anchor_price)
        
        assert result.passed is False
        assert result.reject_code == ErrorCode.PRICE_SANITY_FAILED
    
    def test_no_attribute_error(self, pool, weth, usdc):
        """
        REGRESSION TEST: gate_price_sanity must not raise AttributeError
        when accessing ErrorCode.PRICE_SANITY_FAILED.
        """
        quote = make_quote(pool, weth, usdc, 10**18, 2500_000000)
        anchor_price = Decimal("1000")  # Will fail
        
        # This should NOT raise AttributeError
        try:
            result = gate_price_sanity(quote, anchor_price=anchor_price)
            assert result.reject_code == ErrorCode.PRICE_SANITY_FAILED
        except AttributeError as e:
            pytest.fail(f"AttributeError raised: {e}")
