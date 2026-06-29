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
DEFAULT_MIRROR_YIELD_FUNNEL_PATH = Path("data/tmp/m8_mirror_yield_funnel_latest.json")
DEFAULT_VERIFY_BUDGET_PATH = Path("data/tmp/m8_verify_budget_latest.json")
DEFAULT_MIRROR_CHECKPOINT_PATH = Path("data/tmp/m8_mirror_quote_smoke_progress.json")
DEFAULT_EXTERNAL_HINTS_PATH = Path("data/runs/_rolling/m8_external_pool_hints_latest.json")
FRESH_DELTA_SUBSET_PATH = Path("data/tmp/m8_fresh_delta_token_subset.json")
TIME_TO_MIRROR_EXPAND_SUBSET_PATH = Path("data/tmp/m8_time_to_mirror_expand_subset.json")
SECOND_POOL_TRANSITION_SUBSET_PATH = Path("data/tmp/m8_second_pool_transition_subset.json")
TRANSITION_VERIFY_MAX_TOKENS = 50
TOPOLOGY_FALLBACK_MAX_TOKENS = 50


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
    expansion_path: Path = DEFAULT_EXPANSION_PATH,
    hints_path: Path = DEFAULT_EXTERNAL_HINTS_PATH,
    output_path: Path = SECOND_POOL_TRANSITION_SUBSET_PATH,
    max_tokens: int = TRANSITION_VERIFY_MAX_TOKENS,
) -> int:
    """Tokens with confirmed 1→2 transition, or topology fallback for quote reprobe."""
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
    fallback_used = False
    if not rows:
        fallback_rows = _build_same_pair_topology_fallback_subset(
            watchlist=watchlist,
            expansion_path=expansion_path,
            hints_path=hints_path,
            max_tokens=TOPOLOGY_FALLBACK_MAX_TOKENS,
        )
        if fallback_rows:
            rows = fallback_rows
            fallback_used = True
            lane_meta["fallback"] = "same_pair_mirror_topology"
            lane_meta["market_state"] = "MARKET_NO_1_TO_2_TRANSITION"
        else:
            lane_meta["market_state"] = "MARKET_NO_1_TO_2_TRANSITION"
    if max_tokens > 0:
        rows = rows[: int(max_tokens)]
    if fallback_used:
        lane_meta["topology_fallback_count"] = len(rows)
    write_token_subset_file(
        rows,
        output_path,
        source="second_pool_transition_1_to_2",
        lane_meta=lane_meta or None,
    )
    state_note = (
        f" market_state={lane_meta['market_state']}" if lane_meta.get("market_state") else ""
    )
    fallback_note = " fallback=topology" if fallback_used else ""
    print(
        f"second_pool_transition_subset: {len(rows)} tokens{state_note}{fallback_note} -> {output_path}",
        flush=True,
    )
    return 0


