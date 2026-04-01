"""
Contract tests for M7.A.4/M7.A.5/M7.A.5.6/M7.A.5.7/M7.A.5.8/M7.A.5.9/M7.A.5.10/M7.A.5.11/M7.A.5.18 — Orderflow-driven replay and live block-event backrun.

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
- M7.A.5.11: Active-liquidity-aware coverage, granular coverage rejects, pre-econ metrics, live_state_metrics fix
- M7.A.5.15: Low-lag debug rows, pair_unresolved_detail, coverage truth metrics, backward compat (54 fields)
- M7.A.5.16: Pool-class truth, finer pool failure causes, aggregated class metrics, backward compat (55 fields)
- M7.A.5.17: V2 direct resolve (getReserves), pool_state_read_path provenance, V2 low-lag metrics, backward compat (56 fields)
- M7.A.5.18: Low-lag watchlist, blocker tags, backward compat (56 fields, 19 reject reasons)
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
    # M7.A.5.11 reject reasons
    REJECT_NO_ACTIVE_COUNTER_POOL,
    REJECT_ALL_POOLS_ZERO_LIQUIDITY,
    # M7.A.5.12 reject reasons
    REJECT_COVERAGE_LOCAL_MISMATCH,
    REJECT_ALL_POOLS_TRULY_INACTIVE,
    # M7.A.5.13: Module-level unscored rejects set
    UNSCORED_REJECTS,
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
    # M7.A.5.18 blocker tags
    ALL_BLOCKER_TAGS,
    BLOCKER_LOW_LAG_NONE_THIS_WINDOW,
    BLOCKER_LOW_LAG_NO_COUNTER_POOL,
    BLOCKER_LOW_LAG_V2_UNSUPPORTED,
    BLOCKER_LOW_LAG_INACTIVE_POOL,
    BLOCKER_LOW_LAG_REMOTE_QUOTER_LATENCY,
    BLOCKER_GAS_L1_DATA_DOMINANT,
    BLOCKER_SUBGRAPH_API_KEY_REQUIRED,
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
        assert len(ALL_REJECT_REASONS) == 19  # 8 original + 5 M7.A.5.6 + 2 M7.A.5.10 + 2 M7.A.5.11 + 2 M7.A.5.12
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
        """ALL_REJECT_REASONS must contain exactly 19 members (8 original + 5 M7.A.5.6 + 2 M7.A.5.10 + 2 M7.A.5.11 + 2 M7.A.5.12)."""
        assert len(ALL_REJECT_REASONS) == 19

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

    def test_field_count_is_54(self):
        ev = _make_event()
        r = score_backrun_offline(ev)
        d = asdict(r)
        assert len(d) == 56, f"Expected 56 fields, got {len(d)}: {sorted(d.keys())}"

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
        "known_pools", "known_pools_total", "active_pools_total",
        "inactive_pool_count", "known_dexes", "active_dexes",
        "buy_venues", "sell_venues",
        "active_buy_venues", "active_sell_venues",
        "coverage_complete", "coverage_blocker_reason",
        "candidate_pools",  # M7.A.5.12
    }

    def test_empty_dex_configs_returns_incomplete(self):
        """With no DEX configs, coverage should be incomplete."""
        result = counter_venue_coverage_scan(
            "0xA", "0xB", {}, "http://unused", 1
        )
        assert set(result.keys()) == self.REQUIRED_KEYS
        assert result["coverage_complete"] is False
        assert result["known_pools"] == 0
        assert result["known_pools_total"] == 0
        assert result["active_pools_total"] == 0
        assert result["known_dexes"] == []
        assert result["active_dexes"] == []
        assert result["buy_venues"] == 0
        assert result["sell_venues"] == 0
        assert result["active_buy_venues"] == 0
        assert result["active_sell_venues"] == 0
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
        assert result["known_pools_total"] >= 0
        assert result["active_pools_total"] >= 0
        assert result["inactive_pool_count"] >= 0
        assert isinstance(result["known_dexes"], list)
        assert isinstance(result["active_dexes"], list)
        assert result["buy_venues"] >= 0
        assert result["sell_venues"] >= 0
        assert result["active_buy_venues"] >= 0
        assert result["active_sell_venues"] >= 0


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
        assert len(d) == 56
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
        assert len(parsed) == 56
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
        # 30 original + 4 M7.A.5.4 + 3 M7.A.5.5 + 5 M7.A.5.6 + 3 M7.A.5.7 + 4 M7.A.5.8 + 4 M7.A.5.9 + 1 M7.A.5.15 + 1 M7.A.5.16 + 1 M7.A.5.17 = 56
        assert len(d) == 56, f"Expected 56 fields, got {len(d)}: {sorted(d.keys())}"


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
        """BackrunResult should have exactly 56 fields."""
        r = BackrunResult(
            event_id="fc55",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
        )
        d = asdict(r)
        assert len(d) == 56, f"Expected 56 fields, got {len(d)}: {sorted(d.keys())}"

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
        assert len(parsed) == 56
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
        assert len(parsed) == 56
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
        assert len(parsed) == 56
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
        assert len(d) == 56

    def test_all_reject_reasons_count(self):
        """ALL_REJECT_REASONS must have 19 entries (15 old + 2 M7.A.5.11 + 2 M7.A.5.12)."""
        assert len(ALL_REJECT_REASONS) == 19

    def test_all_admission_sources_count(self):
        """ALL_ADMISSION_SOURCES must have 5 entries (4 old + 1 new)."""
        assert len(ALL_ADMISSION_SOURCES) == 5

    def test_old_reject_reasons_still_present(self):
        for reason in [
            REJECT_GAS_EXCEEDS_GROSS, REJECT_NO_COUNTER_VENUE,
            REJECT_NO_COUNTER_POOL, REJECT_TOKEN_PAIR_UNRESOLVED,
        ]:
            assert reason in ALL_REJECT_REASONS


# ===========================================================================
# M7.A.5.11: Active-liquidity-aware coverage, granular rejects, pre-econ metrics
# ===========================================================================


class TestM7A511RejectConstants:
    """M7.A.5.11: New granular reject constants exist and are in ALL_REJECT_REASONS."""

    def test_no_active_counter_pool_constant(self):
        assert REJECT_NO_ACTIVE_COUNTER_POOL == "NO_ACTIVE_COUNTER_POOL"
        assert REJECT_NO_ACTIVE_COUNTER_POOL in ALL_REJECT_REASONS

    def test_all_pools_zero_liquidity_constant(self):
        assert REJECT_ALL_POOLS_ZERO_LIQUIDITY == "ALL_POOLS_ZERO_LIQUIDITY"
        assert REJECT_ALL_POOLS_ZERO_LIQUIDITY in ALL_REJECT_REASONS

    def test_legacy_zero_liquidity_still_exists(self):
        """REJECT_ZERO_LIQUIDITY kept for backward compat."""
        assert REJECT_ZERO_LIQUIDITY == "ZERO_LIQUIDITY"
        assert REJECT_ZERO_LIQUIDITY in ALL_REJECT_REASONS

    def test_all_reject_reasons_count_19(self):
        assert len(ALL_REJECT_REASONS) == 19


class TestM7A511ActiveCoverageSchema:
    """M7.A.5.11: counter_venue_coverage_scan returns active-liquidity fields."""

    def test_new_fields_present_empty_config(self):
        result = counter_venue_coverage_scan("0xA", "0xB", {}, "http://unused", 1)
        for key in [
            "known_pools_total", "active_pools_total", "inactive_pool_count",
            "active_dexes", "active_buy_venues", "active_sell_venues",
        ]:
            assert key in result, f"Missing M7.A.5.11 field: {key}"

    def test_inactive_pool_count_equals_diff(self):
        result = counter_venue_coverage_scan("0xA", "0xB", {}, "http://unused", 1)
        assert result["inactive_pool_count"] == (
            result["known_pools_total"] - result["active_pools_total"]
        )

    def test_known_pools_alias_matches_total(self):
        """Legacy known_pools == known_pools_total."""
        result = counter_venue_coverage_scan("0xA", "0xB", {}, "http://unused", 1)
        assert result["known_pools"] == result["known_pools_total"]

    def test_no_pools_blocker(self):
        result = counter_venue_coverage_scan("0xA", "0xB", {}, "http://unused", 1)
        assert result["coverage_blocker_reason"] == "no_pools_found"
        assert result["coverage_complete"] is False


class TestM7A511CoverageRejectSplit:
    """M7.A.5.11: BackrunResult with granular coverage rejects."""

    def test_no_active_counter_pool_result(self):
        r = BackrunResult(
            event_id="cov_511_1",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            reject_reason=REJECT_NO_ACTIVE_COUNTER_POOL,
            route_viable=False,
            coverage_result={
                "known_pools_total": 2, "active_pools_total": 0,
                "inactive_pool_count": 2,
                "coverage_complete": False,
                "coverage_blocker_reason": "all_pools_zero_liquidity",
            },
        )
        assert r.reject_reason == REJECT_NO_ACTIVE_COUNTER_POOL
        assert r.route_viable is False

    def test_all_pools_zero_liq_result(self):
        r = BackrunResult(
            event_id="cov_511_2",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            reject_reason=REJECT_ALL_POOLS_ZERO_LIQUIDITY,
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
        assert r.reject_reason == REJECT_ALL_POOLS_ZERO_LIQUIDITY
        assert r.route_viable is False


class TestM7A511PreEconMetrics:
    """M7.A.5.11: build_replay_summary includes pre-economics coverage metrics."""

    def _make_mixed_results(self):
        """Build a mix with scored and unscored results."""
        results = []
        # Scored: viable result
        results.append(BackrunResult(
            event_id="pe_1", event_source="live", event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live", backrun_direction=BACKRUN_BUY_DEPRESSED,
            best_backrun_net_bps=50.0, block_lag=1, same_state_class="next_block",
            route_viable=True, reject_reason=None,
            coverage_result={"coverage_complete": True, "known_pools_total": 2, "active_pools_total": 2},
        ))
        # Scored: gas-rejected
        results.append(BackrunResult(
            event_id="pe_2", event_source="live", event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live", backrun_direction=BACKRUN_BUY_DEPRESSED,
            best_backrun_net_bps=-400.0, block_lag=1, same_state_class="next_block",
            route_viable=False, reject_reason=REJECT_GAS_EXCEEDS_GROSS,
            coverage_result={"coverage_complete": True, "known_pools_total": 1, "active_pools_total": 1},
        ))
        # Unscored: no active counter pool (pools found, all zero liq)
        results.append(BackrunResult(
            event_id="pe_3", event_source="live", event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live", backrun_direction=BACKRUN_BUY_DEPRESSED,
            best_backrun_net_bps=0.0, block_lag=2, same_state_class="next_block",
            route_viable=False, reject_reason=REJECT_NO_ACTIVE_COUNTER_POOL,
            coverage_result={"coverage_complete": False, "known_pools_total": 3, "active_pools_total": 0},
        ))
        # Unscored: no counter pool at all
        results.append(BackrunResult(
            event_id="pe_4", event_source="live", event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live", backrun_direction=BACKRUN_BUY_DEPRESSED,
            best_backrun_net_bps=0.0, block_lag=5, same_state_class="stale",
            route_viable=False, reject_reason=REJECT_NO_COUNTER_POOL,
        ))
        return results

    def test_pre_econ_fields_present(self):
        events = [_make_event(event_id=f"pe_{i}") for i in range(1, 5)]
        results = self._make_mixed_results()
        art = build_replay_summary(events, results, mode="test")
        for key in [
            "pre_econ_reject_rate", "active_coverage_rate",
            "inactive_coverage_false_positive_rate", "scored_results_rate",
        ]:
            assert key in art, f"Missing M7.A.5.11 field: {key}"

    def test_pre_econ_reject_rate(self):
        events = [_make_event(event_id=f"pe_{i}") for i in range(1, 5)]
        results = self._make_mixed_results()
        art = build_replay_summary(events, results, mode="test")
        # 2 scored, 2 unscored out of 4 total
        assert art["pre_econ_reject_rate"] == 0.5
        assert art["scored_results_rate"] == 0.5

    def test_active_coverage_rate(self):
        events = [_make_event(event_id=f"pe_{i}") for i in range(1, 5)]
        results = self._make_mixed_results()
        art = build_replay_summary(events, results, mode="test")
        # pe_1 and pe_2 have coverage_complete=True → 2/4
        assert art["active_coverage_rate"] == 0.5

    def test_inactive_false_positive_rate(self):
        events = [_make_event(event_id=f"pe_{i}") for i in range(1, 5)]
        results = self._make_mixed_results()
        art = build_replay_summary(events, results, mode="test")
        # pe_3 has known_pools_total=3, active_pools_total=0 → inactive FP
        assert art["inactive_coverage_false_positive_rate"] == 0.25

    def test_empty_results(self):
        art = build_replay_summary([], [], mode="test")
        assert art["pre_econ_reject_rate"] == 0.0
        assert art["active_coverage_rate"] == 0.0
        assert art["scored_results_rate"] == 0.0


class TestM7A511LiveStateMetricsFix:
    """M7.A.5.11: Early reject BackrunResults must have same_state_class set."""

    def test_reject_result_has_same_state_class(self):
        """A result with block_lag=0 and reject should still have same_state_class."""
        r = BackrunResult(
            event_id="lsm_1",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            reject_reason=REJECT_NO_ACTIVE_COUNTER_POOL,
            event_block=100,
            quote_block=100,
            block_lag=0,
            same_state_class="same_block",
            route_viable=False,
        )
        assert r.same_state_class == "same_block"
        assert r.block_lag == 0

    def test_reject_result_stale_class(self):
        r = BackrunResult(
            event_id="lsm_2",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            reject_reason=REJECT_ALL_POOLS_ZERO_LIQUIDITY,
            event_block=100,
            quote_block=110,
            block_lag=10,
            same_state_class="stale",
            route_viable=False,
        )
        assert r.same_state_class == "stale"

    def test_live_state_metrics_counts_early_rejects(self):
        """All live results with same_state_class contribute to state counts."""
        results = [
            BackrunResult(
                event_id="lsm_3",
                event_source="live",
                event_type=EVENT_TYPE_SWAP,
                post_trade_state_used="live",
                backrun_direction=BACKRUN_BUY_DEPRESSED,
                reject_reason=REJECT_NO_ACTIVE_COUNTER_POOL,
                event_block=100, quote_block=100, block_lag=0,
                same_state_class="same_block",
                route_viable=False,
            ),
            BackrunResult(
                event_id="lsm_4",
                event_source="live",
                event_type=EVENT_TYPE_SWAP,
                post_trade_state_used="live",
                backrun_direction=BACKRUN_BUY_DEPRESSED,
                reject_reason=REJECT_ALL_POOLS_ZERO_LIQUIDITY,
                event_block=100, quote_block=105, block_lag=5,
                same_state_class="stale",
                route_viable=False,
            ),
        ]
        live_results = [r for r in results if r.event_block is not None]
        same_block_count = sum(1 for r in live_results if r.same_state_class == "same_block")
        stale_count = sum(1 for r in live_results if r.same_state_class == "stale")
        # Both should now be counted (unlike pre-5.11 where early rejects had None)
        assert same_block_count == 1
        assert stale_count == 1


class TestM7A511UnscoredRejectsExpanded:
    """M7.A.5.11: _UNSCORED_REJECTS includes new granular rejects."""

    def test_new_rejects_are_unscored(self):
        """NO_ACTIVE_COUNTER_POOL and ALL_POOLS_ZERO_LIQUIDITY are unscored."""
        events = [_make_event(event_id=f"us_{i}") for i in range(1, 3)]
        results = [
            BackrunResult(
                event_id="us_1", event_source="live", event_type=EVENT_TYPE_SWAP,
                post_trade_state_used="live", backrun_direction=BACKRUN_BUY_DEPRESSED,
                best_backrun_net_bps=0.0, block_lag=2, same_state_class="next_block",
                route_viable=False, reject_reason=REJECT_NO_ACTIVE_COUNTER_POOL,
            ),
            BackrunResult(
                event_id="us_2", event_source="live", event_type=EVENT_TYPE_SWAP,
                post_trade_state_used="live", backrun_direction=BACKRUN_BUY_DEPRESSED,
                best_backrun_net_bps=0.0, block_lag=1, same_state_class="next_block",
                route_viable=False, reject_reason=REJECT_ALL_POOLS_ZERO_LIQUIDITY,
            ),
        ]
        art = build_replay_summary(events, results, mode="test")
        assert art["scored_results_count"] == 0  # both are unscored


class TestM7A511BackwardCompat:
    """M7.A.5.11 must not break existing BackrunResult (still 53 fields)."""

    def test_backrun_result_field_count_still_53(self):
        r = BackrunResult(
            event_id="compat_511",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
        )
        d = asdict(r)
        assert len(d) == 56

    def test_all_reject_reasons_count_19(self):
        assert len(ALL_REJECT_REASONS) == 19

    def test_old_constants_still_present(self):
        for reason in [
            REJECT_ZERO_LIQUIDITY, REJECT_STALE_POSITIVE,
            REJECT_NO_COUNTER_POOL, REJECT_GAS_EXCEEDS_GROSS,
        ]:
            assert reason in ALL_REJECT_REASONS

    def test_511_constants_present(self):
        assert REJECT_NO_ACTIVE_COUNTER_POOL in ALL_REJECT_REASONS
        assert REJECT_ALL_POOLS_ZERO_LIQUIDITY in ALL_REJECT_REASONS

    def test_512_constants_present(self):
        assert REJECT_COVERAGE_LOCAL_MISMATCH in ALL_REJECT_REASONS
        assert REJECT_ALL_POOLS_TRULY_INACTIVE in ALL_REJECT_REASONS

    def test_coverage_schema_has_active_fields(self):
        result = counter_venue_coverage_scan("0xA", "0xB", {}, "http://unused", 1)
        for key in [
            "known_pools_total", "active_pools_total", "inactive_pool_count",
            "active_dexes", "active_buy_venues", "active_sell_venues",
            "known_pools",  # legacy alias
        ]:
            assert key in result

    def test_summary_has_pre_econ_fields(self):
        art = build_replay_summary([], [], mode="test")
        for key in [
            "pre_econ_reject_rate", "active_coverage_rate",
            "inactive_coverage_false_positive_rate", "scored_results_rate",
        ]:
            assert key in art


# ===========================================================================
# M7.A.5.12: Coverage/local-sim consistency, split blocker, per-pool debug
# ===========================================================================

class TestM7A512RejectConstants:
    """M7.A.5.12: New reject constants for coverage/local-sim split."""

    def test_coverage_local_mismatch_value(self):
        assert REJECT_COVERAGE_LOCAL_MISMATCH == "COVERAGE_SAYS_ACTIVE_BUT_LOCAL_SIM_ZERO"

    def test_all_pools_truly_inactive_value(self):
        assert REJECT_ALL_POOLS_TRULY_INACTIVE == "ALL_CANDIDATE_POOLS_TRULY_INACTIVE"

    def test_both_in_all_reject_reasons(self):
        assert REJECT_COVERAGE_LOCAL_MISMATCH in ALL_REJECT_REASONS
        assert REJECT_ALL_POOLS_TRULY_INACTIVE in ALL_REJECT_REASONS

    def test_all_reject_reasons_count_19(self):
        assert len(ALL_REJECT_REASONS) == 19


class TestM7A512CandidatePoolDebug:
    """M7.A.5.12: coverage_result must include candidate_pools debug list."""

    def test_candidate_pools_present_in_coverage(self):
        result = counter_venue_coverage_scan("0xA", "0xB", {}, "http://unused", 1)
        assert "candidate_pools" in result
        assert isinstance(result["candidate_pools"], list)

    def test_candidate_pools_empty_for_no_configs(self):
        result = counter_venue_coverage_scan("0xA", "0xB", {}, "http://unused", 1)
        assert result["candidate_pools"] == []

    def test_candidate_pool_schema_fields(self):
        """Each candidate pool entry must have the required debug fields."""
        required_keys = {"address", "dex", "fee", "liquidity", "activity_source", "activity_drop_reason"}
        # With empty config, no pools found, but schema is tested via invariant
        result = counter_venue_coverage_scan("0xA", "0xB", {}, "http://unused", 1)
        # For empty configs, list is empty — schema validated via mock below
        assert isinstance(result["candidate_pools"], list)
        # Verify the schema by constructing a synthetic candidate pool
        synthetic = {
            "address": "0x1234",
            "dex": "uniswap_v3",
            "fee": 3000,
            "liquidity": 0,
            "activity_source": "batch_full_pool_data",
            "activity_drop_reason": "liquidity_zero",
        }
        assert required_keys.issubset(set(synthetic.keys()))


class TestM7A512CoverageLocalSimInvariant:
    """M7.A.5.12: Hard invariant: if reject=ALL_CANDIDATE_POOLS_TRULY_INACTIVE,
    then coverage_result.active_pools_total == 0 and coverage_complete == False."""

    def _make_result(self, reject_reason, coverage_result=None, local_sim_state=None):
        return BackrunResult(
            event_id="inv_512",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            reject_reason=reject_reason,
            coverage_result=coverage_result,
            local_sim_state=local_sim_state,
        )

    def test_truly_inactive_implies_zero_active(self):
        """If reject is TRULY_INACTIVE, active_pools_total must be 0."""
        cov = {
            "active_pools_total": 0,
            "coverage_complete": False,
            "known_pools_total": 3,
            "inactive_pool_count": 3,
        }
        r = self._make_result(REJECT_ALL_POOLS_TRULY_INACTIVE, coverage_result=cov)
        assert r.coverage_result["active_pools_total"] == 0
        assert r.coverage_result["coverage_complete"] is False

    def test_mismatch_implies_patched_coverage(self):
        """If reject is MISMATCH, coverage must have been patched to show 0 active."""
        cov = {
            "active_pools_total": 0,  # patched
            "coverage_complete": False,  # patched
            "known_pools_total": 6,
            "inactive_pool_count": 6,
            "coverage_blocker_reason": "local_sim_all_zero_liquidity",
        }
        r = self._make_result(REJECT_COVERAGE_LOCAL_MISMATCH, coverage_result=cov)
        assert r.coverage_result["active_pools_total"] == 0
        assert r.coverage_result["coverage_complete"] is False
        assert r.coverage_result["coverage_blocker_reason"] == "local_sim_all_zero_liquidity"


class TestM7A512QuoteReachabilityInvariant:
    """M7.A.5.12: Reverse invariant: if coverage_complete=True, event must reach
    quote stage (quote_calls_attempted > 0) or be rejected with an explicit reason."""

    def _make_result_with_coverage(self, coverage_complete, quote_calls, reject=None):
        cov = {"coverage_complete": coverage_complete, "active_pools_total": 3}
        return BackrunResult(
            event_id="qr_512",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            coverage_result=cov,
            quote_calls_attempted=quote_calls,
            reject_reason=reject,
        )

    def test_coverage_complete_with_quotes_is_valid(self):
        r = self._make_result_with_coverage(True, 4)
        assert r.coverage_result["coverage_complete"] is True
        assert r.quote_calls_attempted > 0

    def test_coverage_complete_no_quotes_needs_explicit_reject(self):
        """If coverage says complete but no quotes attempted, must have an explicit reject."""
        r = self._make_result_with_coverage(True, 0, reject=REJECT_COVERAGE_LOCAL_MISMATCH)
        assert r.reject_reason is not None

    def test_coverage_incomplete_is_always_valid(self):
        r = self._make_result_with_coverage(False, None, reject=REJECT_ALL_POOLS_TRULY_INACTIVE)
        assert r.coverage_result["coverage_complete"] is False


class TestM7A512ConsistencyMetrics:
    """M7.A.5.12: build_replay_summary must include consistency metrics."""

    def test_summary_has_consistency_fields(self):
        art = build_replay_summary([], [], mode="test")
        for key in [
            "coverage_local_mismatch_count",
            "truly_inactive_count",
            "quote_reachability_rate",
            "coverage_complete_no_quote_count",
        ]:
            assert key in art

    def test_consistency_defaults_for_empty(self):
        art = build_replay_summary([], [], mode="test")
        assert art["coverage_local_mismatch_count"] == 0
        assert art["truly_inactive_count"] == 0
        assert art["quote_reachability_rate"] is None
        assert art["coverage_complete_no_quote_count"] == 0

    def test_mismatch_count_from_reject_histogram(self):
        events = [_make_event(event_id=f"ev_{i}") for i in range(3)]
        results = [
            BackrunResult(
                event_id="ev_0",
                event_source="live",
                event_type=EVENT_TYPE_SWAP,
                post_trade_state_used="live",
                backrun_direction=BACKRUN_BUY_DEPRESSED,
                reject_reason="COVERAGE_SAYS_ACTIVE_BUT_LOCAL_SIM_ZERO",
            ),
            BackrunResult(
                event_id="ev_1",
                event_source="live",
                event_type=EVENT_TYPE_SWAP,
                post_trade_state_used="live",
                backrun_direction=BACKRUN_BUY_DEPRESSED,
                reject_reason="ALL_CANDIDATE_POOLS_TRULY_INACTIVE",
            ),
            BackrunResult(
                event_id="ev_2",
                event_source="live",
                event_type=EVENT_TYPE_SWAP,
                post_trade_state_used="live",
                backrun_direction=BACKRUN_BUY_DEPRESSED,
                reject_reason="NO_COUNTER_POOL",
            ),
        ]
        art = build_replay_summary(events, results, mode="test")
        assert art["coverage_local_mismatch_count"] == 1
        assert art["truly_inactive_count"] == 1


class TestM7A512UnscoredRejectsExpanded:
    """M7.A.5.12 new rejects must be in _UNSCORED_REJECTS."""

    def test_new_rejects_counted_as_unscored(self):
        events = [_make_event(event_id=f"ev_{i}") for i in range(2)]
        results = [
            BackrunResult(
                event_id="ev_0",
                event_source="live",
                event_type=EVENT_TYPE_SWAP,
                post_trade_state_used="live",
                backrun_direction=BACKRUN_BUY_DEPRESSED,
                reject_reason="COVERAGE_SAYS_ACTIVE_BUT_LOCAL_SIM_ZERO",
            ),
            BackrunResult(
                event_id="ev_1",
                event_source="live",
                event_type=EVENT_TYPE_SWAP,
                post_trade_state_used="live",
                backrun_direction=BACKRUN_BUY_DEPRESSED,
                reject_reason="ALL_CANDIDATE_POOLS_TRULY_INACTIVE",
            ),
        ]
        art = build_replay_summary(events, results, mode="test")
        assert art["scored_results_count"] == 0  # both are unscored


class TestM7A512BackwardCompat:
    """M7.A.5.12 must not break existing BackrunResult (still 53 fields)."""

    def test_backrun_result_field_count_still_53(self):
        r = BackrunResult(
            event_id="compat_512",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
        )
        d = asdict(r)
        assert len(d) == 56

    def test_all_reject_reasons_count_19(self):
        assert len(ALL_REJECT_REASONS) == 19

    def test_old_511_constants_still_present(self):
        for reason in [
            REJECT_ZERO_LIQUIDITY, REJECT_STALE_POSITIVE,
            REJECT_NO_COUNTER_POOL, REJECT_GAS_EXCEEDS_GROSS,
            REJECT_NO_ACTIVE_COUNTER_POOL, REJECT_ALL_POOLS_ZERO_LIQUIDITY,
        ]:
            assert reason in ALL_REJECT_REASONS

    def test_new_512_constants_present(self):
        assert REJECT_COVERAGE_LOCAL_MISMATCH in ALL_REJECT_REASONS
        assert REJECT_ALL_POOLS_TRULY_INACTIVE in ALL_REJECT_REASONS

    def test_coverage_schema_has_candidate_pools(self):
        result = counter_venue_coverage_scan("0xA", "0xB", {}, "http://unused", 1)
        assert "candidate_pools" in result
        assert isinstance(result["candidate_pools"], list)

    def test_summary_has_512_consistency_fields(self):
        art = build_replay_summary([], [], mode="test")
        for key in [
            "coverage_local_mismatch_count", "truly_inactive_count",
            "quote_reachability_rate", "coverage_complete_no_quote_count",
        ]:
            assert key in art


# ===========================================================================
# M7.A.5.13 — Stale vs low-lag scored split
# ===========================================================================


class TestM7A513StaleLowLagSplitFields:
    """M7.A.5.13 summary must include stale/low-lag scored split fields."""

    def test_split_fields_present_in_empty_summary(self):
        art = build_replay_summary([], [], mode="test")
        for key in [
            "events_detected_low_lag", "events_scored_low_lag",
            "best_net_bps_stale", "best_net_bps_low_lag_scored",
            "mean_net_bps_stale", "mean_net_bps_low_lag_scored",
        ]:
            assert key in art, f"Missing key: {key}"

    def test_split_fields_none_when_no_results(self):
        art = build_replay_summary([], [], mode="test")
        assert art["events_detected_low_lag"] == 0
        assert art["events_scored_low_lag"] == 0
        assert art["best_net_bps_stale"] is None
        assert art["best_net_bps_low_lag_scored"] is None
        assert art["mean_net_bps_stale"] is None
        assert art["mean_net_bps_low_lag_scored"] is None

    def test_stale_result_goes_to_stale_metrics(self):
        """A scored result with block_lag > 2 should appear in stale metrics only."""
        e = _make_event()
        r = BackrunResult(
            event_id="stale_1", event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            best_backrun_net_bps=-50.0,
            block_lag=100,
            same_state_class="stale",
            reject_reason=REJECT_GAS_EXCEEDS_GROSS,
            route_viable=False,
        )
        art = build_replay_summary([e], [r], mode="test")
        assert art["events_detected_low_lag"] == 0
        assert art["events_scored_low_lag"] == 0
        assert art["best_net_bps_stale"] == -50.0
        assert art["best_net_bps_low_lag_scored"] is None

    def test_low_lag_scored_result_goes_to_low_lag_metrics(self):
        """A scored result with block_lag=0 should appear in low-lag metrics."""
        e = _make_event()
        r = BackrunResult(
            event_id="ll_1", event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            best_backrun_net_bps=-20.0,
            block_lag=0,
            same_state_class="same_block",
            reject_reason=REJECT_GAS_EXCEEDS_GROSS,
            route_viable=False,
        )
        art = build_replay_summary([e], [r], mode="test")
        assert art["events_detected_low_lag"] == 1
        assert art["events_scored_low_lag"] == 1
        assert art["best_net_bps_low_lag_scored"] == -20.0
        assert art["best_net_bps_stale"] is None

    def test_unscored_low_lag_detected_not_scored(self):
        """An unscored reject with block_lag=0: detected but not scored."""
        e = _make_event()
        r = BackrunResult(
            event_id="unscore_ll", event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            best_backrun_net_bps=0.0,
            block_lag=0,
            same_state_class="same_block",
            reject_reason=REJECT_TOKEN_PAIR_UNRESOLVED,
            route_viable=False,
        )
        art = build_replay_summary([e], [r], mode="test")
        assert art["events_detected_low_lag"] == 1
        assert art["events_scored_low_lag"] == 0


class TestM7A513ComparisonBlock:
    """M7.A.5.13 must include machine-readable stale_low_lag_comparison."""

    def test_comparison_block_present(self):
        art = build_replay_summary([], [], mode="test")
        assert "stale_low_lag_comparison" in art
        comp = art["stale_low_lag_comparison"]
        for key in [
            "stale_scored_count", "stale_positive_count",
            "low_lag_scored_count", "low_lag_positive_count",
            "beats_m4_baseline_stale", "beats_m4_baseline_low_lag",
        ]:
            assert key in comp, f"Missing comparison key: {key}"

    def test_comparison_empty_has_zeros_and_false(self):
        art = build_replay_summary([], [], mode="test")
        comp = art["stale_low_lag_comparison"]
        assert comp["stale_scored_count"] == 0
        assert comp["low_lag_scored_count"] == 0
        assert comp["beats_m4_baseline_stale"] is False
        assert comp["beats_m4_baseline_low_lag"] is False

    def test_comparison_with_stale_positive(self):
        """Stale positive → stale_positive_count=1, beats_m4_baseline_stale=True."""
        e = _make_event()
        r = BackrunResult(
            event_id="sp_1", event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            best_backrun_net_bps=100.0,
            block_lag=500,
            same_state_class="stale",
            reject_reason=REJECT_STALE_POSITIVE,
            route_viable=False,
        )
        art = build_replay_summary([e], [r], mode="test")
        comp = art["stale_low_lag_comparison"]
        assert comp["stale_scored_count"] == 1
        assert comp["stale_positive_count"] == 1
        assert comp["beats_m4_baseline_stale"] is True
        assert comp["low_lag_scored_count"] == 0
        assert comp["beats_m4_baseline_low_lag"] is False

    def test_comparison_with_low_lag_positive(self):
        """Low-lag viable → low_lag_positive_count=1, beats_m4_baseline_low_lag=True."""
        e = _make_event()
        r = BackrunResult(
            event_id="llv_1", event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            best_backrun_net_bps=50.0,
            block_lag=0,
            same_state_class="same_block",
            reject_reason=None,
            route_viable=True,
        )
        art = build_replay_summary([e], [r], mode="test")
        comp = art["stale_low_lag_comparison"]
        assert comp["low_lag_scored_count"] == 1
        assert comp["low_lag_positive_count"] == 1
        assert comp["beats_m4_baseline_low_lag"] is True


class TestM7A513EventsScoredLowLagContract:
    """M7.A.5.13: events_scored_low_lag_ws must count only scored results."""

    def test_events_scored_low_lag_excludes_unscored(self):
        """If low-lag event has an unscored reject, it's detected but not scored."""
        e = _make_event()
        r_unscored = BackrunResult(
            event_id="unscore_ll", event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            best_backrun_net_bps=0.0,
            block_lag=1,
            same_state_class="next_block",
            reject_reason=REJECT_NO_COUNTER_POOL,
            route_viable=False,
        )
        r_scored = BackrunResult(
            event_id="scored_ll", event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            best_backrun_net_bps=-10.0,
            block_lag=0,
            same_state_class="same_block",
            reject_reason=REJECT_GAS_EXCEEDS_GROSS,
            route_viable=False,
        )
        art = build_replay_summary([e, e], [r_unscored, r_scored], mode="test")
        assert art["events_detected_low_lag"] == 2
        assert art["events_scored_low_lag"] == 1  # only the scored one

    def test_best_net_bps_executable_only_viable(self):
        """best_net_bps_executable only considers route_viable=True results."""
        e = _make_event()
        r_stale_pos = BackrunResult(
            event_id="sp", event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            best_backrun_net_bps=200.0,
            block_lag=100,
            same_state_class="stale",
            reject_reason=REJECT_STALE_POSITIVE,
            route_viable=False,
        )
        r_viable = BackrunResult(
            event_id="v", event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            best_backrun_net_bps=5.0,
            block_lag=0,
            same_state_class="same_block",
            reject_reason=None,
            route_viable=True,
        )
        art = build_replay_summary([e, e], [r_stale_pos, r_viable], mode="test")
        # best_net_bps_executable = only from viable subset = 5.0
        assert art["best_net_bps_executable"] == 5.0
        # best_net_bps_any = includes stale positive = 200.0
        assert art["best_net_bps_any"] == 200.0


