"""Materialized projections over runtime artifacts.

The dashboard/API must not re-parse multi-megabyte artifacts on every
request.  ``ProjectionCache`` caches parsed JSON keyed by ``(path, mtime,
size)``; a changed file is re-read exactly once.  Every projection carries
an ETag (weak content hash) so clients can use ``If-None-Match``.

Read-only: this module never writes to ``data/**``.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Optional, Tuple, Union

__all__ = ["Projection", "ProjectionCache"]


class Projection:
    """One materialized artifact projection with ETag metadata."""

    __slots__ = ("path", "data", "etag", "mtime", "size")

    def __init__(self, path: Path, data: Any, etag: str, mtime: float, size: int) -> None:
        self.path = path
        self.data = data
        self.etag = etag
        self.mtime = mtime
        self.size = size


class ProjectionCache:
    """mtime/size-keyed cache for parsed artifact JSON."""

    def __init__(self) -> None:
        self._cache: Dict[str, Projection] = {}
        self.hits: int = 0
        self.misses: int = 0

    @staticmethod
    def _etag_for(raw: bytes) -> str:
        digest = hashlib.sha256(raw).hexdigest()[:16]
        return f'W/"{digest}"'

    def get(self, path: Union[str, Path]) -> Optional[Projection]:
        """Return the projection for *path* (None when missing/unreadable).

        Re-parses only when the file changed (mtime or size); otherwise
        serves the cached projection.
        """
        p = Path(path)
        key = str(p)
        try:
            stat = p.stat()
        except OSError:
            self._cache.pop(key, None)
            return None
        cached = self._cache.get(key)
        if cached is not None and cached.mtime == stat.st_mtime and cached.size == stat.st_size:
            self.hits += 1
            return cached
        try:
            raw = p.read_bytes()
            data = json.loads(raw.decode("utf-8"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            return None
        projection = Projection(
            path=p,
            data=data,
            etag=self._etag_for(raw),
            mtime=stat.st_mtime,
            size=stat.st_size,
        )
        self._cache[key] = projection
        self.misses += 1
        return projection

    def stats(self) -> Dict[str, int]:
        return {
            "entries": len(self._cache),
            "hits": self.hits,
            "misses": self.misses,
        }
