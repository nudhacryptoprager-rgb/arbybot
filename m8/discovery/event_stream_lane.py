"""Event-stream lane: factory log poll + webhook ingest → pending queue."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_EVENT_STREAM_ARTIFACT = Path("data/tmp/m8_event_stream_lane_latest.json")
DEFAULT_WATCHLIST_PATH = Path("data/tmp/m8_token_watchlist_latest.json")
DEFAULT_PENDING_QUEUE_PATH = Path("data/tmp/m8_time_to_mirror_pending_queue_latest.json")
DEFAULT_EXPAND_SUBSET = Path("data/tmp/m8_time_to_mirror_expand_subset.json")
DEFAULT_CONFIG_PATH = Path("config/exotic_base_anchor.yaml")


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_yaml_config(path: Path) -> Dict[str, Any]:
    import yaml

    if not path.is_file():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def parse_alchemy_webhook_events(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Normalize Alchemy Custom Webhook activity into pool-created events."""
    out: List[Dict[str, Any]] = []
    for block in payload.get("event", {}).get("data", {}).get("block", {}).get("logs", []):
        if not isinstance(block, dict):
            continue
        topics = block.get("topics") or []
        if not topics:
            continue
        out.append(
            {
                "source": "alchemy_webhook",
                "topic0": str(topics[0]),
                "address": str(block.get("address") or "").lower(),
                "transaction_hash": block.get("transactionHash"),
                "block_number": block.get("blockNumber"),
                "log_index": block.get("logIndex"),
                "raw": block,
            }
        )
    for activity in payload.get("activity") or []:
        if not isinstance(activity, dict):
            continue
        out.append(
            {
                "source": "alchemy_webhook_activity",
                "address": str(activity.get("toAddress") or activity.get("contractAddress") or "").lower(),
                "block_number": activity.get("blockNum"),
                "raw": activity,
            }
        )
    return out


def merge_events_into_watchlist(
    events: List[Dict[str, Any]],
    *,
    watchlist_path: Path = DEFAULT_WATCHLIST_PATH,
) -> Dict[str, Any]:
    """Upsert minimal watch entries from streamed factory events."""
    from m8.discovery.token_watchlist import load_watchlist, save_watchlist

    watchlist = load_watchlist(str(watchlist_path))
    tokens = watchlist.setdefault("tokens", {})
    now_ts = datetime.now(timezone.utc).timestamp()
    touched = 0
    for ev in events:
        pool = str(ev.get("pool") or ev.get("pool_address") or "").lower()
        focus = str(ev.get("focus_token") or ev.get("token") or "").lower()
        if not focus.startswith("0x"):
            continue
        is_raw_factory = str(ev.get("source") or "").startswith("raw_factory")
        entry = dict(tokens.get(focus) or {})
        entry.setdefault("first_seen_ts", now_ts)
        # Raw factory-log focus tokens go straight to the fresh_delta lane;
        # token-scoped poll events keep the generic event_stream_lane lane.
        if is_raw_factory:
            entry["refresh_lane"] = "fresh_delta_lane"
            entry["token_class"] = "fresh_long_tail"
        else:
            entry["refresh_lane"] = entry.get("refresh_lane") or "event_stream_lane"
            entry["token_class"] = entry.get("token_class") or "fresh_long_tail"
        if pool:
            entry.setdefault("first_pool", pool)
        if ev.get("dex_id"):
            entry.setdefault("first_dex", ev.get("dex_id"))
        if ev.get("source"):
            entry.setdefault("source", ev.get("source"))
        if ev.get("block_number"):
            entry.setdefault("first_seen_block", int(ev["block_number"]))
        entry["event_stream_last_seen_ts"] = now_ts
        tokens[focus] = entry
        touched += 1
    watchlist["event_stream_lane"] = {
        "last_ingest_utc": _iso_now(),
        "events_ingested": len(events),
        "tokens_touched": touched,
    }
    save_watchlist(watchlist, str(watchlist_path))
    return watchlist


