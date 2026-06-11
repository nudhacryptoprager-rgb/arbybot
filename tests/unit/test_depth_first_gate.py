"""Depth-first economics gate tests."""
from __future__ import annotations

from m9.graph_arb.depth_first_gate import (
    REJECT_DEPTH_BELOW_LIVENESS,
    apply_depth_first_gate,
    cycle_fails_depth_first_gate,
    min_quote_size_usd,
)
from m9.graph_arb.models import GraphCycle, GraphEdge


def _edge(
    *,
    route_suffix: str,
    pool_suffix: str,
    tin: str,
    tout: str,
    depth: float | None,
) -> GraphEdge:
    addr_in = "0x" + tin * 40
    addr_out = "0x" + tout * 40
    return GraphEdge(
        token_in_sym="A" if tin == "1" else "B",
        token_out_sym="B" if tin == "1" else "A",
        token_in_addr=addr_in,
        token_out_addr=addr_out,
        token_in_decimals=18,
        token_out_decimals=18,
        route_id=f"r_{route_suffix}",
        dex_id="uniswap_v3",
        adapter_type="uniswap_v3",
        fee=3000,
        tick_spacing=None,
        quoter_addr="0x" + "9" * 40,
        pool_address="0x" + pool_suffix * 40,
        fee_bps=30.0,
        factory_class="EFFICIENT_BASELINE",
        pair_id="A_B",
        effective_depth_usd=depth,
    )


def _cycle(depth: float | None) -> GraphCycle:
    return GraphCycle(
        edges=(
            _edge(route_suffix="1", pool_suffix="a", tin="1", tout="2", depth=depth),
            _edge(route_suffix="2", pool_suffix="b", tin="2", tout="1", depth=depth),
        )
    )


def test_min_quote_size_from_ladder():
    assert min_quote_size_usd([0.25, 1.0, 100.0]) == 0.25


def test_shallow_pool_fails_depth_gate():
    assert cycle_fails_depth_first_gate(_cycle(0.1), 0.25) is True
    assert cycle_fails_depth_first_gate(_cycle(1.0), 0.25) is False
    assert cycle_fails_depth_first_gate(_cycle(None), 0.25) is False


def test_apply_depth_first_gate_splits_batch():
    shallow = _cycle(0.05)
    deep = _cycle(50.0)
    batch, skipped = apply_depth_first_gate([shallow, deep], [0.25, 1.0])
    assert len(batch) == 1
    assert len(skipped) == 1
    assert skipped[0].reject_reason == REJECT_DEPTH_BELOW_LIVENESS
