"""
Consolidated CONTRACTS_CORE tests for M7 orderflow.

Locks the core contracts that must never break:
- BackrunResult field count (66) and schema
- OrderflowEvent schema and validation
- IntentSurfaceAssessment schema
- Reject reason constants (ALL_REJECT_REASONS=21, UNSCORED_REJECTS=12)
- Blocker tag constants (ALL_BLOCKER_TAGS=8)
- Event type and surface constants
- Admission source constants
- scoring_path field contract
- PRICING_ANOMALY reject constant
- PoolRegistryEntry basic contracts
"""
from __future__ import annotations

import json
from dataclasses import asdict, fields

import pytest

from m7.orderflow.contracts import (
    BackrunResult,
    OrderflowEvent,
    IntentSurfaceAssessment,
)
from m7.orderflow.pool_registry import PoolRegistry, PoolRegistryEntry
from m7.shared.constants import (
    ALL_ADMISSION_SOURCES,
    ALL_BLOCKER_TAGS,
    ALL_EVENT_TYPES,
    ALL_REJECT_REASONS,
    ALL_SURFACES,
    ADMISSION_ADDR_TO_SYMBOL,
    ADMISSION_CANONICAL,
    ADMISSION_ONCHAIN_ENRICHED,
    ADMISSION_REJECTED,
    ADMISSION_SUBGRAPH_VERIFIED,
    BACKRUN_BUY_DEPRESSED,
    BLOCKER_GAS_L1_DATA_DOMINANT,
    BLOCKER_LOW_LAG_INACTIVE_POOL,
    BLOCKER_LOW_LAG_NONE_THIS_WINDOW,
    BLOCKER_LOW_LAG_NO_COUNTER_POOL,
    BLOCKER_LOW_LAG_REMOTE_QUOTER_LATENCY,
    BLOCKER_LOW_LAG_COMPLETION_LATENCY,
    BLOCKER_LOW_LAG_RPC_QUOTE_FAIL,
    BLOCKER_LOW_LAG_V2_UNSUPPORTED,
    BLOCKER_SUBGRAPH_API_KEY_REQUIRED,
    EVENT_TYPE_LARGE_TRANSFER,
    EVENT_TYPE_POOL_REBALANCE,
    EVENT_TYPE_SWAP,
    GAS_FLOOR_BPS_ARBITRUM,
    M7A4_CHAIN,
    REJECT_ALL_POOLS_TRULY_INACTIVE,
    REJECT_ALL_POOLS_ZERO_LIQUIDITY,
    REJECT_COVERAGE_LOCAL_MISMATCH,
    REJECT_EVENT_TOO_SMALL,
    REJECT_GAS_EXCEEDS_GROSS,
    REJECT_GAS_FLOOR_EXCEEDED,
    REJECT_INSUFFICIENT_IMPACT,
    REJECT_NO_ACTIVE_COUNTER_POOL,
    REJECT_NO_COUNTER_POOL,
    REJECT_NO_COUNTER_VENUE,
    REJECT_PAIR_RESOLVED_UNTRADEABLE,
    REJECT_PRICING_ANOMALY,
    REJECT_QUOTE_FAILURE,
    REJECT_RPC_QUOTE_FAIL,
    REJECT_SAME_BLOCK_IMPOSSIBLE,
    REJECT_SLIPPAGE_EXCEEDS_GROSS,
    REJECT_STALE_POSITIVE,
    REJECT_TOKEN_NOT_ADMITTED,
    REJECT_TOKEN_PAIR_UNRESOLVED,
    REJECT_UNSUPPORTED_ADAPTER,
    REJECT_ZERO_LIQUIDITY,
    SURFACE_BLOCK_BACKRUN,
    SURFACE_COW_SOLVER,
    SURFACE_MEV_SHARE_BACKRUN,
    SURFACE_UNISWAPX_FILLER,
    UNSCORED_REJECTS,
)

from tests.unit.conftest import _make_event, _make_result


# ===========================================================================
# Canonical count invariants (ONE test per constant — deduplicated)
# ===========================================================================


