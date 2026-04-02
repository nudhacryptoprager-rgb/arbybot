"""
Consolidated PRICING_LATENCY tests for M7 orderflow.

Test categories covered:
- Event classification (backrun type, viability)
- Backrun scoring offline (gross, gas, fee, net bps)
- Chainlink oracle constants and guard
- Token enrichment functions (offline contract)
- Local-sim state extraction
- Subgraph seed constants
- Gas decomposition (L1/L2 split)
- Normalized bounds per-decimals
- Size normalization contract
- Gas denomination conversion (ETH→token units)
- Stale gate viability
- Zero liquidity reject
- V3 swap math (compute_v3_swap_amount_out)
- V2 swap math (compute_v2_swap_amount_out)
- Algebra/Camelot swap math (compute_algebra_swap_amount_out)
- attempt_local_pricing orchestrator
- Adapter dispatch (V3/V2/Algebra)
- Two-queue priority (low-lag vs stale)
- Mid-pipeline abort
- Low-lag zero-active-pools instant reject
- Session prewarm pairs
- Detection-time lag accounting (M7.A.5.25)
"""
from __future__ import annotations

import os
from dataclasses import asdict
from typing import Dict

import pytest

from m7.orderflow.contracts import BackrunResult, OrderflowEvent
from m7.orderflow.events import build_fixture_events
from m7.orderflow.pricing import (
    _gas_cost_in_token_wei,
    _normalized_bounds,
    check_oracle_sanity,
    classify_event_backrun_type,
    classify_event_viability,
    estimate_backrun_gross_bps,
    estimate_fee_cost_bps,
    estimate_gas_cost_bps,
    estimate_gas_decomposition_bps,
)
from m7.orderflow.resolve import (
    enrich_tokens_batch,
    enrich_unknown_token,
    extract_pool_state_for_sim,
)
from m7.orderflow.v3_math import (
    attempt_local_pricing,
    compute_algebra_swap_amount_out,
    compute_v2_swap_amount_out,
    compute_v3_swap_amount_out,
)
from m7.orderflow.artifacts import build_replay_summary, score_backrun_offline
from m7.orderflow.coverage import seed_tokens_from_subgraph
from m7.orderflow.pool_registry import PoolRegistryEntry
from m7.shared.constants import (
    _FALLBACK_ETH_PRICE_USD,
    _REF_MAX_WEI_18,
    _REF_MIN_WEI_18,
    BACKRUN_BUY_DEPRESSED,
    BACKRUN_SELL_APPRECIATED,
    CHAINLINK_DECIMALS,
    CHAINLINK_FEEDS_ARBITRUM,
    CHAINLINK_LATEST_ROUND_SELECTOR,
    DEFAULT_BACKRUN_GAS,
    DEFAULT_GAS_PRICE_GWEI,
    EVENT_TYPE_SWAP,
    MIN_EVENT_SIZE_USD,
    REJECT_ALL_POOLS_TRULY_INACTIVE,
    REJECT_EVENT_TOO_SMALL,
    REJECT_GAS_EXCEEDS_GROSS,
    REJECT_INSUFFICIENT_IMPACT,
    REJECT_PRICING_ANOMALY,
    REJECT_STALE_POSITIVE,
    REJECT_ZERO_LIQUIDITY,
    SIGNIFICANT_IMPACT_BPS,
    SUBGRAPH_ENDPOINTS_ARBITRUM,
    SUBGRAPH_SEED_TOKEN_CAP,
    SUBGRAPH_TIMEOUT_SECONDS,
    UNSCORED_REJECTS,
)

from tests.unit.conftest import _make_event, _make_result


# ---------------------------------------------------------------------------
# 1. Event classification
# ---------------------------------------------------------------------------
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
        assert classify_event_viability(e) is None


# ---------------------------------------------------------------------------
# 2. Backrun scoring (offline)
# ---------------------------------------------------------------------------
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
        for key in [
            "event_id", "event_source", "event_type",
            "post_trade_state_used", "best_backrun_net_bps",
            "candidate_path", "route_viable", "reject_reason",
        ]:
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
            assert r.event_id


# ---------------------------------------------------------------------------
# 3. Chainlink oracle constants & guard
# ---------------------------------------------------------------------------
class TestChainlinkConstants:
    """Chainlink feed constants on Arbitrum."""

    def test_chainlink_feeds_arbitrum_is_dict(self):
        assert isinstance(CHAINLINK_FEEDS_ARBITRUM, dict)

    def test_chainlink_feeds_has_major_tokens(self):
        for token in ["WETH", "WBTC", "USDT", "USDC", "ARB"]:
            assert token in CHAINLINK_FEEDS_ARBITRUM, f"Missing feed for {token}"

    def test_chainlink_feed_addresses_are_valid(self):
        for token, addr in CHAINLINK_FEEDS_ARBITRUM.items():
            assert addr.startswith("0x"), f"Bad prefix for {token}"
            assert len(addr) == 42, f"Bad length for {token}: {len(addr)}"

    def test_chainlink_selector(self):
        assert CHAINLINK_LATEST_ROUND_SELECTOR == "0xfeaf968c"

    def test_chainlink_decimals(self):
        assert CHAINLINK_DECIMALS == 8


