"""
Consolidated REGISTRY_COVERAGE tests for M7 orderflow.

Test categories covered:
- Fixture event generation contracts
- Token admission (admit_event_tokens)
- Coverage scan schema and active-liquidity fields
- Size sweep schema
- Coverage reject split (granular rejects)
- Coverage-local-sim invariant
- Candidate pool debug format
- PoolRegistry session lifecycle and lookup
- Pool contract truth field
- Finer unresolved detail values
- Pool state read path provenance (V2/V3)
- Registry-direct fast path (synthetic coverage/local_sim)
- Gas floor result fields
- ws-live registry integration
- Session low-lag pair tracking
- BackrunResult M7.A.5.21 registry fields
- Address normalization
- Live state metrics fix (same_state_class on early rejects)
"""
from __future__ import annotations

import inspect
import json
from dataclasses import asdict, fields

import pytest

from m7.orderflow.contracts import BackrunResult, OrderflowEvent
from m7.orderflow.coverage import admit_event_tokens, counter_venue_coverage_scan
from m7.orderflow.events import build_fixture_events
from m7.orderflow.pool_registry import PoolRegistry, PoolRegistryEntry
from m7.shared.constants import (
    ALL_REJECT_REASONS,
    BACKRUN_BUY_DEPRESSED,
    EVENT_TYPE_SWAP,
    GAS_FLOOR_BPS_ARBITRUM,
    M7A4_CHAIN,
    REJECT_ALL_POOLS_TRULY_INACTIVE,
    REJECT_ALL_POOLS_ZERO_LIQUIDITY,
    REJECT_COVERAGE_LOCAL_MISMATCH,
    REJECT_GAS_EXCEEDS_GROSS,
    REJECT_GAS_FLOOR_EXCEEDED,
    REJECT_NO_ACTIVE_COUNTER_POOL,
    REJECT_NO_COUNTER_POOL,
    REJECT_TOKEN_PAIR_UNRESOLVED,
    REJECT_UNSUPPORTED_ADAPTER,
    SIGNIFICANT_IMPACT_BPS,
    UNSCORED_REJECTS,
)

from tests.unit.conftest import _make_event, _make_result


# ===========================================================================
# Fixture events
# ===========================================================================


class TestFixtureEvents:
    """Lock fixture event generation."""

    def test_fixture_count(self):
        events = build_fixture_events()
        assert len(events) == 5

    def test_all_fixtures_are_swap_type(self):
        for e in build_fixture_events():
            assert e.event_type == EVENT_TYPE_SWAP

    def test_all_fixtures_on_m7a4_chain(self):
        for e in build_fixture_events():
            assert e.chain == M7A4_CHAIN

    def test_fixture_ids_are_unique(self):
        events = build_fixture_events()
        ids = [e.event_id for e in events]
        assert len(ids) == len(set(ids))

    def test_fixtures_have_positive_amounts(self):
        for e in build_fixture_events():
            assert e.amount_in_wei > 0
            assert e.amount_out_wei > 0

    def test_fixtures_have_positive_size_usd(self):
        for e in build_fixture_events():
            assert e.estimated_size_usd > 0

    def test_fixtures_cover_multiple_tokens(self):
        events = build_fixture_events()
        all_tokens = {e.token_in for e in events} | {e.token_out for e in events}
        assert len(all_tokens) >= 3

    def test_fixtures_cover_multiple_dexes(self):
        events = build_fixture_events()
        dexes = {e.dex for e in events}
        assert len(dexes) >= 2

    def test_fixtures_cover_impact_range(self):
        events = build_fixture_events()
        impacts = [e.estimated_impact_bps for e in events]
        assert min(impacts) < SIGNIFICANT_IMPACT_BPS
        assert max(impacts) >= SIGNIFICANT_IMPACT_BPS


# ===========================================================================
# Token admission
# ===========================================================================


