"""DexScreener-first two-phase radar pipeline (fast radar → selective verify)."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from m8.discovery.pool_hints import PoolHint
from m8.discovery.radar_layer import (
    RADAR_REASON_LIQUIDITY,
    RADAR_REASON_NEW_POOL,
    RADAR_REASON_TOKEN_PAIR,
)


@dataclass
class ProviderTiming:
    calls: int = 0
    timeouts: int = 0
    errors: int = 0
    latency_s_sum: float = 0.0

    def record(self, latency_s: float, *, timeout: bool = False, error: bool = False) -> None:
        self.calls += 1
        self.latency_s_sum += max(0.0, latency_s)
        if timeout:
            self.timeouts += 1
        if error:
            self.errors += 1

    def to_dict(self) -> Dict[str, Any]:
        avg = self.latency_s_sum / self.calls if self.calls else 0.0
        return {
            "calls": self.calls,
            "timeouts": self.timeouts,
            "errors": self.errors,
            "avg_latency_s": round(avg, 4),
            "latency_s_sum": round(self.latency_s_sum, 4),
        }


SECONDARY_SOURCES = ("geckoterminal", "thegraph_token_api")
FALLBACK_SOURCES = ("coingecko_onchain",)
AUDIT_SOURCES = ("dexscreener", "geckoterminal", "thegraph_token_api", "coingecko_onchain")


def hints_by_token(hints: List[PoolHint]) -> Dict[str, List[PoolHint]]:
    out: Dict[str, List[PoolHint]] = defaultdict(list)
    for h in hints:
        tok = (h.focus_token or h.token0_addr or "").lower()
        if tok:
            out[tok].append(h)
    return dict(out)


def dex_count(hints: List[PoolHint]) -> int:
    return len({h.dex_id for h in hints if h.dex_id})


def build_verify_subset_tokens(
    hints: List[PoolHint],
    *,
    min_dex_count: int = 2,
) -> Set[str]:
    """Tokens worth on-chain verify: multi-venue or strong radar signals."""
    by_tok = hints_by_token(hints)
    subset: Set[str] = set()
    for tok, rows in by_tok.items():
        if dex_count(rows) >= min_dex_count:
            subset.add(tok)
            continue
        reasons = {r.radar_reason for r in rows}
        if RADAR_REASON_NEW_POOL in reasons or RADAR_REASON_LIQUIDITY in reasons:
            subset.add(tok)
            continue
        if not rows:
            subset.add(tok)  # stale_unknown — verify attempt via secondary first
    return subset


def tokens_for_secondary_sources(
    all_tokens: List[str],
    hints: List[PoolHint],
    *,
    verify_subset: Optional[Set[str]] = None,
) -> List[str]:
    """GeckoTerminal/TheGraph only when DexScreener empty or weak."""
    by_tok = hints_by_token(hints)
    out: List[str] = []
    for tok in all_tokens:
        tok = tok.lower()
        rows = by_tok.get(tok) or []
        if not rows:
            out.append(tok)
            continue
        if dex_count(rows) < 2 and (verify_subset is None or tok in verify_subset):
            out.append(tok)
    return out


def tokens_for_coingecko_fallback(
    all_tokens: List[str],
    hints: List[PoolHint],
    *,
    verify_failed_tokens: Optional[Set[str]] = None,
) -> List[str]:
    failed = verify_failed_tokens or set()
    by_tok = hints_by_token(hints)
    out: List[str] = []
    for tok in all_tokens:
        tok = tok.lower()
        if tok in failed or not by_tok.get(tok):
            out.append(tok)
    return out


def filter_hints_for_tokens(hints: List[PoolHint], tokens: Set[str]) -> List[PoolHint]:
    tok_set = {t.lower() for t in tokens}
    return [
        h
        for h in hints
        if (h.focus_token or h.token0_addr or "").lower() in tok_set
    ]


def pipeline_metrics(
    *,
    radar_fast_tokens: int,
    radar_candidates: int,
    verify_subset_size: int,
    verified_count: int,
    provider_timing: Dict[str, ProviderTiming],
    verified_yield_by_source: Optional[Dict[str, int]] = None,
) -> Dict[str, Any]:
    rate = round(verified_count / verify_subset_size, 4) if verify_subset_size else 0.0
    return {
        "pipeline_mode": "dexscreener_first_two_phase",
        "radar_fast_tokens": radar_fast_tokens,
        "radar_candidates": radar_candidates,
        "verify_subset_size": verify_subset_size,
        "radar_to_verify_rate": rate,
        "verified_yield": int(verified_count),
        "per_source_verified_yield": dict(verified_yield_by_source or {}),
        "provider_timing": {k: v.to_dict() for k, v in provider_timing.items()},
    }


def classify_token_bucket(hints: List[PoolHint]) -> str:
    if not hints:
        return "stale_unknown"
    reasons = Counter(h.radar_reason or RADAR_REASON_TOKEN_PAIR for h in hints)
    if dex_count(hints) >= 2:
        return "multi_venue"
    if reasons.get(RADAR_REASON_NEW_POOL):
        return "new_pool_seen"
    if reasons.get(RADAR_REASON_LIQUIDITY):
        return "liquidity_seen"
    return "single_venue"
