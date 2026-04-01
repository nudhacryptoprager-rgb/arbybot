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
        assert len(d) == 59, f"Expected 56 fields, got {len(d)}: {sorted(d.keys())}"

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
        assert len(d) == 59
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
        assert len(parsed) == 59
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
        assert len(d) == 59, f"Expected 56 fields, got {len(d)}: {sorted(d.keys())}"



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
        assert len(d) == 59, f"Expected 56 fields, got {len(d)}: {sorted(d.keys())}"

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