class TestContractCoreInvariants:
    """Canonical count assertions for all core contract invariants."""

    def test_backrun_result_field_count_is_66(self):
        assert len(fields(BackrunResult)) == 78

    def test_all_reject_reasons_count_is_21(self):
        assert len(ALL_REJECT_REASONS) == 21

    def test_unscored_rejects_count_is_12(self):
        assert len(UNSCORED_REJECTS) == 12

    def test_all_blocker_tags_count_is_9(self):
        assert len(ALL_BLOCKER_TAGS) == 9

    def test_all_event_types_count_is_3(self):
        assert len(ALL_EVENT_TYPES) == 3
        assert EVENT_TYPE_SWAP in ALL_EVENT_TYPES
        assert EVENT_TYPE_LARGE_TRANSFER in ALL_EVENT_TYPES
        assert EVENT_TYPE_POOL_REBALANCE in ALL_EVENT_TYPES

    def test_all_surfaces_count_is_4(self):
        assert len(ALL_SURFACES) == 4
        assert SURFACE_MEV_SHARE_BACKRUN in ALL_SURFACES
        assert SURFACE_UNISWAPX_FILLER in ALL_SURFACES
        assert SURFACE_COW_SOLVER in ALL_SURFACES
        assert SURFACE_BLOCK_BACKRUN in ALL_SURFACES

    def test_all_admission_sources_count_is_5(self):
        assert len(ALL_ADMISSION_SOURCES) == 5


# ===========================================================================
# OrderflowEvent schema
# ===========================================================================


class TestOrderflowEventSchema:
    """Lock OrderflowEvent creation, validation, and field contracts."""

    def test_valid_swap_event(self):
        e = _make_event()
        assert e.event_type == "swap"
        assert e.chain == "arbitrum_one"
        assert e.amount_in_wei > 0

    def test_valid_large_transfer_event(self):
        e = _make_event(event_type=EVENT_TYPE_LARGE_TRANSFER)
        assert e.event_type == EVENT_TYPE_LARGE_TRANSFER

    def test_valid_pool_rebalance_event(self):
        e = _make_event(event_type=EVENT_TYPE_POOL_REBALANCE)
        assert e.event_type == EVENT_TYPE_POOL_REBALANCE

    def test_invalid_event_type_raises(self):
        with pytest.raises(ValueError, match="Unknown event_type"):
            _make_event(event_type="unknown_type")

    def test_event_asdict_keys(self):
        e = _make_event()
        d = asdict(e)
        required = {
            "event_id", "event_type", "chain", "block_number", "tx_hash",
            "token_in", "token_out", "amount_in_wei", "amount_out_wei",
            "dex", "pool_address", "fee_tier", "estimated_size_usd",
            "estimated_impact_bps", "timestamp",
        }
        assert required.issubset(set(d.keys()))


# ===========================================================================
# BackrunResult schema
# ===========================================================================


class TestBackrunResultSchema:
    """Lock BackrunResult schema and required fields."""

    def test_default_backrun_result(self):
        r = _make_result()
        assert r.route_viable is False
        assert r.reject_reason is None
        assert r.best_backrun_net_bps == 0.0

    def test_backrun_result_has_all_artifact_fields(self):
        r = _make_result()
        d = asdict(r)
        required = {
            "event_id", "event_source", "event_type",
            "post_trade_state_used", "best_backrun_net_bps",
            "same_block_possible", "candidate_path",
            "route_viable", "reject_reason",
        }
        assert required.issubset(set(d.keys()))

    def test_reject_reasons_are_all_present(self):
        assert REJECT_NO_COUNTER_VENUE in ALL_REJECT_REASONS
        assert REJECT_GAS_EXCEEDS_GROSS in ALL_REJECT_REASONS
        assert REJECT_SLIPPAGE_EXCEEDS_GROSS in ALL_REJECT_REASONS
        assert REJECT_EVENT_TOO_SMALL in ALL_REJECT_REASONS
        assert REJECT_SAME_BLOCK_IMPOSSIBLE in ALL_REJECT_REASONS
        assert REJECT_TOKEN_PAIR_UNRESOLVED in ALL_REJECT_REASONS
        assert REJECT_QUOTE_FAILURE in ALL_REJECT_REASONS
        assert REJECT_INSUFFICIENT_IMPACT in ALL_REJECT_REASONS
        assert REJECT_NO_COUNTER_POOL in ALL_REJECT_REASONS
        assert REJECT_TOKEN_NOT_ADMITTED in ALL_REJECT_REASONS
        assert REJECT_UNSUPPORTED_ADAPTER in ALL_REJECT_REASONS
        assert REJECT_RPC_QUOTE_FAIL in ALL_REJECT_REASONS
        assert REJECT_PAIR_RESOLVED_UNTRADEABLE in ALL_REJECT_REASONS
        assert REJECT_STALE_POSITIVE in ALL_REJECT_REASONS
        assert REJECT_ZERO_LIQUIDITY in ALL_REJECT_REASONS
        assert REJECT_NO_ACTIVE_COUNTER_POOL in ALL_REJECT_REASONS
        assert REJECT_ALL_POOLS_ZERO_LIQUIDITY in ALL_REJECT_REASONS
        assert REJECT_COVERAGE_LOCAL_MISMATCH in ALL_REJECT_REASONS
        assert REJECT_ALL_POOLS_TRULY_INACTIVE in ALL_REJECT_REASONS
        assert REJECT_GAS_FLOOR_EXCEEDED in ALL_REJECT_REASONS
        assert REJECT_PRICING_ANOMALY in ALL_REJECT_REASONS

    def test_backrun_result_json_roundtrip(self):
        r = _make_result()
        s = json.dumps(asdict(r), default=str)
        parsed = json.loads(s)
        assert len(parsed) == 78
        assert parsed["event_id"] == "e1"


