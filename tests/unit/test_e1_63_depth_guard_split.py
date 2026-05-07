"""
E1.63 unit tests — step 7 (route splitting) + step 8 (QuoterV2 depth guard).

Tests:
  - compute_v3_sqrt_price_after: basic zero_for_one=True/False paths, edge cases
  - attempt_split_pricing: 2 pools → split, 1 pool → None, V2 excluded, pricing_path
  - price_impact_bps derivation formula
"""
import pytest
from typing import Optional

from m7.orderflow.v3_math import (
    compute_v3_sqrt_price_after,
    attempt_split_pricing,
    compute_v3_swap_amount_out,
)


# ── Q96 and typical pool constants ──────────────────────────────────────────
Q96 = 2**96
# sqrtPrice for 1:1 at Q96
_SQRT_PRICE_1_1 = int(1.0 * Q96)
# sqrtPrice for price=2000 (WETH/USDC-like)
_SQRT_PRICE_2000 = int((2000**0.5) * Q96)
_LIQ = 10**18  # adequate liquidity
_ADDR_LOW = "0x0000000000000000000000000000000000000001"
_ADDR_HIGH = "0x0000000000000000000000000000000000000002"
_ADDR_V2 = "0x0000000000000000000000000000000000000003"


# ── compute_v3_sqrt_price_after ──────────────────────────────────────────────

class TestComputeV3SqrtPriceAfter:

    def test_zero_for_one_price_decreases(self):
        """Buying token0 with token1 pushes sqrtPrice down."""
        sp_before = _SQRT_PRICE_1_1
        result = compute_v3_sqrt_price_after(
            sqrt_price_x96=sp_before,
            liquidity=_LIQ,
            amount_in=10**15,  # 0.001 token
            fee_pips=3000,
            zero_for_one=True,
        )
        assert result is not None, "Expected sqrtPrice result for zero_for_one=True"
        assert result < sp_before, "sqrtPrice should decrease when zero_for_one=True"

    def test_one_for_zero_price_increases(self):
        """Buying token1 with token0 pushes sqrtPrice up."""
        sp_before = _SQRT_PRICE_1_1
        result = compute_v3_sqrt_price_after(
            sqrt_price_x96=sp_before,
            liquidity=_LIQ,
            amount_in=10**15,
            fee_pips=3000,
            zero_for_one=False,
        )
        assert result is not None, "Expected sqrtPrice result for zero_for_one=False"
        assert result > sp_before, "sqrtPrice should increase when zero_for_one=False"

    def test_zero_liquidity_returns_none(self):
        assert compute_v3_sqrt_price_after(
            sqrt_price_x96=_SQRT_PRICE_1_1,
            liquidity=0,
            amount_in=10**15,
            fee_pips=3000,
            zero_for_one=True,
        ) is None

    def test_zero_amount_in_returns_none(self):
        assert compute_v3_sqrt_price_after(
            sqrt_price_x96=_SQRT_PRICE_1_1,
            liquidity=_LIQ,
            amount_in=0,
            fee_pips=3000,
            zero_for_one=True,
        ) is None

    def test_zero_sqrt_price_returns_none(self):
        assert compute_v3_sqrt_price_after(
            sqrt_price_x96=0,
            liquidity=_LIQ,
            amount_in=10**15,
            fee_pips=3000,
            zero_for_one=True,
        ) is None

    def test_invalid_fee_returns_none(self):
        """fee_pips >= FEE_DENOMINATOR (1_000_000) is invalid."""
        assert compute_v3_sqrt_price_after(
            sqrt_price_x96=_SQRT_PRICE_1_1,
            liquidity=_LIQ,
            amount_in=10**15,
            fee_pips=1_000_000,
            zero_for_one=True,
        ) is None

    def test_price_impact_bps_derivation(self):
        """Derive price_impact_bps = |1 - (sp_after/sp_before)^2| * 10_000."""
        sp_before = _SQRT_PRICE_1_1
        sp_after = compute_v3_sqrt_price_after(
            sqrt_price_x96=sp_before,
            liquidity=_LIQ,
            amount_in=10**16,  # 0.01 token
            fee_pips=3000,
            zero_for_one=True,
        )
        assert sp_after is not None
        ratio = (sp_after / sp_before) ** 2
        impact_bps = abs(1.0 - ratio) * 10_000.0
        # For small swaps relative to liquidity, impact should be small
        assert 0.0 < impact_bps < 500.0, f"impact_bps={impact_bps} out of expected range"


# ── attempt_split_pricing ────────────────────────────────────────────────────

def _make_pool(addr: str, fee: int = 3000, sp: Optional[int] = None, liq: Optional[int] = None):
    return {
        "address": addr,
        "fee": fee,
        "sqrt_price_x96": sp if sp is not None else _SQRT_PRICE_1_1,
        "liquidity": liq if liq is not None else _LIQ,
    }


