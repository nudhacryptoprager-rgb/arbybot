"""Cycle-level usable capacity diagnostics (depth × per-DEX fraction)."""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from m9.graph_arb.adapter_families import route_family
from m9.graph_arb.finder import find_cycles
from m9.graph_arb.models import GraphCycle, GraphEdge
from m9.graph_arb.per_dex_sizing import depth_fraction_for_family
from m9.graph_arb.size_truth import (
    economic_size_floor_for_profile,
    economics_profile_specs,
    load_cost_model,
    resolve_active_economics_profile_name,
)

DEFAULT_CAPACITY_FLOORS_USD: Tuple[float, ...] = (25.0, 50.0, 100.0, 180.0)

_ECON_GATE_ONLY_STATUSES = frozenset(
    {
        "DEPTH_BELOW_ECONOMICS_FLOOR",
        "DEPTH_UNRESOLVED",
        "LEG_CAPACITY_REJECT",
    }
)


def edge_usable_capacity_usd(edge: GraphEdge) -> Optional[float]:
    """Per-leg quoteable notional: ``effective_depth_usd * family_fraction``."""
    depth = edge.effective_depth_usd
    if depth is None or not isinstance(depth, (int, float)) or float(depth) <= 0:
        return None
    family = route_family(
        {
            "dex_id": edge.dex_id,
            "adapter_type": edge.adapter_type,
        }
    )
    frac = depth_fraction_for_family(
        family,
        depth_probe_status=getattr(edge, "depth_probe_status", None),
    )
    return round(float(depth) * float(frac), 4)


def cycle_bottleneck_usable_capacity_usd(cycle: GraphCycle) -> Optional[float]:
    """Minimum per-leg usable capacity; None when any leg lacks measured depth."""
    usables: List[float] = []
    for edge in cycle.edges:
        leg_usable = edge_usable_capacity_usd(edge)
        if leg_usable is None:
            return None
        usables.append(leg_usable)
    return min(usables) if usables else None


def cycle_meets_usable_floor(cycle: GraphCycle, floor_usd: float) -> bool:
    usable = cycle_bottleneck_usable_capacity_usd(cycle)
    return usable is not None and usable >= float(floor_usd)


def count_cycles_by_usable_capacity(
    cycles: Iterable[GraphCycle],
    floors_usd: Sequence[float],
) -> Dict[str, int]:
    """Count cycles whose bottleneck usable capacity meets each floor."""
    floors = tuple(float(f) for f in floors_usd)
    counts = {str(int(f) if f == int(f) else f): 0 for f in floors}
    for cycle in cycles:
        usable = cycle_bottleneck_usable_capacity_usd(cycle)
        if usable is None:
            continue
        for floor in floors:
            if usable >= floor:
                key = str(int(floor) if floor == int(floor) else floor)
                counts[key] = counts.get(key, 0) + 1
    return counts


def count_cycles_by_profile(
    cycles: Iterable[GraphCycle],
    cost_model: Optional[Dict[str, Any]] = None,
    *,
    config_path: str = "config/exotic_base_anchor.yaml",
) -> Dict[str, Dict[str, Any]]:
    """Count cycles meeting each named economics profile floor."""
    specs = economics_profile_specs(cost_model, config_path=config_path)
    cycle_list = list(cycles)
    out: Dict[str, Dict[str, Any]] = {}
    for name, spec in specs.items():
        floor = float(spec["economics_floor_usd"])
        count = sum(1 for c in cycle_list if cycle_meets_usable_floor(c, floor))
        out[name] = {
            "economics_floor_usd": floor,
            "cycles_at_floor": count,
            "profit_claim_allowed": bool(spec.get("profit_claim_allowed", True)),
            "role": spec.get("role", "production"),
        }
    return out


