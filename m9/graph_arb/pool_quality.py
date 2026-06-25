"""Per-pool quality state machine for discovery → productive admission."""
from __future__ import annotations

from typing import Any, Dict, Optional, Set, Tuple

# Canonical states (ordered progression; QUARANTINED is terminal).
STATE_DISCOVERED = "DISCOVERED"
STATE_FACTORY_VERIFIED = "FACTORY_VERIFIED"
STATE_DEPTH_OK = "DEPTH_OK"
STATE_QUOTE_OK = "QUOTE_OK"
STATE_PRODUCTIVE_READY = "PRODUCTIVE_READY"
STATE_QUARANTINED = "QUARANTINED"

_ALL_STATES = frozenset({
    STATE_DISCOVERED,
    STATE_FACTORY_VERIFIED,
    STATE_DEPTH_OK,
    STATE_QUOTE_OK,
    STATE_PRODUCTIVE_READY,
    STATE_QUARANTINED,
})

# Minimum effective depth USD for productive admission when depth is measured.
_DEFAULT_MIN_DEPTH_USD = 50.0

# Quote smoke statuses treated as OK for admission.
_QUOTE_OK_STATUSES = frozenset({
    "QUOTE_OK",
    "QUOTE_OK_INT128",
    "QUOTE_OK_UINT256",
    "ok",
    "OK",
})


def _depth_ok(route: Dict[str, Any], min_depth_usd: float) -> bool:
    depth = route.get("effective_depth_usd")
    if depth is None:
        return False
    try:
        return float(depth) >= min_depth_usd
    except (TypeError, ValueError):
        return False


def _quote_ok(route: Dict[str, Any]) -> bool:
    smoke = route.get("quote_smoke_status") or route.get("quote_smoke")
    if smoke in _QUOTE_OK_STATUSES:
        return True
    if route.get("quote_smoke_ok") is True:
        return True
    if route.get("last_quote_ok") is True:
        return True
    return False


def _is_quarantined(route: Dict[str, Any]) -> bool:
    if route.get("quarantined") is True:
        return True
    if route.get("pool_quality_state") == STATE_QUARANTINED:
        return True
    reason = (route.get("depth_reject_reason") or "").upper()
    if reason in ("TOXIC_PRICE_IMPACT", "QUARANTINED"):
        from m9.graph_arb.quarantine_depth_rca import is_false_positive_toxic_depth

        if is_false_positive_toxic_depth(route):
            return False
        return True
    return False


def compute_pool_quality_state(
    route: Dict[str, Any],
    *,
    min_depth_usd: float = _DEFAULT_MIN_DEPTH_USD,
    adapter_supported: Optional[bool] = None,
    provider_ok: bool = True,
) -> str:
    """Derive pool_quality_state from route fields (does not mutate route)."""
    if _is_quarantined(route):
        return STATE_QUARANTINED

    factory_ok = route.get("factory_verified") is True
    if adapter_supported is None:
        adapter_supported = bool(route.get("adapter_type")) and route.get("adapter_type") != "unknown"

    if not factory_ok:
        return STATE_DISCOVERED
    if not adapter_supported:
        return STATE_FACTORY_VERIFIED

    if not _depth_ok(route, min_depth_usd):
        return STATE_FACTORY_VERIFIED

    depth_state = STATE_DEPTH_OK
    if not _quote_ok(route):
        return depth_state

    if not provider_ok:
        return STATE_QUOTE_OK

    if productive_admission_ok(
        route,
        min_depth_usd=min_depth_usd,
        adapter_supported=adapter_supported,
        provider_ok=provider_ok,
    ):
        return STATE_PRODUCTIVE_READY
    return STATE_QUOTE_OK


def _is_distinct_pricing_route(route: Dict[str, Any]) -> bool:
    from m9.graph_arb.adapter_families import (
        FAMILY_BALANCER_VAULT,
        FAMILY_CURVE_STABLE,
        FAMILY_MAVERICK_V2,
        route_family,
    )

    family = route_family(route)
    return family in (FAMILY_MAVERICK_V2, FAMILY_BALANCER_VAULT, FAMILY_CURVE_STABLE)


def _expansion_admit_ok(route: Dict[str, Any]) -> bool:
    if route.get("expansion_productive_admit") is not False:
        return True
    from m9.graph_arb.expansion_admission import measured_depth_productive_override

    return measured_depth_productive_override(route)


