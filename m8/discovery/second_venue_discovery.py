"""Second-venue discovery helpers: external hints → watch-list transitions."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from m8.discovery.pool_hints import (
    BRIDGE_ELIGIBLE_HINT_STATUSES,
    PoolHint,
    hints_for_token,
    load_hints_artifact,
    verify_hint_onchain,
)


def bump_second_venue_source(metrics: Dict[str, Any], source: str) -> None:
    hist = dict(metrics.get("second_venue_source") or {})
    hist[source] = int(hist.get(source, 0)) + 1
    metrics["second_venue_source"] = hist


def apply_verified_hints_for_token(
    *,
    token_address: str,
    entry: Dict[str, Any],
    hints_artifact: Dict[str, Any],
    chain: str,
    dex_adapter: Dict[str, str],
    metrics: Dict[str, Any],
    verify_mode: str = "specialized",
    allowed_dex_ids: Optional[Set[str]] = None,
) -> bool:
    """Try external hints to trigger 1→2 transition; returns True if transitioned."""
    from m8.discovery.token_watchlist import _record_second_pool

    token = token_address.lower()
    seen: Set[str] = set(entry.get("seen_on_dexes") or [])
    if len(seen) >= 2 and entry.get("second_pool_verified"):
        return False

    transitioned = False
    for hint in hints_for_token(hints_artifact, token):
        if allowed_dex_ids and hint.dex_id not in allowed_dex_ids:
            continue
        if hint.hint_status in BRIDGE_ELIGIBLE_HINT_STATUSES and hint.verify_method:
            verified = hint
        else:
            verified = verify_hint_onchain(
                hint,
                chain=chain,
                allowed_dex_ids=allowed_dex_ids,
                verify_mode=verify_mode,
            )
        if verified.hint_status not in BRIDGE_ELIGIBLE_HINT_STATUSES:
            continue
        if verified.dex_id in seen:
            continue
        ev = {
            "dex": verified.dex_id,
            "dex_id": verified.dex_id,
            "pool": verified.pool_id or verified.pool_address,
            "pool_address": verified.pool_id or verified.pool_address,
            "token0": verified.token0_addr,
            "token1": verified.token1_addr,
            "block_number": 0,
            "tx_hash": "",
            "resolve_source": f"external_hint:{verified.source}",
        }
        if _record_second_pool(
            entry,
            event_dict=ev,
            dex_adapter=dex_adapter,
            now_ts=__import__("time").time(),
            metrics=metrics,
            source=verified.source,
        ):
            transitioned = True
    return transitioned


def recall_rates(
    *,
    metrics: Dict[str, Any],
    watchlist_tokens: int,
    events_seen: int,
) -> Dict[str, Any]:
    verified = int(metrics.get("verified_second_pool_hints") or 0)
    transitions = int(metrics.get("transitions_1_to_2") or 0)
    tcr = round(verified / watchlist_tokens, 4) if watchlist_tokens else 0.0
    cdr = round(transitions / events_seen, 4) if events_seen else 0.0
    return {
        "transition_candidate_rate": tcr,
        "crossdex_transition_rate": cdr,
        "verified_second_pool_hints": verified,
    }


def load_hints_or_empty(path: str) -> Dict[str, Any]:
    art = load_hints_artifact(path)
    if art.get("hints"):
        return art
    return art