def near_econ_candidate_cycles(
    cycles: Iterable[GraphCycle],
    *,
    near_floors_usd: Sequence[float] = (25.0, 50.0),
) -> List[Dict[str, Any]]:
    """Cycles qualifying at diagnostic near floors (no production profit claim)."""
    rows: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for floor in near_floors_usd:
        for cycle in cycles:
            if not cycle_meets_usable_floor(cycle, float(floor)):
                continue
            if cycle.cycle_id in seen:
                continue
            seen.add(cycle.cycle_id)
            leg_caps = []
            for edge in cycle.edges:
                leg_caps.append(
                    {
                        "route_id": edge.route_id,
                        "dex_id": edge.dex_id,
                        "adapter_type": edge.adapter_type,
                        "effective_depth_usd": edge.effective_depth_usd,
                        "usable_capacity_usd": edge_usable_capacity_usd(edge),
                    }
                )
            rows.append(
                {
                    "cycle_id": cycle.cycle_id,
                    "length": cycle.length,
                    "token_path": cycle.token_path,
                    "qualifies_at_floor_usd": float(floor),
                    "bottleneck_usable_capacity_usd": cycle_bottleneck_usable_capacity_usd(
                        cycle
                    ),
                    "legs": leg_caps,
                }
            )
    return rows


def enrichment_targets_from_cycles(
    cycles: Iterable[GraphCycle],
    *,
    near_floors_usd: Sequence[float] = (25.0, 50.0, 100.0, 180.0),
) -> Dict[str, Any]:
    """Route targets for targeted decimals/depth enrichment."""
    route_ids: Set[str] = set()
    bottleneck_legs: List[Dict[str, Any]] = []
    for cycle in cycles:
        usable_by_leg: List[Tuple[GraphEdge, Optional[float]]] = []
        for edge in cycle.edges:
            usable_by_leg.append((edge, edge_usable_capacity_usd(edge)))
        if not usable_by_leg:
            continue
        bottleneck_edge, bottleneck_usable = min(
            usable_by_leg,
            key=lambda row: row[1] if row[1] is not None else -1.0,
        )
        cycle_usable = cycle_bottleneck_usable_capacity_usd(cycle)
        if cycle_usable is None:
            for edge, _ in usable_by_leg:
                route_ids.add(edge.route_id)
            bottleneck_legs.append(
                {
                    "route_id": bottleneck_edge.route_id,
                    "dex_id": bottleneck_edge.dex_id,
                    "reason": "unknown_depth_on_bottleneck",
                }
            )
            continue
        if any(float(f) <= cycle_usable for f in near_floors_usd):
            for edge in cycle.edges:
                route_ids.add(edge.route_id)
            bottleneck_legs.append(
                {
                    "route_id": bottleneck_edge.route_id,
                    "dex_id": bottleneck_edge.dex_id,
                    "usable_capacity_usd": bottleneck_usable,
                    "cycle_bottleneck_usd": cycle_usable,
                }
            )
    return {
        "route_ids": sorted(route_ids),
        "route_ids_count": len(route_ids),
        "bottleneck_legs": bottleneck_legs[:64],
    }