def _depth_gate_ok(
    route: Dict[str, Any],
    min_depth_usd: float,
    *,
    economics_lane: bool = False,
) -> bool:
    """Depth required when measured; distinct unknown blocked only on economics lane."""
    import os

    from m9.graph_arb.depth_capacity_probe import DEPTH_PROBE_ANALYTICAL_SUSPECT
    from m9.graph_arb.expansion_admission import is_analytical_suspect_depth

    if route.get("depth_probe_status") == DEPTH_PROBE_ANALYTICAL_SUSPECT:
        return False
    if is_analytical_suspect_depth(route):
        return False

    require = str(os.environ.get("ARBY_PRODUCTIVE_REQUIRE_DEPTH", "")).strip().lower() in (
        "1",
        "true",
        "yes",
    )
    depth = route.get("effective_depth_usd")
    if depth is None:
        if require:
            return False
        if economics_lane and _is_distinct_pricing_route(route):
            return False
        return True
    return _depth_ok(route, min_depth_usd)


def productive_admission_fail_reason(
    route: Dict[str, Any],
    *,
    min_depth_usd: float = _DEFAULT_MIN_DEPTH_USD,
    adapter_supported: Optional[bool] = None,
    provider_ok: bool = True,
    require_quote_smoke: bool = False,
) -> Optional[str]:
    """First failing productive gate for a route, or None when admission would pass."""
    if _is_quarantined(route):
        return "quarantined"
    if route.get("factory_verified") is not True:
        return "not_factory_verified"
    if adapter_supported is None:
        adapter_supported = bool(route.get("adapter_type")) and route.get("adapter_type") != "unknown"
    if not adapter_supported:
        return "adapter_unsupported"
    if not _depth_gate_ok(route, min_depth_usd):
        return "missing_depth"
    if require_quote_smoke and not _quote_ok(route):
        return "quote_smoke_fail"
    if not provider_ok:
        return "provider_not_ok"
    if not _expansion_admit_ok(route):
        return "expansion_productive_admit_false"
    if route.get("depth_probe_status") == "ANALYTICAL_SUSPECT":
        return "analytical_suspect_depth"
    return None


def _maverick_has_direction_probe(route: Dict[str, Any]) -> bool:
    by_tin = route.get("maverick_probe_by_token_in")
    if isinstance(by_tin, dict) and by_tin:
        return True
    return bool(
        route.get("maverick_pool_lane_probe_amount")
        and route.get("maverick_pool_lane_token_in")
    )


def _balancer_productive_ready(route: Dict[str, Any]) -> Optional[str]:
    from m9.graph_arb.adapter_families import FAMILY_BALANCER_VAULT, balancer_route_metadata_complete, route_family
    from m9.graph_arb.expansion_admission import is_sane_measured_depth

    if route_family(route) != FAMILY_BALANCER_VAULT:
        return None
    if not balancer_route_metadata_complete(route):
        return "balancer_metadata_incomplete"
    prod_status = str(
        route.get("productive_quote_status") or route.get("quote_smoke_status") or ""
    )
    prod_ok = prod_status.startswith("QUOTE_OK")
    if not is_sane_measured_depth(route):
        return "missing_measured_depth"
    if not prod_ok:
        return "balancer_quote_smoke_fail"
    return None


def maverick_admission_fail_reason(route: Dict[str, Any]) -> Optional[str]:
    """Distinct-pricing Maverick gate detail when route fails productive admission."""
    base = productive_admission_fail_reason(route)
    if base:
        return base
    adapter = route.get("adapter_type") or ""
    dex = route.get("dex_id") or ""
    if adapter != "maverick_v2" and dex != "maverick_v2":
        return None
    token_a = str(route.get("token_a") or route.get("token_a_address") or "").lower()
    if not (token_a.startswith("0x") and len(token_a) == 42):
        return "missing_token_a"
    prod_status = str(
        route.get("productive_quote_status") or route.get("quote_smoke_status") or ""
    )
    prod_ok = prod_status.startswith("QUOTE_OK")
    from m9.graph_arb.expansion_admission import is_sane_measured_depth

    if not is_sane_measured_depth(route) and not prod_ok:
        return "missing_depth_or_quote_ok"
    return None


def productive_admission_ok(
    route: Dict[str, Any],
    *,
    min_depth_usd: float = _DEFAULT_MIN_DEPTH_USD,
    adapter_supported: Optional[bool] = None,
    provider_ok: bool = True,
    require_quote_smoke: bool = False,
) -> bool:
    """Data-driven productive gate for a single inventory route."""
    if _is_quarantined(route):
        return False
    if route.get("factory_verified") is not True:
        return False
    if adapter_supported is None:
        adapter_supported = bool(route.get("adapter_type")) and route.get("adapter_type") != "unknown"
    if not adapter_supported:
        return False
    if not _depth_gate_ok(route, min_depth_usd):
        return False
    if require_quote_smoke and not _quote_ok(route):
        return False
    if not provider_ok:
        return False
    if not _expansion_admit_ok(route):
        return False
    if route.get("depth_probe_status") == "ANALYTICAL_SUSPECT":
        return False
    return True


