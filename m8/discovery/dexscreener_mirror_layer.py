"""DexScreener all-mirror recall layer for verified token contracts.

This layer is intentionally hint-only: it expands the mirror candidate universe
by token contract address, then downstream on-chain verification decides whether
any pool may enter M8.2/M9 bridge flow.
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Set

from m8.discovery.dex_coverage_gate import stamp_hint_support_status
from m8.discovery.dexscreener_hints import fetch_token_hints_batch
from m8.discovery.pool_hints import PoolHint, build_artifact, dedupe_hints

DEXSCREENER_MIRROR_LAYER = "dexscreener_all_mirrors"


def _norm_addr(addr: str) -> str:
    return str(addr or "").lower().strip()


def _valid_token_addresses(token_addresses: Iterable[str]) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for addr in token_addresses:
        a = _norm_addr(addr)
        if not (a.startswith("0x") and len(a) == 42):
            continue
        if a in seen:
            continue
        seen.add(a)
        out.append(a)
    return out


def classify_dexscreener_mirrors(
    hints: Iterable[PoolHint],
    *,
    config: Dict[str, Any],
) -> tuple[List[PoolHint], Dict[str, Any]]:
    """Stamp support status and compute recall-layer metrics for all mirrors."""
    stamped: List[PoolHint] = []
    support_hist: Counter = Counter()
    dex_hist: Counter = Counter()
    raw_dex_hist: Counter = Counter()
    tokens_any: Set[str] = set()
    tokens_supported: Set[str] = set()

    for hint in hints:
        h = stamp_hint_support_status(hint, config, source="dexscreener")
        raw = dict(h.raw or {})
        raw["mirror_recall_layer"] = DEXSCREENER_MIRROR_LAYER
        h.raw = raw
        stamped.append(h)

        status = str(raw.get("support_status") or "unknown_alias")
        support_hist[status] += 1
        if h.dex_id:
            dex_hist[h.dex_id] += 1
        raw_dex = str(raw.get("raw_dex_id") or raw.get("dexId") or h.dex_id or "")
        if raw_dex:
            raw_dex_hist[raw_dex] += 1
        focus = _norm_addr(h.focus_token)
        if focus:
            tokens_any.add(focus)
            if status == "supported":
                tokens_supported.add(focus)

    deduped = dedupe_hints(stamped)
    metrics = {
        "dexscreener_mirror_layer": DEXSCREENER_MIRROR_LAYER,
        "dexscreener_all_mirrors_total": len(deduped),
        "dexscreener_supported_mirrors_total": int(support_hist.get("supported", 0)),
        "dexscreener_unsupported_mirrors_total": int(support_hist.get("unsupported", 0)),
        "dexscreener_unknown_alias_mirrors_total": int(
            support_hist.get("unknown_alias", 0)
        ),
        "dexscreener_support_status_counts": dict(support_hist),
        "dexscreener_internal_dex_counts": dict(dex_hist),
        "dexscreener_raw_dex_counts": dict(raw_dex_hist),
        "dexscreener_tokens_with_any_mirror": len(tokens_any),
        "dexscreener_tokens_with_supported_mirror": len(tokens_supported),
    }
    return deduped, metrics


def build_dexscreener_mirror_artifact(
    token_addresses: Iterable[str],
    *,
    chain: str = "base",
    config: Dict[str, Any],
    use_cache: bool = True,
    max_recall: bool = True,
    timeout_s: float = 12.0,
    fetched_hints_by_token: Optional[Dict[str, List[PoolHint]]] = None,
) -> Dict[str, Any]:
    """Fetch/classify every DexScreener mirror for verified token addresses."""
    tokens = _valid_token_addresses(token_addresses)
    if fetched_hints_by_token is None:
        fetched_hints_by_token = fetch_token_hints_batch(
            tokens,
            chain=chain,
            timeout_s=timeout_s,
            use_cache=use_cache,
            max_recall=max_recall,
            dex_config=config,
            cache_lane=DEXSCREENER_MIRROR_LAYER,
        )

    hints: List[PoolHint] = []
    for token in tokens:
        hints.extend(fetched_hints_by_token.get(token) or [])

    classified, metrics = classify_dexscreener_mirrors(hints, config=config)
    metrics["dexscreener_tokens_requested"] = len(tokens)
    metrics["dexscreener_tokens_returned"] = len(
        {h.focus_token for h in classified if h.focus_token}
    )
    return build_artifact(
        chain=chain,
        sources=[DEXSCREENER_MIRROR_LAYER],
        hints=classified,
        metrics=metrics,
    )