def leg_bottleneck_diagnosis(
    edge: GraphEdge,
    *,
    floor_usd: float,
    route_map: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Per-leg capacity diagnosis for RCA (raw depth, family fraction, reason)."""
    raw = edge.effective_depth_usd
    family = route_family(
        {
            "dex_id": edge.dex_id,
            "adapter_type": edge.adapter_type,
        }
    )
    frac = depth_fraction_for_family(
        family,
        depth_probe_status=getattr(edge, "depth_probe_status", None),
    )
    usable = edge_usable_capacity_usd(edge)
    route = (route_map or {}).get(edge.route_id) or {}
    if raw is None:
        reason = "unknown_depth"
    elif route.get("depth_reprobe_required"):
        reason = "false_positive_reprobe_required"
    elif usable is None:
        reason = "unknown_depth"
    elif float(usable) < float(floor_usd):
        reason = "below_floor"
    else:
        reason = "at_or_above_floor"
    return {
        "route_id": edge.route_id,
        "dex_id": edge.dex_id,
        "adapter_type": edge.adapter_type,
        "raw_depth_usd": raw,
        "family_fraction": round(float(frac), 4),
        "usable_depth_usd": usable,
        "reason": reason,
    }


def top_bottleneck_legs(
    cycles: Iterable[GraphCycle],
    *,
    floor_usd: float,
    route_map: Optional[Dict[str, Dict[str, Any]]] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """Aggregate bottleneck legs for cycles below ``floor_usd``."""
    from collections import Counter

    counts: Counter[str] = Counter()
    samples: Dict[str, Dict[str, Any]] = {}
    for cycle in cycles:
        if cycle_meets_usable_floor(cycle, float(floor_usd)):
            continue
        usable_by_leg: List[Tuple[GraphEdge, Optional[float]]] = []
        for edge in cycle.edges:
            usable_by_leg.append((edge, edge_usable_capacity_usd(edge)))
        if not usable_by_leg:
            continue
        bottleneck_edge, _ = min(
            usable_by_leg,
            key=lambda row: row[1] if row[1] is not None else -1.0,
        )
        diag = leg_bottleneck_diagnosis(
            bottleneck_edge,
            floor_usd=float(floor_usd),
            route_map=route_map,
        )
        rid = str(bottleneck_edge.route_id)
        counts[rid] += 1
        if rid not in samples:
            samples[rid] = {
                **diag,
                "cycles_blocked_count": 0,
            }
        samples[rid]["cycles_blocked_count"] = int(counts[rid])
    ranked = sorted(
        samples.values(),
        key=lambda row: (-int(row.get("cycles_blocked_count") or 0), str(row.get("route_id") or "")),
    )
    return ranked[: max(1, int(limit))]


def shadow_gate_blocked(
    capacity_doc: Dict[str, Any],
    *,
    profile_names: Sequence[str] = ("diagnostic_near_econ", "base_realistic", "production_conservative"),
) -> Tuple[bool, str]:
    """Return (blocked, reason) when cycles_total=0 or no profile has cycles_at_floor > 0."""
    if int(capacity_doc.get("cycles_total") or 0) <= 0:
        return True, "M9_CAPACITY_BLOCKED_BY_ZERO_CYCLES_TOTAL"
    by_profile = capacity_doc.get("cycles_by_profile") or {}
    for name in profile_names:
        row = by_profile.get(name) or {}
        if int(row.get("cycles_at_floor") or 0) > 0:
            return False, f"cycles_at_floor>0 profile={name}"
    active = str(capacity_doc.get("active_economics_profile") or "")
    if active:
        row = by_profile.get(active) or {}
        if int(row.get("cycles_at_floor") or 0) > 0:
            return False, f"cycles_at_floor>0 profile={active}"
    if int(capacity_doc.get("cycles_at_production_floor") or 0) > 0:
        return False, "cycles_at_production_floor>0"
    return True, "M9_CAPACITY_BLOCKED_BY_ZERO_CYCLES_AT_FLOOR"


def spread_lifetime_allowed(prior_shadow: Optional[Dict[str, Any]]) -> Tuple[bool, str]:
    """30m spread-lifetime requires prior shadow with cycles_positive_gross > 0."""
    if not prior_shadow:
        return False, "NO_PRIOR_SHADOW_ARTIFACT"
    positive = int(prior_shadow.get("cycles_positive_gross") or 0)
    if positive > 0:
        return True, f"cycles_positive_gross={positive}"
    return False, "SPREAD_LIFETIME_REQUIRES_CYCLES_POSITIVE_GROSS"


def run_productive_four_leg_rca(
    *,
    inventory_path: str,
    config_path: str = "config/exotic_base_anchor.yaml",
    max_cycles: int = 800,
    lost_sample_limit: int = 10,
) -> Dict[str, Any]:
    """Show 4-leg route_ids present in discovery but lost in productive lane."""
    import json
    from collections import Counter
    from pathlib import Path

    from m9.graph_arb.builder import build_graph_from_inventory

    routes_by_id: Dict[str, Dict[str, Any]] = {}
    try:
        inv = json.loads(Path(inventory_path).read_text(encoding="utf-8"))
        for r in inv.get("active_routes") or []:
            rid = str(r.get("route_id") or "")
            if rid:
                routes_by_id[rid] = r
    except Exception:
        pass

    def _four_leg_route_ids(lane: str) -> Tuple[Set[str], int]:
        adj = build_graph_from_inventory(
            inventory_path=inventory_path,
            config_path=config_path,
            lane=lane,
            require_factory_verified=False,
            diagnostic_admission_mode=(
                "topology_probe" if lane == "productive" else None
            ),
        )
        if not adj:
            return set(), 0
        ids: Set[str] = set()
        count = 0
        for cycle in find_cycles(adj, cycle_lengths=(4,), max_cycles=max_cycles):
            count += 1
            for edge in cycle.edges:
                ids.add(edge.route_id)
        return ids, count

    disc_ids, disc_cycles = _four_leg_route_ids("discovery")
    prod_ids, prod_cycles = _four_leg_route_ids("productive")
    lost = sorted(disc_ids - prod_ids)
    kept = sorted(disc_ids & prod_ids)
    family_hist: Counter[str] = Counter()
    reason_hist: Counter[str] = Counter()
    lost_details: List[Dict[str, Any]] = []
    for rid in lost:
        route = routes_by_id.get(rid) or {"route_id": rid, "dex_id": "unknown"}
        fam = _family_bucket(route)
        reason = route_loss_reason(route)
        family_hist[fam] += 1
        reason_hist[reason] += 1
        if len(lost_details) < lost_sample_limit:
            lost_details.append(
                {
                    "route_id": rid,
                    "dex_id": route.get("dex_id"),
                    "adapter_type": route.get("adapter_type"),
                    "family_bucket": fam,
                    "loss_reason": reason,
                }
            )
    return {
        "discovery_four_leg_cycles": disc_cycles,
        "productive_four_leg_cycles": prod_cycles,
        "discovery_route_ids_in_four_leg": len(disc_ids),
        "productive_route_ids_in_four_leg": len(prod_ids),
        "route_ids_lost_in_productive": lost[:128],
        "route_ids_lost_count": len(lost),
        "route_ids_lost_by_family": dict(sorted(family_hist.items())),
        "route_ids_lost_by_reason": dict(sorted(reason_hist.items())),
        "route_ids_lost_sample": lost_details,
        "route_ids_kept_in_productive": kept[:64],
        "route_ids_kept_count": len(kept),
    }


def production_conservative_floor(
    cost_model: Optional[Dict[str, Any]] = None,
    *,
    config_path: str = "config/exotic_base_anchor.yaml",
) -> float:
    cm = cost_model if cost_model is not None else load_cost_model(config_path)
    return economic_size_floor_for_profile(cm, "production_conservative")


def collect_cycles_at_floor(
    adjacency: Dict[str, Dict[str, List[GraphEdge]]],
    *,
    cycle_lengths: Tuple[int, ...],
    floor_usd: float,
    max_cycles: int = 8000,
) -> Tuple[List[GraphCycle], Dict[str, int]]:
    """Find cycles where every leg has usable capacity >= floor_usd."""
    qualified: List[GraphCycle] = []
    seen_ids: Set[str] = set()
    by_length: Dict[str, int] = {str(n): 0 for n in cycle_lengths}
    for length in cycle_lengths:
        for cycle in find_cycles(
            adjacency, cycle_lengths=(length,), max_cycles=max_cycles
        ):
            if not cycle_meets_usable_floor(cycle, floor_usd):
                continue
            if cycle.cycle_id in seen_ids:
                continue
            seen_ids.add(cycle.cycle_id)
            qualified.append(cycle)
            by_length[str(length)] = by_length.get(str(length), 0) + 1
    return qualified, by_length


def route_ids_from_cycles(cycles: Iterable[GraphCycle]) -> Set[str]:
    ids: Set[str] = set()
    for cycle in cycles:
        for edge in cycle.edges:
            ids.add(edge.route_id)
    return ids


def closure_route_ids_for_qualified_cycles(
    adjacency: Dict[str, Dict[str, List[GraphEdge]]],
    qualified_cycles: Iterable[GraphCycle],
    *,
    cycle_lengths: Tuple[int, ...],
    max_cycles: int = 8000,
) -> Set[str]:
    """Expand capacity-qualified routes to minimal productive cycle closure.

    Keeps every route_id from any productive cycle that shares a token with a
    capacity-qualified cycle, so narrow bridges retain builder/admission context.
    """
    qual_tokens: Set[str] = set()
    for cycle in qualified_cycles:
        for edge in cycle.edges:
            qual_tokens.add(edge.token_in_sym)
            qual_tokens.add(edge.token_out_sym)
    if not qual_tokens:
        return set()

    closure_ids: Set[str] = set()
    seen_cycle_ids: Set[str] = set()
    for length in cycle_lengths:
        for cycle in find_cycles(
            adjacency, cycle_lengths=(length,), max_cycles=max_cycles
        ):
            if cycle.cycle_id in seen_cycle_ids:
                continue
            seen_cycle_ids.add(cycle.cycle_id)
            tokens = {e.token_in_sym for e in cycle.edges} | {
                e.token_out_sym for e in cycle.edges
            }
            if tokens & qual_tokens:
                closure_ids.update(route_ids_from_cycles([cycle]))
    return closure_ids


def route_loss_reason(route: Dict[str, Any]) -> str:
    """Classify why a route is absent from productive 4-leg closure."""
    from m9.graph_arb.pool_quality import productive_admission_fail_reason

    if route.get("soft_quarantine_tag") or route.get("hard_quarantine"):
        return "QUARANTINE"
    t0 = route.get("token0_decimals")
    t1 = route.get("token1_decimals")
    if t0 is None or t1 is None:
        return "DECIMALS_UNKNOWN"
    if route.get("effective_depth_usd") is None:
        return "DEPTH_UNKNOWN"
    fail = productive_admission_fail_reason(route)
    if fail:
        key = str(fail).upper()
        if "quote" in key:
            return "QUOTE_SMOKE_FAIL"
        if "depth" in key or fail == "missing_depth":
            return "DEPTH_UNKNOWN"
        if fail == "not_factory_verified":
            return "PRODUCTIVE_ADMISSION_FAIL"
        return "PRODUCTIVE_ADMISSION_FAIL"
    prod_status = str(
        route.get("productive_quote_status") or route.get("quote_smoke_status") or ""
    )
    if prod_status and not prod_status.startswith("QUOTE_OK"):
        return "QUOTE_SMOKE_FAIL"
    return "PRODUCTIVE_ADMISSION_FAIL"


def _family_bucket(route: Dict[str, Any]) -> str:
    from m9.graph_arb.adapter_families import route_family

    fam = route_family(route)
    dex = str(route.get("dex_id") or "unknown")
    if fam == "v4_pool_manager":
        return "V4"
    if fam == "balancer_vault":
        return "Balancer"
    if fam == "maverick_v2":
        return "Maverick"
    if fam == "curve_stable":
        return "Curve"
    if fam == "v3_fork":
        return "V3"
    if fam == "v2_fork":
        return "V2"
    return dex or fam or "unknown"


def narrow_routes_by_econ_capacity_closure(
    routes: List[Dict[str, Any]],
    *,
    config_path: str,
    cycle_lengths: Tuple[int, ...] = (2, 3, 4),
    floor_usd: Optional[float] = None,
    profile_name: Optional[str] = None,
    lane: str = "productive",
    max_cycles: int = 8000,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Keep routes participating in at least one cycle with usable capacity >= floor."""
    from m9.graph_arb.builder import build_graph_from_inventory
    from m9.graph_arb.topology_diagnostic import (
        _write_temp_inventory,
        collect_cycle_route_ids_from_routes,
    )

    cm = load_cost_model(config_path)
    if floor_usd is not None:
        _floor = float(floor_usd)
    elif profile_name:
        _floor = economic_size_floor_for_profile(cm, profile_name)
    else:
        _floor = economic_size_floor_for_profile(
            cm, resolve_active_economics_profile_name(cm)
        )

    all_route_ids, _ = collect_cycle_route_ids_from_routes(
        routes,
        config_path=config_path,
        cycle_lengths=cycle_lengths,
        lane=lane,
        max_cycles=max_cycles,
    )
    path = _write_temp_inventory(routes)
    qualified: List[GraphCycle] = []
    by_length: Dict[str, int] = {}
    capacity_ids: Set[str] = set()
    keep_ids: Set[str] = set()
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
        qualified, by_length = collect_cycles_at_floor(
            adjacency or {},
            cycle_lengths=cycle_lengths,
            floor_usd=_floor,
            max_cycles=max_cycles,
        )
        capacity_ids = route_ids_from_cycles(qualified)
        keep_ids = closure_route_ids_for_qualified_cycles(
            adjacency or {},
            qualified,
            cycle_lengths=cycle_lengths,
            max_cycles=max_cycles,
        )
        if not keep_ids:
            keep_ids = capacity_ids
    finally:
        import os

        try:
            os.remove(path)
        except OSError:
            pass

    kept = [r for r in routes if str(r.get("route_id") or "") in keep_ids]
    meta = {
        "floor_usd": _floor,
        "profile_name": profile_name,
        "routes_before": len(routes),
        "routes_after": len(kept),
        "cycles_at_floor": len(qualified),
        "cycles_at_floor_by_length": by_length,
        "route_ids_in_any_cycle": len(all_route_ids),
        "route_ids_in_econ_capacity_cycles": len(capacity_ids),
        "route_ids_in_closure_wrapper": len(keep_ids),
        "closure_expansion_routes_added": max(0, len(keep_ids) - len(capacity_ids)),
    }
    return kept, meta


def run_capacity_cycle_diagnostic(
    *,
    inventory_path: str,
    config_path: str = "config/exotic_base_anchor.yaml",
    cycle_lengths: Tuple[int, ...] = (2, 3, 4),
    floors_usd: Sequence[float] = DEFAULT_CAPACITY_FLOORS_USD,
    lane: str = "productive",
    require_factory_verified: bool = False,
    max_cycles: int = 8000,
    sample_limit: int = 8,
    include_four_leg_rca: bool = False,
) -> Dict[str, Any]:
    """Build productive graph and count cycles by usable-capacity floors."""
    from m9.graph_arb.builder import build_graph_from_inventory

    cost_model = load_cost_model(config_path)
    active_profile = resolve_active_economics_profile_name(cost_model)
    prod_floor = production_conservative_floor(cost_model)
    active_floor = economic_size_floor_for_profile(cost_model, active_profile)

    route_map: Dict[str, Dict[str, Any]] = {}
    try:
        import json
        from pathlib import Path

        inv = json.loads(Path(inventory_path).read_text(encoding="utf-8"))
        for route in inv.get("active_routes") or []:
            rid = str(route.get("route_id") or "")
            if rid:
                route_map[rid] = route
    except Exception:
        route_map = {}

    adjacency = build_graph_from_inventory(
        inventory_path=inventory_path,
        config_path=config_path,
        lane=lane,
        require_factory_verified=require_factory_verified,
        diagnostic_admission_mode=(
            "topology_probe" if lane == "productive" else None
        ),
    )
    from m9.graph_arb.universe_contract import build_graph_fingerprint

    active_route_count = len(route_map)
    graph_fingerprint = build_graph_fingerprint(
        inventory_path=inventory_path,
        adjacency=adjacency,
        active_route_count=active_route_count,
        lane=lane,
        require_factory_verified=require_factory_verified,
    )
    empty_base = {
        "schema_version": "m9_capacity_cycle_diagnostic.2",
        "inventory_path": inventory_path,
        "config_path": config_path,
        "lane": lane,
        "require_factory_verified": require_factory_verified,
        "cycle_lengths": list(cycle_lengths),
        "capacity_floors_usd": list(floors_usd),
        "active_economics_profile": active_profile,
        "economic_size_floor_usd": active_floor,
        "production_conservative_floor_usd": prod_floor,
        "cycles_total": 0,
        "cycles_with_all_legs_depth_known": 0,
        "cycles_by_usable_capacity_floor": {
            str(int(f) if f == int(f) else f): 0 for f in floors_usd
        },
        "cycles_by_profile": count_cycles_by_profile([], cost_model, config_path=config_path),
        "near_econ_candidate_cycles": [],
        "near_econ_cycles_count": 0,
        "enrichment_targets": {"route_ids": [], "route_ids_count": 0, "bottleneck_legs": []},
        "cycles_at_econ_floor": 0,
        "cycles_at_production_floor": 0,
        "cycles_at_econ_floor_by_length": {str(n): 0 for n in cycle_lengths},
        "sample_cycles_at_econ_floor": [],
        "capacity_valid_cycle_ids": [],
        "blocker_hint": "NO_GRAPH_OR_NO_CYCLES",
        "graph_fingerprint": graph_fingerprint,
    }
    if not adjacency:
        return empty_base

    all_cycles: List[GraphCycle] = []
    seen_ids: Set[str] = set()
    depth_known_count = 0
    for length in cycle_lengths:
        for cycle in find_cycles(
            adjacency, cycle_lengths=(length,), max_cycles=max_cycles
        ):
            if cycle.cycle_id in seen_ids:
                continue
            seen_ids.add(cycle.cycle_id)
            all_cycles.append(cycle)
            if cycle_bottleneck_usable_capacity_usd(cycle) is not None:
                depth_known_count += 1

    floor_counts = count_cycles_by_usable_capacity(all_cycles, floors_usd)
    cycles_by_profile = count_cycles_by_profile(
        all_cycles, cost_model, config_path=config_path
    )
    near_rows = near_econ_candidate_cycles(all_cycles, near_floors_usd=(25.0, 50.0))
    enrich_targets = enrichment_targets_from_cycles(all_cycles, near_floors_usd=floors_usd)

    prod_key = str(int(prod_floor) if prod_floor == int(prod_floor) else prod_floor)
    cycles_at_prod = int(floor_counts.get(prod_key, 0))
    if prod_key not in floor_counts:
        cycles_at_prod = int(
            (cycles_by_profile.get("production_conservative") or {}).get(
                "cycles_at_floor", 0
            )
        )

    active_key = str(int(active_floor) if active_floor == int(active_floor) else active_floor)
    cycles_at_active = int(floor_counts.get(active_key, cycles_at_prod))

    qualified, by_length = collect_cycles_at_floor(
        adjacency,
        cycle_lengths=cycle_lengths,
        floor_usd=active_floor,
        max_cycles=max_cycles,
    )

    samples: List[Dict[str, Any]] = []
    for cycle in qualified[:sample_limit]:
        leg_caps = []
        for edge in cycle.edges:
            leg_caps.append(
                {
                    "route_id": edge.route_id,
                    "dex_id": edge.dex_id,
                    "effective_depth_usd": edge.effective_depth_usd,
                    "usable_capacity_usd": edge_usable_capacity_usd(edge),
                }
            )
        samples.append(
            {
                "cycle_id": cycle.cycle_id,
                "length": cycle.length,
                "token_path": cycle.token_path,
                "bottleneck_usable_capacity_usd": cycle_bottleneck_usable_capacity_usd(
                    cycle
                ),
                "min_raw_depth_usd": cycle.min_effective_depth_usd,
                "legs": leg_caps,
            }
        )

    if cycles_at_prod > 0:
        blocker_hint = "ECON_CAPACITY_CYCLES_PRESENT"
    elif near_rows:
        blocker_hint = "NEAR_ECON_CAPACITY_ONLY"
    else:
        blocker_hint = "NO_ECON_CAPACITY_CYCLES_AT_PRODUCTION_FLOOR"

    shadow_blocked, shadow_block_reason = shadow_gate_blocked(
        {
            "cycles_total": len(all_cycles),
            "cycles_by_profile": cycles_by_profile,
            "cycles_at_production_floor": cycles_at_prod,
            "active_economics_profile": active_profile,
        }
    )
    top_legs = top_bottleneck_legs(
        all_cycles,
        floor_usd=active_floor,
        route_map=route_map,
        limit=50,
    )

    report: Dict[str, Any] = {
        **empty_base,
        "cycles_total": len(all_cycles),
        "cycles_with_all_legs_depth_known": depth_known_count,
        "cycles_by_usable_capacity_floor": floor_counts,
        "cycles_by_profile": cycles_by_profile,
        "near_econ_candidate_cycles": near_rows[:sample_limit],
        "near_econ_cycles_count": len(near_rows),
        "enrichment_targets": enrich_targets,
        "cycles_at_econ_floor": cycles_at_active,
        "cycles_at_production_floor": cycles_at_prod,
        "cycles_at_econ_floor_by_length": by_length,
        "capacity_valid_cycle_ids": [c.cycle_id for c in qualified],
        "sample_cycles_at_econ_floor": samples,
        "blocker_hint": blocker_hint,
        "top_bottleneck_legs": top_legs,
        "shadow_gate": {
            "blocked": shadow_blocked,
            "reason": shadow_block_reason,
            "cycles_at_floor_required": True,
        },
        "graph_fingerprint": graph_fingerprint,
    }
    if include_four_leg_rca:
        report["productive_four_leg_rca"] = run_productive_four_leg_rca(
            inventory_path=inventory_path,
            config_path=config_path,
        )
    return report


def is_econ_gate_attempt(qr: Any, econ_floor_usd: float) -> bool:
    """Econ-sized attempt stopped before RPC (depth/sizing gate)."""
    sz = float(getattr(qr, "size_usd", 0.0) or 0.0)
    if sz < float(econ_floor_usd):
        return False
    status = str(getattr(qr, "status", "") or "")
    if status in _ECON_GATE_ONLY_STATUSES:
        return True
    legs = getattr(qr, "leg_results", None) or []
    return not legs and status not in (
        "QUOTE_FAILED",
        "CYCLE_QUOTE_TIMEOUT",
        "POSITIVE_GROSS",
        "NEGATIVE_GROSS",
    )


def is_econ_rpc_quote_attempt(qr: Any, econ_floor_usd: float) -> bool:
    """Econ-sized attempt that reached at least one RPC leg quote."""
    sz = float(getattr(qr, "size_usd", 0.0) or 0.0)
    if sz < float(econ_floor_usd):
        return False
    status = str(getattr(qr, "status", "") or "")
    if status in _ECON_GATE_ONLY_STATUSES:
        return False
    legs = getattr(qr, "leg_results", None) or []
    if legs:
        return True
    return status in (
        "QUOTE_FAILED",
        "CYCLE_QUOTE_TIMEOUT",
        "POSITIVE_GROSS",
        "NEGATIVE_GROSS",
    )