def run_incremental_factory_log_poll(
    *,
    chain: str = "base",
    config_path: Path = DEFAULT_CONFIG_PATH,
    subset_path: Path = DEFAULT_EXPAND_SUBSET,
    max_tokens: int = 50,
    max_blocks: int = 500,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Short-window getLogs poll for P0 factories (no full radar window).

    Polls in two modes:
      1. Token-scoped: events for already tracked tokens (legacy behaviour).
      2. Raw anchor-side: events where one token is a known anchor and the
         other is an untracked focus token. This seeds the fresh_delta lane
         with brand-new long-tail tokens before DexScreener sees them.
    """
    from m8.discovery.onchain_factory_mirror_discovery import (
        load_expand_subset_tokens,
        scan_factory_logs_for_tokens,
        scan_raw_factory_logs_for_anchor_pools,
    )

    config = _load_yaml_config(config_path)

    # Legacy token-scoped poll.
    tokens = load_expand_subset_tokens(subset_path, max_tokens=max_tokens)
    hints, stats = scan_factory_logs_for_tokens(
        tokens,
        chain=chain,
        config=config,
        dry_run=dry_run or os.environ.get("ARBY_SKIP_RPC") == "1",
        max_blocks=max_blocks,
    )
    events: List[Dict[str, Any]] = []
    for h in hints:
        events.append(
            {
                "source": "factory_log_poll",
                "focus_token": h.focus_token,
                "pool": h.pool_address,
                "dex_id": h.dex_id,
                "block_number": (h.raw or {}).get("block_number"),
            }
        )

    # New raw anchor-side poll: discover new focus tokens from factory logs.
    raw_events, raw_stats = scan_raw_factory_logs_for_anchor_pools(
        chain=chain,
        config=config,
        max_blocks=max_blocks,
        dry_run=dry_run or os.environ.get("ARBY_SKIP_RPC") == "1",
    )
    if raw_events:
        merge_events_into_watchlist(raw_events)
        events.extend(raw_events)

    # Observer-mode scan: look for second venues on discovery_only factories for
    # tokens that are already in the watchlist/pending queue.
    from m8.discovery.token_watchlist import load_watchlist

    watchlist = load_watchlist(DEFAULT_WATCHLIST_PATH)
    focus_tokens = list((watchlist.get("tokens") or {}).keys())
    observer_events, observer_stats = scan_raw_factory_logs_for_anchor_pools(
        chain=chain,
        config=config,
        max_blocks=max_blocks,
        dry_run=dry_run or os.environ.get("ARBY_SKIP_RPC") == "1",
        observer_mode=True,
        focus_tokens=focus_tokens,
    )
    if observer_events:
        # Do not overwrite first_pool/first_dex; observer events are second venues.
        merge_events_into_watchlist(observer_events)
        events.extend(observer_events)

    all_events = events
    return {
        "schema_version": "m8_event_stream_lane_v1",
        "generated_at_utc": _iso_now(),
        "mode": "factory_log_poll",
        "events_emitted": len(all_events),
        "hints_from_poll": len(hints),
        "raw_factory_logs_fetched": raw_stats.get("logs_fetched", 0),
        "raw_anchor_pools_seen": raw_stats.get("raw_anchor_pools_seen", 0),
        "raw_factory_new_focus_tokens_total": raw_stats.get(
            "raw_factory_new_focus_tokens_total", 0
        ),
        "observer_factory_logs_fetched": observer_stats.get("logs_fetched", 0),
        "observer_anchor_pools_seen": observer_stats.get("raw_anchor_pools_seen", 0),
        "observer_factory_new_focus_tokens_total": observer_stats.get(
            "raw_factory_new_focus_tokens_total", 0
        ),
        "productive_factories_scanned": raw_stats.get("productive_factories_scanned", 0),
        "observer_factories_scanned": observer_stats.get("observer_factories_scanned", 0),
        "fresh_factory_event_hints_total": len(all_events),
        "factory_log_stats": stats,
        "raw_factory_log_stats": raw_stats,
        "observer_factory_log_stats": observer_stats,
        "observer_factory_events": observer_events,
        "raw_factory_events": raw_events,
    }


def run_event_stream_lane(
    *,
    chain: str = "base",
    webhook_payload_path: Optional[Path] = None,
    subset_path: Path = DEFAULT_EXPAND_SUBSET,
    max_tokens: int = 50,
    max_blocks: int = 500,
    output_path: Path = DEFAULT_EVENT_STREAM_ARTIFACT,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Primary entry: poll factory logs and optionally ingest webhook batch."""
    payload = run_incremental_factory_log_poll(
        chain=chain,
        subset_path=subset_path,
        max_tokens=max_tokens,
        max_blocks=max_blocks,
        dry_run=dry_run,
    )
    webhook_events = 0
    if webhook_payload_path and webhook_payload_path.is_file():
        raw = json.loads(webhook_payload_path.read_text(encoding="utf-8"))
        events = parse_alchemy_webhook_events(raw)
        webhook_events = len(events)
        if events:
            merge_events_into_watchlist(events)
        payload["webhook_events_ingested"] = webhook_events
    from m8.discovery.time_to_mirror_lane import (
        build_pending_queue_payload,
        load_watchlist,
    )

    pending = build_pending_queue_payload(load_watchlist(DEFAULT_WATCHLIST_PATH))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    DEFAULT_PENDING_QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_PENDING_QUEUE_PATH.write_text(json.dumps(pending, indent=2), encoding="utf-8")
    payload["pending_queue_refreshed"] = True
    payload["pending_count"] = pending.get("pending_count")
    payload["queue_buckets"] = pending.get("queues", {})
    return payload
