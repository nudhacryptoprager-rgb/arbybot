"""M8.2 cross-DEX expansion — resolve anchor/exotic pairs across all configured DEXes."""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

SCHEMA_VERSION = "m8_cross_dex_expansion.1"

# Align with m9/graph_arb/bridge_builder.py dex_id → adapter_type
_DEX_ID_TO_ADAPTER: Dict[str, str] = {
    "uniswap_v2": "uniswap_v2",
    "uniswap_v3": "uniswap_v3",
    "uniswap_v4": "uniswap_v4",
    "pancakeswap_v3": "uniswap_v3",
    "sushiswap_v3": "uniswap_v3",
    "aerodrome": "ve33",
    "aerodrome_slipstream": "aerodrome_slipstream",
    "aerodrome_v2_stable": "aerodrome_v2_stable",
    "sushiswap_v2": "uniswap_v2",
    "baseswap_v2": "uniswap_v2",
    "curve_stable": "curve_stable",
    "balancer_vault": "balancer_stable",
    "maverick_v2": "maverick_v2",
}

# Specialized DEX mirror resolve uses rolling indices (mirror_index.py), not pool_resolver.
_SPECIALIZED_MIRROR_ADAPTERS = frozenset(
    {"curve_stable", "balancer_stable", "maverick_v2"}
)


def _focus_token_key(route: Dict[str, Any]) -> str:
    return str(
        route.get("focus_token_address")
        or route.get("exotic_address")
        or route.get("token0_addr")
        or ""
    ).lower()


def tag_cross_mechanic_routes(routes: List[Dict[str, Any]]) -> int:
    """Tag routes when a focus token spans >=2 distinct pricing models."""
    by_focus: Dict[str, List[Dict[str, Any]]] = {}
    for route in routes:
        focus = _focus_token_key(route)
        if not focus:
            continue
        by_focus.setdefault(focus, []).append(route)
    tagged = 0
    for group in by_focus.values():
        models = sorted(
            {_pricing_model_for_dex(str(r.get("dex_id") or "")) for r in group}
        )
        distinct = [m for m in models if m and m != "unknown"]
        if len(distinct) < 2:
            continue
        for route in group:
            route["cross_mechanic"] = True
            route["mirror_pricing_models"] = distinct
            route["mechanic_pair"] = "cross_mechanic"
            tagged += 1
    return tagged


