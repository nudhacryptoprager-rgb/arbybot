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
    BLOCKER_LOW_LAG_RPC_QUOTE_FAIL,
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

class TestM7A518BlockerTagConstants:
    """M7.A.5.18: Canonical blocker tag constants are module-level and frozen."""

    def test_all_blocker_tags_count_is_8(self):
        assert len(ALL_BLOCKER_TAGS) == 8

    def test_all_blocker_tags_is_frozenset(self):
        assert isinstance(ALL_BLOCKER_TAGS, frozenset)

    def test_each_canonical_tag_in_set(self):
        expected = {
            "LOW_LAG_NONE_THIS_WINDOW",
            "LOW_LAG_NO_COUNTER_POOL",
            "LOW_LAG_V2_UNSUPPORTED",
            "LOW_LAG_INACTIVE_POOL",
            "LOW_LAG_REMOTE_QUOTER_LATENCY",
            "LOW_LAG_RPC_QUOTE_FAIL",
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
        assert BLOCKER_LOW_LAG_RPC_QUOTE_FAIL == "LOW_LAG_RPC_QUOTE_FAIL"
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
        """Low-lag detected but 0 scored → REMOTE_QUOTER_LATENCY does NOT fire (M7.R1).

        Per M7.R1: latency tag only fires for SCORED low-lag paths where
        pipeline_latency > budget.  Zero scored paths means zero over-budget.
        """
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
        # M7.R1: 0 scored → latency tag does NOT fire (only fires for scored paths over budget)
        assert BLOCKER_LOW_LAG_REMOTE_QUOTER_LATENCY not in bt["active_tags"]



class TestM7A519QuoteFailProvenance:
    """M7.A.5.19: quote_fail_stage/venue/exception_short in low-lag debug rows."""

    def test_provenance_populated_for_rpc_quote_fail(self):
        """When reject_reason is RPC_QUOTE_FAIL with provenance in pipeline_stage_latency_ms,
        debug rows should surface the three provenance fields."""
        r = BackrunResult(
            event_id="qfp_1",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            block_lag=1,
            reject_reason=REJECT_RPC_QUOTE_FAIL,
            pair_resolved=True,
            actual_pair="WETH/USDC",
            pipeline_stage_latency_ms={
                "stage_a_ms": 10.0,
                "stage_b_ms": 20.0,
                "quote_fail_stage": "buy",
                "quote_fail_venue": "uniswap_v3",
                "quote_fail_exception_short": "ContractLogicError",
            },
        )
        art = build_replay_summary([], [r], mode="ws_live")
        row = art["low_lag_debug_rows"][0]
        assert row["quote_fail_stage"] == "buy"
        assert row["quote_fail_venue"] == "uniswap_v3"
        assert row["quote_fail_exception_short"] == "ContractLogicError"

    def test_provenance_none_for_non_rpc_fail(self):
        """For non-RPC_QUOTE_FAIL rejects, provenance fields should be None."""
        r = BackrunResult(
            event_id="qfp_2",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            block_lag=0,
            reject_reason=REJECT_NO_COUNTER_POOL,
            pair_resolved=True,
            actual_pair="WETH/ARB",
        )
        art = build_replay_summary([], [r], mode="ws_live")
        row = art["low_lag_debug_rows"][0]
        assert row["quote_fail_stage"] is None
        assert row["quote_fail_venue"] is None
        assert row["quote_fail_exception_short"] is None

    def test_provenance_none_when_no_pipeline_latency(self):
        """RPC_QUOTE_FAIL with no pipeline_stage_latency_ms still has None provenance."""
        r = BackrunResult(
            event_id="qfp_3",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
            block_lag=2,
            reject_reason=REJECT_RPC_QUOTE_FAIL,
            pair_resolved=True,
            actual_pair="WETH/USDT",
        )
        art = build_replay_summary([], [r], mode="ws_live")
        row = art["low_lag_debug_rows"][0]
        assert row["quote_fail_stage"] is None
        assert row["quote_fail_venue"] is None
        assert row["quote_fail_exception_short"] is None



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
    """M7.A.5.18 must keep BackrunResult at 59 fields (56 + 3 M7.A.5.20), reject count at 19."""

    def test_backrun_result_field_count_still_59(self):
        """M7.A.5.20 adds 3 local_pricing fields → 59 total."""
        r = BackrunResult(
            event_id="compat_518",
            event_source="live",
            event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live",
            backrun_direction=BACKRUN_BUY_DEPRESSED,
        )
        d = asdict(r)
        assert len(d) == 59, f"Expected 59 fields, got {len(d)}: {sorted(d.keys())}"

    def test_all_reject_reasons_count_still_19(self):
        """M7.A.5.18 adds no new reject reasons."""
        assert len(ALL_REJECT_REASONS) == 19

    def test_unscored_rejects_count_still_11(self):
        """M7.A.5.18 does not change unscored rejects set."""
        assert len(UNSCORED_REJECTS) == 11

    def test_all_blocker_tags_count_is_8(self):
        """M7.R1 defines exactly 8 canonical blocker tags (was 7 in M7.A.5.18)."""
        assert len(ALL_BLOCKER_TAGS) == 8

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
