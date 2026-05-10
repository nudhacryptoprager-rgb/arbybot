"""E1.59 step #7: DISC -> PROD pool-level promotion with TTL + provenance.

Reviewer 3h-soak finding: ``roundtrip_profitable_total`` DISC=35 vs PROD=7
— DISC discovers profitable opportunities on specific pool *addresses*,
but PROD's prewarm queue only consumes pair-symbol keys, so PROD doesn't
re-route to the exact pool DISC succeeded on. This module promotes at
the pool address level with:

  * TTL (default 600s) so a pool that stops being profitable falls off.
  * Provenance metadata (``observed_in_session``, ``last_profitable_at``,
    ``profitable_count``) so the operator can audit promotions.
  * Topology constraints (``router``, ``fee_tier``, ``token_in``,
    ``token_out``) so PROD reuses the exact identity DISC succeeded on.

Default OFF — opt-in via ``ARBY_POOL_PROMOTION=1``. When OFF the snapshot
methods still work (return zeros) so callers can stay agnostic.

Public API:
  * ``observe_profitable(pool, ...)``: record a DISC-side success.
  * ``active_promotions(now)``: list of currently-valid promotions.
  * ``snapshot()``: rollup-friendly dict.
  * ``reset()``.
"""
from __future__ import annotations

import os
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional


def is_enabled() -> bool:
    return os.environ.get("ARBY_POOL_PROMOTION", "0") == "1"


def _ttl_seconds() -> int:
    try:
        return max(1, int(os.environ.get("ARBY_POOL_PROMOTION_TTL_S", "600")))
    except ValueError:
        return 600


@dataclass
class PoolPromotion:
    pool: str
    pair: Optional[str] = None
    router: Optional[str] = None
    fee_tier: Optional[int] = None
    token_in: Optional[str] = None
    token_out: Optional[str] = None
    chain: Optional[str] = None
    first_observed_at: float = 0.0  # monotonic seconds
    last_profitable_at: float = 0.0
    profitable_count: int = 0
    observed_in_session: Optional[str] = None
    last_profit_bps: Optional[float] = None


_LOCK = threading.RLock()
_PROMOTIONS: Dict[str, PoolPromotion] = {}


def _key(pool: str) -> str:
    return (pool or "").strip().lower()


def observe_profitable(
    *,
    pool: str,
    pair: Optional[str] = None,
    router: Optional[str] = None,
    fee_tier: Optional[int] = None,
    token_in: Optional[str] = None,
    token_out: Optional[str] = None,
    chain: Optional[str] = None,
    profit_bps: Optional[float] = None,
    session_id: Optional[str] = None,
    now: Optional[float] = None,
) -> PoolPromotion:
    """Record a DISC-side profitable observation for a pool.

    Returns the stored ``PoolPromotion``. When the feature flag is OFF
    a transient ``PoolPromotion`` is returned but nothing is persisted
    in the registry.
    """
    if not pool:
        raise ValueError("pool address is required")
    if now is None:
        now = time.monotonic()
    rec = PoolPromotion(
        pool=pool,
        pair=pair,
        router=router,
        fee_tier=fee_tier,
        token_in=token_in,
        token_out=token_out,
        chain=chain,
        first_observed_at=now,
        last_profitable_at=now,
        profitable_count=1,
        observed_in_session=session_id,
        last_profit_bps=profit_bps,
    )
    if not is_enabled():
        return rec
    k = _key(pool)
    with _LOCK:
        existing = _PROMOTIONS.get(k)
        if existing is None:
            _PROMOTIONS[k] = rec
            return rec
        existing.last_profitable_at = now
        existing.profitable_count += 1
        # Refresh routing identity if newer info arrived.
        if pair is not None:
            existing.pair = pair
        if router is not None:
            existing.router = router
        if fee_tier is not None:
            existing.fee_tier = fee_tier
        if token_in is not None:
            existing.token_in = token_in
        if token_out is not None:
            existing.token_out = token_out
        if profit_bps is not None:
            existing.last_profit_bps = profit_bps
        if session_id is not None:
            existing.observed_in_session = session_id
        return existing


def _expire_locked(now: float) -> None:
    ttl = _ttl_seconds()
    expired = [
        k for k, p in _PROMOTIONS.items() if (now - p.last_profitable_at) > ttl
    ]
    for k in expired:
        _PROMOTIONS.pop(k, None)


def active_promotions(now: Optional[float] = None) -> List[PoolPromotion]:
    """Return the list of currently-valid promotions (post-TTL).

    Mutates the registry: expired entries are dropped.
    """
    if not is_enabled():
        return []
    if now is None:
        now = time.monotonic()
    with _LOCK:
        _expire_locked(now)
        # Stable ordering: most recent first, then by profitable_count desc.
        return sorted(
            _PROMOTIONS.values(),
            key=lambda p: (-p.last_profitable_at, -p.profitable_count, p.pool),
        )


