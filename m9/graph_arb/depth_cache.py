"""Short-TTL cache for M9 depth probe results."""
from __future__ import annotations

import time
from typing import Any, Dict, Optional, Tuple

_DEFAULT_TTL_S = 90.0


def block_bucket(block_number: Optional[int], *, bucket_size: int = 32) -> str:
    if block_number is None:
        return "latest"
    try:
        bn = int(block_number)
    except (TypeError, ValueError):
        return "latest"
    if bn <= 0:
        return "latest"
    return str((bn // max(1, bucket_size)) * bucket_size)


def depth_cache_key(
    *,
    chain: str,
    dex_id: str,
    pool_address: str,
    token_in: str,
    token_out: str,
    block_number: Optional[int] = None,
) -> str:
    return ":".join(
        [
            str(chain or "base").lower(),
            str(dex_id or "").lower(),
            str(pool_address or "").lower(),
            str(token_in or "").lower(),
            str(token_out or "").lower(),
            block_bucket(block_number),
        ]
    )


class DepthProbeCache:
    """In-process TTL cache keyed by chain/dex/pool/token pair/block bucket."""

    def __init__(self, *, ttl_s: float = _DEFAULT_TTL_S) -> None:
        self.ttl_s = max(30.0, min(120.0, float(ttl_s)))
        self._store: Dict[str, Tuple[float, Dict[str, Any]]] = {}

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        row = self._store.get(key)
        if not row:
            return None
        expires_at, payload = row
        if time.monotonic() > expires_at:
            self._store.pop(key, None)
            return None
        return dict(payload)

    def set(self, key: str, payload: Dict[str, Any]) -> None:
        self._store[key] = (time.monotonic() + self.ttl_s, dict(payload))

    def clear(self) -> None:
        self._store.clear()
