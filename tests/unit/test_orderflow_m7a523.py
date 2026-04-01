"""
M7.A.5.23 contract tests:
  - Low-lag registry-direct scoring fast path
  - BackrunResult.low_lag_scoring_path field
  - Artifact metrics for registry-direct path
  - Session-persistent low-lag pair tracking in ws-live
"""
from __future__ import annotations

import pytest
from dataclasses import asdict, fields

from m7.orderflow.contracts import BackrunResult, OrderflowEvent
from m7.orderflow.pool_registry import PoolRegistry, PoolRegistryEntry
from m7.shared.constants import (
    ALL_REJECT_REASONS,
    UNSCORED_REJECTS,
    REJECT_GAS_EXCEEDS_GROSS,
    REJECT_NO_COUNTER_POOL,
    REJECT_UNSUPPORTED_ADAPTER,
    REJECT_ALL_POOLS_TRULY_INACTIVE,
)


# ── BackrunResult field contract ────────────────────────────────────


class TestBackrunResultM7A523:
    """Verify low_lag_scoring_path field exists and BackrunResult field count."""

    def test_low_lag_scoring_path_field_exists(self):
        r = BackrunResult(
            event_id="e1", event_source="live",
            event_type="uniswap_v3_swap", post_trade_state_used="live",
            backrun_direction="buy_depressed",
        )
        assert hasattr(r, "low_lag_scoring_path")
        assert r.low_lag_scoring_path is None

    def test_low_lag_scoring_path_settable(self):
        r = BackrunResult(
            event_id="e1", event_source="live",
            event_type="uniswap_v3_swap", post_trade_state_used="live",
            backrun_direction="buy_depressed",
            low_lag_scoring_path="registry_direct",
        )
        assert r.low_lag_scoring_path == "registry_direct"

    def test_field_count_is_66(self):
        """M7.A.5.23 adds low_lag_scoring_path → 66 fields total."""
        assert len(fields(BackrunResult)) == 66

    def test_low_lag_scoring_path_in_asdict(self):
        r = BackrunResult(
            event_id="e1", event_source="live",
            event_type="uniswap_v3_swap", post_trade_state_used="live",
            backrun_direction="buy_depressed",
            low_lag_scoring_path="registry_direct",
        )
        d = asdict(r)
        assert "low_lag_scoring_path" in d
        assert d["low_lag_scoring_path"] == "registry_direct"


# ── Registry-direct fast path contract ──────────────────────────────


