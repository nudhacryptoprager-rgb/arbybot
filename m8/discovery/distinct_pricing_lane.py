"""Distinct-pricing DEX lane — Curve / Balancer / Maverick acceptance metrics."""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Set

BLOCKER_DISTINCT_PRICING_LANE_NOT_READY = "DISTINCT_PRICING_DEX_LANE_NOT_READY"
BLOCKER_DISTINCT_PRICING_BALANCER_MAVERICK_LANES_NOT_READY = (
    "DISTINCT_PRICING_BALANCER_MAVERICK_LANES_NOT_READY"
)

CURVE_DEX_IDS: Set[str] = {"curve_stable", "curve"}
BALANCER_DEX_IDS: Set[str] = {"balancer_vault", "balancer_stable", "balancer_weighted"}
MAVERICK_DEX_IDS: Set[str] = {"maverick_v2"}

CURVE_ADAPTER_TYPES: Set[str] = {"curve_stable", "curve_stableswap"}
BALANCER_ADAPTER_TYPES: Set[str] = {
    "balancer_vault",
    "balancer_stable",
    "balancer_weighted",
}
MAVERICK_ADAPTER_TYPES: Set[str] = {"maverick_v2"}

DISTINCT_PRICING_DEX_IDS: Set[str] = CURVE_DEX_IDS | BALANCER_DEX_IDS | MAVERICK_DEX_IDS

_QUOTE_OK_PREFIXES = ("QUOTE_OK", "OK", "PASS", "SUCCESS")


def _lane_for_route(route: Dict[str, Any]) -> Optional[str]:
    dex = str(route.get("dex_id") or "")
    adapter = str(route.get("adapter_type") or "")
    if dex in CURVE_DEX_IDS or adapter in CURVE_ADAPTER_TYPES:
        return "curve"
    if dex in BALANCER_DEX_IDS or adapter in BALANCER_ADAPTER_TYPES:
        return "balancer"
    if dex in MAVERICK_DEX_IDS or adapter in MAVERICK_ADAPTER_TYPES:
        return "maverick"
    return None


def _is_quoteable(route: Dict[str, Any]) -> bool:
    qss = str(route.get("quote_smoke_status") or route.get("quote_smoke") or "")
    if not qss or qss in ("not_run", "skipped_registry", ""):
        return False
    upper = qss.upper()
    return any(upper.startswith(p) for p in _QUOTE_OK_PREFIXES)


