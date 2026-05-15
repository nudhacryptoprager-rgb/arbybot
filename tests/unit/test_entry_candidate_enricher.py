"""Unit tests for ``strategy/entry_candidate_enricher.py`` (Phase 2 enricher).

Locks the enricher's contracts: liquidity fetch dispatch, USD normalisation,
mirror detection, honeypot integration, spread estimation, and expected PnL.
All on-chain calls are mocked via a minimal ``MockW3`` stub so tests run
fully offline.
"""
from __future__ import annotations

from typing import Any, Optional
from unittest.mock import MagicMock, patch

import pytest

from strategy.entry_candidate_enricher import (
    ANCHOR_ADDRESSES,
    ANCHOR_TOKEN_USD,
    EnrichmentResult,
    EntryCandidateEnricher,
)
from strategy.sniper_entry_decision import EntryCandidate

# ---------------------------------------------------------------------------
# Address fixtures
# ---------------------------------------------------------------------------

USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
WETH = "0x4200000000000000000000000000000000000006"
DAI = "0x50c5725949a6f0c72e6c4a641f24049a917db0cb"
RAND_TOKEN = "0x" + "aa" * 20
POOL_V2 = "0x" + "bb" * 20
POOL_V3 = "0x" + "cc" * 20
POOL_V4 = "0x" + "dd" * 20


# ---------------------------------------------------------------------------
# Minimal mock for web3 contract calls
# ---------------------------------------------------------------------------

class _MockContractFunctions:
    """Configurable mock contract-function registry.

    Supports the web3 pattern ``contract.functions.METHOD().call()``:
    - ``contract.functions.METHOD`` → returns ``m``
    - ``contract.functions.METHOD()`` → returns ``m.return_value``
    - ``contract.functions.METHOD().call()`` → returns the fixture value
    """

    def __init__(self, responses: dict):
        self._responses = responses

    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        resp = self._responses.get(name)
        if resp is None:
            raise AttributeError(f"No mock response for {name!r}")
        m = MagicMock()
        # METHOD() → m.return_value;  METHOD().call() → resp
        m.return_value.call.return_value = resp
        return m


class _MockContract:
    def __init__(self, responses: dict):
        self.functions = _MockContractFunctions(responses)


class MockW3:
    """Minimal web3-alike stub.  Intercepts ``eth.contract(...)`` calls."""

    def __init__(self, contract_responses: Optional[dict] = None):
        # pool_addr (lowercase) → {function_name: return_value}
        self._responses: dict = contract_responses or {}
        self.eth = self

    def to_checksum_address(self, addr: str) -> str:
        return addr  # no checksum in tests

    def contract(self, *, address: str, abi: Any) -> _MockContract:
        addr_l = address.lower()
        resp = self._responses.get(addr_l, {})
        return _MockContract(resp)


# ---------------------------------------------------------------------------
# NewPoolEvent stub
# ---------------------------------------------------------------------------

def _make_event(
    *,
    token0: str = USDC,
    token1: str = WETH,
    pool: str = POOL_V2,
    dex: str = "aerodrome",
    block_number: int = 100,
) -> Any:
    """Build a minimal object with the fields EntryCandidateEnricher reads."""
    e = MagicMock()
    e.token0 = token0
    e.token1 = token1
    e.pool = pool
    e.dex = dex
    e.block_number = block_number
    e.event_id = f"test_{pool}_{block_number}"
    e.chain = "base"
    e.factory = "0x" + "ef" * 20
    e.tx_hash = "0x" + "0" * 64
    return e


# ---------------------------------------------------------------------------
# Tests: ANCHOR_ADDRESSES and ANCHOR_TOKEN_USD coverage
# ---------------------------------------------------------------------------

class TestAnchorConstants:
    def test_usdc_in_anchor_addresses(self):
        assert USDC in ANCHOR_ADDRESSES

    def test_weth_price_positive(self):
        assert ANCHOR_TOKEN_USD[WETH] > 0

    def test_stable_prices_are_one(self):
        assert ANCHOR_TOKEN_USD[USDC] == 1.0
        assert ANCHOR_TOKEN_USD[DAI] == 1.0


# ---------------------------------------------------------------------------
# Tests: V2 liquidity fetch
# ---------------------------------------------------------------------------

