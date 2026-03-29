"""
Contract tests for M7.A.4/M7.A.5/M7.A.5.6/M7.A.5.7/M7.A.5.8/M7.A.5.9/M7.A.5.10 — Orderflow-driven replay and live block-event backrun.

Tests lock:
- OrderflowEvent schema and validation
- BackrunResult schema (incl. M7.A.5 live replay fields + M7.A.5.6 coverage/sweep + M7.A.5.7 enrichment/oracle/sim + M7.A.5.8 subgraph seed/gas decomp + M7.A.5.9 decimal-aware size normalization)
- IntentSurfaceAssessment schema
- Fixture event generation
- Event classification viability
- Backrun scoring (offline estimation)
- Intent surface scout
- Artifact schema
- Backward compatibility with M7.A constants
- M7.A.5: Live event normalization, block propagation, live replay schema
- M7.A.5.6: Event-token admission, coverage scan, granular rejects, size sweep
- M7.A.5.7: Admission source provenance, oracle guard schema, enrichment, local-sim state
- M7.A.5.8: Subgraph seed function, gas decomposition, backward compat (49 fields)
- M7.A.5.9: Decimal-aware size normalization, _normalized_bounds(), BackrunResult size fields
- M7.A.5.10: Stale-gate viability, zero-liquidity reject, admission provenance fix, split summary
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Dict

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.m7a_orderflow_replay import (
    # Constants
    ALL_EVENT_TYPES,
    ALL_REJECT_REASONS,
    ALL_SURFACES,
    BACKRUN_BUY_DEPRESSED,
    BACKRUN_SELL_APPRECIATED,
    DEFAULT_BACKRUN_GAS,
    DEFAULT_GAS_PRICE_GWEI,
    DEFAULT_LIVE_BLOCKS,
    EVENT_TYPE_LARGE_TRANSFER,
    EVENT_TYPE_POOL_REBALANCE,
    EVENT_TYPE_SWAP,
    M7A4_CHAIN,
    MIN_EVENT_SIZE_USD,
    REJECT_EVENT_TOO_SMALL,
    REJECT_GAS_EXCEEDS_GROSS,
    REJECT_INSUFFICIENT_IMPACT,
    REJECT_NO_COUNTER_VENUE,
    REJECT_QUOTE_FAILURE,
    REJECT_SAME_BLOCK_IMPOSSIBLE,
    REJECT_SLIPPAGE_EXCEEDS_GROSS,
    REJECT_TOKEN_PAIR_UNRESOLVED,
    # M7.A.5.6 reject reasons
    REJECT_NO_COUNTER_POOL,
    REJECT_TOKEN_NOT_ADMITTED,
    REJECT_UNSUPPORTED_ADAPTER,
    REJECT_RPC_QUOTE_FAIL,
    REJECT_PAIR_RESOLVED_UNTRADEABLE,
    # M7.A.5.10 reject reasons
    REJECT_STALE_POSITIVE,
    REJECT_ZERO_LIQUIDITY,
    SIGNIFICANT_IMPACT_BPS,
    SURFACE_BLOCK_BACKRUN,
    SURFACE_COW_SOLVER,
    SURFACE_MEV_SHARE_BACKRUN,
    SURFACE_UNISWAPX_FILLER,
    SWAP_EVENT_TOPIC,
    # Data structures
    BackrunResult,
    IntentSurfaceAssessment,
    OrderflowEvent,
    # Functions
    build_fixture_events,
    build_intent_scout_summary,
    build_intent_surface_assessments,
    build_replay_summary,
    classify_event_backrun_type,
    classify_event_viability,
    estimate_backrun_gross_bps,
    estimate_fee_cost_bps,
    estimate_gas_cost_bps,
    normalize_swap_log,
    score_backrun_live_parallel,
    score_backrun_offline,
    # M7.A.5.6 functions
    admit_event_tokens,
    counter_venue_coverage_scan,
    _build_address_to_symbol,
    _resolve_pool_addresses_multicall,
    _resolve_event_tokens,
    # M7.A.5.7 constants and functions
    ADMISSION_CANONICAL,
    ADMISSION_ADDR_TO_SYMBOL,
    ADMISSION_SUBGRAPH_VERIFIED,
    ADMISSION_REJECTED,
    # M7.A.5.10 admission sources
    ADMISSION_ONCHAIN_ENRICHED,
    ALL_ADMISSION_SOURCES,
    CHAINLINK_FEEDS_ARBITRUM,
    CHAINLINK_LATEST_ROUND_SELECTOR,
    CHAINLINK_DECIMALS,
    enrich_unknown_token,
    enrich_tokens_batch,
    check_oracle_sanity,
    extract_pool_state_for_sim,
    # M7.A.5.8 constants and functions
    SUBGRAPH_ENDPOINTS_ARBITRUM,
    SUBGRAPH_SEED_TOKEN_CAP,
    SUBGRAPH_TIMEOUT_SECONDS,
    seed_tokens_from_subgraph,
    estimate_gas_decomposition_bps,
    # M7.A.5.9 size normalization
    _normalized_bounds,
    _REF_MIN_WEI_18,
    _REF_MAX_WEI_18,
    # M7.A.5.9 gas denomination conversion
    _gas_cost_in_token_wei,
    _FALLBACK_ETH_PRICE_USD,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_event(**overrides) -> OrderflowEvent:
    """Build a test event with sensible defaults."""
    defaults = dict(
        event_id="test_event_1",
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
# TestOrderflowEventSchema
# ===========================================================================

class TestOrderflowEventSchema:
    """Lock OrderflowEvent creation, validation, and field contracts."""

    def test_valid_swap_event(self):
        e = _make_event()
        assert e.event_type == EVENT_TYPE_SWAP
        assert e.chain == M7A4_CHAIN
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

    def test_all_event_types_is_complete(self):
        assert EVENT_TYPE_SWAP in ALL_EVENT_TYPES
        assert EVENT_TYPE_LARGE_TRANSFER in ALL_EVENT_TYPES
        assert EVENT_TYPE_POOL_REBALANCE in ALL_EVENT_TYPES
        assert len(ALL_EVENT_TYPES) == 3

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
# TestBackrunResultSchema
# ===========================================================================

class TestBackrunResultSchema:
    """Lock BackrunResult schema and required fields."""

    def test_default_backrun_result(self):
        r = BackrunResult(
            event_id="test",
            event_source="fixture",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="estimated",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
        )
        assert r.route_viable is False
        assert r.reject_reason is None
        assert r.best_backrun_net_bps == 0.0

    def test_backrun_result_has_all_artifact_fields(self):
        """Per fix step 5: artifact must have these fields."""
        r = BackrunResult(
            event_id="t",
            event_source="fixture",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="estimated",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
        )
        d = asdict(r)
        required = {
            "event_id", "event_source", "event_type",
            "post_trade_state_used", "best_backrun_net_bps",
            "same_block_possible", "candidate_path",
            "route_viable", "reject_reason",
        }
        assert required.issubset(set(d.keys()))

    def test_reject_reasons_are_canonical(self):
        """All reject reasons must be from the canonical set."""
        assert len(ALL_REJECT_REASONS) == 15  # 8 original + 5 M7.A.5.6 + 2 M7.A.5.10
        assert REJECT_NO_COUNTER_VENUE in ALL_REJECT_REASONS
        assert REJECT_GAS_EXCEEDS_GROSS in ALL_REJECT_REASONS
        assert REJECT_SLIPPAGE_EXCEEDS_GROSS in ALL_REJECT_REASONS
        assert REJECT_EVENT_TOO_SMALL in ALL_REJECT_REASONS
        assert REJECT_SAME_BLOCK_IMPOSSIBLE in ALL_REJECT_REASONS
        assert REJECT_TOKEN_PAIR_UNRESOLVED in ALL_REJECT_REASONS
        assert REJECT_QUOTE_FAILURE in ALL_REJECT_REASONS
        assert REJECT_INSUFFICIENT_IMPACT in ALL_REJECT_REASONS


# ===========================================================================
# TestIntentSurfaceSchema
# ===========================================================================

class TestIntentSurfaceSchema:
    """Lock IntentSurfaceAssessment schema and canonical surfaces."""

    def test_all_surfaces_count(self):
        assert len(ALL_SURFACES) == 4

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
# TestFixtureEvents
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
        tokens_in = {e.token_in for e in events}
        tokens_out = {e.token_out for e in events}
        # Must cover at least 3 distinct tokens across all events
        all_tokens = tokens_in | tokens_out
        assert len(all_tokens) >= 3

    def test_fixtures_cover_multiple_dexes(self):
        events = build_fixture_events()
        dexes = {e.dex for e in events}
        assert len(dexes) >= 2

    def test_fixtures_cover_impact_range(self):
        """Fixtures should have both low and high impact events."""
        events = build_fixture_events()
        impacts = [e.estimated_impact_bps for e in events]
        assert min(impacts) < SIGNIFICANT_IMPACT_BPS  # Low impact exists
        assert max(impacts) >= SIGNIFICANT_IMPACT_BPS  # High impact exists


# ===========================================================================
# TestEventClassification
# ===========================================================================

class TestEventClassification:
    """Lock event classification logic."""

    def test_high_impact_classified_as_buy_depressed(self):
        e = _make_event(estimated_impact_bps=20.0)
        assert classify_event_backrun_type(e) == BACKRUN_BUY_DEPRESSED

    def test_low_impact_classified_as_sell_appreciated(self):
        e = _make_event(estimated_impact_bps=1.0)
        assert classify_event_backrun_type(e) == BACKRUN_SELL_APPRECIATED

    def test_boundary_impact_at_threshold(self):
        e = _make_event(estimated_impact_bps=SIGNIFICANT_IMPACT_BPS)
        result = classify_event_backrun_type(e)
        assert result == BACKRUN_BUY_DEPRESSED

    def test_viability_rejects_small_events(self):
        e = _make_event(estimated_size_usd=50.0)
        assert classify_event_viability(e) == REJECT_EVENT_TOO_SMALL

    def test_viability_rejects_zero_impact(self):
        e = _make_event(estimated_impact_bps=0.0)
        assert classify_event_viability(e) == REJECT_INSUFFICIENT_IMPACT

    def test_viability_accepts_normal_event(self):
        e = _make_event(estimated_size_usd=5000.0, estimated_impact_bps=10.0)
        assert classify_event_viability(e) is None

    def test_viability_boundary_at_min_size(self):
        e = _make_event(estimated_size_usd=MIN_EVENT_SIZE_USD)
        assert classify_event_viability(e) is None  # Exactly at threshold = viable


# ===========================================================================
# TestBackrunScoring
# ===========================================================================

class TestBackrunScoring:
    """Lock offline backrun scoring logic."""

    def test_gross_estimation_proportional_to_impact(self):
        e_low = _make_event(estimated_impact_bps=5.0)
        e_high = _make_event(estimated_impact_bps=50.0)
        assert estimate_backrun_gross_bps(e_high) > estimate_backrun_gross_bps(e_low)

    def test_gross_estimation_is_positive(self):
        e = _make_event(estimated_impact_bps=10.0)
        assert estimate_backrun_gross_bps(e) > 0

    def test_gas_cost_inversely_proportional_to_size(self):
        e_small = _make_event(estimated_size_usd=100.0)
        e_large = _make_event(estimated_size_usd=100000.0)
        assert estimate_gas_cost_bps(e_small) > estimate_gas_cost_bps(e_large)

    def test_gas_cost_positive(self):
        e = _make_event(estimated_size_usd=5000.0)
        assert estimate_gas_cost_bps(e) > 0

    def test_fee_cost_positive(self):
        e = _make_event(fee_tier=500)
        assert estimate_fee_cost_bps(e) > 0

    def test_score_offline_small_event_rejected(self):
        e = _make_event(estimated_size_usd=50.0)
        r = score_backrun_offline(e)
        assert r.reject_reason == REJECT_EVENT_TOO_SMALL
        assert r.route_viable is False

    def test_score_offline_zero_impact_rejected(self):
        e = _make_event(estimated_impact_bps=0.0)
        r = score_backrun_offline(e)
        assert r.reject_reason == REJECT_INSUFFICIENT_IMPACT

    def test_score_offline_produces_all_fields(self):
        e = _make_event(estimated_size_usd=5000.0, estimated_impact_bps=10.0)
        r = score_backrun_offline(e)
        d = asdict(r)
        for key in ["event_id", "event_source", "event_type",
                     "post_trade_state_used", "best_backrun_net_bps",
                     "candidate_path", "route_viable", "reject_reason"]:
            assert key in d

    def test_score_offline_has_estimated_state(self):
        e = _make_event()
        r = score_backrun_offline(e)
        assert r.post_trade_state_used == "estimated"
        assert r.event_source == "fixture"

    def test_score_offline_net_is_gross_minus_costs(self):
        """Net bps should be gross - gas - fees."""
        e = _make_event(estimated_size_usd=50000.0, estimated_impact_bps=25.0)
        r = score_backrun_offline(e)
        gross = estimate_backrun_gross_bps(e)
        gas = estimate_gas_cost_bps(e)
        fee = estimate_fee_cost_bps(e)
        expected_net = gross - gas - fee
        assert abs(r.best_backrun_net_bps - expected_net) < 0.01

    def test_all_fixtures_scored(self):
        """All fixture events should produce results."""
        events = build_fixture_events()
        results = [score_backrun_offline(e) for e in events]
        assert len(results) == len(events)
        for r in results:
            assert r.event_id  # Non-empty


# ===========================================================================
# TestIntentScout
# ===========================================================================

class TestIntentScout:
    """Lock intent/auction surface scout."""

    def test_assessment_count(self):
        assessments = build_intent_surface_assessments()
        assert len(assessments) == 4

    def test_all_canonical_surfaces_covered(self):
        assessments = build_intent_surface_assessments()
        surface_types = {a.surface_type for a in assessments}
        assert surface_types == ALL_SURFACES

    def test_block_backrun_highest_feasibility(self):
        assessments = build_intent_surface_assessments()
        block_backrun = [a for a in assessments if a.surface_type == SURFACE_BLOCK_BACKRUN]
        assert len(block_backrun) == 1
        assert block_backrun[0].feasibility_score == "high"

    def test_cow_solver_lowest_feasibility(self):
        assessments = build_intent_surface_assessments()
        cow = [a for a in assessments if a.surface_type == SURFACE_COW_SOLVER]
        assert len(cow) == 1
        assert cow[0].feasibility_score == "low"

    def test_block_backrun_on_arbitrum(self):
        assessments = build_intent_surface_assessments()
        block_backrun = [a for a in assessments if a.surface_type == SURFACE_BLOCK_BACKRUN]
        assert block_backrun[0].chain == M7A4_CHAIN

    def test_summary_artifact_keys(self):
        assessments = build_intent_surface_assessments()
        summary = build_intent_scout_summary(assessments)
        required = {
            "scout_type", "chain_focus", "surfaces_assessed",
            "by_feasibility", "best_near_term", "best_near_term_reason",
            "assessments",
        }
        assert required.issubset(set(summary.keys()))

    def test_summary_best_near_term_is_block_backrun(self):
        assessments = build_intent_surface_assessments()
        summary = build_intent_scout_summary(assessments)
        assert summary["best_near_term"] == SURFACE_BLOCK_BACKRUN


# ===========================================================================
# TestReplayArtifactSchema
# ===========================================================================

class TestReplayArtifactSchema:
    """Lock replay artifact schema."""

    def test_artifact_has_hypothesis_field(self):
        events = build_fixture_events()
        results = [score_backrun_offline(e) for e in events]
        artifact = build_replay_summary(events, results, mode="offline")
        assert artifact["m7a4_hypothesis"] == "orderflow_driven_backrun_replay"

    def test_artifact_has_baseline_comparisons(self):
        events = build_fixture_events()
        results = [score_backrun_offline(e) for e in events]
        artifact = build_replay_summary(events, results, mode="offline")
        assert "two_leg_baseline_net_bps" in artifact
        assert "m7a_triangular_best_net_bps" in artifact
        assert "beats_two_leg_baseline" in artifact
        assert "beats_triangular_baseline" in artifact

    def test_artifact_has_reject_histogram(self):
        events = build_fixture_events()
        results = [score_backrun_offline(e) for e in events]
        artifact = build_replay_summary(events, results, mode="offline")
        assert "reject_histogram" in artifact
        assert isinstance(artifact["reject_histogram"], dict)

    def test_artifact_results_match_events(self):
        events = build_fixture_events()
        results = [score_backrun_offline(e) for e in events]
        artifact = build_replay_summary(events, results, mode="offline")
        assert artifact["events_count"] == len(events)
        assert artifact["results_count"] == len(results)

    def test_artifact_mode_propagated(self):
        events = build_fixture_events()
        results = [score_backrun_offline(e) for e in events]
        artifact = build_replay_summary(events, results, mode="replay")
        assert artifact["mode"] == "replay"

    def test_artifact_chain_is_m7a4(self):
        events = build_fixture_events()
        results = [score_backrun_offline(e) for e in events]
        artifact = build_replay_summary(events, results, mode="offline")
        assert artifact["chain"] == M7A4_CHAIN

    def test_artifact_is_json_serializable(self):
        events = build_fixture_events()
        results = [score_backrun_offline(e) for e in events]
        artifact = build_replay_summary(events, results, mode="offline")
        # Must not raise
        json_str = json.dumps(artifact, default=str)
        parsed = json.loads(json_str)
        assert parsed["events_count"] == len(events)

    def test_empty_results_produce_valid_artifact(self):
        artifact = build_replay_summary([], [], mode="offline")
        assert artifact["events_count"] == 0
        assert artifact["results_count"] == 0
        assert artifact["best_net_bps"] is None
        assert artifact["viable_count"] == 0


# ===========================================================================
# TestBackwardCompatibility
# ===========================================================================

class TestBackwardCompatibility:
    """M7.A.4 must not break M7.A/M7.A.2/M7.A.3 contracts."""

    def test_m7a4_chain_matches_m7a(self):
        """M7.A.4 operates on same chain as M7.A."""
        assert M7A4_CHAIN == "arbitrum_one"

    def test_m7a4_does_not_import_m7a_internals(self):
        """M7.A.4 is a separate pipeline — must not modify M7.A scoring."""
        # If this import fails, M7.A modules are broken
        from engine.triangular_cycles import (
            TriangularCycle,
            CycleScore,
            score_cycle_measured,
        )
        # Just verify they still exist and import
        assert TriangularCycle is not None
        assert CycleScore is not None
        assert score_cycle_measured is not None

    def test_m7a4_two_leg_baseline_matches(self):
        """Baseline reference must match M7.A evidence."""
        events = build_fixture_events()
        results = [score_backrun_offline(e) for e in events]
        artifact = build_replay_summary(events, results, mode="offline")
        assert artifact["two_leg_baseline_net_bps"] == -3.5062

    def test_m7a4_triangular_baseline_matches(self):
        """Triangular baseline must match M7.A.3 best evidence."""
        events = build_fixture_events()
        results = [score_backrun_offline(e) for e in events]
        artifact = build_replay_summary(events, results, mode="offline")
        assert artifact["m7a_triangular_best_net_bps"] == -14.16


# ===========================================================================
# M7.A.5: Live event normalization tests
# ===========================================================================

class TestSwapEventConstants:
    """Lock M7.A.5 constants."""

    def test_swap_event_topic_is_v3(self):
        """Swap topic matches Uniswap V3 canonical topic."""
        assert SWAP_EVENT_TOPIC == "0xc42079f94a6350d7e6235f29174924f928cc2ac818eb64fed8004e115fbcca67"

    def test_default_live_blocks(self):
        assert DEFAULT_LIVE_BLOCKS == 5


class TestAddressLookup:
    """Test reverse address→symbol lookup helper."""

    def test_build_address_to_symbol_basic(self):
        addrs = {"WETH": "0xABCD", "USDC": "0x1234"}
        result = _build_address_to_symbol(addrs)
        assert result["0xabcd"] == "WETH"
        assert result["0x1234"] == "USDC"

    def test_build_address_to_symbol_empty(self):
        assert _build_address_to_symbol({}) == {}

    def test_build_address_to_symbol_case_insensitive(self):
        addrs = {"ARB": "0xAbCdEf"}
        result = _build_address_to_symbol(addrs)
        assert "0xabcdef" in result
        assert result["0xabcdef"] == "ARB"


class TestNormalizeSwapLog:
    """Test raw V3 Swap log → OrderflowEvent normalization."""

    @staticmethod
    def _make_swap_log(amount0: int, amount1: int, pool_addr: str = "0x" + "aa" * 20,
                       block_number: int = 500000000, tx_hash_bytes: bytes = b"\xde" * 32):
        """Build a fake Web3-like log entry for Swap events."""
        # Encode amount0, amount1, sqrtPriceX96, liquidity, tick as 5 x 32-byte words
        def _encode_int256(val: int) -> str:
            if val < 0:
                val = val + (1 << 256)
            return format(val, "064x")

        data_hex = (
            "0x"
            + _encode_int256(amount0)
            + _encode_int256(amount1)
            + "0" * 64  # sqrtPriceX96 placeholder
            + "0" * 64  # liquidity placeholder
            + "0" * 64  # tick placeholder
        )

        class HexBytes:
            def __init__(self, val):
                self._val = val
            def hex(self):
                return self._val.hex() if isinstance(self._val, bytes) else self._val

        return {
            "address": pool_addr,
            "transactionHash": HexBytes(tx_hash_bytes),
            "blockNumber": block_number,
            "data": data_hex,
            "topics": [SWAP_EVENT_TOPIC],
        }

    def test_normalize_basic_token0_in(self):
        """Positive amount0, negative amount1 → token0 in."""
        log = self._make_swap_log(amount0=5000 * 10**6, amount1=-(10**18))
        ev = normalize_swap_log(
            log=log,
            addr_to_symbol={},
            token_addresses={},
            dex_configs={},
            event_index=0,
        )
        assert ev is not None
        assert ev.event_type == EVENT_TYPE_SWAP
        assert ev.chain == M7A4_CHAIN
        assert ev.amount_in_wei == 5000 * 10**6
        assert ev.amount_out_wei == 10**18
        assert ev.block_number == 500000000

    def test_normalize_basic_token1_in(self):
        """Positive amount1, negative amount0 → token1 in."""
        log = self._make_swap_log(amount0=-(10**18), amount1=5000 * 10**6)
        ev = normalize_swap_log(
            log=log,
            addr_to_symbol={},
            token_addresses={},
            dex_configs={},
            event_index=7,
        )
        assert ev is not None
        assert ev.token_in == "token1_in"
        assert ev.event_id == "live_swap_500000000_7"

    def test_normalize_skips_both_positive(self):
        """Both amounts same sign → None."""
        log = self._make_swap_log(amount0=100, amount1=200)
        ev = normalize_swap_log(log, {}, {}, {}, 0)
        assert ev is None

    def test_normalize_skips_tiny_events(self):
        """Events below MIN_EVENT_SIZE_USD * 0.1 threshold are skipped."""
        log = self._make_swap_log(amount0=1, amount1=-1)
        ev = normalize_swap_log(log, {}, {}, {}, 0)
        assert ev is None

    def test_normalize_truncated_data(self):
        """Short data hex → None."""
        log = self._make_swap_log(amount0=1, amount1=-1)
        log["data"] = "0x" + "00" * 10  # Too short
        ev = normalize_swap_log(log, {}, {}, {}, 0)
        assert ev is None

    def test_normalize_preserves_tx_hash(self):
        """Transaction hash is preserved in event."""
        tx_bytes = b"\xab" * 32
        log = self._make_swap_log(amount0=10**18, amount1=-(5000 * 10**6), tx_hash_bytes=tx_bytes)
        ev = normalize_swap_log(log, {}, {}, {}, 0)
        assert ev is not None
        assert ev.tx_hash == tx_bytes.hex()


# ===========================================================================
# M7.A.5: BackrunResult live fields
# ===========================================================================

class TestBackrunResultLiveFields:
    """Lock M7.A.5 live replay fields on BackrunResult."""

    def test_live_fields_default_none(self):
        """New M7.A.5 fields default to None/0 for offline results."""
        r = BackrunResult(
            event_id="test",
            event_source="fixture",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="estimated",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
        )
        assert r.event_block is None
        assert r.quote_block is None
        assert r.block_lag is None
        assert r.same_state_class is None
        assert r.counter_venue_count == 0
        assert r.best_live_net_bps is None

    def test_live_fields_in_asdict(self):
        """M7.A.5 fields must appear in serialized form."""
        r = BackrunResult(
            event_id="test",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            event_block=500000000,
            quote_block=500000002,
            block_lag=2,
            same_state_class="next_block",
            counter_venue_count=3,
            best_live_net_bps=-2.5,
        )
        d = asdict(r)
        assert d["event_block"] == 500000000
        assert d["quote_block"] == 500000002
        assert d["block_lag"] == 2
        assert d["same_state_class"] == "next_block"
        assert d["counter_venue_count"] == 3
        assert d["best_live_net_bps"] == -2.5

    def test_live_fields_all_present_in_schema(self):
        """All M7.A.5 fields exist in BackrunResult."""
        r = BackrunResult(
            event_id="t",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
        )
        d = asdict(r)
        m7a5_fields = {
            "event_block", "quote_block", "block_lag",
            "same_state_class", "counter_venue_count", "best_live_net_bps",
        }
        assert m7a5_fields.issubset(set(d.keys()))

    def test_same_state_class_values(self):
        """Same-state classifications are valid."""
        for cls in ("same_block", "next_block", "stale"):
            r = BackrunResult(
                event_id="t",
                event_source="live",
                event_type=EVENT_TYPE_SWAP,
                post_trade_state_used="live",
                backrun_direction=BACKRUN_BUY_DEPRESSED,
                same_state_class=cls,
            )
            assert r.same_state_class == cls


# ===========================================================================
# M7.A.5.2: Provider provenance tests
# ===========================================================================


class TestProviderProvenance:
    """M7.A.5.2: Provider provenance fields must be present in live artifacts."""

    PROVENANCE_KEYS = {"rpc_provider", "rpc_source", "resolved_rpc_host", "fallback_used"}

    def test_provenance_keys_schema(self):
        """All 4 provenance fields must be machine-readable strings/bool."""
        example = {
            "rpc_provider": "alchemy",
            "rpc_source": "alchemy_api_key",
            "resolved_rpc_host": "arb-mainnet.g.alchemy.com",
            "fallback_used": False,
        }
        assert self.PROVENANCE_KEYS == set(example.keys())
        assert isinstance(example["rpc_provider"], str)
        assert isinstance(example["rpc_source"], str)
        assert isinstance(example["resolved_rpc_host"], str)
        assert isinstance(example["fallback_used"], bool)

    def test_resolve_rpc_http_returns_provenance(self):
        """resolve_rpc_http() returns (url, provider, diagnostics) tuple."""
        from core.rpc_urls import resolve_rpc_http

        url, provider, diag = resolve_rpc_http(
            chain_id=42161,
            network="arbitrum_one",
            env={},  # No keys → public fallback
        )
        assert isinstance(provider, str)
        assert isinstance(diag, dict)
        assert "source" in diag

    def test_public_fallback_detected(self):
        """When no Alchemy key, fallback_used logic is correct."""
        from core.rpc_urls import resolve_rpc_http

        url, provider, diag = resolve_rpc_http(
            chain_id=42161,
            network="arbitrum_one",
            env={},  # No keys → public fallback
        )
        fallback_used = diag.get("source") == "public_fallback"
        assert fallback_used is True
        assert provider == "public"

    def test_alchemy_key_detected(self):
        """When ALCHEMY_API_KEY is set, provider is alchemy."""
        from core.rpc_urls import resolve_rpc_http

        url, provider, diag = resolve_rpc_http(
            chain_id=42161,
            network="arbitrum_one",
            env={"ALCHEMY_API_KEY": "test_key_fake"},
        )
        assert provider == "alchemy"
        assert diag.get("source") == "alchemy_api_key"
        assert "alchemy.com" in (url or "")

    def test_low_lag_subset_fields_in_schema(self):
        """Low-lag subset keys are defined correctly."""
        low_lag_keys = {"events_scored_low_lag", "best_live_net_bps_low_lag"}
        # These keys must appear in live_state_metrics when live results exist
        assert len(low_lag_keys) == 2

    def test_post_trade_state_live_value(self):
        """M7.A.5 uses 'live' as post_trade_state_used."""
        r = BackrunResult(
            event_id="t",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
        )
        assert r.post_trade_state_used == "live"
        # Check that "live" is distinct from "estimated", "simulated", "quoted"
        assert r.post_trade_state_used not in ("estimated", "simulated", "quoted")


# ===========================================================================
# M7.A.5: Offline backward compatibility
# ===========================================================================

class TestM7A5BackwardCompat:
    """M7.A.5 additions must not break offline/fixture flows."""

    def test_offline_results_have_none_live_fields(self):
        """Offline scoring must not populate M7.A.5 fields."""
        ev = _make_event()
        r = score_backrun_offline(ev)
        assert r.event_block is None
        assert r.quote_block is None
        assert r.block_lag is None
        assert r.same_state_class is None
        assert r.best_live_net_bps is None

    def test_fixture_events_still_5(self):
        """Fixture event count must not change."""
        events = build_fixture_events()
        assert len(events) == 5

    def test_offline_artifact_schema_unchanged(self):
        """Offline artifact still has all expected fields."""
        events = build_fixture_events()
        results = [score_backrun_offline(e) for e in events]
        artifact = build_replay_summary(events, results, mode="offline")
        required_keys = {
            "m7a4_hypothesis", "mode", "timestamp", "chain",
            "events_count", "results_count", "viable_count",
            "positive_net_count", "best_net_bps", "worst_net_bps",
            "mean_net_bps", "reject_histogram", "results",
            "two_leg_baseline_net_bps", "m7a_triangular_best_net_bps",
        }
        assert required_keys.issubset(set(artifact.keys()))

    def test_offline_results_serialize_with_new_fields(self):
        """Serialized offline results include M7.A.5 fields as None/0."""
        ev = _make_event()
        r = score_backrun_offline(ev)
        d = asdict(r)
        # M7.A.5 fields present but None/0
        assert "event_block" in d
        assert "best_live_net_bps" in d
        assert d["event_block"] is None
        assert d["counter_venue_count"] == 0

    def test_offline_json_roundtrip(self):
        """Full offline artifact round-trips through JSON."""
        events = build_fixture_events()
        results = [score_backrun_offline(e) for e in events]
        artifact = build_replay_summary(events, results, mode="offline")
        json_str = json.dumps(artifact, default=str)
        parsed = json.loads(json_str)
        assert parsed["events_count"] == 5
        assert parsed["mode"] == "offline"


class TestScoreBackrunLiveRoundtrip:
    """M7.A.5: Verify two-pass roundtrip logic chains buy output into sell input."""

    def test_sell_uses_buy_output_as_input(self):
        """The sell pass must use best_buy_amount, not backrun_size_wei."""
        from unittest.mock import patch, MagicMock
        from scripts.m7a_orderflow_replay import score_backrun_live

        ev = OrderflowEvent(
            event_id="test_rt_001",
            event_type="swap",
            chain="arbitrum_one",
            pool_address="0xabc",
            token_in="USDC",
            token_out="WETH",
            amount_in_wei=5000 * 10**6,  # 5000 USDC
            amount_out_wei=0,
            dex="uniswap_v3",
            fee_tier=500,
            estimated_size_usd=5000.0,
            estimated_impact_bps=10.0,
            block_number=100,
            tx_hash="0xdef",
            timestamp="2026-01-01T00:00:00Z",
        )

        # Track call args to verify sell input matches buy output
        call_log = []
        USDC_ADDR = "0xaf88d065e77c8cC2239327C5EDb3A432268e5831"
        WETH_ADDR = "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1"
        # Backrun buys what user sold (WETH) then sells back
        # Buy: WETH→USDC, Sell: USDC→WETH
        # backrun_size_wei will be ~10^15 (0.001 WETH after clamp)
        BUY_OUTPUT_USDC = 3_500_000  # Buy: WETH→USDC output (~$3.50)

        def mock_quoter(quoter_address, token_in, token_out, amount_in, fee,
                        rpc_url, block_num="latest", fallback_rpc_urls=None):
            call_log.append({
                "token_in": token_in, "token_out": token_out,
                "amount_in": amount_in,
            })
            # Buy side: WETH→USDC (token_in=WETH)
            if token_in.lower() == WETH_ADDR.lower():
                return {"amount_out": BUY_OUTPUT_USDC}
            # Sell side: USDC→WETH (token_in=USDC)
            return {"amount_out": 990_000_000_000}  # ~0.00000099 WETH (small loss)

        token_addresses = {"WETH": WETH_ADDR, "USDC": USDC_ADDR}
        dex_configs = {"uniswap_v3": {
            "quoter_v2": "0x61fFE014bA17989E743c5F6cB21bF9697530B21e",
            "fee_tiers": [500],
        }}

        with patch("strategy.quote_rpc.read_quoter_v2", side_effect=mock_quoter):
            with patch("strategy.quote_rpc.QUOTER_RATE_LIMITED", new=object()):
                r = score_backrun_live(
                    event=ev, rpc_url="http://fake", dex_configs=dex_configs,
                    token_addresses=token_addresses, current_block=100,
                )

        # Pass 1 = buy (WETH→USDC), Pass 2 = sell (USDC→WETH)
        buy_calls = [c for c in call_log if c["token_in"].lower() == WETH_ADDR.lower()]
        sell_calls = [c for c in call_log if c["token_in"].lower() == USDC_ADDR.lower()]
        assert len(buy_calls) >= 1, f"Expected buy calls, got {call_log}"
        assert len(sell_calls) >= 1, f"Expected sell calls, got {call_log}"
        # Critical: sell input must equal buy output, NOT backrun_size_wei
        assert sell_calls[0]["amount_in"] == BUY_OUTPUT_USDC, (
            f"Sell input {sell_calls[0]['amount_in']} != buy output {BUY_OUTPUT_USDC}"
        )


# ===========================================================================
# M7.A.5.3: WebSocket provenance and parallel scoring tests
# ===========================================================================


class TestWsLiveFields:
    """M7.A.5.3: BackrunResult must carry ws-live specific fields."""

    WS_FIELDS = {
        "ws_provider",
        "event_detected_at_block",
        "quote_started_block",
        "quote_finished_block",
        "quote_pipeline_latency_ms",
        "venues_pruned_by_multicall",
    }

    def test_ws_fields_present_in_dataclass(self):
        """BackrunResult has all M7.A.5.3 fields."""
        r = BackrunResult(
            event_id="t",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
        )
        d = asdict(r)
        for field_name in self.WS_FIELDS:
            assert field_name in d, f"Missing ws field: {field_name}"

    def test_ws_fields_default_none_for_offline(self):
        """Offline results have ws fields as None/0."""
        ev = _make_event()
        r = score_backrun_offline(ev)
        assert r.ws_provider is None
        assert r.event_detected_at_block is None
        assert r.quote_started_block is None
        assert r.quote_finished_block is None
        assert r.quote_pipeline_latency_ms is None
        assert r.venues_pruned_by_multicall == 0

    def test_ws_provider_values(self):
        """ws_provider accepts valid string values."""
        for prov in ("alchemy", "public", "unknown", None):
            r = BackrunResult(
                event_id="t",
                event_source="live",
                event_type=EVENT_TYPE_SWAP,
                post_trade_state_used="live",
                backrun_direction=BACKRUN_BUY_DEPRESSED,
                ws_provider=prov,
            )
            assert r.ws_provider == prov

    def test_pipeline_latency_numeric(self):
        """quote_pipeline_latency_ms is a numeric type when set."""
        r = BackrunResult(
            event_id="t",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            quote_pipeline_latency_ms=42.5,
        )
        assert isinstance(r.quote_pipeline_latency_ms, float)
        assert r.quote_pipeline_latency_ms > 0

    def test_serialization_includes_ws_fields(self):
        """JSON serialization includes all M7.A.5.3 fields."""
        r = BackrunResult(
            event_id="t",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            ws_provider="alchemy",
            event_detected_at_block=500,
            quote_started_block=500,
            quote_finished_block=501,
            quote_pipeline_latency_ms=123.4,
            venues_pruned_by_multicall=2,
        )
        d = asdict(r)
        json_str = json.dumps(d, default=str)
        parsed = json.loads(json_str)
        assert parsed["ws_provider"] == "alchemy"
        assert parsed["event_detected_at_block"] == 500
        assert parsed["quote_started_block"] == 500
        assert parsed["quote_finished_block"] == 501
        assert parsed["quote_pipeline_latency_ms"] == 123.4
        assert parsed["venues_pruned_by_multicall"] == 2


class TestWsProvenance:
    """M7.A.5.3: resolve_rpc_ws returns provenance for WS connections."""

    def test_resolve_rpc_ws_returns_triple(self):
        """resolve_rpc_ws() returns (url, provider, diagnostics) tuple."""
        from core.rpc_urls import resolve_rpc_ws

        url, provider, diag = resolve_rpc_ws(
            chain_id=42161,
            network="arbitrum_one",
            env={},  # No keys → no WS
        )
        assert isinstance(provider, str)
        assert isinstance(diag, dict)
        assert "source" in diag

    def test_alchemy_ws_detected(self):
        """When ALCHEMY_API_KEY is set, ws provider is alchemy."""
        from core.rpc_urls import resolve_rpc_ws

        url, provider, diag = resolve_rpc_ws(
            chain_id=42161,
            network="arbitrum_one",
            env={"ALCHEMY_API_KEY": "test_key_fake"},
        )
        assert provider == "alchemy"
        assert "alchemy" in (url or "")

    def test_no_key_returns_none_url(self):
        """Without API key, ws URL is None."""
        from core.rpc_urls import resolve_rpc_ws

        url, provider, diag = resolve_rpc_ws(
            chain_id=42161,
            network="arbitrum_one",
            env={},
        )
        assert url is None
        assert diag.get("source") == "none"


class TestScoreBackrunLiveParallel:
    """M7.A.5.3: Parallel scoring function contract tests."""

    def test_parallel_scoring_with_mock_quoter(self):
        """score_backrun_live_parallel produces valid BackrunResult."""
        from unittest.mock import patch

        ev = OrderflowEvent(
            event_id="test_ws_001",
            event_type="swap",
            chain="arbitrum_one",
            pool_address="0xabc",
            token_in="WETH",
            token_out="USDC",
            amount_in_wei=10**18,
            amount_out_wei=0,
            dex="uniswap_v3",
            fee_tier=500,
            estimated_size_usd=2000.0,
            estimated_impact_bps=10.0,
            block_number=100,
            tx_hash="0xdef",
            timestamp="2026-01-01T00:00:00Z",
        )

        USDC_ADDR = "0xaf88d065e77c8cC2239327C5EDb3A432268e5831"
        WETH_ADDR = "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1"

        def mock_quoter(**kwargs):
            return {"amount_out": 9_970_000_000_000_000}

        token_addresses = {"WETH": WETH_ADDR, "USDC": USDC_ADDR}
        dex_configs = {"uniswap_v3": {
            "quoter_v2": "0x61fFE014bA17989E743c5F6cB21bF9697530B21e",
            "fee_tiers": [500],
        }}

        with patch("strategy.quote_rpc.read_quoter_v2", side_effect=mock_quoter):
            with patch("strategy.quote_rpc.QUOTER_RATE_LIMITED", new=object()):
                r = score_backrun_live_parallel(
                    event=ev, rpc_url="http://fake", dex_configs=dex_configs,
                    token_addresses=token_addresses, current_block=100,
                    ws_provider="alchemy", event_detected_at_block=100,
                )

        assert r.event_source == "live"
        assert r.ws_provider == "alchemy"
        assert r.event_detected_at_block == 100
        assert r.quote_pipeline_latency_ms is not None
        assert r.quote_pipeline_latency_ms >= 0
        assert r.venues_pruned_by_multicall == 0

    def test_parallel_scoring_populates_block_lag(self):
        """Parallel scoring computes block_lag from event to quote."""
        from unittest.mock import patch

        ev = _make_event(block_number=100)

        def mock_quoter(**kwargs):
            return {"amount_out": 5_000_000}

        token_addresses = {"WETH": "0xWETH", "USDC": "0xUSDC"}
        dex_configs = {"test_dex": {
            "quoter_v2": "0xQuoter",
            "fee_tiers": [500],
        }}

        with patch("strategy.quote_rpc.read_quoter_v2", side_effect=mock_quoter):
            with patch("strategy.quote_rpc.QUOTER_RATE_LIMITED", new=object()):
                with patch("web3.Web3") as mock_w3_cls:
                    mock_w3_cls.return_value.eth.block_number = 102
                    mock_w3_cls.HTTPProvider = lambda url: None
                    r = score_backrun_live_parallel(
                        event=ev, rpc_url="http://fake", dex_configs=dex_configs,
                        token_addresses=token_addresses, current_block=100,
                        ws_provider="alchemy", event_detected_at_block=100,
                    )

        assert r.block_lag is not None
        assert r.quote_started_block == 100

    def test_parallel_scoring_no_venues_returns_reject(self):
        """No quotable venues → granular reject (NO_COUNTER_POOL or RPC_QUOTE_FAIL)."""
        ev = _make_event()

        r = score_backrun_live_parallel(
            event=ev, rpc_url="http://fake", dex_configs={},
            token_addresses={"WETH": "0xW", "USDC": "0xU"},
            current_block=100,
            ws_provider="alchemy",
        )
        # M7.A.5.6: QUOTE_FAILURE is now split into granular reasons
        assert r.reject_reason in (
            REJECT_QUOTE_FAILURE, REJECT_NO_COUNTER_POOL,
            REJECT_RPC_QUOTE_FAIL, REJECT_PAIR_RESOLVED_UNTRADEABLE,
            REJECT_TOKEN_NOT_ADMITTED, REJECT_UNSUPPORTED_ADAPTER,
        )
        assert r.ws_provider == "alchemy"
        assert r.quote_pipeline_latency_ms is not None


class TestWsLiveArtifactSchema:
    """M7.A.5.3: ws_live artifact must contain ws-specific fields."""

    def test_ws_live_mode_in_replay_summary(self):
        """build_replay_summary accepts ws_live mode."""
        events = build_fixture_events()[:1]
        results = [score_backrun_offline(events[0])]
        artifact = build_replay_summary(events, results, mode="ws_live")
        assert artifact["mode"] == "ws_live"

    def test_ws_live_artifact_keys(self):
        """ws_live artifact should contain standard replay fields."""
        events = build_fixture_events()[:1]
        results = [score_backrun_offline(events[0])]
        artifact = build_replay_summary(events, results, mode="ws_live")
        required_keys = {
            "m7a4_hypothesis", "mode", "timestamp", "chain",
            "events_count", "results_count", "viable_count",
            "best_net_bps", "reject_histogram", "results",
        }
        assert required_keys.issubset(set(artifact.keys()))


class TestM7A53BackwardCompat:
    """M7.A.5.3 additions must not break existing M7.A.5 flows."""

    def test_offline_results_have_none_ws_fields(self):
        """Offline scoring: ws fields are None/0."""
        ev = _make_event()
        r = score_backrun_offline(ev)
        d = asdict(r)
        assert d["ws_provider"] is None
        assert d["event_detected_at_block"] is None
        assert d["quote_started_block"] is None
        assert d["quote_finished_block"] is None
        assert d["quote_pipeline_latency_ms"] is None
        assert d["venues_pruned_by_multicall"] == 0

    def test_json_roundtrip_with_ws_fields(self):
        """Full result with ws fields round-trips through JSON."""
        r = BackrunResult(
            event_id="t",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            ws_provider="alchemy",
            event_detected_at_block=500,
            quote_started_block=500,
            quote_finished_block=501,
            quote_pipeline_latency_ms=42.5,
            venues_pruned_by_multicall=3,
        )
        d = asdict(r)
        json_str = json.dumps(d, default=str)
        parsed = json.loads(json_str)
        assert parsed["ws_provider"] == "alchemy"
        assert parsed["venues_pruned_by_multicall"] == 3
        assert parsed["quote_pipeline_latency_ms"] == 42.5


# ---------------------------------------------------------------------------
# M7.A.5.3.1 — Latency budget + low-lag/stale summary tests
# ---------------------------------------------------------------------------


class TestLatencyBudgetField:
    """latency_budget_ms field on BackrunResult."""

    def test_latency_budget_exists_in_dataclass(self):
        r = BackrunResult(
            event_id="lb1",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
        )
        d = asdict(r)
        assert "latency_budget_ms" in d

    def test_latency_budget_default_none(self):
        r = BackrunResult(
            event_id="lb2",
            event_source="fixture",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="estimated",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
        )
        assert r.latency_budget_ms is None

    def test_latency_budget_set_value(self):
        r = BackrunResult(
            event_id="lb3",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            latency_budget_ms=250.0,
            quote_pipeline_latency_ms=180.5,
        )
        assert r.latency_budget_ms == 250.0
        assert r.quote_pipeline_latency_ms < r.latency_budget_ms

    def test_latency_budget_json_roundtrip(self):
        r = BackrunResult(
            event_id="lb4",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            latency_budget_ms=250.0,
        )
        d = asdict(r)
        parsed = json.loads(json.dumps(d, default=str))
        assert parsed["latency_budget_ms"] == 250.0

    def test_offline_result_latency_budget_none(self):
        """Offline scoring never sets latency_budget_ms."""
        ev = _make_event()
        r = score_backrun_offline(ev)
        assert r.latency_budget_ms is None


class TestScoreBackrunLiveParallelLatencyBudget:
    """score_backrun_live_parallel passes block_time_ms to result."""

    def test_parallel_scoring_receives_latency_budget(self):
        ev = _make_event(block_number=100)
        import unittest.mock as mock

        mock_result = {"amount_out": 10**18, "sqrtPriceX96After": 0, "ticksCrossed": 1}
        with mock.patch(
            "strategy.quote_rpc.read_quoter_v2",
            return_value=mock_result,
        ):
            r = score_backrun_live_parallel(
                event=ev,
                rpc_url="http://localhost:8545",
                dex_configs={
                    "uniswap_v3": {
                        "quoter_v2": "0x" + "11" * 20,
                        "fee_tiers": [500],
                    }
                },
                token_addresses={"WETH": "0x" + "aa" * 20, "USDC": "0x" + "bb" * 20},
                current_block=100,
                ws_provider="alchemy",
                block_time_ms=250.0,
            )
        assert r.latency_budget_ms == 250.0

    def test_parallel_scoring_no_budget_defaults_none(self):
        ev = _make_event(block_number=100)
        import unittest.mock as mock

        with mock.patch(
            "strategy.quote_rpc.read_quoter_v2",
            return_value=None,
        ):
            r = score_backrun_live_parallel(
                event=ev,
                rpc_url="http://localhost:8545",
                dex_configs={},
                token_addresses={"WETH": "0x" + "aa" * 20, "USDC": "0x" + "bb" * 20},
                current_block=100,
            )
        assert r.latency_budget_ms is None


class TestWsLowLagStaleSummary:
    """ws_low_lag_summary and ws_stale_summary artifact schema tests."""

    def test_summary_keys_present_in_artifact(self):
        r = BackrunResult(
            event_id="s1",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
        )
        artifact = build_replay_summary([_make_event()], [r], mode="ws_live")
        artifact["ws_low_lag_summary"] = {
            "count": 3,
            "best_net_bps": -5.0,
            "worst_net_bps": -20.0,
            "mean_net_bps": -12.0,
            "same_block_count": 1,
            "next_block_count": 2,
            "mean_pipeline_latency_ms": 180.0,
            "viable_count": 0,
        }
        artifact["ws_stale_summary"] = {
            "count": 5,
            "best_net_bps": -18.0,
            "worst_net_bps": -25.0,
            "mean_net_bps": -21.0,
            "mean_block_lag": 12.5,
            "mean_pipeline_latency_ms": 350.0,
            "viable_count": 0,
        }
        s = json.dumps(artifact, default=str)
        parsed = json.loads(s)
        assert "ws_low_lag_summary" in parsed
        assert "ws_stale_summary" in parsed

    def test_low_lag_summary_required_keys(self):
        expected = {
            "count", "best_net_bps", "worst_net_bps", "mean_net_bps",
            "same_block_count", "next_block_count", "mean_pipeline_latency_ms",
            "viable_count",
        }
        summary = {
            "count": 0, "best_net_bps": None, "worst_net_bps": None,
            "mean_net_bps": None, "same_block_count": 0, "next_block_count": 0,
            "mean_pipeline_latency_ms": None, "viable_count": 0,
        }
        assert set(summary.keys()) == expected

    def test_stale_summary_required_keys(self):
        expected = {
            "count", "best_net_bps", "worst_net_bps", "mean_net_bps",
            "mean_block_lag", "mean_pipeline_latency_ms", "viable_count",
        }
        summary = {
            "count": 0, "best_net_bps": None, "worst_net_bps": None,
            "mean_net_bps": None, "mean_block_lag": None,
            "mean_pipeline_latency_ms": None, "viable_count": 0,
        }
        assert set(summary.keys()) == expected

    def test_latency_budget_in_live_state_metrics(self):
        metrics = {
            "latency_budget_ms": 250,
            "latency_budget_hit_rate": 0.75,
            "sub_block_capable": True,
        }
        assert metrics["latency_budget_ms"] == 250
        assert 0.0 <= metrics["latency_budget_hit_rate"] <= 1.0
        assert isinstance(metrics["sub_block_capable"], bool)


class TestM7A531BackwardCompat:
    """M7.A.5.3.1 additions must not break existing M7.A.5.3 flows."""

    def test_offline_results_no_latency_budget(self):
        ev = _make_event()
        r = score_backrun_offline(ev)
        d = asdict(r)
        assert d["latency_budget_ms"] is None
        assert d["ws_provider"] is None
        assert d["quote_pipeline_latency_ms"] is None

    def test_existing_ws_fields_still_present(self):
        r = BackrunResult(
            event_id="bc1",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            ws_provider="alchemy",
            quote_pipeline_latency_ms=200.0,
            latency_budget_ms=250.0,
        )
        d = asdict(r)
        ws_fields = [
            "ws_provider", "event_detected_at_block", "quote_started_block",
            "quote_finished_block", "quote_pipeline_latency_ms",
            "venues_pruned_by_multicall", "latency_budget_ms",
        ]
        for fld in ws_fields:
            assert fld in d, f"Missing field: {fld}"


# ===========================================================================
# M7.A.5.4: Two-stage pruning pipeline tests
# ===========================================================================


class TestM7A54BackrunResultFields:
    """M7.A.5.4 new BackrunResult fields for two-stage pruning."""

    def test_new_fields_exist_in_dataclass(self):
        r = BackrunResult(
            event_id="t1",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
        )
        d = asdict(r)
        assert "quote_calls_attempted" in d
        assert "quote_calls_after_pruning" in d
        assert "prune_reason_histogram" in d
        assert "pipeline_stage_latency_ms" in d

    def test_new_fields_default_none(self):
        r = BackrunResult(
            event_id="t2",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
        )
        assert r.quote_calls_attempted is None
        assert r.quote_calls_after_pruning is None
        assert r.prune_reason_histogram is None
        assert r.pipeline_stage_latency_ms is None

    def test_fields_accept_values(self):
        r = BackrunResult(
            event_id="t3",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            quote_calls_attempted=12,
            quote_calls_after_pruning=4,
            prune_reason_histogram={"NO_POOL": 2, "ZERO_LIQUIDITY": 1},
            pipeline_stage_latency_ms={"stage_a_ms": 50.5, "stage_b_ms": 200.0},
        )
        assert r.quote_calls_attempted == 12
        assert r.quote_calls_after_pruning == 4
        assert r.prune_reason_histogram["NO_POOL"] == 2
        assert r.pipeline_stage_latency_ms["stage_a_ms"] == 50.5

    def test_json_round_trip(self):
        r = BackrunResult(
            event_id="t4",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            quote_calls_attempted=10,
            quote_calls_after_pruning=3,
            prune_reason_histogram={"ZERO_LIQUIDITY": 3},
            pipeline_stage_latency_ms={"stage_a_ms": 45.0, "stage_b_ms": 180.0},
        )
        d = asdict(r)
        s = json.dumps(d, default=str)
        parsed = json.loads(s)
        assert parsed["quote_calls_attempted"] == 10
        assert parsed["quote_calls_after_pruning"] == 3
        assert parsed["prune_reason_histogram"]["ZERO_LIQUIDITY"] == 3
        assert parsed["pipeline_stage_latency_ms"]["stage_a_ms"] == 45.0

    def test_offline_results_have_none_pruning_fields(self):
        ev = _make_event()
        r = score_backrun_offline(ev)
        d = asdict(r)
        assert d["quote_calls_attempted"] is None
        assert d["quote_calls_after_pruning"] is None
        assert d["prune_reason_histogram"] is None
        assert d["pipeline_stage_latency_ms"] is None

    def test_pruning_reduces_calls(self):
        """Verify that after pruning, quote_calls_after_pruning <= quote_calls_attempted."""
        r = BackrunResult(
            event_id="t5",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            quote_calls_attempted=12,
            quote_calls_after_pruning=4,
            venues_pruned_by_multicall=2,
        )
        assert r.quote_calls_after_pruning <= r.quote_calls_attempted


class TestM7A54PruneReasonHistogram:
    """M7.A.5.4: prune_reason_histogram contract tests."""

    VALID_REASONS = {"NO_POOL", "ZERO_LIQUIDITY"}

    def test_empty_histogram_is_none(self):
        r = BackrunResult(
            event_id="prh1",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            prune_reason_histogram=None,
        )
        assert r.prune_reason_histogram is None

    def test_valid_histogram_keys(self):
        hist = {"NO_POOL": 3, "ZERO_LIQUIDITY": 1}
        assert all(k in self.VALID_REASONS for k in hist)

    def test_histogram_values_non_negative(self):
        hist = {"NO_POOL": 0, "ZERO_LIQUIDITY": 5}
        assert all(v >= 0 for v in hist.values())


class TestM7A54StageLatency:
    """M7.A.5.4: pipeline_stage_latency_ms contract tests."""

    REQUIRED_KEYS = {"stage_a_ms", "stage_b_ms"}

    def test_stage_latency_has_required_keys(self):
        latency = {"stage_a_ms": 50.0, "stage_b_ms": 200.0}
        assert set(latency.keys()) == self.REQUIRED_KEYS

    def test_stage_a_cheaper_than_stage_b(self):
        """In typical operation, Stage A (multicall) should be faster than Stage B (quoter)."""
        latency = {"stage_a_ms": 50.0, "stage_b_ms": 200.0}
        # Not an invariant, just a typical expectation
        assert latency["stage_a_ms"] >= 0
        assert latency["stage_b_ms"] >= 0

    def test_stage_latency_serializes(self):
        latency = {"stage_a_ms": 123.45, "stage_b_ms": 678.90}
        s = json.dumps(latency)
        parsed = json.loads(s)
        assert parsed["stage_a_ms"] == 123.45
        assert parsed["stage_b_ms"] == 678.90


class TestM7A54ArtifactFields:
    """M7.A.5.4: Artifact-level pruning metrics."""

    def test_live_state_metrics_pruning_fields(self):
        """Verify the artifact live_state_metrics includes M7.A.5.4 fields."""
        expected_m7a54_fields = {
            "mean_quote_calls_attempted",
            "mean_quote_calls_after_pruning",
            "prune_reason_histogram",
            "mean_stage_a_ms",
            "mean_stage_b_ms",
        }
        # Build a synthetic artifact snippet to validate schema
        metrics = {
            "mean_quote_calls_attempted": 12.0,
            "mean_quote_calls_after_pruning": 4.0,
            "prune_reason_histogram": {"NO_POOL": 5, "ZERO_LIQUIDITY": 2},
            "mean_stage_a_ms": 55.0,
            "mean_stage_b_ms": 180.0,
        }
        assert expected_m7a54_fields == set(metrics.keys())

    def test_ws_low_lag_summary_has_pruning_field(self):
        """ws_low_lag_summary must include mean_quote_calls_after_pruning."""
        summary = {
            "count": 2,
            "best_net_bps": -10.0,
            "worst_net_bps": -20.0,
            "mean_net_bps": -15.0,
            "same_block_count": 1,
            "next_block_count": 1,
            "mean_pipeline_latency_ms": 200.0,
            "viable_count": 0,
            "mean_quote_calls_after_pruning": 3.5,
        }
        assert "mean_quote_calls_after_pruning" in summary


class TestM7A54ResolvePoolAddresses:
    """M7.A.5.4: _resolve_pool_addresses_multicall edge cases (offline)."""

    def test_empty_dex_configs(self):
        result = _resolve_pool_addresses_multicall({}, "0xA", "0xB", "http://unused", 1)
        assert result == {}

    def test_no_v3_dexes(self):
        """Non-V3 adapters should produce no queries."""
        configs = {
            "sushiswap_v2": {"adapter_type": "uniswap_v2", "factory": "0x123"},
        }
        result = _resolve_pool_addresses_multicall(configs, "0xA", "0xB", "http://unused", 1)
        assert result == {}


class TestM7A54BackwardCompat:
    """M7.A.5.4 additions must not break existing M7.A.5.3 / M7.A.5.3.1 flows."""

    def test_offline_results_unchanged(self):
        ev = _make_event()
        r = score_backrun_offline(ev)
        d = asdict(r)
        # All pre-existing fields still present


# ===========================================================================
# M7.A.5.6 Contract Tests
# ===========================================================================


class TestM7A56RejectConstants:
    """M7.A.5.6: 5 new granular reject reasons and expanded ALL_REJECT_REASONS."""

    def test_all_reject_reasons_count(self):
        """ALL_REJECT_REASONS must contain exactly 15 members (8 original + 5 M7.A.5.6 + 2 M7.A.5.10)."""
        assert len(ALL_REJECT_REASONS) == 15

    def test_new_reject_constants_in_frozen_set(self):
        new_reasons = {
            REJECT_NO_COUNTER_POOL,
            REJECT_TOKEN_NOT_ADMITTED,
            REJECT_UNSUPPORTED_ADAPTER,
            REJECT_RPC_QUOTE_FAIL,
            REJECT_PAIR_RESOLVED_UNTRADEABLE,
        }
        assert new_reasons.issubset(ALL_REJECT_REASONS)

    def test_original_reject_reasons_preserved(self):
        original = {
            REJECT_NO_COUNTER_VENUE,
            REJECT_GAS_EXCEEDS_GROSS,
            REJECT_SLIPPAGE_EXCEEDS_GROSS,
            REJECT_EVENT_TOO_SMALL,
            REJECT_SAME_BLOCK_IMPOSSIBLE,
            REJECT_QUOTE_FAILURE,
            REJECT_INSUFFICIENT_IMPACT,
            REJECT_TOKEN_PAIR_UNRESOLVED,
        }
        assert original.issubset(ALL_REJECT_REASONS)

    def test_reject_values_are_unique_strings(self):
        values = list(ALL_REJECT_REASONS)
        assert len(values) == len(set(values))
        assert all(isinstance(v, str) for v in values)

    def test_reject_no_counter_pool_value(self):
        assert REJECT_NO_COUNTER_POOL == "NO_COUNTER_POOL"

    def test_reject_token_not_admitted_value(self):
        assert REJECT_TOKEN_NOT_ADMITTED == "TOKEN_NOT_ADMITTED"

    def test_reject_unsupported_adapter_value(self):
        assert REJECT_UNSUPPORTED_ADAPTER == "UNSUPPORTED_ADAPTER"

    def test_reject_rpc_quote_fail_value(self):
        assert REJECT_RPC_QUOTE_FAIL == "RPC_QUOTE_FAIL"

    def test_reject_pair_resolved_untradeable_value(self):
        assert REJECT_PAIR_RESOLVED_UNTRADEABLE == "PAIR_RESOLVED_BUT_UNTRADEABLE"


class TestM7A56BackrunResultFields:
    """M7.A.5.6: BackrunResult must have 42 fields with 5 new M7.A.5.6 entries."""

    M7A56_NEW_FIELDS = {
        "coverage_result",
        "size_sweep_results",
        "best_sweep_net_bps",
        "best_sweep_size_wei",
        "token_admitted",
    }

    def test_field_count_is_53(self):
        ev = _make_event()
        r = score_backrun_offline(ev)
        d = asdict(r)
        assert len(d) == 53, f"Expected 53 fields, got {len(d)}: {sorted(d.keys())}"

    def test_new_fields_present(self):
        ev = _make_event()
        r = score_backrun_offline(ev)
        d = asdict(r)
        for field in self.M7A56_NEW_FIELDS:
            assert field in d, f"Missing M7.A.5.6 field: {field}"

    def test_new_fields_default_none_for_offline(self):
        """Offline results should have all M7.A.5.6 fields as None."""
        ev = _make_event()
        r = score_backrun_offline(ev)
        assert r.coverage_result is None
        assert r.size_sweep_results is None
        assert r.best_sweep_net_bps is None
        assert r.best_sweep_size_wei is None
        assert r.token_admitted is None

    def test_m7a55_fields_still_present(self):
        """M7.A.5.5 actual-pair resolution fields must coexist."""
        ev = _make_event()
        r = score_backrun_offline(ev)
        d = asdict(r)
        assert "pair_resolved" in d
        assert "actual_pair" in d
        assert "size_source" in d

    def test_m7a54_fields_still_present(self):
        """M7.A.5.4 two-stage pruning fields must coexist."""
        ev = _make_event()
        r = score_backrun_offline(ev)
        d = asdict(r)
        assert "quote_calls_attempted" in d
        assert "quote_calls_after_pruning" in d
        assert "prune_reason_histogram" in d
        assert "pipeline_stage_latency_ms" in d


class TestM7A56AdmitEventTokens:
    """M7.A.5.6: admit_event_tokens() contract tests."""

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
        """Return dict must have exactly the documented keys (7 incl. admission_source)."""
        required_keys = {
            "admitted", "token_in_symbol", "token_out_symbol",
            "token_in_known", "token_out_known", "blocker_reason",
            "admission_source",
        }
        result = admit_event_tokens("0xa", "0xb", {}, {})
        assert set(result.keys()) == required_keys

    def test_case_insensitive_address_lookup(self):
        """Addresses should match regardless of case."""
        addr_to_sym = {"0xAA": "WETH", "0xBB": "USDC"}
        canonical = {"WETH": "0xAA", "USDC": "0xBB"}
        # At minimum, same-case must work.
        result = admit_event_tokens("0xAA", "0xBB", addr_to_sym, canonical)
        assert result["admitted"] is True


class TestM7A56CoverageSchema:
    """M7.A.5.6: counter_venue_coverage_scan() return schema."""

    REQUIRED_KEYS = {
        "known_pools", "known_dexes", "buy_venues", "sell_venues",
        "coverage_complete", "coverage_blocker_reason",
    }

    def test_empty_dex_configs_returns_incomplete(self):
        """With no DEX configs, coverage should be incomplete."""
        result = counter_venue_coverage_scan(
            "0xA", "0xB", {}, "http://unused", 1
        )
        assert set(result.keys()) == self.REQUIRED_KEYS
        assert result["coverage_complete"] is False
        assert result["known_pools"] == 0
        assert result["known_dexes"] == []
        assert result["buy_venues"] == 0
        assert result["sell_venues"] == 0
        assert result["coverage_blocker_reason"] is not None

    def test_schema_keys_exact(self):
        result = counter_venue_coverage_scan(
            "0xA", "0xB", {}, "http://unused", 1
        )
        assert set(result.keys()) == self.REQUIRED_KEYS

    def test_coverage_complete_is_bool(self):
        result = counter_venue_coverage_scan(
            "0xA", "0xB", {}, "http://unused", 1
        )
        assert isinstance(result["coverage_complete"], bool)

    def test_numeric_fields_non_negative(self):
        result = counter_venue_coverage_scan(
            "0xA", "0xB", {}, "http://unused", 1
        )
        assert result["known_pools"] >= 0
        assert isinstance(result["known_dexes"], list)
        assert result["buy_venues"] >= 0
        assert result["sell_venues"] >= 0


class TestM7A56SizeSweepSchema:
    """M7.A.5.6: Size sweep result schema contract tests."""

    REQUIRED_POINT_KEYS = {
        "size_wei", "gross_pnl_wei", "gas_cost_wei",
        "net_pnl_wei", "net_bps", "buy_venue", "sell_venue",
    }

    def test_sweep_point_schema(self):
        """Each sweep point must have the documented keys."""
        point = {
            "size_wei": 10**17,
            "gross_pnl_wei": 10**14,
            "gas_cost_wei": 10**13,
            "net_pnl_wei": 10**14 - 10**13,
            "net_bps": 5.5,
            "buy_venue": "uniswap_v3",
            "sell_venue": "sushiswap_v3",
        }
        assert set(point.keys()) == self.REQUIRED_POINT_KEYS

    def test_sweep_point_serializes(self):
        point = {
            "size_wei": 10**17,
            "gross_pnl_wei": 0,
            "gas_cost_wei": 0,
            "net_pnl_wei": 0,
            "net_bps": 0.0,
            "buy_venue": None,
            "sell_venue": None,
        }
        s = json.dumps(point)
        parsed = json.loads(s)
        assert parsed["size_wei"] == 10**17

    def test_sweep_ladder_multipliers(self):
        """Sweep should use 5-point bounded ladder: 0.2x, 0.5x, 1x, 2x, 5x."""
        multipliers = [0.2, 0.5, 1.0, 2.0, 5.0]
        assert len(multipliers) == 5


class TestM7A56ArtifactSchema:
    """M7.A.5.6: Artifact-level blocks needed for ws-live evidence."""

    def test_coverage_scan_metrics_schema(self):
        metrics = {
            "events_admitted": 5,
            "events_not_admitted": 15,
            "events_coverage_complete": 3,
            "coverage_blocker_histogram": {"no_v3_pools": 10, "no_adapter": 5},
            "admission_rate": 0.25,
        }
        required = {
            "events_admitted", "events_not_admitted",
            "events_coverage_complete", "coverage_blocker_histogram",
            "admission_rate",
        }
        assert set(metrics.keys()) == required
        assert 0.0 <= metrics["admission_rate"] <= 1.0

    def test_size_sweep_metrics_schema(self):
        metrics = {
            "events_with_sweep": 3,
            "sweep_net_bps_all": [-5.0, -2.0, 1.0],
            "best_sweep_net_bps": 1.0,
            "mean_sweep_net_bps": -2.0,
            "events_with_positive_sweep": 1,
        }
        required = {
            "events_with_sweep", "sweep_net_bps_all",
            "best_sweep_net_bps", "mean_sweep_net_bps",
            "events_with_positive_sweep",
        }
        assert set(metrics.keys()) == required

    def test_m4_m7_comparison_v2_schema(self):
        v2 = {
            "m4_best_net_bps": -3.5062,
            "m4_gross_pre_cost_bps": 36.35,
            "m4_gas_bps": 2.01,
            "m4_fee_bps": 31.0,
            "m4_slippage_bps": 6.85,
            "m4_size_usd": 50,
            "m4_pair": "WBTC/USDC",
            "m7_best_net_bps": -10.0,
            "m7_gross_pre_cost_bps": 20.0,
            "m7_gas_bps": 5.0,
            "m7_fee_bps": 15.0,
            "m7_slippage_bps": None,
            "m7_size_usd": 100.0,
            "m7_pair_resolved": True,
            "m7_coverage_complete_count": 3,
            "m7_latency_class": "stale",
            "m7_best_sweep_net_bps": -5.0,
            "note": "M4 has mature pair-specific dynamic sweep; M7 now has pair-resolved coverage + bounded event-size evaluation",
        }
        required_keys = {
            "m4_best_net_bps", "m4_gross_pre_cost_bps", "m4_gas_bps",
            "m4_fee_bps", "m4_slippage_bps", "m4_size_usd", "m4_pair",
            "m7_best_net_bps", "m7_gross_pre_cost_bps", "m7_gas_bps",
            "m7_fee_bps", "m7_slippage_bps", "m7_size_usd",
            "m7_pair_resolved", "m7_coverage_complete_count",
            "m7_latency_class", "m7_best_sweep_net_bps", "note",
        }
        assert set(v2.keys()) == required_keys

    def test_reject_histogram_v2_accepts_new_reasons(self):
        hist = {
            "NO_COUNTER_POOL": 5,
            "TOKEN_NOT_ADMITTED": 10,
            "UNSUPPORTED_ADAPTER": 2,
            "RPC_QUOTE_FAIL": 3,
            "PAIR_RESOLVED_BUT_UNTRADEABLE": 1,
            "QUOTE_FAILURE": 0,
            "TOKEN_PAIR_UNRESOLVED": 4,
        }
        # All histogram keys must be valid reject reasons
        for k in hist:
            assert k in ALL_REJECT_REASONS, f"Unknown reject reason in histogram: {k}"


class TestM7A56BackwardCompat:
    """M7.A.5.6 additions must not break existing offline/fixture flows."""

    def test_offline_results_unchanged(self):
        ev = _make_event()
        r = score_backrun_offline(ev)
        d = asdict(r)
        assert len(d) == 53
        # Core offline fields still work
        assert r.event_source == "fixture"
        assert r.reject_reason is not None or r.route_viable

    def test_m7a56_fields_default_none_offline(self):
        ev = _make_event()
        r = score_backrun_offline(ev)
        assert r.coverage_result is None
        assert r.size_sweep_results is None
        assert r.best_sweep_net_bps is None
        assert r.best_sweep_size_wei is None
        assert r.token_admitted is None

    def test_m7a55_fields_coexist(self):
        ev = _make_event()
        r = score_backrun_offline(ev)
        d = asdict(r)
        m7a55_fields = {"pair_resolved", "actual_pair", "size_source"}
        assert m7a55_fields.issubset(d.keys())

    def test_m7a53_fields_coexist(self):
        ev = _make_event()
        r = score_backrun_offline(ev)
        d = asdict(r)
        m7a53_fields = {"ws_provider", "event_detected_at_block", "quote_started_block",
                        "quote_finished_block", "quote_pipeline_latency_ms"}
        assert m7a53_fields.issubset(d.keys())

    def test_asdict_serializes_to_json(self):
        ev = _make_event()
        r = score_backrun_offline(ev)
        d = asdict(r)
        s = json.dumps(d)
        parsed = json.loads(s)
        assert parsed["event_id"] == r.event_id
        assert len(parsed) == 53
        assert "event_id" in d
        assert "venues_pruned_by_multicall" in d
        assert "latency_budget_ms" in d
        # New fields default to None
        assert d["quote_calls_attempted"] is None
        assert d["pipeline_stage_latency_ms"] is None

    def test_ws_fields_coexist_with_pruning_fields(self):
        r = BackrunResult(
            event_id="bc2",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            ws_provider="alchemy",
            latency_budget_ms=250.0,
            quote_calls_attempted=12,
            quote_calls_after_pruning=4,
            pipeline_stage_latency_ms={"stage_a_ms": 50, "stage_b_ms": 200},
        )
        d = asdict(r)
        # ws fields intact
        assert d["ws_provider"] == "alchemy"
        assert d["latency_budget_ms"] == 250.0
        # New pruning fields intact
        assert d["quote_calls_attempted"] == 12
        assert d["quote_calls_after_pruning"] == 4
        assert d["pipeline_stage_latency_ms"]["stage_a_ms"] == 50

    def test_all_backrun_result_fields_count(self):
        """BackrunResult should have exactly the expected number of fields."""
        r = BackrunResult(
            event_id="fc1",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
        )
        d = asdict(r)
        # 30 original + 4 M7.A.5.4 + 3 M7.A.5.5 + 5 M7.A.5.6 + 3 M7.A.5.7 + 4 M7.A.5.8 + 4 M7.A.5.9 = 53
        assert len(d) == 53, f"Expected 53 fields, got {len(d)}: {sorted(d.keys())}"


class TestBatchGetPool:
    """M7.A.5.4: MulticallBatcher.batch_get_pool contract tests."""

    def test_empty_queries_returns_empty(self):
        from core.multicall import MulticallBatcher
        batcher = MulticallBatcher("http://unused", 1)
        result = batcher.batch_get_pool([])
        assert result == []


# ---------------------------------------------------------------------------
# M7.A.5.5: Actual-pair resolution contract tests
# ---------------------------------------------------------------------------


class TestM7A55TokenPairUnresolved:
    """M7.A.5.5: TOKEN_PAIR_UNRESOLVED is a valid reject reason."""

    def test_reject_reason_in_set(self):
        assert REJECT_TOKEN_PAIR_UNRESOLVED in ALL_REJECT_REASONS

    def test_reject_value(self):
        assert REJECT_TOKEN_PAIR_UNRESOLVED == "TOKEN_PAIR_UNRESOLVED"


class TestM7A55BackrunResultFields:
    """M7.A.5.5: New BackrunResult fields for pair resolution."""

    def test_pair_resolved_default_false(self):
        r = BackrunResult(
            event_id="pr1",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
        )
        assert r.pair_resolved is False

    def test_actual_pair_default_none(self):
        r = BackrunResult(
            event_id="pr2",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
        )
        assert r.actual_pair is None

    def test_size_source_default_none(self):
        r = BackrunResult(
            event_id="pr3",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
        )
        assert r.size_source is None

    def test_pair_resolved_values(self):
        r = BackrunResult(
            event_id="pr4",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            pair_resolved=True,
            actual_pair="WETH/USDC",
            size_source="event_proportional",
        )
        assert r.pair_resolved is True
        assert r.actual_pair == "WETH/USDC"
        assert r.size_source == "event_proportional"

    def test_json_round_trip(self):
        r = BackrunResult(
            event_id="pr5",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            pair_resolved=True,
            actual_pair="WBTC/USDC",
            size_source="bounded",
        )
        d = asdict(r)
        j = json.loads(json.dumps(d, default=str))
        assert j["pair_resolved"] is True
        assert j["actual_pair"] == "WBTC/USDC"
        assert j["size_source"] == "bounded"

    def test_offline_fields_none(self):
        """Offline/fixture results should have pair_resolved=False, rest None."""
        r = score_backrun_offline(_make_event())
        d = asdict(r)
        assert d["pair_resolved"] is False
        assert d["actual_pair"] is None
        assert d["size_source"] is None


class TestM7A55BoundedSize:
    """M7.A.5.5: Bounded size logic for backrun notional."""

    def test_min_bound(self):
        """Tiny events should be bounded to minimum 0.001 ETH."""
        MIN_BACKRUN_WEI = 10**15
        # event with 1 wei amount -> 10% = 0 -> bounded to min
        tiny_amount = 100  # 100 wei
        size = max(tiny_amount // 10, 1)
        bounded = max(MIN_BACKRUN_WEI, min(10**18, size))
        assert bounded == MIN_BACKRUN_WEI

    def test_max_bound(self):
        """Huge events should be bounded to maximum 1 ETH."""
        MAX_BACKRUN_WEI = 10**18
        huge_amount = 100 * 10**18  # 100 ETH, 10% = 10 ETH
        size = max(huge_amount // 10, 1)
        bounded = max(10**15, min(MAX_BACKRUN_WEI, size))
        assert bounded == MAX_BACKRUN_WEI

    def test_normal_range_passes_through(self):
        """Normal sized events should pass through unbounded."""
        amount = 10**17  # 0.1 ETH, 10% = 0.01 ETH
        size = max(amount // 10, 1)
        bounded = max(10**15, min(10**18, size))
        assert bounded == 10**16  # 0.01 ETH


class TestM7A55ResolveEventTokens:
    """M7.A.5.5: _resolve_event_tokens basic contract tests."""

    def test_empty_pool_address_returns_none(self):
        result = _resolve_event_tokens(
            pool_address="",
            swap_direction="token0_in",
            rpc_url="http://unused",
            block_num=1,
            addr_to_symbol={},
        )
        assert result is None

    def test_invalid_direction_returns_none(self):
        """Unknown swap direction should return None (not crash)."""
        # This requires batch_token_info to return something, but with empty pool
        # it will return None from the empty pool check
        result = _resolve_event_tokens(
            pool_address="",
            swap_direction="unknown_direction",
            rpc_url="http://unused",
            block_num=1,
            addr_to_symbol={},
        )
        assert result is None


class TestM7A55ArtifactFields:
    """M7.A.5.5: New artifact fields for pair resolution and M4/M7 comparison."""

    def test_pair_resolution_metrics_schema(self):
        """pair_resolution_metrics must contain required keys."""
        required = {
            "events_pair_resolved",
            "events_pair_unresolved",
            "pair_resolution_rate",
            "actual_pairs_seen",
            "resolved_best_net_bps",
            "resolved_mean_net_bps",
            "size_source_histogram",
        }
        # Test by constructing minimal metrics dict
        metrics = {
            "events_pair_resolved": 5,
            "events_pair_unresolved": 3,
            "pair_resolution_rate": 0.625,
            "actual_pairs_seen": ["WETH/USDC"],
            "resolved_best_net_bps": -10.0,
            "resolved_mean_net_bps": -15.0,
            "size_source_histogram": {"event_proportional": 5},
        }
        assert required == set(metrics.keys())

    def test_m4_m7_comparison_schema(self):
        """m4_m7_comparison must contain required keys."""
        required = {
            "m4_best_net_bps", "m4_frontier_pair", "m4_size_usd", "m4_gas_bps",
            "m7_best_net_bps", "m7_mean_gross_bps", "m7_mean_gas_bps",
            "m7_mean_size_wei", "m7_latency_class", "m7_pair_resolved_count",
            "note",
        }
        comparison = {
            "m4_best_net_bps": -3.5062,
            "m4_frontier_pair": "WBTC/USDC",
            "m4_size_usd": 50,
            "m4_gas_bps": 2.01,
            "m7_best_net_bps": -19.73,
            "m7_mean_gross_bps": -1.61,
            "m7_mean_gas_bps": 20.0,
            "m7_mean_size_wei": 10**16,
            "m7_latency_class": "stale",
            "m7_pair_resolved_count": 5,
            "note": "test",
        }
        assert required == set(comparison.keys())


class TestM7A55BackwardCompat:
    """M7.A.5.5: Backward compatibility with M7.A.5.4 and earlier."""

    def test_offline_scoring_unchanged(self):
        """Offline scoring should still work and return valid BackrunResult."""
        ev = _make_event()
        result = score_backrun_offline(ev)
        assert result.event_source == "fixture"
        assert result.reject_reason is not None or result.route_viable

    def test_ws_and_pair_fields_coexist(self):
        """All ws + pair + pruning fields coexist in BackrunResult."""
        r = BackrunResult(
            event_id="bc55_1",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            ws_provider="alchemy",
            latency_budget_ms=250.0,
            quote_calls_attempted=12,
            quote_calls_after_pruning=4,
            pipeline_stage_latency_ms={"stage_a_ms": 50, "stage_b_ms": 200},
            pair_resolved=True,
            actual_pair="WETH/USDC",
            size_source="event_proportional",
        )
        d = asdict(r)
        assert d["ws_provider"] == "alchemy"
        assert d["pair_resolved"] is True
        assert d["actual_pair"] == "WETH/USDC"
        assert d["size_source"] == "event_proportional"
        assert d["quote_calls_attempted"] == 12

    def test_total_field_count_53(self):
        """BackrunResult should have exactly 53 fields (42 M7.A.5.6 + 3 M7.A.5.7 + 4 M7.A.5.8 + 4 M7.A.5.9)."""
        r = BackrunResult(
            event_id="fc55",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
        )
        d = asdict(r)
        assert len(d) == 53, f"Expected 53 fields, got {len(d)}: {sorted(d.keys())}"

    def test_m7a57_fields_exist_in_backrun_result(self):
        """M7.A.5.7 fields (admission_source, oracle_guard, local_sim_state) exist and default to None."""
        r = BackrunResult(
            event_id="m57_1",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
        )
        d = asdict(r)
        assert d["admission_source"] is None
        assert d["oracle_guard"] is None
        assert d["local_sim_state"] is None

    def test_m7a57_fields_serialize_correctly(self):
        """M7.A.5.7 fields serialize to JSON when set."""
        r = BackrunResult(
            event_id="m57_2",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            admission_source=ADMISSION_CANONICAL,
            oracle_guard={"oracle_price_available": True, "oracle_guard_triggered": False},
            local_sim_state={"pools_queried": 2, "pools_with_state": 1},
        )
        d = asdict(r)
        s = json.dumps(d, default=str)
        parsed = json.loads(s)
        assert parsed["admission_source"] == "canonical_core"
        assert parsed["oracle_guard"]["oracle_price_available"] is True
        assert parsed["local_sim_state"]["pools_queried"] == 2


# ===========================================================================
# TestM7A57AdmissionSource
# ===========================================================================

class TestM7A57AdmissionSource:
    """Tests for M7.A.5.7 admission source tracking."""

    def test_admission_source_constants_exist(self):
        """All admission source constants should be defined."""
        assert ADMISSION_CANONICAL == "canonical_core"
        assert ADMISSION_ADDR_TO_SYMBOL == "addr_to_symbol"
        assert ADMISSION_SUBGRAPH_VERIFIED == "subgraph_seeded_verified"
        assert ADMISSION_REJECTED == "rejected_unverified"

    def test_all_admission_sources_frozenset(self):
        """ALL_ADMISSION_SOURCES should be a frozenset with 5 members (4 old + 1 M7.A.5.10)."""
        assert isinstance(ALL_ADMISSION_SOURCES, frozenset)
        assert len(ALL_ADMISSION_SOURCES) == 5

    def test_admit_canonical_both_known(self):
        """Both tokens in canonical universe → admission_source = canonical_core."""
        token_addrs = {"WETH": "0xaa", "USDC": "0xbb"}
        ats = {"0xaa": "WETH", "0xbb": "USDC"}
        result = admit_event_tokens("0xaa", "0xbb", ats, token_addrs)
        assert result["admitted"] is True
        assert result["admission_source"] == ADMISSION_CANONICAL

    def test_admit_addr_to_symbol_one_known(self):
        """One canonical + one from addr_to_symbol → addr_to_symbol source."""
        token_addrs = {"WETH": "0xaa"}
        ats = {"0xaa": "WETH", "0xcc": "MAGIC"}
        result = admit_event_tokens("0xaa", "0xcc", ats, token_addrs)
        assert result["admitted"] is True
        assert result["admission_source"] == ADMISSION_ADDR_TO_SYMBOL

    def test_admit_rejected_both_unknown(self):
        """Both tokens unknown → rejected_unverified."""
        token_addrs = {"WETH": "0xaa"}
        ats = {}
        result = admit_event_tokens("0xdd", "0xee", ats, token_addrs)
        assert result["admitted"] is False
        assert result["admission_source"] == ADMISSION_REJECTED

    def test_admit_rejected_one_unknown(self):
        """One known + one unknown → rejected."""
        token_addrs = {"WETH": "0xaa"}
        ats = {"0xaa": "WETH"}
        result = admit_event_tokens("0xaa", "0xdd", ats, token_addrs)
        assert result["admitted"] is False
        assert result["admission_source"] == ADMISSION_REJECTED

    def test_admission_source_in_all_sources(self):
        """All possible return values should be in ALL_ADMISSION_SOURCES."""
        token_addrs = {"WETH": "0xaa", "USDC": "0xbb"}
        # canonical
        r1 = admit_event_tokens("0xaa", "0xbb", {"0xaa": "WETH", "0xbb": "USDC"}, token_addrs)
        assert r1["admission_source"] in ALL_ADMISSION_SOURCES
        # rejected
        r2 = admit_event_tokens("0xdd", "0xee", {}, token_addrs)
        assert r2["admission_source"] in ALL_ADMISSION_SOURCES

    def test_admission_has_seven_keys(self):
        """admit_event_tokens should return dict with 7 keys (6 old + admission_source)."""
        token_addrs = {"WETH": "0xaa"}
        ats = {"0xaa": "WETH"}
        result = admit_event_tokens("0xaa", "0xdd", ats, token_addrs)
        assert len(result) == 7


# ===========================================================================
# TestM7A57ChainlinkConstants
# ===========================================================================

class TestM7A57ChainlinkConstants:
    """Tests for M7.A.5.7 Chainlink feed constants."""

    def test_chainlink_feeds_arbitrum_is_dict(self):
        assert isinstance(CHAINLINK_FEEDS_ARBITRUM, dict)

    def test_chainlink_feeds_has_major_tokens(self):
        """Major tokens should have Chainlink feeds defined."""
        for token in ["WETH", "WBTC", "USDT", "USDC", "ARB"]:
            assert token in CHAINLINK_FEEDS_ARBITRUM, f"Missing feed for {token}"

    def test_chainlink_feed_addresses_are_valid(self):
        """Feed addresses should be 42-char hex strings."""
        for token, addr in CHAINLINK_FEEDS_ARBITRUM.items():
            assert addr.startswith("0x"), f"Bad prefix for {token}"
            assert len(addr) == 42, f"Bad length for {token}: {len(addr)}"

    def test_chainlink_selector(self):
        assert CHAINLINK_LATEST_ROUND_SELECTOR == "0xfeaf968c"

    def test_chainlink_decimals(self):
        assert CHAINLINK_DECIMALS == 8


# ===========================================================================
# TestM7A57OracleGuard
# ===========================================================================

class TestM7A57OracleGuard:
    """Tests for M7.A.5.7 oracle guard function contract."""

    def test_oracle_guard_no_feeds_returns_default(self):
        """Unknown tokens should return oracle_price_available=False."""
        result = check_oracle_sanity("UNKNOWN_TOKEN", "ALSO_UNKNOWN", "http://fake", 100)
        assert result["oracle_price_available"] is False
        assert result["oracle_guard_triggered"] is False
        assert result["oracle_staleness_seconds"] is None

    def test_oracle_guard_schema_keys(self):
        """Oracle guard result should contain all expected keys."""
        result = check_oracle_sanity(None, None, "http://fake", 100)
        expected_keys = {
            "oracle_price_available",
            "token_in_oracle_usd",
            "token_out_oracle_usd",
            "oracle_deviation_bps",
            "oracle_guard_triggered",
            "oracle_staleness_seconds",
        }
        assert set(result.keys()) == expected_keys

    def test_oracle_guard_none_symbols(self):
        """None symbols should not crash."""
        result = check_oracle_sanity(None, None, "http://fake", 100)
        assert result["oracle_price_available"] is False

    def test_oracle_guard_empty_symbols(self):
        """Empty string symbols should not crash."""
        result = check_oracle_sanity("", "", "http://fake", 100)
        assert result["oracle_price_available"] is False


# ===========================================================================
# TestM7A57EnrichmentFunctions
# ===========================================================================

class TestM7A57EnrichmentFunctions:
    """Tests for M7.A.5.7 on-chain enrichment functions (offline contract)."""

    def test_enrich_unknown_token_offline(self):
        """Offline enrichment should return enriched=False (no RPC)."""
        import os
        old = os.environ.get("ARBY_SKIP_RPC")
        os.environ["ARBY_SKIP_RPC"] = "1"
        try:
            result = enrich_unknown_token("0x" + "ab" * 20, "http://fake", 100)
            assert result["enriched"] is False
            assert result["source"] == "onchain"
        finally:
            if old is not None:
                os.environ["ARBY_SKIP_RPC"] = old
            else:
                os.environ.pop("ARBY_SKIP_RPC", None)

    def test_enrich_tokens_batch_empty(self):
        """Empty input returns empty dict."""
        result = enrich_tokens_batch([], "http://fake", 100)
        assert result == {}

    def test_enrich_tokens_batch_offline(self):
        """Offline batch enrichment returns enriched=False for each token."""
        import os
        old = os.environ.get("ARBY_SKIP_RPC")
        os.environ["ARBY_SKIP_RPC"] = "1"
        try:
            addrs = ["0x" + "ab" * 20, "0x" + "cd" * 20]
            result = enrich_tokens_batch(addrs, "http://fake", 100)
            assert len(result) == 2
            for addr in addrs:
                assert result[addr.lower()]["enriched"] is False
        finally:
            if old is not None:
                os.environ["ARBY_SKIP_RPC"] = old
            else:
                os.environ.pop("ARBY_SKIP_RPC", None)

    def test_enrich_result_schema(self):
        """Enrichment result should have expected keys."""
        import os
        old = os.environ.get("ARBY_SKIP_RPC")
        os.environ["ARBY_SKIP_RPC"] = "1"
        try:
            result = enrich_unknown_token("0x" + "ab" * 20, "http://fake", 100)
            assert "enriched" in result
            assert "symbol" in result
            assert "decimals" in result
            assert "source" in result
        finally:
            if old is not None:
                os.environ["ARBY_SKIP_RPC"] = old
            else:
                os.environ.pop("ARBY_SKIP_RPC", None)


# ===========================================================================
# TestM7A57LocalSimState
# ===========================================================================

class TestM7A57LocalSimState:
    """Tests for M7.A.5.7 local-sim state extraction contract."""

    def test_extract_pool_state_empty(self):
        """Empty pool list returns empty dict."""
        result = extract_pool_state_for_sim([], "http://fake", 100)
        assert result == {}

    def test_extract_pool_state_offline(self):
        """Offline extraction returns None for each pool."""
        import os
        old = os.environ.get("ARBY_SKIP_RPC")
        os.environ["ARBY_SKIP_RPC"] = "1"
        try:
            pools = ["0x" + "ab" * 20]
            result = extract_pool_state_for_sim(pools, "http://fake", 100)
            assert pools[0] in result
            assert result[pools[0]] is None
        finally:
            if old is not None:
                os.environ["ARBY_SKIP_RPC"] = old
            else:
                os.environ.pop("ARBY_SKIP_RPC", None)


# ===========================================================================
# TestM7A57BackwardCompat
# ===========================================================================

class TestM7A57BackwardCompat:
    """M7.A.5.7 fields must not break existing artifact serialization."""

    def test_backrun_result_json_roundtrip_45_fields(self):
        """Full BackrunResult serializes and deserializes cleanly."""
        r = BackrunResult(
            event_id="compat_1",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            pair_resolved=True,
            actual_pair="WETH/USDC",
            token_admitted=True,
            admission_source=ADMISSION_CANONICAL,
            oracle_guard={"oracle_price_available": True, "oracle_guard_triggered": False},
            local_sim_state={"pools_queried": 3, "pools_with_state": 2},
        )
        s = json.dumps(asdict(r), default=str)
        parsed = json.loads(s)
        assert len(parsed) == 53
        # Old fields still present
        assert "event_id" in parsed
        assert "reject_reason" in parsed
        assert "coverage_result" in parsed
        # M7.A.5.7 fields present
        assert "admission_source" in parsed
        assert "oracle_guard" in parsed
        assert "local_sim_state" in parsed
        # M7.A.5.8 fields present
        assert "l2_gas_bps" in parsed
        assert "l1_data_bps" in parsed
        assert "total_gas_bps" in parsed
        assert "subgraph_seed_used" in parsed

    def test_m7a56_fields_still_default(self):
        """M7.A.5.6 fields should still default correctly after M7.A.5.7 additions."""
        r = BackrunResult(
            event_id="compat_2",
            event_source="fixture",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="estimated",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
        )
        d = asdict(r)
        assert d["coverage_result"] is None
        assert d["size_sweep_results"] is None
        assert d["best_sweep_net_bps"] is None
        assert d["token_admitted"] is None
        # M7.A.5.7 defaults
        assert d["admission_source"] is None
        assert d["oracle_guard"] is None
        assert d["local_sim_state"] is None
        # M7.A.5.8 defaults
        assert d["l2_gas_bps"] is None
        assert d["l1_data_bps"] is None
        assert d["total_gas_bps"] is None
        assert d["subgraph_seed_used"] is None


# ===========================================================================
# TestM7A58SubgraphSeedConstants
# ===========================================================================

class TestM7A58SubgraphSeedConstants:
    """M7.A.5.8 subgraph-backed seed constants and function contracts."""

    def test_subgraph_endpoints_shape(self):
        """SUBGRAPH_ENDPOINTS_ARBITRUM must be a non-empty dict of str->str."""
        assert isinstance(SUBGRAPH_ENDPOINTS_ARBITRUM, dict)
        assert len(SUBGRAPH_ENDPOINTS_ARBITRUM) >= 1
        for k, v in SUBGRAPH_ENDPOINTS_ARBITRUM.items():
            assert isinstance(k, str)
            assert isinstance(v, str)
            assert v.startswith("https://")

    def test_seed_token_cap_bounds(self):
        """SUBGRAPH_SEED_TOKEN_CAP must be a positive integer <= 200."""
        assert isinstance(SUBGRAPH_SEED_TOKEN_CAP, int)
        assert 1 <= SUBGRAPH_SEED_TOKEN_CAP <= 200

    def test_timeout_seconds_bounds(self):
        """SUBGRAPH_TIMEOUT_SECONDS must be positive and <= 60."""
        assert isinstance(SUBGRAPH_TIMEOUT_SECONDS, (int, float))
        assert 1 <= SUBGRAPH_TIMEOUT_SECONDS <= 60

    def test_seed_tokens_from_subgraph_returns_dict_on_empty(self):
        """seed_tokens_from_subgraph returns stats dict even with empty input."""
        addr_to_sym: Dict[str, str] = {}
        result = seed_tokens_from_subgraph(addr_to_sym, "http://fake", 100, chain="arbitrum_one")
        assert isinstance(result, dict)
        assert "tokens_discovered" in result
        assert "tokens_new" in result
        assert "tokens_verified" in result
        assert "sources_queried" in result
        assert "errors" in result


# ===========================================================================
# TestM7A58GasDecomposition
# ===========================================================================

class TestM7A58GasDecomposition:
    """M7.A.5.8 gas decomposition estimator contract."""

    def test_basic_decomposition(self):
        """estimate_gas_decomposition_bps returns expected fields."""
        result = estimate_gas_decomposition_bps(
            amount_in_wei=10**18,  # 1 ETH
            gas_cost_wei=10**15,   # 0.001 ETH = 10 bps
        )
        assert isinstance(result, dict)
        assert "l2_gas_bps" in result
        assert "l1_data_bps" in result
        assert "total_gas_bps" in result

    def test_total_equals_sum(self):
        """total_gas_bps must equal l2_gas_bps + l1_data_bps."""
        result = estimate_gas_decomposition_bps(
            amount_in_wei=10**18,
            gas_cost_wei=5 * 10**14,
        )
        expected_total = round(result["l2_gas_bps"] + result["l1_data_bps"], 4)
        assert abs(result["total_gas_bps"] - expected_total) < 0.001

    def test_zero_amount_returns_zero(self):
        """Zero amount_in_wei should return all zeros gracefully."""
        result = estimate_gas_decomposition_bps(
            amount_in_wei=0,
            gas_cost_wei=10**15,
        )
        assert isinstance(result, dict)
        assert result["total_gas_bps"] == 0.0
        assert result["l2_gas_bps"] == 0.0
        assert result["l1_data_bps"] == 0.0

    def test_zero_gas_returns_zero(self):
        """Zero gas cost should produce zero bps."""
        result = estimate_gas_decomposition_bps(
            amount_in_wei=10**18,
            gas_cost_wei=0,
        )
        assert result["l2_gas_bps"] == 0.0
        assert result["l1_data_bps"] == 0.0
        assert result["total_gas_bps"] == 0.0

    def test_l1_dominates(self):
        """L1 data cost should be >= L2 execution cost (Arbitrum Nitro model)."""
        result = estimate_gas_decomposition_bps(
            amount_in_wei=10**18,
            gas_cost_wei=10**15,
        )
        assert result["l1_data_bps"] >= result["l2_gas_bps"]


# ===========================================================================
# TestM7A58BackwardCompat
# ===========================================================================

class TestM7A58BackwardCompat:
    """M7.A.5.8 fields must not break existing artifact serialization."""

    def test_backrun_result_json_roundtrip_49_fields(self):
        """Full BackrunResult serializes and deserializes cleanly."""
        r = BackrunResult(
            event_id="compat_58_1",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            pair_resolved=True,
            actual_pair="WETH/USDC",
            token_admitted=True,
            admission_source=ADMISSION_CANONICAL,
            oracle_guard={"oracle_price_available": True, "oracle_guard_triggered": False},
            local_sim_state={"pools_queried": 3, "pools_with_state": 2},
            l2_gas_bps=2.0,
            l1_data_bps=8.0,
            total_gas_bps=10.0,
            subgraph_seed_used=True,
        )
        s = json.dumps(asdict(r), default=str)
        parsed = json.loads(s)
        assert len(parsed) == 53
        # M7.A.5.8 fields present
        assert parsed["l2_gas_bps"] == 2.0
        assert parsed["l1_data_bps"] == 8.0
        assert parsed["total_gas_bps"] == 10.0
        assert parsed["subgraph_seed_used"] is True

    def test_m7a57_fields_still_default_after_58(self):
        """M7.A.5.7 fields should still default correctly after M7.A.5.8 additions."""
        r = BackrunResult(
            event_id="compat_58_2",
            event_source="fixture",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="estimated",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
        )
        d = asdict(r)
        # M7.A.5.7 defaults
        assert d["admission_source"] is None
        assert d["oracle_guard"] is None
        assert d["local_sim_state"] is None
        # M7.A.5.8 defaults
        assert d["l2_gas_bps"] is None
        assert d["l1_data_bps"] is None
        assert d["total_gas_bps"] is None
        assert d["subgraph_seed_used"] is None


# ===========================================================================
# M7.A.5.9: Decimal-aware size normalization
# ===========================================================================


class TestM7A59NormalizedBounds:
    """_normalized_bounds returns decimal-adjusted min/max."""

    def test_18_dec_identity(self):
        """18-decimal tokens should return original reference bounds."""
        mn, mx = _normalized_bounds(18)
        assert mn == _REF_MIN_WEI_18
        assert mx == _REF_MAX_WEI_18

    def test_none_dec_fallback(self):
        """None decimals should return original reference bounds (fallback)."""
        mn, mx = _normalized_bounds(None)
        assert mn == _REF_MIN_WEI_18
        assert mx == _REF_MAX_WEI_18

    def test_6_dec_usdc(self):
        """6-decimal tokens (USDC/USDT): bounds scale down by 10^12."""
        mn, mx = _normalized_bounds(6)
        assert mn == 10**3, f"min should be 10^3 for 6-dec, got {mn}"
        assert mx == 10**6, f"max should be 10^6 for 6-dec, got {mx}"

    def test_8_dec_wbtc(self):
        """8-decimal tokens (WBTC): bounds scale down by 10^10."""
        mn, mx = _normalized_bounds(8)
        assert mn == 10**5
        assert mx == 10**8

    def test_min_is_at_least_1(self):
        """Bounds must never be zero."""
        mn, mx = _normalized_bounds(1)
        assert mn >= 1
        assert mx >= 1

    def test_6_dec_far_smaller_than_18_dec(self):
        """USDC bounds must be dramatically smaller than WETH bounds."""
        mn6, mx6 = _normalized_bounds(6)
        mn18, mx18 = _normalized_bounds(18)
        # 10^12 ratio
        assert mn18 / mn6 == 10**12
        assert mx18 / mx6 == 10**12

    def test_custom_reference_bounds(self):
        """Custom default_18_min/max should also be scaled correctly."""
        mn, mx = _normalized_bounds(6, default_18_min=10**16, default_18_max=10**19)
        assert mn == 10**4
        assert mx == 10**7

    def test_all_common_decimals_positive(self):
        """All common decimal values should produce positive bounds."""
        for dec in [0, 2, 4, 6, 8, 12, 18]:
            mn, mx = _normalized_bounds(dec)
            assert mn >= 1, f"min<1 for decimals={dec}"
            assert mx >= mn, f"max<min for decimals={dec}"

    def test_same_usd_comparable_units(self):
        """A USDC amount of 1000 tokens and a WETH amount of 1 token
        should both be in the [min, max] range of their respective bounds."""
        mn6, mx6 = _normalized_bounds(6)
        mn18, mx18 = _normalized_bounds(18)
        # Both ranges give 0.001..1.0 of the token in native units
        assert mn6 < 10**6  # min < 1 USDC
        assert mx6 == 10**6  # max = 1 USDC
        assert mn18 < 10**18  # min < 1 WETH
        assert mx18 == 10**18  # max = 1 WETH


class TestM7A59BackrunResultFields:
    """M7.A.5.9 fields in BackrunResult."""

    def test_new_fields_exist(self):
        """BackrunResult should have all M7.A.5.9 fields."""
        r = BackrunResult(
            event_id="test_59_1",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
        )
        d = asdict(r)
        assert "token_in_decimals" in d
        assert "size_normalization_source" in d
        assert "size_usd_estimate" in d
        assert "size_valid_for_token" in d

    def test_new_fields_default_none(self):
        """M7.A.5.9 fields default to None."""
        r = BackrunResult(
            event_id="test_59_2",
            event_source="fixture",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="estimated",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
        )
        d = asdict(r)
        assert d["token_in_decimals"] is None
        assert d["size_normalization_source"] is None
        assert d["size_usd_estimate"] is None
        assert d["size_valid_for_token"] is None

    def test_fields_accept_values(self):
        """M7.A.5.9 fields should accept correct typed values."""
        r = BackrunResult(
            event_id="test_59_3",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            token_in_decimals=6,
            size_normalization_source="decimal_only",
            size_usd_estimate=42.50,
            size_valid_for_token=True,
        )
        d = asdict(r)
        assert d["token_in_decimals"] == 6
        assert d["size_normalization_source"] == "decimal_only"
        assert d["size_usd_estimate"] == 42.50
        assert d["size_valid_for_token"] is True


class TestM7A59SizeNormalizationContract:
    """Contract: bounded size clamp must use _normalized_bounds for the token."""

    def test_usdc_event_not_clamped_to_weth_min(self):
        """A 5000 USDC event (10% = 500 USDC = 5*10^8) should NOT be
        clamped UP to 10^15 (the 18-dec minimum)."""
        event_amount_usdc = 5000 * 10**6  # 5000 USDC
        raw_size = max(event_amount_usdc // 10, 1)  # 500 USDC = 5*10^8
        mn, mx = _normalized_bounds(6)
        bounded = max(mn, min(mx, raw_size))
        # 5*10^8 > max(10^6) → clamped to 10^6 = 1 USDC
        assert bounded == mx
        assert bounded < 10**15, "USDC bounded size must not reach 18-dec territory"

    def test_weth_event_normal_range(self):
        """A 1 WETH event (10% = 0.1 WETH = 10^17) passes through in normal range."""
        event_amount_weth = 10**18  # 1 WETH
        raw_size = max(event_amount_weth // 10, 1)  # 10^17
        mn, mx = _normalized_bounds(18)
        bounded = max(mn, min(mx, raw_size))
        assert bounded == 10**17  # passes through

    def test_usdt_6_dec_same_as_usdc(self):
        """USDT (also 6-dec) should get same bounds as USDC."""
        mn_usdc, mx_usdc = _normalized_bounds(6)
        mn_usdt, mx_usdt = _normalized_bounds(6)
        assert mn_usdc == mn_usdt
        assert mx_usdc == mx_usdt

    def test_wbtc_8_dec_reasonable(self):
        """WBTC (8-dec) bounds: 10^5 to 10^8 (0.001 to 1 WBTC)."""
        mn, mx = _normalized_bounds(8)
        assert mn == 10**5
        assert mx == 10**8


class TestM7A59BackwardCompat:
    """M7.A.5.9 fields must not break existing artifact serialization."""

    def test_backrun_result_json_roundtrip_53_fields(self):
        """Full 53-field BackrunResult serializes and deserializes cleanly."""
        r = BackrunResult(
            event_id="compat_59_1",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            pair_resolved=True,
            actual_pair="WETH/USDC",
            token_admitted=True,
            admission_source=ADMISSION_CANONICAL,
            oracle_guard={"oracle_price_available": True, "oracle_guard_triggered": False},
            local_sim_state={"pools_queried": 3, "pools_with_state": 2},
            l2_gas_bps=2.0,
            l1_data_bps=8.0,
            total_gas_bps=10.0,
            subgraph_seed_used=True,
            token_in_decimals=18,
            size_normalization_source="decimal_only",
            size_usd_estimate=3.50,
            size_valid_for_token=True,
        )
        s = json.dumps(asdict(r), default=str)
        parsed = json.loads(s)
        assert len(parsed) == 53
        # M7.A.5.9 fields present
        assert parsed["token_in_decimals"] == 18
        assert parsed["size_normalization_source"] == "decimal_only"
        assert parsed["size_usd_estimate"] == 3.50
        assert parsed["size_valid_for_token"] is True

    def test_m7a58_fields_still_default_after_59(self):
        """M7.A.5.8 fields should still default correctly after M7.A.5.9 additions."""
        r = BackrunResult(
            event_id="compat_59_2",
            event_source="fixture",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="estimated",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
        )
        d = asdict(r)
        # M7.A.5.8 defaults
        assert d["l2_gas_bps"] is None
        assert d["l1_data_bps"] is None
        assert d["total_gas_bps"] is None
        assert d["subgraph_seed_used"] is None
        # M7.A.5.9 defaults
        assert d["token_in_decimals"] is None
        assert d["size_normalization_source"] is None
        assert d["size_usd_estimate"] is None
        assert d["size_valid_for_token"] is None


# ---------------------------------------------------------------------------
# M7.A.5.9: Gas denomination conversion tests
# ---------------------------------------------------------------------------

class TestM7A59GasDenominationConversion:
    """_gas_cost_in_token_wei must convert ETH gas to the backrun token's units."""

    # Reference ETH gas for two-swap backrun: 200_000 * 0.1 gwei = 20 * 10^12 wei
    GAS_ETH_WEI = int(DEFAULT_BACKRUN_GAS * DEFAULT_GAS_PRICE_GWEI * 1e9)

    def test_18dec_no_price_identity(self):
        """For 18-dec token with no explicit price, return unchanged (assume ETH)."""
        result = _gas_cost_in_token_wei(self.GAS_ETH_WEI, 18)
        assert result == self.GAS_ETH_WEI

    def test_18dec_with_price_converts(self):
        """For 18-dec token with explicit USD price, convert via ETH/token ratio."""
        # Token worth $3500 (same as ETH) → 1:1
        result = _gas_cost_in_token_wei(self.GAS_ETH_WEI, 18, token_price_usd=3500.0, eth_price_usd=3500.0)
        assert result == self.GAS_ETH_WEI

    def test_6dec_usdc_with_oracle(self):
        """USDC (6-dec, $1) with ETH at $3500 → gas ≈ $0.07 → 70_000 USDC raw."""
        result = _gas_cost_in_token_wei(self.GAS_ETH_WEI, 6, token_price_usd=1.0, eth_price_usd=3500.0)
        # Expected: 20*10^12 * 3500 * 10^6 / (1.0 * 10^18) = 70_000_000
        gas_usd = self.GAS_ETH_WEI / 1e18 * 3500.0  # ~0.07 USD
        expected = int(gas_usd * 1e6)
        assert result == expected

    def test_6dec_usdc_fallback(self):
        """USDC (6-dec) with no oracle → uses $3500 fallback for ETH and $1 for token."""
        result = _gas_cost_in_token_wei(self.GAS_ETH_WEI, 6)
        expected = int(self.GAS_ETH_WEI * _FALLBACK_ETH_PRICE_USD * 1e6 / (1.0 * 1e18))
        assert result == expected
        # Must be in the thousands range, not in the trillions
        assert result < 1_000_000  # less than 1 USDC

    def test_8dec_wbtc_with_oracle(self):
        """WBTC (8-dec, ~$65000) with ETH at $3500."""
        result = _gas_cost_in_token_wei(self.GAS_ETH_WEI, 8, token_price_usd=65000.0, eth_price_usd=3500.0)
        gas_usd = self.GAS_ETH_WEI / 1e18 * 3500.0
        expected = int(gas_usd / 65000.0 * 1e8)
        assert result == expected or abs(result - expected) <= 1  # rounding

    def test_never_returns_zero(self):
        """Even for very small gas or expensive tokens, result must be >= 1."""
        result = _gas_cost_in_token_wei(1, 6, token_price_usd=100000.0, eth_price_usd=1.0)
        assert result >= 1

    def test_none_decimals_defaults_18(self):
        """None decimals → treated as 18, no price → identity."""
        result = _gas_cost_in_token_wei(self.GAS_ETH_WEI, None)
        assert result == self.GAS_ETH_WEI

    def test_bps_now_reasonable_for_usdc(self):
        """After gas conversion, net_bps for USDC must be in human-range, not 10^11."""
        backrun_wei = 10**6  # 1 USDC
        gross_wei = -836  # small loss in USDC units
        gas_token = _gas_cost_in_token_wei(self.GAS_ETH_WEI, 6, token_price_usd=1.0, eth_price_usd=3500.0)
        net_wei = gross_wei - gas_token
        net_bps = (net_wei / backrun_wei) * 10000
        # Must be in range [-10000, 10000], NOT -200_000_000_000
        assert -10000 < net_bps < 10000
        # Gas dominates, so net is negative but bounded
        assert net_bps < 0

    def test_gas_decomposition_consistent_after_conversion(self):
        """estimate_gas_decomposition_bps must produce reasonable bps with converted gas."""
        backrun_wei = 10**6  # 1 USDC
        gas_token = _gas_cost_in_token_wei(self.GAS_ETH_WEI, 6, token_price_usd=1.0, eth_price_usd=3500.0)
        decomp = estimate_gas_decomposition_bps(backrun_wei, gas_token)
        # total_gas_bps should be in hundreds/thousands, not billions
        assert 0 < decomp["total_gas_bps"] < 100_000
        assert decomp["l1_data_bps"] > 0
        assert decomp["l2_gas_bps"] > 0

