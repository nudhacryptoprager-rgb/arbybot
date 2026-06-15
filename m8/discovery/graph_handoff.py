"""M8.2 graph-topology handoff lanes (broader than 2-leg same-pair mirror).

Lanes:
  same_pair_mirror     — TOKEN/ANCHOR on DEX-A and TOKEN/ANCHOR on DEX-B (2-leg)
  cross_anchor_mirror  — TOKEN/WETH on DEX-A and TOKEN/USDC on DEX-B (3-leg via anchor hop)
  token_presence_graph — TOKEN/X on DEX-A, TOKEN/Y on DEX-B, connector path to anchor
  connector_graph      — TOKEN/X, X/Y, Y/ANCHOR (4-leg candidate)

M8.2 proves connectivity + metadata; M9 owns quote/sizing economics.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple

_GRAPH_ROUTE_KINDS = frozenset(
    {"cross_anchor_mirror", "token_presence_graph", "connector_graph"}
)
_LEGACY_CONNECTOR_KIND = "connector_hop"


def anchor_symbols_for_graph() -> Set[str]:
    try:
        from m8.discovery.pending_pair_registry import _ANCHOR_TOKENS

        return set(_ANCHOR_TOKENS) | {"USDbC"}
    except Exception:
        return {"WETH", "USDC", "USDbC", "DAI", "EURC", "cbBTC", "USDT", "WETH_BASE"}


def _focus_partner(route: Dict[str, Any], focus_sym: str) -> str:
    t0 = str(route.get("token0") or "")
    t1 = str(route.get("token1") or "")
    if t0 == focus_sym:
        return t1
    if t1 == focus_sym:
        return t0
    return ""


def _anchor_reachable(
    focus_sym: str,
    routes: List[Dict[str, Any]],
    connector_routes: List[Dict[str, Any]],
    anchor_syms: Set[str],
) -> bool:
    if focus_sym in anchor_syms:
        return True
    adj: Dict[str, Set[str]] = defaultdict(set)
    for route in routes + connector_routes:
        t0 = str(route.get("token0") or "")
        t1 = str(route.get("token1") or "")
        if t0 and t1:
            adj[t0].add(t1)
            adj[t1].add(t0)
    visited = {focus_sym}
    queue = [focus_sym]
    while queue:
        cur = queue.pop(0)
        if cur in anchor_syms:
            return True
        for nbr in adj.get(cur, ()):
            if nbr not in visited:
                visited.add(nbr)
                queue.append(nbr)
    return False


def detect_cross_anchor_pattern(
    focus_sym: str,
    same_pair_routes: List[Dict[str, Any]],
    anchor_syms: Set[str],
    token_presence_routes: Optional[List[Dict[str, Any]]] = None,
) -> bool:
    """TOKEN/ANCHOR_A on DEX-A and TOKEN/ANCHOR_B on DEX-B (anchors may differ)."""
    by_dex: Dict[str, Set[str]] = defaultdict(set)
    for route in list(same_pair_routes) + list(token_presence_routes or []):
        dex = str(route.get("dex_id") or "")
        partner = _focus_partner(route, focus_sym)
        if not partner:
            fs = str(route.get("focus_token_symbol") or focus_sym)
            partner = _focus_partner(route, fs)
        if dex and partner in anchor_syms:
            by_dex[dex].add(partner)
    anchors_all: Set[str] = set()
    dex_with_anchor = 0
    for _dex, anchors in by_dex.items():
        if anchors:
            dex_with_anchor += 1
            anchors_all |= anchors
    return len(anchors_all) >= 2 and dex_with_anchor >= 2


def detect_token_presence_graph_pattern(
    token_presence_routes: List[Dict[str, Any]],
    token_seen_on_dexes: int,
) -> bool:
    dexes = {str(r.get("dex_id") or "") for r in token_presence_routes if r.get("dex_id")}
    return token_seen_on_dexes >= 2 and len(dexes) >= 2


def detect_connector_graph_pattern(
    connector_routes: List[Dict[str, Any]],
    token_seen_on_dexes: int,
) -> bool:
    return token_seen_on_dexes >= 2 and len(connector_routes) >= 1


def classify_and_tag_neighborhood_routes(
    *,
    focus_sym: str,
    same_pair_routes: List[Dict[str, Any]],
    token_presence_routes: List[Dict[str, Any]],
    connector_routes: List[Dict[str, Any]],
    anchor_syms: Set[str],
    anchor_reachable: bool,
    cross_anchor: bool,
    token_presence_graph: bool,
) -> None:
    """Mutates route dicts: sets expansion_route_kind + handoff metadata."""
    if cross_anchor:
        for route in same_pair_routes + token_presence_routes:
            partner = _focus_partner(route, focus_sym)
            if partner in anchor_syms:
                route["expansion_route_kind"] = "cross_anchor_mirror"
                _apply_graph_handoff_tags(route)

    if token_presence_graph and anchor_reachable:
        for route in token_presence_routes:
            route["expansion_route_kind"] = "token_presence_graph"
            _apply_graph_handoff_tags(route)

    for route in connector_routes:
        route["expansion_route_kind"] = "connector_graph"
        if anchor_reachable:
            _apply_graph_handoff_tags(route)

    for route in same_pair_routes:
        if route.get("expansion_route_kind") == "cross_anchor_mirror":
            continue
        if str(route.get("expansion_route_kind") or "") in ("", "same_pair_mirror"):
            route["expansion_route_kind"] = "same_pair_mirror"
            route.setdefault("handoff_lane", "mirror_2leg")


def _apply_graph_handoff_tags(route: Dict[str, Any]) -> None:
    route["requires_quote_validation"] = True
    route["economics_claim"] = False
    route["handoff_lane"] = "graph_topology"


def graph_topology_missing_reason(
    *,
    token_seen_on_dexes: int,
    unique_tokens: int,
    active_routes: int,
    anchor_reachable: bool,
    cross_anchor: bool,
    token_presence_graph: bool,
    connector_graph: bool,
) -> str:
    if token_seen_on_dexes < 2:
        return "TOKEN_SEEN_ON_ONE_DEX"
    if unique_tokens < 3:
        return "UNIQUE_TOKENS_LT_3"
    if active_routes < 2:
        return "ACTIVE_ROUTES_LT_2"
    if not cross_anchor and active_routes < 3:
        return "ACTIVE_ROUTES_LT_3"
    if not anchor_reachable:
        return "NO_ANCHOR_PATH"
    if not (cross_anchor or token_presence_graph or connector_graph):
        return "NO_GRAPH_PATTERN"
    return "READY"


def evaluate_token_graph_handoff(
    *,
    focus_symbol: str,
    focus_address: str,
    token_seen_on_dexes: int,
    unique_tokens: int,
    active_routes: int,
    same_pair_routes: List[Dict[str, Any]],
    token_presence_routes: List[Dict[str, Any]],
    connector_routes: List[Dict[str, Any]],
    anchor_syms: Optional[Set[str]] = None,
) -> Dict[str, Any]:
    """Per-token mini-subgraph readiness for M9 graph handoff (no quote required)."""
    anchors = anchor_syms if anchor_syms is not None else anchor_symbols_for_graph()
    all_routes = same_pair_routes + token_presence_routes + connector_routes
    anchor_reachable = _anchor_reachable(
        focus_symbol, all_routes, connector_routes, anchors
    )
    cross_anchor = detect_cross_anchor_pattern(
        focus_symbol, same_pair_routes, anchors, token_presence_routes
    )
    token_presence_graph = (
        detect_token_presence_graph_pattern(
            token_presence_routes, token_seen_on_dexes
        )
        and anchor_reachable
    )
    connector_graph = (
        detect_connector_graph_pattern(connector_routes, token_seen_on_dexes)
        and anchor_reachable
    )

    classify_and_tag_neighborhood_routes(
        focus_sym=focus_symbol,
        same_pair_routes=same_pair_routes,
        token_presence_routes=token_presence_routes,
        connector_routes=connector_routes,
        anchor_syms=anchors,
        anchor_reachable=anchor_reachable,
        cross_anchor=cross_anchor,
        token_presence_graph=token_presence_graph,
    )

    cross_anchor_ready = cross_anchor and token_seen_on_dexes >= 2 and anchor_reachable
    connector_graph_ready = connector_graph
    token_presence_graph_ready = token_presence_graph
    min_active_routes = 2 if cross_anchor_ready else 3
    graph_topology_ready = (
        token_seen_on_dexes >= 2
        and unique_tokens >= 3
        and active_routes >= min_active_routes
        and anchor_reachable
        and (cross_anchor_ready or token_presence_graph_ready or connector_graph_ready)
    )

    return {
        "focus_token_address": focus_address,
        "focus_token_symbol": focus_symbol,
        "token_seen_on_dexes": token_seen_on_dexes,
        "unique_tokens": unique_tokens,
        "active_routes": active_routes,
        "anchor_reachable": anchor_reachable,
        "cross_anchor_ready": cross_anchor_ready,
        "token_presence_graph_ready": token_presence_graph_ready,
        "connector_graph_ready": connector_graph_ready,
        "graph_topology_ready": graph_topology_ready,
        "missing_reason": (
            "READY"
            if graph_topology_ready
            else graph_topology_missing_reason(
                token_seen_on_dexes=token_seen_on_dexes,
                unique_tokens=unique_tokens,
                active_routes=active_routes,
                anchor_reachable=anchor_reachable,
                cross_anchor=cross_anchor,
                token_presence_graph=token_presence_graph,
                connector_graph=connector_graph,
            )
        ),
        "requires_m9_quote": graph_topology_ready,
        "economics_claim": False,
    }


def _bucket_routes_by_focus(
    routes: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    by_focus: Dict[str, Dict[str, Any]] = {}
    for route in routes:
        focus = str(
            route.get("focus_token_address") or route.get("exotic_address") or ""
        ).lower()
        if not focus.startswith("0x"):
            continue
        bucket = by_focus.setdefault(
            focus,
            {
                "symbol": route.get("focus_token_symbol") or "",
                "same_pair": [],
                "token_presence": [],
                "connector": [],
                "dexes": set(),
            },
        )
        if route.get("focus_token_symbol"):
            bucket["symbol"] = route.get("focus_token_symbol")
        dex = str(route.get("dex_id") or "")
        if dex:
            bucket["dexes"].add(dex)
        kind = str(route.get("expansion_route_kind") or "token_presence")
        if kind in ("same_pair_mirror", "cross_anchor_mirror"):
            bucket["same_pair"].append(route)
        elif kind in ("connector_graph", _LEGACY_CONNECTOR_KIND):
            bucket["connector"].append(route)
        else:
            bucket["token_presence"].append(route)
    return by_focus


def aggregate_graph_handoff_from_routes(
    routes: List[Dict[str, Any]],
    *,
    anchor_syms: Optional[Set[str]] = None,
) -> Tuple[int, int, int, int, List[Dict[str, Any]]]:
    """Recompute graph handoff counts from admitted routes (artifact refresh)."""
    anchors = anchor_syms if anchor_syms is not None else anchor_symbols_for_graph()
    by_focus = _bucket_routes_by_focus(routes)
    graph_topology = cross_anchor = connector_graph = token_presence_graph = 0
    debug: List[Dict[str, Any]] = []

    for focus, info in sorted(by_focus.items()):
        same = list(info["same_pair"])
        tp = list(info["token_presence"])
        conn = list(info["connector"])
        all_routes = same + tp + conn
        syms = {
            info["symbol"],
            *[str(r.get("token0") or "") for r in all_routes],
            *[str(r.get("token1") or "") for r in all_routes],
        }
        syms.discard("")
        gh = evaluate_token_graph_handoff(
            focus_symbol=str(info["symbol"] or focus[:8]),
            focus_address=focus,
            token_seen_on_dexes=len(info["dexes"]),
            unique_tokens=len(syms),
            active_routes=len(all_routes),
            same_pair_routes=same,
            token_presence_routes=tp,
            connector_routes=conn,
            anchor_syms=anchors,
        )
        if gh["graph_topology_ready"]:
            graph_topology += 1
        if gh["cross_anchor_ready"]:
            cross_anchor += 1
        if gh["connector_graph_ready"]:
            connector_graph += 1
        if gh["token_presence_graph_ready"]:
            token_presence_graph += 1
        if len(debug) < 64 and (
            gh["graph_topology_ready"]
            or gh["cross_anchor_ready"]
            or gh["token_presence_graph_ready"]
            or gh["connector_graph_ready"]
        ):
            debug.append(gh)

    return graph_topology, cross_anchor, token_presence_graph, connector_graph, debug


def _route_pool_key(route: Dict[str, Any]) -> Tuple[str, str, str]:
    return (
        str(route.get("pool_address") or route.get("pool_id") or "").lower(),
        str(route.get("dex_id") or ""),
        str(route.get("focus_token_address") or route.get("exotic_address") or "").lower(),
    )


def _neighborhood_for_ready_token(
    *,
    focus_addr: str,
    focus_sym: str,
    info: Dict[str, Any],
    anchor_syms: Set[str],
) -> Tuple[Set[str], Set[str]]:
    """Symbols and connector (non-anchor) symbols for a graph-topology-ready token."""
    neighborhood: Set[str] = set()
    connectors: Set[str] = set()
    if focus_sym:
        neighborhood.add(focus_sym)
    for route in info["same_pair"] + info["token_presence"] + info["connector"]:
        for sym in (route.get("token0"), route.get("token1")):
            if sym:
                neighborhood.add(str(sym))
        partner = _focus_partner(route, focus_sym) if focus_sym else ""
        if partner and partner not in anchor_syms:
            connectors.add(partner)
    return neighborhood, connectors


def select_graph_handoff_universe_routes(
    routes: List[Dict[str, Any]],
    graph_topology_debug: List[Dict[str, Any]],
    *,
    anchor_syms: Optional[Set[str]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Select expansion routes for M9 graph-handoff bridge (focus + connector closure)."""
    from collections import Counter

    anchors = anchor_syms if anchor_syms is not None else anchor_symbols_for_graph()
    ready_addrs = {
        str(row.get("focus_token_address") or "").lower()
        for row in graph_topology_debug
        if row.get("graph_topology_ready")
    }
    by_focus = _bucket_routes_by_focus(routes)
    neighborhood_syms: Set[str] = set()
    connector_syms: Set[str] = set()
    for focus in ready_addrs:
        info = by_focus.get(focus)
        if not info:
            continue
        sym = str(info.get("symbol") or "")
        nbr, conn = _neighborhood_for_ready_token(
            focus_addr=focus,
            focus_sym=sym,
            info=info,
            anchor_syms=anchors,
        )
        neighborhood_syms |= nbr
        connector_syms |= conn

    selected: List[Dict[str, Any]] = []
    seen: Set[Tuple[str, str, str]] = set()
    include_reasons: Counter[str] = Counter()
    reject_reasons: Counter[str] = Counter()

    def _try_add(route: Dict[str, Any], reason: str) -> bool:
        key = _route_pool_key(route)
        if key[0] and key in seen:
            return False
        if key[0]:
            seen.add(key)
        _apply_graph_handoff_tags(route)
        selected.append(route)
        include_reasons[reason] += 1
        return True

    for route in routes:
        focus = str(
            route.get("focus_token_address") or route.get("exotic_address") or ""
        ).lower()
        kind = str(route.get("expansion_route_kind") or "")
        t0 = str(route.get("token0") or "")
        t1 = str(route.get("token1") or "")

        if focus in ready_addrs:
            _try_add(route, "focus_graph_topology_ready")
            continue

        if not ready_addrs:
            reject_reasons["NO_GRAPH_TOPOLOGY_READY_TOKENS"] += 1
            continue

        if kind in ("connector_graph", _LEGACY_CONNECTOR_KIND):
            if (t0 in connector_syms and t1 in anchors) or (
                t1 in connector_syms and t0 in anchors
            ):
                _try_add(route, "connector_closure_x_anchor")
                continue
            if t0 in connector_syms or t1 in connector_syms:
                if t0 in anchors or t1 in anchors:
                    _try_add(route, "connector_closure_x_anchor")
                    continue
            reject_reasons["CONNECTOR_NOT_IN_NEIGHBORHOOD"] += 1
            continue

        if t0 in neighborhood_syms and t1 in neighborhood_syms:
            _try_add(route, "neighborhood_symbol_pair")
            continue
        if (t0 in neighborhood_syms and t1 in anchors) or (
            t1 in neighborhood_syms and t0 in anchors
        ):
            _try_add(route, "neighborhood_anchor_touch")
            continue

        if route.get("requires_quote_validation"):
            reject_reasons["HANDOFF_TAGGED_OUTSIDE_UNIVERSE"] += 1
        else:
            reject_reasons["NOT_IN_GRAPH_HANDOFF_UNIVERSE"] += 1

    handoff_tagged = sum(1 for r in routes if r.get("requires_quote_validation"))
    funnel: Dict[str, Any] = {
        "expansion_routes_total": len(routes),
        "expansion_handoff_tagged_routes": handoff_tagged,
        "graph_topology_ready_tokens": len(ready_addrs),
        "graph_handoff_universe_routes": len(selected),
        "graph_handoff_cycle_potential_routes": len(selected),
        "include_reason_histogram": dict(sorted(include_reasons.items())),
        "reject_reason_histogram": dict(sorted(reject_reasons.items())),
        "neighborhood_symbols": sorted(neighborhood_syms),
        "connector_symbols": sorted(connector_syms),
    }
    return selected, funnel


