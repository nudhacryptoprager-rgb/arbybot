"""Tests for the fair per-pool data-quality scorecard methodology.

Validates that the scorecard:
* gives every pool a fair sample (LOW_SAMPLE → never quarantined),
* credits pools that produce valid quotes as HEALTHY (even unprofitable),
* ignores transient RPC/revert noise,
* blames the depth bottleneck, not its deeper partners,
* only marks a pool TOXIC after consistent, multi-size, zero-valid evidence,
* emits soft, TTL'd quarantine recommendations only for TOXIC pools.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from m9.graph_arb.models import CycleQuoteResult, GraphCycle, GraphEdge
from m9.graph_arb.pool_scorecard import (
    CLASS_HEALTHY,
    CLASS_LOW_SAMPLE,
    CLASS_PROBATION,
    CLASS_TOXIC,
    REASON_DEPTH_TOXIC,
    REASON_STRUCTURAL_ZERO,
    ScorecardConfig,
    build_pool_scorecards,
    classify_leg_reject,
    recommend_quarantine,
)

_ADDR_A = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
_ADDR_B = "0xbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
_ADDR_C = "0xcccccccccccccccccccccccccccccccccccccccc"
_THIN = "0x1111111111111111111111111111111111111111"   # bottleneck pool
_DEEP = "0x2222222222222222222222222222222222222222"   # deep partner pool
_POOL3 = "0x3333333333333333333333333333333333333333"
_QUOTER = "0x0000000000000000000000000000000000000001"


@dataclass
class _Leg:
    """Minimal stand-in for a leg QuoteResult (ok / reject_reason / route_id)."""

    ok: bool
    reject_reason: Optional[str] = None
    route_id: str = "r"


def _edge(sym_in, addr_in, sym_out, addr_out, pool, depth):
    return GraphEdge(
        token_in_sym=sym_in, token_out_sym=sym_out,
        token_in_addr=addr_in, token_out_addr=addr_out,
        token_in_decimals=18, token_out_decimals=18,
        route_id=f"{sym_in}_{sym_out}",
        dex_id="uniswap_v2", adapter_type="uniswap_v2",
        fee=3000, tick_spacing=None,
        quoter_addr=_QUOTER, pool_address=pool,
        fee_bps=30.0, factory_class="UNKNOWN",
        pair_id=f"{sym_in}_{sym_out}",
        effective_depth_usd=depth,
    )


def _cycle(thin_depth=50.0, deep_depth=500_000.0) -> GraphCycle:
    """3-leg cycle: THIN bottleneck pool + DEEP partner + a third pool."""
    return GraphCycle(edges=(
        _edge("A", _ADDR_A, "B", _ADDR_B, _THIN, thin_depth),
        _edge("B", _ADDR_B, "C", _ADDR_C, _DEEP, deep_depth),
        _edge("C", _ADDR_C, "A", _ADDR_A, _POOL3, deep_depth),
    ))


def _qr(status, size, *, reject_reason=None, legs=None, raw_gross_bps=None,
        cycle=None) -> CycleQuoteResult:
    return CycleQuoteResult(
        cycle=cycle or _cycle(),
        size_usd=size, amount_in=1_000_000, amount_out=0,
        gross_bps=0.0, status=status, reject_reason=reject_reason,
        leg_results=legs or [], elapsed_s=0.01, raw_gross_bps=raw_gross_bps,
    )


# --- leg reject classification --------------------------------------------

def test_classify_leg_reject_transient():
    assert classify_leg_reject("QUOTE_RPC_ERROR") == "TRANSIENT"
    assert classify_leg_reject("QUOTE_REVERT") == "TRANSIENT"
    assert classify_leg_reject("TIMEOUT") == "TRANSIENT"


def test_classify_leg_reject_structural_zero():
    assert classify_leg_reject("QUOTE_ZERO_OUTPUT") == "STRUCTURAL_ZERO"


def test_classify_leg_reject_other_is_failed():
    assert classify_leg_reject("SOME_DECODE_ERROR") == "FAILED"
    assert classify_leg_reject(None) == "FAILED"


# --- bottleneck attribution: deep partner is NOT condemned -----------------

def test_depth_overflow_blames_bottleneck_not_deep_partner():
    cfg = ScorecardConfig(min_samples=4, min_sizes_for_toxic=2)
    results = [
        _qr("QUOTE_FAILED", s, reject_reason="OVERSIZED_VS_DEPTH")
        for s in (1.0, 5.0, 10.0, 20.0)
    ]
    cards = {c["pool_address"].lower(): c for c in build_pool_scorecards(results, cfg)}
    thin = cards[_THIN.lower()]
    deep = cards[_DEEP.lower()]
    # THIN bottleneck took all the depth-overflow blame -> TOXIC
    assert thin["classification"] == CLASS_TOXIC
    assert thin["depth_overflow_count"] == 4
    assert thin["valid_count"] == 0
    # DEEP partner produced usable leg quotes every time -> HEALTHY, kept
    assert deep["classification"] == CLASS_HEALTHY
    assert deep["valid_count"] == 4
    assert deep["depth_overflow_count"] == 0


# --- HEALTHY: a valid (even unprofitable) quote is credit -------------------

def test_pool_with_valid_quotes_is_healthy_even_if_unprofitable():
    cfg = ScorecardConfig(min_samples=4)
    results = [_qr("NEGATIVE_GROSS", s) for s in (1.0, 5.0, 10.0, 20.0)]
    cards = {c["pool_address"].lower(): c for c in build_pool_scorecards(results, cfg)}
    for pool in (_THIN, _DEEP, _POOL3):
        assert cards[pool.lower()]["classification"] == CLASS_HEALTHY


# --- fair sample: not enough evidence -> never toxic -----------------------

def test_low_sample_pool_is_not_quarantined():
    cfg = ScorecardConfig(min_samples=8, min_sizes_for_toxic=2)
    # Only 3 overflow observations of the thin pool — below min_samples.
    results = [
        _qr("QUOTE_FAILED", s, reject_reason="OVERSIZED_VS_DEPTH")
        for s in (1.0, 5.0, 10.0)
    ]
    cards = {c["pool_address"].lower(): c for c in build_pool_scorecards(results, cfg)}
    thin = cards[_THIN.lower()]
    assert thin["classification"] == CLASS_LOW_SAMPLE
    assert recommend_quarantine(list(cards.values()), cfg) == []


# --- transient RPC noise never condemns a pool -----------------------------

def test_transient_rpc_errors_do_not_make_pool_toxic():
    cfg = ScorecardConfig(min_samples=4, min_sizes_for_toxic=2)
    legs = [_Leg(ok=False, reject_reason="QUOTE_RPC_ERROR")]
    results = [_qr("QUOTE_FAILED", s, reject_reason="CYCLE_QUOTE_FAILED", legs=legs)
               for s in (1.0, 5.0, 10.0, 20.0)]
    cards = {c["pool_address"].lower(): c for c in build_pool_scorecards(results, cfg)}
    thin = cards[_THIN.lower()]
    # All failures were transient -> excluded from denominator -> LOW_SAMPLE,
    # never TOXIC.
    assert thin["classification"] == CLASS_LOW_SAMPLE
    assert thin["transient_count"] == 4
    assert thin["samples"] == 0


# --- single-size failure is not enough for toxic ---------------------------

def test_single_size_overflow_stays_probation_not_toxic():
    cfg = ScorecardConfig(min_samples=4, min_sizes_for_toxic=2)
    # Many overflows but all at the SAME size -> cannot conclude depth-toxic.
    results = [_qr("QUOTE_FAILED", 1.0, reject_reason="OVERSIZED_VS_DEPTH")
               for _ in range(6)]
    cards = {c["pool_address"].lower(): c for c in build_pool_scorecards(results, cfg)}
    thin = cards[_THIN.lower()]
    assert thin["classification"] == CLASS_PROBATION


# --- structural zero-output reason surfaces correctly ----------------------

def test_structural_zero_output_pool_is_toxic_with_zero_reason():
    cfg = ScorecardConfig(min_samples=4, min_sizes_for_toxic=2)
    # First leg (THIN pool) returns zero output across multiple sizes.
    legs = [_Leg(ok=False, reject_reason="QUOTE_ZERO_OUTPUT")]
    results = [_qr("QUOTE_FAILED", s, reject_reason="CYCLE_QUOTE_FAILED", legs=legs)
               for s in (1.0, 5.0, 10.0, 20.0)]
    cards = {c["pool_address"].lower(): c for c in build_pool_scorecards(results, cfg)}
    thin = cards[_THIN.lower()]
    assert thin["classification"] == CLASS_TOXIC
    assert thin["toxic_reason"] == REASON_STRUCTURAL_ZERO


# --- recommendation: soft entry with TTL only for TOXIC --------------------

def test_recommendation_is_soft_ttl_only_for_toxic():
    cfg = ScorecardConfig(min_samples=4, min_sizes_for_toxic=2)
    results = [
        _qr("QUOTE_FAILED", s, reject_reason="OVERSIZED_VS_DEPTH")
        for s in (1.0, 5.0, 10.0, 20.0)
    ]
    cards = build_pool_scorecards(results, cfg)
    recs = recommend_quarantine(cards, cfg)
    assert len(recs) == 1
    entry = recs[0]
    assert entry["pool_address"].lower() == _THIN.lower()
    assert entry["reject_reason"] == REASON_DEPTH_TOXIC
    assert entry["retry_after_utc"].endswith("Z")  # soft TTL present
    assert entry["source"] == "pool_scorecard"
    assert entry["fee"] == 3000


# --- mixed pool keeps observing (probation) --------------------------------

def test_mixed_valid_and_overflow_below_healthy_is_probation():
    cfg = ScorecardConfig(min_samples=4, min_sizes_for_toxic=2,
                          healthy_valid_rate=0.5, toxic_dominance_rate=0.9)
    # THIN pool: 1 valid + 5 overflow -> valid_rate ~0.17 (<0.5 healthy),
    # but valid_count > 0 so not toxic -> PROBATION (keep observing).
    results = [_qr("NEGATIVE_GROSS", 1.0, cycle=_cycle())]
    results += [_qr("QUOTE_FAILED", s, reject_reason="OVERSIZED_VS_DEPTH")
                for s in (5.0, 10.0, 20.0, 30.0, 40.0)]
    cards = {c["pool_address"].lower(): c for c in build_pool_scorecards(results, cfg)}
    thin = cards[_THIN.lower()]
    assert thin["classification"] == CLASS_PROBATION
    assert thin["valid_count"] == 1