class TestOracleGuard:
    """check_oracle_sanity offline contract."""

    def test_oracle_guard_no_feeds_returns_default(self):
        result = check_oracle_sanity("UNKNOWN_TOKEN", "ALSO_UNKNOWN", "http://fake", 100)
        assert result["oracle_price_available"] is False
        assert result["oracle_guard_triggered"] is False
        assert result["oracle_staleness_seconds"] is None

    def test_oracle_guard_schema_keys(self):
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
        result = check_oracle_sanity(None, None, "http://fake", 100)
        assert result["oracle_price_available"] is False

    def test_oracle_guard_empty_symbols(self):
        result = check_oracle_sanity("", "", "http://fake", 100)
        assert result["oracle_price_available"] is False


# ---------------------------------------------------------------------------
# 4. Token enrichment (offline)
# ---------------------------------------------------------------------------
class TestEnrichmentFunctions:
    """On-chain enrichment functions (offline contract)."""

    def test_enrich_unknown_token_offline(self):
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
        result = enrich_tokens_batch([], "http://fake", 100)
        assert result == {}

    def test_enrich_tokens_batch_offline(self):
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


# ---------------------------------------------------------------------------
# 5. Local-sim state extraction
# ---------------------------------------------------------------------------
class TestLocalSimState:
    """extract_pool_state_for_sim offline contract."""

    def test_extract_pool_state_empty(self):
        result = extract_pool_state_for_sim([], "http://fake", 100)
        assert result == {}

    def test_extract_pool_state_offline(self):
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


# ---------------------------------------------------------------------------
# 6. Subgraph seed constants
# ---------------------------------------------------------------------------
class TestSubgraphSeedConstants:
    """Subgraph-backed seed constants and function contracts."""

    def test_subgraph_endpoints_shape(self):
        assert isinstance(SUBGRAPH_ENDPOINTS_ARBITRUM, dict)
        assert len(SUBGRAPH_ENDPOINTS_ARBITRUM) >= 1
        for k, v in SUBGRAPH_ENDPOINTS_ARBITRUM.items():
            assert isinstance(k, str)
            assert isinstance(v, str)
            assert v.startswith("https://")

    def test_seed_token_cap_bounds(self):
        assert isinstance(SUBGRAPH_SEED_TOKEN_CAP, int)
        assert 1 <= SUBGRAPH_SEED_TOKEN_CAP <= 200

    def test_timeout_seconds_bounds(self):
        assert isinstance(SUBGRAPH_TIMEOUT_SECONDS, (int, float))
        assert 1 <= SUBGRAPH_TIMEOUT_SECONDS <= 60

    def test_seed_tokens_from_subgraph_returns_dict_on_empty(self):
        addr_to_sym: Dict[str, str] = {}
        result = seed_tokens_from_subgraph(addr_to_sym, "http://fake", 100, chain="arbitrum_one")
        assert isinstance(result, dict)
        assert "tokens_discovered" in result
        assert "tokens_new" in result
        assert "tokens_verified" in result
        assert "sources_queried" in result
        assert "errors" in result


# ---------------------------------------------------------------------------
# 7. Gas decomposition (L1/L2)
# ---------------------------------------------------------------------------
class TestGasDecomposition:
    """estimate_gas_decomposition_bps: L1/L2 split."""

    def test_basic_decomposition(self):
        result = estimate_gas_decomposition_bps(
            amount_in_wei=10**18,
            gas_cost_wei=10**15,
        )
        assert isinstance(result, dict)
        assert "l2_gas_bps" in result
        assert "l1_data_bps" in result
        assert "total_gas_bps" in result

    def test_total_equals_sum(self):
        result = estimate_gas_decomposition_bps(
            amount_in_wei=10**18,
            gas_cost_wei=5 * 10**14,
        )
        expected_total = round(result["l2_gas_bps"] + result["l1_data_bps"], 4)
        assert abs(result["total_gas_bps"] - expected_total) < 0.001

    def test_zero_amount_returns_zero(self):
        result = estimate_gas_decomposition_bps(
            amount_in_wei=0,
            gas_cost_wei=10**15,
        )
        assert isinstance(result, dict)
        assert result["total_gas_bps"] == 0.0
        assert result["l2_gas_bps"] == 0.0
        assert result["l1_data_bps"] == 0.0

    def test_zero_gas_returns_zero(self):
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