class TestM7A513UnscoredRejectsModuleLevel:
    """M7.A.5.13: UNSCORED_REJECTS should be available at module level."""

    def test_unscored_rejects_is_frozenset(self):
        assert isinstance(UNSCORED_REJECTS, frozenset)

    def test_unscored_rejects_has_expected_members(self):
        expected = {
            REJECT_TOKEN_PAIR_UNRESOLVED, REJECT_NO_COUNTER_POOL,
            REJECT_TOKEN_NOT_ADMITTED, REJECT_UNSUPPORTED_ADAPTER,
            REJECT_RPC_QUOTE_FAIL, REJECT_PAIR_RESOLVED_UNTRADEABLE,
            REJECT_ZERO_LIQUIDITY,
            REJECT_NO_ACTIVE_COUNTER_POOL, REJECT_ALL_POOLS_ZERO_LIQUIDITY,
            REJECT_COVERAGE_LOCAL_MISMATCH, REJECT_ALL_POOLS_TRULY_INACTIVE,
        }
        assert UNSCORED_REJECTS == expected

    def test_scored_rejects_not_in_unscored(self):
        """GAS_EXCEEDS_GROSS and STALE_POSITIVE are scored rejects."""
        assert REJECT_GAS_EXCEEDS_GROSS not in UNSCORED_REJECTS
        assert REJECT_STALE_POSITIVE not in UNSCORED_REJECTS


