"""Short-TTL quote result cache for mirror smoke probes."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

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
        self._entries: Dict[str, Tuple[str, float]] = {}
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> Optional[str]:
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
        self._entries[key] = (str(status), time.monotonic())

    def stats(self) -> Dict[str, Any]:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "entry_count": len(self._entries),
            "ttl_s": self.ttl_s,
        }


class PersistentMirrorQuoteCache(MirrorQuoteCache):
    """Cross-run mirror quote cache persisted under data/tmp."""

    def __init__(
        self,
        *,
        path: Path = DEFAULT_PERSISTENT_PATH,
        ttl_s: float = DEFAULT_TTL_S,
    ) -> None:
        super().__init__(ttl_s=ttl_s)
        self.path = Path(path)
        self._load()

    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            doc = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        now = time.time()
        for key, row in (doc.get("entries") or {}).items():
            if not isinstance(row, dict):
                continue
            status = str(row.get("status") or "")
            expires_at = float(row.get("expires_at_unix") or 0.0)
            if expires_at <= now:
                continue
            remaining = max(0.0, expires_at - now)
            self._entries[str(key)] = (status, time.monotonic() - self.ttl_s + remaining)

    def _save(self) -> None:
        now = time.time()
        entries: Dict[str, Dict[str, Any]] = {}
        for key, (status, mono_ts) in self._entries.items():
            age = time.monotonic() - mono_ts
            if age >= self.ttl_s:
                continue
            entries[key] = {
                "status": status,
                "expires_at_unix": now + (self.ttl_s - age),
            }
        payload = {
            "schema_version": "m8_mirror_quote_cache.1",
            "ttl_s": self.ttl_s,
            "entries": entries,
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def put(self, key: str, status: str) -> None:
        super().put(key, status)
        self._save()