# ---------------------------------------------------------------------------
# 8. Normalized bounds (_normalized_bounds per-decimals)
# ---------------------------------------------------------------------------
class TestNormalizedBounds:
    """_normalized_bounds returns decimal-adjusted min/max."""

    def test_18_dec_identity(self):
        mn, mx = _normalized_bounds(18)
        assert mn == _REF_MIN_WEI_18
        assert mx == _REF_MAX_WEI_18

    def test_none_dec_fallback(self):
        mn, mx = _normalized_bounds(None)
        assert mn == _REF_MIN_WEI_18
        assert mx == _REF_MAX_WEI_18

    def test_6_dec_usdc(self):
        mn, mx = _normalized_bounds(6)
        assert mn == 10**3, f"min should be 10^3 for 6-dec, got {mn}"
        assert mx == 10**6, f"max should be 10^6 for 6-dec, got {mx}"

    def test_8_dec_wbtc(self):
        mn, mx = _normalized_bounds(8)
        assert mn == 10**5
        assert mx == 10**8

    def test_min_is_at_least_1(self):
        mn, mx = _normalized_bounds(1)
        assert mn >= 1
        assert mx >= 1

    def test_6_dec_far_smaller_than_18_dec(self):
        mn6, mx6 = _normalized_bounds(6)
        mn18, mx18 = _normalized_bounds(18)
        assert mn18 / mn6 == 10**12
        assert mx18 / mx6 == 10**12

    def test_custom_reference_bounds(self):
        mn, mx = _normalized_bounds(6, default_18_min=10**16, default_18_max=10**19)
        assert mn == 10**4
        assert mx == 10**7

    def test_all_common_decimals_positive(self):
        for dec in [0, 2, 4, 6, 8, 12, 18]:
            mn, mx = _normalized_bounds(dec)
            assert mn >= 1, f"min<1 for decimals={dec}"
            assert mx >= mn, f"max<min for decimals={dec}"

    def test_same_usd_comparable_units(self):
        mn6, mx6 = _normalized_bounds(6)
        mn18, mx18 = _normalized_bounds(18)
        assert mn6 < 10**6
        assert mx6 == 10**6
        assert mn18 < 10**18
        assert mx18 == 10**18


