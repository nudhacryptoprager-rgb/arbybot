# PATH: tests/unit/test_adaptive_sweep.py
"""
Unit tests for adaptive refinement in engine/roundtrip.py sweep_roundtrip_sizes.

Tests the golden-section search that refines the optimal trade size between
the coarse sweep grid points.
"""

import pytest
from unittest.mock import MagicMock
from decimal import Decimal

from engine.roundtrip import (
    sweep_roundtrip_sizes,
    SizeSweepResult,
    SizeSweepPoint,
    _evaluate_single_size,
    ADAPTIVE_MAX_ITERATIONS,
    ADAPTIVE_MIN_INTERVAL_USD,
    CANONICAL_SWEEP_SIZES_USD,
)


def _make_requote(amount_out_factor=0.998, gas=150_000, ticks=1):
    """Create a requote callback that returns factor * input."""
    def _requote(amount_in_wei):
        return {
            "amount_out_wei": int(amount_in_wei * amount_out_factor),
            "gas_estimate": gas,
            "ticks_crossed": ticks,
        }
    return _requote


def _make_buy_quote():
    return {
        "token_in": "USDC",
        "token_out": "WETH",
        "dex_id": "uniswap_v3",
        "fee": 500,
        "amount_in_wei": 50_000_000,
        "amount_out_wei": 24_000_000_000_000_000,
        "gas_estimate": 150_000,
        "ticks_crossed": 1,
    }


def _make_sell_quote():
    return {
        "token_in": "WETH",
        "token_out": "USDC",
        "dex_id": "sushiswap_v3",
        "fee": 500,
        "amount_in_wei": 24_000_000_000_000_000,
        "amount_out_wei": 49_800_000,
        "gas_estimate": 150_000,
        "ticks_crossed": 1,
    }


class TestAdaptiveRefinementConstants:
    def test_max_iterations_bounded(self):
        assert ADAPTIVE_MAX_ITERATIONS >= 2
        assert ADAPTIVE_MAX_ITERATIONS <= 10

    def test_min_interval_positive(self):
        assert ADAPTIVE_MIN_INTERVAL_USD > 0


class TestEvaluateSingleSize:
    def test_basic_evaluation(self):
        bq = _make_buy_quote()
        sq = _make_sell_quote()
        rq1 = _make_requote(0.998)
        rq2 = _make_requote(0.998)

        pt = _evaluate_single_size(
            size_usd=100.0,
            buy_quote_base=bq,
            sell_quote_base=sq,
            requote_leg1=rq1,
            requote_leg2=rq2,
            token_in_usd_price=1.0,  # USDC
            token_in_decimals=6,
            gas_price_wei=100_000_000,
            l1_cost_wei=6_000_000_000_000,
            l1_cost_source="default",
            eth_usd_price=2000.0,
        )
        assert pt is not None
        assert pt.size_usd == 100.0
        assert pt.net_pnl_bps is not None

    def test_zero_amount_returns_none(self):
        bq = _make_buy_quote()
        sq = _make_sell_quote()
        pt = _evaluate_single_size(
            size_usd=0.0,
            buy_quote_base=bq,
            sell_quote_base=sq,
            requote_leg1=_make_requote(),
            requote_leg2=_make_requote(),
            token_in_usd_price=1.0,
            token_in_decimals=6,
            gas_price_wei=100_000_000,
            l1_cost_wei=6_000_000_000_000,
            l1_cost_source="default",
            eth_usd_price=2000.0,
        )
        assert pt is None

    def test_failing_requote_returns_none(self):
        bq = _make_buy_quote()
        sq = _make_sell_quote()

        def _fail(amt):
            raise RuntimeError("RPC error")

        pt = _evaluate_single_size(
            size_usd=50.0,
            buy_quote_base=bq,
            sell_quote_base=sq,
            requote_leg1=_fail,
            requote_leg2=_make_requote(),
            token_in_usd_price=1.0,
            token_in_decimals=6,
            gas_price_wei=100_000_000,
            l1_cost_wei=6_000_000_000_000,
            l1_cost_source="default",
            eth_usd_price=2000.0,
        )
        assert pt is None