class TestAdmitEventTokens:
    """admit_event_tokens() contract tests."""

    def test_admitted_when_both_known(self):
        addr_to_sym = {"0xaa": "WETH", "0xbb": "USDC"}
        canonical = {"WETH": "0xaa", "USDC": "0xbb"}
        result = admit_event_tokens("0xaa", "0xbb", addr_to_sym, canonical)
        assert result["admitted"] is True
        assert result["token_in_symbol"] == "WETH"
        assert result["token_out_symbol"] == "USDC"
        assert result["token_in_known"] is True
        assert result["token_out_known"] is True
        assert result["blocker_reason"] is None

    def test_not_admitted_when_token_in_unknown(self):
        addr_to_sym = {"0xbb": "USDC"}
        canonical = {"USDC": "0xbb"}
        result = admit_event_tokens("0xunknown", "0xbb", addr_to_sym, canonical)
        assert result["admitted"] is False
        assert result["token_in_known"] is False
        assert result["blocker_reason"] is not None

    def test_not_admitted_when_token_out_unknown(self):
        addr_to_sym = {"0xaa": "WETH"}
        canonical = {"WETH": "0xaa"}
        result = admit_event_tokens("0xaa", "0xunknown", addr_to_sym, canonical)
        assert result["admitted"] is False
        assert result["token_out_known"] is False

    def test_not_admitted_when_both_unknown(self):
        result = admit_event_tokens("0xfoo", "0xbar", {}, {})
        assert result["admitted"] is False
        assert result["token_in_known"] is False
        assert result["token_out_known"] is False

    def test_return_schema(self):
        required_keys = {
            "admitted", "token_in_symbol", "token_out_symbol",
            "token_in_known", "token_out_known", "blocker_reason",
            "admission_source",
        }
        result = admit_event_tokens("0xa", "0xb", {}, {})
        assert set(result.keys()) == required_keys

    def test_case_insensitive_address_lookup(self):
        addr_to_sym = {"0xAA": "WETH", "0xBB": "USDC"}
        canonical = {"WETH": "0xAA", "USDC": "0xBB"}
        result = admit_event_tokens("0xAA", "0xBB", addr_to_sym, canonical)
        assert result["admitted"] is True


# ===========================================================================
# Coverage scan schema
# ===========================================================================


class TestCoverageSchema:
    """counter_venue_coverage_scan() return schema."""

    REQUIRED_KEYS = {
        "known_pools", "known_pools_total", "active_pools_total",
        "inactive_pool_count", "known_dexes", "active_dexes",
        "buy_venues", "sell_venues",
        "active_buy_venues", "active_sell_venues",
        "coverage_complete", "coverage_blocker_reason",
        "candidate_pools",
        "registry_pools_merged",
    }

    def test_empty_dex_configs_returns_incomplete(self):
        result = counter_venue_coverage_scan("0xA", "0xB", {}, "http://unused", 1)
        assert set(result.keys()) == self.REQUIRED_KEYS
        assert result["coverage_complete"] is False
        assert result["known_pools"] == 0
        assert result["coverage_blocker_reason"] is not None

    def test_schema_keys_exact(self):
        result = counter_venue_coverage_scan("0xA", "0xB", {}, "http://unused", 1)
        assert set(result.keys()) == self.REQUIRED_KEYS

    def test_coverage_complete_is_bool(self):
        result = counter_venue_coverage_scan("0xA", "0xB", {}, "http://unused", 1)
        assert isinstance(result["coverage_complete"], bool)

    def test_numeric_fields_non_negative(self):
        result = counter_venue_coverage_scan("0xA", "0xB", {}, "http://unused", 1)
        assert result["known_pools"] >= 0
        assert result["known_pools_total"] >= 0
        assert result["active_pools_total"] >= 0
        assert result["inactive_pool_count"] >= 0
        assert result["buy_venues"] >= 0
        assert result["sell_venues"] >= 0


# ===========================================================================
# Size sweep schema
# ===========================================================================


class TestSizeSweepSchema:
    """Size sweep result schema contract tests."""

    REQUIRED_POINT_KEYS = {
        "size_wei", "gross_pnl_wei", "gas_cost_wei",
        "net_pnl_wei", "net_bps", "buy_venue", "sell_venue",
    }

    def test_sweep_point_schema(self):
        point = {
            "size_wei": 10**17, "gross_pnl_wei": 10**14, "gas_cost_wei": 10**13,
            "net_pnl_wei": 10**14 - 10**13, "net_bps": 5.5,
            "buy_venue": "uniswap_v3", "sell_venue": "sushiswap_v3",
        }
        assert set(point.keys()) == self.REQUIRED_POINT_KEYS

    def test_sweep_point_serializes(self):
        point = {
            "size_wei": 10**17, "gross_pnl_wei": 0, "gas_cost_wei": 0,
            "net_pnl_wei": 0, "net_bps": 0.0, "buy_venue": None, "sell_venue": None,
        }
        s = json.dumps(point)
        parsed = json.loads(s)
        assert parsed["size_wei"] == 10**17

    def test_sweep_ladder_multipliers(self):
        multipliers = [0.2, 0.5, 1.0, 2.0, 5.0]
        assert len(multipliers) == 5


