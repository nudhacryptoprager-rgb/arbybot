"""M8-rooted data provenance for M8.2 / M9 routes."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

ORIGIN_M8_SNIPER = "m8_sniper"
ORIGIN_M8_WATCHLIST_HINT = "m8_watchlist_hint"
ORIGIN_SPECIALIZED_INDEX_FOR_M8_TOKEN = "specialized_index_for_m8_token"
ORIGIN_EXPLORATION = "exploration"

CANONICAL_ORIGINS: frozenset[str] = frozenset(
    {
        ORIGIN_M8_SNIPER,
        ORIGIN_M8_WATCHLIST_HINT,
        ORIGIN_SPECIALIZED_INDEX_FOR_M8_TOKEN,
    }
)

_ANCHOR_SYMBOLS = frozenset(
    {"USDC", "EURC", "WETH", "cbBTC", "WETH_BASE", "DAI", "USDT", "USDbC"}
)


def collect_m8_token_addrs(
    *,
    sniper: Optional[Dict[str, Any]] = None,
    registry: Optional[Dict[str, Any]] = None,
    watchlist_path: Optional[str] = None,
) -> Set[str]:
    """Union of token addresses from sniper events, pending registry, watchlist."""
    addrs: Set[str] = set()
    for ev in (sniper or {}).get("recent_events") or []:
        for key in ("token0", "token1"):
            a = str(ev.get(key) or "").lower()
            if a.startswith("0x") and len(a) == 42:
                addrs.add(a)
    prov = (sniper or {}).get("provenance") or {}
    for a in prov.get("candidate_token_addrs") or []:
        if str(a).lower().startswith("0x"):
            addrs.add(str(a).lower())
    if registry:
        for tok in (registry.get("tokens") or {}):
            if str(tok).lower().startswith("0x"):
                addrs.add(str(tok).lower())
    if watchlist_path:
        p = Path(watchlist_path)
        if p.exists():
            try:
                wl = json.loads(p.read_text(encoding="utf-8"))
                for tok in (wl.get("tokens") or {}):
                    if str(tok).lower().startswith("0x"):
                        addrs.add(str(tok).lower())
            except (json.JSONDecodeError, OSError):
                pass
    return addrs


def infer_origin_source(
    route: Dict[str, Any],
    m8_token_addrs: Optional[Set[str]] = None,
) -> str:
    """Classify route provenance without mutating the route."""
    existing = route.get("origin_source")
    if existing in CANONICAL_ORIGINS or existing == ORIGIN_EXPLORATION:
        return str(existing)

    if route.get("source") == "m8_sniper":
        return ORIGIN_M8_SNIPER

    focus = str(
        route.get("focus_token_address")
        or route.get("token0_addr")
        or route.get("token1_addr")
        or ""
    ).lower()
    in_m8 = bool(m8_token_addrs and focus and focus in m8_token_addrs)

    hint_status = str(route.get("hint_status") or "")
    if route.get("hint_source") or hint_status:
        return ORIGIN_M8_WATCHLIST_HINT if in_m8 else ORIGIN_EXPLORATION

    resolve = str(route.get("resolve_source") or "")
    if resolve == "specialized_index":
        return (
            ORIGIN_SPECIALIZED_INDEX_FOR_M8_TOKEN if in_m8 else ORIGIN_EXPLORATION
        )

    if route.get("source") == "m8_cross_dex_expansion":
        if in_m8 or route.get("promoted_from_registry"):
            return ORIGIN_M8_WATCHLIST_HINT
        return ORIGIN_EXPLORATION

    if route.get("metadata_seeded") or route.get("source") in (
        "adapter_metadata",
        "curve_factory_discovery",
    ):
        return ORIGIN_EXPLORATION

    # Base verified inventory: canonical only when tied to M8 context token
    if in_m8:
        return ORIGIN_M8_WATCHLIST_HINT
    return ORIGIN_EXPLORATION


def stamp_route_origin_source(
    route: Dict[str, Any],
    m8_token_addrs: Optional[Set[str]] = None,
) -> str:
    origin = infer_origin_source(route, m8_token_addrs)
    route["origin_source"] = origin
    if m8_token_addrs and route.get("focus_token_address"):
        route["matched_m8_token"] = (
            str(route.get("focus_token_address", "")).lower() in m8_token_addrs
        )
    return origin


def partition_canonical_routes(
    routes: List[Dict[str, Any]],
    m8_token_addrs: Optional[Set[str]] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Split routes into canonical (M8-derived) vs exploration."""
    canonical: List[Dict[str, Any]] = []
    exploration: List[Dict[str, Any]] = []
    for route in routes:
        origin = stamp_route_origin_source(route, m8_token_addrs)
        if origin in CANONICAL_ORIGINS:
            canonical.append(route)
        else:
            exploration.append(route)
    return canonical, exploration


def build_sniper_provenance_from_events(
    events: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    """Top-level sniper provenance block from recent_events."""
    candidate_addrs: Set[str] = set()
    anchor_addrs: Set[str] = set()
    for ev in events:
        t0 = str(ev.get("token0") or "").lower()
        t1 = str(ev.get("token1") or "").lower()
        s0 = str(ev.get("token0_symbol") or "")
        s1 = str(ev.get("token1_symbol") or "")
        for addr, sym in ((t0, s0), (t1, s1)):
            if not addr.startswith("0x"):
                continue
            if sym in _ANCHOR_SYMBOLS:
                anchor_addrs.add(addr)
            else:
                candidate_addrs.add(addr)
        candidate_addrs.discard("0x0000000000000000000000000000000000000000")
    return {
        "candidate_token_addrs": sorted(candidate_addrs),
        "anchor_token_addrs": sorted(anchor_addrs),
        "primary_source": ORIGIN_M8_SNIPER,
    }
