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


def _depth_gate_ok(route: Dict[str, Any], min_depth_usd: float) -> bool:
    """Depth required only when measured or ARBY_PRODUCTIVE_REQUIRE_DEPTH=1."""
    import os

    require = str(os.environ.get("ARBY_PRODUCTIVE_REQUIRE_DEPTH", "")).strip().lower() in (
        "1",
        "true",
        "yes",
    )
    depth = route.get("effective_depth_usd")
    if depth is None:
        return not require
    return _depth_ok(route, min_depth_usd)


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
    if route.get("expansion_productive_admit") is False:
        return False
    return True


def annotate_route_pool_quality(
    route: Dict[str, Any],
    *,
    min_depth_usd: float = _DEFAULT_MIN_DEPTH_USD,
    provider_ok: bool = True,
) -> str:
    """Write pool_quality_state (+ admission flags) on route; return state."""
    state = compute_pool_quality_state(
        route,
        min_depth_usd=min_depth_usd,
        provider_ok=provider_ok,
    )
    route["pool_quality_state"] = state
    route["productive_admission_ok"] = state == STATE_PRODUCTIVE_READY
    route["depth_ok"] = _depth_ok(route, min_depth_usd)
    route["quote_ok"] = _quote_ok(route)
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
