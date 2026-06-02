"""Tests for configurable cycle topologies in m9.graph_arb.

Covers the opt-in widening of cycle enumeration beyond triangles:
  * 2-leg direct cross-venue arbitrage (A->B->A on two *distinct* pools)
  * 4-leg quadrilateral cycles
  * the distinct-pool invariant that rejects degenerate same-pool round-trips

Default runner behavior stays (3, 4); these tests exercise the finder/model
directly with explicit ``cycle_lengths``.
"""
from __future__ import annotations

from typing import Dict, List

import pytest

from m9.graph_arb.finder import find_cycles
from m9.graph_arb.models import GraphCycle, GraphEdge

_ADDR = {
    "WETH": "0x" + "1" * 40,
    "AERO": "0x" + "2" * 40,
    "USDC": "0x" + "3" * 40,
    "DAI": "0x" + "4" * 40,
}


def _edge(a: str, b: str, route_id: str, pool: str) -> GraphEdge:
    return GraphEdge(
        token_in_sym=a,
        token_out_sym=b,
        token_in_addr=_ADDR[a],
        token_out_addr=_ADDR[b],
        token_in_decimals=18,
        token_out_decimals=18,
        route_id=route_id,
        dex_id="uniswap_v2",
        adapter_type="v2",
        fee=3000,
        tick_spacing=None,
        quoter_addr="0x" + "9" * 40,
        pool_address=pool,
        fee_bps=30.0,
        factory_class="EFFICIENT_BASELINE",
        pair_id=f"{a}-{b}",
    )


# --------------------------------------------------------------------------- #
# Model invariant: 2-leg cycles                                               #
# --------------------------------------------------------------------------- #
def test_graphcycle_two_leg_distinct_pools_accepted():
    """A->B->A across two distinct pools is a valid 2-leg arbitrage cycle."""
    pool1 = "0x" + "a" * 40
    pool2 = "0x" + "b" * 40
    cycle = GraphCycle(
        edges=(
            _edge("WETH", "AERO", "r1", pool1),
            _edge("AERO", "WETH", "r2", pool2),
        )
    )
    assert cycle.length == 2
    assert cycle.token_path == ["WETH", "AERO"]


def test_graphcycle_two_leg_same_pool_rejected():
    """A->B->A through the SAME pool is a guaranteed fee loss, not arbitrage."""
    pool = "0x" + "a" * 40
    with pytest.raises(ValueError, match="two distinct pools"):
        GraphCycle(
            edges=(
                _edge("WETH", "AERO", "r1", pool),
                _edge("AERO", "WETH", "r2", pool),
            )
        )


def test_graphcycle_single_edge_still_rejected():
    """A 1-edge 'cycle' is impossible and must still raise."""
    pool = "0x" + "a" * 40
    with pytest.raises(ValueError, match=">= 2 edges"):
        GraphCycle(edges=(_edge("WETH", "AERO", "r1", pool),))


# --------------------------------------------------------------------------- #
# Finder: 2-leg enumeration                                                   #
# --------------------------------------------------------------------------- #
def test_finder_emits_two_leg_across_distinct_pools():
    """Two distinct WETH<->AERO pools yield a direct 2-leg cycle."""
    adj: Dict[str, Dict[str, List[GraphEdge]]] = {
        "WETH": {"AERO": [
            _edge("WETH", "AERO", "rA", "0x" + "a" * 40),
            _edge("WETH", "AERO", "rB", "0x" + "b" * 40),
        ]},
        "AERO": {"WETH": [
            _edge("AERO", "WETH", "rA", "0x" + "a" * 40),
            _edge("AERO", "WETH", "rB", "0x" + "b" * 40),
        ]},
    }
    cycles = find_cycles(adj, cycle_lengths=(2,))
    assert cycles, "expected at least one 2-leg cycle across distinct pools"
    for c in cycles:
        assert c.length == 2
        assert c.edges[0].pool_address.lower() != c.edges[1].pool_address.lower()


def test_finder_skips_two_leg_same_pool():
    """A single WETH<->AERO pool must NOT produce a degenerate 2-leg loop."""
    adj: Dict[str, Dict[str, List[GraphEdge]]] = {
        "WETH": {"AERO": [_edge("WETH", "AERO", "rA", "0x" + "a" * 40)]},
        "AERO": {"WETH": [_edge("AERO", "WETH", "rA", "0x" + "a" * 40)]},
    }
    cycles = find_cycles(adj, cycle_lengths=(2,))
    assert cycles == [], "same-pool round-trip must be skipped"


def test_finder_two_leg_does_not_appear_under_default_lengths():
    """With default (3, 4) lengths, no 2-leg cycle is emitted."""
    adj: Dict[str, Dict[str, List[GraphEdge]]] = {
        "WETH": {"AERO": [
            _edge("WETH", "AERO", "rA", "0x" + "a" * 40),
            _edge("WETH", "AERO", "rB", "0x" + "b" * 40),
        ]},
        "AERO": {"WETH": [
            _edge("AERO", "WETH", "rA", "0x" + "a" * 40),
            _edge("AERO", "WETH", "rB", "0x" + "b" * 40),
        ]},
    }
    cycles = find_cycles(adj, cycle_lengths=(3, 4))
    assert cycles == []


# --------------------------------------------------------------------------- #
# Finder: 4-leg enumeration                                                   #
# --------------------------------------------------------------------------- #
def test_finder_emits_four_leg_quadrilateral():
    """WETH->AERO->USDC->DAI->WETH quadrilateral is found at length 4."""
    pairs = [("WETH", "AERO"), ("AERO", "USDC"), ("USDC", "DAI"), ("DAI", "WETH")]
    adj: Dict[str, Dict[str, List[GraphEdge]]] = {}
    for i, (a, b) in enumerate(pairs):
        for x, y in ((a, b), (b, a)):
            pool = "0x" + format(i, "x") * 40 if i else "0x" + "f" * 40
            adj.setdefault(x, {}).setdefault(y, []).append(
                _edge(x, y, f"r{i}_{x}_{y}", pool)
            )
    cycles = find_cycles(adj, cycle_lengths=(4,))
    assert any(c.length == 4 for c in cycles), "expected a 4-leg quadrilateral"
    for c in cycles:
        # All cycles are simple (no repeated vertex).
        assert len(set(c.token_path)) == len(c.token_path)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