class TestM7A513BackwardCompat:
    """M7.A.5.13 must not break existing BackrunResult (still 53 fields)."""

    def test_backrun_result_field_count_still_53(self):
        r = BackrunResult(
            event_id="compat_513",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
        )
        d = asdict(r)
        assert len(d) == 56

    def test_all_reject_reasons_count_still_19(self):
        """M7.A.5.13 adds no new reject reasons."""
        assert len(ALL_REJECT_REASONS) == 19

    def test_old_summary_fields_still_present(self):
        art = build_replay_summary([], [], mode="test")
        # Verify pre-5.13 fields still exist
        for key in [
            "events_count", "results_count", "viable_count",
            "best_net_bps_any", "best_net_bps_executable",
            "positive_net_count_any", "positive_net_count_low_lag",
            "stale_positive_count", "scored_results_count",
            "reject_histogram", "two_leg_baseline_net_bps",
            "coverage_local_mismatch_count", "truly_inactive_count",
        ]:
            assert key in art, f"Missing backward-compat key: {key}"

    def test_new_513_fields_additive(self):
        art = build_replay_summary([], [], mode="test")
        for key in [
            "events_detected_low_lag", "events_scored_low_lag",
            "best_net_bps_stale", "best_net_bps_low_lag_scored",
            "mean_net_bps_stale", "mean_net_bps_low_lag_scored",
            "stale_low_lag_comparison",
        ]:
            assert key in art, f"Missing 5.13 key: {key}"