# ===========================================================================
# IntentSurfaceAssessment schema
# ===========================================================================


class TestIntentSurfaceSchema:
    """Lock IntentSurfaceAssessment schema and canonical surfaces."""

    def test_canonical_surfaces(self):
        assert SURFACE_MEV_SHARE_BACKRUN in ALL_SURFACES
        assert SURFACE_UNISWAPX_FILLER in ALL_SURFACES
        assert SURFACE_COW_SOLVER in ALL_SURFACES
        assert SURFACE_BLOCK_BACKRUN in ALL_SURFACES

    def test_assessment_schema_keys(self):
        a = IntentSurfaceAssessment(
            surface_type=SURFACE_BLOCK_BACKRUN,
            chain=M7A4_CHAIN,
            description="test",
            orderflow_accessible=True,
            execution_model="direct_arb",
            requires_private_inventory=False,
            requires_onchain_execution=True,
            latency_class="single_block",
            capital_requirement_class="low",
            quote_infra_ready=True,
            simulation_possible=True,
            current_repo_gap="none",
            feasibility_score="high",
            key_advantage="test",
            key_risk="test",
        )
        d = asdict(a)
        required = {
            "surface_type", "chain", "description",
            "orderflow_accessible", "execution_model",
            "requires_private_inventory", "requires_onchain_execution",
            "latency_class", "capital_requirement_class",
            "quote_infra_ready", "simulation_possible",
            "current_repo_gap", "feasibility_score",
            "key_advantage", "key_risk",
        }
        assert required == set(d.keys())


# ===========================================================================
# Admission source constants
# ===========================================================================


class TestAdmissionSourceConstants:
    def test_admission_source_values(self):
        assert ADMISSION_CANONICAL == "canonical_core"
        assert ADMISSION_ADDR_TO_SYMBOL == "addr_to_symbol"
        assert ADMISSION_SUBGRAPH_VERIFIED == "subgraph_seeded_verified"
        assert ADMISSION_REJECTED == "rejected_unverified"
        assert ADMISSION_ONCHAIN_ENRICHED == "onchain_enriched_verified"

    def test_all_admission_sources_is_frozenset(self):
        assert isinstance(ALL_ADMISSION_SOURCES, frozenset)

    def test_all_admission_sources_contains_all_constants(self):
        assert ADMISSION_CANONICAL in ALL_ADMISSION_SOURCES
        assert ADMISSION_ADDR_TO_SYMBOL in ALL_ADMISSION_SOURCES
        assert ADMISSION_SUBGRAPH_VERIFIED in ALL_ADMISSION_SOURCES
        assert ADMISSION_REJECTED in ALL_ADMISSION_SOURCES
        assert ADMISSION_ONCHAIN_ENRICHED in ALL_ADMISSION_SOURCES


# ===========================================================================
# Blocker tag constants
# ===========================================================================


