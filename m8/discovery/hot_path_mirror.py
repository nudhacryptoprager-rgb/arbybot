"""Hot-path mirror resolve (Phase 4 skeleton).

WS new-pool event -> single token/anchor pair -> immediate M8.2 mirror-resolve
without scanning the full registry batch.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from m8.discovery.cross_dex_expand import expand_cross_dex


def resolve_mirrors_for_token(
    *,
    chain: str,
    config: Dict[str, Any],
    registry: Optional[Dict[str, Any]],
    exotic_address: str,
    exotic_symbol: str,
    anchor_symbol: str,
    anchor_artifact: Optional[Dict[str, Any]] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Run M8.2 expansion scoped to one exotic token (hot-path)."""
    t0 = time.perf_counter()
    art = expand_cross_dex(
        chain=chain,
        config=config,
        registry=registry,
        anchor_artifact=anchor_artifact,
        dry_run=dry_run,
        exotic_address_filter=exotic_address,
    )
    latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
    summary = art.get("summary") or {}
    routes = list(art.get("routes_admitted") or [])
    token_rows = [
        t
        for t in (art.get("tokens") or [])
        if (t.get("exotic_address") or "").lower() == exotic_address.lower()
    ]
    cross_mechanic = bool(summary.get("cross_mechanic_tokens", 0))
    return {
        "chain": chain,
        "exotic_address": exotic_address.lower(),
        "exotic_symbol": exotic_symbol,
        "anchor_symbol": anchor_symbol,
        "hot_path_mirror_resolve_latency_ms": latency_ms,
        "routes_admitted": routes,
        "routes_admitted_count": len(routes),
        "cross_mechanic": cross_mechanic,
        "venues_quoteable": token_rows[0].get("venues_quoteable") if token_rows else 0,
        "summary": summary,
        "reject_reason_histogram": art.get("reject_reason_histogram") or {},
    }


def resolve_from_sniper_event(
    event: Dict[str, Any],
    *,
    chain: str,
    config: Dict[str, Any],
    registry: Optional[Dict[str, Any]],
    anchor_artifact: Optional[Dict[str, Any]] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Map a sniper pool event dict to hot-path mirror resolve."""
    exotic_addr = (event.get("token0") or event.get("token0_addr") or "").lower()
    exotic_sym = event.get("token0_symbol") or ""
    anchor_sym = event.get("token1_symbol") or "USDC"
    t0s, t1s = event.get("token0_symbol", ""), event.get("token1_symbol", "")
    if t1s in ("USDC", "USDBC", "DAI", "WETH"):
        exotic_addr = (event.get("token0") or event.get("token0_addr") or exotic_addr).lower()
        exotic_sym = t0s
        anchor_sym = t1s
    elif t0s in ("USDC", "USDBC", "DAI", "WETH"):
        exotic_addr = (event.get("token1") or event.get("token1_addr") or exotic_addr).lower()
        exotic_sym = t1s
        anchor_sym = t0s
    return resolve_mirrors_for_token(
        chain=chain,
        config=config,
        registry=registry,
        exotic_address=exotic_addr,
        exotic_symbol=exotic_sym,
        anchor_symbol=anchor_sym,
        anchor_artifact=anchor_artifact,
        dry_run=dry_run,
    )