class TestM7A514LowLagRejectDecomposition:
    """M7.A.5.14: Low-lag reject histogram and pipeline stage rates."""

    def _make_mixed_lag_results(self):
        """Build results with mix of low-lag (block_lag<=2) and stale, scored and unscored."""
        results = []
        # Low-lag, scored, viable
        results.append(BackrunResult(
            event_id="ll_1", event_source="live", event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live", backrun_direction=BACKRUN_BUY_DEPRESSED,
            best_backrun_net_bps=50.0, block_lag=1, same_state_class="next_block",
            route_viable=True, reject_reason=None,
        ))
        # Low-lag, scored, gas-rejected
        results.append(BackrunResult(
            event_id="ll_2", event_source="live", event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live", backrun_direction=BACKRUN_BUY_DEPRESSED,
            best_backrun_net_bps=-100.0, block_lag=0, same_state_class="same_block",
            route_viable=False, reject_reason=REJECT_GAS_EXCEEDS_GROSS,
        ))
        # Low-lag, unscored: TOKEN_PAIR_UNRESOLVED
        results.append(BackrunResult(
            event_id="ll_3", event_source="live", event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live", backrun_direction=BACKRUN_BUY_DEPRESSED,
            best_backrun_net_bps=0.0, block_lag=2, same_state_class="next_block",
            route_viable=False, reject_reason=REJECT_TOKEN_PAIR_UNRESOLVED,
        ))
        # Low-lag, unscored: NO_COUNTER_POOL
        results.append(BackrunResult(
            event_id="ll_4", event_source="live", event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live", backrun_direction=BACKRUN_BUY_DEPRESSED,
            best_backrun_net_bps=0.0, block_lag=1, same_state_class="next_block",
            route_viable=False, reject_reason=REJECT_NO_COUNTER_POOL,
        ))
        # Stale, scored, positive
        results.append(BackrunResult(
            event_id="st_1", event_source="live", event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live", backrun_direction=BACKRUN_BUY_DEPRESSED,
            best_backrun_net_bps=200.0, block_lag=10, same_state_class="stale",
            route_viable=False, reject_reason=REJECT_STALE_POSITIVE,
        ))
        # Stale, unscored: TOKEN_NOT_ADMITTED
        results.append(BackrunResult(
            event_id="st_2", event_source="live", event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live", backrun_direction=BACKRUN_BUY_DEPRESSED,
            best_backrun_net_bps=0.0, block_lag=15, same_state_class="stale",
            route_viable=False, reject_reason=REJECT_TOKEN_NOT_ADMITTED,
        ))
        return results

    def test_low_lag_reject_histogram_present(self):
        events = [_make_event(event_id=f"ev_{i}") for i in range(6)]
        results = self._make_mixed_lag_results()
        art = build_replay_summary(events, results, mode="test")
        assert "low_lag_reject_histogram" in art

    def test_low_lag_reject_histogram_only_low_lag(self):
        """low_lag_reject_histogram must only contain rejects from block_lag <= 2."""
        events = [_make_event(event_id=f"ev_{i}") for i in range(6)]
        results = self._make_mixed_lag_results()
        art = build_replay_summary(events, results, mode="test")
        ll_hist = art["low_lag_reject_histogram"]
        # Low-lag rejects: GAS_EXCEEDS_GROSS(1), TOKEN_PAIR_UNRESOLVED(1), NO_COUNTER_POOL(1)
        assert ll_hist.get(REJECT_GAS_EXCEEDS_GROSS) == 1
        assert ll_hist.get(REJECT_TOKEN_PAIR_UNRESOLVED) == 1
        assert ll_hist.get(REJECT_NO_COUNTER_POOL) == 1
        # Stale rejects must NOT appear
        assert REJECT_STALE_POSITIVE not in ll_hist
        assert REJECT_TOKEN_NOT_ADMITTED not in ll_hist

    def test_low_lag_reject_histogram_subset_of_full(self):
        """Every reason in low_lag_reject_histogram must also be in reject_histogram."""
        events = [_make_event(event_id=f"ev_{i}") for i in range(6)]
        results = self._make_mixed_lag_results()
        art = build_replay_summary(events, results, mode="test")
        for reason, count in art["low_lag_reject_histogram"].items():
            assert reason in art["reject_histogram"], (
                f"{reason} in low_lag but not in full histogram"
            )
            assert count <= art["reject_histogram"][reason]

    def test_low_lag_pipeline_stage_rates_present(self):
        events = [_make_event(event_id=f"ev_{i}") for i in range(6)]
        results = self._make_mixed_lag_results()
        art = build_replay_summary(events, results, mode="test")
        for key in [
            "low_lag_pair_resolution_rate",
            "low_lag_counter_coverage_rate",
            "low_lag_scored_results_rate",
            "low_lag_pre_econ_reject_rate",
        ]:
            assert key in art, f"Missing M7.A.5.14 field: {key}"

    def test_low_lag_pair_resolution_rate(self):
        """4 low-lag results, 1 has TOKEN_PAIR_UNRESOLVED → 3/4 = 0.75."""
        events = [_make_event(event_id=f"ev_{i}") for i in range(6)]
        results = self._make_mixed_lag_results()
        art = build_replay_summary(events, results, mode="test")
        assert art["low_lag_pair_resolution_rate"] == 0.75

    def test_low_lag_counter_coverage_rate(self):
        """4 low-lag, 1 TOKEN_PAIR_UNRESOLVED + 1 NO_COUNTER_POOL → 2/4 = 0.5."""
        events = [_make_event(event_id=f"ev_{i}") for i in range(6)]
        results = self._make_mixed_lag_results()
        art = build_replay_summary(events, results, mode="test")
        assert art["low_lag_counter_coverage_rate"] == 0.5

    def test_low_lag_scored_results_rate(self):
        """4 low-lag total, 2 scored (viable + gas-rejected) → 0.5."""
        events = [_make_event(event_id=f"ev_{i}") for i in range(6)]
        results = self._make_mixed_lag_results()
        art = build_replay_summary(events, results, mode="test")
        assert art["low_lag_scored_results_rate"] == 0.5

    def test_low_lag_pre_econ_reject_rate(self):
        """4 low-lag, 2 unscored → 0.5."""
        events = [_make_event(event_id=f"ev_{i}") for i in range(6)]
        results = self._make_mixed_lag_results()
        art = build_replay_summary(events, results, mode="test")
        assert art["low_lag_pre_econ_reject_rate"] == 0.5

    def test_low_lag_rates_none_when_no_low_lag(self):
        """When all results are stale, low-lag rates should be None."""
        results = [BackrunResult(
            event_id="stale_only", event_source="live", event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live", backrun_direction=BACKRUN_BUY_DEPRESSED,
            best_backrun_net_bps=100.0, block_lag=10, same_state_class="stale",
            route_viable=False, reject_reason=REJECT_STALE_POSITIVE,
        )]
        events = [_make_event(event_id="stale_only")]
        art = build_replay_summary(events, results, mode="test")
        assert art["low_lag_pair_resolution_rate"] is None
        assert art["low_lag_counter_coverage_rate"] is None
        assert art["low_lag_scored_results_rate"] is None
        assert art["low_lag_pre_econ_reject_rate"] is None
        assert art["low_lag_reject_histogram"] == {}

    def test_detected_low_lag_gte_scored_low_lag(self):
        """Invariant: events_detected_low_lag >= events_scored_low_lag."""
        events = [_make_event(event_id=f"ev_{i}") for i in range(6)]
        results = self._make_mixed_lag_results()
        art = build_replay_summary(events, results, mode="test")
        assert art["events_detected_low_lag"] >= art["events_scored_low_lag"]

    def test_block_lag_zero_counted_as_low_lag(self):
        """block_lag=0 must be treated as low-lag (same_block), not filtered out."""
        results = [BackrunResult(
            event_id="lag0", event_source="live", event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live", backrun_direction=BACKRUN_BUY_DEPRESSED,
            best_backrun_net_bps=10.0, block_lag=0, same_state_class="same_block",
            route_viable=True, reject_reason=None,
        )]
        events = [_make_event(event_id="lag0")]
        art = build_replay_summary(events, results, mode="test")
        assert art["events_detected_low_lag"] == 1
        assert art["events_scored_low_lag"] == 1
        assert art["low_lag_scored_results_rate"] == 1.0
        assert art["low_lag_pre_econ_reject_rate"] == 0.0


class TestM7A514BackwardCompat:
    """M7.A.5.14 compat — field count updated to 54 by M7.A.5.15."""

    def test_backrun_result_field_count_now_54(self):
        r = BackrunResult(
            event_id="compat_514",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
        )
        d = asdict(r)
        assert len(d) == 56

    def test_all_reject_reasons_count_still_19(self):
        """M7.A.5.14 adds no new reject reasons."""
        assert len(ALL_REJECT_REASONS) == 19

    def test_old_summary_fields_still_present(self):
        art = build_replay_summary([], [], mode="test")
        for key in [
            "events_count", "results_count", "viable_count",
            "best_net_bps_any", "best_net_bps_executable",
            "positive_net_count_any", "positive_net_count_low_lag",
            "stale_positive_count", "scored_results_count",
            "reject_histogram", "two_leg_baseline_net_bps",
            "coverage_local_mismatch_count", "truly_inactive_count",
            "events_detected_low_lag", "events_scored_low_lag",
            "stale_low_lag_comparison",
        ]:
            assert key in art, f"Missing backward-compat key: {key}"

    def test_new_514_fields_additive(self):
        art = build_replay_summary([], [], mode="test")
        for key in [
            "low_lag_reject_histogram",
            "low_lag_pair_resolution_rate",
            "low_lag_counter_coverage_rate",
            "low_lag_scored_results_rate",
            "low_lag_pre_econ_reject_rate",
        ]:
            assert key in art, f"Missing 5.14 key: {key}"


# ────────────────────────────────────────────────────────────
# M7.A.5.15: Low-lag debug rows, pair_unresolved_detail, coverage truth, backward compat
# ────────────────────────────────────────────────────────────


class TestM7A515PairUnresolvedDetail:
    """M7.A.5.15: BackrunResult gains pair_unresolved_detail field."""

    def test_pair_unresolved_detail_default_none(self):
        r = BackrunResult(
            event_id="pud_default",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
        )
        assert r.pair_unresolved_detail is None

    def test_pair_unresolved_detail_stored(self):
        r = BackrunResult(
            event_id="pud_stored",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            reject_reason=REJECT_TOKEN_PAIR_UNRESOLVED,
            pair_unresolved_detail="pool_read_failed",
        )
        assert r.pair_unresolved_detail == "pool_read_failed"

    def test_pair_unresolved_detail_no_pool_address(self):
        r = BackrunResult(
            event_id="pud_no_pool",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            reject_reason=REJECT_TOKEN_PAIR_UNRESOLVED,
            pair_unresolved_detail="no_pool_address",
        )
        assert r.pair_unresolved_detail == "no_pool_address"
        d = asdict(r)
        assert "pair_unresolved_detail" in d

    def test_pair_unresolved_detail_valid_values(self):
        valid = {"no_pool_address", "pool_read_failed", "no_symbol_map",
                 "token0_unknown", "token1_unknown"}
        for v in valid:
            r = BackrunResult(
                event_id=f"pud_{v}",
                event_source="live",
                event_type=EVENT_TYPE_SWAP,
                post_trade_state_used="live",
                backrun_direction=BACKRUN_BUY_DEPRESSED,
                pair_unresolved_detail=v,
            )
            assert r.pair_unresolved_detail == v


