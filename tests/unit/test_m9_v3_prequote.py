"""Unit tests for v3_prequote.py (Step 9)."""
from __future__ import annotations

import math
import time

import pytest

from m9.graph_arb.pool_state_cache import PoolState
from m9.graph_arb.v3_prequote import (
    _price_ratio_for_edge,
    estimate_cycle_gross_bps,
    cycle_has_empty_pool,
    should_skip_cycle,
    prequote_priority_bonus,
    _V3_COMPATIBLE_ADAPTERS,
    _Q96,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pool_state(addr, sqrt_price_x96, liquidity=1_000_000, tick=0):
    return PoolState(
        pool_addr=addr.lower(),
        sqrt_price_x96=sqrt_price_x96,
        tick=tick,
        liquidity=liquidity,
        block_number=100,
        fetched_at_mono=time.monotonic(),
    )


def _make_edge(token_in, token_out, pool, fee_bps=30, adapter="uniswap_v3"):
    """Minimal edge-like object for testing."""
    from types import SimpleNamespace
    return SimpleNamespace(
        token_in_addr=token_in,
        token_out_addr=token_out,
        pool_address=pool,
        fee_bps=fee_bps,
        adapter_type=adapter,
    )


def _make_cycle(*edges):
    from types import SimpleNamespace
    return SimpleNamespace(edges=edges)


# ---------------------------------------------------------------------------
# V3 price ratio for a single edge
# ---------------------------------------------------------------------------

class TestPriceRatioForEdge:
    def test_zero_for_one_basic(self):
        # token_in < token_out → zero_for_one, price = sqrtPx96^2/2^192
        sqrt_px96 = int(math.sqrt(2.0) * _Q96)
        edge = _make_edge("0x0001", "0x0002", "0xpool")
        ratio = _price_ratio_for_edge(edge, sqrt_px96)
        assert ratio is not None
        assert abs(ratio - 2.0 * (1 - 30/10000)) < 0.01

    def test_one_for_zero_basic(self):
        # token_in > token_out → one_for_zero, price = 1/P
        sqrt_px96 = int(math.sqrt(2.0) * _Q96)
        edge = _make_edge("0x0002", "0x0001", "0xpool")
        ratio = _price_ratio_for_edge(edge, sqrt_px96)
        assert ratio is not None
        assert abs(ratio - (1 / 2.0) * (1 - 30/10000)) < 0.01

    def test_zero_sqrt_price_returns_none(self):
        edge = _make_edge("0x0001", "0x0002", "0xpool")
        assert _price_ratio_for_edge(edge, 0) is None

    def test_non_v3_adapter_returns_none(self):
        edge = _make_edge("0x0001", "0x0002", "0xpool", adapter="uniswap_v2")
        sqrt_px96 = int(1.5 * _Q96)
        assert _price_ratio_for_edge(edge, sqrt_px96) is None

    def test_fee_applied(self):
        # With fee_bps=100 (1%), ratio should be 0.99x of fee-free
        sqrt_px96 = _Q96  # price_raw = 1.0
        edge_no_fee = _make_edge("0x0001", "0x0002", "0xpool", fee_bps=0)
        edge_fee = _make_edge("0x0001", "0x0002", "0xpool", fee_bps=100)
        r_no_fee = _price_ratio_for_edge(edge_no_fee, sqrt_px96)
        r_fee = _price_ratio_for_edge(edge_fee, sqrt_px96)
        assert abs(r_no_fee - 1.0) < 1e-9
        assert abs(r_fee - 0.99) < 1e-9

    def test_all_v3_adapters_supported(self):
        sqrt_px96 = _Q96
        for adapter in _V3_COMPATIBLE_ADAPTERS:
            edge = _make_edge("0x0001", "0x0002", "0xpool", adapter=adapter)
            ratio = _price_ratio_for_edge(edge, sqrt_px96)
            assert ratio is not None, f"Adapter {adapter} should return a ratio"


# ---------------------------------------------------------------------------
# Cycle gross bps estimation
# ---------------------------------------------------------------------------

class TestEstimateCycleGrossBps:
    def _balanced_cycle(self):
        """2-hop cycle where both legs have price=1 (perfectly balanced)."""
        # hop A→B: zero_for_one, price=1, fee=0
        # hop B→A: one_for_zero, price=1/1=1, fee=0
        # product = 1.0, gross_bps = 0
        pool1 = "0xpool1"
        pool2 = "0xpool2"
        edges = [
            _make_edge("0x000a", "0x000b", pool1, fee_bps=0),
            _make_edge("0x000b", "0x000a", pool2, fee_bps=0),
        ]
        cycle = _make_cycle(*edges)
        pool_states = {
            pool1: _pool_state(pool1, _Q96),  # price=1
            pool2: _pool_state(pool2, _Q96),  # price=1
        }
        return cycle, pool_states

    def test_balanced_cycle_near_zero(self):
        cycle, pool_states = self._balanced_cycle()
        gross = estimate_cycle_gross_bps(cycle, pool_states)
        assert gross is not None
        assert abs(gross) < 1.0  # near zero for balanced market

    def test_missing_pool_returns_none(self):
        pool1 = "0xpool1"
        edge = _make_edge("0x0001", "0x0002", pool1)
        cycle = _make_cycle(edge)
        assert estimate_cycle_gross_bps(cycle, {}) is None

    def test_positive_spread_detected(self):
        # Artificial: hop A→B at price 1.01, hop B→A at price 1.01/1 = 1.01
        # gross_ratio ≈ 1.01 * 1.01 - 1 ≈ 2.01%
        pool1, pool2 = "0xpool1", "0xpool2"
        # For zero_for_one at price 1.01: sqrt_price = sqrt(1.01) * Q96
        sqrt_px96_ab = int(math.sqrt(1.05) * _Q96)  # price = 1.05 A→B direction
        sqrt_px96_ba = int(math.sqrt(1 / 1.05) * _Q96)  # price = 1/1.05 for the pool, B→A goes one_for_zero → gets 1.05
        edges = [
            _make_edge("0x000a", "0x000b", pool1, fee_bps=0),  # zero_for_one, price=1.05
            _make_edge("0x000b", "0x000a", pool2, fee_bps=0),  # one_for_zero, price=1/price_raw=1.05
        ]
        cycle = _make_cycle(*edges)
        pool_states = {
            pool1: _pool_state(pool1, sqrt_px96_ab),
            pool2: _pool_state(pool2, sqrt_px96_ba),
        }
        gross = estimate_cycle_gross_bps(cycle, pool_states)
        assert gross is not None
        assert gross > 0  # should show positive spread

    def test_very_negative_spread(self):
        # Use different prices in pool1 and pool2 to get a genuinely negative cycle.
        # hop1: A→B zero_for_one: ratio = price_raw(pool1) = 0.1
        # hop2: B→A one_for_zero: ratio = 1/price_raw(pool2) = 1/10 = 0.1
        # product = 0.1 * 0.1 = 0.01 → gross_bps = (0.01-1)*10000 = -9900
        pool1, pool2 = "0xpool1", "0xpool2"
        sqrt_px96_p1 = int(math.sqrt(0.1) * _Q96)  # pool1 price_raw = 0.1
        sqrt_px96_p2 = int(math.sqrt(10.0) * _Q96)  # pool2 one_for_zero: 1/10 = 0.1
        edges = [
            _make_edge("0x000a", "0x000b", pool1, fee_bps=0),
            _make_edge("0x000b", "0x000a", pool2, fee_bps=0),
        ]
        cycle = _make_cycle(*edges)
        pool_states = {
            pool1: _pool_state(pool1, sqrt_px96_p1),
            pool2: _pool_state(pool2, sqrt_px96_p2),
        }
        gross = estimate_cycle_gross_bps(cycle, pool_states)
        assert gross is not None
        assert gross < -1000  # very negative


# ---------------------------------------------------------------------------
# Empty pool detection
# ---------------------------------------------------------------------------

class TestCycleHasEmptyPool:
    def test_empty_liquidity_detected(self):
        pool = "0xpool1"
        edge = _make_edge("0x0001", "0x0002", pool)
        cycle = _make_cycle(edge)
        pool_states = {pool: _pool_state(pool, _Q96, liquidity=0)}
        assert cycle_has_empty_pool(cycle, pool_states)

    def test_not_empty(self):
        pool = "0xpool1"
        edge = _make_edge("0x0001", "0x0002", pool)
        cycle = _make_cycle(edge)
        pool_states = {pool: _pool_state(pool, _Q96, liquidity=1000)}
        assert not cycle_has_empty_pool(cycle, pool_states)

    def test_missing_pool_counts_as_empty(self):
        pool = "0xpool1"
        edge = _make_edge("0x0001", "0x0002", pool)
        cycle = _make_cycle(edge)
        assert cycle_has_empty_pool(cycle, {})


# ---------------------------------------------------------------------------
# should_skip_cycle
# ---------------------------------------------------------------------------

class TestShouldSkipCycle:
    def test_skip_empty_pool(self):
        pool = "0xpool1"
        edge = _make_edge("0x0001", "0x0002", pool)
        cycle = _make_cycle(edge)
        pool_states = {pool: _pool_state(pool, _Q96, liquidity=0)}
        assert should_skip_cycle(cycle, pool_states)

    def test_skip_very_negative_spread(self):
        # hop1: A→B zero_for_one, pool1 price=0.1; hop2: B→A one_for_zero, pool2 price=10
        # product = 0.1 * (1/10) = 0.01 → gross_bps = -9900 < -500 → skip
        pool1, pool2 = "0xpool1", "0xpool2"
        edges = [
            _make_edge("0x000a", "0x000b", pool1, fee_bps=0),
            _make_edge("0x000b", "0x000a", pool2, fee_bps=0),
        ]
        cycle = _make_cycle(*edges)
        pool_states = {
            pool1: _pool_state(pool1, int(math.sqrt(0.1) * _Q96)),   # price_raw=0.1
            pool2: _pool_state(pool2, int(math.sqrt(10.0) * _Q96)),  # price_raw=10, inverted=0.1
        }
        assert should_skip_cycle(cycle, pool_states, min_spread_bps=-500.0)

    def test_do_not_skip_missing_states(self):
        # If pool states are missing, should NOT skip (conservative fallback to Quoter)
        pool = "0xpool1"
        edge = _make_edge("0x0001", "0x0002", pool)
        cycle = _make_cycle(edge)
        # Empty dict = no pool states available
        assert not should_skip_cycle(cycle, {})

    def test_do_not_skip_near_zero(self):
        pool1, pool2 = "0xpool1", "0xpool2"
        edges = [
            _make_edge("0x000a", "0x000b", pool1, fee_bps=0),
            _make_edge("0x000b", "0x000a", pool2, fee_bps=0),
        ]
        cycle = _make_cycle(*edges)
        pool_states = {
            pool1: _pool_state(pool1, _Q96),  # price=1 (near zero spread)
            pool2: _pool_state(pool2, _Q96),
        }
        # Default threshold is -500 bps, near-zero should NOT be skipped
        assert not should_skip_cycle(cycle, pool_states)

    def test_force_quote_threshold_never_skips_empty_pool(self):
        # --prequote-min-bps -9999 means "quote everything": even a known-empty pool
        # (which would normally be skipped at the default threshold) must NOT be skipped.
        pool = "0xpool1"
        edge = _make_edge("0x0001", "0x0002", pool)
        cycle = _make_cycle(edge)
        pool_states = {pool: _pool_state(pool, _Q96, liquidity=0)}
        # Sanity: it WOULD be skipped at the default threshold.
        assert should_skip_cycle(cycle, pool_states)
        # Force-quote: not skipped.
        assert not should_skip_cycle(cycle, pool_states, min_spread_bps=-9999.0)

    def test_force_quote_threshold_never_skips_very_negative_spread(self):
        # A catastrophically negative cycle is skipped at -500 but force-quoted at -9999.
        pool1, pool2 = "0xpool1", "0xpool2"
        edges = [
            _make_edge("0x000a", "0x000b", pool1, fee_bps=0),
            _make_edge("0x000b", "0x000a", pool2, fee_bps=0),
        ]
        cycle = _make_cycle(*edges)
        pool_states = {
            pool1: _pool_state(pool1, int(math.sqrt(0.1) * _Q96)),
            pool2: _pool_state(pool2, int(math.sqrt(10.0) * _Q96)),
        }
        assert should_skip_cycle(cycle, pool_states, min_spread_bps=-500.0)
        assert not should_skip_cycle(cycle, pool_states, min_spread_bps=-9999.0)



# ---------------------------------------------------------------------------
# Priority bonus
# ---------------------------------------------------------------------------

class TestPrioritBonus:
    def test_returns_zero_for_missing_state(self):
        edge = _make_edge("0x0001", "0x0002", "0xpool")
        cycle = _make_cycle(edge)
        assert prequote_priority_bonus(cycle, {}) == 0.0

    def test_clamped_at_50(self):
        # Artificially large positive spread should be clamped to 50
        pool = "0xpool"
        sqrt_px96 = int(math.sqrt(100.0) * _Q96)  # 100x ratio
        edge = _make_edge("0x000a", "0x000b", pool, fee_bps=0)
        cycle = _make_cycle(edge)
        pool_states = {pool: _pool_state(pool, sqrt_px96)}
        bonus = prequote_priority_bonus(cycle, pool_states)
        assert bonus <= 50.0

    def test_clamped_at_minus_50(self):
        pool = "0xpool"
        sqrt_px96 = int(math.sqrt(0.0001) * _Q96)  # very negative
        edge = _make_edge("0x000a", "0x000b", pool, fee_bps=0)
        cycle = _make_cycle(edge)
        pool_states = {pool: _pool_state(pool, sqrt_px96)}
        bonus = prequote_priority_bonus(cycle, pool_states)
        assert bonus >= -50.0
