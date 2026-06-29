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
    PoolHint,
    hint_is_stale,
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
) -> PoolHint:
    raw = dict(hint.raw or {})
    raw["mirror_age_bucket"] = mirror_age_bucket(hint)
    raw["is_stale_hint"] = hint_is_stale(hint)
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


def _pool_has_bytecode(hint: PoolHint, *, chain: str) -> bool:
    from m8.discovery.hint_verifier import _eth_get_code, _rpc_url

    addr = (hint.pool_address or "").lower()
    if not addr.startswith("0x") or len(addr) != 42:
        return False
    url = _rpc_url(chain, None)
    return bool(url and _eth_get_code(url, addr))


def _stale_verify_v4(
    hint: PoolHint,
    *,
    chain: str,
    metrics: Optional[Dict[str, Any]],
) -> Tuple[PoolHint, str]:
    h = hint
    pool_id = resolve_pool_id(h) or h.pool_address
    if not is_bytes32_hex(pool_id):
        bucket = V4_POOLID_NOT_RESOLVED
        return _annotate_recall_fields(
            h,
            recall_exists=False,
            selection_fresh=False,
            stale_bucket=STALE_POOL_NOT_FOUND,
            existence_bucket=bucket,
            verify_reject_reason="V4_INVALID_POOL_ID",
        ), bucket

    ok, method = verify_v4_pool_id_exists(pool_id, chain=chain)
    if metrics is not None:
        record_verification_metrics(
            metrics,
            h,
            verified=ok,
            reject_reason=STALE_BUT_POOL_EXISTS if ok else method,
        )
    if ok:
        h.pool_id = pool_id
        h.verify_method = method
        h.hint_status = HINT_STALE
        return _annotate_recall_fields(
            h,
            recall_exists=True,
            selection_fresh=False,
            stale_bucket=STALE_BUT_POOL_EXISTS,
            existence_bucket=STALE_BUT_POOL_EXISTS,
            pool_exists_stale=True,
        ), STALE_BUT_POOL_EXISTS

    bucket = _V4_FAILURE_TO_BUCKET.get(method, V4_POOLID_NOT_RESOLVED)
    return _annotate_recall_fields(
        h,
        recall_exists=False,
        selection_fresh=False,
        stale_bucket=STALE_POOL_NOT_FOUND,
        existence_bucket=bucket,
        verify_reject_reason=method,
    ), bucket


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

    if method == "FACTORY_MISSING_TOKENS":
        bucket = TOKEN_PAIR_MISMATCH
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

    bucket = POOL_CODE_MISSING if method == "BYTECODE_EMPTY" else FACTORY_MEMBERSHIP_FAIL
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
) -> PoolHint:
    """Recall-layer verify: stale hints may count as pool_exists but not selection-fresh."""
    h = normalize_pool_identity(PoolHint.from_dict(hint.to_dict()))
    stale = hint_is_stale(h)

    if dry_run or os.environ.get("ARBY_SKIP_RPC") == "1":
        recall_exists = h.hint_status in BRIDGE_ELIGIBLE_HINT_STATUSES
        return _annotate_recall_fields(
            h,
            recall_exists=recall_exists,
            selection_fresh=recall_exists and not stale,
            fresh_quote_candidate=recall_exists and not stale,
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
        )

    verified, _bucket = _classify_stale_existence(h, chain=chain, metrics=metrics)
    return verified


def verify_hints_for_recall(
    hints: List[PoolHint],
    *,
    chain: str = "base",
    dry_run: bool = False,
) -> Tuple[List[PoolHint], Dict[str, Any], List[Dict[str, Any]]]:
    from m8.discovery.hint_verifier import empty_verification_metrics

    metrics = empty_verification_metrics()
    out: List[PoolHint] = []
    stale_buckets: Dict[str, int] = {}
    existence_buckets: Dict[str, int] = {}
    reject_rows: List[Dict[str, Any]] = []

    for h in hints:
        verified = verify_hint_for_recall(h, chain=chain, metrics=metrics, dry_run=dry_run)
        raw = verified.raw or {}
        if raw.get("is_stale_hint"):
            bucket = str(raw.get("stale_recall_bucket") or STALE_POOL_NOT_FOUND)
            stale_buckets[bucket] = int(stale_buckets.get(bucket, 0)) + 1
        ex_bucket = raw.get("existence_rca_bucket")
        if ex_bucket:
            existence_buckets[str(ex_bucket)] = int(existence_buckets.get(str(ex_bucket), 0)) + 1
        if not raw.get("selection_verified_fresh"):
            reason = str(
                raw.get("verify_reject_reason")
                or raw.get("existence_rca_bucket")
                or raw.get("stale_recall_bucket")
                or verified.hint_status
            )
            reject_rows.append(
                {
                    "token": str(verified.focus_token or "").lower(),
                    "pool": str(verified.pool_address or "").lower(),
                    "dex_id": str(verified.dex_id or ""),
                    "hint_status": verified.hint_status,
                    "verify_reject_reason": reason,
                    "stale_recall_bucket": raw.get("stale_recall_bucket"),
                    "existence_rca_bucket": raw.get("existence_rca_bucket"),
                    "recall_verified_pool_exists": raw.get("recall_verified_pool_exists"),
                    "selection_verified_fresh": raw.get("selection_verified_fresh"),
                    "pool_exists_stale": raw.get("pool_exists_stale"),
                    "mirror_age_bucket": raw.get("mirror_age_bucket"),
                }
            )
        out.append(verified)

    metrics["stale_recall_bucket_histogram"] = stale_buckets
    metrics["existence_rca_bucket_histogram"] = existence_buckets
    return out, metrics, reject_rows
