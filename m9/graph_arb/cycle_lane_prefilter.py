"""Cycle-lane prefilter: prioritize cycles whose legs are productive-quote ready."""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Set

from m9.graph_arb.models import GraphCycle

_CLMM_ADAPTERS: Set[str] = {
    "uniswap_v3",
    "pancakeswap_v3",
    "aerodrome_slipstream",
    "uniswap_v4",
    "uniswap_v2",
    "aerodrome_v2_stable",
    "ve33",
}

_QUOTE_OK_PREFIXES = ("QUOTE_OK", "OK", "PASS", "SUCCESS")


def build_route_metadata_from_routes(
    routes: Iterable[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """Map lowercase pool_address → admission / quote metadata."""
    meta: Dict[str, Dict[str, Any]] = {}
    for route in routes:
        pool = str(route.get("pool_address") or "").lower()
        if not pool:
            continue
        meta[pool] = {
            "route_id": route.get("route_id"),
            "dex_id": route.get("dex_id"),
            "adapter_type": route.get("adapter_type"),
            "productive_quote_status": route.get("productive_quote_status"),
            "quote_smoke_status": route.get("quote_smoke_status"),
            "effective_depth_usd": route.get("effective_depth_usd"),
            "balancer_assets": route.get("balancer_assets"),
            "pool_id": route.get("pool_id"),
            "factory_verified": route.get("factory_verified"),
            "maverick_pool_lane_probe_amount": route.get("maverick_pool_lane_probe_amount"),
            "maverick_min_quoteable_amount_raw": route.get("maverick_min_quoteable_amount_raw"),
            "maverick_max_quoteable_amount_raw": route.get("maverick_max_quoteable_amount_raw"),
            "maverick_token_a_in_probe": route.get("maverick_token_a_in_probe"),
            "maverick_pool_lane_token_in": route.get("maverick_pool_lane_token_in"),
        }
    return meta


def _status_quoteable(status: Any) -> bool:
    qss = str(status or "")
    if not qss:
        return False
    upper = qss.upper()
    return any(upper.startswith(p) for p in _QUOTE_OK_PREFIXES)


def maverick_amount_in_verified_range(
    amount_in: int,
    row: Dict[str, Any],
) -> bool:
    """True when cycle amount fits pool-lane verified Maverick probe range."""
    probe = row.get("maverick_pool_lane_probe_amount")
    if not probe:
        return True
    min_raw = int(row.get("maverick_min_quoteable_amount_raw") or probe)
    max_raw = int(row.get("maverick_max_quoteable_amount_raw") or probe)
    return min_raw <= int(amount_in) <= max_raw


def leg_productive_ready(
    edge: Any,
    route_meta: Dict[str, Dict[str, Any]],
    *,
    amount_in: Optional[int] = None,
) -> bool:
    """True when leg has productive stamp or verified CLMM quote path."""
    pool = str(getattr(edge, "pool_address", "") or "").lower()
    row = route_meta.get(pool) or {}
    adapter = str(getattr(edge, "adapter_type", "") or row.get("adapter_type") or "")
    if adapter == "maverick_v2" and _status_quoteable(row.get("productive_quote_status")):
        probe = row.get("maverick_pool_lane_probe_amount")
        if probe and amount_in is not None:
            return maverick_amount_in_verified_range(amount_in, row)
        return bool(probe)
    if _status_quoteable(row.get("productive_quote_status")):
        return True
    if _status_quoteable(row.get("quote_smoke_status")):
        return True
    if adapter in _CLMM_ADAPTERS and getattr(edge, "factory_verified", False):
        return True
    if adapter in _CLMM_ADAPTERS and row.get("factory_verified") is True:
        return True
    return False


def cycle_productive_readiness_score(
    cycle: GraphCycle,
    route_meta: Dict[str, Dict[str, Any]],
) -> tuple[int, int]:
    """Return (ready_legs, total_legs) for cycle productive prefilter."""
    total = len(cycle.edges)
    ready = sum(1 for e in cycle.edges if leg_productive_ready(e, route_meta))
    return ready, total


def prioritize_productive_ready_cycles(
    cycles: List[GraphCycle],
    route_meta: Dict[str, Dict[str, Any]],
) -> List[GraphCycle]:
    """Stable sort: all-leg-ready cycles first, then partial, then fee order preserved."""

    def sort_key(c: GraphCycle) -> tuple:
        ready, total = cycle_productive_readiness_score(c, route_meta)
        all_ready = 0 if ready == total and total > 0 else 1
        return (all_ready, -(ready / total if total else 0.0), c.total_fee_bps, c.cycle_id)

    return sorted(cycles, key=sort_key)


def explain_cycle_kill_leg(
    qr: Any,
    route_meta: Dict[str, Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """First failing leg with pool metadata for cycle RCA."""
    for idx, leg in enumerate(qr.leg_results or []):
        if getattr(leg, "ok", False):
            continue
        edge = qr.cycle.edges[idx] if idx < len(qr.cycle.edges) else None
        pool = str(getattr(edge, "pool_address", "") or "").lower()
        row = route_meta.get(pool) or {}
        return {
            "leg_index": idx,
            "route_id": getattr(edge, "route_id", None) if edge else None,
            "pool_address": pool or None,
            "dex_id": getattr(edge, "dex_id", None) if edge else None,
            "adapter_type": getattr(edge, "adapter_type", None) if edge else None,
            "reject_reason": getattr(leg, "reject_reason", None),
            "amount_in": getattr(leg, "amount_in", None),
            "effective_depth_usd": (
                getattr(edge, "effective_depth_usd", None) if edge else row.get("effective_depth_usd")
            ),
            "productive_quote_status": row.get("productive_quote_status"),
            "balancer_assets_present": bool(row.get("balancer_assets")),
            "pool_id": row.get("pool_id"),
            "cycle_amount_in": getattr(leg, "amount_in", None),
            "pool_lane_probe_amount": (
                getattr(edge, "maverick_pool_lane_probe_amount", None)
                if edge
                else row.get("maverick_pool_lane_probe_amount")
            ),
            "token_a_in_probe": (
                getattr(edge, "maverick_token_a_in_probe", None)
                if edge and edge.maverick_token_a_in_probe is not None
                else row.get("maverick_token_a_in_probe")
            ),
            "token_in": getattr(edge, "token_in_addr", None) if edge else None,
            "token_out": getattr(edge, "token_out_addr", None) if edge else None,
        }
    status = str(getattr(qr, "status", "") or "")
    if status in ("OVERSIZED_VS_DEPTH", "UNKNOWN_PRICE", "CYCLE_QUOTE_FAILED"):
        return {"leg_index": None, "reject_reason": getattr(qr, "reject_reason", status)}
    return None
