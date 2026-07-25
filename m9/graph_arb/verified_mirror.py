"""Verified mirror pool identification — stricter than matched_m8_token alone."""
from __future__ import annotations

from typing import Any, Mapping

_QUOTE_OK_PREFIXES = ("QUOTE_OK", "OK", "PASS", "SUCCESS")


def _status_quoteable(status: Any) -> bool:
    qss = str(status or "")
    if not qss:
        return False
    upper = qss.upper()
    return any(upper.startswith(p) for p in _QUOTE_OK_PREFIXES)


def is_mirror_topology_ready_diagnostic(route: Mapping[str, Any]) -> bool:
    """Topology readiness alone — diagnostic signal, not verified-quote mirror."""
    return route.get("mirror_topology_ready") is True


def is_verified_mirror_route(route: Mapping[str, Any]) -> bool:
    """Factory-verified mirror with quote-ready confirmation — not topology-only."""
    if route.get("source") == "m8_sniper":
        return False
    if route.get("factory_verified") is not True:
        return False
    if not route.get("matched_m8_token"):
        return False
    smoke = route.get("productive_quote_status") or route.get("quote_smoke_status")
    if _status_quoteable(smoke):
        return True
    if route.get("mirror_quote_ready") is True:
        return True
    return False


def verified_mirror_pool_addrs(routes: Any) -> frozenset[str]:
    out = set()
    for route in routes or []:
        if not isinstance(route, dict):
            continue
        if not is_verified_mirror_route(route):
            continue
        pool = str(route.get("pool_address") or "").lower()
        if pool:
            out.add(pool)
    return frozenset(out)


def direct_sniper_pool_addrs(routes: Any) -> frozenset[str]:
    return frozenset(
        str(r.get("pool_address", "")).lower()
        for r in (routes or [])
        if isinstance(r, dict)
        and r.get("source") == "m8_sniper"
        and r.get("pool_address")
    )
