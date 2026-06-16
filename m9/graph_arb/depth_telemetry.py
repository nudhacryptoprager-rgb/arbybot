"""Depth telemetry: measured vs unknown vs fallback-capped rejects."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

DEPTH_STATUS_MEASURED = "MEASURED"
DEPTH_STATUS_UNKNOWN = "UNKNOWN"
DEPTH_STATUS_FALLBACK_CAPPED = "FALLBACK_CAPPED"
DEPTH_STATUS_MEASURED_TOO_THIN = "MEASURED_TOO_THIN"
DEPTH_STATUS_LOWER_BOUND = "LOWER_BOUND_AT_MAX_PROBE"
DEPTH_STATUS_UNRESOLVED = "DEPTH_UNRESOLVED"

REJECT_DEPTH_BELOW_ECONOMICS_FLOOR = "DEPTH_BELOW_ECONOMICS_FLOOR"

STATUS_OVERSIZED_VS_MEASURED_DEPTH = "OVERSIZED_VS_MEASURED_DEPTH"
STATUS_OVERSIZED_VS_UNKNOWN_DEPTH_FALLBACK = "OVERSIZED_VS_UNKNOWN_DEPTH_FALLBACK"
REJECT_OVERSIZED_VS_MEASURED_DEPTH = "OVERSIZED_VS_MEASURED_DEPTH"
REJECT_OVERSIZED_VS_UNKNOWN_DEPTH_FALLBACK = "OVERSIZED_VS_UNKNOWN_DEPTH_FALLBACK"
REJECT_DEPTH_UNKNOWN = "DEPTH_UNKNOWN"

ECONOMICS_DEPTH_KNOWN_RATE_MIN = 0.8
MICRO_LIVENESS_MAX_USD = 0.25


def _route_depth_is_known(route: Dict[str, Any]) -> bool:
    from m9.graph_arb.depth_capacity_probe import (
        DEPTH_PROBE_LOWER_BOUND_AT_MAX,
        DEPTH_PROBE_MEASURED_CAPACITY,
        DEPTH_PROBE_TOO_THIN,
    )

    status = route.get("depth_probe_status")
    if status in (
        DEPTH_PROBE_MEASURED_CAPACITY,
        DEPTH_PROBE_LOWER_BOUND_AT_MAX,
        DEPTH_PROBE_TOO_THIN,
    ):
        return True
    depth = route.get("effective_depth_usd")
    if depth is None:
        return False
    try:
        return float(depth) > 0
    except (TypeError, ValueError):
        return False


def depth_known_rate(routes: Sequence[Dict[str, Any]]) -> float:
    """Fraction of routes with measured or ladder-bounded ``effective_depth_usd``."""
    active = [r for r in routes if r.get("pool_address")]
    if not active:
        return 0.0
    known = sum(1 for r in active if _route_depth_is_known(r))
    return round(known / len(active), 4)


def classify_route_depth_status(
    route: Dict[str, Any],
    *,
    min_econ_usd: float = MICRO_LIVENESS_MAX_USD,
) -> str:
    from m9.graph_arb.depth_capacity_probe import (
        DEPTH_PROBE_LOWER_BOUND_AT_MAX,
        DEPTH_PROBE_MEASURED_CAPACITY,
        DEPTH_PROBE_TOO_THIN,
        DEPTH_PROBE_UNKNOWN,
    )

    probe_status = route.get("depth_probe_status")
    if probe_status == DEPTH_PROBE_UNKNOWN or (
        route.get("depth_probe_error") and route.get("effective_depth_usd") is None
    ):
        return DEPTH_STATUS_UNKNOWN

    depth = route.get("effective_depth_usd")
    if depth is None:
        return DEPTH_STATUS_UNKNOWN
    try:
        d = float(depth)
    except (TypeError, ValueError):
        return DEPTH_STATUS_UNKNOWN
    if d <= 0:
        return DEPTH_STATUS_UNKNOWN
    if route.get("depth_probe_source") == "distinct_depth_probe" and d <= 10.0:
        return DEPTH_STATUS_FALLBACK_CAPPED
    if probe_status == DEPTH_PROBE_TOO_THIN:
        return DEPTH_STATUS_MEASURED_TOO_THIN
    if d < min_econ_usd:
        return DEPTH_STATUS_MEASURED_TOO_THIN
    if probe_status == DEPTH_PROBE_LOWER_BOUND_AT_MAX and d <= 100.0:
        return DEPTH_STATUS_FALLBACK_CAPPED
    if probe_status == DEPTH_PROBE_LOWER_BOUND_AT_MAX:
        return DEPTH_STATUS_LOWER_BOUND
    if probe_status == DEPTH_PROBE_MEASURED_CAPACITY:
        return DEPTH_STATUS_MEASURED
    if d <= 100.0 and probe_status is None:
        return DEPTH_STATUS_FALLBACK_CAPPED
    return DEPTH_STATUS_MEASURED


def classify_cycle_depth_status(
    cycle: Any,
    route_meta_by_pool: Optional[Dict[str, Dict[str, Any]]] = None,
) -> str:
    """Worst depth status across cycle legs."""
    order = {
        DEPTH_STATUS_UNKNOWN: 0,
        DEPTH_STATUS_FALLBACK_CAPPED: 1,
        DEPTH_STATUS_LOWER_BOUND: 2,
        DEPTH_STATUS_MEASURED_TOO_THIN: 3,
        DEPTH_STATUS_MEASURED: 4,
    }
    worst = DEPTH_STATUS_MEASURED
    for edge in getattr(cycle, "edges", ()) or ():
        pool = str(getattr(edge, "pool_address", "") or "").lower()
        row = (route_meta_by_pool or {}).get(pool) or {}
        edge_depth = getattr(edge, "effective_depth_usd", None)
        if edge_depth is not None:
            row = {**row, "effective_depth_usd": edge_depth}
        leg_status = classify_route_depth_status(row)
        if order.get(leg_status, 0) < order.get(worst, 3):
            worst = leg_status
    if worst == DEPTH_STATUS_MEASURED:
        min_d = getattr(cycle, "min_effective_depth_usd", None)
        if min_d is None:
            return DEPTH_STATUS_UNKNOWN
    return worst


def oversized_reject_for_depth(
    cycle_depth_usd: Optional[float],
    *,
    gross_bps: float,
) -> tuple[str, str]:
    """Return (status, reject_reason) for negative gross depth overflow."""
    if cycle_depth_usd is None or cycle_depth_usd <= 0:
        return (
            STATUS_OVERSIZED_VS_UNKNOWN_DEPTH_FALLBACK,
            REJECT_OVERSIZED_VS_UNKNOWN_DEPTH_FALLBACK,
        )
    return (
        STATUS_OVERSIZED_VS_MEASURED_DEPTH,
        REJECT_OVERSIZED_VS_MEASURED_DEPTH,
    )


def opportunity_depth_fields(
    qr: Any,
    route_meta_by_pool: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Fields for top_opportunities / cycle summaries."""
    depth_status = classify_cycle_depth_status(qr.cycle, route_meta_by_pool)
    min_depth = getattr(qr.cycle, "min_effective_depth_usd", None)
    size = float(qr.size_usd or 0)
    opp_class: Optional[str] = None
    if (
        qr.status == "POSITIVE_GROSS"
        and size > 0
        and size < MICRO_LIVENESS_MAX_USD
    ):
        opp_class = "MICRO_ONLY_NOT_ECONOMIC"
    return {
        "effective_depth_usd": min_depth,
        "depth_status": depth_status,
        "opportunity_class": opp_class,
    }