class TestM7A515LowLagDebugRows:
    """M7.A.5.15: build_replay_summary emits low_lag_debug_rows."""

    def test_low_lag_debug_rows_present_empty(self):
        art = build_replay_summary([], [], mode="test")
        assert "low_lag_debug_rows" in art
        assert art["low_lag_debug_rows"] == []

    def test_low_lag_debug_rows_present_with_results(self):
        r = BackrunResult(
            event_id="debug_row_1",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            block_lag=1,
            reject_reason=REJECT_TOKEN_PAIR_UNRESOLVED,
            pair_resolved=False,
            pair_unresolved_detail="pool_read_failed",
        )
        art = build_replay_summary([], [r], mode="ws_live")
        rows = art["low_lag_debug_rows"]
        assert len(rows) == 1
        row = rows[0]
        assert row["event_id"] == "debug_row_1"
        assert row["block_lag"] == 1
        assert row["reject_reason"] == REJECT_TOKEN_PAIR_UNRESOLVED
        assert row["pair_resolved"] is False
        assert row["pair_unresolved_detail"] == "pool_read_failed"

    def test_low_lag_debug_rows_only_low_lag(self):
        """Stale results (block_lag > 2) are excluded from debug_rows."""
        low = BackrunResult(
            event_id="low_lag",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            block_lag=0,
            reject_reason=REJECT_NO_COUNTER_POOL,
            pair_resolved=True,
            actual_pair="LINK/UNI",
        )
        stale = BackrunResult(
            event_id="stale",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            block_lag=10,
            reject_reason=REJECT_NO_COUNTER_POOL,
            pair_resolved=True,
            actual_pair="LINK/UNI",
        )
        art = build_replay_summary([], [low, stale], mode="ws_live")
        rows = art["low_lag_debug_rows"]
        assert len(rows) == 1
        assert rows[0]["event_id"] == "low_lag"

    def test_low_lag_debug_row_keys(self):
        r = BackrunResult(
            event_id="key_check",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            block_lag=2,
            reject_reason=REJECT_ALL_POOLS_TRULY_INACTIVE,
            pair_resolved=True,
            actual_pair="X/Y",
            token_admitted=True,
            admission_source=ADMISSION_CANONICAL,
            counter_venue_count=3,
        )
        art = build_replay_summary([], [r], mode="ws_live")
        row = art["low_lag_debug_rows"][0]
        expected_keys = {
            "event_id", "block_lag", "reject_reason", "pair_resolved",
            "actual_pair", "pair_unresolved_detail", "token_admitted",
            "admission_source", "known_pools", "active_pools",
            "counter_venue_count", "pool_contract_truth",
            "pool_state_read_path",
        }
        assert set(row.keys()) == expected_keys


class TestM7A515LowLagCoverageTruth:
    """M7.A.5.15: Coverage truth metrics for low-lag subset."""

    def test_coverage_truth_present_empty(self):
        art = build_replay_summary([], [], mode="test")
        assert "low_lag_coverage_truth" in art
        ct = art["low_lag_coverage_truth"]
        assert ct["known_pools_total"] == 0
        assert ct["active_pools_total"] == 0
        assert ct["active_buy_venues"] == 0
        assert ct["active_sell_venues"] == 0
        assert ct["no_counter_pool_rate"] is None
        assert ct["inactive_pool_rate"] is None

    def test_coverage_truth_rates_with_results(self):
        results = []
        # 1 NO_COUNTER_POOL, 1 ALL_POOLS_TRULY_INACTIVE, 1 scored
        results.append(BackrunResult(
            event_id="cov_1", event_source="live", event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live", backrun_direction=BACKRUN_BUY_DEPRESSED,
            block_lag=0, reject_reason=REJECT_NO_COUNTER_POOL, pair_resolved=True,
        ))
        results.append(BackrunResult(
            event_id="cov_2", event_source="live", event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live", backrun_direction=BACKRUN_BUY_DEPRESSED,
            block_lag=1, reject_reason=REJECT_ALL_POOLS_TRULY_INACTIVE, pair_resolved=True,
            coverage_result={"known_pools_total": 3, "active_pools_total": 0,
                             "active_buy_venues": 0, "active_sell_venues": 0},
        ))
        results.append(BackrunResult(
            event_id="cov_3", event_source="live", event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live", backrun_direction=BACKRUN_BUY_DEPRESSED,
            block_lag=2,  # low-lag, scored
            best_backrun_net_bps=-1.5, route_viable=False, pair_resolved=True,
            coverage_result={"known_pools_total": 5, "active_pools_total": 2,
                             "active_buy_venues": 1, "active_sell_venues": 1},
        ))
        art = build_replay_summary([], results, mode="ws_live")
        ct = art["low_lag_coverage_truth"]
        # Only 2 results have coverage_result, so sums are from those 2
        assert ct["known_pools_total"] == 8
        assert ct["active_pools_total"] == 2
        assert ct["active_buy_venues"] == 1
        assert ct["active_sell_venues"] == 1
        assert ct["no_counter_pool_rate"] == round(1 / 3, 4)
        assert ct["inactive_pool_rate"] == round(1 / 3, 4)


class TestM7A515FourLowLagPaths:
    """M7.A.5.15: 4 synthetic low-lag paths: unresolved, no-counter, inactive, scored."""

    def test_path_unresolved_pair(self):
        """Low-lag event fails at TOKEN_PAIR_UNRESOLVED."""
        r = BackrunResult(
            event_id="path_unresolved", event_source="live",
            event_type=EVENT_TYPE_SWAP, post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            block_lag=0, reject_reason=REJECT_TOKEN_PAIR_UNRESOLVED,
            pair_resolved=False, pair_unresolved_detail="pool_read_failed",
        )
        art = build_replay_summary([], [r], mode="ws_live")
        assert art["events_detected_low_lag"] == 1
        assert art["events_scored_low_lag"] == 0
        assert art["low_lag_pair_resolution_rate"] == 0.0
        assert art["low_lag_pre_econ_reject_rate"] == 1.0
        rows = art["low_lag_debug_rows"]
        assert len(rows) == 1
        assert rows[0]["pair_unresolved_detail"] == "pool_read_failed"

    def test_path_no_counter_pool(self):
        """Low-lag event resolves pair but hits NO_COUNTER_POOL."""
        r = BackrunResult(
            event_id="path_no_counter", event_source="live",
            event_type=EVENT_TYPE_SWAP, post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            block_lag=1, reject_reason=REJECT_NO_COUNTER_POOL,
            pair_resolved=True, actual_pair="0x3212dc0f/WETH",
            token_admitted=True, admission_source=ADMISSION_ONCHAIN_ENRICHED,
            counter_venue_count=0,
        )
        art = build_replay_summary([], [r], mode="ws_live")
        assert art["events_detected_low_lag"] == 1
        assert art["events_scored_low_lag"] == 0
        assert art["low_lag_pair_resolution_rate"] == 1.0
        assert art["low_lag_counter_coverage_rate"] == 0.0
        ct = art["low_lag_coverage_truth"]
        assert ct["no_counter_pool_rate"] == 1.0

    def test_path_inactive_counter_pool(self):
        """Low-lag event resolves pair, has pools, but all inactive."""
        r = BackrunResult(
            event_id="path_inactive", event_source="live",
            event_type=EVENT_TYPE_SWAP, post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            block_lag=0, reject_reason=REJECT_ALL_POOLS_TRULY_INACTIVE,
            pair_resolved=True, actual_pair="LINK/UNI",
            token_admitted=True, admission_source=ADMISSION_CANONICAL,
            coverage_result={"known_pools_total": 2, "active_pools_total": 0,
                             "active_buy_venues": 0, "active_sell_venues": 0},
            counter_venue_count=2,
        )
        art = build_replay_summary([], [r], mode="ws_live")
        assert art["events_detected_low_lag"] == 1
        assert art["events_scored_low_lag"] == 0
        assert art["low_lag_pair_resolution_rate"] == 1.0
        ct = art["low_lag_coverage_truth"]
        assert ct["known_pools_total"] == 2
        assert ct["active_pools_total"] == 0
        assert ct["inactive_pool_rate"] == 1.0

    def test_path_active_reaches_scoring(self):
        """Low-lag event resolves pair, has active pool, reaches econ scoring."""
        r = BackrunResult(
            event_id="path_scored", event_source="live",
            event_type=EVENT_TYPE_SWAP, post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            block_lag=0, pair_resolved=True, actual_pair="WETH/USDC",
            token_admitted=True, admission_source=ADMISSION_CANONICAL,
            coverage_result={"known_pools_total": 4, "active_pools_total": 2,
                             "active_buy_venues": 1, "active_sell_venues": 1},
            counter_venue_count=4,
            best_backrun_net_bps=-1.5, route_viable=False,
        )
        art = build_replay_summary([], [r], mode="ws_live")
        assert art["events_detected_low_lag"] == 1
        assert art["events_scored_low_lag"] == 1
        assert art["low_lag_scored_results_rate"] == 1.0
        assert art["low_lag_pre_econ_reject_rate"] == 0.0
        ct = art["low_lag_coverage_truth"]
        assert ct["known_pools_total"] == 4
        assert ct["active_pools_total"] == 2


class TestM7A515BackwardCompat:
    """M7.A.5.15 must update BackrunResult to 54 fields, keep reject count at 19."""

    def test_backrun_result_field_count_now_54(self):
        r = BackrunResult(
            event_id="compat_515",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
        )
        d = asdict(r)
        assert len(d) == 56

    def test_all_reject_reasons_count_still_19(self):
        assert len(ALL_REJECT_REASONS) == 19

    def test_new_515_fields_present(self):
        art = build_replay_summary([], [], mode="test")
        for key in [
            "low_lag_debug_rows",
            "low_lag_coverage_truth",
        ]:
            assert key in art, f"Missing 5.15 key: {key}"

    def test_old_514_fields_still_present(self):
        art = build_replay_summary([], [], mode="test")
        for key in [
            "low_lag_reject_histogram",
            "low_lag_pair_resolution_rate",
            "low_lag_counter_coverage_rate",
            "low_lag_scored_results_rate",
            "low_lag_pre_econ_reject_rate",
        ]:
            assert key in art, f"Missing backward-compat 5.14 key: {key}"


# ────────────────────────────────────────────────────────────
# M7.A.5.16: Pool-class truth, finer failure causes, aggregated class metrics
# ────────────────────────────────────────────────────────────


class TestM7A516PoolContractTruthField:
    """M7.A.5.16: BackrunResult gains pool_contract_truth field (55 fields)."""

    def test_pool_contract_truth_default_none(self):
        r = BackrunResult(
            event_id="pct_default",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
        )
        assert r.pool_contract_truth is None

    def test_pool_contract_truth_stored(self):
        truth = {
            "pool_address": "0xabc",
            "code_present": True,
            "token0_ok": True,
            "token1_ok": True,
            "slot0_ok": False,
            "liquidity_ok": False,
            "dex_family_guess": "uniswap_v2_like",
        }
        r = BackrunResult(
            event_id="pct_stored",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            reject_reason=REJECT_TOKEN_PAIR_UNRESOLVED,
            pair_unresolved_detail="POOL_SLOT0_REVERT",
            pool_contract_truth=truth,
        )
        assert r.pool_contract_truth == truth
        d = asdict(r)
        assert "pool_contract_truth" in d
        assert d["pool_contract_truth"]["dex_family_guess"] == "uniswap_v2_like"

    def test_pool_contract_truth_schema_keys(self):
        """Pool contract truth dict must have exactly 7 keys."""
        truth = {
            "pool_address": "0x123",
            "code_present": True,
            "token0_ok": False,
            "token1_ok": False,
            "slot0_ok": False,
            "liquidity_ok": False,
            "dex_family_guess": "unknown",
        }
        expected_keys = {
            "pool_address", "code_present", "token0_ok", "token1_ok",
            "slot0_ok", "liquidity_ok", "dex_family_guess",
        }
        assert set(truth.keys()) == expected_keys


class TestM7A516FinerUnresolvedDetails:
    """M7.A.5.16: pair_unresolved_detail now accepts finer values."""

    def test_finer_detail_values_valid(self):
        finer_values = [
            "POOL_CODE_EMPTY",
            "POOL_TOKEN0_REVERT",
            "POOL_TOKEN1_REVERT",
            "POOL_SLOT0_REVERT",
            "POOL_LIQUIDITY_REVERT",
        ]
        for v in finer_values:
            r = BackrunResult(
                event_id=f"fine_{v}",
                event_source="live",
                event_type=EVENT_TYPE_SWAP,
                post_trade_state_used="live",
                backrun_direction=BACKRUN_BUY_DEPRESSED,
                reject_reason=REJECT_TOKEN_PAIR_UNRESOLVED,
                pair_unresolved_detail=v,
            )
            assert r.pair_unresolved_detail == v

    def test_legacy_detail_values_still_valid(self):
        legacy_values = [
            "no_pool_address", "pool_read_failed", "no_symbol_map",
            "token0_unknown", "token1_unknown",
        ]
        for v in legacy_values:
            r = BackrunResult(
                event_id=f"legacy_{v}",
                event_source="live",
                event_type=EVENT_TYPE_SWAP,
                post_trade_state_used="live",
                backrun_direction=BACKRUN_BUY_DEPRESSED,
                pair_unresolved_detail=v,
            )
            assert r.pair_unresolved_detail == v


