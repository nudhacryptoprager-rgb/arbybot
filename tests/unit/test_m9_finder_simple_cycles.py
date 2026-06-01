"""Regression tests for m9.graph_arb.finder simple-cycle enforcement.

Guards against the non-simple "figure-8" cycle bug where the DFS continuation
guard excluded the start token, allowing paths like WETH->XCHAT->WETH->AERO->WETH
(two concatenated round-trips that surface as low-grade asymmetry phantoms).
"""
from __future__ import annotations

from typing import Dict, List

import pytest

from m9.graph_arb.finder import find_cycles
from m9.graph_arb.models import GraphEdge

_ADDR = {
    "WETH": "0x" + "1" * 40,
    "XCHAT": "0x" + "2" * 40,
    "AERO": "0x" + "3" * 40,
    "USDC": "0x" + "4" * 40,
}


def _edge(a: str, b: str, route_id: str) -> GraphEdge:
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
        pool_address="0x" + "a" * 40,
        fee_bps=30.0,
        factory_class="EFFICIENT_BASELINE",
        pair_id=f"{a}-{b}",
    )


def _build_adjacency(pairs: List[tuple[str, str]]) -> Dict[str, Dict[str, List[GraphEdge]]]:
    """Build a bidirectional adjacency from undirected symbol pairs."""
    adj: Dict[str, Dict[str, List[GraphEdge]]] = {}
    for i, (a, b) in enumerate(pairs):
        for x, y in ((a, b), (b, a)):
            adj.setdefault(x, {}).setdefault(y, []).append(_edge(x, y, f"r{i}_{x}_{y}"))
    return adj


def _interior_revisits_start(token_path: List[str]) -> bool:
    """True if the start token appears in the interior (non-simple cycle)."""
    if len(token_path) < 3:
        return False
    return token_path[0] in token_path[1:]


def test_finder_never_emits_interior_start_revisit():
    """The hub token must not be revisited mid-path (figure-8 bug)."""
    # WETH connected to XCHAT and AERO would have produced
    # WETH->XCHAT->WETH->AERO->WETH under the old guard.
    adj = _build_adjacency([("WETH", "XCHAT"), ("WETH", "AERO")])
    cycles = find_cycles(adj, cycle_lengths=(3, 4))
    for c in cycles:
        assert not _interior_revisits_start(
            c.token_path
        ), f"non-simple cycle emitted: {c.token_path}"
    # No simple 3- or 4-cycle exists in this star topology, so none should be found.
    assert cycles == []


def test_finder_still_finds_genuine_triangle():
    """A real WETH->XCHAT->USDC->WETH triangle must still be found."""
    adj = _build_adjacency(
        [("WETH", "XCHAT"), ("XCHAT", "USDC"), ("USDC", "WETH")]
    )
    cycles = find_cycles(adj, cycle_lengths=(3, 4))
    assert cycles, "genuine triangle should be found"
    for c in cycles:
        assert not _interior_revisits_start(c.token_path)
        # Every token in the path is distinct (simple cycle).
        assert len(set(c.token_path)) == len(c.token_path)


def test_finder_simple_cycles_have_distinct_tokens():
    """All emitted cycles are simple: no repeated vertices in token_path."""
    adj = _build_adjacency(
        [
            ("WETH", "XCHAT"),
            ("WETH", "AERO"),
            ("XCHAT", "USDC"),
            ("USDC", "WETH"),
            ("AERO", "USDC"),
        ]
    )
    cycles = find_cycles(adj, cycle_lengths=(3, 4))
    for c in cycles:
        assert len(set(c.token_path)) == len(
            c.token_path
        ), f"non-simple cycle: {c.token_path}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