def _expansion_quoteable_by_dex(routes: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Counter[str] = Counter()
    for route in routes:
        dex = str(route.get("dex_id") or "unknown")
        status = route.get("quote_smoke_status") or route.get("quote_smoke")
        if status and str(status).upper().startswith("QUOTE_OK"):
            counts[dex] += 1
    return dict(counts)


def _pricing_model_for_dex(dex_id: str) -> str:
    """Pricing-model taxonomy for a dex_id (clmm/cpmm/solidly_stable/...).

    Reuses m9 cost_model.adapter_pricing_model so the cross-mechanic edge
    classification is consistent with M9 economics. Falls back to "unknown".
    """
    adapter = _DEX_ID_TO_ADAPTER.get(dex_id, "")
    try:
        from m9.graph_arb.cost_model import adapter_pricing_model

        return adapter_pricing_model(adapter)
    except Exception:
        return "unknown"


def _iso_now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_yaml_config(path: Path) -> Dict[str, Any]:
    import yaml

    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def discovery_dexes_from_config(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """DEX entries from exotic config with productivity flags."""
    productivity = config.get("m9_dex_productivity") or {}
    dexes = config.get("dexes") or {}
    rows: List[Dict[str, Any]] = []
    for dex_id, dex_cfg in dexes.items():
        if not dex_cfg.get("enabled", True):
            continue
        prod = productivity.get(dex_id) or {}
        rows.append({
            "dex_id": dex_id,
            "adapter_type": dex_cfg.get("adapter_type") or _DEX_ID_TO_ADAPTER.get(dex_id, "uniswap_v3"),
            "factory": dex_cfg.get("factory", ""),
            "enabled_for_discovery": bool(prod.get("enabled_for_discovery", True)),
            "enabled_for_productive": bool(prod.get("enabled_for_productive", False)),
        })
    return [r for r in rows if r["enabled_for_discovery"]]


def collect_token_anchor_pairs(
    registry: Optional[Dict[str, Any]],
    anchor_artifact: Optional[Dict[str, Any]],
) -> List[Dict[str, str]]:
    """Candidates as {exotic_address, exotic_symbol, anchor_symbol}."""
    seen: Set[Tuple[str, str, str]] = set()
    out: List[Dict[str, str]] = []

    def _add(addr: str, sym: str, anchor: str) -> None:
        key = (addr.lower(), sym, anchor)
        if not addr or not anchor or key in seen:
            return
        seen.add(key)
        out.append({
            "exotic_address": addr.lower(),
            "exotic_symbol": sym,
            "anchor_symbol": anchor,
        })

    if registry:
        for addr, tok in (registry.get("tokens") or {}).items():
            sym = str(tok.get("symbol") or "")
            for anchor in tok.get("anchors") or []:
                _add(addr, sym, str(anchor))

    if anchor_artifact:
        for route in anchor_artifact.get("active_routes") or []:
            t0, t1 = route.get("token0", ""), route.get("token1", "")
            a0, a1 = route.get("token0_addr", ""), route.get("token1_addr", "")
            from m8.discovery.pending_pair_registry import _ANCHOR_TOKENS

            if t0 in _ANCHOR_TOKENS and t1 not in _ANCHOR_TOKENS:
                _add(a1 or "", t1, t0)
            elif t1 in _ANCHOR_TOKENS and t0 not in _ANCHOR_TOKENS:
                _add(a0 or "", t0, t1)

    return out


def _registry_pools_for_pair(
    registry: Optional[Dict[str, Any]],
    exotic_address: str,
    exotic_symbol: str,
    anchor_symbol: str,
    allowed_dex_ids: Optional[Set[str]] = None,
) -> List[Dict[str, Any]]:
    if not registry:
        return []
    tok = (registry.get("tokens") or {}).get(exotic_address.lower())
    if not tok:
        return []
    pools: List[Dict[str, Any]] = []
    for venue in (tok.get("venues") or {}).values():
        dex = venue.get("dex", "")
        if allowed_dex_ids is not None and dex not in allowed_dex_ids:
            continue
        t0s = venue.get("token0_symbol", "")
        t1s = venue.get("token1_symbol", "")
        if anchor_symbol not in (t0s, t1s):
            continue
        if exotic_symbol not in (t0s, t1s):
            continue
        pools.append({
            "dex_id": dex,
            "pool_address": (venue.get("pool") or "").lower(),
            "factory_address": venue.get("factory", ""),
            "token0_symbol": t0s,
            "token1_symbol": t1s,
            "token0_addr": venue.get("token0", ""),
            "token1_addr": venue.get("token1", ""),
            "fee": venue.get("fee"),
            "tick_spacing": venue.get("tick_spacing"),
            "hooks": venue.get("hooks"),
            "resolve_source": "registry_venue",
            "factory_verified": True,
            "quote_smoke": "skipped_registry",
            "source_event_block": venue.get("source_event_block") or venue.get("block_number"),
            "pool_first_seen_block": venue.get("pool_first_seen_block") or venue.get("block_number"),
            "token_first_seen_ts": tok.get("first_seen_ts"),
        })
    return pools


def _registry_pools_for_token(
    registry: Optional[Dict[str, Any]],
    token_address: str,
    allowed_dex_ids: Optional[Set[str]] = None,
) -> List[Dict[str, Any]]:
    """All registry venues where ``token_address`` is token0 or token1."""
    if not registry:
        return []
    tok = (registry.get("tokens") or {}).get(token_address.lower())
    if not tok:
        return []
    focus_sym = str(tok.get("symbol") or "")
    pools: List[Dict[str, Any]] = []
    for venue in (tok.get("venues") or {}).values():
        dex = venue.get("dex", "")
        if allowed_dex_ids is not None and dex not in allowed_dex_ids:
            continue
        t0a = (venue.get("token0") or "").lower()
        t1a = (venue.get("token1") or "").lower()
        t0s = venue.get("token0_symbol", "")
        t1s = venue.get("token1_symbol", "")
        if token_address.lower() not in (t0a, t1a):
            continue
        if t0a == token_address.lower():
            connector_sym, connector_addr = t1s, t1a
        else:
            connector_sym, connector_addr = t0s, t0a
        pools.append({
            "dex_id": dex,
            "pool_address": (venue.get("pool") or "").lower(),
            "factory_address": venue.get("factory", ""),
            "token0_symbol": t0s,
            "token1_symbol": t1s,
            "token0_addr": t0a,
            "token1_addr": t1a,
            "fee": venue.get("fee"),
            "tick_spacing": venue.get("tick_spacing"),
            "hooks": venue.get("hooks"),
            "resolve_source": "registry_venue",
            "factory_verified": True,
            "quote_smoke": "skipped_registry",
            "expansion_route_kind": "token_presence",
            "connector_token": connector_sym,
            "connector_addr": connector_addr,
            "focus_token_symbol": focus_sym,
            "focus_token_address": token_address.lower(),
            "source_event_block": venue.get("source_event_block") or venue.get("block_number"),
            "pool_first_seen_block": venue.get("pool_first_seen_block") or venue.get("block_number"),
            "token_first_seen_ts": tok.get("first_seen_ts"),
        })
    return pools


def _registry_pools_connector_to_anchor(
    registry: Optional[Dict[str, Any]],
    connector_sym: str,
    connector_addr: str,
    anchor_sym: str,
    allowed_dex_ids: Optional[Set[str]] = None,
) -> List[Dict[str, Any]]:
    """Registry venues for connector→anchor (search by address or symbol)."""
    if connector_addr:
        pools = _registry_pools_for_pair(
            registry,
            connector_addr,
            connector_sym,
            anchor_sym,
            allowed_dex_ids,
        )
        if pools:
            return pools
    if not registry:
        return []
    for addr, tok in (registry.get("tokens") or {}).items():
        if str(tok.get("symbol") or "") != connector_sym:
            continue
        pools = _registry_pools_for_pair(
            registry, addr, connector_sym, anchor_sym, allowed_dex_ids
        )
        if pools:
            return pools
    return []


def _route_dedupe_key(pool_entry: Dict[str, Any]) -> Tuple[str, str, str, str]:
    return (
        str(pool_entry.get("dex_id", "")),
        str(pool_entry.get("pool_address", "")).lower(),
        str(pool_entry.get("token0_addr", "")).lower(),
        str(pool_entry.get("token1_addr", "")).lower(),
    )


def _anchor_symbols_from_config(config: Dict[str, Any]) -> Set[str]:
    from m8.discovery.pending_pair_registry import _ANCHOR_TOKENS

    anchors = set(_ANCHOR_TOKENS)
    for sym in (config.get("tokens") or {}):
        if sym in _ANCHOR_TOKENS:
            anchors.add(sym)
    return anchors


def evaluate_subgraph_readiness(
    *,
    token_seen_on_dexes: int,
    connector_tokens: int,
    active_routes: int,
    unique_tokens: int,
) -> Dict[str, Any]:
    """M9 shadow acceptance gate for token-neighborhood mini-subgraphs."""
    return {
        "token_seen_on_dexes": token_seen_on_dexes,
        "connector_token_count": connector_tokens,
        "unique_tokens": unique_tokens,
        "active_routes": active_routes,
        "token_seen_on_dexes_gte_2": token_seen_on_dexes >= 2,
        "connector_tokens_gte_1": connector_tokens >= 1,
        "active_routes_gte_4": active_routes >= 4,
        "unique_tokens_gte_3": unique_tokens >= 3,
        "subgraph_ready": (
            token_seen_on_dexes >= 2
            and connector_tokens >= 1
            and active_routes >= 4
            and unique_tokens >= 3
        ),
    }


def _merge_external_hints(
    t_pools: Dict[Tuple[str, str, str, str], Dict[str, Any]],
    *,
    chain: str,
    exotic_address: str,
    focus_sym: str,
    external_hints_artifact: Optional[Dict[str, Any]],
    allowed_dex_ids: Set[str],
    dry_run: bool,
    hint_metrics: Dict[str, Any],
) -> None:
    """Merge external hints after registry/MirrorIndex; verify on-chain unless dry_run."""
    if not external_hints_artifact:
        return
    from m8.discovery.pool_hints import (
        BRIDGE_ELIGIBLE_HINT_STATUSES,
        HINT_DEX_UNSUPPORTED,
        HINT_ONLY,
        HINT_STALE,
        hint_to_pool_entry,
        hints_for_token,
        verify_hint_onchain,
    )

    token_hints = hints_for_token(external_hints_artifact, exotic_address)
    if token_hints:
        hint_metrics["hint_tokens_matched"] = int(
            hint_metrics.get("hint_tokens_matched", 0)
        ) + 1
    hint_metrics["hint_pools_seen"] = int(hint_metrics.get("hint_pools_seen", 0)) + len(
        token_hints
    )
    existing_dexes = {p["dex_id"] for p in t_pools.values()}
    for hint in token_hints:
        if hint.dex_id not in allowed_dex_ids:
            hint.hint_status = HINT_DEX_UNSUPPORTED
            continue
        if dry_run:
            verified = hint
            verified.hint_status = HINT_ONLY
        elif hint.hint_status in BRIDGE_ELIGIBLE_HINT_STATUSES and hint.verify_method:
            verified = hint
        else:
            verified = verify_hint_onchain(
                hint, chain=chain, allowed_dex_ids=allowed_dex_ids
            )
        if verified.hint_status in (HINT_ONLY, HINT_STALE, HINT_DEX_UNSUPPORTED):
            hint_metrics["hint_rejected"] = int(hint_metrics.get("hint_rejected", 0)) + 1
            continue
        if verified.hint_status not in BRIDGE_ELIGIBLE_HINT_STATUSES:
            continue
        if verified.dex_id in existing_dexes:
            hint_metrics["hint_duplicate_dex"] = int(
                hint_metrics.get("hint_duplicate_dex", 0)
            ) + 1
            continue
        conn_sym = ""
        if verified.token0_addr == exotic_address.lower():
            conn_sym = (verified.raw or {}).get("token1_symbol", "")
        else:
            conn_sym = (verified.raw or {}).get("token0_symbol", "")
        entry = hint_to_pool_entry(
            verified,
            focus_token=exotic_address,
            focus_symbol=focus_sym,
            connector_symbol=conn_sym,
        )
        entry["factory_verified"] = True
        entry["hint_status"] = verified.hint_status
        t_pools[_route_dedupe_key(entry)] = entry
        existing_dexes.add(verified.dex_id)
        hint_metrics["eligible_hint_routes"] = int(
            hint_metrics.get("eligible_hint_routes", 0)
        ) + 1
        hint_metrics["verified_second_pool_count"] = int(
            hint_metrics.get("verified_second_pool_count", 0)
        ) + 1
        hint_metrics["second_pool_hints_found"] = int(
            hint_metrics.get("second_pool_hints_found", 0)
        ) + 1
        dex_hist = dict(hint_metrics.get("hint_dex_counts") or {})
        dex_hist[verified.dex_id] = int(dex_hist.get(verified.dex_id, 0)) + 1
        hint_metrics["hint_dex_counts"] = dex_hist
        status_hist = dict(hint_metrics.get("hint_status_counts") or {})
        status_hist[verified.hint_status] = int(
            status_hist.get(verified.hint_status, 0)
        ) + 1
        hint_metrics["hint_status_counts"] = status_hist


def expand_token_neighborhood(
    *,
    chain: str,
    config: Dict[str, Any],
    registry: Optional[Dict[str, Any]],
    exotic_address: str,
    exotic_symbol: str = "",
    dry_run: bool = False,
    dex_rows: Optional[List[Dict[str, Any]]] = None,
    allowed_dex_ids: Optional[Set[str]] = None,
    productive_dexes: Optional[Set[str]] = None,
    resolver: Any = None,
    mirror_index: Any = None,
    external_hints_artifact: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Token-global neighborhood expansion (3/4-leg subgraph discovery)."""
    from discovery.pool_resolver import get_pool_resolver
    from m8.discovery.mirror_index import MirrorIndex

    exotic_address = exotic_address.lower()
    dex_rows = dex_rows or discovery_dexes_from_config(config)
    allowed_dex_ids = allowed_dex_ids or {d["dex_id"] for d in dex_rows}
    productive_dexes = productive_dexes or {
        d["dex_id"] for d in dex_rows if d["enabled_for_productive"]
    }
    resolver = resolver or get_pool_resolver(chain)
    mirror_index = mirror_index or MirrorIndex.load(chain)
    anchor_syms = _anchor_symbols_from_config(config)

    reg_tok = ((registry or {}).get("tokens") or {}).get(exotic_address) or {}
    focus_sym = exotic_symbol or str(reg_tok.get("symbol") or exotic_address[:8])

    reject_hist: Counter = Counter()
    all_reject_rows: List[Dict[str, str]] = []
    hint_metrics: Dict[str, Any] = {
        "hint_tokens_checked": 1 if external_hints_artifact else 0,
        "hint_pools_seen": 0,
        "hint_to_verified_pool_rate": 0.0,
        "second_pool_hints_found": 0,
        "verified_second_pool_count": 0,
        "hint_source_latency_s": (external_hints_artifact or {}).get("metrics", {}).get(
            "hint_source_latency_s", {}
        ),
    }

    # Hop 1: all pools containing focus token T
    # Merge order: registry → MirrorIndex → external hints → on-chain verify
    t_pools: Dict[Tuple[str, str, str, str], Dict[str, Any]] = {}
    for p in _registry_pools_for_token(registry, exotic_address, allowed_dex_ids):
        t_pools[_route_dedupe_key(p)] = p
    for p in mirror_index.find_pools_containing_token(
        exotic_address, allowed_dex_ids, max_results_per_dex=4
    ):
        p.setdefault("focus_token_symbol", focus_sym)
        p.setdefault("focus_token_address", exotic_address)
        t_pools[_route_dedupe_key(p)] = p
    _merge_external_hints(
        t_pools,
        chain=chain,
        exotic_address=exotic_address,
        focus_sym=focus_sym,
        external_hints_artifact=external_hints_artifact,
        allowed_dex_ids=allowed_dex_ids,
        dry_run=dry_run,
        hint_metrics=hint_metrics,
    )
    seen_hints = int(hint_metrics.get("hint_pools_seen", 0))
    verified_hints = int(hint_metrics.get("verified_second_pool_count", 0))
    if seen_hints:
        hint_metrics["hint_to_verified_pool_rate"] = round(verified_hints / seen_hints, 4)

    token_seen_on_dexes = len({p["dex_id"] for p in t_pools.values()})
    if token_seen_on_dexes < 2:
        reject_hist["TOKEN_NOT_SEEN_ELSEWHERE"] += 1

    connectors: Dict[str, Dict[str, str]] = {}
    for p in t_pools.values():
        conn_sym = str(p.get("connector_token") or "")
        conn_addr = str(p.get("connector_addr") or "").lower()
        if not conn_sym and not conn_addr:
            t0s, t1s = p.get("token0_symbol", ""), p.get("token1_symbol", "")
            t0a, t1a = p.get("token0_addr", ""), p.get("token1_addr", "")
            if t0a == exotic_address:
                conn_sym, conn_addr = t1s, t1a
            else:
                conn_sym, conn_addr = t0s, t0a
        if conn_sym in anchor_syms:
            continue
        if conn_sym or conn_addr:
            connectors[conn_sym or conn_addr[:10]] = {
                "symbol": conn_sym,
                "address": conn_addr,
            }

    if not connectors:
        reject_hist["CONNECTOR_NOT_FOUND"] += 1

    same_pair_routes: List[Dict[str, Any]] = []
    token_presence_routes: List[Dict[str, Any]] = []
    connector_routes: List[Dict[str, Any]] = []
    seen_routes: Set[Tuple[str, str, str, str]] = set()

    def _admit_pool(
        pool_entry: Dict[str, Any],
        *,
        pair_sym_a: str,
        pair_sym_b: str,
        route_kind: str,
    ) -> None:
        key = _route_dedupe_key(pool_entry)
        if key in seen_routes:
            return
        seen_routes.add(key)
        entry = {**pool_entry, "expansion_route_kind": route_kind}
        productive = pool_entry.get("dex_id") in productive_dexes
        pair = {
            "exotic_symbol": pair_sym_a,
            "anchor_symbol": pair_sym_b,
            "exotic_address": exotic_address,
            "focus_token_address": exotic_address,
            "focus_token_symbol": focus_sym,
        }
        route = _build_route(pair, entry, productive=productive)
        if route_kind == "same_pair_mirror":
            same_pair_routes.append(route)
        elif route_kind == "connector_hop":
            connector_routes.append(route)
        else:
            token_presence_routes.append(route)

    # Classify T pools
    for p in t_pools.values():
        conn_sym = str(p.get("connector_token") or p.get("token1_symbol", ""))
        if p.get("token0_addr", "").lower() == exotic_address:
            conn_sym = str(p.get("token1_symbol") or p.get("connector_token") or "")
        elif p.get("token1_addr", "").lower() == exotic_address:
            conn_sym = str(p.get("token0_symbol") or p.get("connector_token") or "")
        kind = (
            "same_pair_mirror"
            if conn_sym in anchor_syms
            else "token_presence"
        )
        _admit_pool(
            p,
            pair_sym_a=focus_sym,
            pair_sym_b=conn_sym,
            route_kind=kind,
        )

    # Hop 2: connector -> anchor pools (+ T-connector on other DEXes)
    for conn in connectors.values():
        conn_sym = conn.get("symbol") or ""
        conn_addr = conn.get("address") or ""
        if not conn_sym:
            continue

        # T-connector on other DEXes (factory / index)
        for dex in dex_rows:
            dex_id = dex["dex_id"]
            if any(
                p.get("dex_id") == dex_id
                and (
                    p.get("connector_token") == conn_sym
                    or conn_sym in (p.get("token0_symbol"), p.get("token1_symbol"))
                )
                for p in t_pools.values()
            ):
                continue
            found, reason = _resolve_via_factory(
                chain,
                dex_id,
                focus_sym,
                conn_sym,
                exotic_address=exotic_address,
                anchor_address=conn_addr,
                dry_run=dry_run,
                resolver=resolver,
                mirror_index=mirror_index,
                config=config,
            )
            if found:
                found["connector_token"] = conn_sym
                found["connector_addr"] = conn_addr
                found["focus_token_symbol"] = focus_sym
                found["focus_token_address"] = exotic_address
                _admit_pool(
                    found,
                    pair_sym_a=focus_sym,
                    pair_sym_b=conn_sym,
                    route_kind="token_presence",
                )
            else:
                all_reject_rows.append({"dex_id": dex_id, "reason": reason})
                reject_hist[reason] += 1

        # connector-anchor bridges
        for anchor_sym in sorted(anchor_syms):
            if conn_sym == anchor_sym:
                continue
            hop_found = False
            for p in _registry_pools_connector_to_anchor(
                registry,
                conn_sym,
                conn_addr,
                anchor_sym,
                allowed_dex_ids,
            ):
                hop_found = True
                p["expansion_route_kind"] = "connector_hop"
                _admit_pool(
                    p,
                    pair_sym_a=conn_sym,
                    pair_sym_b=anchor_sym,
                    route_kind="connector_hop",
                )
            for dex in dex_rows:
                dex_id = dex["dex_id"]
                if hop_found:
                    break
                found, reason = _resolve_via_factory(
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
                    hop_found = True
                    found["expansion_route_kind"] = "connector_hop"
                    _admit_pool(
                        found,
                        pair_sym_a=conn_sym,
                        pair_sym_b=anchor_sym,
                        route_kind="connector_hop",
                    )
                elif reason not in ("NO_POOL", "SKIPPED_DRY_RUN"):
                    all_reject_rows.append({"dex_id": dex_id, "reason": reason})
                    if reason.endswith("NOT_QUOTEABLE"):
                        reject_hist["CONNECTOR_POOL_NOT_QUOTEABLE"] += 1
                    else:
                        reject_hist[reason] += 1
            if not hop_found and conn_sym not in anchor_syms:
                reject_hist["CONNECTOR_POOL_NOT_QUOTEABLE"] += 1

    routes_admitted = same_pair_routes + token_presence_routes + connector_routes
    _cm_tagged = tag_cross_mechanic_routes(routes_admitted)
    unique_token_syms = {
        focus_sym,
        *[r.get("token0", "") for r in routes_admitted],
        *[r.get("token1", "") for r in routes_admitted],
    }
    unique_token_syms.discard("")

    subgraph = evaluate_subgraph_readiness(
        token_seen_on_dexes=token_seen_on_dexes,
        connector_tokens=len(connectors),
        active_routes=len(routes_admitted),
        unique_tokens=len(unique_token_syms),
    )
    if not subgraph["subgraph_ready"]:
        reject_hist["SUBGRAPH_TOO_SMALL"] += 1

    quoteable_dexes = {r["dex_id"] for r in routes_admitted}
    _models = sorted({_pricing_model_for_dex(d) for d in quoteable_dexes})
    _distinct_models = [m for m in _models if m and m != "unknown"]
    cross_mechanic = len(_distinct_models) >= 2

    return {
        "focus_token_address": exotic_address,
        "focus_token_symbol": focus_sym,
        "same_pair_routes": same_pair_routes,
        "token_presence_routes": token_presence_routes,
        "connector_routes": connector_routes,
        "connector_tokens": sorted(connectors.keys()),
        "routes_admitted": routes_admitted,
        "reject_reason_histogram": dict(reject_hist),
        "all_reject_rows": all_reject_rows,
        "token_seen_on_dexes": token_seen_on_dexes,
        "subgraph": subgraph,
        "cross_mechanic": cross_mechanic,
        "cross_mechanic_routes_tagged": _cm_tagged,
        "venues_quoteable": len(quoteable_dexes),
        "hint_metrics": hint_metrics,
    }


def _token_address_from_config(config: Dict[str, Any], symbol: str) -> str:
    for sym, info in (config.get("tokens") or {}).items():
        if sym == symbol and isinstance(info, dict):
            addr = info.get("address") or info.get("addr")
            if addr:
                return str(addr).lower()
    return ""


def _resolve_via_factory(
    chain: str,
    dex_id: str,
    exotic_symbol: str,
    anchor_symbol: str,
    *,
    exotic_address: str = "",
    anchor_address: str = "",
    dry_run: bool,
    resolver: Any,
    mirror_index: Any = None,
    config: Optional[Dict[str, Any]] = None,
) -> Tuple[Optional[Dict[str, Any]], str]:
    adapter = _DEX_ID_TO_ADAPTER.get(dex_id, "")
    if not adapter:
        return None, "UNSUPPORTED_DEX"

    if adapter in _SPECIALIZED_MIRROR_ADAPTERS:
        if dry_run:
            return None, "SKIPPED_DRY_RUN"
        if mirror_index is None:
            from m8.discovery.mirror_index import MirrorIndex

            mirror_index = MirrorIndex.load(chain)
        exotic_addr = (exotic_address or "").lower()
        anchor_addr = (anchor_address or "").lower()
        if not anchor_addr and config:
            anchor_addr = _token_address_from_config(config, anchor_symbol)
        if adapter == "curve_stable":
            return mirror_index.resolve_curve(
                exotic_symbol,
                anchor_symbol,
                exotic_address=exotic_addr,
                anchor_address=anchor_addr,
            )
        if adapter == "balancer_stable":
            return mirror_index.resolve_balancer(
                exotic_symbol,
                anchor_symbol,
                exotic_address=exotic_addr,
                anchor_address=anchor_addr,
            )
        if adapter == "maverick_v2":
            return mirror_index.resolve_maverick(
                exotic_symbol,
                anchor_symbol,
                exotic_address=exotic_addr,
                anchor_address=anchor_addr,
            )
        return None, "ADAPTER_RESOLVE_PENDING"

    if dry_run:
        return None, "SKIPPED_DRY_RUN"

    from discovery.index_factories import get_dex_fee_tiers

    if adapter == "uniswap_v3":
        for fee in get_dex_fee_tiers(chain, dex_id)[:2]:
            pool = resolver.resolve(chain, dex_id, exotic_symbol, anchor_symbol, fee=fee)
            if pool:
                return {
                    "dex_id": dex_id,
                    "pool_address": pool.lower(),
                    "fee": fee,
                    "resolve_source": "pool_resolver",
                    "factory_verified": True,
                    "quote_smoke": "not_run",
                }, "OK"
        return None, "NO_POOL"
    if adapter == "uniswap_v2":
        pool = resolver.resolve(chain, dex_id, exotic_symbol, anchor_symbol, fee=None)
        if pool:
            return {
                "dex_id": dex_id,
                "pool_address": pool.lower(),
                "fee": 0,
                "resolve_source": "pool_resolver",
                "factory_verified": True,
                "quote_smoke": "not_run",
            }, "OK"
        return None, "NO_POOL"
    if adapter == "ve33":
        for stable_flag in (False, True):
            pool = resolver.resolve(
                chain, dex_id, exotic_symbol, anchor_symbol, fee=1 if stable_flag else 0
            )
            if pool:
                return {
                    "dex_id": dex_id,
                    "pool_address": pool.lower(),
                    "fee": 1 if stable_flag else 0,
                    "resolve_source": "pool_resolver",
                    "factory_verified": True,
                    "quote_smoke": "not_run",
                }, "OK"
        return None, "NO_POOL"
    if adapter == "aerodrome_v2_stable":
        # Solidly stable-curve pool: ve33 getPool(token0, token1, stable=True).
        pool = resolver.resolve(chain, dex_id, exotic_symbol, anchor_symbol, fee=1)
        if pool:
            return {
                "dex_id": dex_id,
                "pool_address": pool.lower(),
                "fee": 1,
                "resolve_source": "pool_resolver",
                "factory_verified": True,
                "quote_smoke": "not_run",
            }, "OK"
        return None, "NO_POOL"
    if adapter == "aerodrome_slipstream":
        from discovery.index_factories import get_dex_fee_tiers

        for fee in get_dex_fee_tiers(chain, dex_id)[:1]:
            pool = resolver.resolve(chain, dex_id, exotic_symbol, anchor_symbol, fee=fee)
            if pool:
                return {
                    "dex_id": dex_id,
                    "pool_address": pool.lower(),
                    "fee": fee,
                    "resolve_source": "pool_resolver",
                    "factory_verified": True,
                    "quote_smoke": "not_run",
                }, "OK"
        return None, "NO_POOL"

    return None, "ADAPTER_RESOLVE_PENDING"


def _build_route(
    pair: Dict[str, str],
    pool_entry: Dict[str, Any],
    *,
    productive: bool,
) -> Dict[str, Any]:
    t0s = pool_entry.get("token0_symbol") or pair["exotic_symbol"]
    t1s = pool_entry.get("token1_symbol") or pair["anchor_symbol"]
    t0a = pool_entry.get("token0_addr", "")
    t1a = pool_entry.get("token1_addr", "")
    if t0s > t1s:
        t0s, t1s = t1s, t0s
        t0a, t1a = t1a, t0a
    dex_id = pool_entry["dex_id"]
    pool_addr = pool_entry["pool_address"]
    return {
        "route_id": f"m8x_{dex_id}_{pool_addr[-8:]}",
        "pair_id": f"{pair['exotic_symbol']}_{pair['anchor_symbol']}",
        "dex_id": dex_id,
        "adapter_type": _DEX_ID_TO_ADAPTER.get(dex_id, "uniswap_v3"),
        "token0": t0s,
        "token1": t1s,
        "token0_addr": t0a,
        "token1_addr": t1a,
        "factory_address": pool_entry.get("factory_address", ""),
        "pool_address": pool_addr,
        "factory_verified": bool(pool_entry.get("factory_verified")),
        "source": "m8_cross_dex_expansion",
        "focus_token_address": pair.get("focus_token_address") or pair.get("exotic_address"),
        "focus_token_symbol": pair.get("focus_token_symbol") or pair.get("exotic_symbol"),
        "fee": pool_entry.get("fee"),
        "tick_spacing": pool_entry.get("tick_spacing"),
        "hooks": pool_entry.get("hooks"),
        "quote_smoke": pool_entry.get("quote_smoke", "not_run"),
        "quote_smoke_status": pool_entry.get("quote_smoke_status")
        or pool_entry.get("quote_smoke", "not_run"),
        "venues_quoteable": pool_entry.get("_venues_quoteable"),
        "expansion_productive_admit": productive,
        "reject_reason_histogram": pool_entry.get("reject_reason_histogram"),
        "source_event_block": pool_entry.get("source_event_block"),
        "pool_first_seen_block": pool_entry.get("pool_first_seen_block"),
        "token_first_seen_ts": pool_entry.get("token_first_seen_ts"),
        # Cross-mechanic edge classification (Phase 1b)
        "pricing_model": _pricing_model_for_dex(dex_id),
        "mirror_pricing_models": pool_entry.get("_mirror_pricing_models"),
        "cross_mechanic": pool_entry.get("_cross_mechanic"),
        "mirror_score": pool_entry.get("_mirror_score"),
        # Token freshness signal (Phase 1c)
        "token_is_fresh": pool_entry.get("_token_is_fresh"),
        "token_is_known_registry": pool_entry.get("_token_is_known_registry"),
        # Specialized mirror index fields
        "pool_kind": pool_entry.get("pool_kind"),
        "coin_indices": pool_entry.get("coin_indices"),
        "pool_id": pool_entry.get("pool_id"),
        "vault_address": pool_entry.get("vault_address"),
        "resolve_source": pool_entry.get("resolve_source"),
        # Token-neighborhood expansion
        "expansion_route_kind": pool_entry.get("expansion_route_kind"),
        "connector_token": pool_entry.get("connector_token"),
        "focus_token_address": pool_entry.get("focus_token_address")
        or pair.get("focus_token_address")
        or pair.get("exotic_address"),
        "focus_token_symbol": pool_entry.get("focus_token_symbol")
        or pair.get("focus_token_symbol")
        or pair.get("exotic_symbol"),
        # External hint provenance (M8.2 hint layer)
        "hint_status": pool_entry.get("hint_status"),
        "hint_source": pool_entry.get("hint_source"),
        "origin_source": pool_entry.get("origin_source"),
        "matched_m8_token": pool_entry.get("matched_m8_token"),
    }


def _expand_batch_token_neighborhood(
    *,
    chain: str,
    config: Dict[str, Any],
    registry: Optional[Dict[str, Any]],
    dry_run: bool,
    dex_rows: List[Dict[str, Any]],
    allowed_dex_ids: Set[str],
    productive_dexes: Set[str],
    max_tokens: Optional[int] = None,
    external_hints_artifact: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Batch rolling expansion: token-neighborhood per registry token."""
    from discovery.pool_resolver import get_pool_resolver
    from m8.discovery.mirror_index import MirrorIndex, per_dex_expansion_breakdown

    resolver = get_pool_resolver(chain)
    mirror_index = MirrorIndex.load(chain)
    reg_tokens = (registry or {}).get("tokens") or {}
    token_addrs = list(reg_tokens.keys())
    if max_tokens is not None:
        token_addrs = token_addrs[:max_tokens]

    reject_hist: Counter = Counter()
    all_reject_rows: List[Dict[str, str]] = []
    routes_admitted: List[Dict[str, Any]] = []
    same_pair_routes: List[Dict[str, Any]] = []
    token_presence_routes: List[Dict[str, Any]] = []
    connector_routes: List[Dict[str, Any]] = []
    connector_tokens_all: Set[str] = set()
    subgraph_ready_count = 0
    seen_route_keys: Set[Tuple[str, str, str, str]] = set()
    from m8.discovery.pool_hints import artifact_hint_summary, hints_for_token

    batch_hint_metrics: Dict[str, Any] = {
        "hint_tokens_checked": 0,
        "hint_pools_seen": 0,
        "hint_tokens_matched": 0,
        "eligible_hint_routes": 0,
        "second_pool_hints_found": 0,
        "verified_second_pool_count": 0,
        "hint_to_verified_pool_rate": 0.0,
        "hint_status_counts": {},
        "hint_dex_counts": {},
        "hint_source_latency_s": (external_hints_artifact or {}).get("metrics", {}).get(
            "hint_source_latency_s", {}
        ),
        **artifact_hint_summary(external_hints_artifact),
    }
    if external_hints_artifact:
        batch_hint_metrics["hint_registry_overlap_tokens"] = sum(
            1 for addr in token_addrs if hints_for_token(external_hints_artifact, addr)
        )

    for addr in token_addrs:
        sym = str((reg_tokens.get(addr) or {}).get("symbol") or "")
        nh = expand_token_neighborhood(
            chain=chain,
            config=config,
            registry=registry,
            exotic_address=addr,
            exotic_symbol=sym,
            dry_run=dry_run,
            dex_rows=dex_rows,
            allowed_dex_ids=allowed_dex_ids,
            productive_dexes=productive_dexes,
            resolver=resolver,
            mirror_index=mirror_index,
            external_hints_artifact=external_hints_artifact,
        )
        hm = nh.get("hint_metrics") or {}
        batch_hint_metrics["hint_tokens_checked"] += int(hm.get("hint_tokens_checked", 0))
        batch_hint_metrics["hint_pools_seen"] += int(hm.get("hint_pools_seen", 0))
        batch_hint_metrics["second_pool_hints_found"] += int(
            hm.get("second_pool_hints_found", 0)
        )
        batch_hint_metrics["verified_second_pool_count"] += int(
            hm.get("verified_second_pool_count", 0)
        )
        batch_hint_metrics["hint_tokens_matched"] += int(
            hm.get("hint_tokens_matched", 0)
        )
        batch_hint_metrics["eligible_hint_routes"] += int(
            hm.get("eligible_hint_routes", 0)
        )
        for k, v in (nh.get("reject_reason_histogram") or {}).items():
            reject_hist[k] += int(v or 0)
        all_reject_rows.extend(nh.get("all_reject_rows") or [])
        connector_tokens_all.update(nh.get("connector_tokens") or [])
        if nh.get("subgraph", {}).get("subgraph_ready"):
            subgraph_ready_count += 1
        for bucket, dest in (
            ("same_pair_routes", same_pair_routes),
            ("token_presence_routes", token_presence_routes),
            ("connector_routes", connector_routes),
        ):
            for route in nh.get(bucket) or []:
                key = (
                    route.get("dex_id", ""),
                    route.get("pool_address", "").lower(),
                    route.get("token0_addr", "").lower(),
                    route.get("token1_addr", "").lower(),
                )
                if key in seen_route_keys:
                    continue
                seen_route_keys.add(key)
                dest.append(route)
                routes_admitted.append(route)

    if batch_hint_metrics["hint_pools_seen"]:
        batch_hint_metrics["hint_to_verified_pool_rate"] = round(
            batch_hint_metrics["verified_second_pool_count"]
            / batch_hint_metrics["hint_pools_seen"],
            4,
        )
    if token_addrs:
        batch_hint_metrics["transition_candidate_rate"] = round(
            subgraph_ready_count / len(token_addrs), 4
        )
    batch_hint_metrics["second_venue_source"] = dict(
        (external_hints_artifact or {}).get("metrics", {}).get("second_venue_source") or {}
    )
    from m8.discovery.specialized_index_merge import (
        merge_specialized_index_batch,
        secondary_watchlist_tokens,
    )

    secondary_tokens = secondary_watchlist_tokens(
        external_hints_artifact=external_hints_artifact,
        mirror_index=mirror_index,
    )
    batch_hint_metrics["specialized_index_secondary_tokens"] = len(secondary_tokens)
    batch_hint_metrics["specialized_index_route_counts"] = merge_specialized_index_batch(
        mirror_index=mirror_index,
        token_addrs=token_addrs,
        reg_tokens=reg_tokens,
        allowed_dex_ids=allowed_dex_ids,
        productive_dexes=productive_dexes,
        secondary_tokens=secondary_tokens,
        seen_route_keys=seen_route_keys,
        routes_admitted=routes_admitted,
        token_presence_routes=token_presence_routes,
    )
    from m8.discovery.specialized_index_merge import merge_connector_routes_from_presence

    batch_hint_metrics["specialized_connector_routes_added"] = (
        merge_connector_routes_from_presence(
            chain=chain,
            config=config,
            mirror_index=mirror_index,
            resolver=resolver,
            dex_rows=dex_rows,
            allowed_dex_ids=allowed_dex_ids,
            productive_dexes=productive_dexes,
            token_presence_routes=token_presence_routes,
            seen_route_keys=seen_route_keys,
            routes_admitted=routes_admitted,
            connector_routes=connector_routes,
            dry_run=dry_run,
        )
    )
    pools_found_by_dex: Counter = Counter(r["dex_id"] for r in routes_admitted)
    _cm_tagged = tag_cross_mechanic_routes(routes_admitted)
    quoteable_by_dex = _expansion_quoteable_by_dex(routes_admitted)
    admitted_by_dex = dict(pools_found_by_dex)
    from m8.discovery.distinct_pricing_lane import (
        build_per_adapter_lane_report,
        evaluate_distinct_pricing_lane,
    )

    per_adapter_lane_report = build_per_adapter_lane_report(
        routes_admitted=routes_admitted,
        reject_rows=all_reject_rows,
        pools_found_by_dex=dict(pools_found_by_dex),
    )
    distinct_lane = evaluate_distinct_pricing_lane(routes_admitted)
    from m8.discovery.origin_source import collect_m8_token_addrs, stamp_route_origin_source

    _m8_token_addrs = collect_m8_token_addrs(registry=registry)
    _hint_matched = 0
    _specialized_matched = 0
    for _r in routes_admitted:
        stamp_route_origin_source(_r, _m8_token_addrs)
        if _r.get("matched_m8_token"):
            _hint_matched += 1
        if _r.get("origin_source") == "specialized_index_for_m8_token":
            _specialized_matched += 1
    summary = {
        "expansion_mode": "token_neighborhood_batch",
        "tokens_in": len(token_addrs),
        "pairs_in": 0,
        "subgraph_ready_tokens": subgraph_ready_count,
        "dexes_checked": len(allowed_dex_ids),
        "dex_ids_checked": sorted(allowed_dex_ids),
        "pools_found_by_dex": dict(pools_found_by_dex),
        "quoteable_by_dex": quoteable_by_dex,
        "admitted_by_dex": admitted_by_dex,
        "cross_mechanic_routes_tagged": _cm_tagged,
        "routes_admitted_count": len(routes_admitted),
        "routes_admitted_raw": len(routes_admitted),
        "same_pair_routes_count": len(same_pair_routes),
        "token_presence_routes_count": len(token_presence_routes),
        "connector_routes_count": len(connector_routes),
        "connector_tokens": sorted(connector_tokens_all),
        "connector_token_count": len(connector_tokens_all),
        "dry_run": dry_run,
        "external_hints_enabled": external_hints_artifact is not None,
        **batch_hint_metrics,
        **per_dex_expansion_breakdown(
            pools_found_by_dex=dict(pools_found_by_dex),
            reject_rows=all_reject_rows,
            routes_admitted=routes_admitted,
        ),
        "per_adapter_lane_report": per_adapter_lane_report,
        "m8_tokens_in": len(_m8_token_addrs),
        "hint_tokens_matched": _hint_matched,
        "specialized_index_tokens_matched": _specialized_matched,
        **distinct_lane,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": _iso_now(),
        "chain": chain,
        "config_path": None,
        "input_registry_path": None,
        "summary": summary,
        "reject_reason_histogram": dict(reject_hist),
        "same_pair_routes": same_pair_routes,
        "token_presence_routes": token_presence_routes,
        "connector_routes": connector_routes,
        "connector_tokens": sorted(connector_tokens_all),
        "tokens": [],
        "routes_admitted": routes_admitted,
    }


def expand_cross_dex(
    *,
    chain: str,
    config: Dict[str, Any],
    registry: Optional[Dict[str, Any]],
    anchor_artifact: Optional[Dict[str, Any]],
    dry_run: bool = False,
    max_pairs: Optional[int] = None,
    exotic_address_filter: Optional[str] = None,
    expansion_mode: str = "pair_anchor",
    external_hints_artifact: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Run M8.2 expansion and return artifact dict (not written)."""
    dex_rows = discovery_dexes_from_config(config)
    dex_ids_checked = [d["dex_id"] for d in dex_rows]
    allowed_dex_ids = set(dex_ids_checked)
    productive_dexes = {d["dex_id"] for d in dex_rows if d["enabled_for_productive"]}

    if expansion_mode == "token_neighborhood" and not exotic_address_filter:
        return _expand_batch_token_neighborhood(
            chain=chain,
            config=config,
            registry=registry,
            dry_run=dry_run,
            dex_rows=dex_rows,
            allowed_dex_ids=allowed_dex_ids,
            productive_dexes=productive_dexes,
            max_tokens=max_pairs,
            external_hints_artifact=external_hints_artifact,
        )

    if expansion_mode == "token_neighborhood" and exotic_address_filter:
        from discovery.pool_resolver import get_pool_resolver
        from m8.discovery.mirror_index import MirrorIndex, per_dex_expansion_breakdown

        resolver = get_pool_resolver(chain)
        mirror_index = MirrorIndex.load(chain)
        reg_tok = ((registry or {}).get("tokens") or {}).get(
            exotic_address_filter.lower(), {}
        )
        nh = expand_token_neighborhood(
            chain=chain,
            config=config,
            registry=registry,
            exotic_address=exotic_address_filter,
            exotic_symbol=str(reg_tok.get("symbol") or ""),
            dry_run=dry_run,
            dex_rows=dex_rows,
            allowed_dex_ids=allowed_dex_ids,
            productive_dexes=productive_dexes,
            resolver=resolver,
            mirror_index=mirror_index,
            external_hints_artifact=external_hints_artifact,
        )
        routes_admitted = nh["routes_admitted"]
        try:
            from m9.graph_arb.pool_quality import annotate_routes_pool_quality

            annotate_routes_pool_quality(routes_admitted)
        except Exception:
            pass
        pools_found_by_dex: Counter = Counter(
            r["dex_id"] for r in routes_admitted
        )
        summary = {
            "expansion_mode": "token_neighborhood",
            "tokens_in": 1,
            "pairs_in": 0,
            "dexes_checked": len(dex_ids_checked),
            "dex_ids_checked": dex_ids_checked,
            "pools_found_by_dex": dict(pools_found_by_dex),
            "routes_admitted_count": len(routes_admitted),
            "routes_admitted_raw": len(routes_admitted),
            "same_pair_routes_count": len(nh["same_pair_routes"]),
            "token_presence_routes_count": len(nh["token_presence_routes"]),
            "connector_routes_count": len(nh["connector_routes"]),
            "connector_tokens": nh["connector_tokens"],
            "token_seen_on_dexes": nh["token_seen_on_dexes"],
            "unique_tokens": nh["subgraph"]["unique_tokens"],
            "subgraph_ready": nh["subgraph"]["subgraph_ready"],
            "cross_mechanic_tokens": 1 if nh["cross_mechanic"] else 0,
            "venues_quoteable": nh["venues_quoteable"],
            "dry_run": dry_run,
            **nh["subgraph"],
            **per_dex_expansion_breakdown(
                pools_found_by_dex=dict(pools_found_by_dex),
                reject_rows=nh["all_reject_rows"],
                routes_admitted=routes_admitted,
            ),
        }
        return {
            "schema_version": SCHEMA_VERSION,
            "generated_at_utc": _iso_now(),
            "chain": chain,
            "config_path": None,
            "input_registry_path": None,
            "summary": summary,
            "reject_reason_histogram": nh["reject_reason_histogram"],
            "same_pair_routes": nh["same_pair_routes"],
            "token_presence_routes": nh["token_presence_routes"],
            "connector_routes": nh["connector_routes"],
            "connector_tokens": nh["connector_tokens"],
            "tokens": [{
                "exotic_address": nh["focus_token_address"],
                "exotic_symbol": nh["focus_token_symbol"],
                "venues_quoteable": nh["venues_quoteable"],
                "subgraph": nh["subgraph"],
            }],
            "routes_admitted": routes_admitted,
        }

    pairs = collect_token_anchor_pairs(registry, anchor_artifact)
    if exotic_address_filter:
        _eaf = exotic_address_filter.lower()
        pairs = [p for p in pairs if (p.get("exotic_address") or "").lower() == _eaf]
    if max_pairs is not None:
        pairs = pairs[: max_pairs]

    from discovery.pool_resolver import get_pool_resolver
    from m8.discovery.mirror_index import MirrorIndex, per_dex_expansion_breakdown

    resolver = get_pool_resolver(chain)
    mirror_index = MirrorIndex.load(chain)

    reject_hist: Counter = Counter()
    all_reject_rows: List[Dict[str, str]] = []
    pools_found_by_dex: Counter = Counter()
    quoteable_by_dex: Counter = Counter()
    token_results: List[Dict[str, Any]] = []
    routes_admitted: List[Dict[str, Any]] = []
    admitted_by_dex: Counter = Counter()
    pricing_model_pairs: Counter = Counter()
    cross_mechanic_tokens = 0
    same_mechanic_tokens = 0
    fresh_token_admitted = 0
    multi_venue_tokens = 0

    # Token-freshness lookup: registry first_seen_ts marks tokens this scanner
    # first observed recently (cheap, RPC-free). An old first_seen means known;
    # a token absent from the registry is unknown, not fresh.
    _reg_tokens: Dict[str, Any] = (registry or {}).get("tokens", {}) or {}
    _now_ts = datetime.now(tz=timezone.utc).timestamp()
    _fresh_window_s = float(config.get("m8_2_fresh_token_window_s", 6 * 3600))

    def _token_freshness(exotic_addr: str) -> Tuple[Optional[bool], Optional[bool]]:
        tok = _reg_tokens.get((exotic_addr or "").lower())
        if not tok:
            return None, None
        fs = tok.get("first_seen_ts")
        if not isinstance(fs, (int, float)):
            return None, True
        is_fresh = (_now_ts - float(fs)) <= _fresh_window_s
        return is_fresh, not is_fresh

    for pair in pairs:
        pools_by_dex: Dict[str, Dict[str, Any]] = {}
        rejects: List[Dict[str, str]] = []

        for p in _registry_pools_for_pair(
            registry,
            pair["exotic_address"],
            pair["exotic_symbol"],
            pair["anchor_symbol"],
            allowed_dex_ids,
        ):
            pools_by_dex[p["dex_id"]] = p
            pools_found_by_dex[p["dex_id"]] += 1

        for dex in dex_rows:
            dex_id = dex["dex_id"]
            if dex_id in pools_by_dex:
                continue
            found, reason = _resolve_via_factory(
                chain,
                dex_id,
                pair["exotic_symbol"],
                pair["anchor_symbol"],
                exotic_address=pair.get("exotic_address", ""),
                anchor_address=_token_address_from_config(config, pair["anchor_symbol"]),
                dry_run=dry_run,
                resolver=resolver,
                mirror_index=mirror_index,
                config=config,
            )
            if found:
                pools_by_dex[dex_id] = found
                pools_found_by_dex[dex_id] += 1
            else:
                rejects.append({"dex_id": dex_id, "reason": reason})
                all_reject_rows.append({"dex_id": dex_id, "reason": reason})
                reject_hist[reason] += 1

        quoteable_dexes = [
            d for d in pools_by_dex
            if _DEX_ID_TO_ADAPTER.get(d) not in (None, "")
        ]
        for d in quoteable_dexes:
            quoteable_by_dex[d] += 1

        venues_quoteable = len(set(quoteable_dexes))
        token_entry = {
            **pair,
            "venues_quoteable": venues_quoteable,
            "dexes_quoteable": sorted(set(quoteable_dexes)),
            "pools": list(pools_by_dex.values()),
            "rejects": rejects,
        }
        token_results.append(token_entry)

        if venues_quoteable >= 2:
            multi_venue_tokens += 1
            # Cross-mechanic classification: distinct pricing models across the
            # token's quoteable venues. >=2 distinct models => structural edge.
            _models = sorted({_pricing_model_for_dex(d) for d in quoteable_dexes})
            _distinct_models = [m for m in _models if m and m != "unknown"]
            _is_cross_mechanic = len(_distinct_models) >= 2
            if _is_cross_mechanic:
                cross_mechanic_tokens += 1
                pricing_model_pairs["+".join(_distinct_models)] += 1
            else:
                same_mechanic_tokens += 1
            # mirror_score: higher when more distinct mechanics participate.
            _mirror_score = float(len(_distinct_models))

            _is_fresh, _is_known = _token_freshness(pair.get("exotic_address", ""))
            if _is_fresh:
                fresh_token_admitted += 1

            for dex_id, pool_entry in pools_by_dex.items():
                productive = dex_id in productive_dexes
                pool_entry = {
                    **pool_entry,
                    "_venues_quoteable": venues_quoteable,
                    "_mirror_pricing_models": _distinct_models,
                    "_cross_mechanic": _is_cross_mechanic,
                    "_mirror_score": _mirror_score,
                    "_token_is_fresh": _is_fresh,
                    "_token_is_known_registry": _is_known,
                }
                routes_admitted.append(
                    _build_route(pair, pool_entry, productive=productive)
                )
                admitted_by_dex[dex_id] += 1
        else:
            reject_hist["SINGLE_VENUE_ONLY"] += 1

    try:
        from m9.graph_arb.pool_quality import annotate_routes_pool_quality

        annotate_routes_pool_quality(routes_admitted)
    except Exception:
        pass

    summary = {
        "expansion_mode": "pair_anchor",
        "tokens_in": len(pairs),
        "pairs_in": len(pairs),
        "dexes_checked": len(dex_ids_checked),
        "dex_ids_checked": dex_ids_checked,
        "pools_found_by_dex": dict(pools_found_by_dex),
        "quoteable_by_dex": dict(quoteable_by_dex),
        "admitted_by_dex": dict(admitted_by_dex),
        "multi_venue_tokens": multi_venue_tokens,
        "venues_quoteable_ge2": multi_venue_tokens,
        "routes_admitted_count": len(routes_admitted),
        "routes_admitted_raw": len(routes_admitted),
        # Populated by bridge merge (not at expand time):
        "routes_admitted_after_bridge_dedupe": None,
        # Cross-mechanic edge metrics (Phase 1b)
        "cross_mechanic_tokens": cross_mechanic_tokens,
        "same_mechanic_tokens": same_mechanic_tokens,
        "pricing_model_pairs": dict(pricing_model_pairs),
        # Token-freshness admission signal (Phase 1c)
        "fresh_token_admitted": fresh_token_admitted,
        "fresh_token_window_s": _fresh_window_s,
        "dry_run": dry_run,
        **per_dex_expansion_breakdown(
            pools_found_by_dex=dict(pools_found_by_dex),
            reject_rows=all_reject_rows,
            routes_admitted=routes_admitted,
        ),
    }

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": _iso_now(),
        "chain": chain,
        "config_path": None,
        "input_registry_path": None,
        "summary": summary,
        "reject_reason_histogram": dict(reject_hist),
        "tokens": token_results,
        "routes_admitted": routes_admitted,
    }


def write_artifact(artifact: Dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(artifact, fh, ensure_ascii=False, indent=2)
