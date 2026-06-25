"""M8/M8.2 refresh lanes — isolate fresh delta from wide recall / audit."""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Set, Tuple

from m8.discovery.token_classify import (
    TOKEN_CLASS_FRESH,
    TOKEN_CLASS_KNOWN_MAJOR,
    _fresh_window_s,
)

REFRESH_LANE_FRESH_DELTA = "fresh_delta_lane"
REFRESH_LANE_WIDE_RECALL = "wide_recall_lane"
REFRESH_LANE_AUDIT = "audit_lane"

DEFAULT_WATCHLIST_AUDIT_TTL_S = 7.0 * 24.0 * 3600.0
DEFAULT_STALE_SCAN_TTL_S = 24.0 * 3600.0


def _entry_age_s(entry: Dict[str, Any], now_ts: float) -> float:
    first = entry.get("first_seen_ts")
    if first is None:
        return 0.0
    try:
        return max(0.0, float(now_ts) - float(first))
    except (TypeError, ValueError):
        return 0.0


def _scan_stale_s(entry: Dict[str, Any], now_ts: float) -> float:
    last = entry.get("last_scan_ts")
    if last is None or float(last) <= 0:
        return _entry_age_s(entry, now_ts)
    try:
        return max(0.0, float(now_ts) - float(last))
    except (TypeError, ValueError):
        return _entry_age_s(entry, now_ts)


def classify_refresh_lane(
    entry: Dict[str, Any],
    *,
    config: Dict[str, Any],
    now_ts: float,
    audit_ttl_s: float = DEFAULT_WATCHLIST_AUDIT_TTL_S,
    stale_scan_ttl_s: float = DEFAULT_STALE_SCAN_TTL_S,
    fresh_window_s: Optional[float] = None,
) -> str:
    """Assign one refresh lane for a watch-list row."""
    token_class = str(entry.get("token_class") or TOKEN_CLASS_FRESH)
    if token_class == TOKEN_CLASS_KNOWN_MAJOR:
        return REFRESH_LANE_AUDIT

    fresh_window = (
        float(fresh_window_s)
        if fresh_window_s is not None
        else _fresh_window_s(config)
    )
    age_s = _entry_age_s(entry, now_ts)
    scan_stale_s = _scan_stale_s(entry, now_ts)
    second_verified = bool(entry.get("second_pool_verified"))
    unresolved_1_to_2 = not second_verified and bool(
        entry.get("first_pool") or entry.get("first_dex")
    )

    if unresolved_1_to_2 and (
        token_class == TOKEN_CLASS_FRESH or age_s <= fresh_window
    ):
        return REFRESH_LANE_FRESH_DELTA

    if (
        not second_verified
        and age_s >= audit_ttl_s
        and scan_stale_s >= stale_scan_ttl_s
    ):
        return REFRESH_LANE_AUDIT

    return REFRESH_LANE_WIDE_RECALL


def apply_watchlist_lane_policy(
    watchlist: Dict[str, Any],
    *,
    config: Dict[str, Any],
    now_ts: Optional[float] = None,
    audit_ttl_s: float = DEFAULT_WATCHLIST_AUDIT_TTL_S,
    stale_scan_ttl_s: float = DEFAULT_STALE_SCAN_TTL_S,
) -> Dict[str, int]:
    """Stamp ``refresh_lane`` on each token row; return lane counts."""
    now = float(now_ts if now_ts is not None else time.time())
    tokens = watchlist.setdefault("tokens", {})
    counts: Dict[str, int] = {
        REFRESH_LANE_FRESH_DELTA: 0,
        REFRESH_LANE_WIDE_RECALL: 0,
        REFRESH_LANE_AUDIT: 0,
    }
    fresh_window = _fresh_window_s(config)
    for entry in tokens.values():
        lane = classify_refresh_lane(
            entry,
            config=config,
            now_ts=now,
            audit_ttl_s=audit_ttl_s,
            stale_scan_ttl_s=stale_scan_ttl_s,
            fresh_window_s=fresh_window,
        )
        entry["refresh_lane"] = lane
        counts[lane] = counts.get(lane, 0) + 1
    watchlist["lane_metrics"] = {
        "generated_at_epoch_s": now,
        "lane_counts": counts,
        "audit_ttl_s": audit_ttl_s,
        "stale_scan_ttl_s": stale_scan_ttl_s,
        "fresh_window_s": fresh_window,
    }
    return counts


def select_tokens_by_lane(
    watchlist: Dict[str, Any],
    lane: str,
    *,
    limit: int,
    exclude: Optional[Set[str]] = None,
) -> List[str]:
    """Return token addresses for one lane, freshest / least-scanned first."""
    exclude = exclude or set()
    rows: List[Tuple[float, float, str]] = []
    for addr, entry in (watchlist.get("tokens") or {}).items():
        if addr in exclude:
            continue
        if str(entry.get("refresh_lane") or "") != lane:
            continue
        first = float(entry.get("first_seen_ts") or 0.0)
        last_scan = float(entry.get("last_scan_ts") or 0.0)
        rows.append((-first, last_scan, addr.lower()))
    rows.sort()
    return [addr for _, _, addr in rows[: max(0, int(limit))]]


def build_radar_token_list(
    watchlist: Dict[str, Any],
    *,
    config: Dict[str, Any],
    max_tokens: int,
    fresh_first: bool = True,
    now_ts: Optional[float] = None,
) -> Tuple[List[str], Dict[str, Any]]:
    """Build radar scan order: fresh delta first, then wide recall (never audit-first)."""
    apply_watchlist_lane_policy(
        watchlist,
        config=config,
        now_ts=now_ts,
    )
    cap = max(0, int(max_tokens))
    fresh = select_tokens_by_lane(
        watchlist,
        REFRESH_LANE_FRESH_DELTA,
        limit=cap,
    )
    selected: List[str] = list(fresh)
    exclude: Set[str] = set(selected)
    if fresh_first and len(selected) < cap:
        wide = select_tokens_by_lane(
            watchlist,
            REFRESH_LANE_WIDE_RECALL,
            limit=cap - len(selected),
            exclude=exclude,
        )
        selected.extend(wide)
        exclude.update(wide)
    meta = {
        "max_tokens": cap,
        "fresh_delta_count": len(fresh),
        "wide_recall_count": max(0, len(selected) - len(fresh)),
        "audit_excluded": True,
        "lane_metrics": dict(watchlist.get("lane_metrics") or {}),
    }
    return selected, meta
