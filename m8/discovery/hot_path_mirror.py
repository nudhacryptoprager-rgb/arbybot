"""Hot-path mirror resolve — token-neighborhood expansion per M8 event."""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

from m8.discovery.anchor_registry import (
    is_anchor_address,
    is_anchor_symbol,
    quote_anchor_maps,
    symbol_for_address,
)
from m8.discovery.cross_dex_expand import expand_cross_dex
from m8.discovery.pending_pair_registry import _ANCHOR_TOKENS, split_token_anchor


def split_token_anchor_from_event(
    event: Dict[str, Any],
    config: Optional[Dict[str, Any]] = None,
) -> Optional[Tuple[str, str, str]]:
    """(exotic_addr, exotic_symbol, anchor_symbol) when one side is anchor."""
    split = split_token_anchor(event, _ANCHOR_TOKENS)
    if split is not None:
        return split
    quote_addr, _ = quote_anchor_maps(config or {})
    t0a = (event.get("token0") or "").lower()
    t1a = (event.get("token1") or "").lower()
    t0s = event.get("token0_symbol") or ""
    t1s = event.get("token1_symbol") or ""
    if is_anchor_address(t0a, quote_addr) and t1a and not is_anchor_address(t1a, quote_addr):
        return t1a, t1s or t1a[:10], symbol_for_address(t0a, quote_addr) or t0s
    if is_anchor_address(t1a, quote_addr) and t0a and not is_anchor_address(t0a, quote_addr):
        return t0a, t0s or t0a[:10], symbol_for_address(t1a, quote_addr) or t1s
    return None


def candidate_tokens_from_event(
    event: Dict[str, Any],
    config: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, str]]:
    """Non-anchor token(s) from a pool event — focus candidates for neighborhood."""
    quote_addr, quote_syms = quote_anchor_maps(config or {})
    seen: set[str] = set()
    out: List[Dict[str, str]] = []
    for addr_key, sym_key in (
        ("token0", "token0_symbol"),
        ("token1", "token1_symbol"),
    ):
        addr = (event.get(addr_key) or event.get(f"{addr_key}_addr") or "").lower()
        sym = str(event.get(sym_key) or "")
        if not addr.startswith("0x") or len(addr) != 42:
            continue
        if is_anchor_address(addr, quote_addr) or is_anchor_symbol(sym, quote_syms):
            continue
        if addr in seen:
            continue
        seen.add(addr)
        out.append({"address": addr, "symbol": sym or addr[:10]})
    return out


def subgraph_candidate_score(row: Dict[str, Any]) -> Tuple[int, int, int, int]:
    """Rank neighborhood results: subgraph_ready, routes, dexes, connectors."""
    return (
        1 if row.get("subgraph_ready") else 0,
        int(row.get("routes_admitted_count") or 0),
        int(row.get("token_seen_on_dexes") or 0),
        len(row.get("connector_tokens") or []),
    )


def resolve_mirrors_for_token(
    *,
    chain: str,
    config: Dict[str, Any],
    registry: Optional[Dict[str, Any]],
    exotic_address: str,
    exotic_symbol: str = "",
    anchor_symbol: Optional[str] = None,
    anchor_artifact: Optional[Dict[str, Any]] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Run M8.2 token-neighborhood expansion for one focus token (anchor optional)."""
    t0 = time.perf_counter()
    art = expand_cross_dex(
        chain=chain,
        config=config,
        registry=registry,
        anchor_artifact=anchor_artifact,
        dry_run=dry_run,
        exotic_address_filter=exotic_address,
        expansion_mode="token_neighborhood",
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
    subgraph = (token_rows[0].get("subgraph") if token_rows else None) or {}
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
        "same_pair_routes_count": summary.get("same_pair_routes_count", 0),
        "token_presence_routes_count": summary.get("token_presence_routes_count", 0),
        "connector_routes_count": summary.get("connector_routes_count", 0),
        "connector_tokens": art.get("connector_tokens") or [],
        "token_seen_on_dexes": summary.get("token_seen_on_dexes", 0),
        "subgraph_ready": summary.get("subgraph_ready", False),
        "subgraph": subgraph,
        "summary": summary,
        "reject_reason_histogram": art.get("reject_reason_histogram") or {},
    }


def resolve_best_neighborhood_for_event(
    event: Dict[str, Any],
    *,
    chain: str,
    config: Dict[str, Any],
    registry: Optional[Dict[str, Any]],
    anchor_artifact: Optional[Dict[str, Any]] = None,
    dry_run: bool = False,
) -> Tuple[Optional[Dict[str, Any]], str]:
    """Try token-neighborhood for each non-anchor event token; return best subgraph."""
    candidates = candidate_tokens_from_event(event, config)
    if not candidates:
        return None, "REJECT_NO_CANDIDATE_TOKEN"

    split = split_token_anchor_from_event(event, config)
    anchor_sym = split[2] if split else None

    best_row: Optional[Dict[str, Any]] = None
    best_score: Tuple[int, int, int, int] = (-1, -1, -1, -1)
    best_focus: Optional[Dict[str, str]] = None
    best_reason = "SUBGRAPH_TOO_SMALL"

    for cand in candidates:
        row = resolve_mirrors_for_token(
            chain=chain,
            config=config,
            registry=registry,
            exotic_address=cand["address"],
            exotic_symbol=cand["symbol"],
            anchor_symbol=anchor_sym,
            anchor_artifact=anchor_artifact,
            dry_run=dry_run,
        )
        score = subgraph_candidate_score(row)
        if score > best_score:
            best_score = score
            best_row = row
            best_focus = cand
            if row.get("subgraph_ready"):
                best_reason = "subgraph_ready"
            elif row.get("reject_reason_histogram", {}).get("TOKEN_NOT_SEEN_ELSEWHERE"):
                best_reason = "TOKEN_NOT_SEEN_ELSEWHERE"
            elif row.get("reject_reason_histogram", {}).get("CONNECTOR_NOT_FOUND"):
                best_reason = "CONNECTOR_NOT_FOUND"
            else:
                best_reason = "SUBGRAPH_TOO_SMALL"

    if best_row is None or best_focus is None:
        return None, "REJECT_NO_CANDIDATE_TOKEN"

    if best_row.get("subgraph_ready"):
        focus_reason = "subgraph_ready"
    elif best_score[1] > 0:
        focus_reason = "best_partial_subgraph"
    else:
        focus_reason = best_reason

    best_row = {
        **best_row,
        "event_candidate_tokens": candidates,
        "selected_focus_token": best_focus["address"],
        "selected_focus_symbol": best_focus["symbol"],
        "selected_focus_reason": focus_reason,
    }
    return best_row, focus_reason if best_row.get("subgraph_ready") else best_reason


def resolve_from_sniper_event(
    event: Dict[str, Any],
    *,
    chain: str,
    config: Dict[str, Any],
    registry: Optional[Dict[str, Any]],
    anchor_artifact: Optional[Dict[str, Any]] = None,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Map a sniper pool event dict to best token-neighborhood resolve."""
    row, _reason = resolve_best_neighborhood_for_event(
        event,
        chain=chain,
        config=config,
        registry=registry,
        anchor_artifact=anchor_artifact,
        dry_run=dry_run,
    )
    if row is None:
        return {
            "reject_reason": "REJECT_NO_CANDIDATE_TOKEN",
            "routes_admitted": [],
            "routes_admitted_count": 0,
            "subgraph_ready": False,
        }
    return row
