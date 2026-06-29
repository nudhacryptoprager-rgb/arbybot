"""Narrow-bridge target-universe checks for time-to-mirror M9 shadow gate."""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Tuple

from m8.discovery.token_classify import TOKEN_CLASS_FRESH, TOKEN_CLASS_KNOWN_MAJOR

_TARGET_TOKEN_CLASSES = frozenset({TOKEN_CLASS_FRESH, "unknown_unclassified"})
_TARGET_REFRESH_LANES = frozenset(
    {
        "fresh_delta_lane",
        "time_to_mirror_hot",
        "pending_queue",
        "wide_recall_lane",
    }
)
_NON_TARGET_REFRESH_LANES = frozenset({"audit_lane"})
_NARROW_ELIGIBLE_DISCOVERY_SOURCES = frozenset(
    {
        "onchain_factory",
        "factory_log",
        "active_factory_scan_batch",
        "onchain_factory_mirror_scan",
    }
)
_DEXSCREENER_ONLY_SOURCES = frozenset({"dexscreener", "geckoterminal", "thegraph"})


def route_has_eligible_mirror_discovery(route: Dict[str, Any]) -> bool:
    """DexScreener-only hints without factory verify are not narrow-bridge eligible."""
    resolve_src = str(
        route.get("resolve_source")
        or route.get("discovery_source")
        or (route.get("raw") or {}).get("discovery_source")
        or ""
    )
    if resolve_src in _NARROW_ELIGIBLE_DISCOVERY_SOURCES:
        return True
    hint_src = str(route.get("hint_source") or route.get("source") or "")
    if hint_src in _NARROW_ELIGIBLE_DISCOVERY_SOURCES:
        return True
    if route.get("factory_verified"):
        return True
    if hint_src in _DEXSCREENER_ONLY_SOURCES and not route.get("factory_verified"):
        return False
    # Legacy expansion rows without external-hint provenance remain eligible.
    if not hint_src and not resolve_src:
        return True
    return bool(route.get("factory_verified"))


def is_target_narrow_route(route: Dict[str, Any]) -> bool:
    """Exclude known_major / audit-only rows from time-to-mirror narrow bridge."""
    token_class = str(route.get("token_class") or "unknown_unclassified")
    if token_class == TOKEN_CLASS_KNOWN_MAJOR:
        return False
    refresh_lane = str(route.get("refresh_lane") or "")
    if token_class in _TARGET_TOKEN_CLASSES:
        return True
    if refresh_lane in _TARGET_REFRESH_LANES:
        return True
    if refresh_lane in _NON_TARGET_REFRESH_LANES and token_class not in _TARGET_TOKEN_CLASSES:
        return False
    return token_class not in {TOKEN_CLASS_KNOWN_MAJOR}


def target_narrow_universe_gate_blocked(bridge_doc: Dict[str, Any]) -> Tuple[bool, str]:
    """Hard gate: M9 depth/capacity/shadow require fresh-long-tail quote-ready inventory."""
    fresh_ready = int(bridge_doc.get("fresh_long_tail_quote_ready_tokens") or 0)
    if fresh_ready <= 0:
        return True, "NO_FRESH_LONG_TAIL_QUOTE_READY"
    non_target, reason = non_target_narrow_universe(bridge_doc)
    if non_target:
        return True, reason
    return False, "target_universe_ok"


def route_provenance_histogram(
    routes: List[Dict[str, Any]], field: str
) -> Dict[str, int]:
    counts: Counter[str] = Counter()
    for route in routes:
        val = str(route.get(field) or "unknown")
        counts[val] += 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def summarize_narrow_bridge_provenance(
    bridge_doc: Dict[str, Any],
) -> Dict[str, Any]:
    routes = list(bridge_doc.get("active_routes") or [])
    by_class = route_provenance_histogram(routes, "token_class")
    by_lane = route_provenance_histogram(routes, "refresh_lane")
    non_target, reason = non_target_narrow_universe(bridge_doc)
    return {
        "active_routes_by_token_class": by_class,
        "active_routes_by_refresh_lane": by_lane,
        "non_target_narrow_universe": non_target,
        "non_target_reason": reason if non_target else None,
    }


def depth_probe_status_histogram(routes: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Counter[str] = Counter()
    for route in routes:
        status = str(route.get("depth_probe_status") or "UNKNOWN")
        counts[status] += 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def non_target_narrow_universe(bridge_doc: Dict[str, Any]) -> Tuple[bool, str]:
    """True when narrow bridge does not prove fresh-long-tail target universe."""
    routes = list(bridge_doc.get("active_routes") or [])
    if not routes:
        return True, "EMPTY_NARROW_BRIDGE"
    classes = {str(r.get("token_class") or "unknown") for r in routes}
    lanes = {str(r.get("refresh_lane") or "unknown") for r in routes}
    if classes <= {TOKEN_CLASS_KNOWN_MAJOR} and lanes <= _NON_TARGET_REFRESH_LANES:
        return True, "NON_TARGET_NARROW_UNIVERSE"
    if not (classes & _TARGET_TOKEN_CLASSES) and lanes <= _NON_TARGET_REFRESH_LANES:
        return True, "NON_TARGET_NARROW_UNIVERSE"
    if classes <= {TOKEN_CLASS_KNOWN_MAJOR} and not (lanes & _TARGET_REFRESH_LANES):
        return True, "NON_TARGET_NARROW_UNIVERSE"
    return False, "target_universe_ok"


def narrow_shadow_gate_blocked(
    capacity_doc: Dict[str, Any],
    bridge_doc: Dict[str, Any],
    *,
    profile_names: Tuple[str, ...] = (
        "diagnostic_near_econ",
        "base_realistic",
        "production_conservative",
    ),
) -> Tuple[bool, str]:
    from m9.graph_arb.cycle_capacity import shadow_gate_blocked

    blocked, reason = target_narrow_universe_gate_blocked(bridge_doc)
    if blocked:
        return blocked, reason
    cycles_total = int(capacity_doc.get("cycles_total") or 0)
    if cycles_total <= 0:
        return True, "M9_CAPACITY_BLOCKED_BY_ZERO_CYCLES_TOTAL"
    blocked, reason = shadow_gate_blocked(capacity_doc, profile_names=profile_names)
    if blocked:
        return blocked, reason
    return False, "shadow_allowed"
