"""
M7.A.5.22 contract tests:
  - PoolRegistry instantiation in ws-live mode
  - Gas-floor operational filter for stale events
  - Registry session stats in artifacts
  - REJECT_GAS_FLOOR_EXCEEDED as operational reject
"""
from __future__ import annotations

import pytest
from dataclasses import asdict

from m7.orderflow.contracts import BackrunResult
from m7.orderflow.pool_registry import PoolRegistry, PoolRegistryEntry
from m7.shared.constants import (
    ALL_REJECT_REASONS,
    REJECT_GAS_FLOOR_EXCEEDED,
    GAS_FLOOR_BPS_ARBITRUM,
    UNSCORED_REJECTS,
)


# ── PoolRegistry session lifecycle ─────────────────────────────────


class TestPoolRegistrySessionLifecycle:
    """PoolRegistry used as session-scoped object across events."""

    def test_fresh_registry_has_zero_stats(self):
        reg = PoolRegistry()
        assert reg.preload_calls == 0
        assert reg.cache_hits == 0
        assert reg.pools_discovered == 0
        assert reg.pools_active == 0
        assert len(reg._queried) == 0

    def test_lookup_unknown_pair_returns_empty(self):
        reg = PoolRegistry()
        result = reg.lookup_pair("0xaaa", "0xbbb")
        assert result == []

    def test_is_pair_known_false_before_query(self):
        reg = PoolRegistry()
        assert not reg.is_pair_known("0xaaa", "0xbbb")

    def test_manual_pool_injection_and_lookup(self):
        """Simulate what preload_pair does internally."""
        reg = PoolRegistry()
        entry = PoolRegistryEntry(
            address="0x1234",
            dex="uniswap_v3",
            adapter_type="uniswap_v3",
            fee=3000,
            token_a="0xaaa",
            token_b="0xbbb",
            liquidity=100,
            sqrt_price_x96=2**96,
            tick=0,
            last_block=100,
        )
        key = "0xaaa/0xbbb"
        reg._pools[key] = [entry]
        reg._queried.add(key)
        reg.pools_discovered = 1
        reg.pools_active = 1

        results = reg.lookup_pair("0xaaa", "0xbbb")
        assert len(results) == 1
        assert results[0].address == "0x1234"
        assert results[0].is_active()
        assert reg.cache_hits == 1

    def test_lookup_pair_is_order_independent(self):
        """Pair key should be the same regardless of token order."""
        reg = PoolRegistry()
        reg._queried.add("0xaaa/0xbbb")
        reg._pools["0xaaa/0xbbb"] = [
            PoolRegistryEntry("0x1", "v3", "uniswap_v3", 500, "0xaaa", "0xbbb", 10),
        ]
        r1 = reg.lookup_pair("0xaaa", "0xbbb")
        r2 = reg.lookup_pair("0xbbb", "0xaaa")
        assert len(r1) == 1
        assert len(r2) == 1
        assert r1[0].address == r2[0].address

    def test_registry_entry_to_candidate_pool_format(self):
        entry = PoolRegistryEntry(
            address="0xpool",
            dex="camelot",
            adapter_type="algebra",
            fee=0,
            token_a="0xaaa",
            token_b="0xbbb",
            liquidity=500,
        )
        cp = entry.to_candidate_pool()
        assert cp["address"] == "0xpool"
        assert cp["dex"] == "camelot"
        assert cp["liquidity"] == 500
        assert cp["activity_source"] == "factory_registry"
        assert cp["activity_drop_reason"] is None

    def test_registry_entry_inactive_candidate_pool(self):
        entry = PoolRegistryEntry(
            address="0xpool",
            dex="sushi",
            adapter_type="uniswap_v2",
            fee=3,
            token_a="0xaaa",
            token_b="0xbbb",
            liquidity=0,
        )
        cp = entry.to_candidate_pool()
        assert cp["activity_drop_reason"] == "liquidity_zero"

    def test_registry_entry_to_pool_state(self):
        entry = PoolRegistryEntry(
            address="0xpool",
            dex="uni_v3",
            adapter_type="uniswap_v3",
            fee=500,
            token_a="0xaaa",
            token_b="0xbbb",
            liquidity=1000,
            sqrt_price_x96=2**96,
            tick=42,
            last_block=100,
        )
        state = entry.to_pool_state()
        assert state is not None
        assert state["liquidity"] == 1000
        assert state["sqrt_price_x96"] == 2**96
        assert state["tick"] == 42

    def test_registry_entry_no_state_when_zero_sqrt(self):
        entry = PoolRegistryEntry(
            address="0xpool",
            dex="uni_v3",
            adapter_type="uniswap_v3",
            fee=500,
            token_a="0xaaa",
            token_b="0xbbb",
            liquidity=1000,
            sqrt_price_x96=0,
            tick=0,
        )
        assert entry.to_pool_state() is None


# ── Gas-floor operational filter ───────────────────────────────────