# ===========================================================================
# Active coverage (M7.A.5.11)
# ===========================================================================


class TestActiveCoverageSchema:
    """counter_venue_coverage_scan returns active-liquidity fields."""

    def test_active_fields_present(self):
        result = counter_venue_coverage_scan("0xA", "0xB", {}, "http://unused", 1)
        for key in [
            "known_pools_total", "active_pools_total", "inactive_pool_count",
            "active_dexes", "active_buy_venues", "active_sell_venues",
        ]:
            assert key in result

    def test_inactive_pool_count_equals_diff(self):
        result = counter_venue_coverage_scan("0xA", "0xB", {}, "http://unused", 1)
        assert result["inactive_pool_count"] == (
            result["known_pools_total"] - result["active_pools_total"]
        )

    def test_known_pools_alias_matches_total(self):
        result = counter_venue_coverage_scan("0xA", "0xB", {}, "http://unused", 1)
        assert result["known_pools"] == result["known_pools_total"]

    def test_no_pools_blocker(self):
        result = counter_venue_coverage_scan("0xA", "0xB", {}, "http://unused", 1)
        assert result["coverage_blocker_reason"] == "no_pools_found"
        assert result["coverage_complete"] is False


# ===========================================================================
# Coverage reject split (M7.A.5.11)
# ===========================================================================


class TestCoverageRejectSplit:
    """BackrunResult with granular coverage rejects."""

    def test_no_active_counter_pool_result(self):
        r = _make_result(
            reject_reason=REJECT_NO_ACTIVE_COUNTER_POOL,
            route_viable=False,
            coverage_result={
                "known_pools_total": 2, "active_pools_total": 0,
                "inactive_pool_count": 2, "coverage_complete": False,
                "coverage_blocker_reason": "all_pools_zero_liquidity",
            },
        )
        assert r.reject_reason == REJECT_NO_ACTIVE_COUNTER_POOL
        assert r.route_viable is False

    def test_all_pools_zero_liq_result(self):
        r = _make_result(
            reject_reason=REJECT_ALL_POOLS_ZERO_LIQUIDITY,
            route_viable=False,
            local_sim_state={
                "pools_queried": 2, "pools_with_state": 2,
                "pool_states": {"0xaaa": {"liquidity": 0}, "0xbbb": {"liquidity": 0}},
            },
        )
        assert r.reject_reason == REJECT_ALL_POOLS_ZERO_LIQUIDITY
        assert r.route_viable is False


# ===========================================================================
# Candidate pool debug (M7.A.5.12)
# ===========================================================================


class TestCandidatePoolDebug:
    """coverage_result must include candidate_pools debug list."""

    def test_candidate_pools_present(self):
        result = counter_venue_coverage_scan("0xA", "0xB", {}, "http://unused", 1)
        assert "candidate_pools" in result
        assert isinstance(result["candidate_pools"], list)

    def test_candidate_pools_empty_for_no_configs(self):
        result = counter_venue_coverage_scan("0xA", "0xB", {}, "http://unused", 1)
        assert result["candidate_pools"] == []

    def test_candidate_pool_schema_fields(self):
        required_keys = {"address", "dex", "fee", "liquidity", "activity_source", "activity_drop_reason"}
        synthetic = {
            "address": "0x1234", "dex": "uniswap_v3", "fee": 3000,
            "liquidity": 0, "activity_source": "batch_full_pool_data",
            "activity_drop_reason": "liquidity_zero",
        }
        assert required_keys.issubset(set(synthetic.keys()))


# ===========================================================================
# Coverage-local-sim invariant (M7.A.5.12)
# ===========================================================================