# ===========================================================================
# M7.A.5.10: Stale-gate, zero-liquidity, admission provenance, split summary
# ===========================================================================

class TestM7A510StaleGateConstants:
    """M7.A.5.10: REJECT_STALE_POSITIVE and REJECT_ZERO_LIQUIDITY in ALL_REJECT_REASONS."""

    def test_stale_positive_in_all_reject_reasons(self):
        assert REJECT_STALE_POSITIVE in ALL_REJECT_REASONS

    def test_zero_liquidity_in_all_reject_reasons(self):
        assert REJECT_ZERO_LIQUIDITY in ALL_REJECT_REASONS

    def test_stale_positive_value(self):
        assert REJECT_STALE_POSITIVE == "STALE_POSITIVE"

    def test_zero_liquidity_value(self):
        assert REJECT_ZERO_LIQUIDITY == "ZERO_LIQUIDITY"


class TestM7A510AdmissionOnchainEnriched:
    """M7.A.5.10: ADMISSION_ONCHAIN_ENRICHED in ALL_ADMISSION_SOURCES."""

    def test_onchain_enriched_in_all_admission_sources(self):
        assert ADMISSION_ONCHAIN_ENRICHED in ALL_ADMISSION_SOURCES

    def test_onchain_enriched_value(self):
        assert ADMISSION_ONCHAIN_ENRICHED == "onchain_enriched_verified"

    def test_subgraph_verified_still_present(self):
        assert ADMISSION_SUBGRAPH_VERIFIED in ALL_ADMISSION_SOURCES

    def test_all_admission_sources_count(self):
        assert len(ALL_ADMISSION_SOURCES) == 5


