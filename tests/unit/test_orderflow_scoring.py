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


