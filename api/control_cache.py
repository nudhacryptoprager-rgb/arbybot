"""TTL-cached M_control projections built on ProjectionCache."""
from __future__ import annotations

import hashlib
import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from api.control_projection import ControlProjectionBuilder
from api.projections import ProjectionCache

__all__ = ["ControlProjectionCache", "get_control_projection_cache"]

_DEFAULT_TTL_S = 5.0

_CACHE_SINGLETON: Optional["ControlProjectionCache"] = None
_CACHE_LOCK = threading.Lock()


def get_control_projection_cache(
    repo_root: Path | str = ".",
    *,
    cache: Optional[ProjectionCache] = None,
    ttl_s: float = _DEFAULT_TTL_S,
) -> "ControlProjectionCache":
    """Process-wide singleton — legacy dashboard and API share one TTL cache."""
    global _CACHE_SINGLETON
    root = Path(repo_root)
    with _CACHE_LOCK:
        if _CACHE_SINGLETON is None or _CACHE_SINGLETON.repo_root != root:
            _CACHE_SINGLETON = ControlProjectionCache(root, cache=cache, ttl_s=ttl_s)
        return _CACHE_SINGLETON


class ControlProjectionCache:
    """Short-TTL cache for expensive multi-artifact control projections."""

    def __init__(
        self,
        repo_root: Path | str = ".",
        *,
        cache: Optional[ProjectionCache] = None,
        ttl_s: float = _DEFAULT_TTL_S,
    ) -> None:
        self.repo_root = Path(repo_root)
        self._builder = ControlProjectionBuilder(self.repo_root, cache or ProjectionCache())
        self._ttl_s = float(ttl_s)
        self._lock = threading.Lock()
        self._funnel: Optional[Dict[str, Any]] = None
        self._funnel_etag: Optional[str] = None
        self._funnel_ts: float = 0.0
        self._traces: Optional[Dict[str, Any]] = None
        self._traces_etag: Optional[str] = None
        self._traces_ts: float = 0.0

    @staticmethod
    def _etag_for(body: Dict[str, Any]) -> str:
        raw = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return f'W/"{hashlib.sha256(raw).hexdigest()[:16]}"'

    def funnel(self) -> Tuple[Dict[str, Any], str]:
        now = time.monotonic()
        with self._lock:
            if self._funnel is not None and (now - self._funnel_ts) < self._ttl_s:
                return self._funnel, self._funnel_etag or ""
            body = self._builder.build_funnel()
            etag = self._etag_for(body)
            self._funnel = body
            self._funnel_etag = etag
            self._funnel_ts = now
            return body, etag

    def traces(self) -> Tuple[Dict[str, Any], str]:
        now = time.monotonic()
        with self._lock:
            if self._traces is not None and (now - self._traces_ts) < self._ttl_s:
                return self._traces, self._traces_etag or ""
            body = self._builder.build_traces()
            etag = self._etag_for(body)
            self._traces = body
            self._traces_etag = etag
            self._traces_ts = now
            return body, etag