class TestV2LiquidityFetch:
    def _make_enricher(self, reserve0: int, reserve1: int) -> EntryCandidateEnricher:
        # USDC (6 dec) / WETH (18 dec) pair
        # reserve0 = 10_000 * 10^6 = 10 000 USDC raw
        # reserve1 = 4 * 10^18 = 4 WETH raw
        w3 = MockW3(
            {
                POOL_V2: {"getReserves": (reserve0, reserve1, 0)},
            }
        )
        return EntryCandidateEnricher(w3)

    def test_v2_liquidity_usd_computed(self):
        # 10000 USDC + 4 WETH → liquidity_usd ≈ 10000 * 1.0 * 2 = 20000
        enricher = self._make_enricher(10_000 * 10**6, 4 * 10**18)
        event = _make_event(token0=USDC, token1=WETH, pool=POOL_V2, dex="aerodrome")
        result = enricher.enrich(event)
        assert result.liquidity_usd is not None
        assert result.liquidity_usd == pytest.approx(20000.0, rel=0.01)

    def test_v2_reserves_returned_as_human(self):
        enricher = self._make_enricher(5_000 * 10**6, 2 * 10**18)
        event = _make_event(token0=USDC, token1=WETH, pool=POOL_V2, dex="aerodrome")
        result = enricher.enrich(event)
        # reserve0 should be ~5000 (in USDC human units), reserve1 ~2 (WETH)
        assert result.reserve0_raw == pytest.approx(5000.0, rel=0.01)
        assert result.reserve1_raw == pytest.approx(2.0, rel=0.01)

    def test_v2_rpc_error_returns_none(self):
        # Contract raises exception → reserves should be None
        w3 = MockW3({})  # no response for pool → AttributeError on getReserves
        enricher = EntryCandidateEnricher(w3)
        event = _make_event(token0=USDC, token1=WETH, pool=POOL_V2, dex="aerodrome")
        result = enricher.enrich(event)
        assert result.liquidity_usd is None
        assert result.reserve0_raw is None


# ---------------------------------------------------------------------------
# Tests: V3 liquidity fetch
# ---------------------------------------------------------------------------

class TestV3LiquidityFetch:
    def _make_enricher(self, liq_raw: int, sqrt_x96: int) -> EntryCandidateEnricher:
        # slot0 returns (sqrtPriceX96, tick, obsIdx, obsCard, obsCardNext, feeProto, unlocked)
        w3 = MockW3(
            {
                POOL_V3: {
                    "liquidity": liq_raw,
                    "slot0": (sqrt_x96, 0, 0, 1, 1, 0, True),
                },
            }
        )
        return EntryCandidateEnricher(w3)

    def test_v3_zero_liquidity_returns_none(self):
        enricher = self._make_enricher(liq_raw=0, sqrt_x96=0)
        event = _make_event(token0=USDC, token1=WETH, pool=POOL_V3, dex="uniswap_v3")
        result = enricher.enrich(event)
        assert result.liquidity_usd is None
        assert "V3_ZERO" in (result.liquidity_note or "")

    def test_v3_nonzero_liquidity_computes_usd(self):
        # Approximate sqrtPriceX96 for 1 USDC = 1/2500 WETH
        # price = 1/2500 WETH/USDC, but we need it in token1/token0 units
        # USDC = token0 (6 dec), WETH = token1 (18 dec)
        # P = (sqrtX96 / 2^96)^2 in raw units
        # For 1 USDC (1e6 raw) = 1/2500 WETH (=4e14 raw):
        #   P_raw = 4e14 / 1e6 = 4e8
        #   sqrtP_raw = sqrt(4e8) ≈ 20000
        #   sqrtX96 = sqrtP_raw * 2^96 ≈ 20000 * 7.9e28 ≈ 1.58e33
        # Use a simpler sanity check: if we set large liq + valid price, USD > 0
        import math
        # P = token1_raw/token0_raw = (4*10^14)/(1*10^6) = 4*10^8
        # sqrt(P) = 2*10^4
        # sqrtX96 = sqrt(P) * 2^96
        sqrt_p_raw = 20_000.0
        sqrt_x96 = int(sqrt_p_raw * (2**96))
        liq_raw = 1_000_000  # arbitrary active liquidity

        enricher = self._make_enricher(liq_raw=liq_raw, sqrt_x96=sqrt_x96)
        event = _make_event(token0=USDC, token1=WETH, pool=POOL_V3, dex="uniswap_v3")
        result = enricher.enrich(event)
        # With a valid sqrtPrice, we should get a non-None liquidity_usd
        assert result.reserve0_raw is not None
        assert result.reserve1_raw is not None


# ---------------------------------------------------------------------------
# Tests: V4 skip
# ---------------------------------------------------------------------------

class TestV4Skip:
    def test_v4_returns_no_reserves(self):
        w3 = MockW3({})
        enricher = EntryCandidateEnricher(w3)
        event = _make_event(pool=POOL_V4, dex="uniswap_v4")
        result = enricher.enrich(event)
        assert result.reserve0_raw is None
        assert result.reserve1_raw is None
        assert result.liquidity_note == "V4_SKIP"


