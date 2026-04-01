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


