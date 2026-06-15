"""Tests for graph node canonicalization."""
from __future__ import annotations

from m9.graph_arb.node_canonical import canonical_graph_node, normalize_expansion_route_tokens


def test_canonical_graph_node_maps_truncated_weth():
    sym = canonical_graph_node("0x420000", "0x4200000000000000000000000000000000000006")
    assert sym == "WETH"


def test_normalize_expansion_route_replaces_placeholder_t():
    route = {
        "pair_id": "0xabc_0x420000",
        "token0": "0x00000000000000000000000000000000000000ab",
        "token1": "T",
        "token0_addr": "0x00000000000000000000000000000000000000ab",
        "focus_token_symbol": "FOO",
        "focus_token_address": "0x00000000000000000000000000000000000000ab",
    }
    out = normalize_expansion_route_tokens(route)
    assert out["token1"] == "WETH"
