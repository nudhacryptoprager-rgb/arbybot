"""Phase 1.5 — token watch-list, active second-pool scan, transition metrics."""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from discovery.new_pool_listener import FactoryConfig, NewPoolEvent
from m8.discovery.anchor_registry import build_anchor_maps
from m8.discovery.factory_token_scan import (
    DEFAULT_MAX_LOOKBACK_BLOCKS,
    find_recent_pools_containing_token,
    new_pool_event_to_registry_dict,
)
from m8.discovery.pending_pair_registry import update_registry
from m8.discovery.token_classify import (
    TOKEN_CLASS_FRESH,
    TOKEN_CLASS_KNOWN_MAJOR,
    TOKEN_CLASS_KNOWN_MID,
    classify_token_class,
    prior_venue_stats,
)

logger = logging.getLogger(__name__)

SCHEMA_VERSION = "m8_token_watchlist.1"
DEFAULT_WATCHLIST_PATH = "data/tmp/m8_token_watchlist_latest.json"

# Scan backoff policy (seconds) — timing constants, not chain data.
SCAN_BACKOFF_STAGES_S: Tuple[int, ...] = (30, 120, 600, 3600)

GetLogsFn = Callable[[Dict[str, Any]], List[Any]]


def _empty_watchlist() -> Dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": None,
        "tokens": {},
        "metrics": {
            "time_to_second_pool_s": [],
            "same_tx_second_pool_count": 0,
            "same_block_second_pool_count": 0,
            "cross_mechanic_transition_count": 0,
            "transitions_1_to_2": 0,
            "no_second_pool_in_window": 0,
        },
    }


def load_watchlist(path: str = DEFAULT_WATCHLIST_PATH) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return _empty_watchlist()
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return _empty_watchlist()
    if not isinstance(data, dict):
        return _empty_watchlist()
    data.setdefault("schema_version", SCHEMA_VERSION)
    data.setdefault("tokens", {})
    data.setdefault("metrics", _empty_watchlist()["metrics"])
    return data


