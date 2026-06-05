"""Unit tests for bridge-shadow spread lifetime telemetry."""
from __future__ import annotations

from m9.graph_arb.models import GraphCycle, GraphEdge, CycleQuoteResult
from m9.graph_arb.spread_lifetime import SpreadLifetimeTracker


def _edge(**kw) -> GraphEdge:
    defaults = dict(
        token_in_sym="FOO",
        token_out_sym="USDC",
        token_in_addr="0xabc",
        token_out_addr="0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
        token_in_decimals=18,
        token_out_decimals=6,
        route_id="m8x_uni_pool1",
        dex_id="uniswap_v3",
        adapter_type="uniswap_v3",
        fee=3000,
        tick_spacing=60,
        quoter_addr="0x0",
        pool_address="0xpool1",
        fee_bps=30.0,
        factory_class="EFFICIENT_BASELINE",
        pair_id="FOO_USDC",
        factory_verified=True,
    )
    defaults.update(kw)
    return GraphEdge(**defaults)


def test_spread_lifetime_tracks_positive_sweeps():
    cycle = GraphCycle(
        edges=(
            _edge(),
            _edge(
                token_in_sym="USDC",
                token_out_sym="FOO",
                token_in_addr="0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
                token_out_addr="0xabc",
                pool_address="0xpool2",
                route_id="m8x_aero_pool2",
                dex_id="aerodrome",
            ),
        )
    )
    qr = CycleQuoteResult(
        cycle=cycle,
        size_usd=10.0,
        amount_in=1,
        amount_out=2,
        gross_bps=12.5,
        status="POSITIVE_GROSS",
        reject_reason=None,
        leg_results=[],
        elapsed_s=0.1,
    )
    tracker = SpreadLifetimeTracker(run_timestamp="2026-06-05T12:00:00Z")
    m8 = frozenset({"0xpool1"})
    xmech = frozenset({"0xpool2"})
    tracker.record_sweep(
        sweep_number=1,
        sweep_ts=1000.0,
        results=[qr],
        m8_pool_addrs=m8,
        cross_mechanic_pool_addrs=xmech,
    )
    tracker.record_sweep(
        sweep_number=2,
        sweep_ts=1060.0,
        results=[qr],
        m8_pool_addrs=m8,
        cross_mechanic_pool_addrs=xmech,
    )
    summary = tracker.build_summary()
    assert summary["entry_count"] == 1
    assert summary["median_lifetime_s"] == 60.0
    assert len(tracker.sweep_observations) == 2
    block = tracker.to_artifact_block()
    assert "spread_lifetime" in block
