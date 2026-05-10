"""E1.81 — PoolFamily: per-pair pool-family model for M7 scoring.

A PoolFamily groups all pools for a single token pair across DEX types
and fee tiers so the scorer can reason about the *best buy pool* and
*best sell pool* across the full family rather than relying on whichever
pool triggered the hotpath event.

Architecture:
  * ``PoolFamily`` — lightweight dataclass populated from ``PoolRegistry``
    entries (factory-discovered) and optionally enriched from TVL scout data.
  * ``best_buy_pool(family)`` / ``best_sell_pool(family)`` — pure helpers
    returning the highest-liquidity active entry for each leg.
  * ``family_summary(family)`` — JSON-serialisable dict for rollup/dashboard.
  * ``PoolRegistry.get_pool_family()`` — entry point; wraps ``lookup_pair()``
    and caches families with a configurable TTL (``ARBY_POOL_FAMILY_TTL_S``).

Backward compat:
  * No existing public symbols are changed.  New symbols only.
  * ``PoolPromotion`` in ``disc_to_prod_pool_promotion`` is unchanged;
    ``PairFamilyPromotion`` is added as an independent dataclass.

ENV flags:
  * ``ARBY_POOL_FAMILY_TTL_S``  — family cache TTL in seconds (default 60).
  * ``ARBY_POOL_FAMILY_ENABLE`` — set to ``"0"`` to disable family cache
    (falls back to list returned by ``lookup_pair``).  Default ``"1"``.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

__all__ = [
    "PoolFamily",
    "best_buy_pool",
    "best_sell_pool",
    "family_summary",
    "pool_family_ttl_s",
    "pool_family_enabled",
]


# ---------------------------------------------------------------------------
# ENV helpers
# ---------------------------------------------------------------------------

def pool_family_ttl_s() -> float:
    """E1.81: TTL for the per-pair family cache. Default 60 s."""
    try:
        return float(os.environ.get("ARBY_POOL_FAMILY_TTL_S", "60") or 60.0)
    except (TypeError, ValueError):
        return 60.0


def pool_family_enabled() -> bool:
    """E1.81: Feature flag — set ARBY_POOL_FAMILY_ENABLE=0 to disable."""
    return os.environ.get("ARBY_POOL_FAMILY_ENABLE", "1") == "1"


# ---------------------------------------------------------------------------
# PoolFamily dataclass
# ---------------------------------------------------------------------------

@dataclass
class PoolFamily:
    """Grouped pool information for a canonical token pair.

    Attributes:
        canonical_key:        Sorted lowercase address pair key ``a/b``.
        token_a:              First token (lowercase address).
        token_b:              Second token (lowercase address).
        pools:                List of ``PoolRegistryEntry`` objects.
        pair_symbol:          Human-readable symbol, e.g. ``USDC/WETH`` (optional).
        source:               Discovery source: ``factory`` | ``event`` |
                              ``scout`` | ``manual``.
        built_at:             ``time.monotonic()`` timestamp of last refresh.
        ttl_s:                Seconds until this family should be rebuilt.
        scout_tvl_usd:        Aggregate TVL from scout data (optional).
        scout_volume_24h_usd: 24 h volume from scout data (optional).
    """

    canonical_key: str
    token_a: str
    token_b: str
    pools: List[Any] = field(default_factory=list)  # List[PoolRegistryEntry]
    pair_symbol: Optional[str] = None
    source: str = "factory"  # factory | event | scout | manual
    built_at: float = field(default_factory=time.monotonic)
    ttl_s: float = field(default_factory=pool_family_ttl_s)
    scout_tvl_usd: Optional[float] = None
    scout_volume_24h_usd: Optional[float] = None

    # -----------------------------------------------------------------------
    # Derived properties
    # -----------------------------------------------------------------------

    def is_stale(self, now: Optional[float] = None) -> bool:
        """Return True if the family is older than its TTL."""
        if now is None:
            now = time.monotonic()
        return (now - self.built_at) > self.ttl_s

    @property
    def pool_count(self) -> int:
        return len(self.pools)

    @property
    def active_pool_count(self) -> int:
        return sum(
            1 for p in self.pools
            if getattr(p, "is_active", lambda: False)()
        )

    @property
    def dex_set(self) -> set:
        return {getattr(p, "dex", "") for p in self.pools if getattr(p, "dex", "")}

    @property
    def fee_tiers(self) -> List[int]:
        return sorted({int(getattr(p, "fee", 0) or 0) for p in self.pools})


# ---------------------------------------------------------------------------
# Pool selection helpers
# ---------------------------------------------------------------------------

def best_buy_pool(family: PoolFamily) -> Optional[Any]:
    """Return the best pool for buying token_in.

    Selection rule: highest liquidity among active pools; falls back to
    any pool when none are active.  Returns ``None`` for an empty family.
    """
    if not family.pools:
        return None
    active = [p for p in family.pools if getattr(p, "is_active", lambda: False)()]
    pool_list = active if active else family.pools
    return max(pool_list, key=lambda p: int(getattr(p, "liquidity", 0) or 0), default=None)


def best_sell_pool(
    family: PoolFamily,
    *,
    exclude_addr: Optional[str] = None,
) -> Optional[Any]:
    """Return the best pool for selling token_out.

    Prefers a *different* pool than the buy leg to enable true cross-pool
    arbitrage.  Falls back to the buy pool when the family has only one entry.

    Args:
        family:       The PoolFamily to search.
        exclude_addr: Pool address to exclude (typically the buy pool).
    """
    if not family.pools:
        return None
    candidates = family.pools
    if exclude_addr:
        others = [
            p for p in candidates
            if (getattr(p, "address", "") or "").lower() != exclude_addr.lower()
        ]
        if others:
            candidates = others
    active = [p for p in candidates if getattr(p, "is_active", lambda: False)()]
    pool_list = active if active else candidates
    return max(pool_list, key=lambda p: int(getattr(p, "liquidity", 0) or 0), default=None)


# ---------------------------------------------------------------------------
# Summary helper
# ---------------------------------------------------------------------------

def family_summary(family: PoolFamily) -> Dict[str, Any]:
    """Return a JSON-serialisable summary of the family for rollup/dashboard.

    Keys emitted:
        canonical_key, pair_symbol, pool_count, active_pool_count, dex_count,
        dexes, fee_tiers, source, ttl_s, is_stale,
        best_buy_pool, best_buy_dex, best_buy_fee,
        best_sell_pool, best_sell_dex, best_sell_fee,
        scout_tvl_usd, scout_volume_24h_usd.
    """
    buy = best_buy_pool(family)
    sell = best_sell_pool(
        family,
        exclude_addr=getattr(buy, "address", None) if buy else None,
    )
    return {
        "canonical_key": family.canonical_key,
        "pair_symbol": family.pair_symbol,
        "pool_count": family.pool_count,
        "active_pool_count": family.active_pool_count,
        "dex_count": len(family.dex_set),
        "dexes": sorted(family.dex_set),
        "fee_tiers": family.fee_tiers,
        "source": family.source,
        "ttl_s": family.ttl_s,
        "is_stale": family.is_stale(),
        "best_buy_pool": getattr(buy, "address", None),
        "best_buy_dex": getattr(buy, "dex", None),
        "best_buy_fee": getattr(buy, "fee", None),
        "best_buy_liquidity": getattr(buy, "liquidity", None),
        "best_sell_pool": getattr(sell, "address", None),
        "best_sell_dex": getattr(sell, "dex", None),
        "best_sell_fee": getattr(sell, "fee", None),
        "best_sell_liquidity": getattr(sell, "liquidity", None),
        "scout_tvl_usd": family.scout_tvl_usd,
        "scout_volume_24h_usd": family.scout_volume_24h_usd,
    }
