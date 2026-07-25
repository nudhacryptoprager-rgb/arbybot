"""Shadow lane modes: strict filtering and unified cycle ranking."""
from __future__ import annotations

from typing import Dict, FrozenSet, List, Optional, Set, Tuple, Any

from m9.graph_arb.models import GraphCycle

SHADOW_LANE_CAPACITY_ONLY = "capacity_only"
SHADOW_LANE_LONG_TAIL_TARGET = "long_tail_target"
SHADOW_LANE_BROAD_DIAGNOSTIC = "broad_graph_diagnostic"

VALID_SHADOW_LANE_MODES = frozenset(
    {
        SHADOW_LANE_CAPACITY_ONLY,
        SHADOW_LANE_LONG_TAIL_TARGET,
        SHADOW_LANE_BROAD_DIAGNOSTIC,
    }
)

BLOCKER_NO_CAPACITY_VALID_CYCLES = "NO_CAPACITY_VALID_CYCLES"
BLOCKER_NO_LONG_TAIL_TARGET_CYCLES = "NO_LONG_TAIL_TARGET_CYCLES"


def normalize_shadow_lane_mode(raw: Optional[str]) -> str:
    mode = str(raw or "").strip()
    if mode in VALID_SHADOW_LANE_MODES:
        return mode
    return SHADOW_LANE_BROAD_DIAGNOSTIC


def cycle_long_tail_target_eligible(
    cycle: GraphCycle,
    *,
    direct_pool_addrs: FrozenSet[str],
    derived_pool_addrs: FrozenSet[str],
) -> bool:
    """Direct sniper pool or verified M8-derived mirror pool on the cycle."""
    for edge in cycle.edges:
        pool = str(getattr(edge, "pool_address", "") or "").lower()
        if pool in direct_pool_addrs or pool in derived_pool_addrs:
            return True
    return False


def filter_cycles_for_shadow_lane(
    cycles: List[GraphCycle],
    *,
    mode: str,
    capacity_ids: Set[str],
    direct_pool_addrs: FrozenSet[str],
    derived_pool_addrs: FrozenSet[str],
) -> Tuple[List[GraphCycle], Optional[str]]:
    """Physical universe filter — not a soft queue boost."""
    lane = normalize_shadow_lane_mode(mode)
    if lane == SHADOW_LANE_CAPACITY_ONLY:
        filtered = [c for c in cycles if c.cycle_id in capacity_ids]
        if not filtered:
            return [], BLOCKER_NO_CAPACITY_VALID_CYCLES
        return filtered, None
    if lane == SHADOW_LANE_LONG_TAIL_TARGET:
        filtered = [
            c
            for c in cycles
            if cycle_long_tail_target_eligible(
                c,
                direct_pool_addrs=direct_pool_addrs,
                derived_pool_addrs=derived_pool_addrs,
            )
        ]
        if not filtered:
            return [], BLOCKER_NO_LONG_TAIL_TARGET_CYCLES
        return filtered, None
    return list(cycles), None


def rank_shadow_cycles(
    cycles: List[GraphCycle],
    *,
    capacity_ids: Set[str],
    route_meta: Dict[str, Dict[str, Any]],
    mode: str,
    direct_pool_addrs: FrozenSet[str],
    derived_pool_addrs: FrozenSet[str],
    capacity_prioritized: bool = False,
) -> List[GraphCycle]:
    """Single stable rank: capacity-valid → target-eligible → productive score."""
    from m9.graph_arb.cycle_lane_prefilter import cycle_productive_readiness_score

    lane = normalize_shadow_lane_mode(mode)
    boost_capacity = capacity_prioritized or lane == SHADOW_LANE_CAPACITY_ONLY
    boost_target = lane == SHADOW_LANE_LONG_TAIL_TARGET

    def sort_key(c: GraphCycle) -> tuple:
        cap_prio = 0 if (boost_capacity and c.cycle_id in capacity_ids) else 1
        if boost_target:
            target_prio = (
                0
                if cycle_long_tail_target_eligible(
                    c,
                    direct_pool_addrs=direct_pool_addrs,
                    derived_pool_addrs=derived_pool_addrs,
                )
                else 1
            )
        else:
            target_prio = 0
        ready, total = (
            cycle_productive_readiness_score(c, route_meta)
            if route_meta
            else (0, len(c.edges))
        )
        prod = -(ready / total if total else 0.0)
        return (cap_prio, target_prio, prod, c.total_fee_bps, c.cycle_id)

    return sorted(cycles, key=sort_key)