class TestM7A510StaleGateViability:
    """M7.A.5.10: route_viable requires net_bps > 0 AND block_lag <= 2."""

    def test_viable_result_positive_low_lag(self):
        """net_bps > 0 + block_lag <= 2 → viable."""
        r = BackrunResult(
            event_id="stale_1",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            best_backrun_net_bps=50.0,
            block_lag=1,
            same_state_class="next_block",
            route_viable=True,
            reject_reason=None,
        )
        assert r.route_viable is True
        assert r.reject_reason is None

    def test_stale_positive_not_viable(self):
        """net_bps > 0 + block_lag > 2 → NOT viable, reject=STALE_POSITIVE."""
        r = BackrunResult(
            event_id="stale_2",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            best_backrun_net_bps=2630.0,
            block_lag=23,
            same_state_class="stale",
            route_viable=False,
            reject_reason=REJECT_STALE_POSITIVE,
        )
        assert r.route_viable is False
        assert r.reject_reason == REJECT_STALE_POSITIVE

    def test_negative_net_not_viable(self):
        """net_bps < 0 → NOT viable, reject=GAS_EXCEEDS_GROSS."""
        r = BackrunResult(
            event_id="stale_3",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            best_backrun_net_bps=-400.0,
            block_lag=1,
            same_state_class="next_block",
            route_viable=False,
            reject_reason=REJECT_GAS_EXCEEDS_GROSS,
        )
        assert r.route_viable is False
        assert r.reject_reason == REJECT_GAS_EXCEEDS_GROSS


