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
    dex_null_age_hist: Dict[str, int] = {}

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
        verify_metrics["dex_null_age_histogram"] = dex_null_age_hist
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

            reason_str = str(
                raw.get("verify_reject_reason")
                or raw.get("existence_rca_bucket")
                or raw.get("stale_recall_bucket")
                or verified.hint_status
            )
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
    verify_metrics["dex_null_age_histogram"] = dex_null_age_hist
    rca = build_verify_rca(hints=out, verify_metrics=verify_metrics, reject_rows=reject_rows)
    return out, rca, reject_rows


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
    all_hints: List[PoolHint] = []
    for i in range(0, len(tokens), DEXSCREENER_BATCH_MAX):
        chunk = tokens[i : i + DEXSCREENER_BATCH_MAX]
        batch = fetch_token_hints_batch(
            chunk,
            chain=chain,
            max_recall=True,
            dex_config=cfg,
            cache_lane=cache_lane,
            use_cache=use_cache,
        )
        for rows in batch.values():
            all_hints.extend(rows)
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
    mirrors = [mirror_row_from_hint(h) for h in verified]
    metrics = compute_recall_metrics(mirrors)
    recall_exists_total = sum(1 for row in mirrors if row.get("recall_verified_pool_exists"))
    selection_fresh_total = sum(1 for row in mirrors if row.get("selection_verified_fresh"))
    pool_exists_stale_total = sum(1 for row in mirrors if row.get("pool_exists_stale"))
    fresh_quote_candidate_total = sum(1 for row in mirrors if row.get("fresh_quote_candidate"))
    age_buckets = Counter(str(row.get("mirror_age_bucket") or "unknown") for row in mirrors)
    pool_universe_width = build_pool_universe_width(
        verified, mirrors, fresh_tokens=fresh_set
    )
    unsupported_backlog = build_unsupported_dex_backlog(mirrors, config=cfg)
    recall_run_id = _iso_now()
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
        "verify_rca_path": str(DEFAULT_VERIFY_RCA_PATH),
        "recall_verified_pool_exists_total": recall_exists_total,
        "pool_exists_stale_total": pool_exists_stale_total,
        "fresh_quote_candidate_total": fresh_quote_candidate_total,
        "selection_verified_fresh_total": selection_fresh_total,
        "supported_hints_verified": selection_fresh_total,
        "m9_target_ready": selection_fresh_total > 0,
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
        "primary_blocker": rca.get("primary_blocker"),
        "primary_blocker_selection": rca.get("primary_blocker_selection"),
        "stale_recall_bucket_histogram": rca.get("stale_recall_bucket_histogram"),
        "existence_rca_bucket_histogram": rca.get("existence_rca_bucket_histogram"),
        "pool_exists_stale_total": rca.get("pool_exists_stale_total"),
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
    quote_ready_hints = [h for h in hints if _hint_raw_bool(h, "selection_verified_fresh")]
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


def evaluate_selection_verified_fresh_gate(payload: Dict[str, Any]) -> Tuple[bool, str]:
    """Cross-dex expand and M8.3 require at least one selection-fresh verified mirror."""
    sel_fresh = int(payload.get("selection_verified_fresh_total") or 0)
    if sel_fresh > 0:
        return True, "selection_verified_fresh_ready"
    return False, "SELECTION_VERIFIED_FRESH_ZERO"


def evaluate_m9_admission_gate(payload: Dict[str, Any]) -> Tuple[bool, str]:
    """M9 opens only when selection fresh + quote-ready + capacity (checked downstream)."""
    sel_fresh = int(payload.get("selection_verified_fresh_total") or 0)
    if sel_fresh <= 0:
        return False, "SELECTION_VERIFIED_FRESH_ZERO"
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
    return {
        "route_id": f"{hint.focus_token}:{hint.pool_address}:{dex_id}",
        "dex_id": dex_id,
        "adapter_type": adapter,
        "pool_address": hint.pool_address,
        "pool_id": hint.pool_id,
        "token0_addr": hint.token0_addr,
        "token1_addr": hint.token1_addr,
        "focus_token": hint.focus_token,
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
    handoff = quote_ready if quote_ready else fresh_enough
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
        "mirrors_selected": len(handoff),
        "output_path": str(output_path),
        "m9_target_ready": len(handoff) > 0 and len(fresh_enough) > 0,
        "narrow_bridge_ready": len(fresh_enough) > 0,
        "stale_quote_smoke": stale_smoke,
        "selection_stages": {
            "recall": int(recall_payload.get("all_dex_mirrors_total") or 0),
            "pool_exists": len(pool_exists),
            "pool_exists_stale": len(pool_exists_stale),
            "fresh_enough": len(fresh_enough),
            "fresh_quote_candidate": len(fresh_quote_candidate),
            "quote_ready": len(quote_ready),
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
) -> Dict[str, Any]:
    tokens = _load_token_list(subset_path, max_tokens=max_tokens)
    _hints, payload = run_mirror_discovery_recall(
        tokens,
        dry_run=dry_run,
        use_cache=use_cache,
    )
    write_mirror_discovery_recall(payload, output_path=output_path)
    return payload
