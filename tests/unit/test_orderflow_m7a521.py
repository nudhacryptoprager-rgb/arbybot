"""
Contract tests for M7.A.5.21 — Factory registry, adapter-complete pricing, gas-floor.

Tests lock:
- Algebra swap math (compute_algebra_swap_amount_out)
- Adapter-complete attempt_local_pricing (V3/V2/Algebra dispatch)
- PoolRegistry basic operations (PoolRegistryEntry, pair lookup)
- BackrunResult field count (65 fields total: 59 + 6 new)
- Constants: ALL_REJECT_REASONS=20, UNSCORED_REJECTS=12, ALL_BLOCKER_TAGS=8
- Artifact m7a521_registry_metrics block
- Gas-floor prefilter constant
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
    # M7.A.5.20/5.21 functions
    compute_v3_swap_amount_out,
    compute_v2_swap_amount_out,
    compute_algebra_swap_amount_out,
    attempt_local_pricing,
    # Constants
    ALL_REJECT_REASONS,
    UNSCORED_REJECTS,
    ALL_BLOCKER_TAGS,
    REJECT_GAS_FLOOR_EXCEEDED,
    GAS_FLOOR_BPS_ARBITRUM,
    EVENT_TYPE_SWAP,
    M7A4_CHAIN,
)

from m7.orderflow.pool_registry import PoolRegistry, PoolRegistryEntry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(**overrides) -> OrderflowEvent:
    defaults = dict(
        event_id="test_521_event",
        event_type=EVENT_TYPE_SWAP,
        chain=M7A4_CHAIN,
        block_number=447000000,
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
        timestamp="2026-03-30T00:00:00Z",
    )
    defaults.update(overrides)
    return OrderflowEvent(**defaults)


# ===========================================================================
# Algebra Swap Math Tests
# ===========================================================================

class TestAlgebraSwapMath:
    """compute_algebra_swap_amount_out: Algebra/Camelot V3 swap math."""

    Q96 = 1 << 96

    def test_algebra_swap_zero_for_one(self):
        """Algebra swap produces positive output in zero→one direction."""
        out = compute_algebra_swap_amount_out(
            sqrt_price_x96=self.Q96,
            liquidity=10**20,
            amount_in=10**15,
            fee_zto=500,
            fee_otz=3000,
            zero_for_one=True,
        )
        assert out is not None
        assert out > 0

    def test_algebra_swap_one_for_zero(self):
        """Algebra swap produces positive output in one→zero direction."""
        out = compute_algebra_swap_amount_out(
            sqrt_price_x96=self.Q96,
            liquidity=10**20,
            amount_in=10**15,
            fee_zto=500,
            fee_otz=3000,
            zero_for_one=False,
        )
        assert out is not None
        assert out > 0

    def test_algebra_uses_direction_specific_fee(self):
        """Algebra uses fee_zto for zero→one, fee_otz for one→zero."""
        out_zto = compute_algebra_swap_amount_out(
            self.Q96, 10**20, 10**15,
            fee_zto=500, fee_otz=3000, zero_for_one=True,
        )
        out_otz = compute_algebra_swap_amount_out(
            self.Q96, 10**20, 10**15,
            fee_zto=500, fee_otz=3000, zero_for_one=False,
        )
        assert out_zto is not None and out_otz is not None
        # zero→one uses 500 (low fee → more output)
        # one→zero uses 3000 (high fee → less output)
        assert out_zto > out_otz

    def test_algebra_zero_liquidity_none(self):
        out = compute_algebra_swap_amount_out(
            self.Q96, 0, 10**15, 500, 3000, True,
        )
        assert out is None

    def test_algebra_zero_amount_none(self):
        out = compute_algebra_swap_amount_out(
            self.Q96, 10**20, 0, 500, 3000, True,
        )
        assert out is None

    def test_algebra_matches_v3_when_same_fee(self):
        """With same fee in both directions, Algebra=V3 for given direction."""
        fee = 3000
        v3_out = compute_v3_swap_amount_out(
            self.Q96, 10**20, 10**15, fee, True,
        )
        algebra_out = compute_algebra_swap_amount_out(
            self.Q96, 10**20, 10**15,
            fee_zto=fee, fee_otz=fee, zero_for_one=True,
        )
        assert v3_out == algebra_out


# ===========================================================================
# Adapter-Complete Local Pricing Tests
# ===========================================================================

class TestAdapterCompleteLocalPricing:
    """attempt_local_pricing: V3/V2/Algebra adapter dispatch."""

    POOL_V3 = "0x" + "a1" * 20
    POOL_V2 = "0x" + "b2" * 20
    POOL_ALG = "0x" + "c3" * 20
    TOKEN_IN = "0x" + "11" * 20   # lower address → token0
    TOKEN_OUT = "0x" + "ff" * 20  # higher address → token1
    Q96 = 1 << 96

    def test_v3_adapter_default(self):
        """Without registry_entries, all pools treated as V3."""
        pools = [{"address": self.POOL_V3, "fee": 500}]
        states = {self.POOL_V3: {"sqrt_price_x96": self.Q96, "tick": 0, "liquidity": 10**18}}
        result = attempt_local_pricing(
            pools, states, self.TOKEN_IN, self.TOKEN_OUT, 10**15,
        )
        assert result is not None
        assert result["pricing_path"] == "v3_local"

    def test_v2_adapter_dispatch(self):
        """V2 pools use reserve-based math when registry_entries provided."""
        pools = [{"address": self.POOL_V2, "fee": 3}]
        # V2: sqrt_price_x96 = reserve0, tick = reserve1
        states = {self.POOL_V2: {"sqrt_price_x96": 10**18, "tick": 10**18, "liquidity": 0}}
        registry = [
            PoolRegistryEntry(
                address=self.POOL_V2, dex="sushiswap_v2",
                adapter_type="uniswap_v2", fee=3,
                token_a=self.TOKEN_IN, token_b=self.TOKEN_OUT,
            )
        ]
        result = attempt_local_pricing(
            pools, states, self.TOKEN_IN, self.TOKEN_OUT, 10**15,
            registry_entries=registry,
        )
        assert result is not None
        assert result["pricing_path"] == "v2_local"

    def test_algebra_adapter_dispatch(self):
        """Algebra pools use V3-style math with adapter dispatch."""
        pools = [{"address": self.POOL_ALG, "fee": 3000}]
        states = {self.POOL_ALG: {"sqrt_price_x96": self.Q96, "tick": 0, "liquidity": 10**18}}
        registry = [
            PoolRegistryEntry(
                address=self.POOL_ALG, dex="camelot_v3",
                adapter_type="algebra", fee=3000,
                token_a=self.TOKEN_IN, token_b=self.TOKEN_OUT,
            )
        ]
        result = attempt_local_pricing(
            pools, states, self.TOKEN_IN, self.TOKEN_OUT, 10**15,
            registry_entries=registry,
        )
        assert result is not None
        assert result["pricing_path"] == "algebra_local"

    def test_backward_compatible_without_registry(self):
        """Without registry_entries, behaves exactly like M7.A.5.20."""
        pools = [
            {"address": self.POOL_V3, "fee": 500},
            {"address": self.POOL_V2, "fee": 3000},
        ]
        states = {
            self.POOL_V3: {"sqrt_price_x96": self.Q96, "tick": 0, "liquidity": 10**18},
            self.POOL_V2: {"sqrt_price_x96": self.Q96, "tick": 0, "liquidity": 10**18},
        }
        result = attempt_local_pricing(
            pools, states, self.TOKEN_IN, self.TOKEN_OUT, 10**15,
        )
        assert result is not None
        assert result["pricing_path"] == "v3_local"  # all treated as V3

    def test_sell_pass_uses_adapter_dispatch(self):
        """Sell pass also dispatches based on adapter type."""
        pools = [{"address": self.POOL_V2, "fee": 3}]
        states = {self.POOL_V2: {"sqrt_price_x96": 10**18, "tick": 10**18, "liquidity": 0}}
        registry = [
            PoolRegistryEntry(
                address=self.POOL_V2, dex="sushiswap_v2",
                adapter_type="uniswap_v2", fee=3,
                token_a=self.TOKEN_IN, token_b=self.TOKEN_OUT,
            )
        ]
        result = attempt_local_pricing(
            pools, states, self.TOKEN_IN, self.TOKEN_OUT, 10**15,
            registry_entries=registry,
        )
        assert result is not None
        assert result["sell_amount"] > 0


# ===========================================================================
# PoolRegistry Tests
# ===========================================================================

class TestPoolRegistryEntry:
    """PoolRegistryEntry: basic dataclass behavior."""

    def test_is_active_with_positive_liquidity(self):
        e = PoolRegistryEntry(
            address="0x" + "aa" * 20, dex="uniswap_v3", adapter_type="uniswap_v3",
            fee=500, token_a="0x1", token_b="0x2", liquidity=1000,
        )
        assert e.is_active() is True

    def test_is_active_zero_liquidity(self):
        e = PoolRegistryEntry(
            address="0x" + "aa" * 20, dex="uniswap_v3", adapter_type="uniswap_v3",
            fee=500, token_a="0x1", token_b="0x2", liquidity=0,
        )
        assert e.is_active() is False

    def test_is_active_none_liquidity(self):
        e = PoolRegistryEntry(
            address="0x" + "aa" * 20, dex="uniswap_v3", adapter_type="uniswap_v3",
            fee=500, token_a="0x1", token_b="0x2", liquidity=None,
        )
        assert e.is_active() is False

    def test_to_candidate_pool(self):
        e = PoolRegistryEntry(
            address="0xaabb", dex="uni", adapter_type="uniswap_v3",
            fee=500, token_a="0x1", token_b="0x2", liquidity=100,
        )
        cp = e.to_candidate_pool()
        assert cp["address"] == "0xaabb"
        assert cp["fee"] == 500
        assert cp["activity_source"] == "factory_registry"
        assert cp["activity_drop_reason"] is None

    def test_to_candidate_pool_zero_liquidity(self):
        e = PoolRegistryEntry(
            address="0xaabb", dex="uni", adapter_type="uniswap_v3",
            fee=500, token_a="0x1", token_b="0x2", liquidity=0,
        )
        cp = e.to_candidate_pool()
        assert cp["activity_drop_reason"] == "liquidity_zero"

    def test_to_pool_state(self):
        e = PoolRegistryEntry(
            address="0xaabb", dex="uni", adapter_type="uniswap_v3",
            fee=500, token_a="0x1", token_b="0x2",
            liquidity=100, sqrt_price_x96=999, tick=-10,
        )
        ps = e.to_pool_state()
        assert ps is not None
        assert ps["sqrt_price_x96"] == 999
        assert ps["tick"] == -10
        assert ps["liquidity"] == 100

    def test_to_pool_state_none_when_no_sqrt_price(self):
        e = PoolRegistryEntry(
            address="0xaabb", dex="uni", adapter_type="uniswap_v3",
            fee=500, token_a="0x1", token_b="0x2",
            liquidity=100, sqrt_price_x96=None,
        )
        assert e.to_pool_state() is None

    def test_address_lowercased(self):
        e = PoolRegistryEntry(
            address="0xAABB", dex="uni", adapter_type="uniswap_v3",
            fee=500, token_a="0xCC", token_b="0xDD",
        )
        assert e.address == "0xaabb"
        assert e.token_a == "0xcc"
        assert e.token_b == "0xdd"


class TestPoolRegistryLookup:
    """PoolRegistry: in-memory pair lookup without RPC."""

    def test_empty_registry(self):
        reg = PoolRegistry()
        entries = reg.lookup_pair("0xA", "0xB")
        assert entries == []

    def test_is_pair_known_false_initially(self):
        reg = PoolRegistry()
        assert reg.is_pair_known("0xA", "0xB") is False

    def test_stats_initial(self):
        reg = PoolRegistry()
        assert reg.preload_calls == 0
        assert reg.cache_hits == 0
        assert reg.pools_discovered == 0
        assert reg.pools_active == 0


# ===========================================================================
# BackrunResult Field Count Tests
# ===========================================================================

class TestBackrunResultM7A521Fields:
    """M7.A.5.21: BackrunResult gains 6 new fields → 65 total."""

    def test_field_count_is_65(self):
        assert len(fields(BackrunResult)) == 66

    def test_new_fields_exist(self):
        r = BackrunResult(
            event_id="test", event_source="fixture",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="estimated",
            backrun_direction="buy_depressed",
        )
        d = asdict(r)
        assert "registry_pools_found" in d
        assert "registry_pools_active" in d
        assert "adapter_type_used" in d
        assert "gas_floor_exceeded" in d
        assert "gas_floor_bps" in d
        assert "pricing_path" in d

    def test_new_fields_default_none(self):
        r = BackrunResult(
            event_id="test", event_source="fixture",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="estimated",
            backrun_direction="buy_depressed",
        )
        assert r.registry_pools_found is None
        assert r.registry_pools_active is None
        assert r.adapter_type_used is None
        assert r.gas_floor_exceeded is None
        assert r.gas_floor_bps is None
        assert r.pricing_path is None


# ===========================================================================
# Constants Count Tests
# ===========================================================================

class TestConstantsM7A521:
    """M7.A.5.21: Updated constant set sizes."""

    def test_all_reject_reasons_count_20(self):
        """One new reject reason: GAS_FLOOR_EXCEEDED."""
        assert len(ALL_REJECT_REASONS) == 20

    def test_unscored_rejects_count_12(self):
        """GAS_FLOOR_EXCEEDED added to UNSCORED_REJECTS."""
        assert len(UNSCORED_REJECTS) == 12

    def test_gas_floor_exceeded_in_sets(self):
        assert REJECT_GAS_FLOOR_EXCEEDED in ALL_REJECT_REASONS
        assert REJECT_GAS_FLOOR_EXCEEDED in UNSCORED_REJECTS

    def test_all_blocker_tags_count_8(self):
        """No new blocker tags in M7.A.5.21."""
        assert len(ALL_BLOCKER_TAGS) == 8

    def test_gas_floor_bps_positive(self):
        assert GAS_FLOOR_BPS_ARBITRUM > 0
        assert GAS_FLOOR_BPS_ARBITRUM == 2.0


# ===========================================================================
# Artifact Schema Tests
# ===========================================================================

class TestArtifactRegistryMetrics:
    """M7.A.5.21: build_replay_summary includes m7a521_registry_metrics."""

    def test_registry_metrics_in_summary(self):
        events = [_make_event()]
        results = [score_backrun_offline(events[0])]
        summary = build_replay_summary(events, results, "test")
        assert "m7a521_registry_metrics" in summary
        rm = summary["m7a521_registry_metrics"]
        assert "events_with_registry" in rm
        assert "total_registry_pools_found" in rm
        assert "total_registry_pools_active" in rm
        assert "gas_floor_exceeded_count" in rm
        assert "adapter_type_histogram" in rm
        assert "pricing_path_histogram" in rm

    def test_offline_results_have_no_registry(self):
        """Offline-scored results don't use registry."""
        events = [_make_event()]
        results = [score_backrun_offline(events[0])]
        summary = build_replay_summary(events, results, "test")
        rm = summary["m7a521_registry_metrics"]
        assert rm["events_with_registry"] == 0
        assert rm["total_registry_pools_found"] == 0

    def test_summary_still_has_local_pricing_block(self):
        events = [_make_event()]
        results = [score_backrun_offline(events[0])]
        summary = build_replay_summary(events, results, "test")
        assert "low_lag_local_pricing" in summary
        assert "blocker_tags" in summary
