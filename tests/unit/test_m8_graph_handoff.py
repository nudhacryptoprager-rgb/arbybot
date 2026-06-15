"""Tests for M8.2 graph-topology handoff lanes."""
from __future__ import annotations

from m8.discovery.graph_handoff import (
    detect_cross_anchor_pattern,
    evaluate_token_graph_handoff,
    refresh_graph_handoff_in_expansion_doc,
)


def _route(
    *,
    dex: str,
    t0: str,
    t1: str,
    focus_addr: str = "0xabc",
    focus_sym: str = "FOO",
    kind: str = "same_pair_mirror",
) -> dict:
    return {
        "dex_id": dex,
        "token0": t0,
        "token1": t1,
        "focus_token_symbol": focus_sym,
        "focus_token_address": focus_addr,
        "exotic_address": focus_addr,
        "expansion_route_kind": kind,
        "pool_address": f"0x{dex}{t0}{t1}0000000000000000000000000000000000"[:42],
    }


def test_cross_anchor_pattern_detected():
    routes = [
        _route(dex="uniswap_v3", t0="FOO", t1="WETH"),
        _route(dex="aerodrome", t0="FOO", t1="USDC"),
    ]
    assert detect_cross_anchor_pattern("FOO", routes, {"WETH", "USDC", "USDbC", "DAI"})


def test_graph_topology_ready_cross_anchor_no_quote_required():
    same = [
        _route(dex="uniswap_v3", t0="FOO", t1="WETH"),
        _route(dex="aerodrome", t0="FOO", t1="USDC"),
    ]
    gh = evaluate_token_graph_handoff(
        focus_symbol="FOO",
        focus_address="0xabc",
        token_seen_on_dexes=2,
        unique_tokens=3,
        active_routes=2,
        same_pair_routes=same,
        token_presence_routes=[],
        connector_routes=[],
        anchor_syms={"WETH", "USDC", "USDbC", "DAI"},
    )
    assert gh["cross_anchor_ready"] is True
    assert gh["graph_topology_ready"] is True
    assert gh["requires_m9_quote"] is True
    assert gh["economics_claim"] is False
    assert same[0]["expansion_route_kind"] == "cross_anchor_mirror"
    assert same[0]["requires_quote_validation"] is True
    assert same[0]["handoff_lane"] == "graph_topology"


def test_connector_graph_topology_ready():
    tp = [
        _route(
            dex="uniswap_v3",
            t0="FOO",
            t1="PEPE",
            kind="token_presence",
        ),
        _route(
            dex="aerodrome",
            t0="FOO",
            t1="DOGE",
            kind="token_presence",
        ),
    ]
    conn = [
        _route(
            dex="uniswap_v3",
            t0="PEPE",
            t1="USDC",
            kind="connector_hop",
        ),
    ]
    gh = evaluate_token_graph_handoff(
        focus_symbol="FOO",
        focus_address="0xabc",
        token_seen_on_dexes=2,
        unique_tokens=4,
        active_routes=3,
        same_pair_routes=[],
        token_presence_routes=tp,
        connector_routes=conn,
        anchor_syms={"WETH", "USDC", "USDbC", "DAI"},
    )
    assert gh["token_presence_graph_ready"] is True
    assert gh["connector_graph_ready"] is True
    assert gh["graph_topology_ready"] is True


def test_refresh_graph_handoff_updates_expansion_summary():
    doc = {
        "summary": {"mirror_quote_ready_tokens": 0},
        "routes_admitted": [
            _route(dex="uniswap_v3", t0="FOO", t1="WETH"),
            _route(dex="aerodrome", t0="FOO", t1="USDC"),
        ],
    }
    out = refresh_graph_handoff_in_expansion_doc(doc)
    assert out["graph_topology_ready_tokens"] == 1
    assert doc["summary"]["handoff_ready"] is True
    assert doc["summary"]["handoff_lane"] == "graph_topology"
    assert doc["graph_handoff"]["requires_m9_quote"] is True
    assert doc["summary"]["graph_handoff_cycle_potential_routes"] >= 2


def test_cross_anchor_via_token_presence_routes():
    tp = [
        _route(dex="uniswap_v3", t0="FOO", t1="WETH", kind="token_presence"),
        _route(dex="aerodrome", t0="FOO", t1="USDC", kind="token_presence"),
    ]
    assert detect_cross_anchor_pattern(
        "FOO", [], {"WETH", "USDC", "USDbC", "DAI"}, tp
    )


def test_select_graph_handoff_universe_includes_connector_closure():
    from m8.discovery.graph_handoff import select_graph_handoff_universe_routes

    focus = "0xabc"
    tp = [
        _route(
            dex="uniswap_v3",
            t0="FOO",
            t1="PEPE",
            focus_addr=focus,
            kind="token_presence",
        ),
        _route(
            dex="aerodrome",
            t0="FOO",
            t1="DOGE",
            focus_addr=focus,
            kind="token_presence",
        ),
    ]
    conn = [
        _route(
            dex="uniswap_v3",
            t0="PEPE",
            t1="USDC",
            focus_addr=focus,
            kind="connector_hop",
        ),
    ]
    gh = evaluate_token_graph_handoff(
        focus_symbol="FOO",
        focus_address=focus,
        token_seen_on_dexes=2,
        unique_tokens=4,
        active_routes=3,
        same_pair_routes=[],
        token_presence_routes=tp,
        connector_routes=conn,
        anchor_syms={"WETH", "USDC", "USDbC", "DAI"},
    )
    routes = tp + conn
    universe, funnel = select_graph_handoff_universe_routes(routes, [gh])
    assert funnel["graph_handoff_cycle_potential_routes"] == len(universe)
    assert len(universe) == 3
    kinds = {r.get("expansion_route_kind") for r in universe}
    assert "connector_hop" in kinds or "connector_graph" in kinds