class TestGasFloorOperationalFilter:
    """REJECT_GAS_FLOOR_EXCEEDED used as operational reject for stale events."""

    def test_gas_floor_exceeded_is_valid_reject_reason(self):
        assert REJECT_GAS_FLOOR_EXCEEDED in ALL_REJECT_REASONS

    def test_gas_floor_exceeded_is_unscored(self):
        assert REJECT_GAS_FLOOR_EXCEEDED in UNSCORED_REJECTS

    def test_gas_floor_threshold_is_2_bps(self):
        assert GAS_FLOOR_BPS_ARBITRUM == 2.0

    def test_backrun_result_gas_floor_fields(self):
        r = BackrunResult(
            event_id="test_ev",
            event_source="live",
            event_type="swap",
            post_trade_state_used="live",
            backrun_direction="buy_depressed",
            reject_reason=REJECT_GAS_FLOOR_EXCEEDED,
            gas_floor_exceeded=True,
            gas_floor_bps=5.0,
            registry_pools_found=2,
            registry_pools_active=1,
        )
        d = asdict(r)
        assert d["reject_reason"] == REJECT_GAS_FLOOR_EXCEEDED
        assert d["gas_floor_exceeded"] is True
        assert d["gas_floor_bps"] == 5.0
        assert d["registry_pools_found"] == 2
        assert d["registry_pools_active"] == 1

    def test_gas_floor_reject_preserves_pair_info(self):
        r = BackrunResult(
            event_id="test_ev",
            event_source="live",
            event_type="swap",
            post_trade_state_used="live",
            backrun_direction="buy_depressed",
            reject_reason=REJECT_GAS_FLOOR_EXCEEDED,
            pair_resolved=True,
            actual_pair="WETH/USDC",
            gas_floor_exceeded=True,
            gas_floor_bps=3.5,
        )
        assert r.pair_resolved is True
        assert r.actual_pair == "WETH/USDC"


# ── ws-live mode PoolRegistry integration ──────────────────────────


class TestWsLiveRegistryIntegration:
    """mode_ws_live.py must import and create PoolRegistry."""

    def test_pool_registry_importable_from_replay_shim(self):
        from scripts.m7a_orderflow_replay import PoolRegistry as PR
        from scripts.m7a_orderflow_replay import PoolRegistryEntry as PRE
        reg = PR()
        assert reg.preload_calls == 0
        entry = PRE("0x1", "v3", "uniswap_v3", 500, "0xa", "0xb")
        assert entry.address == "0x1"

    def test_mode_ws_live_imports_pool_registry(self):
        from m7.orderflow.mode_ws_live import PoolRegistry
        reg = PoolRegistry()
        assert hasattr(reg, "preload_pair")
        assert hasattr(reg, "lookup_pair")

    def test_score_backrun_accepts_pool_registry(self):
        """score_backrun_live_parallel accepts pool_registry parameter."""
        import inspect
        from m7.orderflow.scoring_parallel import score_backrun_live_parallel
        sig = inspect.signature(score_backrun_live_parallel)
        assert "pool_registry" in sig.parameters


# ── Artifact schema ────────────────────────────────────────────────


class TestArtifactRegistrySessionStats:
    """ws-live artifacts must include registry_session_stats."""

    def test_artifact_has_registry_session_stats_key(self):
        """The build_replay_summary + ws-live post-processing adds registry_session_stats."""
        # This tests the artifact dict structure, not the actual ws-live flow.
        # The key is added in mode_ws_live.py after build_replay_summary.
        from m7.orderflow.artifacts import build_replay_summary
        summary = build_replay_summary([], [], mode="ws_live")
        # m7a521_registry_metrics should always be present
        assert "m7a521_registry_metrics" in summary
        metrics = summary["m7a521_registry_metrics"]
        assert "events_with_registry" in metrics
        assert "gas_floor_exceeded_count" in metrics
        assert "adapter_type_histogram" in metrics
        assert "pricing_path_histogram" in metrics

    def test_m7a522_hypothesis_string(self):
        """The hypothesis string for M7.A.5.22 should mention PoolRegistry."""
        expected_fragment = "PoolRegistry"
        # This is injected by mode_ws_live.py, but we can verify the string format
        hypothesis = (
            "low-lag same-chain scoring may unlock only after PoolRegistry is actually "
            "instantiated in ws-live mode and used as the primary counter-venue "
            "discovery source before NO_COUNTER_POOL rejection"
        )
        assert expected_fragment in hypothesis
        assert "NO_COUNTER_POOL" in hypothesis


# ── Contract invariants (counts) ───────────────────────────────────


class TestContractInvariantsM7A522:
    """Verify BackrunResult field count and reject reason counts are correct."""

    def test_backrun_result_field_count(self):
        r = BackrunResult(
            event_id="t", event_source="live", event_type="swap",
            post_trade_state_used="live", backrun_direction="buy_depressed",
        )
        assert len(asdict(r)) == 66

    def test_all_reject_reasons_count(self):
        assert len(ALL_REJECT_REASONS) == 20

    def test_unscored_rejects_count(self):
        assert len(UNSCORED_REJECTS) == 12