class TestRegistryDirectFastPath:
    """Test that registry entries can provide synthetic coverage and local_sim."""

    def _make_active_entry(self, addr="0xpool1", dex="uniswap_v3",
                           adapter="uniswap_v3", fee=3000, liq=10000,
                           sqrt_p=2**96, tick=0):
        return PoolRegistryEntry(
            address=addr, dex=dex, adapter_type=adapter, fee=fee,
            token_a="0xaaa", token_b="0xbbb",
            liquidity=liq, sqrt_price_x96=sqrt_p, tick=tick,
            last_block=100,
        )

    def test_active_entry_to_candidate_pool(self):
        e = self._make_active_entry()
        cp = e.to_candidate_pool()
        assert cp["address"] == "0xpool1"
        assert cp["liquidity"] == 10000
        assert cp["activity_source"] == "factory_registry"
        assert cp["activity_drop_reason"] is None

    def test_active_entry_to_pool_state_has_full_state(self):
        e = self._make_active_entry()
        ps = e.to_pool_state()
        assert ps is not None
        assert ps["sqrt_price_x96"] == 2**96
        assert ps["tick"] == 0
        assert ps["liquidity"] == 10000

    def test_inactive_entry_excluded_from_fast_path(self):
        e = PoolRegistryEntry(
            address="0xdead", dex="v3", adapter_type="uniswap_v3", fee=500,
            token_a="0xaaa", token_b="0xbbb", liquidity=0,
        )
        assert not e.is_active()
        assert e.to_pool_state() is None

    def test_synthetic_coverage_from_registry(self):
        """Simulate what the fast path builds from registry entries."""
        entries = [
            self._make_active_entry(addr="0xp1", dex="uniswap_v3"),
            self._make_active_entry(addr="0xp2", dex="sushiswap"),
        ]
        active = [e for e in entries if e.is_active()]
        cand_pools = [e.to_candidate_pool() for e in active]
        pool_states = {}
        for e in active:
            ps = e.to_pool_state()
            if ps:
                pool_states[e.address] = ps

        assert len(cand_pools) == 2
        assert len(pool_states) == 2
        assert all(cp["activity_source"] == "factory_registry" for cp in cand_pools)

        # Build synthetic coverage
        reg_dexes = list(set(e.dex for e in active))
        coverage = {
            "coverage_complete": True,
            "coverage_blocker_reason": None,
            "candidate_pools": cand_pools,
            "active_pools_total": len(active),
            "active_buy_venues": len(reg_dexes),
            "active_sell_venues": len(reg_dexes),
        }
        assert coverage["coverage_complete"] is True
        assert coverage["active_pools_total"] == 2

    def test_synthetic_local_sim_from_registry(self):
        """Verify local_sim dict built from registry has expected shape."""
        entries = [
            self._make_active_entry(addr="0xp1"),
            self._make_active_entry(addr="0xp2", liq=5000, sqrt_p=2**97, tick=10),
        ]
        pool_states = {}
        for e in entries:
            ps = e.to_pool_state()
            if ps:
                pool_states[e.address] = ps

        local_sim = {
            "pools_queried": len(entries),
            "pools_with_state": len(pool_states),
            "pool_states": dict(list(pool_states.items())[:3]),
        }
        assert local_sim["pools_with_state"] == 2
        assert len(local_sim["pool_states"]) == 2

    def test_v2_entry_provides_pool_state_via_reserves(self):
        """V2 pools store reserve0/reserve1 as sqrt_price_x96/tick."""
        e = PoolRegistryEntry(
            address="0xv2pool", dex="sushiswap", adapter_type="uniswap_v2",
            fee=30, token_a="0xaaa", token_b="0xbbb",
            liquidity=500, sqrt_price_x96=1000000, tick=2000000,
            last_block=100,
        )
        assert e.is_active()
        ps = e.to_pool_state()
        assert ps is not None
        assert ps["sqrt_price_x96"] == 1000000  # reserve0
        assert ps["tick"] == 2000000  # reserve1
        assert ps["liquidity"] == 500


# ── Artifact metrics for M7.A.5.23 ─────────────────────────────────


class TestArtifactM7A523:
    """Verify build_replay_summary includes M7.A.5.23 metrics."""

    def _make_event(self, eid="e1"):
        return OrderflowEvent(
            event_id=eid, event_type="swap",
            chain="arbitrum_one", block_number=100,
            tx_hash="0xabc", token_in="USDC", token_out="WETH",
            amount_in_wei=1000000, amount_out_wei=500000,
            dex="uniswap_v3", pool_address="0xpool",
            fee_tier=3000, estimated_size_usd=100.0,
            estimated_impact_bps=5.0, timestamp="2025-01-01T00:00:00Z",
        )

    def _make_result_low_lag_registry_direct(self, eid="e1"):
        return BackrunResult(
            event_id=eid, event_source="live",
            event_type="uniswap_v3_swap", post_trade_state_used="live",
            backrun_direction="buy_depressed",
            event_block=100, quote_block=100, block_lag=0,
            same_state_class="same_block",
            best_backrun_net_bps=-5.0,
            reject_reason=REJECT_GAS_EXCEEDS_GROSS,
            low_lag_scoring_path="registry_direct",
            local_pricing_attempted=True,
            local_pricing_used=True,
            registry_pools_found=3,
            registry_pools_active=2,
        )

    def _make_result_low_lag_coverage(self, eid="e2"):
        return BackrunResult(
            event_id=eid, event_source="live",
            event_type="uniswap_v3_swap", post_trade_state_used="live",
            backrun_direction="buy_depressed",
            event_block=100, quote_block=101, block_lag=1,
            same_state_class="next_block",
            reject_reason=REJECT_UNSUPPORTED_ADAPTER,
        )

    def _make_result_stale(self, eid="e3"):
        return BackrunResult(
            event_id=eid, event_source="live",
            event_type="uniswap_v3_swap", post_trade_state_used="live",
            backrun_direction="buy_depressed",
            event_block=100, quote_block=110, block_lag=10,
            same_state_class="stale",
            reject_reason=REJECT_NO_COUNTER_POOL,
        )

    def test_artifact_has_m7a523_metrics(self):
        from m7.orderflow.artifacts import build_replay_summary

        events = [self._make_event("e1"), self._make_event("e2"), self._make_event("e3")]
        results = [
            self._make_result_low_lag_registry_direct("e1"),
            self._make_result_low_lag_coverage("e2"),
            self._make_result_stale("e3"),
        ]
        art = build_replay_summary(events, results, mode="ws_live")

        assert "m7a523_low_lag_fast_path" in art
        fp = art["m7a523_low_lag_fast_path"]
        assert fp["low_lag_registry_direct_count"] == 1
        # REJECT_GAS_EXCEEDS_GROSS is not in UNSCORED_REJECTS → scored
        assert fp["low_lag_registry_direct_scored_count"] == 1

    def test_artifact_zero_registry_direct_when_all_stale(self):
        from m7.orderflow.artifacts import build_replay_summary

        events = [self._make_event("e1")]
        results = [self._make_result_stale("e1")]
        art = build_replay_summary(events, results, mode="ws_live")

        fp = art["m7a523_low_lag_fast_path"]
        assert fp["low_lag_registry_direct_count"] == 0
        assert fp["low_lag_registry_direct_scored_count"] == 0

    def test_low_lag_scored_count_includes_registry_direct(self):
        """Registry-direct events with non-unscored reject count as scored."""
        from m7.orderflow.artifacts import build_replay_summary

        events = [self._make_event("e1")]
        results = [self._make_result_low_lag_registry_direct("e1")]
        art = build_replay_summary(events, results, mode="ws_live")

        assert art["events_detected_low_lag"] == 1
        assert art["events_scored_low_lag"] == 1