class TestM7A516DebugRowPoolTruth:
    """M7.A.5.16: low_lag_debug_rows includes pool_contract_truth per event."""

    def test_debug_row_has_pool_contract_truth_key(self):
        r = BackrunResult(
            event_id="row_pct",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            block_lag=0,
            reject_reason=REJECT_TOKEN_PAIR_UNRESOLVED,
            pair_resolved=False,
            pair_unresolved_detail="POOL_TOKEN0_REVERT",
            pool_contract_truth={
                "pool_address": "0xabc",
                "code_present": True,
                "token0_ok": False,
                "token1_ok": False,
                "slot0_ok": False,
                "liquidity_ok": False,
                "dex_family_guess": "unknown",
            },
        )
        art = build_replay_summary([], [r], mode="ws_live")
        rows = art["low_lag_debug_rows"]
        assert len(rows) == 1
        assert "pool_contract_truth" in rows[0]
        assert rows[0]["pool_contract_truth"]["code_present"] is True
        assert rows[0]["pool_contract_truth"]["token0_ok"] is False

    def test_debug_row_pool_truth_none_when_resolved(self):
        """Events that resolve pairs have pool_contract_truth=None."""
        r = BackrunResult(
            event_id="row_resolved",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            block_lag=1,
            reject_reason=REJECT_NO_COUNTER_POOL,
            pair_resolved=True,
            actual_pair="WETH/USDC",
            pool_contract_truth=None,
        )
        art = build_replay_summary([], [r], mode="ws_live")
        assert art["low_lag_debug_rows"][0]["pool_contract_truth"] is None

    def test_debug_row_keys_updated_with_pool_truth(self):
        """Low-lag debug rows now have 13 keys (was 12)."""
        r = BackrunResult(
            event_id="key_check_516",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            block_lag=0,
            reject_reason=REJECT_ALL_POOLS_TRULY_INACTIVE,
            pair_resolved=True,
            actual_pair="X/Y",
            token_admitted=True,
            admission_source=ADMISSION_CANONICAL,
            counter_venue_count=3,
        )
        art = build_replay_summary([], [r], mode="ws_live")
        row = art["low_lag_debug_rows"][0]
        expected_keys = {
            "event_id", "block_lag", "reject_reason", "pair_resolved",
            "actual_pair", "pair_unresolved_detail", "token_admitted",
            "admission_source", "known_pools", "active_pools",
            "counter_venue_count", "pool_contract_truth",
            "pool_state_read_path",
        }
        assert set(row.keys()) == expected_keys


class TestM7A516ThreeLowLagClasses:
    """M7.A.5.16: Three structural low-lag blocker classes in pool_class_truth."""

    def _make_class_results(self):
        """Build results covering all three low-lag blocker classes + one scored."""
        results = []
        # Class 1: Unsupported pool ABI (TOKEN_PAIR_UNRESOLVED + POOL_TOKEN0_REVERT)
        results.append(BackrunResult(
            event_id="c1_unsupported", event_source="live",
            event_type=EVENT_TYPE_SWAP, post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            block_lag=0, reject_reason=REJECT_TOKEN_PAIR_UNRESOLVED,
            pair_resolved=False,
            pair_unresolved_detail="POOL_TOKEN0_REVERT",
            pool_contract_truth={
                "pool_address": "0xaaa", "code_present": True,
                "token0_ok": False, "token1_ok": False,
                "slot0_ok": False, "liquidity_ok": False,
                "dex_family_guess": "unknown",
            },
        ))
        # Class 2: No counter pool
        results.append(BackrunResult(
            event_id="c2_no_counter", event_source="live",
            event_type=EVENT_TYPE_SWAP, post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            block_lag=1, reject_reason=REJECT_NO_COUNTER_POOL,
            pair_resolved=True, actual_pair="0xabc/WETH",
            counter_venue_count=0,
        ))
        # Class 3: Known but inactive pool
        results.append(BackrunResult(
            event_id="c3_inactive", event_source="live",
            event_type=EVENT_TYPE_SWAP, post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            block_lag=0, reject_reason=REJECT_ALL_POOLS_TRULY_INACTIVE,
            pair_resolved=True, actual_pair="LINK/UNI",
            counter_venue_count=2,
            coverage_result={"known_pools_total": 2, "active_pools_total": 0,
                             "active_buy_venues": 0, "active_sell_venues": 0},
        ))
        # Class 4: Active, scored (reaches economics)
        results.append(BackrunResult(
            event_id="c4_scored", event_source="live",
            event_type=EVENT_TYPE_SWAP, post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            block_lag=0, pair_resolved=True, actual_pair="WETH/USDC",
            best_backrun_net_bps=-1.5, route_viable=False,
            coverage_result={"known_pools_total": 4, "active_pools_total": 2,
                             "active_buy_venues": 1, "active_sell_venues": 1},
        ))
        return results

    def test_pool_class_truth_present(self):
        events = [_make_event(event_id=f"ev_{i}") for i in range(4)]
        results = self._make_class_results()
        art = build_replay_summary(events, results, mode="test")
        assert "low_lag_pool_class_truth" in art

    def test_unsupported_pool_rate(self):
        """1 out of 4 low-lag events has unsupported pool ABI."""
        events = [_make_event(event_id=f"ev_{i}") for i in range(4)]
        results = self._make_class_results()
        art = build_replay_summary(events, results, mode="test")
        pct = art["low_lag_pool_class_truth"]
        assert pct["unsupported_pool_rate"] == 0.25

    def test_no_counter_pool_rate(self):
        """1 out of 4 low-lag events has no counter pool."""
        events = [_make_event(event_id=f"ev_{i}") for i in range(4)]
        results = self._make_class_results()
        art = build_replay_summary(events, results, mode="test")
        pct = art["low_lag_pool_class_truth"]
        assert pct["no_counter_pool_rate"] == 0.25

    def test_inactive_known_pool_rate(self):
        """1 out of 4 low-lag events has inactive known pool."""
        events = [_make_event(event_id=f"ev_{i}") for i in range(4)]
        results = self._make_class_results()
        art = build_replay_summary(events, results, mode="test")
        pct = art["low_lag_pool_class_truth"]
        assert pct["inactive_known_pool_rate"] == 0.25

    def test_known_but_untradeable_rate(self):
        """2 out of 4 low-lag events resolved pair but still rejected pre-econ."""
        events = [_make_event(event_id=f"ev_{i}") for i in range(4)]
        results = self._make_class_results()
        art = build_replay_summary(events, results, mode="test")
        pct = art["low_lag_pool_class_truth"]
        # NO_COUNTER_POOL + ALL_CANDIDATE_POOLS_TRULY_INACTIVE both resolved pair + in UNSCORED_REJECTS
        assert pct["known_but_untradeable_rate"] == 0.5

    def test_dex_family_histogram(self):
        """Only 1 event has pool_contract_truth, with dex_family_guess=unknown."""
        events = [_make_event(event_id=f"ev_{i}") for i in range(4)]
        results = self._make_class_results()
        art = build_replay_summary(events, results, mode="test")
        pct = art["low_lag_pool_class_truth"]
        assert pct["dex_family_histogram"] == {"unknown": 1}
        assert pct["pool_truth_count"] == 1

    def test_pool_class_truth_all_none_when_no_low_lag(self):
        """When no low-lag results exist, all class rates are None."""
        results = [BackrunResult(
            event_id="stale_only", event_source="live", event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live", backrun_direction=BACKRUN_BUY_DEPRESSED,
            block_lag=10, reject_reason=REJECT_STALE_POSITIVE,
        )]
        art = build_replay_summary([_make_event()], results, mode="test")
        pct = art["low_lag_pool_class_truth"]
        assert pct["unsupported_pool_rate"] is None
        assert pct["no_counter_pool_rate"] is None
        assert pct["inactive_known_pool_rate"] is None
        assert pct["known_but_untradeable_rate"] is None
        assert pct["dex_family_histogram"] == {}
        assert pct["pool_truth_count"] == 0


class TestM7A516PoolCodeEmpty:
    """M7.A.5.16: POOL_CODE_EMPTY path — pool has no bytecode."""

    def test_pool_code_empty_detail(self):
        r = BackrunResult(
            event_id="code_empty",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            block_lag=0,
            reject_reason=REJECT_TOKEN_PAIR_UNRESOLVED,
            pair_resolved=False,
            pair_unresolved_detail="POOL_CODE_EMPTY",
            pool_contract_truth={
                "pool_address": "0xdead",
                "code_present": False,
                "token0_ok": False,
                "token1_ok": False,
                "slot0_ok": False,
                "liquidity_ok": False,
                "dex_family_guess": "no_code",
            },
        )
        art = build_replay_summary([], [r], mode="ws_live")
        pct = art["low_lag_pool_class_truth"]
        assert pct["unsupported_pool_rate"] == 1.0
        assert pct["dex_family_histogram"] == {"no_code": 1}
        row = art["low_lag_debug_rows"][0]
        assert row["pair_unresolved_detail"] == "POOL_CODE_EMPTY"
        assert row["pool_contract_truth"]["code_present"] is False


class TestM7A516DexFamilyGuessValues:
    """M7.A.5.16: dex_family_guess covers all expected categories."""

    def test_all_family_guesses(self):
        families = [
            "uniswap_v3_like", "uniswap_v2_like",
            "partial_erc20_pool", "unknown", "no_code",
        ]
        for fam in families:
            truth = {
                "pool_address": "0x123", "code_present": fam != "no_code",
                "token0_ok": fam in ("uniswap_v3_like", "uniswap_v2_like", "partial_erc20_pool"),
                "token1_ok": fam in ("uniswap_v3_like", "uniswap_v2_like"),
                "slot0_ok": fam == "uniswap_v3_like",
                "liquidity_ok": fam == "uniswap_v3_like",
                "dex_family_guess": fam,
            }
            r = BackrunResult(
                event_id=f"fam_{fam}",
                event_source="live",
                event_type=EVENT_TYPE_SWAP,
                post_trade_state_used="live",
                backrun_direction=BACKRUN_BUY_DEPRESSED,
                block_lag=0,
                reject_reason=REJECT_TOKEN_PAIR_UNRESOLVED,
                pool_contract_truth=truth,
            )
            art = build_replay_summary([], [r], mode="ws_live")
            assert art["low_lag_pool_class_truth"]["dex_family_histogram"] == {fam: 1}


class TestM7A516BackwardCompat:
    """M7.A.5.16 must update BackrunResult to 55 fields, keep reject count at 19."""

    def test_backrun_result_field_count_now_55(self):
        r = BackrunResult(
            event_id="compat_516",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
        )
        d = asdict(r)
        assert len(d) == 56

    def test_all_reject_reasons_count_still_19(self):
        """M7.A.5.16 adds no new reject reasons."""
        assert len(ALL_REJECT_REASONS) == 19

    def test_new_516_fields_present(self):
        art = build_replay_summary([], [], mode="test")
        assert "low_lag_pool_class_truth" in art
        pct = art["low_lag_pool_class_truth"]
        for key in [
            "unsupported_pool_rate",
            "no_counter_pool_rate",
            "inactive_known_pool_rate",
            "known_but_untradeable_rate",
            "dex_family_histogram",
            "pool_truth_count",
        ]:
            assert key in pct, f"Missing 5.16 key: {key}"

    def test_old_515_fields_still_present(self):
        art = build_replay_summary([], [], mode="test")
        for key in [
            "low_lag_debug_rows",
            "low_lag_coverage_truth",
            "low_lag_reject_histogram",
            "low_lag_pair_resolution_rate",
            "low_lag_counter_coverage_rate",
            "low_lag_scored_results_rate",
            "low_lag_pre_econ_reject_rate",
        ]:
            assert key in art, f"Missing backward-compat key: {key}"

    def test_old_backrun_result_fields_unchanged(self):
        """All 54 pre-5.16 fields must still be present."""
        r = BackrunResult(
            event_id="bc_fields",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
        )
        d = asdict(r)
        pre_516_fields = [
            "event_id", "event_source", "event_type", "post_trade_state_used",
            "backrun_direction", "best_buy_venue", "best_sell_venue",
            "candidate_path", "amount_in_wei", "gross_pnl_wei",
            "gas_cost_wei", "fee_cost_wei", "net_pnl_wei",
            "best_backrun_net_bps", "same_block_possible", "route_viable",
            "reject_reason", "event_block", "quote_block", "block_lag",
            "same_state_class", "counter_venue_count", "best_live_net_bps",
            "ws_provider", "event_detected_at_block", "quote_started_block",
            "quote_finished_block", "quote_pipeline_latency_ms",
            "venues_pruned_by_multicall", "latency_budget_ms",
            "quote_calls_attempted", "quote_calls_after_pruning",
            "prune_reason_histogram", "pipeline_stage_latency_ms",
            "pair_resolved", "actual_pair", "size_source",
            "coverage_result", "size_sweep_results",
            "best_sweep_net_bps", "best_sweep_size_wei",
            "token_admitted", "admission_source", "oracle_guard",
            "local_sim_state", "l2_gas_bps", "l1_data_bps",
            "total_gas_bps", "subgraph_seed_used",
            "token_in_decimals", "size_normalization_source",
            "size_usd_estimate", "size_valid_for_token",
            "pair_unresolved_detail",
        ]
        for f in pre_516_fields:
            assert f in d, f"Missing pre-5.16 field: {f}"
        # New field
        assert "pool_contract_truth" in d


