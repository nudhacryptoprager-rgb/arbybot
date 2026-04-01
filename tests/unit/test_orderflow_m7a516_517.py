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
        """Low-lag debug rows now have 16 keys (was 13)."""
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
            "quote_fail_stage", "quote_fail_venue",
            "quote_fail_exception_short",
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
        assert len(d) == 66

    def test_all_reject_reasons_count_still_19(self):
        """M7.A.5.16 adds no new reject reasons."""
        assert len(ALL_REJECT_REASONS) == 20

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
        assert len(row) == 16, f"Expected 16 debug row keys, got {len(row)}: {sorted(row.keys())}"



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
        assert len(d) == 66, f"Expected 56 fields, got {len(d)}: {sorted(d.keys())}"

    def test_all_reject_reasons_count_still_19(self):
        """M7.A.5.17 adds no new reject reasons."""
        assert len(ALL_REJECT_REASONS) == 20

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


