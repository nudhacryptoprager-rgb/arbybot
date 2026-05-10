"""E1.80 Iter 7 — tests for Aave V3 flash loan adapter skeleton."""
from __future__ import annotations

import pytest

from execution.flash_loan.aave_adapter import (
    AAVE_V3_BASE_POOL,
    AAVE_V3_FLASH_PREMIUM_BPS,
    build_flash_loan_simple_call,
    estimate_flash_loan_profit,
    min_profitable_spread_bps,
)


def test_default_premium_is_9_bps():
    assert AAVE_V3_FLASH_PREMIUM_BPS == 9.0


def test_pool_address_is_base_mainnet():
    assert AAVE_V3_BASE_POOL.lower() == "0xa238dd80c259a72e81d7e4664a9801593f98d1c5"


def test_profit_clears_when_spread_above_premium_plus_gas():
    # 25 bps spread, $1000 size, $0.50 gas
    # gross = $2.50, premium = $0.90, net = $2.50 - $0.90 - $0.50 = $1.10
    econ = estimate_flash_loan_profit(
        spread_bps=25.0, size_usd=1000.0, gas_cost_usd=0.50
    )
    assert econ.gross_profit_usd == pytest.approx(2.50)
    assert econ.flash_premium_usd == pytest.approx(0.90)
    assert econ.net_profit_usd == pytest.approx(1.10)
    assert econ.profitable is True


def test_profit_rejected_when_below_breakeven():
    # 10 bps spread, $1000 size, $0.50 gas
    # gross = $1.00, premium = $0.90, net = -$0.40
    econ = estimate_flash_loan_profit(
        spread_bps=10.0, size_usd=1000.0, gas_cost_usd=0.50
    )
    assert econ.profitable is False
    assert econ.net_profit_usd < 0


def test_min_profitable_spread_includes_safety_margin():
    # gas $0.50 / $1000 = 5 bps + 9 bps premium = 14 bps + 1 bps margin = 15 bps
    threshold = min_profitable_spread_bps(size_usd=1000.0, gas_cost_usd=0.50)
    assert threshold == pytest.approx(15.0)


def test_min_profitable_spread_returns_none_for_zero_size():
    assert min_profitable_spread_bps(size_usd=0.0, gas_cost_usd=1.0) is None


def test_zero_size_returns_negative_gas_cost():
    econ = estimate_flash_loan_profit(spread_bps=999.0, size_usd=0.0, gas_cost_usd=0.5)
    assert econ.profitable is False
    assert econ.net_profit_usd == pytest.approx(-0.5)


def test_calldata_shape_minimal():
    call = build_flash_loan_simple_call(
        receiver="0xRECEIVER",
        asset="0xUSDC",
        amount_wei=1_000_000_000,
    )
    assert call["to"] == AAVE_V3_BASE_POOL
    assert call["selector"] == "0x42b0b77c"
    assert call["args"]["receiver"] == "0xRECEIVER"
    assert call["args"]["asset"] == "0xUSDC"
    assert call["args"]["amount"] == 1_000_000_000
    assert call["args"]["params"] == "0x"
    assert call["args"]["referralCode"] == 0


def test_calldata_rejects_zero_amount():
    with pytest.raises(ValueError):
        build_flash_loan_simple_call(receiver="0xR", asset="0xA", amount_wei=0)


def test_calldata_rejects_invalid_referral():
    with pytest.raises(ValueError):
        build_flash_loan_simple_call(
            receiver="0xR", asset="0xA", amount_wei=1, referral_code=70_000
        )


def test_calldata_rejects_empty_addresses():
    with pytest.raises(ValueError):
        build_flash_loan_simple_call(receiver="", asset="0xA", amount_wei=1)
    with pytest.raises(ValueError):
        build_flash_loan_simple_call(receiver="0xR", asset="", amount_wei=1)
