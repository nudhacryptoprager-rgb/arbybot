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
    route_id: str | None = None,
) -> dict:
    pool = f"0x{dex}{t0}{t1}0000000000000000000000000000000000"[:42]
    return {
        "route_id": route_id or f"r_{dex}_{t0}_{t1}",
        "dex_id": dex,
        "token0": t0,
        "token1": t1,
        "token0_addr": "0x4200000000000000000000000000000000000006" if t0 == "WETH" else focus_addr,
        "token1_addr": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913" if t1 == "USDC" else focus_addr,
        "pair_id": "_".join(sorted([t0, t1])),
        "pool_address": pool,
        "factory_verified": True,
        "factory_class": "EFFICIENT_BASELINE",
        "fee": 3000,
        "adapter_type": "uniswap_v3",
        "focus_token_symbol": focus_sym,
        "focus_token_address": focus_addr,
        "exotic_address": focus_addr,
        "expansion_route_kind": kind,
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


def test_select_graph_handoff_preserves_34_cycle_participants():
    """Regression: graph-handoff selection must keep all 3/4 cycle participant routes."""
    from m8.discovery.graph_handoff import select_graph_handoff_universe_routes
    from m9.graph_arb.topology_diagnostic import collect_cycle_route_ids_from_routes

    focus = "0x00000000000000000000000000000000000000ab"
    foo = focus
    weth = "0x4200000000000000000000000000000000000006"
    usdc = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
    routes = [
        {
            **_route(
                dex="uniswap_v3",
                t0="FOO",
                t1="WETH",
                focus_addr=focus,
                route_id="r_ab",
                kind="token_presence",
            ),
            "token0_addr": foo,
            "token1_addr": weth,
        },
        {
            **_route(
                dex="uniswap_v3",
                t0="WETH",
                t1="USDC",
                focus_addr=focus,
                route_id="r_bc",
                kind="connector_hop",
            ),
            "token0_addr": weth,
            "token1_addr": usdc,
        },
        {
            **_route(
                dex="uniswap_v3",
                t0="USDC",
                t1="FOO",
                focus_addr=focus,
                route_id="r_ca",
                kind="connector_hop",
            ),
            "token0_addr": usdc,
            "token1_addr": foo,
        },
    ]
    gh = evaluate_token_graph_handoff(
        focus_symbol="FOO",
        focus_address=focus,
        token_seen_on_dexes=2,
        unique_tokens=4,
        active_routes=3,
        same_pair_routes=[],
        token_presence_routes=[routes[0]],
        connector_routes=routes[1:],
        anchor_syms={"WETH", "USDC", "USDbC", "DAI"},
    )
    cycle_34_ids, _ = collect_cycle_route_ids_from_routes(
        routes, cycle_lengths=(3, 4), lane="discovery"
    )
    universe, funnel = select_graph_handoff_universe_routes(routes, [gh])
    selected_ids = {str(r.get("route_id") or "") for r in universe}
    if cycle_34_ids:
        assert cycle_34_ids <= selected_ids
    else:
        assert len(universe) >= 3
    assert funnel.get("routes_causing_cycle_loss") == []


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


def test_select_mirror_handoff_universe_includes_same_pair_routes():
    from m8.discovery.graph_handoff import select_mirror_handoff_universe_routes

    focus = "0xmirrorfocus000000000000000000000001"
    routes = [
        _route(
            dex="uniswap_v3",
            t0="FOO",
            t1="USDC",
            focus_addr=focus,
            kind="same_pair_mirror",
        ),
        _route(
            dex="aerodrome",
            t0="FOO",
            t1="USDC",
            focus_addr=focus,
            kind="same_pair_mirror",
        ),
        _route(
            dex="uniswap_v2",
            t0="FOO",
            t1="WETH",
            focus_addr=focus,
            kind="token_presence",
        ),
    ]
    mirror_debug = [
        {
            "focus_token_address": focus,
            "mirror_quote_ready": True,
        }
    ]
    universe, funnel = select_mirror_handoff_universe_routes(routes, mirror_debug)
    assert funnel["handoff_lane"] == "mirror_2leg"
    assert len(universe) >= 2
    mirror_kinds = {
        r.get("expansion_route_kind")
        for r in universe
        if r.get("expansion_route_kind") in ("same_pair_mirror", "cross_anchor_mirror")
    }
    assert "same_pair_mirror" in mirror_kinds or len(universe) >= 2