class TestBlockerTagConstants:
    def test_all_blocker_tags_is_frozenset(self):
        assert isinstance(ALL_BLOCKER_TAGS, frozenset)

    def test_each_canonical_tag_in_set(self):
        expected = {
            BLOCKER_LOW_LAG_NONE_THIS_WINDOW,
            BLOCKER_LOW_LAG_NO_COUNTER_POOL,
            BLOCKER_LOW_LAG_V2_UNSUPPORTED,
            BLOCKER_LOW_LAG_INACTIVE_POOL,
            BLOCKER_LOW_LAG_REMOTE_QUOTER_LATENCY,
            BLOCKER_LOW_LAG_COMPLETION_LATENCY,
            BLOCKER_LOW_LAG_RPC_QUOTE_FAIL,
            BLOCKER_GAS_L1_DATA_DOMINANT,
            BLOCKER_SUBGRAPH_API_KEY_REQUIRED,
        }
        assert expected == ALL_BLOCKER_TAGS

    def test_blocker_constants_match_strings(self):
        assert BLOCKER_LOW_LAG_NONE_THIS_WINDOW == "LOW_LAG_NONE_THIS_WINDOW"
        assert BLOCKER_LOW_LAG_NO_COUNTER_POOL == "LOW_LAG_NO_COUNTER_POOL"
        assert BLOCKER_LOW_LAG_V2_UNSUPPORTED == "LOW_LAG_V2_UNSUPPORTED"
        assert BLOCKER_LOW_LAG_INACTIVE_POOL == "LOW_LAG_INACTIVE_POOL"
        assert BLOCKER_LOW_LAG_REMOTE_QUOTER_LATENCY == "LOW_LAG_REMOTE_QUOTER_LATENCY"
        assert BLOCKER_LOW_LAG_COMPLETION_LATENCY == "LOW_LAG_COMPLETION_LATENCY"
        assert BLOCKER_LOW_LAG_RPC_QUOTE_FAIL == "LOW_LAG_RPC_QUOTE_FAIL"
        assert BLOCKER_GAS_L1_DATA_DOMINANT == "GAS_L1_DATA_DOMINANT"
        assert BLOCKER_SUBGRAPH_API_KEY_REQUIRED == "SUBGRAPH_API_KEY_REQUIRED"


# ===========================================================================
# Unscored rejects membership
# ===========================================================================


class TestUnscoredRejectsMembership:
    def test_unscored_rejects_is_frozenset(self):
        assert isinstance(UNSCORED_REJECTS, frozenset)

    def test_unscored_rejects_exact_members(self):
        expected = {
            REJECT_TOKEN_PAIR_UNRESOLVED, REJECT_NO_COUNTER_POOL,
            REJECT_TOKEN_NOT_ADMITTED, REJECT_UNSUPPORTED_ADAPTER,
            REJECT_RPC_QUOTE_FAIL, REJECT_PAIR_RESOLVED_UNTRADEABLE,
            REJECT_ZERO_LIQUIDITY,
            REJECT_NO_ACTIVE_COUNTER_POOL, REJECT_ALL_POOLS_ZERO_LIQUIDITY,
            REJECT_COVERAGE_LOCAL_MISMATCH, REJECT_ALL_POOLS_TRULY_INACTIVE,
            REJECT_GAS_FLOOR_EXCEEDED,
        }
        assert UNSCORED_REJECTS == expected

    def test_gas_exceeds_gross_is_scored(self):
        assert REJECT_GAS_EXCEEDS_GROSS not in UNSCORED_REJECTS

    def test_stale_positive_is_scored(self):
        assert REJECT_STALE_POSITIVE not in UNSCORED_REJECTS

    def test_pricing_anomaly_is_scored(self):
        assert REJECT_PRICING_ANOMALY not in UNSCORED_REJECTS


# ===========================================================================
# scoring_path field contract (M7.A.5.23+)
# ===========================================================================


class TestScoringPathField:
    def test_scoring_path_exists_and_defaults_none(self):
        r = _make_result()
        assert hasattr(r, "scoring_path")
        assert r.scoring_path is None

    def test_scoring_path_settable(self):
        r = _make_result(scoring_path="registry_direct")
        assert r.scoring_path == "registry_direct"

    def test_scoring_path_in_asdict(self):
        r = _make_result(scoring_path="registry_direct")
        d = asdict(r)
        assert "scoring_path" in d
        assert d["scoring_path"] == "registry_direct"

    def test_old_field_name_does_not_exist(self):
        r = _make_result()
        assert not hasattr(r, "low_lag_scoring_path")


# ===========================================================================
# PRICING_ANOMALY reject constant (M7.A.5.25)
# ===========================================================================


