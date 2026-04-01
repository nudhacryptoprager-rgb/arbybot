"""
Contract tests for M7.A.5.20 — Local-state-first pricing.

Tests lock:
- V3 single-tick swap math (compute_v3_swap_amount_out)
- V2 constant-product swap math (compute_v2_swap_amount_out)
- attempt_local_pricing orchestration
- BackrunResult local pricing fields (59 fields total)
- Artifact low_lag_local_pricing block
"""
from __future__ import annotations

import sys
from dataclasses import asdict, fields
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.m7a_orderflow_replay import (
    BackrunResult,
    OrderflowEvent,
    build_replay_summary,
    score_backrun_offline,
    # M7.A.5.20 functions
    compute_v3_swap_amount_out,
    compute_v2_swap_amount_out,
    attempt_local_pricing,
    # Constants
    ALL_REJECT_REASONS,
    UNSCORED_REJECTS,
    ALL_BLOCKER_TAGS,
    EVENT_TYPE_SWAP,
    M7A4_CHAIN,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(**overrides) -> OrderflowEvent:
    defaults = dict(
        event_id="test_520_event",
        event_type=EVENT_TYPE_SWAP,
        chain=M7A4_CHAIN,
        block_number=446900000,
        tx_hash="0x" + "ab" * 32,
        token_in="USDC",
        token_out="WETH",
        amount_in_wei=5000 * 10**6,
        amount_out_wei=1_400_000_000_000_000,
        dex="uniswap_v3",
        pool_address="0x" + "cd" * 20,
        fee_tier=500,
        estimated_size_usd=5000.0,
        estimated_impact_bps=10.0,
        timestamp="2026-03-29T00:00:00Z",
    )
    defaults.update(overrides)
    return OrderflowEvent(**defaults)


# ===========================================================================
# V3 Math Tests
# ===========================================================================

class TestV3SwapMath:
    """compute_v3_swap_amount_out: single-tick V3 swap math."""

    # Known V3 pool state (USDC/WETH 0.05% on Arbitrum, realistic values)
    # sqrtPriceX96 ~ sqrt(3500) * 2^96 ≈ 4.685e39 (WETH/USDC price ~3500)
    # We use a simplified but valid state for testing
    SQRT_PRICE = 4685413736498040635278359 * (10**15)  # ~4.685e39
    LIQUIDITY = 10**18  # 1e18 units of liquidity
    FEE_500 = 500  # 0.05%
    FEE_3000 = 3000  # 0.30%

    def test_zero_for_one_positive_output(self):
        """Swapping token0→token1 with valid state produces positive output."""
        out = compute_v3_swap_amount_out(
            sqrt_price_x96=self.SQRT_PRICE,
            liquidity=self.LIQUIDITY,
            amount_in=10**15,  # 0.001 token0
            fee_pips=self.FEE_500,
            zero_for_one=True,
        )
        assert out is not None
        assert out > 0

    def test_one_for_zero_positive_output(self):
        """Swapping token1→token0 with valid state produces positive output."""
        Q96 = 1 << 96
        out = compute_v3_swap_amount_out(
            sqrt_price_x96=Q96,  # price = 1.0 (symmetric)
            liquidity=10**20,  # high liquidity for meaningful output
            amount_in=10**15,
            fee_pips=self.FEE_500,
            zero_for_one=False,
        )
        assert out is not None
        assert out > 0

    def test_higher_fee_less_output(self):
        """Higher fee tier → less output for same input."""
        out_low = compute_v3_swap_amount_out(
            self.SQRT_PRICE, self.LIQUIDITY, 10**15, self.FEE_500, True,
        )
        out_high = compute_v3_swap_amount_out(
            self.SQRT_PRICE, self.LIQUIDITY, 10**15, self.FEE_3000, True,
        )
        assert out_low is not None and out_high is not None
        assert out_low > out_high

    def test_zero_liquidity_returns_none(self):
        """Zero liquidity → None (no swap possible)."""
        out = compute_v3_swap_amount_out(
            self.SQRT_PRICE, 0, 10**15, self.FEE_500, True,
        )
        assert out is None

    def test_zero_amount_in_returns_none(self):
        out = compute_v3_swap_amount_out(
            self.SQRT_PRICE, self.LIQUIDITY, 0, self.FEE_500, True,
        )
        assert out is None

    def test_zero_sqrt_price_returns_none(self):
        out = compute_v3_swap_amount_out(
            0, self.LIQUIDITY, 10**15, self.FEE_500, True,
        )
        assert out is None

    def test_negative_amount_returns_none(self):
        out = compute_v3_swap_amount_out(
            self.SQRT_PRICE, self.LIQUIDITY, -1, self.FEE_500, True,
        )
        assert out is None

    def test_fee_100_percent_returns_none(self):
        """Fee of 1_000_000 (100%) → no amount after fee → None."""
        out = compute_v3_swap_amount_out(
            self.SQRT_PRICE, self.LIQUIDITY, 10**15, 1_000_000, True,
        )
        assert out is None

    def test_larger_input_more_output(self):
        """Larger input → more output (monotonicity)."""
        out_small = compute_v3_swap_amount_out(
            self.SQRT_PRICE, self.LIQUIDITY, 10**14, self.FEE_500, True,
        )
        out_large = compute_v3_swap_amount_out(
            self.SQRT_PRICE, self.LIQUIDITY, 10**15, self.FEE_500, True,
        )
        assert out_small is not None and out_large is not None
        assert out_large > out_small

    def test_output_less_than_input_for_equal_token_price(self):
        """When sqrtPrice ≈ Q96 (price=1), output < input due to fees."""
        Q96 = 1 << 96
        out = compute_v3_swap_amount_out(
            sqrt_price_x96=Q96,  # price = 1.0
            liquidity=10**20,
            amount_in=10**15,
            fee_pips=3000,
            zero_for_one=True,
        )
        assert out is not None
        assert out < 10**15  # less than input due to fee


# ===========================================================================
# V2 Math Tests
# ===========================================================================

class TestV2SwapMath:
    """compute_v2_swap_amount_out: constant-product swap math."""

    def test_basic_swap(self):
        """Standard V2 swap with equal reserves."""
        out = compute_v2_swap_amount_out(
            reserve_in=10**18,
            reserve_out=10**18,
            amount_in=10**15,
        )
        assert out is not None
        assert out > 0
        # Output should be less than input (fee + price impact)
        assert out < 10**15

    def test_zero_reserves_returns_none(self):
        assert compute_v2_swap_amount_out(0, 10**18, 10**15) is None
        assert compute_v2_swap_amount_out(10**18, 0, 10**15) is None

    def test_zero_amount_returns_none(self):
        assert compute_v2_swap_amount_out(10**18, 10**18, 0) is None

    def test_larger_reserve_out_more_output(self):
        """More reserve_out → more output for same input."""
        out_small = compute_v2_swap_amount_out(10**18, 10**17, 10**15)
        out_large = compute_v2_swap_amount_out(10**18, 10**19, 10**15)
        assert out_small is not None and out_large is not None
        assert out_large > out_small

    def test_fee_affects_output(self):
        """Higher fee → less output."""
        out_low_fee = compute_v2_swap_amount_out(10**18, 10**18, 10**15, 999, 1000)
        out_high_fee = compute_v2_swap_amount_out(10**18, 10**18, 10**15, 990, 1000)
        assert out_low_fee is not None and out_high_fee is not None
        assert out_low_fee > out_high_fee


# ===========================================================================
# attempt_local_pricing Tests
# ===========================================================================

class TestAttemptLocalPricing:
    """attempt_local_pricing: orchestrates local-state pricing across pools."""

    POOL_A = "0x" + "aa" * 20
    POOL_B = "0x" + "bb" * 20
    TOKEN_IN = "0x" + "11" * 20  # lower address → token0
    TOKEN_OUT = "0x" + "ff" * 20  # higher address → token1
    Q96 = 1 << 96

    def _make_candidate_pools(self):
        return [
            {"address": self.POOL_A, "fee": 500, "dex": "uniswap_v3", "liquidity": 10**18},
            {"address": self.POOL_B, "fee": 3000, "dex": "sushiswap_v3", "liquidity": 10**18},
        ]

    def _make_pool_states(self):
        return {
            self.POOL_A: {
                "sqrt_price_x96": self.Q96,  # price = 1.0
                "tick": 0,
                "liquidity": 10**18,
            },
            self.POOL_B: {
                "sqrt_price_x96": self.Q96,
                "tick": 0,
                "liquidity": 10**18,
            },
        }

    def test_successful_local_pricing(self):
        result = attempt_local_pricing(
            candidate_pools=self._make_candidate_pools(),
            local_sim_states=self._make_pool_states(),
            token_in_addr=self.TOKEN_IN,
            token_out_addr=self.TOKEN_OUT,
            backrun_size_wei=10**15,
        )
        assert result is not None
        assert result["buy_amount"] > 0
        assert result["sell_amount"] > 0
        assert result["pricing_path"] == "v3_local"
        assert result["pools_attempted"] >= 1
        assert result["pools_succeeded"] >= 1

    def test_empty_pools_returns_none(self):
        result = attempt_local_pricing(
            candidate_pools=[],
            local_sim_states={},
            token_in_addr=self.TOKEN_IN,
            token_out_addr=self.TOKEN_OUT,
            backrun_size_wei=10**15,
        )
        assert result is None

    def test_zero_liquidity_returns_none(self):
        """Pools with zero liquidity can't produce a quote."""
        pools = [{"address": self.POOL_A, "fee": 500, "liquidity": 0}]
        states = {self.POOL_A: {"sqrt_price_x96": self.Q96, "tick": 0, "liquidity": 0}}
        result = attempt_local_pricing(
            candidate_pools=pools,
            local_sim_states=states,
            token_in_addr=self.TOKEN_IN,
            token_out_addr=self.TOKEN_OUT,
            backrun_size_wei=10**15,
        )
        assert result is None

    def test_no_matching_state_returns_none(self):
        """Candidate pools exist but no matching state."""
        pools = self._make_candidate_pools()
        result = attempt_local_pricing(
            candidate_pools=pools,
            local_sim_states={},  # empty
            token_in_addr=self.TOKEN_IN,
            token_out_addr=self.TOKEN_OUT,
            backrun_size_wei=10**15,
        )
        assert result is None

    def test_picks_best_buy_venue(self):
        """With multiple pools, picks the best (highest output)."""
        pools = self._make_candidate_pools()
        states = self._make_pool_states()
        # Pool A has lower fee (500) → should give more output than Pool B (3000)
        result = attempt_local_pricing(
            candidate_pools=pools,
            local_sim_states=states,
            token_in_addr=self.TOKEN_IN,
            token_out_addr=self.TOKEN_OUT,
            backrun_size_wei=10**15,
        )
        assert result is not None
        assert result["buy_fee"] == 500  # lower fee → better output


# ===========================================================================
# BackrunResult Field Count Tests
# ===========================================================================

class TestBackrunResultM7A520Fields:
    """M7.A.5.20: BackrunResult gains 3 new fields → 59 total."""

    def test_field_count_is_65(self):
        assert len(fields(BackrunResult)) == 65

    def test_local_pricing_fields_exist(self):
        r = BackrunResult(
            event_id="test", event_source="fixture",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="estimated",
            backrun_direction="buy_depressed",
        )
        d = asdict(r)
        assert "local_pricing_attempted" in d
        assert "local_pricing_used" in d
        assert "local_pricing_failure_reason" in d

    def test_local_pricing_defaults_none(self):
        r = BackrunResult(
            event_id="test", event_source="fixture",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="estimated",
            backrun_direction="buy_depressed",
        )
        assert r.local_pricing_attempted is None
        assert r.local_pricing_used is None
        assert r.local_pricing_failure_reason is None

    def test_all_reject_reasons_count_20(self):
        """One new reject reason added in M7.A.5.21."""
        assert len(ALL_REJECT_REASONS) == 20

    def test_unscored_rejects_count_12(self):
        assert len(UNSCORED_REJECTS) == 12

    def test_all_blocker_tags_count_8(self):
        assert len(ALL_BLOCKER_TAGS) == 8


# ===========================================================================
# Artifact Schema Tests
# ===========================================================================

class TestArtifactLocalPricingBlock:
    """M7.A.5.20: build_replay_summary includes low_lag_local_pricing block."""

    def test_low_lag_local_pricing_in_summary(self):
        events = [_make_event()]
        results = [score_backrun_offline(events[0])]
        summary = build_replay_summary(events, results, "test")
        assert "low_lag_local_pricing" in summary
        lp = summary["low_lag_local_pricing"]
        assert "local_attempted_count" in lp
        assert "local_used_count" in lp
        assert "low_lag_scored_local_state_count" in lp
        assert "low_lag_scored_remote_quoter_count" in lp
        assert "low_lag_scored_watchlist_count" in lp
        assert "best_net_bps_local" in lp

    def test_offline_results_have_zero_local_pricing(self):
        """Offline-scored results don't attempt local pricing."""
        events = [_make_event()]
        results = [score_backrun_offline(events[0])]
        summary = build_replay_summary(events, results, "test")
        lp = summary["low_lag_local_pricing"]
        assert lp["local_attempted_count"] == 0
        assert lp["local_used_count"] == 0
        assert lp["low_lag_scored_local_state_count"] == 0

    def test_summary_still_has_blocker_tags(self):
        events = [_make_event()]
        results = [score_backrun_offline(events[0])]
        summary = build_replay_summary(events, results, "test")
        assert "blocker_tags" in summary
        assert "low_lag_watchlist" in summary
