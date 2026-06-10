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

DISTINCT_PRICING_DEXES: frozenset[str] = frozenset(
    {"curve_stable", "balancer_vault", "maverick_v2"}
)

_ANCHOR_SYMBOLS = frozenset(
    {"USDC", "EURC", "WETH", "cbBTC", "WETH_BASE", "DAI", "USDT", "USDbC"}
)

_VERIFIED_ROUTE_STATUSES = frozenset({"active", "verified", "quote_ok"})


def route_m8_token_match(
    route: Dict[str, Any],
    m8_token_addrs: Optional[Set[str]] = None,
) -> bool:
    if route.get("matched_m8_token"):
        return True
    if not m8_token_addrs:
        return False
    for key in (
        "focus_token_address",
        "token0_addr",
        "token1_addr",
        "exotic_address",
    ):
        a = str(route.get(key) or "").lower()
        if a in m8_token_addrs:
            return True
    return False


def route_has_verified_evidence(route: Dict[str, Any]) -> bool:
    status = str(route.get("status") or "active").lower()
    if status in _VERIFIED_ROUTE_STATUSES:
        return True
    if route.get("factory_verified"):
        return True
    hint = str(route.get("hint_status") or "")
    if hint and "VERIFIED" in hint.upper():
        return True
    if route.get("quote_smoke_status") or route.get("productive_quote_status"):
        return True
    return False


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
    if existing in CANONICAL_ORIGINS:
        return str(existing)
    if existing == ORIGIN_EXPLORATION and route_m8_token_match(route, m8_token_addrs):
        pass  # re-classify below

    if route.get("source") == "m8_sniper":
        return ORIGIN_M8_SNIPER

    in_m8 = route_m8_token_match(route, m8_token_addrs)
    dex_id = str(route.get("dex_id") or "")
    resolve = str(route.get("resolve_source") or "")

    if in_m8 and (
        resolve == "specialized_index"
        or dex_id in DISTINCT_PRICING_DEXES
        or route.get("expansion_source") == "specialized_index"
    ):
        return ORIGIN_SPECIALIZED_INDEX_FOR_M8_TOKEN

    hint_status = str(route.get("hint_status") or "")
    if route.get("hint_source") or hint_status:
        return ORIGIN_M8_WATCHLIST_HINT if in_m8 else ORIGIN_EXPLORATION

    if route.get("source") == "m8_cross_dex_expansion":
        if in_m8 or route.get("promoted_from_registry"):
            return ORIGIN_M8_WATCHLIST_HINT
        return ORIGIN_EXPLORATION

    if route.get("metadata_seeded") or route.get("source") in (
        "adapter_metadata",
        "curve_factory_discovery",
    ):
        return ORIGIN_SPECIALIZED_INDEX_FOR_M8_TOKEN if in_m8 else ORIGIN_EXPLORATION

    if in_m8:
        return ORIGIN_M8_WATCHLIST_HINT
    return ORIGIN_EXPLORATION


def stamp_route_origin_source(
    route: Dict[str, Any],
    m8_token_addrs: Optional[Set[str]] = None,
) -> str:
    matched = route_m8_token_match(route, m8_token_addrs)
    route["matched_m8_token"] = matched
    origin = infer_origin_source(route, m8_token_addrs)
    if matched and str(route.get("dex_id") or "") in DISTINCT_PRICING_DEXES:
        origin = ORIGIN_SPECIALIZED_INDEX_FOR_M8_TOKEN
    route["origin_source"] = origin
    return origin


def is_canonical_bridge_route(
    route: Dict[str, Any],
    m8_token_addrs: Optional[Set[str]] = None,
) -> bool:
    """Canonical M9 bridge admission: M8-derived + verified evidence."""
    origin = stamp_route_origin_source(route, m8_token_addrs)
    if origin not in CANONICAL_ORIGINS:
        return False
    if origin == ORIGIN_SPECIALIZED_INDEX_FOR_M8_TOKEN:
        if not route.get("matched_m8_token"):
            return False
        if not route_has_verified_evidence(route):
            return False
    return True


def partition_canonical_routes(
    routes: List[Dict[str, Any]],
    m8_token_addrs: Optional[Set[str]] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Split routes into canonical (M8-derived) vs exploration."""
    canonical: List[Dict[str, Any]] = []
    exploration: List[Dict[str, Any]] = []
    for route in routes:
        if is_canonical_bridge_route(route, m8_token_addrs):
            canonical.append(route)
        else:
            stamp_route_origin_source(route, m8_token_addrs)
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
