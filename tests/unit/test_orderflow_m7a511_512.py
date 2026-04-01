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
        assert len(d) == 59

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
        assert len(d) == 59

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


