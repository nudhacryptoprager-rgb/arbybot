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


def bridge_shadow_acceptance_from_candidates(
    candidates: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Derive M9 bridge-shadow acceptance from best eligible token-neighborhood subgraph."""
    from m8.discovery.token_classify import bridge_shadow_lane_eligible

    best_summary: Dict[str, Any] = {}
    best_row: Dict[str, Any] = {}
    best_routes = -1
    for row in candidates:
        if row.get("bridge_shadow_lane_eligible") is False:
            continue
        summary = row.get("summary") or {}
        n = int(summary.get("routes_admitted_count") or row.get("routes_admitted_count") or 0)
        if n > best_routes:
            best_routes = n
            best_summary = summary
            best_row = row

    if best_routes < 0:
        for row in candidates:
            summary = row.get("summary") or {}
            n = int(summary.get("routes_admitted_count") or row.get("routes_admitted_count") or 0)
            if n > best_routes:
                best_routes = n
                best_summary = summary
                best_row = row

    token_seen = int(best_summary.get("token_seen_on_dexes", 0))
    connectors = int(
        best_summary.get("connector_token_count")
        or len(best_summary.get("connector_tokens") or [])
        or 0
    )
    routes = int(best_summary.get("routes_admitted_count", best_routes))
    unique = int(best_summary.get("unique_tokens", 0))
    token_class = str(best_row.get("token_class") or "")
    mechanic_pair = str(best_row.get("mechanic_pair") or "")
    cross = bool(best_row.get("cross_mechanic"))
    lane_eligible = bridge_shadow_lane_eligible(
        token_class=token_class or "unknown_unclassified",
        mechanic_pair=mechanic_pair or "unknown_mechanic",
        connector_tokens=connectors,
        cross_mechanic=cross,
    )
    topology_ready = bool(
        token_seen >= 2
        and connectors >= 1
        and routes >= 4
        and unique >= 3
    )
    routes_list = list(best_row.get("routes_admitted") or [])
    from m8.discovery.distinct_pricing_lane import merge_distinct_pricing_into_acceptance

    base = {
        "token_seen_on_dexes_gte_2": token_seen >= 2,
        "connector_tokens_gte_1": connectors >= 1,
        "active_routes_gte_4": routes >= 4,
        "unique_tokens_gte_3": unique >= 3,
        "subgraph_ready": topology_ready,
        "bridge_shadow_lane_eligible": lane_eligible,
        "ready_for_bridge_shadow": topology_ready and lane_eligible,
        "token_seen_on_dexes": token_seen,
        "connector_tokens": connectors,
        "active_routes": routes,
        "unique_tokens": unique,
        "best_token_class": token_class or None,
        "best_mechanic_pair": mechanic_pair or None,
    }
    return merge_distinct_pricing_into_acceptance(base, routes=routes_list)


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
    from core.env import load_root_dotenv
    from core.rpc_urls import apply_productive_rpc_env, classify_provider, resolve_productive_http_rpc
    from web3 import Web3

    load_root_dotenv()
    try:
        env = apply_productive_rpc_env(chain)
    except RuntimeError:
        import os

        env = os.environ
    rpc_url = resolve_productive_http_rpc(chain, env=env)
    if not rpc_url:
        raise RuntimeError(f"No HTTP RPC for chain={chain}")
    provider = classify_provider(rpc_url)
    w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 15}))
    return w3, rpc_url, str(provider or "unknown")
