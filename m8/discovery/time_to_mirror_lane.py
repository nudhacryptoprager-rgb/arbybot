"""Time-to-mirror lane helpers: pending priority, SLA artifact, narrow M9 handoff."""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_WATCHLIST_PATH = Path("data/tmp/m8_token_watchlist_latest.json")
DEFAULT_EXPANSION_PATH = Path("data/runs/_rolling/m8_cross_dex_expansion_latest.json")
DEFAULT_PENDING_QUEUE_PATH = Path("data/tmp/m8_time_to_mirror_pending_queue_latest.json")
DEFAULT_SLA_PATH = Path("data/tmp/m8_time_to_mirror_sla_latest.json")
DEFAULT_NARROW_BRIDGE_PATH = Path("data/tmp/m9_bridge_time_to_mirror_narrow_latest.json")
DEFAULT_MIRROR_CHECKPOINT_PATH = Path("data/tmp/m8_mirror_quote_smoke_progress.json")
FRESH_DELTA_SUBSET_PATH = Path("data/tmp/m8_fresh_delta_token_subset.json")
TIME_TO_MIRROR_EXPAND_SUBSET_PATH = Path("data/tmp/m8_time_to_mirror_expand_subset.json")
SECOND_POOL_TRANSITION_SUBSET_PATH = Path("data/tmp/m8_second_pool_transition_subset.json")