def compute_expansion_to_bridge_funnel(
    *,
    expansion_funnel: Dict[str, Any],
    bridge_input_routes: int,
    bridge_active_routes: int,
    bridge_reject_histogram: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    """Funnel from expansion handoff universe to bridge active routes."""
    return {
        "expansion_handoff_routes": int(
            expansion_funnel.get("graph_handoff_universe_routes")
            or expansion_funnel.get("expansion_handoff_tagged_routes")
            or 0
        ),
        "bridge_input_routes": bridge_input_routes,
        "bridge_active_routes": bridge_active_routes,
        "expansion_to_bridge_loss": max(
            0,
            int(
                expansion_funnel.get("graph_handoff_universe_routes")
                or expansion_funnel.get("expansion_handoff_tagged_routes")
                or 0
            )
            - bridge_active_routes,
        ),
        "expansion_funnel": expansion_funnel,
        "bridge_reject_histogram": dict(bridge_reject_histogram or {}),
    }


def refresh_graph_handoff_in_expansion_doc(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Re-tag routes and refresh summary graph-handoff metrics in-place."""
    routes = list(doc.get("routes_admitted") or [])
    gt, ca, tp, cg, debug = aggregate_graph_handoff_from_routes(routes)
    _universe, funnel = select_graph_handoff_universe_routes(routes, debug)
    summary = doc.setdefault("summary", {})
    mirror_ready = int(summary.get("mirror_quote_ready_tokens") or 0)
    if mirror_ready > 0:
        handoff_lane = "mirror_2leg"
    elif gt > 0:
        handoff_lane = "graph_topology"
    else:
        handoff_lane = "none"

    summary["graph_topology_ready_tokens"] = gt
    summary["cross_anchor_ready_tokens"] = ca
    summary["token_presence_graph_ready_tokens"] = tp
    summary["connector_graph_ready_tokens"] = cg
    summary["graph_topology_ready_debug"] = debug
    summary["two_leg_mirror_ready_tokens"] = mirror_ready
    summary["graph_handoff_ready_tokens"] = gt
    summary["graph_handoff_cycle_potential_routes"] = funnel[
        "graph_handoff_cycle_potential_routes"
    ]
    summary["handoff_funnel"] = funnel
    summary["handoff_lane"] = handoff_lane
    summary["handoff_ready"] = bool(mirror_ready > 0 or gt > 0)
    doc["routes_admitted"] = routes
    doc["graph_handoff"] = {
        "graph_topology_ready_tokens": gt,
        "cross_anchor_ready_tokens": ca,
        "token_presence_graph_ready_tokens": tp,
        "connector_graph_ready_tokens": cg,
        "graph_handoff_cycle_potential_routes": funnel[
            "graph_handoff_cycle_potential_routes"
        ],
        "handoff_lane": handoff_lane,
        "handoff_ready": summary["handoff_ready"],
        "requires_m9_quote": gt > 0,
        "economics_claim": False,
        "handoff_funnel": funnel,
    }
    doc["handoff_ready"] = summary["handoff_ready"]
    doc["handoff_lane"] = handoff_lane
    return {
        "graph_topology_ready_tokens": gt,
        "cross_anchor_ready_tokens": ca,
        "token_presence_graph_ready_tokens": tp,
        "connector_graph_ready_tokens": cg,
        "graph_handoff_cycle_potential_routes": funnel[
            "graph_handoff_cycle_potential_routes"
        ],
        "handoff_lane": handoff_lane,
        "handoff_funnel": funnel,
        "graph_topology_ready_debug": debug,
    }


def apply_bridge_handoff_metadata(route: Dict[str, Any]) -> Dict[str, Any]:
    """Ensure M9 bridge routes carry graph-handoff flags from M8.2 expansion."""
    kind = str(route.get("expansion_route_kind") or "")
    lane = str(route.get("handoff_lane") or "")
    if kind in _GRAPH_ROUTE_KINDS or lane == "graph_topology":
        route["requires_quote_validation"] = True
        route["economics_claim"] = False
        route.setdefault("handoff_lane", "graph_topology")
    elif kind == "same_pair_mirror":
        route.setdefault("handoff_lane", "mirror_2leg")
    return route
