"""Cycle-finding and topology analysis for the M9 token exchange graph."""
from __future__ import annotations

from typing import Dict, List, Optional, Set

from m9.graph_arb.models import GraphCycle, GraphEdge, GraphTopology

_MAX_CYCLES_PER_START = 500
_MAX_EDGES_PER_DIRECTION = 8

_FACTORY_ORDER = {"EFFICIENT_BASELINE": 0, "MID_EFFICIENCY": 1, "LOW_EFFICIENCY": 2}

# Prefer exotic / long-tail adapter families when fee and factory class tie.
_ADAPTER_PRIORITY = {
    "uniswap_v4": 0,
    "uniswap_v2": 1,
    "ve33": 2,
    "aerodrome_v2_stable": 2,
    "curve_stable": 3,
    "uniswap_v3": 4,
}


def _edge_rank_key(edge: GraphEdge) -> tuple:
    """Deterministic expansion rank: lower fee/factory cost first, then adapter family."""
    fc = _FACTORY_ORDER.get(edge.factory_class, 99)
    ap = _ADAPTER_PRIORITY.get(edge.adapter_type, 50)
    return (edge.fee_bps, fc, ap, edge.route_id)


def _ranked_neighbor_items(
    neighbors: "Dict[str, List[GraphEdge]]",
) -> List[tuple[str, List[GraphEdge]]]:
    """Rank neighbors by best outgoing edge, then cap per direction."""
    ranked: List[tuple[str, List[GraphEdge], tuple]] = []
    for next_token, edges in neighbors.items():
        if not edges:
            continue
        sorted_edges = sorted(edges, key=_edge_rank_key)[:_MAX_EDGES_PER_DIRECTION]
        ranked.append((next_token, sorted_edges, _edge_rank_key(sorted_edges[0])))
    ranked.sort(key=lambda item: (item[2], item[0]))
    return [(token, edge_list) for token, edge_list, _ in ranked[:_MAX_EDGES_PER_DIRECTION]]


def find_cycles(
    adjacency: "Dict[str, Dict[str, List[GraphEdge]]]",
    cycle_lengths: "tuple[int, ...]" = (3, 4),
    anchor_tokens: Optional[Set[str]] = None,
    max_cycles: int = 5000,
    exclude_factory_classes: Optional[Set[str]] = None,
) -> List[GraphCycle]:
    """Find all simple cycles of the given lengths in the graph.

    Uses DFS from each token. Returns deduplicated cycles sorted by
    cycle_id to ensure determinism.
    """
    cycles: List[GraphCycle] = []
    seen_ids: Set[str] = set()
    max_length = max(cycle_lengths) if cycle_lengths else 4

    start_tokens = list(adjacency.keys())
    if anchor_tokens:
        # Prioritise anchor tokens as start points
        start_tokens = sorted(
            start_tokens,
            key=lambda t: (0 if t in anchor_tokens else 1, t),
        )

    for start in start_tokens:
        if len(cycles) >= max_cycles:
            break
        _dfs_cycles(
            start_token=start,
            adjacency=adjacency,
            cycle_lengths=cycle_lengths,
            max_length=max_length,
            anchor_tokens=anchor_tokens,
            exclude_factory_classes=exclude_factory_classes,
            path_tokens=[start],
            path_edges=[],
            cycles=cycles,
            seen_ids=seen_ids,
            max_cycles=max_cycles,
        )

    return cycles