def snapshot(now: Optional[float] = None) -> Dict[str, object]:
    """Return a JSON-serialisable snapshot for the rollup writer."""
    if now is None:
        now = time.monotonic()
    promos = active_promotions(now=now) if is_enabled() else []
    pairs_unique = {p.pair for p in promos if p.pair}
    routers_unique = {p.router for p in promos if p.router}
    return {
        "active_count": len(promos),
        "pairs_unique_count": len(pairs_unique),
        "routers_unique_count": len(routers_unique),
        "ttl_s": _ttl_seconds(),
        "promotions": [asdict(p) for p in promos],
    }


def reset() -> None:
    with _LOCK:
        _PROMOTIONS.clear()


def seed_from_env(now: Optional[float] = None) -> int:
    """Pre-populate promotion registry from ARBY_POOL_PROMOTION_SEED_JSON.

    E1.70 fix 6: operators can supply a JSON array of known profitable
    DISC pools (e.g. VIRTUAL/WETH discovered in the 30-min soak) so PROD
    lane immediately includes them as prewarm targets without waiting for
    the DISC → PROD feedback loop to re-observe them.

    JSON format: list of {"pool": "0x...", "pair": "VIRTUAL/WETH",
                          "profit_bps": 703, "chain": "base"} dicts.
    Returns the number of entries seeded.
    """
    seed_json = os.environ.get("ARBY_POOL_PROMOTION_SEED_JSON", "").strip()
    if not seed_json or not is_enabled():
        return 0
    try:
        import json
        entries = json.loads(seed_json)
        if not isinstance(entries, list):
            return 0
    except Exception:
        return 0
    count = 0
    if now is None:
        now = time.monotonic()
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("pool"):
            continue
        try:
            observe_profitable(
                pool=entry["pool"],
                pair=entry.get("pair"),
                router=entry.get("router"),
                token_in=entry.get("token_in"),
                token_out=entry.get("token_out"),
                chain=entry.get("chain"),
                profit_bps=float(entry.get("profit_bps") or 0) or None,
                session_id="env_seed",
                now=now,
            )
            count += 1
        except Exception:
            continue
    return count


def _auto_promotion_bps_threshold() -> float:
    """E1.80: minimum net_bps for auto-promotion from cold-positive signal.

    Default 20.0 bps — well above the typical noise floor (gas+fee combined
    ≈10-15 bps on Base) but low enough to catch real divergence windows.
    Override via ``ARBY_POOL_PROMOTION_AUTO_BPS``.
    """
    try:
        return float(os.environ.get("ARBY_POOL_PROMOTION_AUTO_BPS", "20") or 20.0)
    except (TypeError, ValueError):
        return 20.0


def try_promote_from_cold_signal(
    *,
    pool: Optional[str],
    net_bps: Optional[float],
    pair: Optional[str] = None,
    router: Optional[str] = None,
    fee_tier: Optional[int] = None,
    token_in: Optional[str] = None,
    token_out: Optional[str] = None,
    chain: Optional[str] = None,
    session_id: Optional[str] = None,
    now: Optional[float] = None,
) -> Optional[PoolPromotion]:
    """E1.80: dynamic cold→hot promotion hook.

    Records a profitable cold-lane observation when:
      * feature flag ``ARBY_POOL_PROMOTION=1`` is set (delegated to
        ``observe_profitable``);
      * a non-empty ``pool`` address is supplied;
      * ``net_bps`` is finite and ≥ ``ARBY_POOL_PROMOTION_AUTO_BPS`` (20 by
        default).

    Returns the resulting ``PoolPromotion`` on success, ``None`` when the
    signal is rejected (below threshold, missing data, or feature off).

    Fail-soft: any exception is swallowed so callers in the cold-immediate
    pipeline never break on a promotion-side bug.
    """
    if not pool or net_bps is None:
        return None
    try:
        bps = float(net_bps)
    except (TypeError, ValueError):
        return None
    if not (bps == bps) or bps < _auto_promotion_bps_threshold():  # NaN-safe
        return None
    if not is_enabled():
        return None
    try:
        return observe_profitable(
            pool=pool,
            pair=pair,
            router=router,
            fee_tier=fee_tier,
            token_in=token_in,
            token_out=token_out,
            chain=chain,
            profit_bps=bps,
            session_id=session_id or "cold_signal_auto",
            now=now,
        )
    except Exception:
        return None


reset_for_tests = reset


__all__ = [
    "PoolPromotion",
    "active_promotions",
    "is_enabled",
    "observe_profitable",
    "reset",
    "reset_for_tests",
    "snapshot",
    "try_promote_from_cold_signal",
]