def economics_blocked_by_depth_telemetry(
    depth_known_rate_value: float,
    *,
    threshold: float = ECONOMICS_DEPTH_KNOWN_RATE_MIN,
) -> bool:
    return depth_known_rate_value < threshold


def economics_quote_depth_resolved(cycle: Any) -> bool:
    """True when the cycle bottleneck has measured or ladder-bounded depth.

    Cycles with only UNKNOWN depth must not be classified as market-toxic when
    quoted at the economics floor — that negative is an instrumentation artifact.
    """
    status = classify_cycle_depth_status(cycle)
    return status not in (DEPTH_STATUS_UNKNOWN, DEPTH_STATUS_UNRESOLVED)


def exclude_from_toxic_economics_denominator(qr: Any) -> bool:
    """Cycles that should not inflate toxic_route_rate or market-negative buckets."""
    from m9.graph_arb.leg_capacity import CAPACITY_INSTRUMENTATION_REJECTS

    if qr.status in ("LEG_CAPACITY_REJECT", "DEPTH_UNRESOLVED", "DEPTH_BELOW_ECONOMICS_FLOOR"):
        return True
    if (qr.reject_reason or "") in CAPACITY_INSTRUMENTATION_REJECTS:
        return True
    if qr.status == "CYCLE_SANITY_FAILED" and (
        qr.reject_reason or ""
    ) in ("AMOUNT_CONTINUITY_VIOLATION",):
        return True
    return False


def pre_shadow_bridge_blockers(
    *,
    depth_known_rate_value: Optional[float],
    routes_decimals_unknown: int = 0,
    active_route_count: int = 0,
    depth_threshold: float = ECONOMICS_DEPTH_KNOWN_RATE_MIN,
    decimals_unknown_max: int = 50,
) -> List[str]:
    """Blockers that must be cleared before a productive M9 shadow run."""
    blockers: List[str] = []
    if depth_known_rate_value is not None and depth_known_rate_value < depth_threshold:
        blockers.append("DEPTH_ENRICHMENT_REQUIRED")
    if active_route_count > 0 and routes_decimals_unknown > decimals_unknown_max:
        blockers.append("DECIMALS_ENRICHMENT_REQUIRED")
    return blockers
