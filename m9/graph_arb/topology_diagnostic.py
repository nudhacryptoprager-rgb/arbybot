"""M9 graph topology diagnostic helpers (components, cycle potential, edge loss)."""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Set, Tuple

from m9.graph_arb.builder import (
    build_graph_from_inventory,
    get_last_graph_build_stats,
    graph_edge_count,
    graph_route_count,
    graph_token_count,
)
from m9.graph_arb.finder import find_cycles
from m9.graph_arb.models import GraphEdge

_DEFAULT_ANCHORS = frozenset(
    {"WETH", "USDC", "USDbC", "DAI", "EURC", "cbBTC", "USDT", "WETH_BASE", "cbETH"}
)

_HISTOGRAM_ALIASES = {
    "unknown_token": "UNKNOWN_TOKEN",
    "decimals_unknown": "DECIMALS_UNKNOWN",
    "not_factory_verified": "NOT_FACTORY_VERIFIED",
    "productive_admission_fail": "PRODUCTIVE_ADMISSION_FAIL",
    "missing_depth_or_quote_ok": "PRODUCTIVE_ADMISSION_FAIL",
    "no_edge_built": "NO_EDGE_BUILT",
    "metadata_incomplete": "METADATA_INCOMPLETE",
    "invalid_pair_id": "INVALID_PAIR_ID",
    "invalid_token_address": "INVALID_TOKEN_ADDRESS",
    "curve_unindexed": "CURVE_UNINDEXED",
    "unknown_price": "UNKNOWN_PRICE",
}


def _normalize_histogram(raw: Dict[str, int]) -> Dict[str, int]:
    out: Counter[str] = Counter()
    for key, count in (raw or {}).items():
        out[_HISTOGRAM_ALIASES.get(key, key.upper())] += int(count or 0)
    return dict(sorted(out.items()))


def _all_tokens(adjacency: Dict[str, Dict[str, List[GraphEdge]]]) -> Set[str]:
    tokens: Set[str] = set(adjacency.keys())
    for neighbors in adjacency.values():
        tokens.update(neighbors.keys())
    return tokens


def _degree_maps(
    adjacency: Dict[str, Dict[str, List[GraphEdge]]],
) -> Tuple[Dict[str, int], Dict[str, int]]:
    out_degree: Dict[str, int] = defaultdict(int)
    in_degree: Dict[str, int] = defaultdict(int)
    for src, neighbors in adjacency.items():
        for dst, edges in neighbors.items():
            out_degree[src] += len(edges)
            in_degree[dst] += len(edges)
    for token in _all_tokens(adjacency):
        out_degree.setdefault(token, 0)
        in_degree.setdefault(token, 0)
    return dict(out_degree), dict(in_degree)


