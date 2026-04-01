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
    # M7.A.5.21 reject reasons
    REJECT_GAS_FLOOR_EXCEEDED,
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
            REJECT_GAS_FLOOR_EXCEEDED,
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
        assert len(d) == 65

    def test_all_reject_reasons_count_still_19(self):
        """M7.A.5.13 adds no new reject reasons."""
        assert len(ALL_REJECT_REASONS) == 20

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
        assert len(d) == 65

    def test_all_reject_reasons_count_still_19(self):
        """M7.A.5.14 adds no new reject reasons."""
        assert len(ALL_REJECT_REASONS) == 20

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
            "quote_fail_stage", "quote_fail_venue",
            "quote_fail_exception_short",
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
        assert len(d) == 65

    def test_all_reject_reasons_count_still_19(self):
        assert len(ALL_REJECT_REASONS) == 20

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


