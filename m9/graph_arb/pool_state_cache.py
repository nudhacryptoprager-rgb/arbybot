"""Persistent TTL cache for V3 pool on-chain state.

Stores per-pool: sqrtPriceX96, tick, liquidity, block_number.
Used by multicall_snapshot.py to avoid re-fetching unchanged state.

TTL is configurable (default 2 s) — short enough to stay fresh across sweeps,
long enough to avoid redundant RPC when the same pool appears in many cycles.

Persistence: optional JSON file so state survives between sweep restarts within
the same scan session.  Call ``load(path)`` at startup and ``save(path)`` after
each snapshot batch.
"""
from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Optional

# Default TTL for cached entries (seconds)
_DEFAULT_TTL_S: float = float(os.environ.get("ARBY_POOL_CACHE_TTL", "2.0"))

# Persistence file (overridden by callers)
_DEFAULT_CACHE_PATH = "data/tmp/m9_pool_state_cache.json"


@dataclass
class PoolState:
    """On-chain state snapshot for a single V3-family pool."""

    pool_addr: str        # lowercase hex, 0x-prefixed
    sqrt_price_x96: int   # sqrtPriceX96 from slot0()
    tick: int             # current tick from slot0()
    liquidity: int        # current in-range liquidity from liquidity()
    block_number: int     # block at which state was fetched
    fetched_at_mono: float  # monotonic clock at fetch time (for TTL)

    def is_empty(self) -> bool:
        """Return True if pool has no in-range liquidity or zero price."""
        return self.liquidity == 0 or self.sqrt_price_x96 == 0

    def age_s(self) -> float:
        """Seconds since this entry was fetched."""
        return time.monotonic() - self.fetched_at_mono

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("fetched_at_mono", None)  # don't persist monotonic clock
        return d

    @classmethod
    def from_dict(cls, d: dict, *, fetched_at_mono: float = 0.0) -> "PoolState":
        # Gracefully handle None values written by older cache versions
        # (e.g. block_number=null in JSON when RPC returned None).
        _bn = d.get("block_number")
        _liq = d.get("liquidity")
        _tick = d.get("tick")
        _sqrt = d.get("sqrt_price_x96")
        if _bn is None or _sqrt is None or _liq is None or _tick is None:
            raise ValueError(
                f"PoolState.from_dict: stale/corrupt cache entry for pool "
                f"{d.get('pool_addr', '?')} — missing required field "
                f"(block_number={_bn}, sqrt_price_x96={_sqrt}, "
                f"liquidity={_liq}, tick={_tick})"
            )
        return cls(
            pool_addr=d["pool_addr"],
            sqrt_price_x96=int(_sqrt),
            tick=int(_tick),
            liquidity=int(_liq),
            block_number=int(_bn),
            fetched_at_mono=fetched_at_mono,
        )


class PoolStateCache:
    """Thread-safe TTL cache for :class:`PoolState` objects.

    Usage::

        cache = PoolStateCache()
        cache.load()                         # optional: warm from JSON file

        # before sweep
        missing = cache.stale_or_missing(pool_addrs)
        # ... fetch missing from RPC ...
        cache.put_many(new_states)

        # during sweep
        state = cache.get("0xpool...")
        if state and not state.is_empty():
            ...

        cache.save()                         # persist to JSON after sweep
    """

    def __init__(self, ttl_s: float = _DEFAULT_TTL_S) -> None:
        self._ttl = ttl_s
        self._lock = threading.Lock()
        self._store: Dict[str, PoolState] = {}  # key = lowercase pool addr

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    def get(self, pool_addr: str) -> Optional[PoolState]:
        """Return cached state if fresh, else None."""
        key = pool_addr.lower()
        with self._lock:
            entry = self._store.get(key)
        if entry is None:
            return None
        if entry.age_s() > self._ttl:
            return None
        return entry

    def stale_or_missing(self, pool_addrs: "list[str]") -> "list[str]":
        """Return addresses whose cached state is missing or stale."""
        now = time.monotonic()
        result = []
        with self._lock:
            for addr in pool_addrs:
                key = addr.lower()
                entry = self._store.get(key)
                if entry is None or (now - entry.fetched_at_mono) > self._ttl:
                    result.append(addr)
        return result

    # ------------------------------------------------------------------
    # Write
    # ------------------------------------------------------------------

    def put(self, state: PoolState) -> None:
        key = state.pool_addr.lower()
        with self._lock:
            self._store[key] = state

    def put_many(self, states: "list[PoolState]") -> None:
        with self._lock:
            for s in states:
                self._store[s.pool_addr.lower()] = s

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: str = _DEFAULT_CACHE_PATH) -> None:
        """Write non-stale entries to a JSON file (atomic write)."""
        now = time.monotonic()
        with self._lock:
            entries = [
                s.to_dict()
                for s in self._store.values()
                if (now - s.fetched_at_mono) <= self._ttl
            ]
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = str(p) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"schema_version": "pool_state_cache.1", "entries": entries}, fh)
        os.replace(tmp, str(p))

    def load(self, path: str = _DEFAULT_CACHE_PATH) -> int:
        """Load entries from JSON file.  Returns number of entries loaded."""
        p = Path(path)
        if not p.exists():
            return 0
        try:
            with p.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except Exception:
            return 0
        entries = data.get("entries", [])
        loaded = 0
        # Use fetched_at_mono = 0 so entries are immediately considered stale
        # (they will be re-fetched at next snapshot) — this is intentional;
        # the file is only useful to pre-populate pool_addr keys for lookup.
        now = time.monotonic()
        with self._lock:
            for d in entries:
                try:
                    state = PoolState.from_dict(d, fetched_at_mono=now - self._ttl - 1)
                    self._store[state.pool_addr.lower()] = state
                    loaded += 1
                except (KeyError, ValueError, TypeError):
                    pass
        return loaded

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def size(self) -> int:
        with self._lock:
            return len(self._store)

    def fresh_count(self) -> int:
        """Number of entries that are still within TTL."""
        now = time.monotonic()
        with self._lock:
            return sum(
                1 for s in self._store.values()
                if (now - s.fetched_at_mono) <= self._ttl
            )

    def summary(self) -> dict:
        with self._lock:
            total = len(self._store)
        return {
            "total": total,
            "fresh": self.fresh_count(),
            "ttl_s": self._ttl,
        }
