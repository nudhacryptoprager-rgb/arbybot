"""Wide mirror discovery recall lane — maximize DexScreener mirrors before M9 narrowing."""
from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from m8.discovery.dexscreener_hints import DEXSCREENER_BATCH_MAX, fetch_token_hints_batch
from m8.discovery.mirror_recall_verify import (
    RECALL_STATUS_POOL_EXISTS,
    SELECTION_STATUS_FRESH,
    STALE_BUT_POOL_EXISTS,
    mirror_age_bucket,
    verify_hint_for_recall,
)
from m8.discovery.pool_hints import (
    BRIDGE_ELIGIBLE_HINT_STATUSES,
    HINT_DEX_UNSUPPORTED,
    HINT_ONLY,
    QUOTE_SMOKE_OK,
    PoolHint,
    build_artifact,
    dedupe_hints,
    write_hints_artifact,
)

DEFAULT_RECALL_ARTIFACT = Path("data/tmp/m8_mirror_discovery_recall_latest.json")
DEFAULT_VERIFY_RCA_PATH = Path("data/tmp/m8_mirror_recall_verify_rca_latest.json")
DEFAULT_SELECTION_ARTIFACT = Path("data/tmp/m8_mirror_selection_latest.json")
DEFAULT_EXPAND_SUBSET = Path("data/tmp/m8_time_to_mirror_expand_subset.json")
DEFAULT_CONFIG_PATH = Path("config/exotic_base_anchor.yaml")
DEFAULT_RECALL_HINTS_PATH = Path("data/tmp/m8_mirror_recall_hints_latest.json")
DEFAULT_SUPPORTED_HINTS_PATH = Path("data/runs/_rolling/m8_external_pool_hints_latest.json")
RECALL_CANDIDATES_PATH = Path("data/tmp/m8_mirror_recall_candidates_latest.json")
EXISTENCE_VERIFY_QUEUE_PATH = Path("data/tmp/m8_mirror_existence_verify_queue_latest.json")
QUOTE_READY_QUEUE_PATH = Path("data/tmp/m8_mirror_quote_ready_queue_latest.json")
EXISTENCE_VERIFY_SUBSET_PATH = Path("data/tmp/m8_existence_verify_subset.json")

SUPPORT_SUPPORTED = "supported"
SUPPORT_UNSUPPORTED = "unsupported"
SUPPORT_UNKNOWN_ALIAS = "unknown_alias"


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_yaml_config(path: Path) -> Dict[str, Any]:
    import yaml

    if not path.is_file():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _load_token_list(path: Path, *, max_tokens: int) -> List[str]:
    if not path.is_file():
        return []
    doc = json.loads(path.read_text(encoding="utf-8"))
    tokens: List[str] = []
    if isinstance(doc, list):
        tokens = [str(t).lower() for t in doc if str(t).startswith("0x")]
    else:
        for item in doc.get("tokens") or []:
            if isinstance(item, str) and item.startswith("0x"):
                tokens.append(item.lower())
            elif isinstance(item, dict):
                addr = str(item.get("token") or item.get("address") or "").lower()
                if addr.startswith("0x"):
                    tokens.append(addr)
    return tokens[: max(1, int(max_tokens))]


def _count_fresh_delta_lane_tokens(path: Path, *, max_tokens: int) -> int:
    """Count tokens explicitly tagged as fresh_delta_lane in expand subset."""
    if not path.is_file():
        return 0
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return 0
    if isinstance(doc, list):
        return 0
    count = 0
    for item in (doc.get("tokens") or [])[: max(1, int(max_tokens))]:
        if isinstance(item, dict) and str(item.get("refresh_lane") or "") == "fresh_delta_lane":
            count += 1
    return count


def hint_support_status(hint: PoolHint) -> str:
    raw = hint.raw or {}
    status = str(raw.get("support_status") or "")
    if status in (SUPPORT_SUPPORTED, SUPPORT_UNSUPPORTED, SUPPORT_UNKNOWN_ALIAS):
        return status
    return SUPPORT_UNKNOWN_ALIAS


def _verify_reject_reason(hint: PoolHint) -> Optional[str]:
    raw = hint.raw or {}
    reason = raw.get("verify_reject_reason")
    if reason:
        return str(reason)
    if hint.hint_status in BRIDGE_ELIGIBLE_HINT_STATUSES:
        return None
    return str(hint.hint_status or HINT_ONLY)


def _hint_raw_bool(hint: PoolHint, key: str) -> bool:
    return bool((hint.raw or {}).get(key))


def mirror_row_from_hint(hint: PoolHint) -> Dict[str, Any]:
    raw = hint.raw or {}
    pair = raw.get("pair") if isinstance(raw.get("pair"), dict) else {}
    recall_exists = _hint_raw_bool(hint, "recall_verified_pool_exists")
    selection_fresh = _hint_raw_bool(hint, "selection_verified_fresh")
    if "recall_verified_pool_exists" not in raw:
        recall_exists = hint.hint_status in BRIDGE_ELIGIBLE_HINT_STATUSES
    if "selection_verified_fresh" not in raw:
        selection_fresh = recall_exists
    return {
        "token": str(hint.focus_token or "").lower(),
        "pool": str(hint.pool_address or "").lower(),
        "dex_id": str(hint.dex_id or ""),
        "token0_addr": str(hint.token0_addr or "").lower(),
        "token1_addr": str(hint.token1_addr or "").lower(),
        "normalized_dex_id": str(raw.get("normalized_dex_id") or hint.dex_id or ""),
        "raw_dex_id": str(raw.get("raw_dex_id") or raw.get("dexId") or hint.dex_id or ""),
        "liquidity_usd": hint.liquidity_usd,
        "volume_24h": hint.volume_24h,
        "pair_created_at": hint.created_at or pair.get("pairCreatedAt"),
        "source": hint.source,
        "support_status": hint_support_status(hint),
        "hint_status": hint.hint_status,
        "mirror_age_bucket": str(raw.get("mirror_age_bucket") or mirror_age_bucket(hint)),
        "is_stale_hint": bool(raw.get("is_stale_hint")),
        "recall_verified_pool_exists": recall_exists,
        "selection_verified_fresh": selection_fresh,
        "recall_verification_status": str(
            raw.get("recall_verification_status")
            or (RECALL_STATUS_POOL_EXISTS if recall_exists else "recall_pool_not_found")
        ),
        "selection_verification_status": str(raw.get("selection_verification_status") or ""),
        "stale_recall_bucket": raw.get("stale_recall_bucket"),
        "existence_rca_bucket": raw.get("existence_rca_bucket"),
        "pool_exists_stale": bool(raw.get("pool_exists_stale")),
        "fresh_quote_candidate": bool(raw.get("fresh_quote_candidate")),
        "onchain_verified": selection_fresh,        "verify_reject_reason": _verify_reject_reason(hint),
        "uniswap_resolve_reason": raw.get("uniswap_resolve_reason"),
    }


