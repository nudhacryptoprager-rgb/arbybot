"""Unit tests for ``execution/slippage_guard.py`` (Phase 2 paper)."""
from __future__ import annotations

import pytest

from execution.slippage_guard import (
    DEFAULT_CIRCUIT_BREAKER_X,
    DEFAULT_MAX_SLIPPAGE_BPS,
    DEFAULT_SAFETY_BUFFER,
    SlippageGuard,
    SlippageGuardResult,
    SlippageGuardVerdict,
    predict_slippage_bps,
)

POOL = "0x" + "d" * 40


class TestPredictSlippage:
    def test_zero_amount_zero_slippage(self):
        assert predict_slippage_bps(reserve_in=1_000, reserve_out=1_000, amount_in=0) == 0.0

    def test_empty_reserves_infinite(self):
        assert predict_slippage_bps(reserve_in=0, reserve_out=1_000, amount_in=1) == float("inf")
        assert predict_slippage_bps(reserve_in=1_000, reserve_out=0, amount_in=1) == float("inf")

    def test_small_trade_low_slippage(self):
        bps = predict_slippage_bps(
            reserve_in=1_000_000, reserve_out=1_000_000, amount_in=100, fee_bps=30
        )
        # Small trade against deep pool → slippage near fee level.
        assert 0 <= bps < 50

    def test_large_trade_high_slippage(self):
        bps = predict_slippage_bps(
            reserve_in=1_000, reserve_out=1_000, amount_in=500, fee_bps=30
        )
        # 50 % of reserves → large slippage.
        assert bps > 1_000

    def test_higher_fee_higher_slippage(self):
        lo = predict_slippage_bps(reserve_in=10_000, reserve_out=10_000, amount_in=100, fee_bps=5)
        hi = predict_slippage_bps(reserve_in=10_000, reserve_out=10_000, amount_in=100, fee_bps=100)
        assert hi > lo


class TestGuardConstruction:
    def test_defaults(self):
        g = SlippageGuard()
        assert g.max_slippage_bps == DEFAULT_MAX_SLIPPAGE_BPS
        assert g.safety_buffer == DEFAULT_SAFETY_BUFFER
        assert g.circuit_breaker_x == DEFAULT_CIRCUIT_BREAKER_X

    def test_invalid_max(self):
        with pytest.raises(ValueError):
            SlippageGuard(max_slippage_bps=0)

    def test_invalid_buffer(self):
        with pytest.raises(ValueError):
            SlippageGuard(safety_buffer=0.5)

    def test_invalid_circuit(self):
        with pytest.raises(ValueError):
            SlippageGuard(circuit_breaker_x=0.5)


class TestGuardCheck:
    def test_allow_small_trade(self):
        g = SlippageGuard()
        r = g.check(pool=POOL, reserve_in=1_000_000, reserve_out=1_000_000, amount_in=100)
        assert r.verdict == SlippageGuardVerdict.ALLOW
        assert r.reason is None

    def test_reject_large_trade(self):
        g = SlippageGuard(max_slippage_bps=100, safety_buffer=2.0)
        r = g.check(pool=POOL, reserve_in=1_000, reserve_out=1_000, amount_in=500)
        assert r.verdict == SlippageGuardVerdict.REJECT
        assert r.reason == "PREDICTED_OVER_LIMIT"

    def test_to_dict_serialises(self):
        r = SlippageGuard().check(
            pool=POOL, reserve_in=1_000_000, reserve_out=1_000_000, amount_in=100
        )
        out = r.to_dict()
        assert "verdict" in out and "predicted_bps" in out

    def test_blacklist_reject(self):
        g = SlippageGuard()
        g._blacklist.add(POOL.lower())  # noqa: SLF001
        r = g.check(pool=POOL, reserve_in=1_000_000, reserve_out=1_000_000, amount_in=100)
        assert r.verdict == SlippageGuardVerdict.REJECT
        assert r.reason == "POOL_BLACKLISTED"
        assert r.pool_blacklisted is True


class TestCircuitBreaker:
    def test_observe_below_threshold_no_blacklist(self):
        g = SlippageGuard(circuit_breaker_x=3.0)
        flipped = g.observe(pool=POOL, predicted_bps=10, realized_bps=20)
        assert flipped is False
        assert g.is_blacklisted(POOL) is False

    def test_observe_over_threshold_blacklists(self):
        g = SlippageGuard(circuit_breaker_x=3.0)
        flipped = g.observe(pool=POOL, predicted_bps=10, realized_bps=40)
        assert flipped is True
        assert g.is_blacklisted(POOL) is True
        assert POOL.lower() in g.blacklist()

    def test_observe_invalid_inputs_noop(self):
        g = SlippageGuard()
        assert g.observe(pool=POOL, predicted_bps=0, realized_bps=10) is False
        assert g.observe(pool=POOL, predicted_bps=10, realized_bps=0) is False
        assert g.is_blacklisted(POOL) is False