def _dfs_cycles(
    start_token: str,
    adjacency: "Dict[str, Dict[str, List[GraphEdge]]]",
    cycle_lengths: "tuple[int, ...]",
    max_length: int,
    anchor_tokens: Optional[Set[str]],
    exclude_factory_classes: Optional[Set[str]],
    path_tokens: List[str],
    path_edges: List[GraphEdge],
    cycles: List[GraphCycle],
    seen_ids: Set[str],
    max_cycles: int,
) -> None:
    if len(cycles) >= max_cycles:
        return

    current = path_tokens[-1]
    depth = len(path_edges)

    if depth >= max_length:
        return

    neighbors = adjacency.get(current, {})
    neighbor_items = _ranked_neighbor_items(neighbors)

    for next_token, candidate_edges in neighbor_items:
        for edge in candidate_edges:
            if exclude_factory_classes and edge.factory_class in exclude_factory_classes:
                continue

            if next_token == start_token and depth + 1 in cycle_lengths:
                # Found a valid cycle
                # 2-leg guard: a direct A->B->A loop is only an arbitrage
                # when the closing hop uses a DIFFERENT pool than the opening
                # hop. Same-pool round-trips are guaranteed fee losses; skip
                # them before constructing the cycle (the model rejects them
                # anyway, but skipping avoids the exception churn).
                if depth + 1 == 2 and path_edges:
                    if edge.pool_address.lower() == path_edges[0].pool_address.lower():
                        continue
                cycle_edges = tuple(path_edges + [edge])
                try:
                    cycle = GraphCycle(edges=cycle_edges)
                except ValueError:
                    continue
                cid = cycle.cycle_id
                if cid not in seen_ids:
                    seen_ids.add(cid)
                    cycles.append(cycle)
                    if len(cycles) >= max_cycles:
                        return

            elif next_token not in path_tokens and depth + 1 < max_length:
                # Continue DFS. Exclude the start token (path_tokens[0]) too:
                # it may only be used to CLOSE the cycle (handled above), never
                # revisited as an interior node. Allowing an interior revisit of
                # the start produced non-simple "figure-8" cycles such as
                # WETH->XCHAT->WETH->AERO->WETH (two concatenated round-trips),
                # which surface as low-grade asymmetry phantoms.
                _dfs_cycles(
                    start_token=start_token,
                    adjacency=adjacency,
                    cycle_lengths=cycle_lengths,
                    max_length=max_length,
                    anchor_tokens=anchor_tokens,
                    exclude_factory_classes=exclude_factory_classes,
                    path_tokens=path_tokens + [next_token],
                    path_edges=path_edges + [edge],
                    cycles=cycles,
                    seen_ids=seen_ids,
                    max_cycles=max_cycles,
                )
                if len(cycles) >= max_cycles:
                    return


def analyze_topology(
    adjacency: "Dict[str, Dict[str, List[GraphEdge]]]",
    cycles: List[GraphCycle],
) -> GraphTopology:
    """Analyze graph structure: identify hubs, dead-ends, and missing edges."""
    token_count = len(adjacency)

    # Count edges per token
    out_degree: Dict[str, int] = {}
    in_degree: Dict[str, int] = {}
    for token, neighbors in adjacency.items():
        out_deg = sum(len(edges) for edges in neighbors.values())
        out_degree[token] = out_deg

    for token, neighbors in adjacency.items():
        for neighbor in neighbors:
            in_degree[neighbor] = in_degree.get(neighbor, 0) + 1

    # Hubs: tokens with high connectivity (>= 3 neighbors)
    hub_tokens = sorted(
        [t for t, deg in out_degree.items() if deg >= 3],
        key=lambda t: -out_degree[t],
    )[:10]

    # Dead ends: tokens with only 1 neighbor in or out
    dead_end_tokens = [
        t for t in adjacency
        if out_degree.get(t, 0) <= 1 or in_degree.get(t, 0) <= 1
    ][:20]

    # Missing edges for 3-cycle: tokens that are connected to a hub but not to each other
    missing_edges: List[Dict] = []
    if hub_tokens:
        hub = hub_tokens[0]
        hub_neighbors = set(adjacency.get(hub, {}).keys())
        for n1 in list(hub_neighbors)[:5]:
            for n2 in list(hub_neighbors)[:5]:
                if n1 != n2:
                    if n2 not in adjacency.get(n1, {}):
                        missing_edges.append({"from": n1, "to": n2, "via_hub": hub})
                if len(missing_edges) >= 10:
                    break
            if len(missing_edges) >= 10:
                break

    # Adjacency summary (top tokens)
    adjacency_summary: Dict[str, List[str]] = {}
    for token in hub_tokens[:5]:
        adjacency_summary[token] = list(adjacency.get(token, {}).keys())[:10]

    edge_count = sum(
        len(edges)
        for adj in adjacency.values()
        for edges in adj.values()
    )
    route_ids: Set[str] = set()
    for adj in adjacency.values():
        for edges in adj.values():
            for e in edges:
                route_ids.add(e.route_id)

    return GraphTopology(
        token_count=token_count,
        edge_count=edge_count,
        route_count=len(route_ids),
        hub_tokens=hub_tokens,
        dead_end_tokens=dead_end_tokens,
        missing_edges_for_3cycle=missing_edges,
        adjacency_summary=adjacency_summary,
    )


def rank_cycles(cycles: List[GraphCycle]) -> List[GraphCycle]:
    """Sort cycles: lower total_fee_bps first, then better min_factory_class."""
    factory_order = {"EFFICIENT_BASELINE": 0, "MID_EFFICIENCY": 1, "LOW_EFFICIENCY": 2}

    def sort_key(c: GraphCycle) -> "tuple[float, int, str]":
        fc_score = factory_order.get(c.min_factory_class, 99)
        return (c.total_fee_bps, fc_score, c.cycle_id)

    return sorted(cycles, key=sort_key)
