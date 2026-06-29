"""Score radar tokens for narrow on-chain verify (time-to-mirror hot path)."""
from __future__ import annotations

import time
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from m8.discovery.radar_fast_pipeline import (
    RADAR_REASON_LIQUIDITY,
    RADAR_REASON_NEW_POOL,
    PoolHint,
    dex_count,
    hints_by_token,
)

_DEFAULT_VERIFY_SCORE_MIN = 20.0

# Canonical disposition buckets for verify-budget diagnostics.
DISPOSITION_SELECTED_FOR_VERIFY = "SELECTED_FOR_VERIFY"
DISPOSITION_DROPPED_TO_WARM = "DROPPED_TO_WARM"
DISPOSITION_NO_RADAR_POOL = "NO_RADAR_POOL"
DISPOSITION_STALE_HINT = "STALE_HINT"
DISPOSITION_DEX_UNSUPPORTED = "DEX_UNSUPPORTED"
DISPOSITION_LOW_LIQUIDITY_HINT = "LOW_LIQUIDITY_HINT"


_ONCHAIN_PRIMARY_SOURCES = frozenset({"onchain_factory", "factory_log"})


def classify_verify_disposition(
    token: str,
    hint_rows: List[PoolHint],
    *,
    in_verify_subset: bool,
    in_verify_cap: bool,
    priority_score: float,
    min_score: float = _DEFAULT_VERIFY_SCORE_MIN,
) -> tuple[str, str]:
    """Return (disposition, disposition_reason) for verify-budget top-N table."""
    if not hint_rows:
        return DISPOSITION_NO_RADAR_POOL, "no_dexscreener_pool_for_token"
    onchain_rows = [h for h in hint_rows if str(h.source or "") in _ONCHAIN_PRIMARY_SOURCES]
    if onchain_rows and not any(
        str(h.source or "") == "dexscreener" for h in hint_rows
    ):
        if in_verify_subset:
            return DISPOSITION_SELECTED_FOR_VERIFY, "onchain_factory_primary"
        if not in_verify_cap:
            return DISPOSITION_DROPPED_TO_WARM, "below_verify_cap_rank"
    if any(getattr(h, "stale", False) for h in hint_rows):
        return DISPOSITION_STALE_HINT, "radar_hint_marked_stale"
    unsupported = [
        h
        for h in hint_rows
        if str(getattr(h, "hint_status", "") or "").upper() in {"UNSUPPORTED_DEX", "DEX_UNSUPPORTED"}
    ]
    if unsupported:
        return DISPOSITION_DEX_UNSUPPORTED, "unsupported_dex_hint"
    if dex_count(hint_rows) < 2 and not any(
        str(h.radar_reason or "") in {RADAR_REASON_NEW_POOL, RADAR_REASON_LIQUIDITY}
        for h in hint_rows
    ):
        return DISPOSITION_LOW_LIQUIDITY_HINT, "weak_single_venue_radar_signal"
    if in_verify_subset:
        return DISPOSITION_SELECTED_FOR_VERIFY, "scored_within_verify_cap"
    if not in_verify_cap:
        return DISPOSITION_DROPPED_TO_WARM, "below_verify_cap_rank"
    if priority_score < min_score:
        return DISPOSITION_DROPPED_TO_WARM, "below_min_score"
    return DISPOSITION_DROPPED_TO_WARM, "not_selected_for_verify_subset"


def build_disposition_histogram(
    top_candidates: List[Dict[str, Any]],
) -> Dict[str, int]:
    hist: Dict[str, int] = {}
    for row in top_candidates:
        disp = str(row.get("disposition") or DISPOSITION_DROPPED_TO_WARM)
        hist[disp] = int(hist.get(disp, 0)) + 1
    return dict(sorted(hist.items(), key=lambda kv: (-kv[1], kv[0])))


def score_mirror_verify_candidate(
    token: str,
    rows: List[PoolHint],
    *,
    watchlist_entry: Optional[Dict[str, Any]] = None,
) -> Tuple[float, List[str]]:
    """Higher score => prioritize productive RPC verify."""
    tok = str(token or "").lower()
    score = 0.0
    reasons: List[str] = []
    venues = dex_count(rows)
    if venues >= 2:
        score += 45.0
        reasons.append("multi_venue_hint")
    radar_reasons = {str(r.radar_reason or "") for r in rows}
    if RADAR_REASON_NEW_POOL in radar_reasons:
        score += 25.0
        reasons.append("fresh_token")
    if RADAR_REASON_LIQUIDITY in radar_reasons:
        score += 15.0
        reasons.append("rough_liquidity")
    if watchlist_entry:
        token_class = str(watchlist_entry.get("token_class") or "")
        refresh_lane = str(watchlist_entry.get("refresh_lane") or "")
        if token_class == "fresh_long_tail":
            score += 60.0
            reasons.append("fresh_long_tail")
        elif token_class == "known_major":
            score -= 60.0
            reasons.append("known_major_penalty")
        if refresh_lane == "fresh_delta_lane":
            score += 20.0
            reasons.append("fresh_delta_lane")
        elif refresh_lane == "audit_lane":
            score -= 25.0
            reasons.append("audit_lane_depriority")
        first_ts = watchlist_entry.get("first_seen_ts")
        if first_ts is not None:
            try:
                age_h = max(0.0, (time.time() - float(first_ts)) / 3600.0)
                if age_h <= 24.0:
                    score += 15.0
                    reasons.append("recent_first_seen_24h")
                elif age_h <= 72.0:
                    score += 8.0
                    reasons.append("recent_first_seen_72h")
            except (TypeError, ValueError):
                pass
        try:
            transitions = int(watchlist_entry.get("transitions_1_to_2") or 0)
        except (TypeError, ValueError):
            transitions = 0
        if transitions >= 1:
            score += 40.0
            reasons.append("second_pool_signal")
        if watchlist_entry.get("second_pool_hint"):
            score += 35.0
            reasons.append("second_pool_hint")
        liq = watchlist_entry.get("approx_liquidity_usd") or watchlist_entry.get(
            "liquidity_usd"
        )
        if liq is not None:
            try:
                score += min(15.0, float(liq) / 10_000.0)
            except (TypeError, ValueError):
                pass
    if not rows:
        score -= 10.0
        reasons.append("stale_unknown")
    elif any(getattr(r, "stale", False) for r in rows):
        score -= 15.0
        reasons.append("stale_hint")
    if tok and not tok.startswith("0x"):
        score -= 100.0
        reasons.append("invalid_token")
    return round(score, 2), reasons


