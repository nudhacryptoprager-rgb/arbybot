"""Tests for TOXIC_STABLE_POOL classification in pool scorecard (Step 5 P0)."""
from __future__ import annotations

from dataclasses import dataclass

from m9.graph_arb.models import CycleQuoteResult, GraphCycle, GraphEdge
from m9.graph_arb.pool_scorecard import (
    OUTCOME_TOXIC_STABLE,
    REASON_TOXIC_STABLE,
    ScorecardConfig,
    accumulate_observations,
    build_pool_scorecards,
    classify_leg_reject,
    recommend_quarantine,
)


def _edge(pool="0xpool1", route_id="r1"):
    return GraphEdge(
        token_in_sym="USDC",
        token_out_sym="DAI",
        token_in_addr="0x0",
        token_out_addr="0x1",
        token_in_decimals=6,
        token_out_decimals=18,
        route_id=route_id,
        dex_id="maverick_v2",
        adapter_type="maverick_v2",
        fee=0,
        tick_spacing=None,
        quoter_addr="0xquoter",
        pool_address=pool,
        fee_bps=0.0,
        factory_class="UNISWAP_V2",
        pair_id="DAI_USDC",
    )


def _cycle(edges):
    if len(edges) == 2:
        src = edges[0]
        e2 = GraphEdge(
            **{
                **edges[1].__dict__,
                "token_in_sym": src.token_out_sym,
                "token_out_sym": src.token_in_sym,
                "token_in_addr": src.token_out_addr,
                "token_out_addr": src.token_in_addr,
            }
        )
        if e2.pool_address.lower() == src.pool_address.lower():
            e2 = GraphEdge(**{**e2.__dict__, "pool_address": "0xpool2"})
        edges = [src, e2]
    return GraphCycle(edges=tuple(edges))


def _qr(cycle, leg_reject_reason="TOXIC_STABLE_POOL", size_usd=0.25):
    @dataclass
    class _Leg:
        ok: bool = False
        amount_in: int = 0
        amount_out: int = 0
        reject_reason: str = ""
        raw_error: str = ""
        elapsed_s: float = 0.0

    leg = _Leg(reject_reason=leg_reject_reason, raw_error="stable_ratio_outlier")
    return CycleQuoteResult(
        cycle=cycle,
        size_usd=size_usd,
        amount_in=0,
        amount_out=0,
        gross_bps=0.0,
        status="CYCLE_QUOTE_FAILED",
        reject_reason=leg_reject_reason,
        leg_results=[leg],
        elapsed_s=0.0,
    )


def test_classify_leg_reject_toxic_stable():
    assert classify_leg_reject("TOXIC_STABLE_POOL") == OUTCOME_TOXIC_STABLE
    assert classify_leg_reject("stable_ratio_outlier") == OUTCOME_TOXIC_STABLE


def test_accumulate_toxic_stable_observations():
    c = _cycle([_edge(), _edge(route_id="r2")])
    results = [_qr(c, size_usd=s) for s in (0.25, 0.5, 1.0, 5.0, 10.0, 50.0, 100.0, 180.0, 250.0, 500.0)]
    pools = accumulate_observations(results)
    # The first leg's pool should have toxic_stable observations
    assert any(obs.toxic_stable > 0 for obs in pools.values())


def test_toxic_stable_pool_recommended_for_quarantine():
    c = _cycle([_edge(), _edge(route_id="r2")])
    cfg = ScorecardConfig(min_samples=8, min_blocks_for_toxic_stable=3)
    # Repeated invariant failure on one size across time buckets (Maverick USDC/DAI case).
    results = [_qr(c, size_usd=0.25) for _ in range(24)]
    cards = build_pool_scorecards(results, config=cfg)
    toxic_cards = [card for card in cards if card["classification"] == "TOXIC"]
    assert len(toxic_cards) >= 1
    assert toxic_cards[0]["toxic_reason"] == REASON_TOXIC_STABLE
    recs = recommend_quarantine(cards, config=cfg)
    assert len(recs) >= 1
    assert recs[0]["reject_reason"] == REASON_TOXIC_STABLE