def _build_same_pair_topology_fallback_subset(
    *,
    watchlist: Dict[str, Any],
    expansion_path: Path,
    hints_path: Path,
    max_tokens: int,
) -> List[Dict[str, Any]]:
    """Top-N same-pair mirror topology tokens when no 1→2 transitions observed."""
    if not expansion_path.is_file():
        return []
    from m8.discovery.mirror_candidate_score import score_mirror_verify_candidate
    from m8.discovery.pool_hints import PoolHint

    doc = json.loads(expansion_path.read_text(encoding="utf-8"))
    routes = list(doc.get("routes_admitted") or [])
    mirror_by = mirror_readiness_by_focus(routes)
    hints_by_token: Dict[str, List[Any]] = {}
    if hints_path.is_file():
        try:
            hints_doc = json.loads(hints_path.read_text(encoding="utf-8"))
            for raw in hints_doc.get("candidates") or hints_doc.get("hints") or []:
                if not isinstance(raw, dict):
                    continue
                hint = PoolHint.from_dict(raw)
                tok = str(hint.focus_token or hint.token0_addr or "").lower()
                if tok.startswith("0x"):
                    hints_by_token.setdefault(tok, []).append(hint)
        except (OSError, json.JSONDecodeError):
            pass

    wl_tokens = watchlist.get("tokens") or {}
    ranked: List[Dict[str, Any]] = []
    for focus, mr in mirror_by.items():
        if not focus.startswith("0x"):
            continue
        if mr.get("mirror_quote_ready"):
            continue
        if not (
            mr.get("mirror_topology_ready")
            or int(mr.get("same_pair_dexes") or 0) >= 2
            or int(mr.get("quoteable_legs") or 0) >= 1
        ):
            continue
        wl_entry = wl_tokens.get(focus) or wl_tokens.get(focus.lower()) or {}
        hint_rows = hints_by_token.get(focus) or []
        score, reasons = score_mirror_verify_candidate(
            focus, hint_rows, watchlist_entry=wl_entry if isinstance(wl_entry, dict) else None
        )
        if mr.get("mirror_topology_ready"):
            score += 25.0
            reasons.append("same_pair_mirror_topology")
        ranked.append(
            {
                "token": focus,
                "source": "same_pair_mirror_topology_fallback",
                "priority_score": round(score, 2),
                "score_reasons": reasons,
                "transitions_1_to_2": int(wl_entry.get("transitions_1_to_2") or 0),
                "first_seen_block": (
                    wl_entry.get("first_seen_block")
                    or wl_entry.get("block_number")
                    or wl_entry.get("first_block")
                ),
            }
        )
    ranked.sort(key=lambda r: float(r.get("priority_score") or 0.0), reverse=True)
    return ranked[: max(1, int(max_tokens))]


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


def _classify_pending_queue_state(entry: Dict[str, Any]) -> str:
    """Bucket token into pending-queue lane (step 6)."""
    if entry.get("mirror_quote_ready") or entry.get("quote_smoke_ok"):
        return "quote_ready"
    if entry.get("second_pool_verified") or entry.get("second_pool_hint"):
        return "second_venue_seen"
    from m8.discovery.launchpad_classifier import classify_launchpad

    launchpad = classify_launchpad(
        str(entry.get("token") or ""),
        entry=entry,
    )
    if launchpad.get("launchpad") not in ("unknown", "generic_launchpad") and launchpad.get(
        "single_venue_common"
    ):
        return "patient_candidate"
    has_first = bool(entry.get("first_pool") or entry.get("first_dex"))
    if has_first and not entry.get("second_pool_verified"):
        return "single_venue_watch"
    return "single_venue_watch"


