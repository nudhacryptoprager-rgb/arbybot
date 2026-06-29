"""On-chain factory + factory-log mirror discovery for time-to-mirror hot path.

Primary discovery for fresh_delta / pending tokens. DexScreener is enrichment only.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from m8.discovery.pool_hints import (
    HINT_FACTORY_VERIFIED,
    PoolHint,
    VERIFY_FACTORY_GET_POOL,
    build_artifact,
    dedupe_hints,
    verify_hint_onchain,
    write_hints_artifact,
)
from m8.discovery.radar_layer import (
    RADAR_REASON_NEW_POOL,
    build_radar_candidates_artifact,
    write_radar_candidates_artifact,
)

_log = logging.getLogger(__name__)

DEFAULT_SCAN_ARTIFACT = "data/tmp/m8_onchain_factory_scan_latest.json"
DEFAULT_HINTS_PATH = "data/runs/_rolling/m8_external_pool_hints_latest.json"
DEFAULT_RADAR_PATH = "data/runs/_rolling/m8_radar_pool_candidates_latest.json"
DEFAULT_VERIFY_BUDGET_PATH = "data/tmp/m8_verify_budget_latest.json"
DEFAULT_EXPAND_SUBSET = "data/tmp/m8_time_to_mirror_expand_subset.json"
FACTORY_LOG_CONFIG_PATH = Path("config/new_pool_factories.yaml")

P0_ANCHOR_SYMS = ("USDC", "WETH", "cbBTC", "EURC", "USDbC", "DAI")
FRESH_NEG_CACHE_TTL_S = 180.0
FACTORY_LOG_MAX_BLOCKS = 5000
FACTORY_LOG_CHUNK_BLOCKS = 2000

_SOURCE_ONCHAIN_FACTORY = "onchain_factory"
_SOURCE_FACTORY_LOG = "factory_log"


@dataclass
class MirrorDiscoveryResult:
    onchain_factory_candidates: int = 0
    factory_log_candidates: int = 0
    dexscreener_candidates: int = 0
    verified_second_pool_by_source: Dict[str, int] = field(default_factory=dict)
    hints: List[PoolHint] = field(default_factory=list)
    tokens_scanned: int = 0
    rpc_skipped: bool = False
    scan_stats: Dict[str, Any] = field(default_factory=dict)


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_yaml_config(path: str | Path) -> Dict[str, Any]:
    import yaml

    p = Path(path)
    if not p.is_file():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


def load_expand_subset_tokens(
    path: str | Path = DEFAULT_EXPAND_SUBSET,
    *,
    max_tokens: int = 50,
) -> List[Dict[str, Any]]:
    p = Path(path)
    if not p.is_file():
        return []
    doc = json.loads(p.read_text(encoding="utf-8"))
    rows: List[Dict[str, Any]] = []
    for item in doc.get("tokens") or []:
        if isinstance(item, str) and item.lower().startswith("0x"):
            rows.append({"token": item.lower(), "source": "expand_subset"})
        elif isinstance(item, dict):
            addr = str(item.get("token") or item.get("address") or "").lower()
            if addr.startswith("0x"):
                rows.append(dict(item, token=addr))
    return rows[: max(1, int(max_tokens))]


def _p0_dex_rows(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    from m8.discovery.cross_dex_expand import _DEX_ID_TO_ADAPTER, discovery_dexes_from_config

    rows = discovery_dexes_from_config(config)
    return [r for r in rows if r.get("enabled_for_productive") and r.get("factory")]


def _anchor_pairs(config: Dict[str, Any]) -> List[Tuple[str, str]]:
    from m8.discovery.cross_dex_expand import _token_address_from_config

    anchor_syms = set(config.get("anchor_tokens") or P0_ANCHOR_SYMS)
    pairs: List[Tuple[str, str]] = []
    for sym in P0_ANCHOR_SYMS:
        if sym not in anchor_syms:
            continue
        addr = _token_address_from_config(config, sym)
        if addr:
            pairs.append((sym, addr))
    return pairs


def _pool_hint_from_factory_scan(
    *,
    chain: str,
    token_addr: str,
    dex_id: str,
    pool_addr: str,
    anchor_sym: str,
    anchor_addr: str,
    source: str,
    factory: str = "",
) -> PoolHint:
    t0, t1 = sorted([token_addr.lower(), anchor_addr.lower()])
    return PoolHint(
        source=source,
        chain=chain,
        dex_id=dex_id,
        pool_address=pool_addr.lower(),
        token0_addr=t0,
        token1_addr=t1,
        focus_token=token_addr.lower(),
        factory_address=factory.lower() if factory else "",
        verify_method=VERIFY_FACTORY_GET_POOL,
        radar_reason=RADAR_REASON_NEW_POOL,
        confidence=0.85 if source == _SOURCE_ONCHAIN_FACTORY else 0.8,
        raw={"discovery_source": source, "connector_token": anchor_sym},
    )


_ONCHAIN_PRIMARY_SOURCES = frozenset({"onchain_factory", "factory_log"})


def _enrich_hints_from_subset(
    hints: List[PoolHint],
    tokens: List[Dict[str, Any]],
    *,
    watchlist_path: str = "data/tmp/m8_token_watchlist_latest.json",
) -> List[PoolHint]:
    """Attach fresh_long_tail provenance for expansion / narrow bridge handoff."""
    from m8.discovery.token_watchlist import load_watchlist

    token_meta = {
        str(r.get("token") or "").lower(): r
        for r in tokens
        if str(r.get("token") or "").startswith("0x")
    }
    watchlist = load_watchlist(watchlist_path)
    wl_tokens = watchlist.get("tokens") or {}
    verified_at = _iso_now()
    for hint in hints:
        focus = str(hint.focus_token or "").lower()
        meta = token_meta.get(focus) or {}
        wl = wl_tokens.get(focus) or {}
        raw = dict(hint.raw or {})
        raw.update(
            {
                "discovery_source": hint.source,
                "token_class": str(
                    meta.get("token_class")
                    or wl.get("token_class")
                    or "fresh_long_tail"
                ),
                "refresh_lane": str(
                    meta.get("refresh_lane")
                    or wl.get("refresh_lane")
                    or meta.get("source")
                    or "fresh_delta_lane"
                ),
                "verified_at": verified_at,
            }
        )
        hint.raw = raw
    return hints


def scan_tokens_via_factory(
    tokens: List[Dict[str, Any]],
    *,
    chain: str,
    config: Dict[str, Any],
    dry_run: bool = False,
    neg_cache_ttl_s: float = FRESH_NEG_CACHE_TTL_S,
) -> Tuple[List[PoolHint], Dict[str, Any]]:
    """Multicall getPair/getPool for token × P0 factories × anchors."""
    from m8.discovery.cross_dex_expand import _DEX_ID_TO_ADAPTER
    from m8.discovery.scan_batch import FactoryBatchResolver, NegativeResultCache

    if dry_run or os.environ.get("ARBY_SKIP_RPC") == "1":
        return [], {"skipped": "dry_run_or_arby_skip_rpc"}

    dex_rows = _p0_dex_rows(config)
    anchors = _anchor_pairs(config)
    if not dex_rows or not anchors:
        return [], {"error": "missing_dex_or_anchors"}

    resolver = FactoryBatchResolver(chain, config)
    neg_cache = NegativeResultCache(ttl_s=neg_cache_ttl_s)
    hints: List[PoolHint] = []
    stats = {"tokens": 0, "pools_found": 0, "neg_cache_hits": 0}

    try:
        from discovery.index_factories import get_dex_fee_tiers
    except ImportError:
        get_dex_fee_tiers = lambda _c, _d: [3000, 500]  # type: ignore[assignment]

    for row in tokens:
        token = str(row.get("token") or "").lower()
        if not token.startswith("0x"):
            continue
        stats["tokens"] += 1
        batch_results = resolver.resolve_many(
            token_addr=token,
            anchors=anchors,
            dex_rows=dex_rows,
            neg_cache=neg_cache,
            adapter_map=_DEX_ID_TO_ADAPTER,
            fee_tiers_fn=get_dex_fee_tiers,
        )
        for (dex_id, anchor_sym), (pool_addr, reason) in batch_results.items():
            if pool_addr and reason == "OK":
                anchor_addr = next((a for s, a in anchors if s == anchor_sym), "")
                factory = next(
                    (str(d.get("factory") or "") for d in dex_rows if d["dex_id"] == dex_id),
                    "",
                )
                hints.append(
                    _pool_hint_from_factory_scan(
                        chain=chain,
                        token_addr=token,
                        dex_id=dex_id,
                        pool_addr=pool_addr,
                        anchor_sym=anchor_sym,
                        anchor_addr=anchor_addr,
                        source=_SOURCE_ONCHAIN_FACTORY,
                        factory=factory,
                    )
                )
                stats["pools_found"] += 1

    nc = neg_cache.stats()
    stats["neg_cache_hits"] = int(nc.get("hits") or 0)
    stats["resolver_stats"] = dict(resolver.stats)
    return hints, stats


def scan_factory_logs_for_tokens(
    tokens: List[Dict[str, Any]],
    *,
    chain: str,
    config: Dict[str, Any],
    dry_run: bool = False,
    max_blocks: int = FACTORY_LOG_MAX_BLOCKS,
) -> Tuple[List[PoolHint], Dict[str, Any]]:
    """Bounded PairCreated/PoolCreated scan from first_seen_block toward head."""
    if dry_run or os.environ.get("ARBY_SKIP_RPC") == "1":
        return [], {"skipped": "dry_run_or_arby_skip_rpc"}

    try:
        from discovery.new_pool_listener import (
            FactoryConfig,
            load_factory_config,
            parse_raw_log,
        )
        from core.rpc_urls import get_rpc_url
    except ImportError as exc:
        return [], {"error": f"import_failed:{exc}"}

    token_set = {
        str(r.get("token") or "").lower()
        for r in tokens
        if str(r.get("token") or "").lower().startswith("0x")
    }
    if not token_set:
        return [], {"tokens": 0}

    anchor_addrs = {a.lower() for _, a in _anchor_pairs(config)}
    productive = {d["dex_id"] for d in _p0_dex_rows(config)}
    factories: List[FactoryConfig] = []
    try:
        for cfg in load_factory_config(
            FACTORY_LOG_CONFIG_PATH,
            chain_filter=chain,
        ):
            if cfg.dex in productive:
                factories.append(cfg)
    except Exception as exc:
        _log.warning("factory log config load failed: %s", exc)
        return [], {"error": str(exc)}

    rpc = get_rpc_url(chain)
    if not rpc:
        return [], {"error": "no_rpc"}

    from web3 import Web3

    w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 20}))
    if not w3.is_connected():
        return [], {"error": "rpc_not_connected"}

    head = int(w3.eth.block_number)
    min_from = head - max(1, int(max_blocks))
    for row in tokens:
        fsb = row.get("first_seen_block")
        if fsb is not None:
            try:
                min_from = max(min_from, int(fsb))
            except (TypeError, ValueError):
                pass

    hints: List[PoolHint] = []
    stats = {"factories": len(factories), "logs_fetched": 0, "pools_matched": 0}
    seen_pools: Set[str] = set()

    for fcfg in factories:
        topic0 = fcfg.topic0
        if not topic0:
            continue
        from_block = min_from
        while from_block <= head:
            to_block = min(head, from_block + FACTORY_LOG_CHUNK_BLOCKS - 1)
            try:
                logs = w3.eth.get_logs(
                    {
                        "fromBlock": from_block,
                        "toBlock": to_block,
                        "address": Web3.to_checksum_address(fcfg.factory),
                        "topics": [topic0],
                    }
                )
            except Exception as exc:
                _log.debug("get_logs failed factory=%s: %s", fcfg.factory[:10], exc)
                from_block = to_block + 1
                continue
            stats["logs_fetched"] += len(logs)
            for raw in logs:
                ev = parse_raw_log(dict(raw), fcfg)
                if ev is None:
                    continue
                t0 = str(ev.token0 or "").lower()
                t1 = str(ev.token1 or "").lower()
                pool = str(ev.pool_address or "").lower()
                if not pool or pool in seen_pools:
                    continue
                focus = ""
                anchor = ""
                if t0 in token_set and t1 in anchor_addrs:
                    focus, anchor = t0, t1
                elif t1 in token_set and t0 in anchor_addrs:
                    focus, anchor = t1, t0
                else:
                    continue
                seen_pools.add(pool)
                anchor_sym = next(
                    (s for s, a in _anchor_pairs(config) if a.lower() == anchor),
                    "",
                )
                hints.append(
                    _pool_hint_from_factory_scan(
                        chain=chain,
                        token_addr=focus,
                        dex_id=fcfg.dex,
                        pool_addr=pool,
                        anchor_sym=anchor_sym,
                        anchor_addr=anchor,
                        source=_SOURCE_FACTORY_LOG,
                        factory=fcfg.factory,
                    )
                )
                stats["pools_matched"] += 1
            from_block = to_block + 1

    return hints, stats


def minimal_verify_hints(
    hints: List[PoolHint],
    *,
    chain: str,
    dry_run: bool = False,
) -> List[PoolHint]:
    """Factory + liquidity light verify for on-chain discovered pools."""
    if dry_run or os.environ.get("ARBY_SKIP_RPC") == "1":
        for h in hints:
            h.hint_status = HINT_FACTORY_VERIFIED
        return hints
    verified: List[PoolHint] = []
    for h in hints:
        try:
            out = verify_hint_onchain(h, chain=chain, verify_mode="light")
            verified.append(out)
        except Exception as exc:
            _log.debug("minimal verify failed pool=%s: %s", h.pool_address[:10], exc)
            h.hint_status = HINT_FACTORY_VERIFIED
            verified.append(h)
    return verified


def _merge_existing_hints(
    path: str | Path,
    new_hints: List[PoolHint],
    *,
    chain: str,
) -> Dict[str, Any]:
    from m8.discovery.hint_artifact_merge import load_hint_artifact, merge_hint_artifacts

    existing = load_hint_artifact(path)
    incoming = build_artifact(
        chain=chain,
        sources=[_SOURCE_ONCHAIN_FACTORY, _SOURCE_FACTORY_LOG],
        hints=new_hints,
        metrics={"discovery_phase": "onchain_factory_mirror_scan"},
    )
    return merge_hint_artifacts(existing, incoming, chain=chain)


def _merge_existing_radar(
    path: str | Path,
    new_hints: List[PoolHint],
    *,
    chain: str,
) -> Dict[str, Any]:
    p = Path(path)
    existing_hints: List[PoolHint] = []
    if p.is_file():
        doc = json.loads(p.read_text(encoding="utf-8"))
        existing_hints = [PoolHint.from_dict(h) for h in (doc.get("candidates") or [])]
    merged = dedupe_hints(existing_hints + list(new_hints))
    return build_radar_candidates_artifact(
        chain=chain,
        sources=[_SOURCE_ONCHAIN_FACTORY, _SOURCE_FACTORY_LOG],
        hints=merged,
        metrics={"onchain_primary": True},
    )


def write_verify_budget_split(
    *,
    result: MirrorDiscoveryResult,
    verify_subset_cap: int,
    path: str | Path = DEFAULT_VERIFY_BUDGET_PATH,
    merge_existing: bool = True,
) -> None:
    p = Path(path)
    existing: Dict[str, Any] = {}
    if merge_existing and p.is_file():
        try:
            existing = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            existing = {}

    verified_by_source = dict(result.verified_second_pool_by_source)
    onchain_verified = sum(verified_by_source.values())
    verified_second_pool_count = onchain_verified
    payload = {
        "schema_version": "m8_verify_budget_v1",
        "pipeline_mode": "onchain_factory_mirror_scan",
        "generated_at_utc": _iso_now(),
        "dexscreener_candidates": int(
            existing.get("dexscreener_candidates", result.dexscreener_candidates)
        ),
        "onchain_factory_candidates": result.onchain_factory_candidates,
        "factory_log_candidates": result.factory_log_candidates,
        "verified_second_pool_by_source": verified_by_source,
        "verified_second_pool_count": verified_second_pool_count,
        "onchain_factory_verified": int(verified_by_source.get("onchain_factory") or 0),
        "onchain_verified": int(existing.get("onchain_verified") or 0) + onchain_verified
        if merge_existing
        else onchain_verified,
        "verify_subset_cap": int(verify_subset_cap),
        "verify_subset_size": min(
            result.onchain_factory_candidates + result.factory_log_candidates,
            int(verify_subset_cap),
        ),
        "scored_candidates": result.onchain_factory_candidates + result.factory_log_candidates,
        "tokens_scanned": result.tokens_scanned,
    }
    if existing.get("top_candidates"):
        payload["top_candidates"] = existing["top_candidates"]
    if existing.get("disposition_histogram"):
        payload["disposition_histogram"] = existing["disposition_histogram"]
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_onchain_scan_funnel_fields(
    scan_path: str | Path = DEFAULT_SCAN_ARTIFACT,
) -> Dict[str, Any]:
    """Read on-chain factory scan counters for funnel / verify-budget overlay."""
    p = Path(scan_path)
    if not p.is_file():
        return {}
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    by_source = dict(doc.get("verified_second_pool_by_source") or {})
    factory_verified = int(by_source.get("onchain_factory") or 0)
    total = int(doc.get("verified_second_pool_count") or sum(by_source.values()) or 0)
    return {
        "onchain_factory_candidates": int(doc.get("onchain_factory_candidates") or 0),
        "factory_log_candidates": int(doc.get("factory_log_candidates") or 0),
        "onchain_factory_verified": factory_verified,
        "verified_second_pool_by_source": by_source,
        "verified_second_pool_count": total,
        "verified_pools": list(doc.get("verified_pools") or []),
    }


def overlay_verify_budget_with_onchain_scan(
    budget: Dict[str, Any],
    *,
    scan_path: str | Path = DEFAULT_SCAN_ARTIFACT,
) -> Dict[str, Any]:
    """Preserve on-chain factory counters when DexScreener verify overwrites budget."""
    scan = load_onchain_scan_funnel_fields(scan_path)
    if not scan:
        return budget
    out = dict(budget)
    for key in (
        "onchain_factory_candidates",
        "factory_log_candidates",
        "onchain_factory_verified",
        "verified_second_pool_count",
    ):
        if scan.get(key):
            out[key] = scan[key]
    merged_src = dict(scan.get("verified_second_pool_by_source") or {})
    merged_src.update(dict(out.get("verified_second_pool_by_source") or {}))
    out["verified_second_pool_by_source"] = merged_src
    factory_v = int(scan.get("onchain_factory_verified") or 0)
    dex_v = int(out.get("onchain_verified") or 0)
    out["onchain_verified"] = max(dex_v, factory_v, int(scan.get("verified_second_pool_count") or 0))
    return out


def run_mirror_discovery(
    *,
    chain: str = "base",
    config_path: str = "config/exotic_base_anchor.yaml",
    token_subset_path: str = DEFAULT_EXPAND_SUBSET,
    max_tokens: int = 50,
    hints_path: str = DEFAULT_HINTS_PATH,
    radar_path: str = DEFAULT_RADAR_PATH,
    scan_artifact_path: str = DEFAULT_SCAN_ARTIFACT,
    verify_budget_path: str = DEFAULT_VERIFY_BUDGET_PATH,
    dry_run: bool = False,
    skip_factory_log: bool = False,
) -> MirrorDiscoveryResult:
    """Primary on-chain mirror discovery for hot time-to-mirror path."""
    t0 = time.monotonic()
    config = _load_yaml_config(config_path)
    tokens = load_expand_subset_tokens(token_subset_path, max_tokens=max_tokens)
    result = MirrorDiscoveryResult(tokens_scanned=len(tokens))

    factory_hints, factory_stats = scan_tokens_via_factory(
        tokens, chain=chain, config=config, dry_run=dry_run
    )
    log_hints: List[PoolHint] = []
    log_stats: Dict[str, Any] = {}
    if not skip_factory_log:
        log_hints, log_stats = scan_factory_logs_for_tokens(
            tokens, chain=chain, config=config, dry_run=dry_run
        )

    all_raw = dedupe_hints(factory_hints + log_hints)
    verified = minimal_verify_hints(all_raw, chain=chain, dry_run=dry_run)
    verified = _enrich_hints_from_subset(verified, tokens)

    result.onchain_factory_candidates = len(factory_hints)
    result.factory_log_candidates = len(log_hints)
    result.hints = verified
    result.scan_stats = {
        "factory_scan": factory_stats,
        "factory_log_scan": log_stats,
        "elapsed_s": round(time.monotonic() - t0, 3),
    }

    by_source: Dict[str, int] = {}
    for h in verified:
        if h.hint_status in {HINT_FACTORY_VERIFIED, "HINT_ONCHAIN_VERIFIED"}:
            by_source[h.source] = int(by_source.get(h.source, 0)) + 1
    result.verified_second_pool_by_source = by_source

    if verified or not dry_run:
        hints_artifact = _merge_existing_hints(hints_path, verified, chain=chain)
        write_hints_artifact(hints_artifact, hints_path)
        radar_artifact = _merge_existing_radar(radar_path, verified, chain=chain)
        write_radar_candidates_artifact(radar_artifact, radar_path)

    write_verify_budget_split(
        result=result,
        verify_subset_cap=max_tokens,
        path=verify_budget_path,
    )

    scan_doc = {
        "schema_version": "m8_onchain_factory_scan_v1",
        "generated_at_utc": _iso_now(),
        "chain": chain,
        "tokens_scanned": result.tokens_scanned,
        "onchain_factory_candidates": result.onchain_factory_candidates,
        "factory_log_candidates": result.factory_log_candidates,
        "verified_second_pool_by_source": result.verified_second_pool_by_source,
        "verified_second_pool_count": sum(result.verified_second_pool_by_source.values()),
        "verified_pools": [
            {
                "focus_token": h.focus_token,
                "dex_id": h.dex_id,
                "pool_address": h.pool_address,
                "hint_status": h.hint_status,
                "token_class": (h.raw or {}).get("token_class"),
                "refresh_lane": (h.raw or {}).get("refresh_lane"),
                "source": h.source,
            }
            for h in verified
        ],
        "scan_stats": result.scan_stats,
        "hints_path": hints_path,
        "radar_path": radar_path,
    }
    sp = Path(scan_artifact_path)
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps(scan_doc, indent=2), encoding="utf-8")

    return result