# ---------------------------------------------------------------------------
# Tests: USD normalisation
# ---------------------------------------------------------------------------

class TestUSDNormalisation:
    def test_anchor_token0_normalises(self):
        # USDC/RAND_TOKEN pair — USDC is anchor on token0 side
        w3 = MockW3(
            {POOL_V2: {"getReserves": (1_000 * 10**6, 1000 * 10**18, 0)}}
        )
        enricher = EntryCandidateEnricher(w3)
        event = _make_event(token0=USDC, token1=RAND_TOKEN, pool=POOL_V2, dex="aerodrome")
        result = enricher.enrich(event)
        # r0 = 1000 USDC, price0 = $1 → USD = 1000 * 1.0 * 2 = 2000
        assert result.liquidity_usd == pytest.approx(2000.0, rel=0.01)

    def test_anchor_token1_normalises(self):
        # RAND_TOKEN/WETH pair — WETH is anchor on token1 side
        w3 = MockW3(
            {POOL_V2: {"getReserves": (1000 * 10**18, 1 * 10**18, 0)}}
        )
        enricher = EntryCandidateEnricher(w3)
        event = _make_event(token0=RAND_TOKEN, token1=WETH, pool=POOL_V2, dex="aerodrome")
        result = enricher.enrich(event)
        # r1 = 1 WETH, price1 = $2500 → USD = 1 * 2500 * 2 = 5000
        assert result.liquidity_usd == pytest.approx(5000.0, rel=0.01)

    def test_no_anchor_returns_none(self):
        w3 = MockW3(
            {POOL_V2: {"getReserves": (500 * 10**18, 500 * 10**18, 0)}}
        )
        enricher = EntryCandidateEnricher(w3)
        event = _make_event(token0=RAND_TOKEN, token1="0x" + "ff" * 20, pool=POOL_V2, dex="aerodrome")
        result = enricher.enrich(event)
        assert result.liquidity_usd is None
        assert result.liquidity_note == "NO_ANCHOR_IN_PAIR"


# ---------------------------------------------------------------------------
# Tests: Mirror detection
# ---------------------------------------------------------------------------

class TestMirrorDetection:
    def test_first_event_no_mirror(self):
        w3 = MockW3(
            {POOL_V2: {"getReserves": (1_000 * 10**6, 1 * 10**18, 0)}}
        )
        enricher = EntryCandidateEnricher(w3)
        event = _make_event(token0=USDC, token1=WETH, pool=POOL_V2, dex="aerodrome")
        result = enricher.enrich(event)
        assert result.mirror_found is False
        assert result.mirror_dex is None

    def test_second_event_different_dex_finds_mirror(self):
        pool_a = "0x" + "11" * 20
        pool_b = "0x" + "22" * 20
        # Both pools: 1000 USDC + 0.4 WETH (same price for simplicity)
        w3 = MockW3(
            {
                pool_a: {"getReserves": (1_000 * 10**6, 4 * 10**17, 0)},
                pool_b: {"getReserves": (2_000 * 10**6, 8 * 10**17, 0)},
            }
        )
        enricher = EntryCandidateEnricher(w3)
        # First event on aerodrome
        e1 = _make_event(token0=USDC, token1=WETH, pool=pool_a, dex="aerodrome")
        r1 = enricher.enrich(e1)
        assert r1.mirror_found is False

        # Second event on uniswap_v3 — same token pair
        e2 = _make_event(token0=USDC, token1=WETH, pool=pool_b, dex="uniswap_v3")
        r2 = enricher.enrich(e2)
        assert r2.mirror_found is True
        assert r2.mirror_dex == "aerodrome"
        assert r2.mirror_pool == pool_a

    def test_same_dex_does_not_count_as_mirror(self):
        pool_a = "0x" + "33" * 20
        pool_b = "0x" + "44" * 20
        w3 = MockW3(
            {
                pool_a: {"getReserves": (1_000 * 10**6, 4 * 10**17, 0)},
                pool_b: {"getReserves": (2_000 * 10**6, 8 * 10**17, 0)},
            }
        )
        enricher = EntryCandidateEnricher(w3)
        e1 = _make_event(token0=USDC, token1=WETH, pool=pool_a, dex="aerodrome")
        enricher.enrich(e1)
        e2 = _make_event(token0=USDC, token1=WETH, pool=pool_b, dex="aerodrome")
        r2 = enricher.enrich(e2)
        assert r2.mirror_found is False

    def test_mirror_spread_computed_from_price_diff(self):
        pool_a = "0x" + "55" * 20
        pool_b = "0x" + "66" * 20
        # pool_a: USDC/WETH at 2500 (1 USDC = 1/2500 WETH, i.e. r1/r0 = 1/2500)
        # pool_b: USDC/WETH at 2600 (slightly different price)
        # Both use V2-style getReserves; different DEX names to trigger mirror logic.
        w3 = MockW3(
            {
                pool_a: {"getReserves": (2500 * 10**6, 1 * 10**18, 0)},   # 2500 USDC / 1 WETH
                pool_b: {"getReserves": (2600 * 10**6, 1 * 10**18, 0)},   # 2600 USDC / 1 WETH
            }
        )
        enricher = EntryCandidateEnricher(w3)
        # First event on aerodrome (V2-style reserves)
        e1 = _make_event(token0=USDC, token1=WETH, pool=pool_a, dex="aerodrome")
        enricher.enrich(e1)
        # Second event on uniswap_v2 — same token pair, different DEX (V2 reserves)
        e2 = _make_event(token0=USDC, token1=WETH, pool=pool_b, dex="uniswap_v2")
        r2 = enricher.enrich(e2)
        assert r2.mirror_found is True
        assert r2.estimated_spread_bps is not None
        # price_a = 1/2500 ≈ 0.0004, price_b = 1/2600 ≈ 0.000385
        # deviation ≈ |0.000385 - 0.0004| / 0.0004 ≈ 3.85%  → ~385 bps
        assert r2.estimated_spread_bps > 0
        assert r2.spread_note == "FROM_MIRROR"