def rank_tokens_for_verify(
    hints: Iterable[PoolHint],
    *,
    all_tokens: Optional[Iterable[str]] = None,
    watchlist: Optional[Dict[str, Any]] = None,
    min_score: float = _DEFAULT_VERIFY_SCORE_MIN,
    max_tokens: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Return scored verify candidates sorted by priority."""
    by_tok = hints_by_token(list(hints))
    token_universe: Set[str] = set()
    if isinstance(watchlist, dict) and isinstance(watchlist.get("tokens"), dict):
        token_universe = {str(k).lower() for k in watchlist["tokens"].keys()}
    elif all_tokens is not None:
        token_universe = {str(t).lower() for t in all_tokens}
    else:
        token_universe = {t.lower() for t in by_tok.keys()}
    wl_tokens = (watchlist or {}).get("tokens") or {}
    ranked: List[Dict[str, Any]] = []
    for tok in sorted(token_universe):
        if not tok.startswith("0x"):
            continue
        rows = by_tok.get(tok) or []
        wl_entry = wl_tokens.get(tok) or wl_tokens.get(tok.lower())
        score, reasons = score_mirror_verify_candidate(tok, rows, watchlist_entry=wl_entry)
        if score < min_score and not rows:
            continue
        if score < min_score and dex_count(rows) < 2:
            continue
        ranked.append(
            {
                "token": tok,
                "priority_score": score,
                "reasons": reasons,
                "dex_count": dex_count(rows),
                "hint_count": len(rows),
            }
        )
    ranked.sort(key=lambda r: float(r.get("priority_score") or 0.0), reverse=True)
    if max_tokens is not None and max_tokens > 0:
        ranked = ranked[: int(max_tokens)]
    return ranked


def rank_tokens_for_verify_with_budget(
    hints: Iterable[PoolHint],
    *,
    all_tokens: Optional[Iterable[str]] = None,
    watchlist: Optional[Dict[str, Any]] = None,
    min_score: float = _DEFAULT_VERIFY_SCORE_MIN,
    max_tokens: Optional[int] = None,
    top_n_table: int = 50,
) -> tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Rank verify candidates and return budget counters for hot/warm lanes."""
    by_tok = hints_by_token(list(hints))
    wl_tokens = (watchlist or {}).get("tokens") or {}
    full = rank_tokens_for_verify(
        hints,
        all_tokens=all_tokens,
        watchlist=watchlist,
        min_score=min_score,
        max_tokens=None,
    )
    scored = [
        r
        for r in full
        if float(r.get("priority_score") or 0.0) >= min_score
    ]
    capped = full
    if max_tokens is not None and max_tokens > 0:
        capped = full[: int(max_tokens)]
    subset = verify_subset_from_scored_candidates(capped, min_score=min_score)
    capped_tokens = {str(r.get("token") or "").lower() for r in capped}
    subset_tokens = set(subset)
    top_candidates: List[Dict[str, Any]] = []
    for row in full[: max(1, int(top_n_table))]:
        tok = str(row.get("token") or "").lower()
        wl_entry = wl_tokens.get(tok) or wl_tokens.get(tok.lower()) or {}
        hint_rows = by_tok.get(tok) or []
        score = float(row.get("priority_score") or 0.0)
        disposition, disposition_reason = classify_verify_disposition(
            tok,
            hint_rows,
            in_verify_subset=tok in subset_tokens,
            in_verify_cap=tok in capped_tokens,
            priority_score=score,
            min_score=min_score,
        )
        top_candidates.append(
            {
                "token": tok,
                "priority_score": row.get("priority_score"),
                "token_class": wl_entry.get("token_class"),
                "refresh_lane": wl_entry.get("refresh_lane"),
                "hint_sources": sorted({str(h.source) for h in hint_rows if h.source}),
                "dex_count": row.get("dex_count"),
                "score_reasons": row.get("reasons"),
                "disposition": disposition,
                "disposition_reason": disposition_reason,
            }
        )
    effective_cap = int(max_tokens or 0)
    if effective_cap <= 0 and subset_tokens:
        effective_cap = len(subset_tokens)
    budget: Dict[str, Any] = {
        "radar_seen": len(by_tok),
        "scored_candidates": len(scored),
        "verify_subset_size": len(subset),
        "dropped_to_warm_count": max(0, len(scored) - len(subset)),
        "verify_subset_cap": effective_cap,
        "top_candidates": top_candidates,
        "disposition_histogram": build_disposition_histogram(top_candidates),
    }
    return capped, budget


def verify_subset_from_scored_candidates(
    ranked: List[Dict[str, Any]],
    *,
    min_score: float = _DEFAULT_VERIFY_SCORE_MIN,
) -> Set[str]:
    out: Set[str] = set()
    for row in ranked:
        if float(row.get("priority_score") or 0.0) < min_score:
            continue
        tok = str(row.get("token") or "").lower()
        if tok.startswith("0x"):
            out.add(tok)
    return out
