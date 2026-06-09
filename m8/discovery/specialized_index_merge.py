"""Merge Balancer/Maverick rolling index routes into M8.2 expansion."""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List, Optional, Set, Tuple

def secondary_watchlist_tokens(
    *,
    external_hints_artifact: Optional[Dict[str, Any]] = None,
    mirror_index: Any = None,
) -> Set[str]:
    """Pool-member tokens from verified hints + specialized indices."""
    out: Set[str] = set()
    if external_hints_artifact:
        for pool in (external_hints_artifact.get("pools") or []):
            if not isinstance(pool, dict):
                continue
            if str(pool.get("hint_status") or "").startswith("HINT_"):
                if "VERIFIED" not in str(pool.get("hint_status") or ""):
                    continue
            for key in ("token0_addr", "token1_addr", "focus_token", "base_token"):
                addr = str(pool.get(key) or "").lower()
                if addr.startswith("0x"):
                    out.add(addr)
    if mirror_index is not None:
        for ent in getattr(mirror_index, "balancer", []) or []:
            out.update(ent.assets)
        for ent in getattr(mirror_index, "maverick", []) or []:
            out.add(ent.token_a)
            out.add(ent.token_b)
    return out


def specialized_index_routes_for_token(
    mirror_index: Any,
    token_addr: str,
    *,
    allowed_dex_ids: Set[str],
    productive_dexes: Set[str],
    focus_sym: str = "",
) -> List[Dict[str, Any]]:
    """token_presence routes from rolling Balancer/Maverick indices only."""
    from m8.discovery.cross_dex_expand import _build_route

    token_addr = token_addr.lower()
    pools = mirror_index.find_pools_containing_token(
        token_addr,
        dex_ids=allowed_dex_ids & {"balancer_vault", "maverick_v2"},
        max_results_per_dex=8,
    )
    routes: List[Dict[str, Any]] = []
    for pool_entry in pools:
        dex = str(pool_entry.get("dex_id") or "")
        if dex not in ("balancer_vault", "maverick_v2"):
            continue
        pool_entry = {
            **pool_entry,
            "focus_token_address": token_addr,
            "focus_token_symbol": focus_sym or token_addr[:8],
            "resolve_source": "specialized_index",
        }
        conn = str(pool_entry.get("connector_token") or pool_entry.get("token1_symbol") or "")
        routes.append(
            _build_route(
                {
                    "exotic_symbol": focus_sym or "T",
                    "anchor_symbol": conn or "C",
                    "exotic_address": token_addr,
                    "focus_token_address": token_addr,
                    "focus_token_symbol": focus_sym or token_addr[:8],
                },
                pool_entry,
                productive=dex in productive_dexes,
            )
        )
    return routes


def merge_specialized_index_batch(
    *,
    mirror_index: Any,
    token_addrs: List[str],
    reg_tokens: Dict[str, Any],
    allowed_dex_ids: Set[str],
    productive_dexes: Set[str],
    secondary_tokens: Set[str],
    seen_route_keys: Set[Tuple[str, str, str, str]],
    routes_admitted: List[Dict[str, Any]],
    token_presence_routes: List[Dict[str, Any]],
) -> Dict[str, int]:
    """Admit specialized_index routes for registry + secondary watchlist tokens."""
    merged_tokens: List[str] = []
    seen_tok: Set[str] = set()
    for addr in list(token_addrs) + sorted(secondary_tokens):
        low = str(addr).lower()
        if not low.startswith("0x") or low in seen_tok:
            continue
        seen_tok.add(low)
        merged_tokens.append(low)

    counts: Counter[str] = Counter()
    for addr in merged_tokens:
        sym = str((reg_tokens.get(addr) or {}).get("symbol") or addr[:8])
        for route in specialized_index_routes_for_token(
            mirror_index,
            addr,
            allowed_dex_ids=allowed_dex_ids,
            productive_dexes=productive_dexes,
            focus_sym=sym,
        ):
            key = (
                route.get("dex_id", ""),
                str(route.get("pool_address", "")).lower(),
                str(route.get("token0_addr", "")).lower(),
                str(route.get("token1_addr", "")).lower(),
            )
            if key in seen_route_keys:
                continue
            seen_route_keys.add(key)
            route["expansion_source"] = "specialized_index"
            token_presence_routes.append(route)
            routes_admitted.append(route)
            counts[str(route.get("dex_id") or "")] += 1
    return dict(counts)


def merge_connector_routes_from_presence(
    *,
    chain: str,
    config: Dict[str, Any],
    mirror_index: Any,
    resolver: Any,
    dex_rows: List[Dict[str, Any]],
    allowed_dex_ids: Set[str],
    productive_dexes: Set[str],
    token_presence_routes: List[Dict[str, Any]],
    seen_route_keys: Set[Tuple[str, str, str, str]],
    routes_admitted: List[Dict[str, Any]],
    connector_routes: List[Dict[str, Any]],
    dry_run: bool = False,
) -> int:
    """For specialized T-C routes, synthesize C-anchor connector hops."""
    from m8.discovery.cross_dex_expand import (
        _anchor_symbols_from_config,
        _build_route,
        _resolve_via_factory,
        _token_address_from_config,
    )

    anchor_syms = _anchor_symbols_from_config(config)
    connectors: Dict[str, str] = {}
    for route in token_presence_routes:
        if route.get("expansion_source") != "specialized_index":
            continue
        conn_addr = str(route.get("connector_addr") or route.get("token1_addr") or "").lower()
        conn_sym = str(route.get("connector_token") or route.get("token1_symbol") or conn_addr[:8])
        if conn_addr.startswith("0x") and conn_sym not in anchor_syms:
            connectors[conn_addr] = conn_sym

    added = 0
    for conn_addr, conn_sym in connectors.items():
        for anchor_sym in sorted(anchor_syms):
            if conn_sym == anchor_sym:
                continue
            found, _reason = _resolve_via_factory(
                chain,
                "uniswap_v3",
                conn_sym,
                anchor_sym,
                exotic_address=conn_addr,
                anchor_address=_token_address_from_config(config, anchor_sym),
                dry_run=dry_run,
                resolver=resolver,
                mirror_index=mirror_index,
                config=config,
            )
            if not found:
                for dex in dex_rows:
                    dex_id = dex["dex_id"]
                    if dex_id not in allowed_dex_ids:
                        continue
                    found, _reason = _resolve_via_factory(
                        chain,
                        dex_id,
                        conn_sym,
                        anchor_sym,
                        exotic_address=conn_addr,
                        anchor_address=_token_address_from_config(config, anchor_sym),
                        dry_run=dry_run,
                        resolver=resolver,
                        mirror_index=mirror_index,
                        config=config,
                    )
                    if found:
                        break
            if not found:
                continue
            found["expansion_route_kind"] = "connector_hop"
            found["expansion_source"] = "specialized_index"
            route = _build_route(
                {
                    "exotic_symbol": conn_sym,
                    "anchor_symbol": anchor_sym,
                    "exotic_address": conn_addr,
                    "focus_token_address": conn_addr,
                    "focus_token_symbol": conn_sym,
                },
                found,
                productive=str(found.get("dex_id") or "") in productive_dexes,
            )
            key = (
                route.get("dex_id", ""),
                str(route.get("pool_address", "")).lower(),
                str(route.get("token0_addr", "")).lower(),
                str(route.get("token1_addr", "")).lower(),
            )
            if key in seen_route_keys:
                continue
            seen_route_keys.add(key)
            connector_routes.append(route)
            routes_admitted.append(route)
            added += 1
    return added