# ── Non-low-lag events unchanged ───────────────────────────────────


class TestNonLowLagUnchanged:
    """Verify stale events still don't get registry-direct path."""

    def test_stale_result_has_no_scoring_path(self):
        r = BackrunResult(
            event_id="e1", event_source="live",
            event_type="uniswap_v3_swap", post_trade_state_used="live",
            backrun_direction="buy_depressed",
            event_block=100, quote_block=110, block_lag=10,
            same_state_class="stale",
        )
        assert r.low_lag_scoring_path is None

    def test_reject_reasons_unchanged(self):
        """ALL_REJECT_REASONS count must remain 20."""
        assert len(ALL_REJECT_REASONS) == 20

    def test_unscored_rejects_unchanged(self):
        """UNSCORED_REJECTS count must remain 12."""
        assert len(UNSCORED_REJECTS) == 12

    def test_gas_exceeds_gross_is_scored(self):
        """GAS_EXCEEDS_GROSS should NOT be in UNSCORED_REJECTS."""
        assert REJECT_GAS_EXCEEDS_GROSS not in UNSCORED_REJECTS


# ── Session low-lag pair tracking contract ──────────────────────────


class TestSessionLowLagPairTracking:
    """Verify the session-persistent low-lag pair accumulation logic."""

    def test_pair_tracking_accumulates(self):
        """Simulate the accumulation logic from mode_ws_live.py."""
        pairs: dict = {}
        # First event for this pair
        pair_key = "WETH/USDC"
        if pair_key not in pairs:
            pairs[pair_key] = {
                "pair": pair_key,
                "first_block": 100,
                "last_block": 100,
                "seen_count": 1,
                "scored_count": 1,
                "registry_direct_count": 1,
            }
        # Second event for same pair
        entry = pairs[pair_key]
        entry["seen_count"] += 1
        entry["last_block"] = max(entry["last_block"], 105)
        entry["scored_count"] += 1
        entry["registry_direct_count"] += 1

        assert entry["seen_count"] == 2
        assert entry["first_block"] == 100
        assert entry["last_block"] == 105
        assert entry["scored_count"] == 2
        assert entry["registry_direct_count"] == 2

    def test_pair_tracking_different_pairs(self):
        """Multiple distinct pairs tracked independently."""
        pairs: dict = {}
        for pk in ["WETH/USDC", "ARB/WETH", "WETH/USDC"]:
            if pk not in pairs:
                pairs[pk] = {"pair": pk, "seen_count": 0}
            pairs[pk]["seen_count"] += 1

        assert len(pairs) == 2
        assert pairs["WETH/USDC"]["seen_count"] == 2
        assert pairs["ARB/WETH"]["seen_count"] == 1