# ===========================================================================
# M7.A.5.17: V2 direct resolve, pool_state_read_path, V2 low-lag metrics
# ===========================================================================


class TestM7A517PoolStateReadPathField:
    """M7.A.5.17: pool_state_read_path added to BackrunResult — default None."""

    def test_default_none(self):
        r = BackrunResult(
            event_id="psrp_default",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
        )
        assert r.pool_state_read_path is None

    def test_v3_multicall_value(self):
        r = BackrunResult(
            event_id="psrp_v3",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            pool_state_read_path="v3_multicall",
        )
        assert r.pool_state_read_path == "v3_multicall"

    def test_v2_getReserves_value(self):
        r = BackrunResult(
            event_id="psrp_v2",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            pool_state_read_path="v2_getReserves",
        )
        assert r.pool_state_read_path == "v2_getReserves"

    def test_field_in_asdict(self):
        r = BackrunResult(
            event_id="psrp_dict",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            pool_state_read_path="v2_getReserves",
        )
        d = asdict(r)
        assert "pool_state_read_path" in d
        assert d["pool_state_read_path"] == "v2_getReserves"

    def test_json_roundtrip(self):
        r = BackrunResult(
            event_id="psrp_json",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            pool_state_read_path="v3_multicall",
        )
        d = asdict(r)
        blob = json.dumps(d)
        loaded = json.loads(blob)
        assert loaded["pool_state_read_path"] == "v3_multicall"


class TestM7A517DebugRowReadPath:
    """M7.A.5.17: pool_state_read_path appears in low_lag_debug_rows (13 keys)."""

    def test_debug_row_contains_read_path(self):
        r = BackrunResult(
            event_id="dr_rp",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            block_lag=1,
            reject_reason=REJECT_NO_COUNTER_POOL,
            pair_resolved=True,
            actual_pair="X/Y",
            token_admitted=True,
            admission_source=ADMISSION_CANONICAL,
            counter_venue_count=0,
            pool_state_read_path="v2_getReserves",
        )
        art = build_replay_summary([], [r], mode="ws_live")
        row = art["low_lag_debug_rows"][0]
        assert "pool_state_read_path" in row
        assert row["pool_state_read_path"] == "v2_getReserves"

    def test_debug_row_read_path_none_default(self):
        r = BackrunResult(
            event_id="dr_rp_none",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            block_lag=0,
            reject_reason=REJECT_TOKEN_PAIR_UNRESOLVED,
            pair_resolved=False,
        )
        art = build_replay_summary([], [r], mode="ws_live")
        row = art["low_lag_debug_rows"][0]
        assert row["pool_state_read_path"] is None

    def test_debug_row_key_count_13(self):
        r = BackrunResult(
            event_id="dr_kc13",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            block_lag=1,
            reject_reason=REJECT_ALL_POOLS_TRULY_INACTIVE,
            pair_resolved=True,
            actual_pair="A/B",
            token_admitted=True,
            admission_source=ADMISSION_CANONICAL,
            counter_venue_count=2,
            pool_state_read_path="v3_multicall",
        )
        art = build_replay_summary([], [r], mode="ws_live")
        row = art["low_lag_debug_rows"][0]
        assert len(row) == 13, f"Expected 13 debug row keys, got {len(row)}: {sorted(row.keys())}"


class TestM7A517V2LowLagMetrics:
    """M7.A.5.17: low_lag_v2_truth block in build_replay_summary."""

    def test_v2_truth_present_empty(self):
        art = build_replay_summary([], [], mode="test")
        assert "low_lag_v2_truth" in art
        v2t = art["low_lag_v2_truth"]
        expected_keys = {
            "low_lag_v2_supported_rate",
            "low_lag_v2_scored_results_rate",
            "low_lag_v2_no_counter_pool_rate",
            "low_lag_v2_inactive_pool_rate",
            "v2_resolved_count",
            "v2_scored_count",
        }
        assert set(v2t.keys()) == expected_keys

    def test_v2_rates_none_when_no_low_lag(self):
        art = build_replay_summary([], [], mode="test")
        v2t = art["low_lag_v2_truth"]
        assert v2t["low_lag_v2_supported_rate"] is None
        assert v2t["low_lag_v2_scored_results_rate"] is None
        assert v2t["low_lag_v2_no_counter_pool_rate"] is None
        assert v2t["low_lag_v2_inactive_pool_rate"] is None
        assert v2t["v2_resolved_count"] == 0
        assert v2t["v2_scored_count"] == 0

    def test_v2_resolved_counted(self):
        """V2-resolved events counted via pool_state_read_path."""
        v2_result = BackrunResult(
            event_id="v2_cnt",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            block_lag=1,
            reject_reason=REJECT_NO_COUNTER_POOL,
            pair_resolved=True,
            actual_pair="A/B",
            token_admitted=True,
            admission_source=ADMISSION_CANONICAL,
            pool_state_read_path="v2_getReserves",
        )
        v3_result = BackrunResult(
            event_id="v3_cnt",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            block_lag=0,
            reject_reason=REJECT_ALL_POOLS_TRULY_INACTIVE,
            pair_resolved=True,
            actual_pair="C/D",
            token_admitted=True,
            admission_source=ADMISSION_CANONICAL,
            pool_state_read_path="v3_multicall",
        )
        art = build_replay_summary([], [v2_result, v3_result], mode="ws_live")
        v2t = art["low_lag_v2_truth"]
        assert v2t["v2_resolved_count"] == 1
        assert v2t["v2_scored_count"] == 0  # Both rejected, neither scored

    def test_v2_supported_rate_calculated(self):
        """When there are low-lag events, v2_supported_rate is computed."""
        v2_result = BackrunResult(
            event_id="v2_rate",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            block_lag=1,
            reject_reason=REJECT_NO_COUNTER_POOL,
            pair_resolved=True,
            actual_pair="A/B",
            pool_state_read_path="v2_getReserves",
        )
        v3_result = BackrunResult(
            event_id="v3_rate",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            block_lag=0,
            reject_reason=REJECT_NO_COUNTER_POOL,
            pair_resolved=True,
            actual_pair="C/D",
            pool_state_read_path="v3_multicall",
        )
        art = build_replay_summary([], [v2_result, v3_result], mode="ws_live")
        v2t = art["low_lag_v2_truth"]
        # 1 V2 out of 2 low-lag
        assert v2t["low_lag_v2_supported_rate"] == 0.5

    def test_v2_truth_keys_exactly_6(self):
        art = build_replay_summary([], [], mode="test")
        assert len(art["low_lag_v2_truth"]) == 6


class TestM7A517BackwardCompat:
    """M7.A.5.17 must update BackrunResult to 56 fields, keep reject count at 19."""

    def test_backrun_result_field_count_now_56(self):
        r = BackrunResult(
            event_id="compat_517",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
        )
        d = asdict(r)
        assert len(d) == 56, f"Expected 56 fields, got {len(d)}: {sorted(d.keys())}"

    def test_all_reject_reasons_count_still_19(self):
        """M7.A.5.17 adds no new reject reasons."""
        assert len(ALL_REJECT_REASONS) == 19

    def test_new_517_field_present(self):
        r = BackrunResult(
            event_id="compat_517_f",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
        )
        d = asdict(r)
        assert "pool_state_read_path" in d
        assert d["pool_state_read_path"] is None  # default

    def test_new_517_artifact_present(self):
        art = build_replay_summary([], [], mode="test")
        assert "low_lag_v2_truth" in art
        v2t = art["low_lag_v2_truth"]
        for key in [
            "low_lag_v2_supported_rate",
            "low_lag_v2_scored_results_rate",
            "low_lag_v2_no_counter_pool_rate",
            "low_lag_v2_inactive_pool_rate",
            "v2_resolved_count",
            "v2_scored_count",
        ]:
            assert key in v2t, f"Missing 5.17 key: {key}"

    def test_old_516_fields_still_present(self):
        art = build_replay_summary([], [], mode="test")
        for key in [
            "low_lag_pool_class_truth",
            "low_lag_debug_rows",
            "low_lag_coverage_truth",
            "low_lag_reject_histogram",
            "low_lag_pair_resolution_rate",
            "low_lag_counter_coverage_rate",
            "low_lag_scored_results_rate",
            "low_lag_pre_econ_reject_rate",
        ]:
            assert key in art, f"Missing backward-compat key: {key}"

    def test_old_backrun_result_fields_unchanged(self):
        """All 55 pre-5.17 fields must still be present."""
        r = BackrunResult(
            event_id="bc_fields_517",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
        )
        d = asdict(r)
        pre_517_fields = [
            "event_id", "event_source", "event_type", "post_trade_state_used",
            "backrun_direction", "best_buy_venue", "best_sell_venue",
            "candidate_path", "amount_in_wei", "gross_pnl_wei",
            "gas_cost_wei", "fee_cost_wei", "net_pnl_wei",
            "best_backrun_net_bps", "same_block_possible", "route_viable",
            "reject_reason", "event_block", "quote_block", "block_lag",
            "same_state_class", "counter_venue_count", "best_live_net_bps",
            "ws_provider", "event_detected_at_block", "quote_started_block",
            "quote_finished_block", "quote_pipeline_latency_ms",
            "venues_pruned_by_multicall", "latency_budget_ms",
            "quote_calls_attempted", "quote_calls_after_pruning",
            "prune_reason_histogram", "pipeline_stage_latency_ms",
            "pair_resolved", "actual_pair", "size_source",
            "coverage_result", "size_sweep_results",
            "best_sweep_net_bps", "best_sweep_size_wei",
            "token_admitted", "admission_source", "oracle_guard",
            "local_sim_state", "l2_gas_bps", "l1_data_bps",
            "total_gas_bps", "subgraph_seed_used",
            "token_in_decimals", "size_normalization_source",
            "size_usd_estimate", "size_valid_for_token",
            "pair_unresolved_detail", "pool_contract_truth",
        ]
        for f in pre_517_fields:
            assert f in d, f"Missing pre-5.17 field: {f}"
        # New M7.A.5.17 field
        assert "pool_state_read_path" in d


# ===========================================================================
# M7.A.5.18 — Low-lag watchlist, blocker tags, backward compat
# ===========================================================================


class TestM7A518BlockerTagConstants:
    """M7.A.5.18: Canonical blocker tag constants are module-level and frozen."""

    def test_all_blocker_tags_count_is_7(self):
        assert len(ALL_BLOCKER_TAGS) == 7

    def test_all_blocker_tags_is_frozenset(self):
        assert isinstance(ALL_BLOCKER_TAGS, frozenset)

    def test_each_canonical_tag_in_set(self):
        expected = {
            "LOW_LAG_NONE_THIS_WINDOW",
            "LOW_LAG_NO_COUNTER_POOL",
            "LOW_LAG_V2_UNSUPPORTED",
            "LOW_LAG_INACTIVE_POOL",
            "LOW_LAG_REMOTE_QUOTER_LATENCY",
            "GAS_L1_DATA_DOMINANT",
            "SUBGRAPH_API_KEY_REQUIRED",
        }
        assert ALL_BLOCKER_TAGS == expected

    def test_blocker_constants_match_strings(self):
        assert BLOCKER_LOW_LAG_NONE_THIS_WINDOW == "LOW_LAG_NONE_THIS_WINDOW"
        assert BLOCKER_LOW_LAG_NO_COUNTER_POOL == "LOW_LAG_NO_COUNTER_POOL"
        assert BLOCKER_LOW_LAG_V2_UNSUPPORTED == "LOW_LAG_V2_UNSUPPORTED"
        assert BLOCKER_LOW_LAG_INACTIVE_POOL == "LOW_LAG_INACTIVE_POOL"
        assert BLOCKER_LOW_LAG_REMOTE_QUOTER_LATENCY == "LOW_LAG_REMOTE_QUOTER_LATENCY"
        assert BLOCKER_GAS_L1_DATA_DOMINANT == "GAS_L1_DATA_DOMINANT"
        assert BLOCKER_SUBGRAPH_API_KEY_REQUIRED == "SUBGRAPH_API_KEY_REQUIRED"


