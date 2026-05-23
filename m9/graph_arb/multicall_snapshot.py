"""Batch-fetch V3 pool state snapshots via Multicall3 (Step 3).

One Multicall3 aggregate3() call replaces N individual eth_call round-trips for
``slot0()`` and ``liquidity()``, reducing RPC load by ~90% for a sweep with many
pools.

Usage::

    from m9.graph_arb.multicall_snapshot import snapshot_pool_states

    states = snapshot_pool_states(pool_addrs, rpc_url=rpc_url, cache=cache)
    # states: dict[str, PoolState | None]

The function:
  1. Checks the cache for fresh entries.
  2. Fetches only stale/missing pools via MulticallBatcher.
  3. Stores new states in the cache.
  4. Returns the merged result.

If rpc_url is None or MulticallBatcher fails, returns whatever the cache has
plus None for unknown pools — callers must handle None gracefully.
"""
from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional

from m9.graph_arb.pool_state_cache import PoolState, PoolStateCache

# Module-level import of MulticallBatcher for mockability in tests.
# Falls back to None if core.multicall is unavailable (no web3 installed).
try:
    from core.multicall import MulticallBatcher
except Exception:  # ImportError or web3 missing
    MulticallBatcher = None  # type: ignore[assignment,misc]

log = logging.getLogger(__name__)

# Env-controllable skip flag (used in unit tests / offline mode)
import os as _os
_SKIP_RPC = _os.environ.get("ARBY_SKIP_RPC") == "1"

# Dedicated rate budget for Multicall3 calls, separate from the quoter budget.
# Default: 1 RPS keeps multicall from competing with per-leg quoter calls.
_MULTICALL_RPS = int(_os.environ.get("ARBY_MULTICALL_RPS", "1"))
_multicall_limiter = None  # lazy-initialised


def _get_multicall_limiter():
    """Return (or create) the dedicated Multicall rate limiter."""
    global _multicall_limiter
    if _multicall_limiter is None:
        from core.rpc_rate_limiter import TokenBucketRateLimiter
        _multicall_limiter = TokenBucketRateLimiter(
            rps=_MULTICALL_RPS, burst=max(_MULTICALL_RPS * 2, 2)
        )
    return _multicall_limiter


# Cumulative per-process stats for artifact reporting.
_cumulative_multicall_stats: dict = {
    "attempted": 0,
    "success": 0,
    "http_429": 0,
    "retry_count": 0,
    "fetched_total": 0,
    "requested_total": 0,
    "subchunk_splits": 0,
}


def get_multicall_stats() -> dict:
    """Return cumulative multicall snapshot stats for this process (copy)."""
    return dict(_cumulative_multicall_stats)


def reset_multicall_stats() -> None:
    """Reset cumulative stats (call before a new run to avoid cross-run contamination)."""
    for k in _cumulative_multicall_stats:
        _cumulative_multicall_stats[k] = 0


def snapshot_pool_states(
    pool_addresses: List[str],
    rpc_url: Optional[str],
    cache: Optional[PoolStateCache] = None,
    block_num: Optional[int] = None,
) -> Dict[str, Optional[PoolState]]:
    """Batch-fetch slot0 + liquidity for *pool_addresses* via Multicall3.

    Args:
        pool_addresses: Pool contract addresses (any case; normalised internally).
        rpc_url: HTTP JSON-RPC endpoint.  If None, returns only cached data.
        cache: Optional :class:`PoolStateCache` to consult and update.
        block_num: Block to query at.  If None, uses ``"latest"``.

    Returns:
        Mapping of lowercase pool address → :class:`PoolState` (or None on RPC
        failure / pool not found).
    """
    if not pool_addresses:
        return {}

    norm = [a.lower() for a in pool_addresses]

    # 1. Check cache
    fresh: Dict[str, PoolState] = {}
    to_fetch: List[str] = []
    if cache is not None:
        for addr in norm:
            cached = cache.get(addr)
            if cached is not None:
                fresh[addr] = cached
            else:
                to_fetch.append(addr)
    else:
        to_fetch = list(norm)

    # 2. Fetch missing via Multicall — skip if no RPC or offline mode
    if to_fetch and rpc_url and not _SKIP_RPC:
        fetched = _batch_fetch(to_fetch, rpc_url, block_num)
        if cache is not None and fetched:
            cache.put_many([s for s in fetched.values() if s is not None])
        fresh.update(fetched)

    # 3. Fill gaps with None for completely unknown addresses
    result: Dict[str, Optional[PoolState]] = {addr: fresh.get(addr) for addr in norm}
    return result


def _batch_fetch(
    pool_addresses: List[str],
    rpc_url: str,
    block_num: Optional[int],
) -> Dict[str, Optional[PoolState]]:
    """Internal: fetch slot0 + liquidity for *pool_addresses* via MulticallBatcher."""
    if MulticallBatcher is None:
        log.warning("MulticallBatcher unavailable (web3 not installed?)")
        return {a.lower(): None for a in pool_addresses}

    _block = block_num  # None → web3.py defaults to "latest"
    batcher = MulticallBatcher(rpc_url=rpc_url, block_num=_block, rpc_limiter=_get_multicall_limiter())

    # Two batched calls: slot0 + liquidity
    # slot0 returns (sqrtPriceX96, tick, ...) via MulticallBatcher.batch_slot0()
    slot0_results = batcher.batch_slot0(pool_addresses)
    liquidity_results = batcher.batch_liquidity(pool_addresses)

    now = time.monotonic()
    output: Dict[str, Optional[PoolState]] = {}
    for addr in pool_addresses:
        key = addr.lower()
        slot0 = slot0_results.get(addr) or slot0_results.get(key)
        liq = liquidity_results.get(addr) or liquidity_results.get(key)

        if slot0 is None:
            output[key] = None
            continue

        sqrt_price, tick, _unused = slot0
        liquidity = liq if liq is not None else 0

        output[key] = PoolState(
            pool_addr=key,
            sqrt_price_x96=sqrt_price,
            tick=tick,
            liquidity=liquidity,
            block_number=_block,
            fetched_at_mono=now,
        )

    log.debug(
        "multicall_snapshot: fetched=%d/%d rpc=%s",
        sum(1 for v in output.values() if v is not None),
        len(pool_addresses),
        rpc_url[:40] if rpc_url else "none",
    )

    # Accumulate into per-process cumulative stats for artifact reporting
    _bs = batcher.stats
    _cumulative_multicall_stats["attempted"] += _bs.get("multicall_attempted", 0)
    _cumulative_multicall_stats["success"] += _bs.get("multicall_success", 0)
    _cumulative_multicall_stats["http_429"] += _bs.get("multicall_429", 0)
    _cumulative_multicall_stats["retry_count"] += _bs.get("multicall_retry_count", 0)
    _cumulative_multicall_stats["subchunk_splits"] += _bs.get("multicall_subchunk_splits", 0)
    _fetched = sum(1 for v in output.values() if v is not None)
    _cumulative_multicall_stats["fetched_total"] += _fetched
    _cumulative_multicall_stats["requested_total"] += len(pool_addresses)

    return output
