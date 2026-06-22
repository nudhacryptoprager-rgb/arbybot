"""M8.3 pool identity preflight (static route/pool truth, no quote/depth)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from m8.metadata.dex.base import route_dex_family, route_id_of
from m8.metadata.registry import is_valid_eth_address


def build_pool_identity_entry(
    route: Dict[str, Any],
    *,
    dex_route_row: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Pool identity metadata for one route."""
    rid = route_id_of(route)
    dex_meta = (dex_route_row or {}).get("metadata") or {}
    adapter = route_dex_family(route)
    token_order = (
        dex_meta.get("token_order")
        or dex_meta.get("tokens_order")
        or route.get("balancer_assets")
        or []
    )
    if not token_order:
        t0 = route.get("token0_addr")
        t1 = route.get("token1_addr")
        if is_valid_eth_address(t0) and is_valid_eth_address(t1):
            token_order = [t0, t1]

    token_order_verified = bool(
        (dex_route_row or {}).get("ready")
        and len(token_order) >= 2
        and adapter not in ("unknown", "")
    )

    factory_verified = route.get("factory_verified")
    factory_source = (
        route.get("factory")
        or route.get("factory_address")
        or route.get("dex_id")
        or dex_meta.get("factory_source")
    )

    return {
        "route_id": rid,
        "pool_address": route.get("pool_address"),
        "pool_id": route.get("pool_id") or dex_meta.get("pool_id"),
        "factory_verified": factory_verified,
        "factory_source": factory_source,
        "created_from_supported_factory": factory_verified is True,
        "pool_type": adapter,
        "pool_code_hash": route.get("pool_code_hash"),
        "creation_block": route.get("creation_block") or route.get("block_number"),
        "creation_source": route.get("source") or route.get("m8_provenance"),
        "token_order_verified": token_order_verified,
        "token_order": list(token_order) if isinstance(token_order, list) else token_order,
        "fee": route.get("fee") or dex_meta.get("fee"),
        "tick_spacing": route.get("tick_spacing") or (dex_meta.get("pool_key") or {}).get(
            "tick_spacing"
        ),
        "hooks": route.get("hooks") or (dex_meta.get("pool_key") or {}).get("hooks"),
        "coin_indices": dex_meta.get("coin_indices") or route.get("coin_indices"),
        "dex_worker_id": (dex_route_row or {}).get("worker_id"),
        "dex_metadata_ready": bool((dex_route_row or {}).get("ready")),
    }


def build_pool_identity_metadata(
    routes: List[Dict[str, Any]],
    dex_by_route: Dict[str, Dict[str, Any]],
    *,
    scopes: Optional[Dict[str, Set[str]]] = None,
) -> Dict[str, Any]:
    """Aggregate pool identity section for rolling artifact."""
    by_route: Dict[str, Dict[str, Any]] = {}
    for route in routes:
        rid = route_id_of(route)
        if not rid:
            continue
        by_route[rid] = build_pool_identity_entry(route, dex_route_row=dex_by_route.get(rid))

    coverage: Dict[str, Any] = {}
    for scope, ids in (scopes or {}).items():
        scoped = [r for r in routes if route_id_of(r) in ids] if ids else routes
        total = len(scoped)
        verified = sum(
            1
            for r in scoped
            if by_route.get(route_id_of(r), {}).get("token_order_verified")
            and by_route.get(route_id_of(r), {}).get("dex_metadata_ready")
        )
        coverage[scope] = {
            "routes_count": total,
            "pool_identity_verified_count": verified,
            "pool_identity_verified_rate": round(verified / total, 4) if total else 0.0,
        }

    return {"by_route_id": by_route, "coverage": coverage}