def economics_admission_fail_reason(route: Dict[str, Any]) -> Optional[str]:
    """Economics-lane gate (distinct depth + adapter quote readiness)."""
    if not _depth_gate_ok(route, _DEFAULT_MIN_DEPTH_USD, economics_lane=True):
        return "missing_depth"
    bal = _balancer_productive_ready(route)
    if bal:
        return bal
    mav = maverick_economics_admission_fail_reason(route)
    if mav:
        return mav
    return None


def balancer_economics_admission_fail_reason(route: Dict[str, Any]) -> Optional[str]:
    """Stricter Balancer gate for quote/economics (not graph topology)."""
    return _balancer_productive_ready(route)


def maverick_economics_admission_fail_reason(route: Dict[str, Any]) -> Optional[str]:
    """Direction probe required before Maverick economics quotes."""
    adapter = route.get("adapter_type") or ""
    dex = route.get("dex_id") or ""
    if adapter != "maverick_v2" and dex != "maverick_v2":
        return None
    if not _maverick_has_direction_probe(route):
        return "missing_maverick_probe_by_token_in"
    return None


def _productive_admission_block_reason(
    route: Dict[str, Any],
    *,
    min_depth_usd: float = _DEFAULT_MIN_DEPTH_USD,
) -> Optional[str]:
    """Honest reason when route is not PRODUCTIVE_READY."""
    if _is_quarantined(route):
        return "quarantined"
    if route.get("factory_verified") is not True:
        return "factory_not_verified"
    if not _depth_ok(route, min_depth_usd):
        dr = str(route.get("depth_reject_reason") or "").upper()
        if dr:
            from m9.graph_arb.depth_telemetry import classify_depth_reject_class

            return f"depth_{classify_depth_reject_class(dr)}"
        if route.get("effective_depth_usd") is None:
            return "depth_unknown"
        return "depth_below_floor"
    if not _quote_ok(route):
        smoke = route.get("quote_smoke_status") or route.get("quote_smoke")
        if smoke is None:
            return "quote_smoke_not_run"
        return f"quote_smoke_{smoke}"
    return None


def annotate_route_pool_quality(
    route: Dict[str, Any],
    *,
    min_depth_usd: float = _DEFAULT_MIN_DEPTH_USD,
    provider_ok: bool = True,
) -> str:
    """Write pool_quality_state (+ admission flags) on route; return state."""
    from m9.graph_arb.quarantine_depth_rca import is_false_positive_toxic_depth

    if is_false_positive_toxic_depth(route):
        route["depth_reprobe_required"] = True
        route["depth_quarantine_class"] = "diagnostic_soft"
    state = compute_pool_quality_state(
        route,
        min_depth_usd=min_depth_usd,
        provider_ok=provider_ok,
    )
    route["pool_quality_state"] = state
    route["productive_admission_ok"] = state == STATE_PRODUCTIVE_READY
    route["depth_ok"] = _depth_ok(route, min_depth_usd)
    route["quote_ok"] = _quote_ok(route)
    block_reason = _productive_admission_block_reason(route, min_depth_usd=min_depth_usd)
    if block_reason:
        route["productive_admission_block_reason"] = block_reason
    return state


def annotate_routes_pool_quality(
    routes: list[Dict[str, Any]],
    *,
    min_depth_usd: float = _DEFAULT_MIN_DEPTH_USD,
    provider_ok: bool = True,
) -> Dict[str, int]:
    """Annotate all routes; return histogram by state."""
    hist: Dict[str, int] = {}
    for route in routes:
        st = annotate_route_pool_quality(
            route, min_depth_usd=min_depth_usd, provider_ok=provider_ok
        )
        hist[st] = hist.get(st, 0) + 1
    return hist


def productive_admission_histogram(routes: list[Dict[str, Any]]) -> Dict[str, int]:
    """Count routes by pool_quality_state (expects annotation)."""
    hist: Dict[str, int] = {}
    for route in routes:
        st = route.get("pool_quality_state") or STATE_DISCOVERED
        hist[st] = hist.get(st, 0) + 1
    return hist
