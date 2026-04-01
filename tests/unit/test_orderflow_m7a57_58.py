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
        assert len(parsed) == 59
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
        assert len(parsed) == 59
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