def save_watchlist(watchlist: Dict[str, Any], path: str = DEFAULT_WATCHLIST_PATH) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    watchlist["schema_version"] = SCHEMA_VERSION
    watchlist["generated_at_utc"] = datetime.now(tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    p.write_text(json.dumps(watchlist, ensure_ascii=False, indent=2), encoding="utf-8")


def _pricing_model_for_adapter(adapter_type: str) -> str:
    from m9.graph_arb.cost_model import adapter_pricing_model

    return adapter_pricing_model(adapter_type or "uniswap_v3")


def _mechanics_for_dexes(dex_ids: Set[str], dex_adapter: Dict[str, str]) -> List[str]:
    models: List[str] = []
    seen: Set[str] = set()
    for dex in sorted(dex_ids):
        model = _pricing_model_for_adapter(dex_adapter.get(dex, ""))
        if model not in seen:
            seen.add(model)
            models.append(model)
    return models


def _dex_adapter_map(config: Dict[str, Any]) -> Dict[str, str]:
    return {
        str(dex_id): str((cfg or {}).get("adapter_type") or "")
        for dex_id, cfg in (config.get("dexes") or {}).items()
    }


def upsert_watch_entry_from_event(
    watchlist: Dict[str, Any],
    event_dict: Dict[str, Any],
    *,
    exotic_address: str,
    exotic_symbol: str,
    now_ts: float,
    config: Optional[Dict[str, Any]] = None,
    registry: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create or refresh watch-list row for exotic token from a pool event."""
    tokens = watchlist.setdefault("tokens", {})
    addr = exotic_address.lower()
    prior_pools, prior_dexes = prior_venue_stats(registry, addr)
    token_class = (
        classify_token_class(
            addr,
            symbol=exotic_symbol,
            config=config or {},
            registry=registry,
            now_ts=now_ts,
            prior_pool_count=prior_pools,
        )
        if config
        else TOKEN_CLASS_FRESH
    )
    entry = tokens.get(addr)
    dex = str(event_dict.get("dex") or event_dict.get("dex_id") or "")
    pool = str(event_dict.get("pool") or event_dict.get("pool_address") or "")
    block = int(event_dict.get("block_number") or 0)
    tx = str(event_dict.get("tx_hash") or "")

    if entry is None:
        entry = {
            "token": addr,
            "symbol": exotic_symbol or addr[:10],
            "token_class": token_class,
            "first_pool": pool,
            "first_dex": dex,
            "first_block": block,
            "first_tx_hash": tx,
            "first_seen_ts": now_ts,
            "seen_on_dexes": [dex] if dex else [],
            "mechanics_seen": [],
            "scan_backoff_stage": 0,
            "last_scan_ts": 0.0,
            "second_pool_verified": False,
            "prior_pool_count": prior_pools,
            "prior_dex_count": prior_dexes,
            "first_seen_as_new_token": token_class == TOKEN_CLASS_FRESH,
            "first_seen_as_known_pool": token_class
            in (TOKEN_CLASS_KNOWN_MAJOR, TOKEN_CLASS_KNOWN_MID),
            "first_quoteable_block_delta": None,
            "first_swap_after_pool_block_delta": None,
            "price_deviation_decay_half_life_s": None,
        }
        tokens[addr] = entry
    else:
        entry["symbol"] = exotic_symbol or entry.get("symbol") or addr[:10]
        entry["token_class"] = token_class
        entry["prior_pool_count"] = prior_pools
        entry["prior_dex_count"] = prior_dexes
        if dex and dex not in entry.get("seen_on_dexes", []):
            entry.setdefault("seen_on_dexes", []).append(dex)

    return entry


def scan_due(entry: Dict[str, Any], now_ts: float) -> bool:
    """True when backoff elapsed since last scan."""
    stage = int(entry.get("scan_backoff_stage") or 0)
    stage = min(stage, len(SCAN_BACKOFF_STAGES_S) - 1)
    delay = SCAN_BACKOFF_STAGES_S[stage]
    last = float(entry.get("last_scan_ts") or 0.0)
    if last <= 0:
        return True
    return (now_ts - last) >= delay


def advance_backoff(entry: Dict[str, Any]) -> None:
    stage = int(entry.get("scan_backoff_stage") or 0)
    entry["scan_backoff_stage"] = min(stage + 1, len(SCAN_BACKOFF_STAGES_S) - 1)


def _record_second_pool(
    entry: Dict[str, Any],
    *,
    event_dict: Dict[str, Any],
    dex_adapter: Dict[str, str],
    now_ts: float,
    metrics: Dict[str, Any],
) -> bool:
    """Record second venue; return True on fresh 1→2 transition."""
    dex = str(event_dict.get("dex") or event_dict.get("dex_id") or "")
    if not dex:
        return False

    seen: Set[str] = set(entry.get("seen_on_dexes") or [])
    prev_count = len(seen)
    seen.add(dex)
    entry["seen_on_dexes"] = sorted(seen)
    entry["mechanics_seen"] = _mechanics_for_dexes(seen, dex_adapter)

    if prev_count >= 2:
        return False
    if len(seen) < 2:
        return False
    if entry.get("second_pool_verified"):
        return False

    entry["second_pool"] = str(event_dict.get("pool") or event_dict.get("pool_address") or "")
    entry["second_dex"] = dex
    entry["second_block"] = int(event_dict.get("block_number") or 0)
    entry["second_tx_hash"] = str(event_dict.get("tx_hash") or "")
    entry["transition_ts"] = now_ts
    entry["second_pool_verified"] = True

    first_ts = float(entry.get("first_seen_ts") or now_ts)
    t2s = round(now_ts - first_ts, 3)
    entry["time_to_second_pool_s"] = t2s
    metrics.setdefault("time_to_second_pool_s", []).append(t2s)

    if entry.get("first_tx_hash") and entry["second_tx_hash"] == entry["first_tx_hash"]:
        metrics["same_tx_second_pool_count"] = int(metrics.get("same_tx_second_pool_count") or 0) + 1
    if int(entry.get("first_block") or 0) == entry["second_block"]:
        metrics["same_block_second_pool_count"] = int(
            metrics.get("same_block_second_pool_count") or 0
        ) + 1

    if len(entry.get("mechanics_seen") or []) >= 2:
        metrics["cross_mechanic_transition_count"] = int(
            metrics.get("cross_mechanic_transition_count") or 0
        ) + 1

    metrics["transitions_1_to_2"] = int(metrics.get("transitions_1_to_2") or 0) + 1
    return True


def run_active_second_pool_scan(
    *,
    token_address: str,
    entry: Dict[str, Any],
    chain: str,
    config: Dict[str, Any],
    registry: Dict[str, Any],
    w3: Any,
    watchlist: Dict[str, Any],
    get_logs: Optional[GetLogsFn] = None,
    factory_configs: Optional[List[FactoryConfig]] = None,
    mirror_index: Any = None,
    head_block: Optional[int] = None,
    now_ts: Optional[float] = None,
    max_lookback_blocks: int = DEFAULT_MAX_LOOKBACK_BLOCKS,
) -> Dict[str, Any]:
    """Active scan: factory logs + mirror indices; update registry + watch-list."""
    from m8.discovery.cross_dex_expand import discovery_dexes_from_config
    from m8.discovery.mirror_index import MirrorIndex

    now_ts = now_ts if now_ts is not None else time.time()
    metrics = watchlist.setdefault("metrics", _empty_watchlist()["metrics"])
    addr_to_sym, _ = build_anchor_maps(config)
    dex_adapter = _dex_adapter_map(config)

    if head_block is None:
        head_block = int(w3.eth.block_number)

    first_block = int(entry.get("first_block") or head_block)
    from_block = max(0, max(first_block - 2, head_block - max_lookback_blocks))
    to_block = head_block

    factory_events: List[NewPoolEvent] = find_recent_pools_containing_token(
        token_address,
        from_block=from_block,
        to_block=to_block,
        chain=chain,
        w3=w3,
        get_logs=get_logs,
        factory_configs=factory_configs,
    )

    registry_events: List[Dict[str, Any]] = []
    for ev in factory_events:
        registry_events.append(
            new_pool_event_to_registry_dict(ev, addr_to_sym=addr_to_sym)
        )

    allowed = {d["dex_id"] for d in discovery_dexes_from_config(config)}
    idx = mirror_index or MirrorIndex.load(chain)
    for row in idx.find_pools_containing_token(token_address, dex_ids=allowed):
        dex_id = str(row.get("dex_id") or "")
        pool = str(row.get("pool_address") or "")
        if not dex_id or not pool:
            continue
        registry_events.append({
            "chain": chain,
            "dex": dex_id,
            "dex_id": dex_id,
            "pool": pool,
            "pool_address": pool,
            "token0": row.get("token0_addr") or row.get("token0") or "",
            "token1": row.get("token1_addr") or row.get("token1") or "",
            "token0_symbol": row.get("token0_symbol") or "",
            "token1_symbol": row.get("token1_symbol") or "",
            "block_number": entry.get("first_block") or 0,
            "tx_hash": "",
            "event_id": f"mirror:{dex_id}:{pool}:{token_address}",
            "factory": "",
            "adapter_type": dex_adapter.get(dex_id, ""),
            "event_name": "MirrorIndexHit",
            "resolve_source": row.get("resolve_source"),
        })

    update_registry(registry, registry_events, now_ts=now_ts)

    transition = False
    for ev_dict in registry_events:
        if _record_second_pool(
            entry,
            event_dict=ev_dict,
            dex_adapter=dex_adapter,
            now_ts=now_ts,
            metrics=metrics,
        ):
            transition = True

    entry["last_scan_ts"] = now_ts
    advance_backoff(entry)

    return {
        "token": token_address.lower(),
        "factory_events_found": len(factory_events),
        "registry_events_merged": len(registry_events),
        "transition_1_to_2": transition,
        "seen_on_dexes": list(entry.get("seen_on_dexes") or []),
        "second_pool_verified": bool(entry.get("second_pool_verified")),
    }


def metrics_summary(watchlist: Dict[str, Any]) -> Dict[str, Any]:
    """Aggregate Phase 1.5 metrics for hot-path artifact."""
    metrics = watchlist.get("metrics") or {}
    t2s = list(metrics.get("time_to_second_pool_s") or [])
    t2s_sorted = sorted(t2s)

    def _p50(vals: List[float]) -> Optional[float]:
        if not vals:
            return None
        return vals[len(vals) // 2]

    tokens = watchlist.get("tokens") or {}
    watching = sum(
        1 for t in tokens.values() if not t.get("second_pool_verified")
    )

    out = {
        "time_to_second_pool_s_p50": _p50(t2s_sorted),
        "time_to_second_pool_s_count": len(t2s),
        "same_tx_second_pool_count": int(metrics.get("same_tx_second_pool_count") or 0),
        "same_block_second_pool_count": int(
            metrics.get("same_block_second_pool_count") or 0
        ),
        "cross_mechanic_transition_count": int(
            metrics.get("cross_mechanic_transition_count") or 0
        ),
        "transitions_1_to_2": int(metrics.get("transitions_1_to_2") or 0),
        "watchlist_tokens": len(tokens),
        "watchlist_pending_second_pool": watching,
    }
    if watching > 0 and not t2s:
        out["existence_note"] = "NO_SECOND_POOL_IN_WINDOW"
    return out