def count_distinct_pricing_routes(routes: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    """Count active/admitted routes per distinct-pricing lane."""
    curve = balancer = maverick = 0
    balancer_quoteable = maverick_quoteable = 0
    for route in routes:
        lane = _lane_for_route(route)
        if lane == "curve":
            curve += 1
        elif lane == "balancer":
            balancer += 1
            if _is_quoteable(route):
                balancer_quoteable += 1
        elif lane == "maverick":
            maverick += 1
            if _is_quoteable(route):
                maverick_quoteable += 1
    return {
        "curve_routes_ready": curve,
        "balancer_routes_ready": balancer,
        "maverick_routes_ready": maverick,
        "balancer_quoteable_routes": balancer_quoteable,
        "maverick_quoteable_routes": maverick_quoteable,
        "distinct_pricing_routes_ready": curve + balancer + maverick,
    }


def quote_success_rates_by_lane(
    routes: Iterable[Dict[str, Any]],
) -> Dict[str, Optional[float]]:
    """Per-lane quote smoke success rate when quote_smoke fields are present."""
    lanes: Dict[str, List[bool]] = {"curve": [], "balancer": [], "maverick": []}
    for route in routes:
        lane = _lane_for_route(route)
        if not lane:
            continue
        qss = route.get("quote_smoke_status") or route.get("quote_smoke")
        if qss is None or str(qss) in ("not_run", "skipped_registry", ""):
            continue
        lanes[lane].append(_is_quoteable(route))
    out: Dict[str, Optional[float]] = {}
    for lane, key in (
        ("curve", "curve_route_qsr"),
        ("balancer", "balancer_route_qsr"),
        ("maverick", "maverick_route_qsr"),
    ):
        vals = lanes[lane]
        out[key] = round(sum(vals) / len(vals), 4) if vals else None
    return out


def evaluate_distinct_pricing_lane(
    routes: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    """Evaluate per-lane shadow readiness (Curve / Balancer / Maverick separate)."""
    counts = count_distinct_pricing_routes(routes)
    qsr = quote_success_rates_by_lane(routes)
    curve_ready = counts["curve_routes_ready"] > 0
    balancer_ready = counts["balancer_routes_ready"] > 0
    maverick_ready = counts["maverick_routes_ready"] > 0
    all_lanes_ready = curve_ready and balancer_ready and maverick_ready
    bm_quoteable = (
        counts["balancer_quoteable_routes"] + counts["maverick_quoteable_routes"]
    ) > 0

    missing_lanes: List[str] = []
    if not curve_ready:
        missing_lanes.append("curve")
    if not balancer_ready:
        missing_lanes.append("balancer")
    if not maverick_ready:
        missing_lanes.append("maverick")

    quote_lanes_not_ready: List[str] = []
    if balancer_ready and counts["balancer_quoteable_routes"] == 0:
        quote_lanes_not_ready.append("balancer")
    if maverick_ready and counts["maverick_quoteable_routes"] == 0:
        quote_lanes_not_ready.append("maverick")
    if curve_ready and counts["curve_routes_ready"] > 0:
        curve_q = sum(1 for r in routes if _lane_for_route(r) == "curve" and _is_quoteable(r))
        if curve_q == 0:
            quote_lanes_not_ready.append("curve")

    blocker = None
    if not balancer_ready or not maverick_ready:
        blocker = BLOCKER_DISTINCT_PRICING_BALANCER_MAVERICK_LANES_NOT_READY
    elif not curve_ready:
        blocker = BLOCKER_DISTINCT_PRICING_LANE_NOT_READY

    return {
        **counts,
        **qsr,
        "curve_lane_ready": curve_ready,
        "balancer_lane_ready": balancer_ready,
        "maverick_lane_ready": maverick_ready,
        "missing_distinct_pricing_lanes": missing_lanes,
        "quote_lanes_not_ready": quote_lanes_not_ready,
        "distinct_pricing_all_lanes_ready": all_lanes_ready,
        "distinct_pricing_lane_ready": all_lanes_ready,
        "distinct_pricing_shadow_quote_ready": bm_quoteable,
        "existence_blocker": blocker,
    }


def build_per_adapter_lane_report(
    *,
    routes_admitted: List[Dict[str, Any]],
    reject_rows: List[Dict[str, str]],
    pools_found_by_dex: Optional[Dict[str, int]] = None,
) -> Dict[str, Dict[str, int]]:
    """Hard per-adapter report: discovered / verified / admitted / quoteable / rejected."""
    lanes = ("curve_stable", "balancer_vault", "maverick_v2")
    report: Dict[str, Dict[str, int]] = {
        dex: {
            "discovered": 0,
            "verified": 0,
            "admitted": 0,
            "quoteable": 0,
            "rejected": 0,
        }
        for dex in lanes
    }

    dex_to_lane = {
        "curve_stable": "curve_stable",
        "curve": "curve_stable",
        "balancer_vault": "balancer_vault",
        "balancer_stable": "balancer_vault",
        "balancer_weighted": "balancer_vault",
        "maverick_v2": "maverick_v2",
    }

    if pools_found_by_dex:
        for dex, count in pools_found_by_dex.items():
            key = dex_to_lane.get(dex)
            if key:
                report[key]["discovered"] += int(count)

    for route in routes_admitted:
        dex = str(route.get("dex_id") or "")
        key = dex_to_lane.get(dex) or (
            "curve_stable"
            if str(route.get("adapter_type") or "") in CURVE_ADAPTER_TYPES
            else "balancer_vault"
            if str(route.get("adapter_type") or "") in BALANCER_ADAPTER_TYPES
            else "maverick_v2"
            if str(route.get("adapter_type") or "") in MAVERICK_ADAPTER_TYPES
            else None
        )
        if not key:
            continue
        report[key]["admitted"] += 1
        if route.get("factory_verified") or route.get("hint_status") in (
            "HINT_ONCHAIN_VERIFIED",
            "HINT_POOLID_VERIFIED",
            "HINT_FACTORY_VERIFIED",
        ):
            report[key]["verified"] += 1
        if _is_quoteable(route):
            report[key]["quoteable"] += 1

    reject_by_dex: Counter[str] = Counter()
    for row in reject_rows:
        dex = str(row.get("dex_id") or "")
        key = dex_to_lane.get(dex)
        if key:
            reject_by_dex[key] += 1
    for key, count in reject_by_dex.items():
        report[key]["rejected"] += int(count)

    return report


def merge_distinct_pricing_into_acceptance(
    acceptance: Dict[str, Any],
    *,
    routes: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    """Augment hot-path bridge-shadow acceptance with per-lane distinct-pricing gate."""
    lane = evaluate_distinct_pricing_lane(routes)
    out = {**acceptance, **lane}
    topology = bool(acceptance.get("subgraph_ready"))
    lane_eligible = acceptance.get("bridge_shadow_lane_eligible", True)
    all_lanes = bool(lane.get("distinct_pricing_all_lanes_ready"))
    quote_ok = bool(lane.get("distinct_pricing_shadow_quote_ready"))
    out["ready_for_bridge_shadow"] = bool(
        topology and lane_eligible and all_lanes and quote_ok
    )
    if lane.get("existence_blocker"):
        out["existence_blocker"] = lane["existence_blocker"]
    return out