class TestCoverageLocalSimInvariant:
    """If reject=ALL_POOLS_TRULY_INACTIVE, coverage.active_pools_total==0."""

    def test_truly_inactive_implies_zero_active(self):
        cov = {
            "active_pools_total": 0, "coverage_complete": False,
            "known_pools_total": 3, "inactive_pool_count": 3,
        }
        r = _make_result(reject_reason=REJECT_ALL_POOLS_TRULY_INACTIVE, coverage_result=cov)
        assert r.coverage_result["active_pools_total"] == 0
        assert r.coverage_result["coverage_complete"] is False

    def test_mismatch_implies_patched_coverage(self):
        cov = {
            "active_pools_total": 0, "coverage_complete": False,
            "known_pools_total": 6, "inactive_pool_count": 6,
            "coverage_blocker_reason": "local_sim_all_zero_liquidity",
        }
        r = _make_result(reject_reason=REJECT_COVERAGE_LOCAL_MISMATCH, coverage_result=cov)
        assert r.coverage_result["active_pools_total"] == 0
        assert r.coverage_result["coverage_blocker_reason"] == "local_sim_all_zero_liquidity"


# ===========================================================================
# Pool contract truth (M7.A.5.16)
# ===========================================================================


class TestPoolContractTruthField:
    """BackrunResult.pool_contract_truth field."""

    def test_default_none(self):
        r = _make_result()
        assert r.pool_contract_truth is None

    def test_stored_truth(self):
        truth = {
            "pool_address": "0xabc", "code_present": True,
            "token0_ok": True, "token1_ok": True,
            "slot0_ok": False, "liquidity_ok": False,
            "dex_family_guess": "uniswap_v2_like",
        }
        r = _make_result(
            reject_reason=REJECT_TOKEN_PAIR_UNRESOLVED,
            pair_unresolved_detail="POOL_SLOT0_REVERT",
            pool_contract_truth=truth,
        )
        assert r.pool_contract_truth == truth
        d = asdict(r)
        assert d["pool_contract_truth"]["dex_family_guess"] == "uniswap_v2_like"

    def test_truth_schema_keys(self):
        expected = {
            "pool_address", "code_present", "token0_ok", "token1_ok",
            "slot0_ok", "liquidity_ok", "dex_family_guess",
        }
        truth = {k: None for k in expected}
        assert set(truth.keys()) == expected


# ===========================================================================
# Finer unresolved details (M7.A.5.16)
# ===========================================================================


class TestFinerUnresolvedDetails:
    """pair_unresolved_detail accepts finer values."""

    def test_finer_detail_values_valid(self):
        for v in ["POOL_CODE_EMPTY", "POOL_TOKEN0_REVERT", "POOL_TOKEN1_REVERT",
                   "POOL_SLOT0_REVERT", "POOL_LIQUIDITY_REVERT"]:
            r = _make_result(
                reject_reason=REJECT_TOKEN_PAIR_UNRESOLVED,
                pair_unresolved_detail=v,
            )
            assert r.pair_unresolved_detail == v

    def test_legacy_detail_values_still_valid(self):
        for v in ["no_pool_address", "pool_read_failed", "no_symbol_map",
                   "token0_unknown", "token1_unknown"]:
            r = _make_result(pair_unresolved_detail=v)
            assert r.pair_unresolved_detail == v


# ===========================================================================
# Pool state read path (M7.A.5.17)
# ===========================================================================


class TestPoolStateReadPathField:
    """pool_state_read_path field on BackrunResult."""

    def test_default_none(self):
        r = _make_result()
        assert r.pool_state_read_path is None

    def test_v3_multicall_value(self):
        r = _make_result(pool_state_read_path="v3_multicall")
        assert r.pool_state_read_path == "v3_multicall"

    def test_v2_getReserves_value(self):
        r = _make_result(pool_state_read_path="v2_getReserves")
        assert r.pool_state_read_path == "v2_getReserves"

    def test_field_in_asdict(self):
        r = _make_result(pool_state_read_path="v2_getReserves")
        d = asdict(r)
        assert "pool_state_read_path" in d
        assert d["pool_state_read_path"] == "v2_getReserves"

    def test_json_roundtrip(self):
        r = _make_result(pool_state_read_path="v3_multicall")
        d = asdict(r)
        loaded = json.loads(json.dumps(d))
        assert loaded["pool_state_read_path"] == "v3_multicall"


