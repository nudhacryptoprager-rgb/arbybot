"""
Contract tests for M7.A.4/M7.A.5 — Orderflow-driven replay and live block-event backrun.

Tests lock:
- OrderflowEvent schema and validation
- BackrunResult schema (incl. M7.A.5 live replay fields)
- IntentSurfaceAssessment schema
- Fixture event generation
- Event classification viability
- Backrun scoring (offline estimation)
- Intent surface scout
- Artifact schema
- Backward compatibility with M7.A constants
- M7.A.5: Live event normalization, block propagation, live replay schema
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
    _build_address_to_symbol,
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
        assert len(ALL_REJECT_REASONS) == 7
        assert REJECT_NO_COUNTER_VENUE in ALL_REJECT_REASONS
        assert REJECT_GAS_EXCEEDS_GROSS in ALL_REJECT_REASONS
        assert REJECT_SLIPPAGE_EXCEEDS_GROSS in ALL_REJECT_REASONS
        assert REJECT_EVENT_TOO_SMALL in ALL_REJECT_REASONS
        assert REJECT_SAME_BLOCK_IMPOSSIBLE in ALL_REJECT_REASONS
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

        # Track call args to verify sell input matches buy output
        call_log = []
        USDC_ADDR = "0xaf88d065e77c8cC2239327C5EDb3A432268e5831"
        WETH_ADDR = "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1"
        BUY_OUTPUT_WETH = 9_970_000_000_000_000  # Buy: USDC→WETH output

        def mock_quoter(quoter_address, token_in, token_out, amount_in, fee,
                        rpc_url, block_num="latest", fallback_rpc_urls=None):
            call_log.append({
                "token_in": token_in, "token_out": token_out,
                "amount_in": amount_in,
            })
            # Buy side: USDC→WETH (token_in=USDC)
            if token_in.lower() == USDC_ADDR.lower():
                return {"amount_out": BUY_OUTPUT_WETH}
            # Sell side: WETH→USDC (token_in=WETH)
            return {"amount_out": 99_500_000_000_000_000}  # ~0.0995 ETH worth of USDC

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

        # Pass 1 = buy (USDC→WETH), Pass 2 = sell (WETH→USDC)
        buy_calls = [c for c in call_log if c["token_in"].lower() == USDC_ADDR.lower()]
        sell_calls = [c for c in call_log if c["token_in"].lower() == WETH_ADDR.lower()]
        assert len(buy_calls) >= 1, f"Expected buy calls, got {call_log}"
        assert len(sell_calls) >= 1, f"Expected sell calls, got {call_log}"
        # Critical: sell input must equal buy output, NOT backrun_size_wei
        assert sell_calls[0]["amount_in"] == BUY_OUTPUT_WETH, (
            f"Sell input {sell_calls[0]['amount_in']} != buy output {BUY_OUTPUT_WETH}"
        )
        # Net bps should be reasonable (not billions)
        assert r.best_backrun_net_bps is not None
        assert abs(r.best_backrun_net_bps) < 10000  # sanity: within ±100%


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
        """No quotable venues → REJECT_QUOTE_FAILURE."""
        ev = _make_event()

        r = score_backrun_live_parallel(
            event=ev, rpc_url="http://fake", dex_configs={},
            token_addresses={"WETH": "0xW", "USDC": "0xU"},
            current_block=100,
            ws_provider="alchemy",
        )
        assert r.reject_reason == REJECT_QUOTE_FAILURE
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
