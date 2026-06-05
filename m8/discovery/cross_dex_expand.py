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

_FACTORY_RESOLVE_SKIP = frozenset({"curve_stable", "balancer_vault", "maverick_v2"})


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
) -> List[Dict[str, Any]]:
    if not registry:
        return []
    tok = (registry.get("tokens") or {}).get(exotic_address.lower())
    if not tok:
        return []
    pools: List[Dict[str, Any]] = []
    for venue in (tok.get("venues") or {}).values():
        dex = venue.get("dex", "")
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


def _resolve_via_factory(
    chain: str,
    dex_id: str,
    exotic_symbol: str,
    anchor_symbol: str,
    *,
    dry_run: bool,
    resolver: Any,
) -> Tuple[Optional[Dict[str, Any]], str]:
    if dex_id in _FACTORY_RESOLVE_SKIP:
        return None, "FACTORY_RESOLVE_NOT_APPLICABLE"

    adapter = _DEX_ID_TO_ADAPTER.get(dex_id, "")
    if not adapter:
        return None, "UNSUPPORTED_DEX"

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
    }


def expand_cross_dex(
    *,
    chain: str,
    config: Dict[str, Any],
    registry: Optional[Dict[str, Any]],
    anchor_artifact: Optional[Dict[str, Any]],
    dry_run: bool = False,
    max_pairs: Optional[int] = None,
) -> Dict[str, Any]:
    """Run M8.2 expansion and return artifact dict (not written)."""
    dex_rows = discovery_dexes_from_config(config)
    dex_ids_checked = [d["dex_id"] for d in dex_rows]
    productive_dexes = {d["dex_id"] for d in dex_rows if d["enabled_for_productive"]}

    pairs = collect_token_anchor_pairs(registry, anchor_artifact)
    if max_pairs is not None:
        pairs = pairs[: max_pairs]

    from discovery.pool_resolver import get_pool_resolver

    resolver = get_pool_resolver(chain)

    reject_hist: Counter = Counter()
    pools_found_by_dex: Counter = Counter()
    quoteable_by_dex: Counter = Counter()
    token_results: List[Dict[str, Any]] = []
    routes_admitted: List[Dict[str, Any]] = []
    admitted_by_dex: Counter = Counter()
    multi_venue_tokens = 0

    for pair in pairs:
        pools_by_dex: Dict[str, Dict[str, Any]] = {}
        rejects: List[Dict[str, str]] = []

        for p in _registry_pools_for_pair(
            registry,
            pair["exotic_address"],
            pair["exotic_symbol"],
            pair["anchor_symbol"],
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
                dry_run=dry_run,
                resolver=resolver,
            )
            if found:
                pools_by_dex[dex_id] = found
                pools_found_by_dex[dex_id] += 1
            else:
                rejects.append({"dex_id": dex_id, "reason": reason})
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
            for dex_id, pool_entry in pools_by_dex.items():
                productive = dex_id in productive_dexes
                pool_entry = {**pool_entry, "_venues_quoteable": venues_quoteable}
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
        "dry_run": dry_run,
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