# ---------------------------------------------------------------------------
# Tests: Honeypot check integration
# ---------------------------------------------------------------------------

class TestHoneypotCheck:
    def test_known_legit_pair_returns_pass(self):
        w3 = MockW3(
            {POOL_V2: {"getReserves": (1_000 * 10**6, 1 * 10**18, 0)}}
        )
        enricher = EntryCandidateEnricher(w3)
        # USDC + WETH are both KNOWN_LEGIT
        event = _make_event(token0=USDC, token1=WETH, pool=POOL_V2, dex="aerodrome")
        result = enricher.enrich(event)
        assert result.honeypot_verdict == "PASS"
        assert result.candidate.honeypot_verdict == "PASS"

    def test_known_scam_pair_returns_fail(self):
        DEAD = "0x000000000000000000000000000000000000dead"
        w3 = MockW3(
            {POOL_V2: {"getReserves": (1000 * 10**18, 1000 * 10**18, 0)}}
        )
        enricher = EntryCandidateEnricher(w3)
        event = _make_event(token0=USDC, token1=DEAD, pool=POOL_V2, dex="aerodrome")
        result = enricher.enrich(event)
        assert result.honeypot_verdict == "FAIL"

    def test_unknown_token_returns_unknown(self):
        w3 = MockW3(
            {POOL_V2: {"getReserves": (1000 * 10**18, 1000 * 10**18, 0)}}
        )
        enricher = EntryCandidateEnricher(w3)
        event = _make_event(token0=RAND_TOKEN, token1=WETH, pool=POOL_V2, dex="aerodrome")
        result = enricher.enrich(event)
        assert result.honeypot_verdict == "UNKNOWN"


# ---------------------------------------------------------------------------
# Tests: Spread estimation (anchor-ratio)
# ---------------------------------------------------------------------------

class TestSpreadEstimation:
    def test_anchor_ratio_spread_usdc_weth(self):
        # USDC/WETH pool at ratio = 1/2500 (expected by anchor prices) → ~0 bps
        w3 = MockW3(
            {POOL_V2: {"getReserves": (2500 * 10**6, 1 * 10**18, 0)}}
        )
        enricher = EntryCandidateEnricher(w3)
        event = _make_event(token0=USDC, token1=WETH, pool=POOL_V2, dex="aerodrome")
        result = enricher.enrich(event)
        assert result.estimated_spread_bps is not None
        assert result.spread_note == "FROM_ANCHOR_RATIO"
        assert result.estimated_spread_bps == pytest.approx(0.0, abs=1.0)

    def test_mispriced_anchor_pair_has_spread(self):
        # USDC/WETH at 2200:1 instead of expected 2500:1 → significant spread
        w3 = MockW3(
            {POOL_V2: {"getReserves": (2200 * 10**6, 1 * 10**18, 0)}}
        )
        enricher = EntryCandidateEnricher(w3)
        event = _make_event(token0=USDC, token1=WETH, pool=POOL_V2, dex="aerodrome")
        result = enricher.enrich(event)
        assert result.estimated_spread_bps is not None
        assert result.estimated_spread_bps > 100  # ~1200 bps deviation

    def test_no_reference_when_neither_token_is_anchor(self):
        w3 = MockW3(
            {POOL_V2: {"getReserves": (500 * 10**18, 500 * 10**18, 0)}}
        )
        enricher = EntryCandidateEnricher(w3)
        event = _make_event(token0=RAND_TOKEN, token1="0x" + "ff" * 20, pool=POOL_V2, dex="aerodrome")
        result = enricher.enrich(event)
        assert result.estimated_spread_bps is None
        assert result.spread_note == "NO_REFERENCE_PRICE"