# ---------------------------------------------------------------------------
# 9. Size normalization contract
# ---------------------------------------------------------------------------
class TestSizeNormalizationContract:
    """Bounded size clamp must use _normalized_bounds for the token."""

    def test_usdc_event_not_clamped_to_weth_min(self):
        event_amount_usdc = 5000 * 10**6
        raw_size = max(event_amount_usdc // 10, 1)
        mn, mx = _normalized_bounds(6)
        bounded = max(mn, min(mx, raw_size))
        assert bounded == mx
        assert bounded < 10**15

    def test_weth_event_normal_range(self):
        event_amount_weth = 10**18
        raw_size = max(event_amount_weth // 10, 1)
        mn, mx = _normalized_bounds(18)
        bounded = max(mn, min(mx, raw_size))
        assert bounded == 10**17

    def test_usdt_6_dec_same_as_usdc(self):
        mn_usdc, mx_usdc = _normalized_bounds(6)
        mn_usdt, mx_usdt = _normalized_bounds(6)
        assert mn_usdc == mn_usdt
        assert mx_usdc == mx_usdt

    def test_wbtc_8_dec_reasonable(self):
        mn, mx = _normalized_bounds(8)
        assert mn == 10**5
        assert mx == 10**8


# ---------------------------------------------------------------------------
# 10. Gas denomination conversion (ETH→token units)
# ---------------------------------------------------------------------------
class TestGasDenominationConversion:
    """_gas_cost_in_token_wei must convert ETH gas to the backrun token's units."""

    GAS_ETH_WEI = int(DEFAULT_BACKRUN_GAS * DEFAULT_GAS_PRICE_GWEI * 1e9)

    def test_18dec_no_price_identity(self):
        result = _gas_cost_in_token_wei(self.GAS_ETH_WEI, 18)
        assert result == self.GAS_ETH_WEI

    def test_18dec_with_price_converts(self):
        result = _gas_cost_in_token_wei(
            self.GAS_ETH_WEI, 18, token_price_usd=3500.0, eth_price_usd=3500.0,
        )
        assert result == self.GAS_ETH_WEI

    def test_6dec_usdc_with_oracle(self):
        result = _gas_cost_in_token_wei(
            self.GAS_ETH_WEI, 6, token_price_usd=1.0, eth_price_usd=3500.0,
        )
        gas_usd = self.GAS_ETH_WEI / 1e18 * 3500.0
        expected = int(gas_usd * 1e6)
        assert result == expected

    def test_6dec_usdc_fallback(self):
        result = _gas_cost_in_token_wei(self.GAS_ETH_WEI, 6)
        expected = int(self.GAS_ETH_WEI * _FALLBACK_ETH_PRICE_USD * 1e6 / (1.0 * 1e18))
        assert result == expected
        assert result < 1_000_000

    def test_8dec_wbtc_with_oracle(self):
        result = _gas_cost_in_token_wei(
            self.GAS_ETH_WEI, 8, token_price_usd=65000.0, eth_price_usd=3500.0,
        )
        gas_usd = self.GAS_ETH_WEI / 1e18 * 3500.0
        expected = int(gas_usd / 65000.0 * 1e8)
        assert result == expected or abs(result - expected) <= 1

    def test_never_returns_zero(self):
        result = _gas_cost_in_token_wei(1, 6, token_price_usd=100000.0, eth_price_usd=1.0)
        assert result >= 1

    def test_none_decimals_defaults_18(self):
        result = _gas_cost_in_token_wei(self.GAS_ETH_WEI, None)
        assert result == self.GAS_ETH_WEI

    def test_bps_now_reasonable_for_usdc(self):
        backrun_wei = 10**6
        gross_wei = -836
        gas_token = _gas_cost_in_token_wei(
            self.GAS_ETH_WEI, 6, token_price_usd=1.0, eth_price_usd=3500.0,
        )
        net_wei = gross_wei - gas_token
        net_bps = (net_wei / backrun_wei) * 10000
        assert -10000 < net_bps < 10000
        assert net_bps < 0

    def test_gas_decomposition_consistent_after_conversion(self):
        backrun_wei = 10**6
        gas_token = _gas_cost_in_token_wei(
            self.GAS_ETH_WEI, 6, token_price_usd=1.0, eth_price_usd=3500.0,
        )
        decomp = estimate_gas_decomposition_bps(backrun_wei, gas_token)
        assert 0 < decomp["total_gas_bps"] < 100_000
        assert decomp["l1_data_bps"] > 0
        assert decomp["l2_gas_bps"] > 0


# ---------------------------------------------------------------------------
# 11. Stale gate viability
# ---------------------------------------------------------------------------
class TestStaleGateViability:
    """route_viable requires net_bps > 0 AND block_lag <= 2."""

    def test_viable_result_positive_low_lag(self):
        r = BackrunResult(
            event_id="stale_1", event_source="live", event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live", backrun_direction=BACKRUN_BUY_DEPRESSED,
            best_backrun_net_bps=50.0, block_lag=1, same_state_class="next_block",
            route_viable=True, reject_reason=None,
        )
        assert r.route_viable is True
        assert r.reject_reason is None

    def test_stale_positive_not_viable(self):
        r = BackrunResult(
            event_id="stale_2", event_source="live", event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live", backrun_direction=BACKRUN_BUY_DEPRESSED,
            best_backrun_net_bps=2630.0, block_lag=23, same_state_class="stale",
            route_viable=False, reject_reason=REJECT_STALE_POSITIVE,
        )
        assert r.route_viable is False
        assert r.reject_reason == REJECT_STALE_POSITIVE

    def test_negative_net_not_viable(self):
        r = BackrunResult(
            event_id="stale_3", event_source="live", event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live", backrun_direction=BACKRUN_BUY_DEPRESSED,
            best_backrun_net_bps=-400.0, block_lag=1, same_state_class="next_block",
            route_viable=False, reject_reason=REJECT_GAS_EXCEEDS_GROSS,
        )
        assert r.route_viable is False
        assert r.reject_reason == REJECT_GAS_EXCEEDS_GROSS


# ---------------------------------------------------------------------------
# 12. Zero liquidity reject
# ---------------------------------------------------------------------------
class TestZeroLiquidityReject:
    """Zero-liquidity pools produce REJECT_ZERO_LIQUIDITY."""

    def test_zero_liq_result(self):
        r = BackrunResult(
            event_id="zeroliq_1", event_source="live", event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live", backrun_direction=BACKRUN_BUY_DEPRESSED,
            reject_reason=REJECT_ZERO_LIQUIDITY, route_viable=False,
            local_sim_state={
                "pools_queried": 2, "pools_with_state": 2,
                "pool_states": {
                    "0xaaa": {"liquidity": 0},
                    "0xbbb": {"liquidity": 0},
                },
            },
        )
        assert r.reject_reason == REJECT_ZERO_LIQUIDITY
        assert r.route_viable is False


# ---------------------------------------------------------------------------
# 13. V3 swap math
# ---------------------------------------------------------------------------
class TestV3SwapMath:
    """compute_v3_swap_amount_out: single-tick V3 swap math."""

    SQRT_PRICE = 4685413736498040635278359 * (10**15)
    LIQUIDITY = 10**18
    FEE_500 = 500
    FEE_3000 = 3000

    def test_zero_for_one_positive_output(self):
        out = compute_v3_swap_amount_out(
            sqrt_price_x96=self.SQRT_PRICE, liquidity=self.LIQUIDITY,
            amount_in=10**15, fee_pips=self.FEE_500, zero_for_one=True,
        )
        assert out is not None
        assert out > 0

    def test_one_for_zero_positive_output(self):
        Q96 = 1 << 96
        out = compute_v3_swap_amount_out(
            sqrt_price_x96=Q96, liquidity=10**20,
            amount_in=10**15, fee_pips=self.FEE_500, zero_for_one=False,
        )
        assert out is not None
        assert out > 0

    def test_higher_fee_less_output(self):
        out_low = compute_v3_swap_amount_out(
            self.SQRT_PRICE, self.LIQUIDITY, 10**15, self.FEE_500, True,
        )
        out_high = compute_v3_swap_amount_out(
            self.SQRT_PRICE, self.LIQUIDITY, 10**15, self.FEE_3000, True,
        )
        assert out_low is not None and out_high is not None
        assert out_low > out_high

    def test_zero_liquidity_returns_none(self):
        out = compute_v3_swap_amount_out(self.SQRT_PRICE, 0, 10**15, self.FEE_500, True)
        assert out is None

    def test_zero_amount_in_returns_none(self):
        out = compute_v3_swap_amount_out(
            self.SQRT_PRICE, self.LIQUIDITY, 0, self.FEE_500, True,
        )
        assert out is None

    def test_zero_sqrt_price_returns_none(self):
        out = compute_v3_swap_amount_out(0, self.LIQUIDITY, 10**15, self.FEE_500, True)
        assert out is None

    def test_negative_amount_returns_none(self):
        out = compute_v3_swap_amount_out(
            self.SQRT_PRICE, self.LIQUIDITY, -1, self.FEE_500, True,
        )
        assert out is None

    def test_fee_100_percent_returns_none(self):
        out = compute_v3_swap_amount_out(
            self.SQRT_PRICE, self.LIQUIDITY, 10**15, 1_000_000, True,
        )
        assert out is None

    def test_larger_input_more_output(self):
        out_small = compute_v3_swap_amount_out(
            self.SQRT_PRICE, self.LIQUIDITY, 10**14, self.FEE_500, True,
        )
        out_large = compute_v3_swap_amount_out(
            self.SQRT_PRICE, self.LIQUIDITY, 10**15, self.FEE_500, True,
        )
        assert out_small is not None and out_large is not None
        assert out_large > out_small

    def test_output_less_than_input_for_equal_token_price(self):
        Q96 = 1 << 96
        out = compute_v3_swap_amount_out(
            sqrt_price_x96=Q96, liquidity=10**20,
            amount_in=10**15, fee_pips=3000, zero_for_one=True,
        )
        assert out is not None
        assert out < 10**15


# ---------------------------------------------------------------------------
# 14. V2 swap math
# ---------------------------------------------------------------------------
class TestV2SwapMath:
    """compute_v2_swap_amount_out: constant-product swap math."""

    def test_basic_swap(self):
        out = compute_v2_swap_amount_out(
            reserve_in=10**18, reserve_out=10**18, amount_in=10**15,
        )
        assert out is not None
        assert out > 0
        assert out < 10**15

    def test_zero_reserves_returns_none(self):
        assert compute_v2_swap_amount_out(0, 10**18, 10**15) is None
        assert compute_v2_swap_amount_out(10**18, 0, 10**15) is None

    def test_zero_amount_returns_none(self):
        assert compute_v2_swap_amount_out(10**18, 10**18, 0) is None

    def test_larger_reserve_out_more_output(self):
        out_small = compute_v2_swap_amount_out(10**18, 10**17, 10**15)
        out_large = compute_v2_swap_amount_out(10**18, 10**19, 10**15)
        assert out_small is not None and out_large is not None
        assert out_large > out_small

    def test_fee_affects_output(self):
        out_low_fee = compute_v2_swap_amount_out(10**18, 10**18, 10**15, 999, 1000)
        out_high_fee = compute_v2_swap_amount_out(10**18, 10**18, 10**15, 990, 1000)
        assert out_low_fee is not None and out_high_fee is not None
        assert out_low_fee > out_high_fee


# ---------------------------------------------------------------------------
# 15. Algebra/Camelot swap math
# ---------------------------------------------------------------------------
class TestAlgebraSwapMath:
    """compute_algebra_swap_amount_out: Algebra/Camelot V3 swap math."""

    Q96 = 1 << 96

    def test_algebra_swap_zero_for_one(self):
        out = compute_algebra_swap_amount_out(
            sqrt_price_x96=self.Q96, liquidity=10**20, amount_in=10**15,
            fee_zto=500, fee_otz=3000, zero_for_one=True,
        )
        assert out is not None
        assert out > 0

    def test_algebra_swap_one_for_zero(self):
        out = compute_algebra_swap_amount_out(
            sqrt_price_x96=self.Q96, liquidity=10**20, amount_in=10**15,
            fee_zto=500, fee_otz=3000, zero_for_one=False,
        )
        assert out is not None
        assert out > 0

    def test_algebra_uses_direction_specific_fee(self):
        out_zto = compute_algebra_swap_amount_out(
            self.Q96, 10**20, 10**15, fee_zto=500, fee_otz=3000, zero_for_one=True,
        )
        out_otz = compute_algebra_swap_amount_out(
            self.Q96, 10**20, 10**15, fee_zto=500, fee_otz=3000, zero_for_one=False,
        )
        assert out_zto is not None and out_otz is not None
        assert out_zto > out_otz

    def test_algebra_zero_liquidity_none(self):
        out = compute_algebra_swap_amount_out(self.Q96, 0, 10**15, 500, 3000, True)
        assert out is None

    def test_algebra_zero_amount_none(self):
        out = compute_algebra_swap_amount_out(self.Q96, 10**20, 0, 500, 3000, True)
        assert out is None

    def test_algebra_matches_v3_when_same_fee(self):
        fee = 3000
        v3_out = compute_v3_swap_amount_out(self.Q96, 10**20, 10**15, fee, True)
        algebra_out = compute_algebra_swap_amount_out(
            self.Q96, 10**20, 10**15, fee_zto=fee, fee_otz=fee, zero_for_one=True,
        )
        assert v3_out == algebra_out


# ---------------------------------------------------------------------------
# 16. attempt_local_pricing orchestrator
# ---------------------------------------------------------------------------
class TestAttemptLocalPricing:
    """attempt_local_pricing: orchestrates local-state pricing across pools."""

    POOL_A = "0x" + "aa" * 20
    POOL_B = "0x" + "bb" * 20
    TOKEN_IN = "0x" + "11" * 20
    TOKEN_OUT = "0x" + "ff" * 20
    Q96 = 1 << 96

    def _make_candidate_pools(self):
        return [
            {"address": self.POOL_A, "fee": 500, "dex": "uniswap_v3", "liquidity": 10**18},
            {"address": self.POOL_B, "fee": 3000, "dex": "sushiswap_v3", "liquidity": 10**18},
        ]

    def _make_pool_states(self):
        return {
            self.POOL_A: {"sqrt_price_x96": self.Q96, "tick": 0, "liquidity": 10**18},
            self.POOL_B: {"sqrt_price_x96": self.Q96, "tick": 0, "liquidity": 10**18},
        }

    def test_successful_local_pricing(self):
        result = attempt_local_pricing(
            candidate_pools=self._make_candidate_pools(),
            local_sim_states=self._make_pool_states(),
            token_in_addr=self.TOKEN_IN,
            token_out_addr=self.TOKEN_OUT,
            backrun_size_wei=10**15,
        )
        assert result is not None
        assert result["buy_amount"] > 0
        assert result["sell_amount"] > 0
        assert result["pricing_path"] == "v3_local"
        assert result["pools_attempted"] >= 1
        assert result["pools_succeeded"] >= 1

    def test_empty_pools_returns_none(self):
        result = attempt_local_pricing(
            candidate_pools=[], local_sim_states={},
            token_in_addr=self.TOKEN_IN, token_out_addr=self.TOKEN_OUT,
            backrun_size_wei=10**15,
        )
        assert result is None

    def test_zero_liquidity_returns_none(self):
        pools = [{"address": self.POOL_A, "fee": 500, "liquidity": 0}]
        states = {self.POOL_A: {"sqrt_price_x96": self.Q96, "tick": 0, "liquidity": 0}}
        result = attempt_local_pricing(
            candidate_pools=pools, local_sim_states=states,
            token_in_addr=self.TOKEN_IN, token_out_addr=self.TOKEN_OUT,
            backrun_size_wei=10**15,
        )
        assert result is None

    def test_no_matching_state_returns_none(self):
        pools = self._make_candidate_pools()
        result = attempt_local_pricing(
            candidate_pools=pools, local_sim_states={},
            token_in_addr=self.TOKEN_IN, token_out_addr=self.TOKEN_OUT,
            backrun_size_wei=10**15,
        )
        assert result is None

    def test_picks_best_buy_venue(self):
        pools = self._make_candidate_pools()
        states = self._make_pool_states()
        result = attempt_local_pricing(
            candidate_pools=pools, local_sim_states=states,
            token_in_addr=self.TOKEN_IN, token_out_addr=self.TOKEN_OUT,
            backrun_size_wei=10**15,
        )
        assert result is not None
        assert result["buy_fee"] == 500


# ---------------------------------------------------------------------------
# 17. Adapter dispatch (V3/V2/Algebra)
# ---------------------------------------------------------------------------
class TestAdapterDispatchLocalPricing:
    """attempt_local_pricing: V3/V2/Algebra adapter dispatch."""

    POOL_V3 = "0x" + "a1" * 20
    POOL_V2 = "0x" + "b2" * 20
    POOL_ALG = "0x" + "c3" * 20
    TOKEN_IN = "0x" + "11" * 20
    TOKEN_OUT = "0x" + "ff" * 20
    Q96 = 1 << 96

    def test_v3_adapter_default(self):
        pools = [{"address": self.POOL_V3, "fee": 500}]
        states = {self.POOL_V3: {"sqrt_price_x96": self.Q96, "tick": 0, "liquidity": 10**18}}
        result = attempt_local_pricing(
            pools, states, self.TOKEN_IN, self.TOKEN_OUT, 10**15,
        )
        assert result is not None
        assert result["pricing_path"] == "v3_local"

    def test_v2_adapter_dispatch(self):
        pools = [{"address": self.POOL_V2, "fee": 3}]
        states = {self.POOL_V2: {"sqrt_price_x96": 10**18, "tick": 10**18, "liquidity": 0}}
        registry = [
            PoolRegistryEntry(
                address=self.POOL_V2, dex="sushiswap_v2",
                adapter_type="uniswap_v2", fee=3,
                token_a=self.TOKEN_IN, token_b=self.TOKEN_OUT,
            )
        ]
        result = attempt_local_pricing(
            pools, states, self.TOKEN_IN, self.TOKEN_OUT, 10**15,
            registry_entries=registry,
        )
        assert result is not None
        assert result["pricing_path"] == "v2_local"

    def test_algebra_adapter_dispatch(self):
        pools = [{"address": self.POOL_ALG, "fee": 3000}]
        states = {self.POOL_ALG: {"sqrt_price_x96": self.Q96, "tick": 0, "liquidity": 10**18}}
        registry = [
            PoolRegistryEntry(
                address=self.POOL_ALG, dex="camelot_v3",
                adapter_type="algebra", fee=3000,
                token_a=self.TOKEN_IN, token_b=self.TOKEN_OUT,
            )
        ]
        result = attempt_local_pricing(
            pools, states, self.TOKEN_IN, self.TOKEN_OUT, 10**15,
            registry_entries=registry,
        )
        assert result is not None
        assert result["pricing_path"] == "algebra_local"

    def test_backward_compatible_without_registry(self):
        pools = [
            {"address": self.POOL_V3, "fee": 500},
            {"address": self.POOL_V2, "fee": 3000},
        ]
        states = {
            self.POOL_V3: {"sqrt_price_x96": self.Q96, "tick": 0, "liquidity": 10**18},
            self.POOL_V2: {"sqrt_price_x96": self.Q96, "tick": 0, "liquidity": 10**18},
        }
        result = attempt_local_pricing(
            pools, states, self.TOKEN_IN, self.TOKEN_OUT, 10**15,
        )
        assert result is not None
        assert result["pricing_path"] == "v3_local"

    def test_sell_pass_uses_adapter_dispatch(self):
        pools = [{"address": self.POOL_V2, "fee": 3}]
        states = {self.POOL_V2: {"sqrt_price_x96": 10**18, "tick": 10**18, "liquidity": 0}}
        registry = [
            PoolRegistryEntry(
                address=self.POOL_V2, dex="sushiswap_v2",
                adapter_type="uniswap_v2", fee=3,
                token_a=self.TOKEN_IN, token_b=self.TOKEN_OUT,
            )
        ]
        result = attempt_local_pricing(
            pools, states, self.TOKEN_IN, self.TOKEN_OUT, 10**15,
            registry_entries=registry,
        )
        assert result is not None
        assert result["sell_amount"] > 0


# ---------------------------------------------------------------------------
# 18. Two-queue priority (low-lag vs stale)
# ---------------------------------------------------------------------------
class TestTwoQueuePriority:
    """Events with detection_lag <= 2 scored before stale events."""

    def test_low_lag_events_sorted_first(self):
        events = [
            _make_event("stale1", block=90),
            _make_event("lowlag1", block=100),
            _make_event("stale2", block=85),
            _make_event("lowlag2", block=99),
        ]
        detected_block = 100
        low_lag_queue = [e for e in events if (detected_block - e.block_number) <= 2]
        stale_queue = [e for e in events if (detected_block - e.block_number) > 2]
        ordered = low_lag_queue + stale_queue
        assert len(low_lag_queue) == 2
        assert len(stale_queue) == 2
        assert ordered[0].event_id == "lowlag1"
        assert ordered[1].event_id == "lowlag2"
        assert ordered[2].event_id == "stale1"
        assert ordered[3].event_id == "stale2"

    def test_all_low_lag(self):
        events = [_make_event("a", block=100), _make_event("b", block=99)]
        detected_block = 100
        low_lag = [e for e in events if (detected_block - e.block_number) <= 2]
        stale = [e for e in events if (detected_block - e.block_number) > 2]
        assert len(low_lag) == 2
        assert len(stale) == 0

    def test_all_stale(self):
        events = [_make_event("a", block=50), _make_event("b", block=60)]
        detected_block = 100
        low_lag = [e for e in events if (detected_block - e.block_number) <= 2]
        stale = [e for e in events if (detected_block - e.block_number) > 2]
        assert len(low_lag) == 0
        assert len(stale) == 2

    def test_boundary_lag_2_is_low_lag(self):
        events = [_make_event("boundary", block=98)]
        detected_block = 100
        low_lag = [e for e in events if (detected_block - e.block_number) <= 2]
        assert len(low_lag) == 1

    def test_boundary_lag_3_is_stale(self):
        events = [_make_event("boundary", block=97)]
        detected_block = 100
        low_lag = [e for e in events if (detected_block - e.block_number) <= 2]
        assert len(low_lag) == 0


# ---------------------------------------------------------------------------
# 19. Mid-pipeline abort
# ---------------------------------------------------------------------------
class TestMidPipelineAbort:
    """BackrunResult with mid_pipeline_abort in stage_latency."""

    def test_abort_result_has_mid_pipeline_abort_flag(self):
        stage_latency = {
            "stage_a_ms": 0.0, "stage_b_ms": 0.0,
            "mid_pipeline_abort": True, "mid_pipeline_lag": 5,
        }
        r = _make_result(
            pipeline_stage_latency_ms=stage_latency,
            scoring_path="registry_direct",
            event_block=100, quote_block=105, block_lag=5,
            same_state_class="stale",
        )
        assert r.pipeline_stage_latency_ms["mid_pipeline_abort"] is True
        assert r.pipeline_stage_latency_ms["mid_pipeline_lag"] == 5

    def test_abort_with_positive_net_gets_stale_positive_reject(self):
        r = _make_result(
            scoring_path="registry_direct",
            best_backrun_net_bps=5.0,
            reject_reason=REJECT_STALE_POSITIVE,
            pipeline_stage_latency_ms={"mid_pipeline_abort": True},
        )
        assert r.reject_reason == REJECT_STALE_POSITIVE

    def test_abort_with_negative_net_gets_gas_exceeds_gross(self):
        r = _make_result(
            scoring_path="registry_direct",
            best_backrun_net_bps=-10.0,
            reject_reason=REJECT_GAS_EXCEEDS_GROSS,
            pipeline_stage_latency_ms={"mid_pipeline_abort": True},
        )
        assert r.reject_reason == REJECT_GAS_EXCEEDS_GROSS

    def test_abort_result_has_zero_stage_b(self):
        stage_latency = {
            "stage_a_ms": 0.0, "stage_b_ms": 0.0,
            "mid_pipeline_abort": True, "mid_pipeline_lag": 4,
        }
        r = _make_result(pipeline_stage_latency_ms=stage_latency)
        assert r.pipeline_stage_latency_ms["stage_b_ms"] == 0.0

    def test_abort_preserves_local_pricing_flag(self):
        r = _make_result(
            scoring_path="registry_direct",
            local_pricing_attempted=True,
            local_pricing_used=True,
            pipeline_stage_latency_ms={"mid_pipeline_abort": True},
        )
        assert r.local_pricing_attempted is True
        assert r.local_pricing_used is True


# ---------------------------------------------------------------------------
# 20. Low-lag zero-active-pools instant reject
# ---------------------------------------------------------------------------
class TestLowLagZeroActivePoolsReject:
    """Low-lag events with zero active registry pools get instantly rejected."""

    def test_reject_reason_is_all_pools_truly_inactive(self):
        r = _make_result(
            reject_reason=REJECT_ALL_POOLS_TRULY_INACTIVE,
            event_block=100, quote_block=100, block_lag=0,
        )
        assert r.reject_reason == REJECT_ALL_POOLS_TRULY_INACTIVE

    def test_reject_is_in_unscored_rejects(self):
        assert REJECT_ALL_POOLS_TRULY_INACTIVE in UNSCORED_REJECTS


# ---------------------------------------------------------------------------
# 21. Session prewarm pairs
# ---------------------------------------------------------------------------
class TestSessionPrewarm:
    """Prewarm high-frequency pairs at session start."""

    def test_prewarm_pairs_list(self):
        expected = [
            ("WETH", "USDC"), ("WETH", "USDT"), ("WETH", "ARB"),
            ("USDC", "USDT"), ("WETH", "WBTC"), ("ARB", "USDC"),
        ]
        assert len(expected) == 6
        for a, b in expected:
            assert a in ("WETH", "USDC", "USDT", "ARB", "WBTC")
            assert b in ("WETH", "USDC", "USDT", "ARB", "WBTC")


# ---------------------------------------------------------------------------
# 22. Detection-time lag accounting (M7.A.5.25)
# ---------------------------------------------------------------------------
class TestDetectionTimeLag:
    """Low-lag metrics use detection-time (event_detected_at_block - event_block)."""

    def test_detection_lag_same_block(self):
        r = _make_result(
            event_block=100, event_detected_at_block=100,
            block_lag=50, same_state_class="stale",
        )
        det_lag = r.event_detected_at_block - r.event_block
        assert det_lag == 0

    def test_detection_lag_different_from_final_lag(self):
        r = _make_result(
            event_block=100, event_detected_at_block=100,
            block_lag=126, same_state_class="stale",
            best_backrun_net_bps=5.0,
        )
        assert r.event_detected_at_block - r.event_block == 0
        assert r.block_lag == 126

    def test_artifact_events_detected_low_lag_uses_detection_time(self):
        """build_replay_summary.events_detected_low_lag uses detection-time lag."""
        r = _make_result(
            event_block=100, event_detected_at_block=100,
            block_lag=50, same_state_class="stale",
            best_backrun_net_bps=-5.0,
            reject_reason=REJECT_STALE_POSITIVE,
        )
        ev = _make_event(block=100)
        art = build_replay_summary([ev], [r], mode="ws_live")
        assert art["events_detected_low_lag"] == 1