def build_dex_alias_backlog(mirrors: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_dex: Dict[str, Dict[str, Any]] = {}
    for row in mirrors:
        raw_id = str(row.get("raw_dex_id") or row.get("dex_id") or "").lower()
        if not raw_id:
            continue
        bucket = by_dex.setdefault(
            raw_id,
            {
                "dexId": raw_id,
                "count": 0,
                "liquidity_sum": 0.0,
                "tokens": set(),
                "support_statuses": Counter(),
            },
        )
        bucket["count"] += 1
        liq = row.get("liquidity_usd")
        if liq is not None:
            try:
                bucket["liquidity_sum"] += float(liq)
            except (TypeError, ValueError):
                pass
        tok = str(row.get("token") or "").lower()
        if tok:
            bucket["tokens"].add(tok)
        bucket["support_statuses"][str(row.get("support_status") or "")] += 1
    out: List[Dict[str, Any]] = []
    for raw_id, bucket in sorted(by_dex.items(), key=lambda kv: -kv[1]["count"]):
        statuses = dict(bucket["support_statuses"])
        dominant = max(statuses, key=statuses.get) if statuses else None
        out.append(
            {
                "dexId": raw_id,
                "count": int(bucket["count"]),
                "liquidity_sum": round(float(bucket["liquidity_sum"]), 2),
                "tokens_count": len(bucket["tokens"]),
                "support_status": dominant,
                "support_status_breakdown": statuses,
            }
        )
    return out


def compute_recall_metrics(mirrors: List[Dict[str, Any]]) -> Dict[str, Any]:
    tokens_any: Set[str] = set()
    tokens_supported: Set[str] = set()
    tokens_unsupported: Set[str] = set()
    tokens_unknown: Set[str] = set()
    counters = defaultdict(int)
    for row in mirrors:
        tok = str(row.get("token") or "").lower()
        status = str(row.get("support_status") or SUPPORT_UNKNOWN_ALIAS)
        counters["mirrors_total"] += 1
        counters[f"mirrors_{status}"] += 1
        if tok:
            tokens_any.add(tok)
            if status == SUPPORT_SUPPORTED:
                tokens_supported.add(tok)
            elif status == SUPPORT_UNSUPPORTED:
                tokens_unsupported.add(tok)
            else:
                tokens_unknown.add(tok)
    supported = int(counters.get(f"mirrors_{SUPPORT_SUPPORTED}", 0))
    unsupported = int(counters.get(f"mirrors_{SUPPORT_UNSUPPORTED}", 0))
    unknown = int(counters.get(f"mirrors_{SUPPORT_UNKNOWN_ALIAS}", 0))
    total = int(counters["mirrors_total"])
    return {
        "mirrors_total": total,
        "mirrors_supported": supported,
        "mirrors_unsupported": unsupported,
        "mirrors_unknown_alias": unknown,
        "all_dex_mirrors_total": total,
        "supported_mirrors_total": supported,
        "unsupported_mirrors_total": unsupported,
        "unknown_alias_mirrors_total": unknown,
        "mirror_seen_any_dex": len(tokens_any),
        "mirror_seen_supported_dex": len(tokens_supported),
        "mirror_seen_unsupported_dex": len(tokens_unsupported),
        "mirror_seen_unknown_alias_dex": len(tokens_unknown),
    }


def build_stale_mirror_backlog(mirrors: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [
        row
        for row in mirrors
        if row.get("is_stale_hint")
        and row.get("recall_verified_pool_exists")
        and str(row.get("stale_recall_bucket") or "") == STALE_BUT_POOL_EXISTS
    ]


def build_verify_rca(
    *,
    hints: List[PoolHint],
    verify_metrics: Dict[str, Any],
    reject_rows: List[Dict[str, Any]],
) -> Dict[str, Any]:
    supported = [h for h in hints if hint_support_status(h) == SUPPORT_SUPPORTED]
    recall_exists = [h for h in supported if _hint_raw_bool(h, "recall_verified_pool_exists")]
    selection_fresh = [h for h in supported if _hint_raw_bool(h, "selection_verified_fresh")]
    by_reason = Counter(
        str(r.get("verify_reject_reason") or r.get("stale_recall_bucket") or "UNKNOWN")
        for r in reject_rows
    )
    stale_hist = dict(verify_metrics.get("stale_recall_bucket_histogram") or {})
    selection_blockers = Counter(
        str(r.get("selection_verification_status") or r.get("verify_reject_reason") or "UNKNOWN")
        for r in reject_rows
        if not r.get("selection_verified_fresh")
    )
    existence_hist = dict(verify_metrics.get("existence_rca_bucket_histogram") or {})
    pool_exists_stale = [
        h for h in supported if _hint_raw_bool(h, "pool_exists_stale")
    ]
    return {
        "schema_version": "m8_mirror_recall_verify_rca_v3",
        "generated_at_utc": _iso_now(),
        "supported_hints_total": len(supported),
        "recall_verified_pool_exists_total": len(recall_exists),
        "pool_exists_stale_total": len(pool_exists_stale),
        "selection_verified_fresh_total": len(selection_fresh),
        "supported_hints_verified": len(selection_fresh),
        "supported_hints_rejected": len(supported) - len(selection_fresh),
        "primary_blocker": (
            selection_blockers.most_common(1)[0][0]
            if selection_blockers
            else ("NO_SUPPORTED_HINTS" if not supported else "NONE")
        ),
        "primary_blocker_recall": (
            max(existence_hist, key=existence_hist.get) if existence_hist else "NONE"
        ),
        "primary_blocker_selection": (
            selection_blockers.most_common(1)[0][0]
            if selection_blockers
            else "NONE"
        ),
        "reject_reason_histogram": dict(by_reason),
        "stale_recall_bucket_histogram": stale_hist,
        "existence_rca_bucket_histogram": existence_hist,
        "factory_no_pool_by_dex": dict(verify_metrics.get("factory_no_pool_by_dex") or {}),
        "factory_no_pool_by_factory": dict(verify_metrics.get("factory_no_pool_by_factory") or {}),
        "factory_no_pool_samples": list(verify_metrics.get("factory_no_pool_samples") or []),
        "dex_null_age_histogram": dict(verify_metrics.get("dex_null_age_histogram") or {}),
        "aerodrome_variant_fallback_histogram": dict(verify_metrics.get("aerodrome_variant_fallback_histogram") or {}),
        "unsupported_aerodrome_pool_histogram": dict(verify_metrics.get("unsupported_aerodrome_pool_histogram") or {}),
        "unsupported_aerodrome_pool_samples": list(verify_metrics.get("unsupported_aerodrome_pool_samples") or []),
        "verification_metrics": verify_metrics,
        "reject_samples": reject_rows[:25],
    }


def verify_supported_hints(
    hints: List[PoolHint],
    *,
    chain: str = "base",
    dry_run: bool = False,
) -> Tuple[List[PoolHint], Dict[str, Any], List[Dict[str, Any]]]:
    """Recall-layer verify: stale hints may exist on-chain without M9 selection eligibility."""
    from m8.discovery.hint_verifier import empty_verification_metrics

    verify_metrics = empty_verification_metrics()
    reject_rows: List[Dict[str, Any]] = []
    out: List[PoolHint] = []
    factory_no_pool_by_dex: Dict[str, int] = {}
    factory_no_pool_by_factory: Dict[str, int] = {}
    factory_no_pool_samples: List[Dict[str, Any]] = []
    rpc_transient_factory_fail_total: int = 0
    dex_null_age_hist: Dict[str, int] = {}
    aero_variant_fallback_hist: Dict[str, int] = {}
    unsupported_aerodrome_pool_hist: Dict[str, Any] = {}
    unsupported_aerodrome_pool_samples: List[Dict[str, Any]] = []

    if dry_run or os.environ.get("ARBY_SKIP_RPC") == "1":
        for h in hints:
            status = hint_support_status(h)
            if status == SUPPORT_SUPPORTED:
                verified = verify_hint_for_recall(h, chain=chain, dry_run=True)
            else:
                verified = h
                verified.hint_status = (
                    HINT_DEX_UNSUPPORTED
                    if status == SUPPORT_UNSUPPORTED
                    else HINT_ONLY
                )
            out.append(verified)
            row = mirror_row_from_hint(verified)
            if not row.get("selection_verified_fresh"):
                reject_rows.append(row)
        verify_metrics["factory_no_pool_by_dex"] = factory_no_pool_by_dex
        verify_metrics["factory_no_pool_by_factory"] = factory_no_pool_by_factory
        verify_metrics["factory_no_pool_samples"] = factory_no_pool_samples
        verify_metrics["rpc_transient_factory_membership_fail_total"] = rpc_transient_factory_fail_total
        verify_metrics["dex_null_age_histogram"] = dex_null_age_hist
        verify_metrics["aerodrome_variant_fallback_histogram"] = aero_variant_fallback_hist
        verify_metrics["unsupported_aerodrome_pool_histogram"] = unsupported_aerodrome_pool_hist
        verify_metrics["unsupported_aerodrome_pool_samples"] = unsupported_aerodrome_pool_samples
        rca = build_verify_rca(hints=out, verify_metrics=verify_metrics, reject_rows=reject_rows)
        return out, rca, reject_rows

    for h in hints:
        status = hint_support_status(h)
        if status == SUPPORT_SUPPORTED:
            verified = verify_hint_for_recall(h, chain=str(h.chain or chain), metrics=verify_metrics)
            raw = verified.raw or {}
            bucket = raw.get("stale_recall_bucket")
            if bucket:
                hist = dict(verify_metrics.get("stale_recall_bucket_histogram") or {})
                hist[str(bucket)] = int(hist.get(str(bucket), 0)) + 1
                verify_metrics["stale_recall_bucket_histogram"] = hist
            ex_bucket = raw.get("existence_rca_bucket")
            if ex_bucket:
                ex_hist = dict(verify_metrics.get("existence_rca_bucket_histogram") or {})
                ex_hist[str(ex_bucket)] = int(ex_hist.get(str(ex_bucket), 0)) + 1
                verify_metrics["existence_rca_bucket_histogram"] = ex_hist

            aero_fb = raw.get("aerodrome_variant_fallback")
            if aero_fb:
                aero_variant_fallback_hist[str(aero_fb)] = int(aero_variant_fallback_hist.get(str(aero_fb), 0)) + 1

            if raw.get("existence_rca_bucket") == "UNSUPPORTED_OR_MISLABELED_AERODROME_POOL":
                key = f"{verified.dex_id}|{str(raw.get('aerodrome_factory_address') or verified.factory_address or 'unknown')[:42]}"
                unsupported_aerodrome_pool_hist[key] = int(unsupported_aerodrome_pool_hist.get(key, 0)) + 1
                if len(unsupported_aerodrome_pool_samples) < 20:
                    unsupported_aerodrome_pool_samples.append({
                        "dex_id": str(verified.dex_id or ""),
                        "raw_dex_id": str(raw.get("raw_dex_id") or ""),
                        "normalized_dex_id": str(raw.get("normalized_dex_id") or ""),
                        "factory_address": str(raw.get("aerodrome_factory_address") or verified.factory_address or "")[:42],
                        "pool_address": str(verified.pool_address or "")[:42],
                        "bytecode_len": raw.get("aerodrome_bytecode_len"),
                        "created_at": verified.created_at,
                        "created_at_source": raw.get("created_at_source"),
                        "token0_addr": str(verified.token0_addr or "")[:42],
                        "token1_addr": str(verified.token1_addr or "")[:42],
                    })

            reason_str = str(
                raw.get("verify_reject_reason")
                or raw.get("existence_rca_bucket")
                or raw.get("stale_recall_bucket")
                or verified.hint_status
            )
            if reason_str == "RPC_TRANSIENT_FACTORY_MEMBERSHIP_FAIL":
                rpc_transient_factory_fail_total += 1
            if reason_str == "FACTORY_NO_POOL":
                dex_key = str(verified.dex_id or "unknown")
                fac_key = str(verified.factory_address or raw.get("factory_address") or "unknown")
                factory_no_pool_by_dex[dex_key] = int(factory_no_pool_by_dex.get(dex_key, 0)) + 1
                factory_no_pool_by_factory[fac_key[:12]] = int(factory_no_pool_by_factory.get(fac_key[:12], 0)) + 1
                if len(factory_no_pool_samples) < 20:
                    factory_no_pool_samples.append({
                        "dex_id": dex_key,
                        "raw_dex_id": str(raw.get("raw_dex_id") or ""),
                        "factory_address": str(verified.factory_address or raw.get("factory_address") or "")[:42],
                        "fee": verified.fee,
                        "source": str(verified.source or ""),
                        "pool_address": str(verified.pool_address or "")[:42],
                        "token0_addr": str(verified.token0_addr or "")[:42],
                        "token1_addr": str(verified.token1_addr or "")[:42],
                        "created_at_source": raw.get("created_at_source"),
                    })

            if not verified.created_at and str(verified.source or "") == "dexscreener":
                dex_null_key = str(verified.dex_id or "unknown")
                dex_null_age_hist[dex_null_key] = int(dex_null_age_hist.get(dex_null_key, 0)) + 1

            row = mirror_row_from_hint(verified)
            if not row.get("selection_verified_fresh"):
                reject_rows.append(row)
            out.append(verified)
        else:
            h.hint_status = (
                HINT_DEX_UNSUPPORTED if status == SUPPORT_UNSUPPORTED else HINT_ONLY
            )
            out.append(h)
    verify_metrics["factory_no_pool_by_dex"] = factory_no_pool_by_dex
    verify_metrics["factory_no_pool_by_factory"] = factory_no_pool_by_factory
    verify_metrics["factory_no_pool_samples"] = factory_no_pool_samples
    verify_metrics["rpc_transient_factory_membership_fail_total"] = rpc_transient_factory_fail_total
    verify_metrics["dex_null_age_histogram"] = dex_null_age_hist
    verify_metrics["aerodrome_variant_fallback_histogram"] = aero_variant_fallback_hist
    verify_metrics["unsupported_aerodrome_pool_histogram"] = unsupported_aerodrome_pool_hist
    verify_metrics["unsupported_aerodrome_pool_samples"] = unsupported_aerodrome_pool_samples
    rca = build_verify_rca(hints=out, verify_metrics=verify_metrics, reject_rows=reject_rows)
    return out, rca, reject_rows


def _source_bucket(source: Optional[str]) -> str:
    s = str(source or "").lower()
    if s == "factory_log":
        return "factory_log"
    if s == "observer_factory_log":
        return "observer_factory_log"
    if s == "dexscreener":
        return "dexscreener"
    return "other"


def build_coverage_matrix(
    hints: List[PoolHint],
    config: Dict[str, Any],
) -> Dict[str, Any]:
    """Runtime coverage matrix: which DEX was seen/verified/quoted by which source."""
    dexes = config.get("dexes") or {}
    enabled_dexes = sorted(did for did, dcfg in dexes.items() if bool(dcfg.get("enabled", True)))
    source_buckets = ("factory_log", "observer_factory_log", "dexscreener", "other")
    verified_counts: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    quote_ready_counts: Dict[str, int] = defaultdict(int)
    for h in hints:
        if not _hint_raw_bool(h, "recall_verified_pool_exists"):
            continue
        dex = str(h.dex_id or "").lower()
        bucket = _source_bucket(h.source)
        if dex:
            verified_counts[dex][bucket] += 1
        status = str(h.hint_status or "").upper()
        if status.startswith("QUOTE") or status == QUOTE_SMOKE_OK:
            if dex:
                quote_ready_counts[dex] += 1

    rows = []
    for did in enabled_dexes:
        cfg = dexes.get(did) or {}
        rows.append({
            "dex_id": did,
            "adapter_type": str(cfg.get("adapter_type") or ""),
            "enabled": bool(cfg.get("enabled", True)),
            "verified_by_source": dict(verified_counts.get(did, {})),
            "verified_total": sum(verified_counts.get(did, {}).values()),
            "quote_ready_total": quote_ready_counts.get(did, 0),
        })
    source_totals = {
        bucket: sum(int(r["verified_by_source"].get(bucket, 0)) for r in rows)
        for bucket in source_buckets
    }
    return {
        "schema_version": "m8_recall_coverage_matrix_v1",
        "dex_count": len(enabled_dexes),
        "covered_dexes": sorted({r["dex_id"] for r in rows if r["verified_total"] > 0}),
        "quote_ready_dexes": sorted({r["dex_id"] for r in rows if r["quote_ready_total"] > 0}),
        "source_totals": source_totals,
        "rows": rows,
    }


def build_second_venue_rca(hints: List[PoolHint]) -> List[Dict[str, Any]]:
    """Per-token RCA for focus tokens with verified second venue but not quote-ready second venue."""
    focus_dexes: Dict[str, Set[str]] = defaultdict(set)
    focus_quote_dexes: Dict[str, Set[str]] = defaultdict(set)
    focus_pools: Dict[str, Dict[str, List[str]]] = defaultdict(lambda: defaultdict(list))
    focus_quote_status: Dict[str, Dict[str, str]] = defaultdict(dict)
    for h in hints:
        if not _hint_raw_bool(h, "recall_verified_pool_exists"):
            continue
        focus = str(h.focus_token or "").lower()
        dex = str(h.dex_id or "").lower()
        if not focus or not dex:
            continue
        focus_dexes[focus].add(dex)
        pool = str(h.pool_address or "").lower()
        if pool:
            focus_pools[focus][dex].append(pool)
        status = str(h.hint_status or "").upper()
        if status.startswith("QUOTE") or status == QUOTE_SMOKE_OK:
            focus_quote_dexes[focus].add(dex)
            focus_quote_status[focus][dex] = str(h.hint_status or "")

    rca_rows = []
    for focus, dexes in focus_dexes.items():
        if len(dexes) < 2:
            continue
        quote_dexes = focus_quote_dexes.get(focus, set())
        if len(quote_dexes) >= 2:
            continue
        blocker = (
            "QUOTE_READY_ZERO"
            if not quote_dexes
            else "QUOTE_READY_SINGLE_VENUE"
        )
        rca_rows.append({
            "focus_token": focus,
            "verified_dexes": sorted(dexes),
            "quote_ready_dexes": sorted(quote_dexes),
            "verified_pools_per_dex": {
                dex: sorted(set(pools)) for dex, pools in focus_pools[focus].items()
            },
            "quote_status_per_dex": dict(focus_quote_status.get(focus, {})),
            "blocker_reason": blocker,
        })
    return sorted(rca_rows, key=lambda x: x["focus_token"])


def run_mirror_discovery_recall(
    tokens: List[str],
    *,
    chain: str = "base",
    config: Optional[Dict[str, Any]] = None,
    dry_run: bool = False,
    cache_lane: str = "mirror_recall",
    use_cache: bool = False,
    token_pool_universe: bool = True,
    graph_closure_only: bool = True,
    anchor_constrained: bool = False,
    run_quote_smoke: bool = False,
    quote_smoke_max_candidates: int = 0,
    use_dexscreener: bool = True,
    subset_path: Optional[Path] = None,
) -> Tuple[List[PoolHint], Dict[str, Any]]:
    from m8.discovery.token_pool_universe import (
        anchor_addresses_from_config,
        build_pool_universe_width,
        build_unsupported_dex_backlog,
        filter_hot_path_hints,
        fresh_token_addresses,
        load_factory_recall_hints,
        sort_hints_for_verify,
        stamp_universe_type,
        build_closure_graph,
    )

    cfg = config or _load_yaml_config(DEFAULT_CONFIG_PATH)
    fresh_set = fresh_token_addresses(tokens)
    anchor_addrs = anchor_addresses_from_config(cfg)
    # In anchor-constrained mode we scan DexScreener only for fresh target tokens
    # (raw factory log seeds / pending single-venue watch), then accept only pairs
    # where the other side is a configured anchor.
    scan_tokens = list(fresh_set) if anchor_constrained else list(tokens)
    anchor_filter_metrics: Dict[str, Any] = {
        "anchor_constrained": anchor_constrained,
        "fresh_targets_scanned": len(fresh_set) if anchor_constrained else 0,
        "fresh_targets_actual_scanned": (
            _count_fresh_delta_lane_tokens(subset_path, max_tokens=len(tokens))
            if anchor_constrained and subset_path
            else 0
        ),
    }
    if anchor_constrained and subset_path:
        anchor_filter_metrics["fresh_targets_non_delta_scanned"] = (
            len(fresh_set) - int(anchor_filter_metrics["fresh_targets_actual_scanned"])
        )
    all_hints: List[PoolHint] = []
    dexscreener_pairs_seen = 0
    anchor_pairs_seen = 0
    if use_dexscreener:
        for i in range(0, len(scan_tokens), DEXSCREENER_BATCH_MAX):
            chunk = scan_tokens[i : i + DEXSCREENER_BATCH_MAX]
            batch = fetch_token_hints_batch(
                chunk,
                chain=chain,
                max_recall=True,
                dex_config=cfg,
                cache_lane=cache_lane,
                use_cache=use_cache,
            )
            for rows in batch.values():
                if anchor_constrained:
                    from m8.discovery.dexscreener_hints import filter_anchor_mirror_pairs

                    filtered, fm = filter_anchor_mirror_pairs(rows, anchor_addrs=anchor_addrs)
                    dexscreener_pairs_seen += int(fm.get("dexscreener_pairs_seen") or 0)
                    anchor_pairs_seen += int(fm.get("anchor_pairs_seen") or 0)
                    all_hints.extend(filtered)
                else:
                    all_hints.extend(rows)
    if anchor_constrained:
        anchor_filter_metrics["dexscreener_pairs_seen"] = dexscreener_pairs_seen
        anchor_filter_metrics["anchor_pairs_seen"] = anchor_pairs_seen
        anchor_filter_metrics["use_dexscreener"] = use_dexscreener
    if token_pool_universe:
        factory_hints = load_factory_recall_hints(fresh_set)
        all_hints.extend(factory_hints)
    deduped = dedupe_hints(all_hints)
    if token_pool_universe:
        deduped = filter_hot_path_hints(
            deduped,
            fresh_tokens=fresh_set,
            anchor_addrs=anchor_addrs,
            graph_closure_only=graph_closure_only,
        )
    closure_graph = build_closure_graph(deduped, fresh_tokens=fresh_set)
    stamped = [
        stamp_universe_type(
            h,
            fresh_tokens=fresh_set,
            closure_graph=closure_graph,
            anchor_addrs=anchor_addrs,
        )
        for h in deduped
    ]
    verify_order = sort_hints_for_verify(stamped)
    verified, rca, _reject_rows = verify_supported_hints(
        verify_order, chain=chain, dry_run=dry_run
    )
    if run_quote_smoke:
        run_fresh_mirror_quote_smoke(
            verified,
            chain=chain,
            config=cfg,
            max_candidates=quote_smoke_max_candidates,
        )
    mirrors = [mirror_row_from_hint(h) for h in verified]
    metrics = compute_recall_metrics(mirrors)
    recall_exists_total = sum(1 for row in mirrors if row.get("recall_verified_pool_exists"))
    selection_fresh_total = sum(1 for row in mirrors if row.get("selection_verified_fresh"))
    pool_exists_stale_total = sum(1 for row in mirrors if row.get("pool_exists_stale"))
    fresh_quote_candidate_total = sum(1 for row in mirrors if row.get("fresh_quote_candidate"))
    quote_ready_total = sum(
        1
        for h in verified
        if str(h.hint_status or "").upper().startswith("QUOTE") or h.hint_status == QUOTE_SMOKE_OK
    )
    # Second-pool / second-venue readiness is computed from selection-fresh
    # verified pools. M9 admission additionally requires the same focus token
    # to have quote-ready pools on >=2 distinct dexes.
    focus_pools_ready: Dict[str, Set[str]] = {}
    focus_dexes_ready: Dict[str, Set[str]] = {}
    focus_quote_dexes_ready: Dict[str, Set[str]] = {}
    for h in verified:
        if _hint_raw_bool(h, "recall_verified_pool_exists") and _hint_raw_bool(h, "selection_verified_fresh"):
            focus = str(h.focus_token or "").lower()
            pool = str(h.pool_address or "").lower()
            dex = str(h.dex_id or "").lower()
            if focus and pool:
                focus_pools_ready.setdefault(focus, set()).add(pool)
            if focus and dex:
                focus_dexes_ready.setdefault(focus, set()).add(dex)
            if (
                focus
                and dex
                and (
                    str(h.hint_status or "").upper().startswith("QUOTE")
                    or h.hint_status == QUOTE_SMOKE_OK
                )
            ):
                focus_quote_dexes_ready.setdefault(focus, set()).add(dex)
    second_pool_ready_total = sum(
        1 for focus, pools in focus_pools_ready.items() if len(pools) >= 2
    )
    second_venue_ready_total = sum(
        1 for focus, dexes in focus_dexes_ready.items() if len(dexes) >= 2
    )
    quote_ready_second_venue_total = sum(
        1 for focus, dexes in focus_quote_dexes_ready.items() if len(dexes) >= 2
    )
    verified_pool_count_by_dex: Dict[str, int] = Counter()
    second_pool_count_by_dex: Dict[str, int] = Counter()
    verified_second_venues_by_dex: Dict[str, int] = Counter()
    observer_focus_tokens: Set[str] = set()
    observer_overlap_fresh: Set[str] = set()
    observer_overlap_quote: Set[str] = set()
    observer_second_venue_candidates: Set[str] = set()
    observer_verified_second_venues: Set[str] = set()
    for h in verified:
        if _hint_raw_bool(h, "recall_verified_pool_exists"):
            dex = str(h.dex_id or "").lower()
            focus = str(h.focus_token or "").lower()
            if dex:
                verified_pool_count_by_dex[dex] += 1
            if str(h.source or "").lower() == "observer_factory_log" and focus:
                observer_focus_tokens.add(focus)
                if focus in focus_pools_ready and len(focus_pools_ready[focus]) >= 2:
                    second_pool_count_by_dex[dex] += 1
                if _hint_raw_bool(h, "selection_verified_fresh"):
                    observer_overlap_fresh.add(focus)
                if h.hint_status == QUOTE_SMOKE_OK:
                    observer_overlap_quote.add(focus)
                if focus in focus_pools_ready and len(focus_pools_ready[focus]) >= 2:
                    observer_second_venue_candidates.add(focus)
    for focus, dexes in focus_dexes_ready.items():
        if len(dexes) >= 2:
            if focus in observer_focus_tokens:
                observer_verified_second_venues.add(focus)
            for dex in dexes:
                verified_second_venues_by_dex[dex] += 1
    age_buckets = Counter(str(row.get("mirror_age_bucket") or "unknown") for row in mirrors)
    fresh_age_buckets = Counter(_fresh_age_bucket(h.created_at) for h in verified if _hint_raw_bool(h, "selection_verified_fresh"))
    pool_universe_width = build_pool_universe_width(
        verified, mirrors, fresh_tokens=fresh_set
    )
    unsupported_backlog = build_unsupported_dex_backlog(mirrors, config=cfg)
    recall_run_id = _iso_now()
    m9_blocker = "NONE"
    if quote_ready_total == 0 and selection_fresh_total > 0:
        m9_blocker = "QUOTE_READY_ZERO"
    elif quote_ready_total > 0 and second_venue_ready_total == 0:
        m9_blocker = "SECOND_VENUE_READY_ZERO"
    elif quote_ready_total > 0 and second_venue_ready_total > 0 and quote_ready_second_venue_total == 0:
        m9_blocker = "QUOTE_READY_SECOND_VENUE_ZERO"
    elif quote_ready_total > 0 and second_venue_ready_total > 0 and second_pool_ready_total == 0:
        m9_blocker = "SECOND_POOL_READY_ZERO"
    payload = {
        "schema_version": "m8_mirror_discovery_recall_v5",
        "generated_at_utc": recall_run_id,
        "recall_run_id": recall_run_id,
        "lane": "token_pool_universe" if token_pool_universe else "mirror_discovery_max_recall",
        "chain": chain,
        "tokens_scanned": len(tokens),
        "fetch_mode": "token_scoped_all_pool_recall",
        "token_pool_universe": token_pool_universe,
        "graph_closure_only": graph_closure_only,
        "use_cache": use_cache,
        "truth_boundary": "recall_candidate_wide_admission_strict",
        "pool_universe_width": pool_universe_width,
        "mirrors": mirrors,
        "dex_alias_backlog": build_dex_alias_backlog(mirrors),
        "unsupported_dex_backlog": unsupported_backlog,
        "stale_mirror_backlog": build_stale_mirror_backlog(mirrors),
        "mirror_age_bucket_histogram": dict(age_buckets),
        "fresh_age_bucket_histogram": dict(fresh_age_buckets),
        "verify_rca_path": str(DEFAULT_VERIFY_RCA_PATH),
        "recall_verified_pool_exists_total": recall_exists_total,
        "pool_exists_stale_total": pool_exists_stale_total,
        "fresh_quote_candidate_total": fresh_quote_candidate_total,
        "selection_verified_fresh_total": selection_fresh_total,
        "fresh_target_ready_total": selection_fresh_total,
        "quote_ready_total": quote_ready_total,
        "second_pool_ready_total": second_pool_ready_total,
        "second_venue_ready_total": second_venue_ready_total,
        "quote_ready_second_venue_total": quote_ready_second_venue_total,
        "verified_pool_count_by_dex": dict(verified_pool_count_by_dex),
        "second_pool_count_by_dex": dict(second_pool_count_by_dex),
        "verified_second_venues_by_dex": dict(verified_second_venues_by_dex),
        "observer_focus_tokens_total": len(observer_focus_tokens),
        "observer_overlap_fresh_total": len(observer_overlap_fresh),
        "observer_overlap_quote_total": len(observer_overlap_quote),
        "observer_second_venue_candidate_total": len(observer_second_venue_candidates),
        "observer_verified_second_venue_total": len(observer_verified_second_venues),
        "rpc_transient_factory_membership_fail_total": rca.get(
            "verification_metrics", {}
        ).get("rpc_transient_factory_membership_fail_total", 0),
        "coverage_matrix": build_coverage_matrix(verified, cfg),
        "second_venue_rca": build_second_venue_rca(verified),
        "supported_hints_verified": selection_fresh_total,
        **anchor_filter_metrics,
        # Deprecated: m9_target_ready historically meant fresh target exists.
        # Use fresh_target_ready_total / fresh_target_ready for that and
        # m9_admission_ready for actual M9 bridge/shadow admission.
        "m9_target_ready": selection_fresh_total > 0,
        "fresh_target_ready": selection_fresh_total > 0,
        "m9_admission_ready": quote_ready_second_venue_total > 0,
        "m9_admission_blocker": m9_blocker,
        "mirror_recall_ready": int(metrics.get("mirrors_total") or 0) > 0,
        **metrics,
    }
    write_verify_rca(rca)
    write_recall_hints_checkpoint(verified, chain=chain)
    queue_paths = write_mirror_queue_artifacts(payload, hints=verified, chain=chain)
    payload["queue_artifacts"] = queue_paths
    payload["verify_rca"] = {
        "supported_hints_total": rca.get("supported_hints_total"),
        "recall_verified_pool_exists_total": rca.get("recall_verified_pool_exists_total"),
        "selection_verified_fresh_total": rca.get("selection_verified_fresh_total"),
        "supported_hints_verified": rca.get("selection_verified_fresh_total"),
        "primary_blocker": (
            m9_blocker if m9_blocker != "NONE" else rca.get("primary_blocker")
        ),
        "primary_blocker_selection": (
            m9_blocker if m9_blocker != "NONE" else rca.get("primary_blocker_selection")
        ),
        "m9_admission_blocker": m9_blocker,
        "stale_recall_bucket_histogram": rca.get("stale_recall_bucket_histogram"),
        "existence_rca_bucket_histogram": rca.get("existence_rca_bucket_histogram"),
        "pool_exists_stale_total": rca.get("pool_exists_stale_total"),
        "rpc_transient_factory_membership_fail_total": rca.get(
            "verification_metrics", {}
        ).get("rpc_transient_factory_membership_fail_total", 0),
    }
    return verified, payload


def write_mirror_queue_artifacts(
    recall_payload: Dict[str, Any],
    *,
    hints: List[PoolHint],
    chain: str = "base",
) -> Dict[str, str]:
    """Split recall output into recall / existence-verify / quote-ready queues."""
    mirrors = list(recall_payload.get("mirrors") or [])
    recall_doc = {
        "schema_version": "m8_mirror_recall_candidates_v1",
        "generated_at_utc": _iso_now(),
        "chain": chain,
        "candidates": mirrors,
        "all_dex_mirrors_total": int(recall_payload.get("all_dex_mirrors_total") or 0),
        "pool_universe_width": recall_payload.get("pool_universe_width"),
    }
    existence_hints = [
        h
        for h in hints
        if hint_support_status(h) == SUPPORT_SUPPORTED
        and not _hint_raw_bool(h, "recall_verified_pool_exists")
    ]
    # Quote-ready queue must contain only hints that passed quote smoke.
    # Fresh-but-not-quote-ready tokens belong in the pending / second-venue
    # watchlist, not in the quote-ready handoff queue.
    quote_ready_hints = [
        h
        for h in hints
        if str(h.hint_status or "").upper().startswith("QUOTE") or h.hint_status == QUOTE_SMOKE_OK
    ]
    existence_doc = {
        "schema_version": "m8_mirror_existence_verify_queue_v1",
        "generated_at_utc": _iso_now(),
        "chain": chain,
        "queue_count": len(existence_hints),
        "hints": [h.to_dict() for h in existence_hints],
        "tokens": sorted(
            {str(h.focus_token or "").lower() for h in existence_hints if h.focus_token}
        ),
    }
    quote_doc = {
        "schema_version": "m8_mirror_quote_ready_queue_v1",
        "generated_at_utc": _iso_now(),
        "chain": chain,
        "queue_count": len(quote_ready_hints),
        "hints": [h.to_dict() for h in quote_ready_hints],
    }
    for path, doc in (
        (RECALL_CANDIDATES_PATH, recall_doc),
        (EXISTENCE_VERIFY_QUEUE_PATH, existence_doc),
        (QUOTE_READY_QUEUE_PATH, quote_doc),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    _write_existence_verify_subset(existence_doc)
    return {
        "recall_candidates": str(RECALL_CANDIDATES_PATH),
        "existence_verify_queue": str(EXISTENCE_VERIFY_QUEUE_PATH),
        "quote_ready_queue": str(QUOTE_READY_QUEUE_PATH),
        "existence_verify_subset": str(EXISTENCE_VERIFY_SUBSET_PATH),
    }


def _write_existence_verify_subset(existence_doc: Dict[str, Any]) -> None:
    tokens = existence_doc.get("tokens") or []
    subset = {
        "schema_version": "m8_existence_verify_subset_v1",
        "generated_at_utc": _iso_now(),
        "tokens": [{"token": t, "source": "existence_verify_queue"} for t in tokens],
        "token_count": len(tokens),
    }
    EXISTENCE_VERIFY_SUBSET_PATH.parent.mkdir(parents=True, exist_ok=True)
    EXISTENCE_VERIFY_SUBSET_PATH.write_text(json.dumps(subset, indent=2), encoding="utf-8")


def write_recall_hints_checkpoint(
    hints: List[PoolHint],
    *,
    output_path: Path = DEFAULT_RECALL_HINTS_PATH,
    chain: str = "base",
) -> Path:
    artifact = build_artifact(
        hints=hints,
        chain=chain,
        sources=["dexscreener_mirror_recall_checkpoint"],
        metrics={"recall_hints_checkpoint": True, "hint_count": len(hints)},
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    return output_path


def load_recall_hints_checkpoint(
    path: Path = DEFAULT_RECALL_HINTS_PATH,
) -> List[PoolHint]:
    if not path.is_file():
        return []
    doc = json.loads(path.read_text(encoding="utf-8"))
    return [PoolHint.from_dict(h) for h in doc.get("hints") or [] if isinstance(h, dict)]


def write_verify_rca(
    rca: Dict[str, Any],
    *,
    output_path: Path = DEFAULT_VERIFY_RCA_PATH,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(rca, indent=2), encoding="utf-8")
    return output_path


def write_mirror_discovery_recall(
    payload: Dict[str, Any],
    *,
    output_path: Path = DEFAULT_RECALL_ARTIFACT,
) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return output_path


def _fresh_age_bucket(created_at_iso: Optional[str]) -> str:
    """Bucket a fresh token by age since created_at (or unknown)."""
    if not created_at_iso:
        return "unknown"
    try:
        from datetime import datetime, timezone

        dt = datetime.fromisoformat(str(created_at_iso).replace("Z", "+00:00"))
        age_s = (datetime.now(timezone.utc) - dt).total_seconds()
        if age_s < 3600:
            return "<1h"
        if age_s < 6 * 3600:
            return "1-6h"
        if age_s < 24 * 3600:
            return "6-24h"
        if age_s < 48 * 3600:
            return "24-48h"
        return "expired"
    except Exception:
        return "unknown"


def evaluate_selection_verified_fresh_gate(payload: Dict[str, Any]) -> Tuple[bool, str]:
    """Cross-dex expand and M8.3 require at least one selection-fresh verified mirror."""
    sel_fresh = int(payload.get("selection_verified_fresh_total") or 0)
    if sel_fresh > 0:
        return True, "selection_verified_fresh_ready"
    return False, "SELECTION_VERIFIED_FRESH_ZERO"


def evaluate_m9_admission_gate(payload: Dict[str, Any]) -> Tuple[bool, str]:
    """M9 bridge/shadow opens only when fresh + quote-ready + second venue exist."""
    sel_fresh = int(payload.get("selection_verified_fresh_total") or 0)
    if sel_fresh <= 0:
        return False, "SELECTION_VERIFIED_FRESH_ZERO"
    quote_ready = int(payload.get("quote_ready_total") or 0)
    if quote_ready <= 0:
        return False, "QUOTE_READY_ZERO"
    second_venue = int(payload.get("second_venue_ready_total") or 0)
    if second_venue <= 0:
        return False, "SECOND_VENUE_ZERO"
    return True, "M9_ADMISSION_POSSIBLE"


def evaluate_mirror_recall_gate(payload: Dict[str, Any]) -> Tuple[bool, str]:
    total = int(payload.get("all_dex_mirrors_total") or payload.get("mirrors_total") or 0)
    if total > 0:
        return True, "MIRROR_RECALL_READY"
    return False, "NO_MIRRORS_SEEN"


def _hint_to_smoke_route(hint: PoolHint) -> Dict[str, Any]:
    raw = hint.raw or {}
    dex_id = str(hint.dex_id or "")
    adapter = dex_id
    if dex_id == "aerodrome":
        adapter = "aerodrome_v2_stable"
    focus = str(hint.focus_token or "").lower()
    return {
        "route_id": f"{hint.focus_token}:{hint.pool_address}:{dex_id}",
        "dex_id": dex_id,
        "adapter_type": adapter,
        "pool_address": hint.pool_address,
        "pool_id": hint.pool_id,
        "token0_addr": hint.token0_addr,
        "token1_addr": hint.token1_addr,
        "focus_token": hint.focus_token,
        "focus_token_address": focus,
        "focus_token_symbol": focus[:10],
        "quote_smoke_status": "not_run",
        "raw_dex_id": raw.get("raw_dex_id"),
    }


def run_stale_mirror_quote_smoke(
    hints: List[PoolHint],
    *,
    chain: str = "base",
    checkpoint_path: Path = Path("data/tmp/m8_mirror_recall_stale_quote_smoke_latest.json"),
) -> Dict[str, Any]:
    """Targeted quote smoke for stale pool_exists mirrors only (not M9)."""
    stale_pool_exists = [
        h
        for h in hints
        if _hint_raw_bool(h, "pool_exists_stale") or (
            _hint_raw_bool(h, "recall_verified_pool_exists")
            and (h.raw or {}).get("is_stale_hint")
        )
    ]
    if not stale_pool_exists:
        return {"attempted": 0, "quote_ok": 0, "skipped": len(hints), "reason": "NO_STALE_POOL_EXISTS"}
    routes = [_hint_to_smoke_route(h) for h in stale_pool_exists]
    from m8.discovery.mirror_quote_smoke import smoke_mirror_same_pair_routes

    result = smoke_mirror_same_pair_routes(
        routes,
        chain=chain,
        checkpoint_path=str(checkpoint_path),
        pipeline_mode=True,
        force_retry=True,
    )
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_path.write_text(json.dumps({**result, "routes": routes}, indent=2), encoding="utf-8")
    return result


def _fresh_candidate_priority(hint: PoolHint) -> float:
    """Newer candidates first; missing created_at sorts last."""
    created_at = hint.created_at
    if not created_at:
        return 0.0
    try:
        dt = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
        return dt.timestamp()
    except (ValueError, TypeError):
        return 0.0


def run_fresh_mirror_quote_smoke(
    hints: List[PoolHint],
    *,
    chain: str = "base",
    config: Optional[Dict[str, Any]] = None,
    max_candidates: int = 0,
    checkpoint_path: Path = Path("data/tmp/m8_mirror_recall_fresh_quote_smoke_latest.json"),
) -> Dict[str, Any]:
    """Targeted quote smoke for fresh pool_exists candidates (any source).

    ``max_candidates`` bounds the number of quote smokes in fast cadence; 0 = unlimited.
    Candidates are sorted newest-first so the hottest tokens get smoke first.
    """
    fresh_candidates = [
        h
        for h in hints
        if _hint_raw_bool(h, "fresh_quote_candidate")
    ]
    if not fresh_candidates:
        return {"attempted": 0, "quote_ok": 0, "skipped": len(hints), "reason": "NO_FRESH_CANDIDATES"}
    fresh_candidates = sorted(fresh_candidates, key=_fresh_candidate_priority, reverse=True)
    if max_candidates and max_candidates > 0:
        fresh_candidates = fresh_candidates[:max_candidates]
    routes = [_hint_to_smoke_route(h) for h in fresh_candidates]
    from m8.discovery.mirror_quote_smoke import smoke_mirror_same_pair_routes

    result = smoke_mirror_same_pair_routes(
        routes,
        chain=chain,
        config=config,
        checkpoint_path=str(checkpoint_path),
        pipeline_mode=True,
        force_retry=True,
    )
    from m8.discovery.mirror_quote_smoke import _status_quoteable

    quote_ok_count = 0
    for h, r in zip(fresh_candidates, routes):
        if _status_quoteable(r.get("quote_smoke_status")):
            h.hint_status = QUOTE_SMOKE_OK
            (h.raw or {}).setdefault("quote_smoke_status", str(r.get("quote_smoke_status") or "QUOTE_OK"))
            quote_ok_count += 1
    result["quote_ready_candidates"] = quote_ok_count
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    checkpoint_path.write_text(json.dumps({**result, "routes": routes}, indent=2), encoding="utf-8")
    return result


def run_mirror_selection_pass(
    recall_payload: Dict[str, Any],
    *,
    hints: List[PoolHint],
    selection_input_path: Optional[Path] = None,
    output_path: Path = DEFAULT_SUPPORTED_HINTS_PATH,
    selection_artifact_path: Path = DEFAULT_SELECTION_ARTIFACT,
    run_stale_quote_smoke: bool = True,
) -> Dict[str, Any]:
    """recall -> pool_exists -> fresh_enough -> quote_ready -> narrow bridge handoff."""
    input_path = selection_input_path or DEFAULT_RECALL_HINTS_PATH
    pool_exists = [
        h
        for h in hints
        if hint_support_status(h) == SUPPORT_SUPPORTED
        and _hint_raw_bool(h, "recall_verified_pool_exists")
    ]
    pool_exists_stale = [
        h for h in pool_exists if _hint_raw_bool(h, "pool_exists_stale")
    ]
    fresh_enough = [
        h
        for h in pool_exists
        if _hint_raw_bool(h, "selection_verified_fresh")
    ]
    fresh_quote_candidate = [
        h for h in hints if _hint_raw_bool(h, "fresh_quote_candidate")
    ]
    stale_smoke: Dict[str, Any] = {"skipped": True, "reason": "DISABLED"}
    if run_stale_quote_smoke and pool_exists_stale:
        stale_smoke = run_stale_mirror_quote_smoke(pool_exists_stale, chain=str(recall_payload.get("chain") or "base"))
    quote_ready = [
        h
        for h in fresh_enough
        if str(h.hint_status or "").upper().startswith("QUOTE")
        or h.hint_status == QUOTE_SMOKE_OK
    ]
    # A token has a verified second venue if it has >=2 distinct verified dexes
    # for the same focus token. M9 admission still requires quote_ready>0 on top
    # of second_venue_ready, so the metrics are reported separately.
    focus_dexes: Dict[str, Set[str]] = {}
    for h in fresh_enough:
        focus = str(h.focus_token or "").lower()
        dex = str(h.dex_id or "").lower()
        if focus and dex:
            focus_dexes.setdefault(focus, set()).add(dex)
    second_venue_ready_focuses = {
        focus for focus, dexes in focus_dexes.items() if len(dexes) >= 2
    }
    second_venue_ready = [h for h in fresh_enough if str(h.focus_token or "").lower() in second_venue_ready_focuses]
    quote_ready_dexes: Dict[str, Set[str]] = {}
    for h in quote_ready:
        focus = str(h.focus_token or "").lower()
        dex = str(h.dex_id or "").lower()
        if focus and dex:
            quote_ready_dexes.setdefault(focus, set()).add(dex)
    quote_ready_second_venue_focuses = {
        focus for focus, dexes in quote_ready_dexes.items() if len(dexes) >= 2
    }
    handoff = quote_ready if quote_ready else fresh_enough
    fresh_target_ready = len(fresh_enough) > 0
    m9_admission_ready = len(quote_ready_second_venue_focuses) > 0
    artifact = build_artifact(
        hints=handoff,
        chain=str(recall_payload.get("chain") or "base"),
        sources=["dexscreener_mirror_recall"],
        metrics={
            "mirror_selection_from_recall": True,
            "mirrors_selected": len(handoff),
            "pool_exists_count": len(pool_exists),
            "pool_exists_stale_count": len(pool_exists_stale),
            "fresh_enough_count": len(fresh_enough),
            "fresh_quote_candidate_count": len(fresh_quote_candidate),
            "quote_ready_count": len(quote_ready),
            "second_venue_ready_count": len(second_venue_ready_focuses),
            "quote_ready_second_venue_count": len(quote_ready_second_venue_focuses),
            "fresh_target_ready": fresh_target_ready,
            "m9_admission_ready": m9_admission_ready,
            "recall_mirrors_total": int(recall_payload.get("mirrors_total") or 0),
        },
    )
    write_hints_artifact(artifact, str(output_path))
    selection = {
        "schema_version": "m8_mirror_selection_v4",
        "generated_at_utc": _iso_now(),
        "selection_input_path": str(input_path),
        "pool_exists_count": len(pool_exists),
        "pool_exists_stale_count": len(pool_exists_stale),
        "fresh_enough_count": len(fresh_enough),
        "fresh_quote_candidate_count": len(fresh_quote_candidate),
        "quote_ready_count": len(quote_ready),
        "second_venue_ready_count": len(second_venue_ready_focuses),
        "quote_ready_second_venue_count": len(quote_ready_second_venue_focuses),
        "mirrors_selected": len(handoff),
        "output_path": str(output_path),
        # Deprecated: m9_target_ready historically meant fresh target exists.
        # Use fresh_target_ready for that semantics and m9_admission_ready for
        # actual M9 bridge/shadow admission.
        "m9_target_ready": fresh_target_ready,
        "fresh_target_ready": fresh_target_ready,
        "m9_admission_ready": m9_admission_ready,
        "narrow_bridge_ready": len(fresh_enough) > 0,
        "stale_quote_smoke": stale_smoke,
        "selection_stages": {
            "recall": int(recall_payload.get("all_dex_mirrors_total") or 0),
            "pool_exists": len(pool_exists),
            "pool_exists_stale": len(pool_exists_stale),
            "fresh_enough": len(fresh_enough),
            "fresh_quote_candidate": len(fresh_quote_candidate),
            "quote_ready": len(quote_ready),
            "second_venue_ready": len(second_venue_ready_focuses),
            "quote_ready_second_venue": len(quote_ready_second_venue_focuses),
            "fresh_target_ready": len(fresh_enough),
            "m9_admission_ready": len(quote_ready) if m9_admission_ready else 0,
            "narrow": len(handoff),
        },
    }
    selection_artifact_path.parent.mkdir(parents=True, exist_ok=True)
    selection_artifact_path.write_text(json.dumps(selection, indent=2), encoding="utf-8")
    return selection


def run_mirror_discovery_recall_from_subset(
    *,
    subset_path: Path = DEFAULT_EXPAND_SUBSET,
    max_tokens: int = 150,
    output_path: Path = DEFAULT_RECALL_ARTIFACT,
    dry_run: bool = False,
    use_cache: bool = False,
    anchor_constrained: bool = False,
    run_quote_smoke: bool = False,
    quote_smoke_max_candidates: int = 0,
) -> Dict[str, Any]:
    tokens = _load_token_list(subset_path, max_tokens=max_tokens)
    _hints, payload = run_mirror_discovery_recall(
        tokens,
        dry_run=dry_run,
        use_cache=use_cache,
        anchor_constrained=anchor_constrained,
        run_quote_smoke=run_quote_smoke,
        quote_smoke_max_candidates=quote_smoke_max_candidates,
        subset_path=subset_path,
    )
    write_mirror_discovery_recall(payload, output_path=output_path)
    return payload