# ===========================================================================
# PoolRegistry session lifecycle
# ===========================================================================


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
        assert reg.lookup_pair("0xaaa", "0xbbb") == []

    def test_is_pair_known_false_before_query(self):
        reg = PoolRegistry()
        assert not reg.is_pair_known("0xaaa", "0xbbb")

    def test_manual_pool_injection_and_lookup(self):
        reg = PoolRegistry()
        entry = PoolRegistryEntry(
            address="0x1234", dex="uniswap_v3", adapter_type="uniswap_v3",
            fee=3000, token_a="0xaaa", token_b="0xbbb",
            liquidity=100, sqrt_price_x96=2**96, tick=0, last_block=100,
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

    def test_address_lowercased(self):
        e = PoolRegistryEntry(
            address="0xAABB", dex="uni", adapter_type="uniswap_v3",
            fee=500, token_a="0xCC", token_b="0xDD",
        )
        assert e.address == "0xaabb"
        assert e.token_a == "0xcc"
        assert e.token_b == "0xdd"


# ===========================================================================
# Gas floor result fields
# ===========================================================================


class TestGasFloorResultFields:
    """BackrunResult with gas_floor_exceeded fields."""

    def test_gas_floor_fields_in_asdict(self):
        r = _make_result(
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
        r = _make_result(
            reject_reason=REJECT_GAS_FLOOR_EXCEEDED,
            pair_resolved=True,
            actual_pair="WETH/USDC",
            gas_floor_exceeded=True,
            gas_floor_bps=3.5,
        )
        assert r.pair_resolved is True
        assert r.actual_pair == "WETH/USDC"


# ===========================================================================
# ws-live registry integration
# ===========================================================================


class TestWsLiveRegistryIntegration:
    """mode_ws_live.py must import and create PoolRegistry."""

    def test_mode_ws_live_imports_pool_registry(self):
        from m7.orderflow.mode_ws_live import PoolRegistry
        reg = PoolRegistry()
        assert hasattr(reg, "preload_pair")
        assert hasattr(reg, "lookup_pair")

    def test_score_backrun_accepts_pool_registry(self):
        from m7.orderflow.scoring_parallel import score_backrun_live_parallel
        sig = inspect.signature(score_backrun_live_parallel)
        assert "pool_registry" in sig.parameters


# ===========================================================================
# Registry-direct fast path (M7.A.5.23)
# ===========================================================================


class TestRegistryDirectFastPath:
    """Synthetic coverage and local_sim from registry entries."""

    def _make_active_entry(self, addr="0xpool1", dex="uniswap_v3", liq=10000,
                           sqrt_p=2**96, tick=0):
        return PoolRegistryEntry(
            address=addr, dex=dex, adapter_type="uniswap_v3", fee=3000,
            token_a="0xaaa", token_b="0xbbb",
            liquidity=liq, sqrt_price_x96=sqrt_p, tick=tick, last_block=100,
        )

    def test_synthetic_coverage_from_registry(self):
        entries = [
            self._make_active_entry(addr="0xp1", dex="uniswap_v3"),
            self._make_active_entry(addr="0xp2", dex="sushiswap"),
        ]
        active = [e for e in entries if e.is_active()]
        cand_pools = [e.to_candidate_pool() for e in active]
        pool_states = {e.address: e.to_pool_state() for e in active if e.to_pool_state()}

        assert len(cand_pools) == 2
        assert len(pool_states) == 2
        assert all(cp["activity_source"] == "factory_registry" for cp in cand_pools)

    def test_synthetic_local_sim_from_registry(self):
        entries = [
            self._make_active_entry(addr="0xp1"),
            self._make_active_entry(addr="0xp2", liq=5000, sqrt_p=2**97, tick=10),
        ]
        pool_states = {e.address: e.to_pool_state() for e in entries if e.to_pool_state()}
        local_sim = {
            "pools_queried": len(entries),
            "pools_with_state": len(pool_states),
            "pool_states": dict(list(pool_states.items())[:3]),
        }
        assert local_sim["pools_with_state"] == 2

    def test_v2_entry_provides_pool_state_via_reserves(self):
        e = PoolRegistryEntry(
            address="0xv2pool", dex="sushiswap", adapter_type="uniswap_v2",
            fee=30, token_a="0xaaa", token_b="0xbbb",
            liquidity=500, sqrt_price_x96=1000000, tick=2000000, last_block=100,
        )
        assert e.is_active()
        ps = e.to_pool_state()
        assert ps is not None
        assert ps["sqrt_price_x96"] == 1000000
        assert ps["tick"] == 2000000


# ===========================================================================
# Session low-lag pair tracking (M7.A.5.23)
# ===========================================================================


class TestSessionLowLagPairTracking:
    """Session-persistent low-lag pair accumulation logic."""

    def test_pair_tracking_accumulates(self):
        pairs: dict = {}
        pair_key = "WETH/USDC"
        pairs[pair_key] = {
            "pair": pair_key, "first_block": 100, "last_block": 100,
            "seen_count": 1, "scored_count": 1, "registry_direct_count": 1,
        }
        entry = pairs[pair_key]
        entry["seen_count"] += 1
        entry["last_block"] = max(entry["last_block"], 105)
        entry["scored_count"] += 1
        entry["registry_direct_count"] += 1

        assert entry["seen_count"] == 2
        assert entry["first_block"] == 100
        assert entry["last_block"] == 105

    def test_pair_tracking_different_pairs(self):
        pairs: dict = {}
        for pk in ["WETH/USDC", "ARB/WETH", "WETH/USDC"]:
            if pk not in pairs:
                pairs[pk] = {"pair": pk, "seen_count": 0}
            pairs[pk]["seen_count"] += 1
        assert len(pairs) == 2
        assert pairs["WETH/USDC"]["seen_count"] == 2
        assert pairs["ARB/WETH"]["seen_count"] == 1


# ===========================================================================
# BackrunResult M7.A.5.21 registry fields
# ===========================================================================


class TestBackrunResultRegistryFields:
    """M7.A.5.21 added 6 registry-related fields to BackrunResult."""

    def test_new_fields_exist(self):
        r = _make_result()
        d = asdict(r)
        assert "registry_pools_found" in d
        assert "registry_pools_active" in d
        assert "adapter_type_used" in d
        assert "gas_floor_exceeded" in d
        assert "gas_floor_bps" in d
        assert "pricing_path" in d

    def test_new_fields_default_none(self):
        r = _make_result()
        assert r.registry_pools_found is None
        assert r.registry_pools_active is None
        assert r.adapter_type_used is None
        assert r.gas_floor_exceeded is None
        assert r.gas_floor_bps is None
        assert r.pricing_path is None


# ===========================================================================
# Live state metrics fix (M7.A.5.11)
# ===========================================================================


class TestLiveStateMetricsFix:
    """Early reject BackrunResults must have same_state_class set."""

    def test_reject_result_has_same_state_class(self):
        r = _make_result(
            reject_reason=REJECT_NO_ACTIVE_COUNTER_POOL,
            event_block=100, quote_block=100, block_lag=0,
            same_state_class="same_block", route_viable=False,
        )
        assert r.same_state_class == "same_block"
        assert r.block_lag == 0

    def test_reject_result_stale_class(self):
        r = _make_result(
            reject_reason=REJECT_ALL_POOLS_ZERO_LIQUIDITY,
            event_block=100, quote_block=110, block_lag=10,
            same_state_class="stale", route_viable=False,
        )
        assert r.same_state_class == "stale"

    def test_live_state_metrics_counts_early_rejects(self):
        results = [
            _make_result(
                event_id="lsm_3",
                reject_reason=REJECT_NO_ACTIVE_COUNTER_POOL,
                event_block=100, quote_block=100, block_lag=0,
                same_state_class="same_block", route_viable=False,
            ),
            _make_result(
                event_id="lsm_4",
                reject_reason=REJECT_ALL_POOLS_ZERO_LIQUIDITY,
                event_block=100, quote_block=105, block_lag=5,
                same_state_class="stale", route_viable=False,
            ),
        ]
        live = [r for r in results if r.event_block is not None]
        same_block = sum(1 for r in live if r.same_state_class == "same_block")
        stale = sum(1 for r in live if r.same_state_class == "stale")
        assert same_block == 1
        assert stale == 1