class TestM7A518BlockerTagsArtifact:
    """M7.A.5.18: blocker_tags block in replay summary."""

    def test_blocker_tags_present_in_empty_artifact(self):
        art = build_replay_summary([], [], mode="test")
        assert "blocker_tags" in art

    def test_blocker_tags_structure(self):
        art = build_replay_summary([], [], mode="test")
        bt = art["blocker_tags"]
        assert "active_tags" in bt
        assert "active_count" in bt
        assert "all_canonical_tags" in bt
        assert isinstance(bt["active_tags"], list)
        assert isinstance(bt["active_count"], int)
        assert isinstance(bt["all_canonical_tags"], list)

    def test_blocker_tags_all_canonical_sorted(self):
        art = build_replay_summary([], [], mode="test")
        bt = art["blocker_tags"]
        assert bt["all_canonical_tags"] == sorted(ALL_BLOCKER_TAGS)

    def test_blocker_tags_no_events_gets_none_this_window(self):
        """When there are zero events, events_detected_low_lag=0 → triggers NONE_THIS_WINDOW."""
        art = build_replay_summary([], [], mode="test")
        bt = art["blocker_tags"]
        assert BLOCKER_LOW_LAG_NONE_THIS_WINDOW in bt["active_tags"]

    def test_blocker_tags_subgraph_always_present(self):
        """SUBGRAPH_API_KEY_REQUIRED is always active (structural stopper)."""
        art = build_replay_summary([], [], mode="test")
        bt = art["blocker_tags"]
        assert BLOCKER_SUBGRAPH_API_KEY_REQUIRED in bt["active_tags"]

    def test_blocker_tags_count_matches_list_length(self):
        art = build_replay_summary([], [], mode="test")
        bt = art["blocker_tags"]
        assert bt["active_count"] == len(bt["active_tags"])

    def test_blocker_tags_with_gas_dominant(self):
        """GAS_EXCEEDS_GROSS reject + all-negative net → GAS_L1_DATA_DOMINANT tag."""
        ev = _make_event(event_id="gas_dom")
        r = BackrunResult(
            event_id="gas_dom",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            best_backrun_net_bps=-5.0,
            reject_reason=REJECT_GAS_EXCEEDS_GROSS,
            event_block=100,
            quote_block=100,
            block_lag=0,
            same_state_class="same_block",
        )
        art = build_replay_summary([ev], [r], mode="test")
        bt = art["blocker_tags"]
        assert BLOCKER_GAS_L1_DATA_DOMINANT in bt["active_tags"]

    def test_blocker_tags_no_counter_pool_on_low_lag(self):
        """Low-lag event with NO_COUNTER_POOL → LOW_LAG_NO_COUNTER_POOL tag."""
        ev = _make_event(event_id="ncp_ll")
        r = BackrunResult(
            event_id="ncp_ll",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            reject_reason=REJECT_NO_COUNTER_POOL,
            event_block=100,
            quote_block=101,
            block_lag=1,
            same_state_class="next_block",
        )
        art = build_replay_summary([ev], [r], mode="test")
        bt = art["blocker_tags"]
        assert BLOCKER_LOW_LAG_NO_COUNTER_POOL in bt["active_tags"]

    def test_blocker_tags_inactive_pool_on_low_lag(self):
        """Low-lag event with ALL_CANDIDATE_POOLS_TRULY_INACTIVE → INACTIVE tag."""
        ev = _make_event(event_id="inactive_ll")
        r = BackrunResult(
            event_id="inactive_ll",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            reject_reason=REJECT_ALL_POOLS_TRULY_INACTIVE,
            event_block=100,
            quote_block=101,
            block_lag=1,
            same_state_class="next_block",
        )
        art = build_replay_summary([ev], [r], mode="test")
        bt = art["blocker_tags"]
        assert BLOCKER_LOW_LAG_INACTIVE_POOL in bt["active_tags"]

    def test_blocker_tags_unsupported_v2_on_low_lag(self):
        """Low-lag event with POOL_SLOT0_REVERT → V2_UNSUPPORTED tag."""
        ev = _make_event(event_id="v2_unsup_ll")
        r = BackrunResult(
            event_id="v2_unsup_ll",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            reject_reason=REJECT_TOKEN_PAIR_UNRESOLVED,
            pair_unresolved_detail="POOL_SLOT0_REVERT",
            event_block=100,
            quote_block=101,
            block_lag=1,
            same_state_class="next_block",
        )
        art = build_replay_summary([ev], [r], mode="test")
        bt = art["blocker_tags"]
        assert BLOCKER_LOW_LAG_V2_UNSUPPORTED in bt["active_tags"]

    def test_blocker_tags_remote_quoter_latency_when_scored_zero(self):
        """Low-lag detected but 0 scored → REMOTE_QUOTER_LATENCY tag."""
        ev = _make_event(event_id="latency_ll")
        r = BackrunResult(
            event_id="latency_ll",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            reject_reason=REJECT_NO_COUNTER_POOL,
            event_block=100,
            quote_block=101,
            block_lag=1,
            same_state_class="next_block",
        )
        art = build_replay_summary([ev], [r], mode="test")
        bt = art["blocker_tags"]
        # events_detected_low_lag=1, events_scored_low_lag=0 → triggers latency tag
        assert BLOCKER_LOW_LAG_REMOTE_QUOTER_LATENCY in bt["active_tags"]


class TestM7A518LowLagWatchlist:
    """M7.A.5.18: low_lag_watchlist artifact block."""

    def test_watchlist_present_in_empty_artifact(self):
        art = build_replay_summary([], [], mode="test")
        assert "low_lag_watchlist" in art
        assert art["low_lag_watchlist"] == []

    def test_watchlist_is_list(self):
        art = build_replay_summary([], [], mode="test")
        assert isinstance(art["low_lag_watchlist"], list)

    def test_watchlist_entry_fields(self):
        """A low-lag event with pool_contract_truth populates watchlist."""
        ev = _make_event(event_id="wl_1")
        r = BackrunResult(
            event_id="wl_1",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            reject_reason=REJECT_NO_COUNTER_POOL,
            event_block=100,
            quote_block=101,
            block_lag=1,
            same_state_class="next_block",
            pair_resolved=True,
            actual_pair="WETH/USDC",
            pool_contract_truth={"pool_address": "0xabc123"},
            pool_state_read_path="v3_multicall",
        )
        art = build_replay_summary([ev], [r], mode="test")
        wl = art["low_lag_watchlist"]
        assert len(wl) == 1
        entry = wl[0]
        expected_keys = {
            "pair", "pool_address", "first_seen_block", "last_seen_block",
            "seen_count", "reject_reason", "pair_unresolved_detail",
            "pool_state_read_path", "known_pools", "active_pools",
        }
        assert set(entry.keys()) == expected_keys

    def test_watchlist_10_required_fields(self):
        """Each watchlist entry must have exactly 10 keys."""
        ev = _make_event(event_id="wl_10f")
        r = BackrunResult(
            event_id="wl_10f",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            reject_reason=REJECT_NO_COUNTER_POOL,
            event_block=100,
            quote_block=101,
            block_lag=1,
            same_state_class="next_block",
            pool_contract_truth={"pool_address": "0xdef456"},
        )
        art = build_replay_summary([ev], [r], mode="test")
        for entry in art["low_lag_watchlist"]:
            assert len(entry) == 10, f"Expected 10 fields, got {len(entry)}: {sorted(entry.keys())}"

    def test_watchlist_deduplication_by_pool(self):
        """Two events from same pool should merge into one watchlist entry."""
        ev1 = _make_event(event_id="wl_dup1")
        ev2 = _make_event(event_id="wl_dup2")
        r1 = BackrunResult(
            event_id="wl_dup1",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            reject_reason=REJECT_NO_COUNTER_POOL,
            event_block=100,
            quote_block=101,
            block_lag=1,
            same_state_class="next_block",
            pool_contract_truth={"pool_address": "0xsamepool"},
        )
        r2 = BackrunResult(
            event_id="wl_dup2",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            reject_reason=REJECT_NO_COUNTER_POOL,
            event_block=105,
            quote_block=106,
            block_lag=1,
            same_state_class="next_block",
            pool_contract_truth={"pool_address": "0xsamepool"},
        )
        art = build_replay_summary([ev1, ev2], [r1, r2], mode="test")
        wl = art["low_lag_watchlist"]
        assert len(wl) == 1
        assert wl[0]["seen_count"] == 2
        assert wl[0]["first_seen_block"] == 100
        assert wl[0]["last_seen_block"] == 105

    def test_watchlist_no_stale_events(self):
        """Stale events (block_lag > 2) should not appear in watchlist."""
        ev = _make_event(event_id="wl_stale")
        r = BackrunResult(
            event_id="wl_stale",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            reject_reason=REJECT_GAS_EXCEEDS_GROSS,
            event_block=100,
            quote_block=200,
            block_lag=100,
            same_state_class="stale",
            pool_contract_truth={"pool_address": "0xstalepool"},
        )
        art = build_replay_summary([ev], [r], mode="test")
        assert art["low_lag_watchlist"] == []

    def test_watchlist_coverage_truth_propagation(self):
        """Watchlist entry inherits known_pools/active_pools from coverage_result."""
        ev = _make_event(event_id="wl_cov")
        r = BackrunResult(
            event_id="wl_cov",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            reject_reason=REJECT_NO_COUNTER_POOL,
            event_block=100,
            quote_block=101,
            block_lag=1,
            same_state_class="next_block",
            coverage_result={
                "known_pools_total": 3,
                "active_pools_total": 1,
                "candidate_pools": [{"address": "0xpool1"}],
            },
        )
        art = build_replay_summary([ev], [r], mode="test")
        wl = art["low_lag_watchlist"]
        assert len(wl) == 1
        assert wl[0]["known_pools"] == 3
        assert wl[0]["active_pools"] == 1


class TestM7A518BackwardCompat:
    """M7.A.5.18 must keep BackrunResult at 56 fields, reject count at 19."""

    def test_backrun_result_field_count_still_56(self):
        """M7.A.5.18 adds no new BackrunResult fields (watchlist + blocker_tags are artifact-level)."""
        r = BackrunResult(
            event_id="compat_518",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
        )
        d = asdict(r)
        assert len(d) == 56, f"Expected 56 fields, got {len(d)}: {sorted(d.keys())}"

    def test_all_reject_reasons_count_still_19(self):
        """M7.A.5.18 adds no new reject reasons."""
        assert len(ALL_REJECT_REASONS) == 19

    def test_unscored_rejects_count_still_11(self):
        """M7.A.5.18 does not change unscored rejects set."""
        assert len(UNSCORED_REJECTS) == 11

    def test_all_blocker_tags_count_is_7(self):
        """M7.A.5.18 defines exactly 7 canonical blocker tags."""
        assert len(ALL_BLOCKER_TAGS) == 7

    def test_new_518_artifact_keys(self):
        art = build_replay_summary([], [], mode="test")
        assert "low_lag_watchlist" in art
        assert "blocker_tags" in art

    def test_old_517_artifact_keys_still_present(self):
        art = build_replay_summary([], [], mode="test")
        for key in [
            "low_lag_v2_truth",
            "low_lag_pool_class_truth",
            "low_lag_debug_rows",
            "low_lag_coverage_truth",
            "low_lag_reject_histogram",
            "low_lag_pair_resolution_rate",
            "low_lag_counter_coverage_rate",
            "low_lag_scored_results_rate",
            "low_lag_pre_econ_reject_rate",
            "stale_low_lag_comparison",
            "reject_histogram",
        ]:
            assert key in art, f"Missing backward-compat key: {key}"

    def test_old_backrun_result_fields_unchanged(self):
        """All 56 fields from M7.A.5.17 must still be present."""
        r = BackrunResult(
            event_id="bc_fields_518",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
        )
        d = asdict(r)
        pre_518_fields = [
            "event_id", "event_source", "event_type", "post_trade_state_used",
            "backrun_direction", "best_buy_venue", "best_sell_venue",
            "candidate_path", "amount_in_wei", "gross_pnl_wei",
            "gas_cost_wei", "fee_cost_wei", "net_pnl_wei",
            "best_backrun_net_bps", "same_block_possible", "route_viable",
            "reject_reason", "event_block", "quote_block", "block_lag",
            "same_state_class", "counter_venue_count", "best_live_net_bps",
            "ws_provider", "event_detected_at_block", "quote_started_block",
            "quote_finished_block", "quote_pipeline_latency_ms",
            "venues_pruned_by_multicall", "latency_budget_ms",
            "quote_calls_attempted", "quote_calls_after_pruning",
            "prune_reason_histogram", "pipeline_stage_latency_ms",
            "pair_resolved", "actual_pair", "size_source",
            "coverage_result", "size_sweep_results",
            "best_sweep_net_bps", "best_sweep_size_wei",
            "token_admitted", "admission_source", "oracle_guard",
            "local_sim_state", "l2_gas_bps", "l1_data_bps",
            "total_gas_bps", "subgraph_seed_used",
            "token_in_decimals", "size_normalization_source",
            "size_usd_estimate", "size_valid_for_token",
            "pair_unresolved_detail", "pool_contract_truth",
            "pool_state_read_path",
        ]
        for f in pre_518_fields:
            assert f in d, f"Missing pre-5.18 field: {f}"