def build_pending_queue_payload(
    watchlist: Dict[str, Any],
    *,
    now_ts: Optional[float] = None,
) -> Dict[str, Any]:
    now = float(now_ts if now_ts is not None else time.time())
    buckets: Dict[str, List[Dict[str, Any]]] = {
        "single_venue_watch": [],
        "second_venue_seen": [],
        "quote_ready": [],
        "patient_candidate": [],
    }
    pending: List[Dict[str, Any]] = []
    for addr, entry in (watchlist.get("tokens") or {}).items():
        if not isinstance(entry, dict):
            continue
        second_verified = bool(entry.get("second_pool_verified"))
        has_first = bool(entry.get("first_pool") or entry.get("first_dex"))
        if not has_first:
            continue
        if second_verified and entry.get("mirror_quote_ready"):
            state = "quote_ready"
        elif second_verified or entry.get("second_pool_hint"):
            state = "second_venue_seen"
        else:
            state = _classify_pending_queue_state({**entry, "token": addr})
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
            "queue_state": state,
            "priority_score": score_pending_token(entry, now_ts=now),
        }
        buckets[state].append(row)
        if state != "quote_ready":
            pending.append(row)
    for key in buckets:
        buckets[key].sort(key=lambda r: float(r.get("priority_score") or 0.0), reverse=True)
    pending.sort(key=lambda r: float(r.get("priority_score") or 0.0), reverse=True)
    return {
        "schema_version": "m8_time_to_mirror_pending_queue_v3",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "pending_count": len(pending),
        "queues": {
            k: {"count": len(v), "tokens": v} for k, v in buckets.items()
        },
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
    routes = list(expansion.get("routes_admitted") or [])
    mirror_by_token = mirror_readiness_by_focus(routes) if routes else {}

    from m8.discovery.onchain_factory_mirror_discovery import load_onchain_scan_funnel_fields

    onchain_scan = load_onchain_scan_funnel_fields()
    first_pool_found = int(onchain_scan.get("first_pool_found") or 0)
    second_venue_found = int(onchain_scan.get("second_venue_found") or 0)
    verified_pool_count = int(onchain_scan.get("verified_pool_count") or 0)
    if onchain_scan:
        verified_second = second_venue_found
    else:
        verified_second = int(summary.get("verified_second_pool_count") or 0)

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

    mirror_funnel: Dict[str, Any] = {
        "pending_count": int(pending.get("pending_count") or 0),
        "expansion_tokens_in": int(summary.get("tokens_in") or 0),
        "mirror_quote_ready_tokens": quote_ready_global,
        "fresh_long_tail_quote_ready_tokens": int(
            summary.get("fresh_long_tail_quote_ready_tokens") or 0
        ),
        "first_pool_found": first_pool_found,
        "second_venue_found": second_venue_found,
        "verified_pool_count": verified_pool_count,
    }
    hints_path = DEFAULT_EXTERNAL_HINTS_PATH
    verify_budget_path = DEFAULT_VERIFY_BUDGET_PATH
    if verify_budget_path.is_file():
        try:
            budget_doc = json.loads(verify_budget_path.read_text(encoding="utf-8"))
            for key in (
                "radar_seen",
                "scored_candidates",
                "verify_subset_size",
                "verify_subset_cap",
                "onchain_verified",
                "dropped_to_warm_count",
            ):
                if budget_doc.get(key) is not None:
                    mirror_funnel[key] = budget_doc.get(key)
        except (OSError, json.JSONDecodeError):
            pass
    if hints_path.is_file():
        try:
            hints_doc = json.loads(hints_path.read_text(encoding="utf-8"))
            hint_metrics = hints_doc.get("metrics") or {}
            mirror_funnel["scored_verify_subset_size"] = int(
                hint_metrics.get("verify_subset_size") or 0
            )
            mirror_funnel["radar_candidates"] = int(
                hint_metrics.get("radar_candidates") or 0
            )
            for key in (
                "radar_seen",
                "scored_candidates",
                "verify_subset_size",
                "onchain_verified",
                "dropped_to_warm_count",
            ):
                if hint_metrics.get(key) is not None:
                    mirror_funnel[key] = int(hint_metrics.get(key) or 0)
        except (OSError, json.JSONDecodeError):
            pass
    narrow_path = DEFAULT_NARROW_BRIDGE_PATH
    if narrow_path.is_file():
        try:
            narrow_doc = json.loads(narrow_path.read_text(encoding="utf-8"))
            mirror_funnel["narrow_active_routes"] = len(narrow_doc.get("active_routes") or [])
            mirror_funnel["narrow_quote_ready_token_count"] = int(
                narrow_doc.get("quote_ready_token_count") or 0
            )
            mirror_funnel["fresh_long_tail_quote_ready_tokens_narrow"] = int(
                narrow_doc.get("fresh_long_tail_quote_ready_tokens") or 0
            )
        except (OSError, json.JSONDecodeError):
            pass
    cap_path = Path("data/tmp/m9_time_to_mirror_narrow_capacity_diagnostic_latest.json")
    if cap_path.is_file():
        try:
            cap_doc = json.loads(cap_path.read_text(encoding="utf-8"))
            mirror_funnel["cycles_total"] = int(cap_doc.get("cycles_total") or 0)
            mirror_funnel["cycles_at_floor"] = int(
                (cap_doc.get("cycles_by_profile") or {})
                .get("diagnostic_near_econ", {})
                .get("cycles_at_floor")
                or 0
            )
        except (OSError, json.JSONDecodeError):
            pass
    timings_path = Path("data/tmp/m8_time_to_mirror_step_timings_latest.json")
    if timings_path.is_file():
        try:
            mirror_funnel["latency"] = json.loads(
                timings_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            pass

    return {
        "schema_version": "m8_time_to_mirror_sla_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "mirror_quote_ready_tokens": per_token_quote_ready or quote_ready_global,
        "mirror_quote_ready_tokens_global": quote_ready_global,
        "first_pool_found": first_pool_found,
        "second_venue_found": second_venue_found,
        "verified_pool_count": verified_pool_count,
        "verified_second_pool_count": verified_second,
        "pending_count": int(pending.get("pending_count") or 0),
        "expand_subset_distribution": expand_subset_distribution,
        "mirror_yield_funnel": mirror_funnel,
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
    from m8.discovery.token_classify import TOKEN_CLASS_FRESH
    from m9.graph_arb.narrow_universe_gate import (
        is_target_narrow_route,
        route_has_eligible_mirror_discovery,
        summarize_narrow_bridge_provenance,
        target_narrow_universe_gate_blocked,
    )

    if not expansion_path.is_file():
        return {"error": "missing_expansion"}, 1
    doc = json.loads(expansion_path.read_text(encoding="utf-8"))
    routes = list(doc.get("routes_admitted") or [])
    summary = doc.get("summary") or {}
    mirror_by_token = mirror_readiness_by_focus(routes)

    active_routes: List[Dict[str, Any]] = []
    excluded_known_major_count = 0
    excluded_dexscreener_only_count = 0
    fresh_long_tail_quote_ready_tokens: set[str] = set()
    for route in routes:
        focus = str(
            route.get("focus_token_address") or route.get("exotic_address") or ""
        ).lower()
        if not focus.startswith("0x"):
            continue
        if not (mirror_by_token.get(focus) or {}).get("mirror_quote_ready"):
            continue
        if not is_same_pair_mirror_route(route) or not _same_pair_route_quoteable(route):
            continue
        if not is_target_narrow_route(route):
            excluded_known_major_count += 1
            continue
        if not route_has_eligible_mirror_discovery(route):
            excluded_dexscreener_only_count += 1
            continue
        tagged = dict(route)
        tagged["include_reason"] = "quote_ready_same_pair_leg"
        active_routes.append(tagged)
        if str(route.get("token_class") or "") in (TOKEN_CLASS_FRESH, "fresh_long_tail"):
            fresh_long_tail_quote_ready_tokens.add(focus)

    quote_ready_tokens = {
        str(r.get("focus_token_address") or r.get("exotic_address") or "").lower()
        for r in active_routes
        if str(r.get("include_reason") or "") == "quote_ready_same_pair_leg"
    }
    quote_ready_tokens.discard("")

    blocked, blocker_reason = target_narrow_universe_gate_blocked(
        {
            "active_routes": active_routes,
            "fresh_long_tail_quote_ready_tokens": len(fresh_long_tail_quote_ready_tokens),
        }
    )

    if not active_routes:
        payload = {
            "schema_version": "m9_bridge_time_to_mirror_narrow_v2",
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "active_routes": [],
            "quote_ready_token_count": 0,
            "fresh_long_tail_quote_ready_tokens": 0,
            "excluded_known_major_route_count": excluded_known_major_count,
            "excluded_dexscreener_only_route_count": excluded_dexscreener_only_count,
            "handoff_ready": False,
            "target_universe_gate_blocked": True,
            "target_universe_blocker_reason": blocker_reason or "EMPTY_NARROW_BRIDGE",
            "active_routes_by_token_class": {},
            "active_routes_by_refresh_lane": {},
        }
        payload.update(summarize_narrow_bridge_provenance(payload))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload, 2

    payload = {
        "schema_version": "m9_bridge_time_to_mirror_narrow_v2",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_expansion": str(expansion_path),
        "active_routes": active_routes,
        "quote_ready_token_count": len(quote_ready_tokens),
        "fresh_long_tail_quote_ready_tokens": len(fresh_long_tail_quote_ready_tokens),
        "excluded_known_major_route_count": excluded_known_major_count,
        "excluded_dexscreener_only_route_count": excluded_dexscreener_only_count,
        "handoff_ready": not blocked,
        "target_universe_gate_blocked": blocked,
        "target_universe_blocker_reason": blocker_reason if blocked else None,
        "profit_claim_allowed": False,
        "lane": "time_to_mirror_narrow",
        "mirror_yield_funnel": {
            "expansion_tokens_in": int(summary.get("tokens_in") or 0),
            "mirror_quote_ready_tokens": int(summary.get("mirror_quote_ready_tokens") or 0),
            "fresh_long_tail_quote_ready_tokens_expansion": int(
                summary.get("fresh_long_tail_quote_ready_tokens") or 0
            ),
            "narrow_active_routes": len(active_routes),
            "narrow_quote_ready_token_count": len(quote_ready_tokens),
        },
    }
    payload.update(summarize_narrow_bridge_provenance(payload))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload, 0 if not blocked else 2


def classify_quote_reject_reason(
    *,
    quote_smoke_status: Optional[str] = None,
    quote_fail_reason: Optional[str] = None,
    dex_id: Optional[str] = None,
    route: Optional[Dict[str, Any]] = None,
) -> str:
    """Bucket why verified-second-pool did not become quote-ready."""
    route = route or {}
    blob = " ".join(
        str(x or "")
        for x in (
            quote_smoke_status,
            quote_fail_reason,
            dex_id,
            route.get("quote_smoke_status"),
            route.get("quote_fail_reason"),
            route.get("reject_reason"),
            route.get("mirror_smoke_reason"),
        )
    ).upper()
    if "TOKEN_MISMATCH" in blob or "FOCUS_MISMATCH" in blob:
        return "TOKEN_MISMATCH"
    if "POOL_NOT_FOUND" in blob or "POOL_MISSING" in blob:
        return "POOL_NOT_FOUND"
    if "REVERT" in blob or "QUOTE_FAIL" in blob or "_QUOTE_REVERT" in blob:
        return "QUOTE_REVERT"
    if "NO_LIQUIDITY" in blob or "ZERO_LIQUIDITY" in blob or "NO_LIQ" in blob:
        return "ZERO_LIQUIDITY"
    if "NO_QUOTER" in blob or "QUOTER" in blob and "MISSING" in blob:
        return "NO_QUOTER"
    if "UNSUPPORTED" in blob or "UNKNOWN_DEX" in blob:
        return "UNSUPPORTED_DEX"
    if "ADAPTER" in blob:
        return "ADAPTER_MISSING"
    if "STALE" in blob:
        return "HINT_STALE"
    if "DEPTH" in blob or "THIN" in blob or "IMPACT" in blob:
        return "DEPTH_TOO_THIN"
    return "OTHER"


def classify_quote_reject_from_routes(routes: List[Dict[str, Any]]) -> str:
    """Pick the most specific reject bucket across all routes for one focus token."""
    if not routes:
        return "OTHER"
    priority = (
        "TOKEN_MISMATCH",
        "POOL_NOT_FOUND",
        "QUOTE_REVERT",
        "ZERO_LIQUIDITY",
        "NO_QUOTER",
        "UNSUPPORTED_DEX",
        "ADAPTER_MISSING",
        "HINT_STALE",
        "DEPTH_TOO_THIN",
        "OTHER",
    )
    buckets = {
        classify_quote_reject_reason(
            quote_smoke_status=r.get("quote_smoke_status"),
            quote_fail_reason=r.get("quote_fail_reason"),
            dex_id=r.get("dex_id"),
            route=r,
        )
        for r in routes
    }
    for bucket in priority:
        if bucket in buckets:
            return bucket
    return "OTHER"


def build_quote_reject_histogram(
    *,
    watchlist_path: Path = DEFAULT_WATCHLIST_PATH,
    expansion_path: Path = DEFAULT_EXPANSION_PATH,
) -> Dict[str, int]:
    """Histogram for second_pool_verified=True but mirror quote not ready."""
    watchlist = load_watchlist(watchlist_path)
    routes: List[Dict[str, Any]] = []
    if expansion_path.is_file():
        routes = list(
            json.loads(expansion_path.read_text(encoding="utf-8")).get("routes_admitted") or []
        )
    mirror_by = mirror_readiness_by_focus(routes)
    hist: Dict[str, int] = {}
    routes_by_focus: Dict[str, List[Dict[str, Any]]] = {}
    for route in routes:
        focus = str(
            route.get("focus_token_address") or route.get("exotic_address") or ""
        ).lower()
        if focus.startswith("0x"):
            routes_by_focus.setdefault(focus, []).append(route)

    for addr, entry in (watchlist.get("tokens") or {}).items():
        if not isinstance(entry, dict) or not entry.get("second_pool_verified"):
            continue
        focus = str(addr).lower()
        if (mirror_by.get(focus) or {}).get("mirror_quote_ready"):
            continue
        token_routes = routes_by_focus.get(focus) or []
        bucket = classify_quote_reject_from_routes(token_routes)
        if bucket == "OTHER" and not token_routes:
            bucket = "POOL_NOT_FOUND"
        hist[bucket] = int(hist.get(bucket, 0)) + 1
    return dict(sorted(hist.items(), key=lambda kv: (-kv[1], kv[0])))


def build_mirror_yield_funnel_artifact(
    *,
    pending_path: Path = DEFAULT_PENDING_QUEUE_PATH,
    verify_budget_path: Path = DEFAULT_VERIFY_BUDGET_PATH,
    narrow_path: Path = DEFAULT_NARROW_BRIDGE_PATH,
    capacity_path: Path = Path(
        "data/tmp/m9_time_to_mirror_narrow_capacity_diagnostic_latest.json"
    ),
    output_path: Path = DEFAULT_MIRROR_YIELD_FUNNEL_PATH,
) -> Dict[str, Any]:
    """Single funnel artifact: pending → verify → mirror → narrow → cycles."""
    pending: Dict[str, Any] = {}
    if pending_path.is_file():
        pending = json.loads(pending_path.read_text(encoding="utf-8"))
    verify_budget: Dict[str, Any] = {}
    if verify_budget_path.is_file():
        verify_budget = json.loads(verify_budget_path.read_text(encoding="utf-8"))
    from m8.discovery.onchain_factory_mirror_discovery import load_onchain_scan_funnel_fields

    onchain_scan = load_onchain_scan_funnel_fields()
    onchain_factory_verified = int(
        onchain_scan.get("onchain_factory_verified")
        or (onchain_scan.get("verified_second_pool_by_source") or {}).get("onchain_factory")
        or 0
    )
    dex_onchain_verified = int(verify_budget.get("onchain_verified") or 0)
    combined_onchain_verified = max(dex_onchain_verified, onchain_factory_verified)
    narrow: Dict[str, Any] = {}
    if narrow_path.is_file():
        narrow = json.loads(narrow_path.read_text(encoding="utf-8"))
    capacity: Dict[str, Any] = {}
    if capacity_path.is_file():
        capacity = json.loads(capacity_path.read_text(encoding="utf-8"))

    pending_tokens = list(pending.get("tokens") or [])
    fresh_pending = sum(
        1 for t in pending_tokens if str(t.get("token_class") or "") == "fresh_long_tail"
    )
    cycles_at_floor = int(
        (capacity.get("cycles_by_profile") or {})
        .get("diagnostic_near_econ", {})
        .get("cycles_at_floor")
        or 0
    )
    verify_cap = int(verify_budget.get("verify_subset_cap") or 0)
    if verify_cap <= 0:
        verify_cap = int(verify_budget.get("verify_subset_size") or 0)
    payload = {
        "schema_version": "m8_mirror_yield_funnel_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "fresh_long_tail_pending": fresh_pending,
        "pending_count": int(pending.get("pending_count") or len(pending_tokens)),
        "scored_candidates": int(verify_budget.get("scored_candidates") or 0),
        "verify_subset_size": int(verify_budget.get("verify_subset_size") or 0),
        "verify_subset_cap": verify_cap,
        "onchain_verified": combined_onchain_verified,
        "onchain_factory_verified": onchain_factory_verified,
        "first_pool_found": int(
            onchain_scan.get("first_pool_found")
            or verify_budget.get("first_pool_found")
            or 0
        ),
        "second_venue_found": int(
            onchain_scan.get("second_venue_found")
            or verify_budget.get("second_venue_found")
            or 0
        ),
        "verified_pool_count": int(
            onchain_scan.get("verified_pool_count")
            or verify_budget.get("verified_pool_count")
            or combined_onchain_verified
        ),
        "onchain_factory_candidates": int(
            onchain_scan.get("onchain_factory_candidates")
            or verify_budget.get("onchain_factory_candidates")
            or 0
        ),
        "verified_second_pool_count": int(
            onchain_scan.get("second_venue_found")
            or onchain_scan.get("verified_second_pool_count")
            or verify_budget.get("second_venue_found")
            or verify_budget.get("verified_second_pool_count")
            or 0
        ),
        "verified_pools_from_onchain_scan": list(onchain_scan.get("verified_pools") or []),
        "dropped_to_warm_count": int(verify_budget.get("dropped_to_warm_count") or 0),
        "top_candidates_count": len(verify_budget.get("top_candidates") or []),
        "disposition_histogram": dict(verify_budget.get("disposition_histogram") or {}),
        "mirror_quote_ready_tokens_narrow": int(narrow.get("quote_ready_token_count") or 0),
        "fresh_long_tail_quote_ready_tokens": int(
            narrow.get("fresh_long_tail_quote_ready_tokens") or 0
        ),
        "narrow_routes": len(narrow.get("active_routes") or []),
        "cycles_at_floor": cycles_at_floor,
        "cycles_total": int(capacity.get("cycles_total") or 0),
        "target_universe_gate_blocked": bool(narrow.get("target_universe_gate_blocked")),
        "target_universe_blocker_reason": narrow.get("target_universe_blocker_reason"),
        "quote_reject_histogram": build_quote_reject_histogram(),
        "verify_budget_source": str(verify_budget_path),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def build_time_to_mirror_latency_artifact(
    *,
    step_timings_s: Dict[str, float],
    pipeline_latency_s: float,
    profile: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Summarize per-step latency for hot-path SLA gate."""
    prof = profile or {}
    radar_s = float(step_timings_s.get("m8_2_radar_two_phase") or 0.0)
    verify_s = 0.0  # verify is inside radar step
    expand_s = float(step_timings_s.get("m8_2_cross_dex_expand") or 0.0)
    mirror_reprobe_s = float(step_timings_s.get("m8_mirror_quote_reprobe") or 0.0)
    mirror_verify_s = float(step_timings_s.get("m8_second_pool_verify") or 0.0)
    m9_ready_s = sum(
        float(step_timings_s.get(k) or 0.0)
        for k in (
            "m9_time_to_mirror_narrow_inventory",
            "m9_time_to_mirror_depth_enrich",
            "m9_time_to_mirror_capacity_diagnostic",
        )
    )
    max_s = int(prof.get("hot_sla_max_s") or 0)
    return {
        "schema_version": "m8_time_to_mirror_latency_v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_kind": prof.get("run_kind", "fresh_run"),
        "hot_lane": prof.get("lane"),
        "time_to_mirror_latency_s": pipeline_latency_s,
        "radar_s": radar_s,
        "verify_s": verify_s,
        "expand_s": expand_s,
        "mirror_reprobe_s": mirror_reprobe_s,
        "mirror_verify_s": mirror_verify_s,
        "m9_ready_s": round(m9_ready_s, 2),
        "step_timings_s": step_timings_s,
        "hot_sla_max_s": max_s,
        "hot_sla_pass": (max_s <= 0 or pipeline_latency_s <= float(max_s)),
    }


def evaluate_hot_sla_gate(
    timings_doc: Dict[str, Any],
    *,
    max_latency_s: int,
) -> tuple[bool, str]:
    latency = float(timings_doc.get("time_to_mirror_latency_s") or 0.0)
    if latency <= 0:
        return False, "HOT_SLA_MISSING_LATENCY"
    if latency > float(max_latency_s):
        return False, f"HOT_SLA_EXCEEDED latency_s={latency} max_s={max_latency_s}"
    return True, "hot_sla_pass"
