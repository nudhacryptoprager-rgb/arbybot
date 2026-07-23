"""TTL negative cache for deterministic M8.1 quote reverts."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from core.persistent_ttl_cache import PersistentTTLCacheBase

DEFAULT_TTL_S = 3600.0
_BLOCK_BUCKET_SIZE = 50
DEFAULT_PERSISTENT_PATH = Path("data/tmp/m8_1_quote_negative_cache_latest.json")

_DETERMINISTIC_REJECTS = frozenset(
    {
        "PAIR_INCOMPATIBLE",
        "QUOTE_REVERT",
        "QUOTE_ZERO",
        "POOL_NOT_FOUND",
        "NO_POOL",
        "TICK_OUT_OF_RANGE",
        "INSUFFICIENT_LIQUIDITY",
    }
)


def block_bucket(block_number: Optional[int]) -> str:
    if block_number is None or block_number <= 0:
        return "head"
    return str(int(block_number) // _BLOCK_BUCKET_SIZE)


def quote_cache_key(
    *,
    route_id: str,
    quoter: str,
    token_in: str,
    token_out: str,
    size_usd: float,
    direction: str = "exact_in",
    fee: int = 0,
    tick_spacing: Optional[int] = None,
    block_bucket_id: str = "head",
) -> str:
    ts = f"ts{tick_spacing}" if tick_spacing is not None else f"f{fee}"
    return (
        f"{route_id}|{quoter.lower()}|{direction}|{token_in.lower()}|{token_out.lower()}"
        f"|{size_usd:.2f}|{ts}|{block_bucket_id}"
    )


def is_deterministic_reject(reason: str) -> bool:
    upper = str(reason or "").upper()
    if upper in _DETERMINISTIC_REJECTS:
        return True
    return upper.startswith("QUOTE_REVERT") or upper.startswith("QUOTE_FAIL_")


class QuoteNegativeCache:
    """In-memory TTL cache for quote reject reasons (not RPC transport errors)."""

    def __init__(self, *, ttl_s: float = DEFAULT_TTL_S) -> None:
        self.ttl_s = float(ttl_s)
        self._entries: Dict[str, tuple[str, float]] = {}
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Optional[str]:
        import time

        row = self._entries.get(key)
        if not row:
            self.misses += 1
            return None
        reason, ts = row
        if time.monotonic() - ts > self.ttl_s:
            del self._entries[key]
            self.misses += 1
            return None
        self.hits += 1
        return reason

    def put(self, key: str, reject_reason: str) -> None:
        import time

        if not reject_reason or reject_reason == "QUOTE_RPC_ERROR":
            return
        if not is_deterministic_reject(reject_reason):
            return
        self._entries[key] = (str(reject_reason), time.monotonic())

    def stats(self) -> Dict[str, Any]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "entry_count": len(self._entries),
            "ttl_s": self.ttl_s,
        }


class PersistentQuoteNegativeCache(PersistentTTLCacheBase):
    """Cross-run negative cache persisted under data/tmp."""

    def __init__(
        self,
        *,
        path: Path = DEFAULT_PERSISTENT_PATH,
        ttl_s: float = DEFAULT_TTL_S,
        flush_interval_s: float = 2.0,
    ) -> None:
        super().__init__(
            path=path,
            ttl_s=ttl_s,
            schema_version="m8_1_quote_negative_cache.2",
            flush_interval_s=flush_interval_s,
        )

    def put(self, key: str, reject_reason: str) -> None:
        super().put(
            key,
            reject_reason,
            accept=is_deterministic_reject,
        )

    def flush(self) -> None:
        super().flush()