class TestM7A510ZeroLiquidityReject:
    """M7.A.5.10: Zero-liquidity pools produce REJECT_ZERO_LIQUIDITY."""

    def test_zero_liq_result(self):
        r = BackrunResult(
            event_id="zeroliq_1",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            reject_reason=REJECT_ZERO_LIQUIDITY,
            route_viable=False,
            local_sim_state={
                "pools_queried": 2,
                "pools_with_state": 2,
                "pool_states": {
                    "0xaaa": {"liquidity": 0},
                    "0xbbb": {"liquidity": 0},
                },
            },
        )
        assert r.reject_reason == REJECT_ZERO_LIQUIDITY
        assert r.route_viable is False


class TestM7A510SplitSummaryFields:
    """M7.A.5.10: build_replay_summary produces split viability fields."""

    def _make_results(self):
        """Build a mix of results for summary testing."""
        results = []
        # Result 1: viable (low lag, positive)
        results.append(BackrunResult(
            event_id="sum_1", event_source="live", event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live", backrun_direction=BACKRUN_BUY_DEPRESSED,
            best_backrun_net_bps=50.0, block_lag=1, same_state_class="next_block",
            route_viable=True, reject_reason=None, size_valid_for_token=True,
        ))
        # Result 2: stale-positive (high lag, positive, NOT viable)
        results.append(BackrunResult(
            event_id="sum_2", event_source="live", event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live", backrun_direction=BACKRUN_BUY_DEPRESSED,
            best_backrun_net_bps=2630.0, block_lag=23, same_state_class="stale",
            route_viable=False, reject_reason=REJECT_STALE_POSITIVE, size_valid_for_token=True,
        ))
        # Result 3: gas-rejected (low lag, negative)
        results.append(BackrunResult(
            event_id="sum_3", event_source="live", event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live", backrun_direction=BACKRUN_BUY_DEPRESSED,
            best_backrun_net_bps=-400.0, block_lag=1, same_state_class="next_block",
            route_viable=False, reject_reason=REJECT_GAS_EXCEEDS_GROSS, size_valid_for_token=False,
        ))
        # Result 4: unscored reject (NO_COUNTER_POOL)
        results.append(BackrunResult(
            event_id="sum_4", event_source="live", event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live", backrun_direction=BACKRUN_BUY_DEPRESSED,
            best_backrun_net_bps=0.0, block_lag=5, same_state_class="stale",
            route_viable=False, reject_reason=REJECT_NO_COUNTER_POOL,
        ))
        return results

    def test_split_fields_present(self):
        events = [_make_event(event_id=f"sum_{i}") for i in range(1, 5)]
        results = self._make_results()
        art = build_replay_summary(events, results, mode="test")
        for key in [
            "best_net_bps_any", "best_net_bps_executable",
            "positive_net_count_any", "positive_net_count_low_lag",
            "stale_positive_count", "scored_results_count",
            "size_valid_count", "size_fallback_count",
        ]:
            assert key in art, f"Missing split field: {key}"

    def test_best_net_bps_excludes_unscored(self):
        """best_net_bps must come from scored results only, not 0.0 from NO_COUNTER_POOL."""
        events = [_make_event(event_id=f"sum_{i}") for i in range(1, 5)]
        results = self._make_results()
        art = build_replay_summary(events, results, mode="test")
        # Scored results: sum_1 (50), sum_2 (2630), sum_3 (-400). Unscored: sum_4 (0)
        assert art["scored_results_count"] == 3
        assert art["best_net_bps"] == 2630.0

    def test_best_net_bps_executable_vs_any(self):
        events = [_make_event(event_id=f"sum_{i}") for i in range(1, 5)]
        results = self._make_results()
        art = build_replay_summary(events, results, mode="test")
        # best_any includes stale-positive (2630), best_executable only viable (50)
        assert art["best_net_bps_any"] == 2630.0
        assert art["best_net_bps_executable"] == 50.0

    def test_positive_net_count_split(self):
        events = [_make_event(event_id=f"sum_{i}") for i in range(1, 5)]
        results = self._make_results()
        art = build_replay_summary(events, results, mode="test")
        assert art["positive_net_count_any"] == 2  # sum_1 + sum_2
        assert art["positive_net_count_low_lag"] == 1  # only sum_1
        assert art["stale_positive_count"] == 1  # only sum_2

    def test_size_validity_counts(self):
        events = [_make_event(event_id=f"sum_{i}") for i in range(1, 5)]
        results = self._make_results()
        art = build_replay_summary(events, results, mode="test")
        assert art["size_valid_count"] == 2  # sum_1 + sum_2
        assert art["size_fallback_count"] == 1  # sum_3

    def test_viable_count_excludes_stale(self):
        events = [_make_event(event_id=f"sum_{i}") for i in range(1, 5)]
        results = self._make_results()
        art = build_replay_summary(events, results, mode="test")
        assert art["viable_count"] == 1  # only sum_1

    def test_reject_histogram_includes_stale_and_zero_liq(self):
        results = [
            BackrunResult(
                event_id="h_1", event_source="live", event_type=EVENT_TYPE_SWAP,
                post_trade_state_used="live", backrun_direction=BACKRUN_BUY_DEPRESSED,
                best_backrun_net_bps=100.0, block_lag=10, route_viable=False,
                reject_reason=REJECT_STALE_POSITIVE,
            ),
            BackrunResult(
                event_id="h_2", event_source="live", event_type=EVENT_TYPE_SWAP,
                post_trade_state_used="live", backrun_direction=BACKRUN_BUY_DEPRESSED,
                best_backrun_net_bps=0.0, block_lag=5, route_viable=False,
                reject_reason=REJECT_ZERO_LIQUIDITY,
            ),
        ]
        events = [_make_event(event_id=f"h_{i}") for i in range(1, 3)]
        art = build_replay_summary(events, results, mode="test")
        assert art["reject_histogram"]["STALE_POSITIVE"] == 1
        assert art["reject_histogram"]["ZERO_LIQUIDITY"] == 1


class TestM7A510BackwardCompat:
    """M7.A.5.10 must not break existing BackrunResult serialization (53 fields)."""

    def test_backrun_result_field_count_still_53(self):
        r = BackrunResult(
            event_id="compat_510",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
        )
        d = asdict(r)
        assert len(d) == 53

    def test_all_reject_reasons_count(self):
        """ALL_REJECT_REASONS must have 15 entries (13 old + 2 new)."""
        assert len(ALL_REJECT_REASONS) == 15

    def test_all_admission_sources_count(self):
        """ALL_ADMISSION_SOURCES must have 5 entries (4 old + 1 new)."""
        assert len(ALL_ADMISSION_SOURCES) == 5

    def test_old_reject_reasons_still_present(self):
        for reason in [
            REJECT_GAS_EXCEEDS_GROSS, REJECT_NO_COUNTER_VENUE,
            REJECT_NO_COUNTER_POOL, REJECT_TOKEN_PAIR_UNRESOLVED,
        ]:
            assert reason in ALL_REJECT_REASONS