def _degree_entries(degree_map: Dict[str, int]) -> List[Dict[str, Any]]:
    return [
        {"token": token, "degree": degree}
        for token, degree in sorted(degree_map.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


def weak_components(
    adjacency: Dict[str, Dict[str, List[GraphEdge]]],
) -> List[List[str]]:
    """Undirected connected components."""
    tokens = sorted(_all_tokens(adjacency))
    if not tokens:
        return []
    adj_undir: Dict[str, Set[str]] = defaultdict(set)
    for src, neighbors in adjacency.items():
        for dst in neighbors:
            adj_undir[src].add(dst)
            adj_undir[dst].add(src)
    for t in tokens:
        adj_undir.setdefault(t, set())

    seen: Set[str] = set()
    components: List[List[str]] = []
    for start in tokens:
        if start in seen:
            continue
        stack = [start]
        comp: List[str] = []
        seen.add(start)
        while stack:
            cur = stack.pop()
            comp.append(cur)
            for nbr in adj_undir.get(cur, ()):
                if nbr not in seen:
                    seen.add(nbr)
                    stack.append(nbr)
        components.append(sorted(comp))
    components.sort(key=lambda c: (-len(c), c[0] if c else ""))
    return components


def strong_components(
    adjacency: Dict[str, Dict[str, List[GraphEdge]]],
) -> List[List[str]]:
    """Kosaraju strongly connected components."""
    tokens = sorted(_all_tokens(adjacency))
    if not tokens:
        return []

    adj: Dict[str, Set[str]] = defaultdict(set)
    radj: Dict[str, Set[str]] = defaultdict(set)
    for src, neighbors in adjacency.items():
        for dst in neighbors:
            adj[src].add(dst)
            radj[dst].add(src)
    for t in tokens:
        adj.setdefault(t, set())
        radj.setdefault(t, set())

    order: List[str] = []
    seen: Set[str] = set()

    def dfs1(node: str) -> None:
        stack = [(node, False)]
        while stack:
            cur, done = stack.pop()
            if done:
                order.append(cur)
                continue
            if cur in seen:
                continue
            seen.add(cur)
            stack.append((cur, True))
            for nbr in sorted(adj.get(cur, ())):
                if nbr not in seen:
                    stack.append((nbr, False))

    for t in tokens:
        if t not in seen:
            dfs1(t)

    comps: List[List[str]] = []
    seen2: Set[str] = set()

    def dfs2(node: str, comp: List[str]) -> None:
        stack = [node]
        while stack:
            cur = stack.pop()
            if cur in seen2:
                continue
            seen2.add(cur)
            comp.append(cur)
            for nbr in sorted(radj.get(cur, ())):
                if nbr not in seen2:
                    stack.append(nbr)

    for t in reversed(order):
        if t not in seen2:
            comp: List[str] = []
            dfs2(t, comp)
            comps.append(sorted(comp))
    comps.sort(key=lambda c: (-len(c), c[0] if c else ""))
    return comps


def missing_reverse_pairs(
    adjacency: Dict[str, Dict[str, List[GraphEdge]]],
) -> List[Dict[str, str]]:
    """Directed token pairs with forward edge but no reverse edge."""
    missing: List[Dict[str, str]] = []
    for src, neighbors in adjacency.items():
        for dst in neighbors:
            if dst not in adjacency or src not in adjacency.get(dst, {}):
                missing.append({"from": src, "to": dst})
    missing.sort(key=lambda r: (r["from"], r["to"]))
    return missing


def _routes_producing_edges(
    adjacency: Dict[str, Dict[str, List[GraphEdge]]],
) -> Dict[str, Dict[str, Any]]:
    by_route: Dict[str, Dict[str, Any]] = {}
    for src, neighbors in adjacency.items():
        for dst, edges in neighbors.items():
            for edge in edges:
                row = by_route.setdefault(
                    edge.route_id,
                    {
                        "route_id": edge.route_id,
                        "pair_id": edge.pair_id,
                        "dex_id": edge.dex_id,
                        "pool_address": edge.pool_address,
                        "directions": set(),
                    },
                )
                row["directions"].add(f"{src}->{dst}")
    return by_route


def routes_in_graph_but_no_cycle_potential(
    adjacency: Dict[str, Dict[str, List[GraphEdge]]],
    *,
    cycle_lengths: Tuple[int, ...] = (2, 3, 4),
) -> List[Dict[str, Any]]:
    """Routes whose endpoints sit in components with zero cycles of requested lengths."""
    wcomps = weak_components(adjacency)
    comp_by_token: Dict[str, int] = {}
    for idx, comp in enumerate(wcomps):
        for tok in comp:
            comp_by_token[tok] = idx

    comp_cycles: Dict[int, int] = defaultdict(int)
    for length in cycle_lengths:
        cycles = find_cycles(adjacency, cycle_lengths=(length,), max_cycles=500)
        for cycle in cycles:
            for edge in cycle.edges:
                comp_id = comp_by_token.get(edge.token_in_sym)
                if comp_id is not None:
                    comp_cycles[comp_id] += 1

    blocked: List[Dict[str, Any]] = []
    for route_id, info in _routes_producing_edges(adjacency).items():
        tokens = set()
        for direction in info["directions"]:
            a, b = direction.split("->", 1)
            tokens.update((a, b))
        comp_ids = {comp_by_token.get(t) for t in tokens if t in comp_by_token}
        if comp_ids and all(comp_cycles.get(cid, 0) == 0 for cid in comp_ids if cid is not None):
            blocked.append(
                {
                    "route_id": route_id,
                    "pair_id": info["pair_id"],
                    "dex_id": info["dex_id"],
                    "pool_address": info["pool_address"],
                    "weak_component_size": max(
                        len(wcomps[cid]) for cid in comp_ids if cid is not None
                    ),
                    "directions": sorted(info["directions"]),
                }
            )
    blocked.sort(key=lambda r: r["route_id"])
    return blocked[:64]


def count_cycles_by_length(
    adjacency: Dict[str, Dict[str, List[GraphEdge]]],
    cycle_lengths: Tuple[int, ...],
    *,
    max_cycles: int = 5000,
) -> Dict[str, Any]:
    by_length: Dict[str, int] = {}
    all_cycles: List[Any] = []
    seen_ids: Set[str] = set()
    for length in cycle_lengths:
        found = find_cycles(
            adjacency, cycle_lengths=(length,), max_cycles=max_cycles
        )
        by_length[str(length)] = len(found)
        for cycle in found:
            if cycle.cycle_id not in seen_ids:
                seen_ids.add(cycle.cycle_id)
                all_cycles.append(cycle)
    return {
        "cycles_by_length": by_length,
        "cycles_found_topology": len(all_cycles),
        "cycles_found_topology_total": len(all_cycles),
    }


def summarize_topology(
    adjacency: Dict[str, Dict[str, List[GraphEdge]]],
    *,
    anchor_tokens: Optional[Set[str]] = None,
    cycle_lengths: Tuple[int, ...] = (2, 3, 4),
) -> Dict[str, Any]:
    anchors = anchor_tokens or set(_DEFAULT_ANCHORS)
    out_deg, in_deg = _degree_maps(adjacency)
    wcomps = weak_components(adjacency)
    scomps = strong_components(adjacency)
    cycle_stats = count_cycles_by_length(adjacency, cycle_lengths)

    isolated_anchors = sorted(
        a
        for a in anchors
        if a in _all_tokens(adjacency)
        and out_deg.get(a, 0) == 0
        and in_deg.get(a, 0) == 0
    )
    anchor_touch = sorted(
        a
        for a in anchors
        if a in _all_tokens(adjacency)
        and (out_deg.get(a, 0) > 0 or in_deg.get(a, 0) > 0)
    )

    missing_rev = missing_reverse_pairs(adjacency)
    scc_multi = [c for c in scomps if len(c) > 1]
    return {
        "token_count": graph_token_count(adjacency),
        "unique_tokens": len(_all_tokens(adjacency)),
        "directed_edge_count": graph_edge_count(adjacency),
        "unique_routes_in_graph": graph_route_count(adjacency),
        "out_degree": _degree_entries(out_deg),
        "in_degree": _degree_entries(in_deg),
        "weak_component_count": len(wcomps),
        "weak_components_top": wcomps[:8],
        "strong_component_count": len(scomps),
        "strong_components_multi_node": scc_multi[:8],
        "strong_components_size_histogram": dict(
            Counter(len(c) for c in scomps).most_common()
        ),
        "isolated_anchor_tokens": isolated_anchors,
        "anchor_tokens_with_edges": anchor_touch,
        "missing_reverse_edge_pairs": missing_rev[:32],
        "missing_reverse_edge_count": len(missing_rev),
        **cycle_stats,
        "routes_in_graph_no_local_cycles": routes_in_graph_but_no_cycle_potential(
            adjacency, cycle_lengths=cycle_lengths
        ),
    }


def run_topology_diagnostic(
    *,
    inventory_path: str,
    config_path: str = "config/exotic_base_anchor.yaml",
    cycle_lengths: Tuple[int, ...] = (2, 3, 4),
    lanes: Tuple[str, ...] = ("discovery", "productive"),
    expansion_path: Optional[str] = None,
    bridge_inventory_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Full topology diagnostic for an M9 bridge inventory artifact."""
    import json
    from pathlib import Path

    inv_path = Path(inventory_path)
    with inv_path.open(encoding="utf-8") as fh:
        inventory = json.load(fh)
    active_routes = list(inventory.get("active_routes") or [])
    dex_hist = Counter(str(r.get("dex_id") or "unknown") for r in active_routes)

    lane_reports: Dict[str, Any] = {}
    for lane in lanes:
        adjacency = build_graph_from_inventory(
            inventory_path=inventory_path,
            config_path=config_path,
            lane=lane,
            require_factory_verified=(lane == "productive"),
            diagnostic_admission_mode="topology_probe" if lane == "productive" else None,
        )
        build_stats = get_last_graph_build_stats()
        admission = _normalize_histogram(build_stats.get("admission_skip_histogram"))
        edge_loss = _normalize_histogram(build_stats.get("edge_build_skip_histogram"))
        missing_rev = summarize_topology(adjacency, cycle_lengths=cycle_lengths)[
            "missing_reverse_edge_count"
        ]
        edge_loss["NO_REVERSE_EDGE"] = missing_rev

        topo = summarize_topology(adjacency, cycle_lengths=cycle_lengths)
        lane_reports[lane] = {
            "topology": topo,
            "graph_build_stats": {
                "routes_inventory": build_stats.get("routes_inventory"),
                "routes_after_admission": build_stats.get("routes_after_admission"),
                "edges_built": build_stats.get("edges_built"),
                "admission_skip_histogram": admission,
                "edge_loss_histogram": edge_loss,
                "post_admission_no_edge_samples": build_stats.get(
                    "post_admission_no_edge_samples"
                ),
            },
            "active_routes_to_edges": {
                "active_routes": len(active_routes),
                "expected_directed_edges_max": len(active_routes) * 2,
                "directed_edges_built": topo["directed_edge_count"],
                "unique_routes_in_graph": topo["unique_routes_in_graph"],
                "routes_lost": max(
                    0, len(active_routes) - topo["unique_routes_in_graph"]
                ),
            },
        }

    productive_cycles = int(
        lane_reports.get("productive", {}).get("topology", {}).get(
            "cycles_found_topology_total", 0
        )
        or 0
    )
    discovery_cycles = int(
        lane_reports.get("discovery", {}).get("topology", {}).get(
            "cycles_found_topology_total", 0
        )
        or 0
    )
    runner_cycle_lengths_note = (
        "M9 runner default config uses cycle_lengths (3,4); "
        "set ARBY_M9_CYCLE_LENGTHS=2,3,4 for graph-handoff validation."
    )

    expansion_compare: Optional[Dict[str, Any]] = None
    if expansion_path and bridge_inventory_path:
        import json as _json
        from pathlib import Path as _Path

        with _Path(expansion_path).open(encoding="utf-8") as _efh:
            _exp_doc = _json.load(_efh)
        with _Path(bridge_inventory_path).open(encoding="utf-8") as _bfh:
            _br_doc = _json.load(_bfh)
        expansion_compare = compare_expansion_vs_bridge_cycles(
            expansion_routes=list(_exp_doc.get("routes_admitted") or []),
            bridge_routes=list(_br_doc.get("active_routes") or []),
            config_path=config_path,
            cycle_lengths=cycle_lengths,
            lane="discovery",
        )

    blocker_hint = "UPSTREAM_OK_BUT_NO_CYCLES"
    if expansion_compare:
        if expansion_compare.get("bridge_cycles_3_4_present"):
            blocker_hint = "TOPOLOGY_CYCLES_PRESENT"
        elif expansion_compare.get("full_expansion_cycles_3_4_present"):
            blocker_hint = "GRAPH_HANDOFF_SELECTION_DROPS_3_4_CLOSURE"
    elif productive_cycles > 0:
        blocker_hint = "TOPOLOGY_CYCLES_PRESENT"

    return {
        "schema_version": "m9_graph_topology_diagnostic.2",
        "inventory_path": str(inv_path),
        "active_routes_count": len(active_routes),
        "active_routes_by_dex": dict(dex_hist.most_common()),
        "m8_2_handoff_ready": inventory.get("m8_2_handoff_ready")
        or (inventory.get("bridge_source_metrics") or {}).get("m8_2_handoff_ready"),
        "m8_2_handoff_lane": inventory.get("m8_2_handoff_lane")
        or (inventory.get("bridge_source_metrics") or {}).get("m8_2_handoff_lane"),
        "cycle_lengths": list(cycle_lengths),
        "lanes": lane_reports,
        "cycles_found_topology": max(productive_cycles, discovery_cycles),
        "cycles_found_topology_productive": productive_cycles,
        "cycles_found_topology_discovery": discovery_cycles,
        "runner_cycle_lengths_note": runner_cycle_lengths_note,
        "expansion_vs_bridge": expansion_compare,
        "blocker_hint": blocker_hint,
    }


def quick_cycle_count(
    inventory_path: str,
    *,
    config_path: str = "config/exotic_base_anchor.yaml",
    cycle_lengths: Tuple[int, ...] = (2, 3, 4),
    lane: str = "discovery",
) -> int:
    """Lightweight cycle count for bridge funnel metrics."""
    adjacency = build_graph_from_inventory(
        inventory_path=inventory_path,
        config_path=config_path,
        lane=lane,
        require_factory_verified=False,
    )
    if not adjacency:
        return 0
    return int(
        count_cycles_by_length(adjacency, cycle_lengths).get(
            "cycles_found_topology_total", 0
        )
    )


def _write_temp_inventory(routes: List[Dict[str, Any]]) -> str:
    import json
    import os
    import tempfile

    fd, path = tempfile.mkstemp(suffix=".json", prefix="m9_topo_inv_")
    os.close(fd)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"active_routes": routes}, fh, ensure_ascii=False)
    return path


def collect_cycle_route_ids_from_routes(
    routes: List[Dict[str, Any]],
    *,
    config_path: str = "config/exotic_base_anchor.yaml",
    cycle_lengths: Tuple[int, ...] = (2, 3, 4),
    lane: str = "discovery",
    max_cycles: int = 8000,
) -> Tuple[Set[str], Dict[str, int]]:
    """Return route_ids participating in cycles + counts by length."""
    import os

    from m9.graph_arb.node_canonical import normalize_expansion_route_tokens

    if not routes:
        return set(), {str(n): 0 for n in cycle_lengths}

    normalized = [normalize_expansion_route_tokens(dict(r)) for r in routes]
    path = _write_temp_inventory(normalized)
    try:
        adjacency = build_graph_from_inventory(
            inventory_path=path,
            config_path=config_path,
            lane=lane,
            require_factory_verified=False,
            diagnostic_admission_mode=(
                "topology_probe" if lane == "productive" else None
            ),
        )
        if not adjacency:
            return set(), {str(n): 0 for n in cycle_lengths}
        stats = count_cycles_by_length(
            adjacency, cycle_lengths, max_cycles=max_cycles
        )
        route_ids: Set[str] = set()
        for length in cycle_lengths:
            for cycle in find_cycles(
                adjacency, cycle_lengths=(length,), max_cycles=max_cycles
            ):
                for edge in cycle.edges:
                    route_ids.add(edge.route_id)
        return route_ids, dict(stats.get("cycles_by_length") or {})
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def compare_expansion_vs_bridge_cycles(
    *,
    expansion_routes: List[Dict[str, Any]],
    bridge_routes: List[Dict[str, Any]],
    config_path: str = "config/exotic_base_anchor.yaml",
    cycle_lengths: Tuple[int, ...] = (2, 3, 4),
    lane: str = "discovery",
) -> Dict[str, Any]:
    """Compare cycle counts full expansion vs bridge-selected routes."""
    full_ids_34, before_34 = collect_cycle_route_ids_from_routes(
        expansion_routes,
        config_path=config_path,
        cycle_lengths=(3, 4),
        lane=lane,
    )
    full_ids_all, before_all = collect_cycle_route_ids_from_routes(
        expansion_routes,
        config_path=config_path,
        cycle_lengths=cycle_lengths,
        lane=lane,
    )
    bridge_ids_34, after_34 = collect_cycle_route_ids_from_routes(
        bridge_routes,
        config_path=config_path,
        cycle_lengths=(3, 4),
        lane=lane,
    )
    bridge_ids_all, after_all = collect_cycle_route_ids_from_routes(
        bridge_routes,
        config_path=config_path,
        cycle_lengths=cycle_lengths,
        lane=lane,
    )
    bridge_route_ids = {
        str(r.get("route_id") or "") for r in bridge_routes if r.get("route_id")
    }
    lost_34 = sorted(full_ids_34 - bridge_route_ids)[:48]
    cycles_lost_34 = {
        str(k): int(before_34.get(str(k), 0)) - int(after_34.get(str(k), 0))
        for k in (3, 4)
    }
    cycles_lost_all = {
        str(k): int(before_all.get(str(k), 0)) - int(after_all.get(str(k), 0))
        for k in cycle_lengths
    }
    return {
        "full_expansion_routes": len(expansion_routes),
        "bridge_active_routes": len(bridge_routes),
        "cycles_by_length_before_bridge": before_all,
        "cycles_by_length_after_bridge": after_all,
        "cycles_by_length_3_4_before_bridge": before_34,
        "cycles_by_length_3_4_after_bridge": after_34,
        "cycles_lost_by_bridge_selection": cycles_lost_all,
        "cycles_lost_3_4_by_bridge_selection": cycles_lost_34,
        "full_expansion_cycles_3_4_present": any(
            int(before_34.get(str(k), 0)) > 0 for k in (3, 4)
        ),
        "bridge_cycles_3_4_present": any(
            int(after_34.get(str(k), 0)) > 0 for k in (3, 4)
        ),
        "routes_causing_cycle_loss": lost_34,
        "routes_causing_cycle_loss_count": len(full_ids_34 - bridge_route_ids),
    }