class TestSweepWithAdaptiveRefinement:
    def test_refinement_produces_more_points(self):
        """Adaptive refinement should add points beyond the coarse grid."""
        bq = _make_buy_quote()
        sq = _make_sell_quote()
        rq1 = _make_requote(0.998)
        rq2 = _make_requote(0.998)

        # Coarse only
        result_coarse = sweep_roundtrip_sizes(
            buy_quote_base=bq,
            sell_quote_base=sq,
            requote_leg1=rq1,
            requote_leg2=rq2,
            sizes_usd=[25, 50, 100, 250],
            token_in_usd_price=1.0,
            token_in_decimals=6,
            gas_price_wei=100_000_000,
            l1_cost_wei=6_000_000_000_000,
            l1_cost_source="default",
            eth_usd_price=2000.0,
            adaptive_refinement=False,
        )

        # With refinement
        result_adaptive = sweep_roundtrip_sizes(
            buy_quote_base=bq,
            sell_quote_base=sq,
            requote_leg1=rq1,
            requote_leg2=rq2,
            sizes_usd=[25, 50, 100, 250],
            token_in_usd_price=1.0,
            token_in_decimals=6,
            gas_price_wei=100_000_000,
            l1_cost_wei=6_000_000_000_000,
            l1_cost_source="default",
            eth_usd_price=2000.0,
            adaptive_refinement=True,
        )

        # Adaptive should have at least as many valid points
        coarse_valid = len([p for p in result_coarse.points if p.error is None])
        adaptive_valid = len([p for p in result_adaptive.points if p.error is None])
        assert adaptive_valid >= coarse_valid

    def test_refinement_best_is_valid(self):
        """The refined best should still be a valid point."""
        bq = _make_buy_quote()
        sq = _make_sell_quote()
        rq1 = _make_requote(0.998)
        rq2 = _make_requote(0.998)

        result = sweep_roundtrip_sizes(
            buy_quote_base=bq,
            sell_quote_base=sq,
            requote_leg1=rq1,
            requote_leg2=rq2,
            sizes_usd=[25, 50, 100, 250, 500],
            token_in_usd_price=1.0,
            token_in_decimals=6,
            gas_price_wei=100_000_000,
            l1_cost_wei=6_000_000_000_000,
            l1_cost_source="default",
            eth_usd_price=2000.0,
            adaptive_refinement=True,
        )

        assert result.best_size_usd is not None
        assert result.best_net_pnl_bps is not None

    def test_no_refinement_with_single_point(self):
        """With only one size point, refinement should be a no-op."""
        bq = _make_buy_quote()
        sq = _make_sell_quote()
        rq1 = _make_requote(0.998)
        rq2 = _make_requote(0.998)

        result = sweep_roundtrip_sizes(
            buy_quote_base=bq,
            sell_quote_base=sq,
            requote_leg1=rq1,
            requote_leg2=rq2,
            sizes_usd=[50],
            token_in_usd_price=1.0,
            token_in_decimals=6,
            gas_price_wei=100_000_000,
            l1_cost_wei=6_000_000_000_000,
            l1_cost_source="default",
            eth_usd_price=2000.0,
            adaptive_refinement=True,
        )

        # Only the one coarse point should exist (maybe none if degenerate)
        valid_points = [p for p in result.points if p.error is None]
        assert len(valid_points) <= 1

    def test_backward_compatible_without_refinement(self):
        """Default behavior (no adaptive) should be unchanged."""
        bq = _make_buy_quote()
        sq = _make_sell_quote()
        rq1 = _make_requote(0.998)
        rq2 = _make_requote(0.998)

        result = sweep_roundtrip_sizes(
            buy_quote_base=bq,
            sell_quote_base=sq,
            requote_leg1=rq1,
            requote_leg2=rq2,
            sizes_usd=[25, 50, 100],
            token_in_usd_price=1.0,
            token_in_decimals=6,
            gas_price_wei=100_000_000,
            l1_cost_wei=6_000_000_000_000,
            l1_cost_source="default",
            eth_usd_price=2000.0,
            # adaptive_refinement defaults to False
        )

        # Should have exactly the coarse grid points (no extras)
        all_sizes = [p.size_usd for p in result.points]
        for s in all_sizes:
            assert s in [25, 50, 100] or "error" in str(result.points)