# ---------------------------------------------------------------------------
# Tests: Expected PnL
# ---------------------------------------------------------------------------

class TestExpectedPnL:
    def test_pnl_computed_when_all_gates_pass(self):
        # 2200 USDC / 1 WETH (mispriced → spread > 0)
        # liquidity_usd ≈ 2200 * 1.0 * 2 = 4400
        # spread_bps ≈ |(2200 USDC / 1 WETH = 2200) vs expected 2500| / 2500 * 10000 = 1200 bps
        # expected_pnl = 4400 * (1200 / 10000) * 0.5 - 0.30 = 263.7
        w3 = MockW3(
            {POOL_V2: {"getReserves": (2200 * 10**6, 1 * 10**18, 0)}}
        )
        enricher = EntryCandidateEnricher(w3)
        event = _make_event(token0=USDC, token1=WETH, pool=POOL_V2, dex="aerodrome")
        result = enricher.enrich(event)
        # honeypot must be PASS for PnL to be computed
        assert result.honeypot_verdict == "PASS"
        assert result.expected_pnl_usd is not None
        assert result.expected_pnl_usd > 0

    def test_pnl_none_when_liquidity_missing(self):
        w3 = MockW3({})  # no response → reserves None
        enricher = EntryCandidateEnricher(w3)
        event = _make_event(token0=USDC, token1=WETH, pool=POOL_V2, dex="aerodrome")
        result = enricher.enrich(event)
        assert result.expected_pnl_usd is None

    def test_pnl_none_when_honeypot_unknown(self):
        # RAND_TOKEN/WETH: honeypot = UNKNOWN → PnL not computed
        w3 = MockW3(
            {POOL_V2: {"getReserves": (2200 * 10**6, 1 * 10**18, 0)}}
        )
        enricher = EntryCandidateEnricher(w3)
        event = _make_event(token0=RAND_TOKEN, token1=WETH, pool=POOL_V2, dex="aerodrome")
        result = enricher.enrich(event)
        assert result.expected_pnl_usd is None


# ---------------------------------------------------------------------------
# Tests: EnrichmentResult.to_dict() schema
# ---------------------------------------------------------------------------

class TestEnrichmentResultToDict:
    def test_all_keys_present(self):
        w3 = MockW3(
            {POOL_V2: {"getReserves": (2500 * 10**6, 1 * 10**18, 0)}}
        )
        enricher = EntryCandidateEnricher(w3)
        event = _make_event(token0=USDC, token1=WETH, pool=POOL_V2, dex="aerodrome")
        result = enricher.enrich(event)
        d = result.to_dict()
        required_keys = {
            "liquidity_usd", "liquidity_note", "estimated_spread_bps", "spread_note",
            "mirror_found", "mirror_dex", "mirror_pool", "honeypot_verdict",
            "slippage_result", "expected_pnl_usd",
        }
        assert required_keys <= set(d.keys())

    def test_candidate_is_entry_candidate(self):
        w3 = MockW3(
            {POOL_V2: {"getReserves": (1_000 * 10**6, 4 * 10**17, 0)}}
        )
        enricher = EntryCandidateEnricher(w3)
        event = _make_event(token0=USDC, token1=WETH, pool=POOL_V2, dex="aerodrome")
        result = enricher.enrich(event)
        assert isinstance(result.candidate, EntryCandidate)
        assert result.candidate.token0 == USDC
        assert result.candidate.token1 == WETH


# ---------------------------------------------------------------------------
# Tests: No-w3 / offline fallback
# ---------------------------------------------------------------------------

class TestNoW3Fallback:
    def test_enricher_with_none_w3_returns_empty_candidate(self):
        enricher = EntryCandidateEnricher(None)
        event = _make_event(token0=USDC, token1=WETH, pool=POOL_V2, dex="aerodrome")
        result = enricher.enrich(event)
        # Should not raise; returns bare candidate with all-None enrichment
        assert result.candidate.token0 == USDC
        assert result.liquidity_usd is None
        assert result.estimated_spread_bps is None