def mirror_readiness_by_focus(
    routes: List[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """Per-token same-pair mirror readiness (requires 2+ quoteable legs on 2+ DEXes)."""
    from m8.discovery.cross_dex_expand import (
        _same_pair_route_quoteable,
        evaluate_mirror_readiness,
    )
    from m8.discovery.mirror_quote_smoke import is_same_pair_mirror_route

    by_focus: Dict[str, Dict[str, Any]] = {}
    for route in routes:
        if not is_same_pair_mirror_route(route):
            continue
        focus = str(
            route.get("focus_token_address") or route.get("exotic_address") or ""
        ).lower()
        if not focus.startswith("0x"):
            continue
        bucket = by_focus.setdefault(focus, {"dexes": set(), "same_pair": []})
        dex = str(route.get("dex_id") or "")
        if dex:
            bucket["dexes"].add(dex)
        bucket["same_pair"].append(route)

    out: Dict[str, Dict[str, Any]] = {}
    for focus, info in by_focus.items():
        same = info["same_pair"]
        dexes = {str(r.get("dex_id") or "") for r in same if r.get("dex_id")}
        quoteable = sum(1 for r in same if _same_pair_route_quoteable(r))
        mr = evaluate_mirror_readiness(
            token_seen_on_dexes=len(info["dexes"]),
            same_pair_routes=len(same),
            same_pair_dexes=len(dexes),
            quoteable_same_pair_routes=quoteable,
        )
        out[focus] = {**mr, "quoteable_legs": quoteable}
    return out


def build_time_to_mirror_expand_subset(
    *,
    max_tokens: int,
    fresh_subset_path: Path = FRESH_DELTA_SUBSET_PATH,
    watchlist_path: Path = DEFAULT_WATCHLIST_PATH,
    output_path: Path = TIME_TO_MIRROR_EXPAND_SUBSET_PATH,
) -> int:
    """Write hot-path expansion subset: fresh_delta ∪ top pending queue tokens."""
    from m8.discovery.token_subset import write_token_subset_file

    fresh_meta: Dict[str, Dict[str, Any]] = {}
    if fresh_subset_path.is_file():
        doc = json.loads(fresh_subset_path.read_text(encoding="utf-8"))
        for item in doc.get("tokens") or []:
            if isinstance(item, str) and item.lower().startswith("0x"):
                fresh_meta[item.lower()] = {"source": "fresh_delta_lane"}
            elif isinstance(item, dict):
                addr = str(item.get("token") or item.get("address") or "").lower()
                if addr.startswith("0x"):
                    fresh_meta[addr] = {
                        "source": str(item.get("source") or "fresh_delta_lane"),
                        "priority_score": item.get("priority_score"),
                        "first_seen_block": item.get("first_seen_block"),
                    }

    watchlist = load_watchlist(watchlist_path)
    pending = build_pending_queue_payload(watchlist)
    cap = max(1, int(max_tokens))
    pending_cap = max(1, cap // 2)
    fresh_cap = cap - pending_cap
    merged: List[Dict[str, Any]] = []
    seen: set[str] = set()
    pending_merged = 0
    fresh_merged = 0

    for row in pending.get("tokens") or []:
        if pending_merged >= pending_cap:
            break
        addr = str(row.get("token") or "").lower()
        if not addr.startswith("0x") or addr in seen:
            continue
        merged.append(
            {
                "token": addr,
                "source": "pending_queue",
                "token_class": row.get("token_class"),
                "refresh_lane": row.get("refresh_lane") or "time_to_mirror_hot",
                "priority_score": row.get("priority_score"),
                "first_seen_block": row.get("first_seen_block"),
                "transitions_1_to_2": row.get("transitions_1_to_2"),
            }
        )
        seen.add(addr)
        pending_merged += 1

    for addr, meta in fresh_meta.items():
        if fresh_merged >= fresh_cap or len(merged) >= cap:
            break
        if addr in seen:
            continue
        wl_entry = (watchlist.get("tokens") or {}).get(addr) or {}
        merged.append(
            {
                "token": addr,
                "source": meta.get("source") or "fresh_delta_lane",
                "token_class": wl_entry.get("token_class"),
                "refresh_lane": wl_entry.get("refresh_lane") or "fresh_delta_lane",
                "priority_score": meta.get("priority_score"),
                "first_seen_block": meta.get("first_seen_block"),
            }
        )
        seen.add(addr)
        fresh_merged += 1

    if not merged:
        return 2
    subset_distribution = {
        "cap": cap,
        "pending_quota": pending_cap,
        "fresh_quota": fresh_cap,
        "pending_merged_count": pending_merged,
        "fresh_merged_count": fresh_merged,
        "fresh_delta_pool_count": len(fresh_meta),
    }
    write_token_subset_file(
        merged,
        output_path,
        source="fresh_delta_union_pending",
        lane_meta=subset_distribution,
    )
    print(
        f"time_to_mirror_expand_subset: {len(merged)} tokens "
        f"(pending={pending_merged}/{pending_cap} fresh={fresh_merged}/{fresh_cap}) -> {output_path}",
        flush=True,
    )
    return 0


def build_second_pool_transition_subset(
    *,
    watchlist_path: Path = DEFAULT_WATCHLIST_PATH,
    output_path: Path = SECOND_POOL_TRANSITION_SUBSET_PATH,
) -> int:
    """Tokens with confirmed venue-count 1→2 transition for mirror verify."""
    from m8.discovery.token_subset import write_token_subset_file

    watchlist = load_watchlist(watchlist_path)
    rows: List[Dict[str, Any]] = []
    for addr, entry in (watchlist.get("tokens") or {}).items():
        if not isinstance(entry, dict):
            continue
        transitions = int(entry.get("transitions_1_to_2") or 0)
        if transitions < 1:
            continue
        if entry.get("second_pool_verified"):
            continue
        rows.append(
            {
                "token": str(addr).lower(),
                "source": "transition_1_to_2",
                "transitions_1_to_2": transitions,
                "first_seen_block": (
                    entry.get("first_seen_block")
                    or entry.get("block_number")
                    or entry.get("first_block")
                ),
                "priority_score": score_pending_token(entry),
            }
        )
    rows.sort(key=lambda r: float(r.get("priority_score") or 0.0), reverse=True)
    lane_meta: Dict[str, Any] = {}
    if not rows:
        lane_meta["market_state"] = "MARKET_NO_1_TO_2_TRANSITION"
    write_token_subset_file(
        rows,
        output_path,
        source="second_pool_transition_1_to_2",
        lane_meta=lane_meta or None,
    )
    state_note = (
        f" market_state={lane_meta['market_state']}" if lane_meta else ""
    )
    print(
        f"second_pool_transition_subset: {len(rows)} tokens{state_note} -> {output_path}",
        flush=True,
    )
    return 0


def load_watchlist(path: Path = DEFAULT_WATCHLIST_PATH) -> Dict[str, Any]:
    if not path.is_file():
        return {"tokens": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def score_pending_token(entry: Dict[str, Any], *, now_ts: Optional[float] = None) -> float:
    """Higher = sooner mirror follow-up. Diagnostic-only scoring, not profit."""
    now = float(now_ts if now_ts is not None else time.time())
    score = 0.0
    first_seen = entry.get("first_seen_ts")
    if first_seen is not None:
        try:
            age_h = max(0.0, (now - float(first_seen)) / 3600.0)
            score += max(0.0, 48.0 - age_h) * 2.0
        except (TypeError, ValueError):
            pass
    if str(entry.get("refresh_lane") or "") == "fresh_delta_lane":
        score += 20.0
    if str(entry.get("token_class") or "") == "fresh_long_tail":
        score += 15.0
    try:
        transitions = int(entry.get("transitions_1_to_2") or 0)
        score += min(10.0, transitions * 5.0)
    except (TypeError, ValueError):
        pass
    if entry.get("second_pool_hint") or entry.get("second_pool_verified"):
        score += 25.0
    if str(entry.get("first_dex") or "").startswith("uniswap_v4"):
        score -= 5.0
    liq = entry.get("approx_liquidity_usd") or entry.get("liquidity_usd")
    if liq is not None:
        try:
            score += min(15.0, float(liq) / 10_000.0)
        except (TypeError, ValueError):
            pass
    return round(score, 2)


def build_pending_queue_payload(
    watchlist: Dict[str, Any],
    *,
    now_ts: Optional[float] = None,
) -> Dict[str, Any]:
    now = float(now_ts if now_ts is not None else time.time())
    pending: List[Dict[str, Any]] = []
    for addr, entry in (watchlist.get("tokens") or {}).items():
        if not isinstance(entry, dict):
            continue
        second_verified = bool(entry.get("second_pool_verified"))
        has_first = bool(entry.get("first_pool") or entry.get("first_dex"))
        if not has_first or second_verified:
            continue
        row = {
            "token": str(addr).lower(),
            "token_class": entry.get("token_class"),
            "first_dex": entry.get("first_dex"),
            "refresh_lane": entry.get("refresh_lane"),
            "transitions_1_to_2": entry.get("transitions_1_to_2"),
            "first_seen_ts": entry.get("first_seen_ts"),
            "first_seen_block": (
                entry.get("first_seen_block")
                or entry.get("block_number")
                or entry.get("first_block")
            ),
            "second_pool_hint": entry.get("second_pool_hint"),
            "priority_score": score_pending_token(entry, now_ts=now),
        }
        pending.append(row)
    pending.sort(key=lambda r: float(r.get("priority_score") or 0.0), reverse=True)
    return {
        "schema_version": "m8_time_to_mirror_pending_queue_v2",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "pending_count": len(pending),
        "tokens": pending,
    }


def build_time_to_mirror_sla(
    *,
    watchlist_path: Path = DEFAULT_WATCHLIST_PATH,
    expansion_path: Path = DEFAULT_EXPANSION_PATH,
    pending_path: Path = DEFAULT_PENDING_QUEUE_PATH,
    mirror_checkpoint_path: Path = DEFAULT_MIRROR_CHECKPOINT_PATH,
    mirror_reprobe_checkpoint_path: Optional[Path] = None,
    mirror_verify_checkpoint_path: Optional[Path] = None,
) -> Dict[str, Any]:
    watchlist = load_watchlist(watchlist_path)
    expansion: Dict[str, Any] = {}
    if expansion_path.is_file():
        expansion = json.loads(expansion_path.read_text(encoding="utf-8"))
    pending: Dict[str, Any] = {}
    if pending_path.is_file():
        pending = json.loads(pending_path.read_text(encoding="utf-8"))

    reprobe_path = mirror_reprobe_checkpoint_path or mirror_checkpoint_path
    verify_path = mirror_verify_checkpoint_path or Path(
        "data/tmp/m8_second_pool_verify_progress.json"
    )

    def _load_ckpt(path: Path) -> Dict[str, Any]:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
        return {}

    reprobe_ckpt = _load_ckpt(reprobe_path)
    verify_ckpt = _load_ckpt(verify_path)

    def _ckpt_summary(ckpt: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "processed_routes": ckpt.get("processed_routes"),
            "quote_ok": ckpt.get("quote_ok"),
            "quote_fail": ckpt.get("quote_fail"),
            "last_rpc_error": ckpt.get("last_rpc_error"),
            "exit_code": ckpt.get("exit_code"),
            "exit_class": ckpt.get("exit_class"),
            "updated_at": ckpt.get("updated_at"),
        }

    summary = expansion.get("summary") or {}
    quote_ready_global = int(summary.get("mirror_quote_ready_tokens") or 0)
    verified_second = int(summary.get("verified_second_pool_count") or 0)
    routes = list(expansion.get("routes_admitted") or [])
    mirror_by_token = mirror_readiness_by_focus(routes) if routes else {}

    rows: List[Dict[str, Any]] = []
    now = time.time()
    for addr, entry in (watchlist.get("tokens") or {}).items():
        if not isinstance(entry, dict):
            continue
        first_ts = entry.get("first_seen_ts")
        second_verified = bool(entry.get("second_pool_verified"))
        token_lc = str(addr).lower()
        mr = mirror_by_token.get(token_lc) or {}
        token_quote_ready = bool(mr.get("mirror_quote_ready"))
        rows.append(
            {
                "token": token_lc,
                "token_class": entry.get("token_class"),
                "first_seen_time": first_ts,
                "first_seen_dex": entry.get("first_dex"),
                "second_pool_seen_time": entry.get("second_pool_seen_ts"),
                "delta_minutes": (
                    round((now - float(first_ts)) / 60.0, 2)
                    if first_ts is not None
                    else None
                ),
                "verified_second_pool": second_verified,
                "quote_ready": token_quote_ready,
                "quoteable_legs": mr.get("quoteable_legs"),
                "m9_handoff": token_quote_ready and second_verified,
                "priority_score": score_pending_token(entry, now_ts=now),
            }
        )
    rows.sort(key=lambda r: float(r.get("priority_score") or 0.0), reverse=True)
    per_token_quote_ready = sum(1 for r in rows if r.get("quote_ready"))
    expand_subset_distribution: Dict[str, Any] = {}
    if TIME_TO_MIRROR_EXPAND_SUBSET_PATH.is_file():
        try:
            subset_doc = json.loads(
                TIME_TO_MIRROR_EXPAND_SUBSET_PATH.read_text(encoding="utf-8")
            )
            expand_subset_distribution = dict(subset_doc.get("lane_meta") or {})
        except (OSError, json.JSONDecodeError):
            pass
    return {
        "schema_version": "m8_time_to_mirror_sla_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "mirror_quote_ready_tokens": per_token_quote_ready or quote_ready_global,
        "mirror_quote_ready_tokens_global": quote_ready_global,
        "verified_second_pool_count": verified_second,
        "pending_count": int(pending.get("pending_count") or 0),
        "expand_subset_distribution": expand_subset_distribution,
        "mirror_reprobe_exit": reprobe_ckpt.get("exit_code"),
        "mirror_verify_exit": verify_ckpt.get("exit_code"),
        "mirror_reprobe_checkpoint": _ckpt_summary(reprobe_ckpt),
        "mirror_verify_checkpoint": _ckpt_summary(verify_ckpt),
        "mirror_checkpoint": _ckpt_summary(verify_ckpt or reprobe_ckpt),
        "tokens": rows[:200],
    }


def build_narrow_m9_bridge_inventory(
    *,
    expansion_path: Path = DEFAULT_EXPANSION_PATH,
    output_path: Path = DEFAULT_NARROW_BRIDGE_PATH,
) -> tuple[Dict[str, Any], int]:
    """Subset bridge: verified same-pair quoteable legs per mirror-ready token."""
    from m8.discovery.cross_dex_expand import _same_pair_route_quoteable
    from m8.discovery.mirror_quote_smoke import is_same_pair_mirror_route

    if not expansion_path.is_file():
        return {"error": "missing_expansion"}, 1
    doc = json.loads(expansion_path.read_text(encoding="utf-8"))
    routes = list(doc.get("routes_admitted") or [])
    mirror_by_token = mirror_readiness_by_focus(routes)

    active_routes: List[Dict[str, Any]] = []
    anchor_closure_count = 0
    for route in routes:
        focus = str(
            route.get("focus_token_address") or route.get("exotic_address") or ""
        ).lower()
        if not focus.startswith("0x"):
            continue
        if not (mirror_by_token.get(focus) or {}).get("mirror_quote_ready"):
            continue
        if is_same_pair_mirror_route(route) and _same_pair_route_quoteable(route):
            tagged = dict(route)
            tagged["include_reason"] = "quote_ready_same_pair_leg"
            active_routes.append(tagged)
        elif str(route.get("include_reason") or "") == "anchor_closure":
            tagged = dict(route)
            tagged["include_reason"] = "anchor_closure"
            active_routes.append(tagged)
            anchor_closure_count += 1

    quote_ready_tokens = {
        str(r.get("focus_token_address") or r.get("exotic_address") or "").lower()
        for r in active_routes
        if str(r.get("include_reason") or "") == "quote_ready_same_pair_leg"
    }
    quote_ready_tokens.discard("")

    if not active_routes:
        payload = {
            "schema_version": "m9_bridge_time_to_mirror_narrow_v2",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "active_routes": [],
            "quote_ready_token_count": 0,
            "anchor_closure_route_count": 0,
            "handoff_ready": False,
        }
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload, 2

    payload = {
        "schema_version": "m9_bridge_time_to_mirror_narrow_v2",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_expansion": str(expansion_path),
        "active_routes": active_routes,
        "quote_ready_token_count": len(quote_ready_tokens),
        "anchor_closure_route_count": anchor_closure_count,
        "handoff_ready": True,
        "profit_claim_allowed": False,
        "lane": "time_to_mirror_narrow",
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload, 0
