"""M8.2 Radar Layer contract — external aggregators, hint-only.

Boundary (do not mix with M8 sniper):

    M8 sniper          = on-chain first-seen truth
    M8.1               = anchor / metadata / quote-probe context
    M8.2 Radar         = external aggregators, hint-only  (this module)
    M8.2 Verify/Expansion = on-chain truth + graph handoff
    M9                 = quote / depth / sizing / economics truth

Raw radar candidates live in ``m8_radar_pool_candidates_latest.json`` without
canonical claims. Verified hints flow to ``m8_external_pool_hints_latest.json``.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set

from m8.discovery.pool_hints import (
    BRIDGE_ELIGIBLE_HINT_STATUSES,
    PoolHint,
    dedupe_hints,
    verify_hint_onchain,
)

SCHEMA_VERSION = "m8_radar_pool_candidates.1"
DEFAULT_RADAR_PATH = "data/runs/_rolling/m8_radar_pool_candidates_latest.json"

RADAR_REASON_TOKEN_PAIR = "token_pair_seen"
RADAR_REASON_NEW_POOL = "new_pool_seen"
RADAR_REASON_LIQUIDITY = "liquidity_seen"
RADAR_REASONS = (
    RADAR_REASON_TOKEN_PAIR,
    RADAR_REASON_NEW_POOL,
    RADAR_REASON_LIQUIDITY,
)

# Hint-only radar sources (never canonical without on-chain verify).
RADAR_HINT_SOURCES = frozenset(
    {
        "dexscreener",
        "geckoterminal",
        "geckoterminal_new_pools",
        "thegraph",
        "thegraph_token_api",
        "coingecko_onchain",
        "coinmarketcap_dex",
        "dexpaprika",
        "moralis",
        "codex_defined",
    }
)


def _iso_now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _age_hours(created_at: Optional[str]) -> Optional[float]:
    if not created_at:
        return None
    try:
        ts = datetime.fromisoformat(str(created_at).replace("Z", "+00:00"))
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return (datetime.now(tz=timezone.utc) - ts).total_seconds() / 3600.0
    except (ValueError, TypeError):
        return None


def classify_radar_reason(
    hint: PoolHint,
    *,
    new_pool_hours: float = 48.0,
    liquidity_usd_min: float = 1000.0,
    volume_24h_min: float = 100.0,
) -> str:
    """Assign per-hint radar_reason for DexScreener / GeckoTerminal / CoinGecko."""
    raw = hint.raw or {}
    if raw.get("backfill_mode") == "new_pools" or raw.get("discovery") == "new_pools":
        return RADAR_REASON_NEW_POOL
    age_h = _age_hours(hint.created_at)
    if age_h is not None and age_h <= new_pool_hours:
        return RADAR_REASON_NEW_POOL
    if (hint.liquidity_usd or 0) >= liquidity_usd_min or (
        hint.volume_24h or 0
    ) >= volume_24h_min:
        return RADAR_REASON_LIQUIDITY
    return RADAR_REASON_TOKEN_PAIR


def stamp_radar_reason(hint: PoolHint, **kwargs: Any) -> PoolHint:
    hint.radar_reason = classify_radar_reason(hint, **kwargs)
    return hint


def build_radar_candidates_artifact(
    *,
    chain: str,
    sources: List[str],
    hints: List[PoolHint],
    metrics: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Raw external candidates — no canonical / bridge claims."""
    deduped = dedupe_hints(hints)
    reason_counts: Dict[str, int] = {}
    source_counts: Dict[str, int] = {}
    for h in deduped:
        reason = h.radar_reason or classify_radar_reason(h)
        reason_counts[reason] = int(reason_counts.get(reason, 0)) + 1
        source_counts[h.source] = int(source_counts.get(h.source, 0)) + 1
    m = {
        "candidates_total": len(deduped),
        "radar_reason_counts": reason_counts,
        "hint_source_pool_counts": source_counts,
        "truth_boundary": "HINT_ONLY_NO_CANONICAL",
        "layer": "M8.2_radar",
    }
    if metrics:
        m.update(metrics)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at_utc": _iso_now(),
        "chain": chain,
        "sources": list(sources),
        "metrics": m,
        "candidates": [h.to_dict() for h in deduped],
    }


def write_radar_candidates_artifact(
    artifact: Dict[str, Any],
    path: str = DEFAULT_RADAR_PATH,
) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    artifact["schema_version"] = SCHEMA_VERSION
    artifact["generated_at_utc"] = _iso_now()
    p.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def run_radar_verify_pipeline(
    hints: Iterable[PoolHint],
    *,
    chain: str,
    verify_mode: str = "specialized",
    allowed_dex_ids: Optional[Set[str]] = None,
    metrics: Optional[Dict[str, Any]] = None,
) -> List[PoolHint]:
    """PoolHint → dedupe → specialized on-chain verify (quote smoke in expansion)."""
    from m8.discovery.hint_verifier import empty_verification_metrics

    m = metrics if metrics is not None else empty_verification_metrics()
    out: List[PoolHint] = []
    for h in hints:
        if not h.radar_reason:
            stamp_radar_reason(h)
        verified = verify_hint_onchain(
            h,
            chain=chain,
            allowed_dex_ids=allowed_dex_ids,
            verify_mode=verify_mode,
            metrics=m,
        )
        out.append(verified)
    return dedupe_hints(out)


def build_radar_funnel(
    *,
    radar: Optional[Dict[str, Any]] = None,
    hints: Optional[Dict[str, Any]] = None,
    expansion: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Funnel split: radar_seen → onchain_verified → bridge_eligible → m9_handoff."""
    radar_m = (radar or {}).get("metrics") or {}
    hint_m = (hints or {}).get("metrics") or {}
    exp_summary = (expansion or {}).get("summary") or {}

    radar_seen = int(
        radar_m.get("candidates_total")
        or len((radar or {}).get("candidates") or [])
        or hint_m.get("hint_pools_seen")
        or 0
    )
    onchain_verified = int(
        hint_m.get("verified_second_pool_count")
        or exp_summary.get("verified_second_pool_count")
        or 0
    )
    bridge_eligible = int(
        exp_summary.get("canonical_routes_count")
        or exp_summary.get("routes_admitted_count")
        or len((expansion or {}).get("routes_admitted") or [])
        or 0
    )
    m9_handoff = {
        "handoff_ready": bool(exp_summary.get("handoff_ready")),
        "handoff_lane": exp_summary.get("handoff_lane"),
        "graph_handoff_cycle_potential_routes": int(
            exp_summary.get("graph_handoff_cycle_potential_routes") or 0
        ),
        "routes_admitted_count": bridge_eligible,
        "requires_m9_quote": True,
        "economics_claim": False,
    }
    verified_yield = dict(hint_m.get("per_source_verified_yield") or {})
    return {
        "radar_seen": radar_seen,
        "onchain_verified": onchain_verified,
        "bridge_eligible": bridge_eligible,
        "m9_handoff": m9_handoff,
        "per_source_verified_yield": verified_yield,
        "radar_to_verified_rate": round(
            onchain_verified / radar_seen, 4
        )
        if radar_seen
        else 0.0,
        "truth_boundary": "ONCHAIN_VERIFY_REQUIRED",
    }
