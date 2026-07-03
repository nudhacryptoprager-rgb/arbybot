"""Stale-aware on-chain checks for mirror recall (separate from M9 selection)."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from m8.discovery.hint_verifier import (
    VERIFY_BYTECODE,
    VERIFY_FACTORY_GET_POOL,
    is_bytes32_hex,
    record_verification_metrics,
    resolve_pool_id,
    verify_factory_pool,
    verify_v4_pool_id_exists,
)
from m8.discovery.pool_hints import (
    BRIDGE_ELIGIBLE_HINT_STATUSES,
    HINT_DEX_UNSUPPORTED,
    HINT_ONLY,
    HINT_STALE,
    RECALL_HOT_STALE_HOURS,
    PoolHint,
    hint_is_stale_for_recall,
    normalize_pool_identity,
    verify_hint_onchain,
)

RECALL_STATUS_POOL_EXISTS = "recall_verified_pool_exists"
RECALL_STATUS_POOL_NOT_FOUND = "recall_pool_not_found"
SELECTION_STATUS_FRESH = "selection_verified_fresh"
SELECTION_STATUS_BLOCKED_STALE = "selection_blocked_stale"
SELECTION_STATUS_BLOCKED_VERIFY = "selection_blocked_verify"

STALE_BUT_POOL_EXISTS = "STALE_BUT_POOL_EXISTS"
STALE_POOL_NOT_FOUND = "STALE_POOL_NOT_FOUND"
STALE_TOKEN_MISMATCH = "STALE_TOKEN_MISMATCH"
STALE_UNSUPPORTED_DEX = "STALE_UNSUPPORTED_DEX"

V4_POOLID_NOT_RESOLVED = "V4_POOLID_NOT_RESOLVED"
FACTORY_MEMBERSHIP_FAIL = "FACTORY_MEMBERSHIP_FAIL"
POOL_CODE_MISSING = "POOL_CODE_MISSING"
TOKEN_PAIR_MISMATCH = "TOKEN_PAIR_MISMATCH"
UNSUPPORTED_OR_MISLABELED_AERODROME_POOL = "UNSUPPORTED_OR_MISLABELED_AERODROME_POOL"

_FACTORY_DEX_IDS: Set[str] = frozenset(
    {
        "uniswap_v2",
        "uniswap_v3",
        "pancakeswap_v3",
        "sushiswap_v3",
        "sushiswap_v2",
        "baseswap_v2",
    }
)
_AERODROME_DEX_IDS: Set[str] = frozenset(
    {
        "aerodrome",
        "aerodrome_slipstream",
        "aerodrome_v2_stable",
    }
)
_V4_FAILURE_TO_BUCKET = {
    "V4_INVALID_POOL_ID": V4_POOLID_NOT_RESOLVED,
    "V4_SLOT0_EMPTY": V4_POOLID_NOT_RESOLVED,
    "V4_LIQUIDITY_CALL_FAILED": V4_POOLID_NOT_RESOLVED,
    "V4_LIQUIDITY_DECODE_FAILED": V4_POOLID_NOT_RESOLVED,
    "V4_ZERO_LIQUIDITY": V4_POOLID_NOT_RESOLVED,
    "RPC_UNAVAILABLE": V4_POOLID_NOT_RESOLVED,
}


def mirror_age_bucket(hint: PoolHint, *, now: Optional[datetime] = None) -> str:
    """Bucket pair age from created_at: <1h, 1-6h, 6-24h, 1-7d, >7d, unknown."""
    if not hint.created_at:
        return "unknown"
    try:
        ts = datetime.fromisoformat(hint.created_at.replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        ref = now or datetime.now(tz=timezone.utc)
        age_h = max(0.0, (ref - ts).total_seconds() / 3600.0)
    except (ValueError, TypeError):
        return "unknown"
    if age_h < 1:
        return "<1h"
    if age_h < 6:
        return "1-6h"
    if age_h < 24:
        return "6-24h"
    if age_h < 168:
        return "1-7d"
    return ">7d"


def _annotate_recall_fields(
    hint: PoolHint,
    *,
    recall_exists: bool,
    selection_fresh: bool,
    stale_bucket: Optional[str] = None,
    existence_bucket: Optional[str] = None,
    verify_reject_reason: Optional[str] = None,
    pool_exists_stale: bool = False,
    fresh_quote_candidate: bool = False,
    max_age_hours: float = RECALL_HOT_STALE_HOURS,
) -> PoolHint:
    raw = dict(hint.raw or {})
    raw["mirror_age_bucket"] = mirror_age_bucket(hint)
    raw["is_stale_hint"] = hint_is_stale_for_recall(hint, max_age_hours=max_age_hours)
    raw["recall_verified_pool_exists"] = bool(recall_exists)
    raw["selection_verified_fresh"] = bool(selection_fresh)
    raw["pool_exists_stale"] = bool(pool_exists_stale)
    raw["fresh_quote_candidate"] = bool(fresh_quote_candidate)
    raw["recall_verification_status"] = (
        RECALL_STATUS_POOL_EXISTS if recall_exists else RECALL_STATUS_POOL_NOT_FOUND
    )
    if selection_fresh:
        raw["selection_verification_status"] = SELECTION_STATUS_FRESH
    elif raw["is_stale_hint"]:
        raw["selection_verification_status"] = SELECTION_STATUS_BLOCKED_STALE
    else:
        raw["selection_verification_status"] = SELECTION_STATUS_BLOCKED_VERIFY
    if stale_bucket:
        raw["stale_recall_bucket"] = stale_bucket
    if existence_bucket:
        raw["existence_rca_bucket"] = existence_bucket
    if verify_reject_reason:
        raw["verify_reject_reason"] = verify_reject_reason
    hint.raw = raw
    return hint


def _pool_bytecode_len(hint: PoolHint, *, chain: str) -> int:
    from m8.discovery.hint_verifier import _eth_get_code, _rpc_url

    addr = (hint.pool_address or "").lower()
    if not addr.startswith("0x") or len(addr) != 42:
        return 0
    url = _rpc_url(chain, None)
    if not url:
        return 0
    code = _eth_get_code(url, addr)
    if not code:
        return 0
    hex_part = code[2:] if code.startswith("0x") else code
    return len(hex_part) // 2


def _pool_has_bytecode(hint: PoolHint, *, chain: str) -> bool:
    return _pool_bytecode_len(hint, chain=chain) > 0


def _stale_verify_v4(
    hint: PoolHint,
    *,
    chain: str,
    metrics: Optional[Dict[str, Any]],
) -> Tuple[PoolHint, str]:
    from m8.discovery.uniswap_v4_pool_resolver import (
        V4_POOLID_EXISTS,
        V4_POOLID_NOT_RESOLVED,
        resolve_v4_pool_existence,
    )

    h = hint
    ok, bucket, detail = resolve_v4_pool_existence(h, chain=chain)
    if metrics is not None:
        record_verification_metrics(
            metrics,
            h,
            verified=ok,
            reject_reason=STALE_BUT_POOL_EXISTS if ok else (detail or bucket),
        )
    if ok:
        if is_bytes32_hex(resolve_pool_id(h) or h.pool_address):
            h.pool_id = resolve_pool_id(h) or h.pool_address
        h.verify_method = detail
        h.hint_status = HINT_STALE
        return _annotate_recall_fields(
            h,
            recall_exists=True,
            selection_fresh=False,
            stale_bucket=STALE_BUT_POOL_EXISTS,
            existence_bucket=bucket,
            pool_exists_stale=True,
        ), STALE_BUT_POOL_EXISTS

    return _annotate_recall_fields(
        h,
        recall_exists=False,
        selection_fresh=False,
        stale_bucket=STALE_POOL_NOT_FOUND,
        existence_bucket=V4_POOLID_NOT_RESOLVED,
        verify_reject_reason=detail or bucket,
    ), V4_POOLID_NOT_RESOLVED


def _stale_verify_factory_membership(
    hint: PoolHint,
    *,
    chain: str,
    metrics: Optional[Dict[str, Any]],
) -> Tuple[PoolHint, str]:
    h = hint
    ok, method = verify_factory_pool(h, chain=chain)
    if ok:
        h.verify_method = method or VERIFY_FACTORY_GET_POOL
        h.hint_status = HINT_STALE
        if metrics is not None:
            record_verification_metrics(
                metrics, h, verified=True, reject_reason=STALE_BUT_POOL_EXISTS
            )
        return _annotate_recall_fields(
            h,
            recall_exists=True,
            selection_fresh=False,
            stale_bucket=STALE_BUT_POOL_EXISTS,
            existence_bucket=STALE_BUT_POOL_EXISTS,
            pool_exists_stale=True,
        ), STALE_BUT_POOL_EXISTS

    if method == "FACTORY_NO_POOL" and str(h.dex_id or "") == "aerodrome":
        from m8.discovery.hint_verifier import _try_aerodrome_slipstream_fallback

        slip_ok, slip_factory, slip_fee = _try_aerodrome_slipstream_fallback(
            h, chain=chain
        )
        if slip_ok:
            h.dex_id = "aerodrome_slipstream"
            h.fee = slip_fee
            h.factory_address = slip_factory
            h.verify_method = VERIFY_FACTORY_GET_POOL
            h.hint_status = HINT_STALE
            raw = dict(h.raw or {})
            raw["aerodrome_variant_fallback"] = "ve33_to_slipstream"
            h.raw = raw
            if metrics is not None:
                record_verification_metrics(
                    metrics, h, verified=True, reject_reason=STALE_BUT_POOL_EXISTS
                )
            return _annotate_recall_fields(
                h,
                recall_exists=True,
                selection_fresh=False,
                stale_bucket=STALE_BUT_POOL_EXISTS,
                existence_bucket=STALE_BUT_POOL_EXISTS,
                pool_exists_stale=True,
            ), STALE_BUT_POOL_EXISTS

    if method == "FACTORY_MISSING_TOKENS":
        bucket = TOKEN_PAIR_MISMATCH
    elif str(h.dex_id or "") == "aerodrome" and method == "FACTORY_NO_POOL":
        bytecode_len = _pool_bytecode_len(h, chain=chain)
        if bytecode_len > 0:
            bucket = UNSUPPORTED_OR_MISLABELED_AERODROME_POOL
            raw = dict(h.raw or {})
            raw["aerodrome_bytecode_len"] = bytecode_len
            raw["aerodrome_factory_address"] = str(h.factory_address or "")
            h.raw = raw
            if metrics is not None:
                record_verification_metrics(
                    metrics, h, verified=False, reject_reason=bucket
                )
            return _annotate_recall_fields(
                h,
                recall_exists=False,
                selection_fresh=False,
                stale_bucket=STALE_POOL_NOT_FOUND,
                existence_bucket=bucket,
                verify_reject_reason=bucket,
            ), bucket
        bucket = FACTORY_MEMBERSHIP_FAIL
    elif _pool_has_bytecode(h, chain=chain):
        h.verify_method = VERIFY_BYTECODE
        h.hint_status = HINT_STALE
        if metrics is not None:
            record_verification_metrics(
                metrics, h, verified=True, reject_reason=STALE_BUT_POOL_EXISTS
            )
        return _annotate_recall_fields(
            h,
            recall_exists=True,
            selection_fresh=False,
            stale_bucket=STALE_BUT_POOL_EXISTS,
            existence_bucket=STALE_BUT_POOL_EXISTS,
            pool_exists_stale=True,
        ), STALE_BUT_POOL_EXISTS

    bucket = POOL_CODE_MISSING if method in ("BYTECODE_EMPTY",) else FACTORY_MEMBERSHIP_FAIL
    if metrics is not None:
        record_verification_metrics(metrics, h, verified=False, reject_reason=method)
    return _annotate_recall_fields(
        h,
        recall_exists=False,
        selection_fresh=False,
        stale_bucket=STALE_POOL_NOT_FOUND,
        existence_bucket=bucket,
        verify_reject_reason=method,
    ), bucket


def _classify_stale_existence(
    hint: PoolHint,
    *,
    chain: str,
    metrics: Optional[Dict[str, Any]],
) -> Tuple[PoolHint, str]:
    """On-chain existence for stale hints; never upgrades to selection-fresh."""
    h = normalize_pool_identity(PoolHint.from_dict(hint.to_dict()))
    if os.environ.get("ARBY_SKIP_RPC") == "1":
        return _annotate_recall_fields(
            h,
            recall_exists=False,
            selection_fresh=False,
            stale_bucket=STALE_POOL_NOT_FOUND,
            existence_bucket=POOL_CODE_MISSING,
            verify_reject_reason=STALE_POOL_NOT_FOUND,
        ), STALE_POOL_NOT_FOUND

    dex = str(h.dex_id or "")
    pool_id = resolve_pool_id(h)

    if dex == "uniswap_v4" or pool_id:
        return _stale_verify_v4(h, chain=chain, metrics=metrics)

    if dex in _AERODROME_DEX_IDS or dex in _FACTORY_DEX_IDS:
        return _stale_verify_factory_membership(h, chain=chain, metrics=metrics)

    if dex and dex not in _FACTORY_DEX_IDS.union(_AERODROME_DEX_IDS):
        if _pool_has_bytecode(h, chain=chain):
            h.verify_method = VERIFY_BYTECODE
            h.hint_status = HINT_STALE
            return _annotate_recall_fields(
                h,
                recall_exists=True,
                selection_fresh=False,
                stale_bucket=STALE_BUT_POOL_EXISTS,
                existence_bucket=STALE_BUT_POOL_EXISTS,
                pool_exists_stale=True,
            ), STALE_BUT_POOL_EXISTS
        return _annotate_recall_fields(
            h,
            recall_exists=False,
            selection_fresh=False,
            stale_bucket=STALE_UNSUPPORTED_DEX,
            existence_bucket=STALE_UNSUPPORTED_DEX,
        ), STALE_UNSUPPORTED_DEX

    if _pool_has_bytecode(h, chain=chain):
        h.verify_method = VERIFY_BYTECODE
        h.hint_status = HINT_STALE
        return _annotate_recall_fields(
            h,
            recall_exists=True,
            selection_fresh=False,
            stale_bucket=STALE_BUT_POOL_EXISTS,
            existence_bucket=STALE_BUT_POOL_EXISTS,
            pool_exists_stale=True,
        ), STALE_BUT_POOL_EXISTS

    return _annotate_recall_fields(
        h,
        recall_exists=False,
        selection_fresh=False,
        stale_bucket=STALE_POOL_NOT_FOUND,
        existence_bucket=POOL_CODE_MISSING,
        verify_reject_reason="BYTECODE_EMPTY",
    ), POOL_CODE_MISSING


def verify_hint_for_recall(
    hint: PoolHint,
    *,
    chain: str,
    metrics: Optional[Dict[str, Any]] = None,
    dry_run: bool = False,
    max_age_hours: float = RECALL_HOT_STALE_HOURS,
) -> PoolHint:
    """Recall-layer verify: stale hints may count as pool_exists but not selection-fresh."""
    h = normalize_pool_identity(PoolHint.from_dict(hint.to_dict()))
    stale = hint_is_stale_for_recall(h, max_age_hours=max_age_hours)

    if dry_run or os.environ.get("ARBY_SKIP_RPC") == "1":
        recall_exists = h.hint_status in BRIDGE_ELIGIBLE_HINT_STATUSES
        return _annotate_recall_fields(
            h,
            recall_exists=recall_exists,
            selection_fresh=recall_exists and not stale,
            fresh_quote_candidate=recall_exists and not stale,
            max_age_hours=max_age_hours,
        )

    if not stale:
        verified = verify_hint_onchain(h, chain=chain, metrics=metrics)
        bridge_ok = verified.hint_status in BRIDGE_ELIGIBLE_HINT_STATUSES
        return _annotate_recall_fields(
            verified,
            recall_exists=bridge_ok,
            selection_fresh=bridge_ok,
            fresh_quote_candidate=bridge_ok,
            verify_reject_reason=(
                None if bridge_ok else str(verified.hint_status or HINT_ONLY)
            ),
            max_age_hours=max_age_hours,
        )

    verified, _bucket = _classify_stale_existence(h, chain=chain, metrics=metrics)
    return verified


def verify_hints_for_recall(
    hints: List[PoolHint],
    *,
    chain: str = "base",
    dry_run: bool = False,
    max_age_hours: float = RECALL_HOT_STALE_HOURS,
) -> Tuple[List[PoolHint], Dict[str, Any], List[Dict[str, Any]]]:
    from m8.discovery.hint_verifier import empty_verification_metrics

    metrics = empty_verification_metrics()
    out: List[PoolHint] = []
    stale_buckets: Dict[str, int] = {}
    existence_buckets: Dict[str, int] = {}
    factory_no_pool_by_dex: Dict[str, int] = {}
    factory_no_pool_by_factory: Dict[str, int] = {}
    factory_no_pool_samples: List[Dict[str, Any]] = []
    dex_null_age_hist: Dict[str, int] = {}
    aero_variant_fallback_hist: Dict[str, int] = {}
    unsupported_aerodrome_pool_hist: Dict[str, int] = {}
    unsupported_aerodrome_pool_samples: List[Dict[str, Any]] = []
    reject_rows: List[Dict[str, Any]] = []

    for h in hints:
        verified = verify_hint_for_recall(
            h,
            chain=chain,
            metrics=metrics,
            dry_run=dry_run,
            max_age_hours=max_age_hours,
        )
        raw = verified.raw or {}
        if raw.get("is_stale_hint"):
            bucket = str(raw.get("stale_recall_bucket") or STALE_POOL_NOT_FOUND)
            stale_buckets[bucket] = int(stale_buckets.get(bucket, 0)) + 1
        ex_bucket = raw.get("existence_rca_bucket")
        if ex_bucket:
            existence_buckets[str(ex_bucket)] = int(existence_buckets.get(str(ex_bucket), 0)) + 1

        aero_fb = raw.get("aerodrome_variant_fallback")
        if aero_fb:
            aero_variant_fallback_hist[str(aero_fb)] = int(aero_variant_fallback_hist.get(str(aero_fb), 0)) + 1

        if raw.get("existence_rca_bucket") == UNSUPPORTED_OR_MISLABELED_AERODROME_POOL:
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

        if reason_str == "FACTORY_NO_POOL":
            dex_key = str(verified.dex_id or "unknown")
            fac_key = str(verified.factory_address or (raw.get("factory_address") or "unknown"))
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

        if not raw.get("selection_verified_fresh"):
            reject_rows.append(
                {
                    "token": str(verified.focus_token or "").lower(),
                    "pool": str(verified.pool_address or "").lower(),
                    "dex_id": str(verified.dex_id or ""),
                    "token0_addr": str(verified.token0_addr or "").lower(),
                    "token1_addr": str(verified.token1_addr or "").lower(),
                    "hint_status": verified.hint_status,
                    "verify_reject_reason": reason_str,
                    "stale_recall_bucket": raw.get("stale_recall_bucket"),
                    "existence_rca_bucket": raw.get("existence_rca_bucket"),
                    "recall_verified_pool_exists": raw.get("recall_verified_pool_exists"),
                    "selection_verified_fresh": raw.get("selection_verified_fresh"),
                    "pool_exists_stale": raw.get("pool_exists_stale"),
                    "mirror_age_bucket": raw.get("mirror_age_bucket"),
                    "created_at_source": raw.get("created_at_source"),
                }
            )
        out.append(verified)

    metrics["stale_recall_bucket_histogram"] = stale_buckets
    metrics["existence_rca_bucket_histogram"] = existence_buckets
    metrics["factory_no_pool_by_dex"] = factory_no_pool_by_dex
    metrics["factory_no_pool_by_factory"] = factory_no_pool_by_factory
    metrics["factory_no_pool_samples"] = factory_no_pool_samples
    metrics["dex_null_age_histogram"] = dex_null_age_hist
    metrics["aerodrome_variant_fallback_histogram"] = aero_variant_fallback_hist
    metrics["unsupported_aerodrome_pool_histogram"] = unsupported_aerodrome_pool_hist
    metrics["unsupported_aerodrome_pool_samples"] = unsupported_aerodrome_pool_samples
    return out, metrics, reject_rows