def _make_states(pools: list) -> dict:
    return {
        p["address"]: {
            "sqrt_price_x96": p["sqrt_price_x96"],
            "liquidity": p["liquidity"],
        }
        for p in pools
    }


class TestAttemptSplitPricing:

    def test_two_pools_returns_split_result(self):
        """With 2 V3 pools, returns dict with pricing_path='v3_split_local'."""
        pool_a = _make_pool(_ADDR_LOW, fee=500)
        pool_b = _make_pool(_ADDR_HIGH, fee=3000)
        candidate_pools = [pool_a, pool_b]
        sim_states = _make_states([pool_a, pool_b])

        result = attempt_split_pricing(
            candidate_pools=candidate_pools,
            local_sim_states=sim_states,
            token_in_addr=_ADDR_LOW,
            token_out_addr=_ADDR_HIGH,
            backrun_size_wei=10**16,
        )
        assert result is not None, "Expected split result with 2 pools"
        assert result["pricing_path"] == "v3_split_local"
        assert "split_pool_b" in result
        assert "split_amount_a" in result
        assert "split_amount_b" in result
        assert result["buy_amount"] > 0
        assert result["sell_amount"] > 0
        assert result["pools_succeeded"] == 2

    def test_one_pool_returns_none(self):
        """With only 1 V3 pool, split is not possible — returns None."""
        pool_a = _make_pool(_ADDR_LOW, fee=500)
        candidate_pools = [pool_a]
        sim_states = _make_states([pool_a])

        result = attempt_split_pricing(
            candidate_pools=candidate_pools,
            local_sim_states=sim_states,
            token_in_addr=_ADDR_LOW,
            token_out_addr=_ADDR_HIGH,
            backrun_size_wei=10**16,
        )
        assert result is None, "Expected None with only 1 pool"

    def test_v2_pools_excluded(self):
        """V2 adapter pools are excluded from split routing."""
        pool_v3 = _make_pool(_ADDR_LOW, fee=500)
        pool_v2 = _make_pool(_ADDR_V2, fee=3000)
        candidate_pools = [pool_v3, pool_v2]
        sim_states = _make_states([pool_v3, pool_v2])

        # Registry entries to mark _ADDR_V2 as V2 adapter
        class FakeEntry:
            def __init__(self, addr, adapter):
                self.address = addr
                self.adapter_type = adapter
                self.dex = adapter

        registry_entries = [
            FakeEntry(_ADDR_LOW, "uniswap_v3"),
            FakeEntry(_ADDR_V2, "uniswap_v2"),
        ]

        result = attempt_split_pricing(
            candidate_pools=candidate_pools,
            local_sim_states=sim_states,
            token_in_addr=_ADDR_LOW,
            token_out_addr=_ADDR_HIGH,
            backrun_size_wei=10**16,
            registry_entries=registry_entries,
        )
        # Only 1 V3 pool available → should return None
        assert result is None, "Expected None when only 1 non-V2 pool available"

    def test_empty_pools_returns_none(self):
        result = attempt_split_pricing(
            candidate_pools=[],
            local_sim_states={},
            token_in_addr=_ADDR_LOW,
            token_out_addr=_ADDR_HIGH,
            backrun_size_wei=10**16,
        )
        assert result is None

    def test_zero_liquidity_pools_returns_none(self):
        """Pools with zero liquidity are skipped."""
        pool_a = _make_pool(_ADDR_LOW, fee=500, liq=0)
        pool_b = _make_pool(_ADDR_HIGH, fee=3000, liq=0)
        candidate_pools = [pool_a, pool_b]
        sim_states = _make_states([pool_a, pool_b])

        result = attempt_split_pricing(
            candidate_pools=candidate_pools,
            local_sim_states=sim_states,
            token_in_addr=_ADDR_LOW,
            token_out_addr=_ADDR_HIGH,
            backrun_size_wei=10**16,
        )
        assert result is None

    def test_split_buy_amounts_sum_correctly(self):
        """buy_amount should equal split_amount_a + split_amount_b."""
        pool_a = _make_pool(_ADDR_LOW, fee=500)
        pool_b = _make_pool(_ADDR_HIGH, fee=3000)
        candidate_pools = [pool_a, pool_b]
        sim_states = _make_states([pool_a, pool_b])

        result = attempt_split_pricing(
            candidate_pools=candidate_pools,
            local_sim_states=sim_states,
            token_in_addr=_ADDR_LOW,
            token_out_addr=_ADDR_HIGH,
            backrun_size_wei=10**16,
        )
        assert result is not None
        assert result["buy_amount"] == result["split_amount_a"] + result["split_amount_b"]
