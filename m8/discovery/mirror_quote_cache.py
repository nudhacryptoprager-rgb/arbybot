"""Short-TTL quote result cache for mirror smoke probes."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from core.persistent_ttl_cache import PersistentTTLCacheBase

DEFAULT_TTL_S = 300.0
DEFAULT_PERSISTENT_PATH = Path("data/tmp/m8_mirror_quote_cache_latest.json")


def mirror_quote_cache_key(
    *,
    route_id: str,
    direction: str,
    amount_wei: int,
    block_bucket: str = "head",
) -> str:
    return f"{route_id}|{direction}|{int(amount_wei)}|{block_bucket}"


class MirrorQuoteCache:
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
        status, ts = row
        if time.monotonic() - ts > self.ttl_s:
            del self._entries[key]
            self.misses += 1
            return None
        self.hits += 1
        return status

    def put(self, key: str, status: str) -> None:
        import time

        self._entries[key] = (str(status), time.monotonic())

    def stats(self) -> Dict[str, Any]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "entry_count": len(self._entries),
            "ttl_s": self.ttl_s,
        }


class PersistentMirrorQuoteCache(PersistentTTLCacheBase):
    """Cross-run mirror quote cache persisted under data/tmp."""

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
            schema_version="m8_mirror_quote_cache.2",
            flush_interval_s=flush_interval_s,
        )

    def put(self, key: str, status: str) -> None:
        super().put(key, status)

    def flush(self) -> None:
        super().flush()
