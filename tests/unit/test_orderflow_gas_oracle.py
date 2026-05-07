"""
GAS_ORACLE tests for M7 orderflow.

Test categories covered:
- Chainlink oracle constants and guard
- Token enrichment functions (offline contract)
- Local-sim state extraction
- Subgraph seed constants
- Gas decomposition (L1/L2 split)
- Gas denomination conversion (ETH→token units)
"""
from __future__ import annotations

import os
from typing import Dict

from m7.orderflow.pricing import (
    _gas_cost_in_token_wei,
    check_oracle_sanity,
    estimate_gas_decomposition_bps,
)
from m7.orderflow.resolve import (
    enrich_tokens_batch,
    enrich_unknown_token,
    extract_pool_state_for_sim,
)
from m7.orderflow.coverage import seed_tokens_from_subgraph
from m7.shared.constants import (
    _FALLBACK_ETH_PRICE_USD,
    CHAINLINK_DECIMALS,
    CHAINLINK_FEEDS_ARBITRUM,
    CHAINLINK_FEEDS_BASE,
    CHAINLINK_LATEST_ROUND_SELECTOR,
    DEFAULT_BACKRUN_GAS,
    DEFAULT_GAS_PRICE_GWEI,
    SUBGRAPH_ENDPOINTS_ARBITRUM,
    SUBGRAPH_SEED_TOKEN_CAP,
    SUBGRAPH_TIMEOUT_SECONDS,
    get_chainlink_feeds,
)

from tests.unit.conftest import _make_event, _make_result


# ---------------------------------------------------------------------------
# 1. Chainlink oracle constants & guard
# ---------------------------------------------------------------------------
class TestChainlinkConstants:
    """Chainlink feed constants on Arbitrum."""

    def test_chainlink_feeds_arbitrum_is_dict(self):
        assert isinstance(CHAINLINK_FEEDS_ARBITRUM, dict)

    def test_chainlink_feeds_has_major_tokens(self):
        for token in ["WETH", "WBTC", "USDT", "USDC", "ARB"]:
            assert token in CHAINLINK_FEEDS_ARBITRUM, f"Missing feed for {token}"

    def test_chainlink_feeds_base_has_weth_usdc(self):
        assert "WETH" in CHAINLINK_FEEDS_BASE
        assert "USDC" in CHAINLINK_FEEDS_BASE
        assert get_chainlink_feeds("base") is CHAINLINK_FEEDS_BASE

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
# 2. Token enrichment (offline)
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
# 3. Local-sim state extraction
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
# 4. Subgraph seed constants
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
# 5. Gas decomposition (L1/L2)
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
# 6. Gas denomination conversion (ETH→token units)
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