class TestRejectPricingAnomaly:
    def test_pricing_anomaly_value(self):
        assert REJECT_PRICING_ANOMALY == "PRICING_ANOMALY"

    def test_pricing_anomaly_in_all_reject_reasons(self):
        assert REJECT_PRICING_ANOMALY in ALL_REJECT_REASONS

    def test_pricing_anomaly_not_in_unscored(self):
        assert REJECT_PRICING_ANOMALY not in UNSCORED_REJECTS

    def test_result_with_pricing_anomaly(self):
        r = _make_result(
            reject_reason=REJECT_PRICING_ANOMALY,
            route_viable=False,
            best_backrun_net_bps=154955.0,
        )
        assert r.reject_reason == "PRICING_ANOMALY"
        assert r.route_viable is False


# ===========================================================================
# PoolRegistryEntry basic contracts
# ===========================================================================


class TestPoolRegistryEntryContracts:
    def test_is_active_positive_liquidity(self):
        e = PoolRegistryEntry(
            address="0xpool", dex="uniswap_v3", adapter_type="uniswap_v3",
            fee=500, token_a="0xaaa", token_b="0xbbb", liquidity=1000,
        )
        assert e.is_active() is True

    def test_is_active_zero_liquidity(self):
        e = PoolRegistryEntry(
            address="0xpool", dex="uniswap_v3", adapter_type="uniswap_v3",
            fee=500, token_a="0xaaa", token_b="0xbbb", liquidity=0,
        )
        assert e.is_active() is False

    def test_is_active_none_liquidity(self):
        e = PoolRegistryEntry(
            address="0xpool", dex="uniswap_v3", adapter_type="uniswap_v3",
            fee=500, token_a="0xaaa", token_b="0xbbb", liquidity=None,
        )
        assert e.is_active() is False

    def test_to_candidate_pool_active(self):
        e = PoolRegistryEntry(
            address="0xpool", dex="uni", adapter_type="uniswap_v3",
            fee=500, token_a="0xaaa", token_b="0xbbb", liquidity=100,
        )
        cp = e.to_candidate_pool()
        assert cp["address"] == "0xpool"
        assert cp["fee"] == 500
        assert cp["activity_source"] == "factory_registry"
        assert cp["activity_drop_reason"] is None

    def test_to_candidate_pool_zero_liquidity(self):
        e = PoolRegistryEntry(
            address="0xpool", dex="uni", adapter_type="uniswap_v3",
            fee=500, token_a="0xaaa", token_b="0xbbb", liquidity=0,
        )
        cp = e.to_candidate_pool()
        assert cp["activity_drop_reason"] == "liquidity_zero"

    def test_to_pool_state_has_fields(self):
        e = PoolRegistryEntry(
            address="0xpool", dex="uni", adapter_type="uniswap_v3",
            fee=500, token_a="0xaaa", token_b="0xbbb",
            liquidity=100, sqrt_price_x96=999, tick=-10,
        )
        ps = e.to_pool_state()
        assert ps is not None
        assert ps["sqrt_price_x96"] == 999
        assert ps["tick"] == -10
        assert ps["liquidity"] == 100

    def test_to_pool_state_none_when_no_sqrt_price(self):
        e = PoolRegistryEntry(
            address="0xpool", dex="uni", adapter_type="uniswap_v3",
            fee=500, token_a="0xaaa", token_b="0xbbb",
            liquidity=100, sqrt_price_x96=0, tick=0,
        )
        assert e.to_pool_state() is None

    def test_v2_entry_provides_pool_state_via_reserves(self):
        e = PoolRegistryEntry(
            address="0xv2pool", dex="sushiswap", adapter_type="uniswap_v2",
            fee=30, token_a="0xaaa", token_b="0xbbb",
            liquidity=500, sqrt_price_x96=1000000, tick=2000000,
            last_block=100,
        )
        assert e.is_active()
        ps = e.to_pool_state()
        assert ps is not None
        assert ps["sqrt_price_x96"] == 1000000
        assert ps["tick"] == 2000000


# ===========================================================================
# Gas floor constant
# ===========================================================================


class TestGasFloorConstant:
    def test_gas_floor_bps_arbitrum_is_2(self):
        assert GAS_FLOOR_BPS_ARBITRUM == 2.0

    def test_gas_floor_exceeded_in_all_reject_reasons(self):
        assert REJECT_GAS_FLOOR_EXCEEDED in ALL_REJECT_REASONS

    def test_gas_floor_exceeded_is_unscored(self):
        assert REJECT_GAS_FLOOR_EXCEEDED in UNSCORED_REJECTS
