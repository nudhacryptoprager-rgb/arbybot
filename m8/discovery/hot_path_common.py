"""Shared helpers for M8 hot-path batch and live WS runners."""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, List


def build_reject_reason_histogram(candidates: List[Dict[str, Any]]) -> Dict[str, int]:
    """Count reject_reason values across candidate rows."""
    counts: Counter[str] = Counter()
    for row in candidates:
        reason = row.get("reject_reason")
        if reason:
            counts[str(reason)] += 1
        elif (row.get("routes_admitted_count") or 0) >= 2 and row.get("cross_mechanic"):
            counts["OK_CROSS_MECHANIC"] += 1
        elif (row.get("routes_admitted_count") or 0) >= 2:
            counts["OK_MIRROR_ONLY"] += 1
        else:
            counts["OK_OR_PENDING"] += 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def merge_per_dex_breakdown(candidates: List[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    """Merge per-dex expansion metrics from hot-path mirror resolve rows."""
    keys = (
        "pending_by_dex",
        "no_pool_by_dex",
        "resolved_by_dex",
        "quote_smoke_by_dex",
    )
    merged: Dict[str, Dict[str, int]] = {k: {} for k in keys}
    for row in candidates:
        summary = row.get("summary") or {}
        for key in keys:
            hist = summary.get(key) or {}
            if not isinstance(hist, dict):
                continue
            for dex, count in hist.items():
                merged[key][str(dex)] = merged[key].get(str(dex), 0) + int(count or 0)
    return {k: dict(sorted(v.items())) for k, v in merged.items()}


def merge_expansion_reject_histogram(candidates: List[Dict[str, Any]]) -> Dict[str, int]:
    """Aggregate M8.2 reject_reason_histogram from mirror resolve rows."""
    merged: Counter[str] = Counter()
    for row in candidates:
        hist = row.get("reject_reason_histogram") or {}
        if isinstance(hist, dict):
            for k, v in hist.items():
                merged[str(k)] += int(v or 0)
    return dict(sorted(merged.items(), key=lambda kv: (-kv[1], kv[0])))


def honeypot_evidence_policy(*, strict_requested: bool) -> Dict[str, Any]:
    """Document whether strict positive-gross evidence can succeed."""
    from monitoring.sniper_honeypot import probe_transfer_tax_sell_side

    probe_sample = probe_transfer_tax_sell_side(
        "0x1234567890123456789012345678901234567890"
    )
    probe_is_stub = probe_sample.value == "UNKNOWN"
    strict_possible = not probe_is_stub
    return {
        "strict_positive_evidence_requested": strict_requested,
        "strict_positive_evidence_possible": strict_possible,
        "probe_transfer_tax_status": "STUB" if probe_is_stub else "ACTIVE",
        "profit_evidence_note": (
            "Strict profit claims blocked: sell-side/tax probe not wired (UNKNOWN only)."
            if probe_is_stub and strict_requested
            else None
        ),
    }


def setup_quote_rpc(chain: str) -> tuple[Any, str, str]:
    """Resolve productive HTTP RPC and return (w3, url, provider_label)."""
    from core.rpc_urls import resolve_rpc_http
    from web3 import Web3

    rpc_url, provider, _diag = resolve_rpc_http(network=chain)
    if not rpc_url:
        raise RuntimeError(f"No HTTP RPC for chain={chain}")
    w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 15}))
    return w3, rpc_url, str(provider or "unknown")
