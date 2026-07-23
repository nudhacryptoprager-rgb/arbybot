"""Thread-safe persistent TTL cache with batched atomic flush."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from core.json_io import atomic_write_json
from core.path_lock import path_lock

EntryRow = Tuple[str, float]  # (value, monotonic_ts)


class PersistentTTLCacheBase:
    """In-memory TTL cache with mutex, dirty flag, and periodic atomic flush."""

    def __init__(
        self,
        *,
        path: Path,
        ttl_s: float,
        schema_version: str,
        flush_interval_s: float = 2.0,
    ) -> None:
        self.path = Path(path)
        self.ttl_s = float(ttl_s)
        self.schema_version = schema_version
        self.flush_interval_s = max(0.25, float(flush_interval_s))
        self._entries: Dict[str, EntryRow] = {}
        self._lock = threading.Lock()
        self._dirty = False
        self._last_flush_mono = 0.0
        self.hits = 0
        self.misses = 0
        self._load()

    def _row_to_disk(self, key: str, value: str, mono_ts: float, now: float) -> Dict[str, Any]:
        age = time.monotonic() - mono_ts
        return {
            "value": value,
            "expires_at_unix": now + max(0.0, self.ttl_s - age),
        }

    def _disk_to_row(self, row: Dict[str, Any], now: float) -> Optional[EntryRow]:
        value = str(row.get("value") or row.get("reason") or row.get("status") or "")
        expires_at = float(row.get("expires_at_unix") or 0.0)
        if expires_at <= now:
            return None
        remaining = max(0.0, expires_at - now)
        return value, time.monotonic() - self.ttl_s + remaining

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
            parsed = self._disk_to_row(row, now)
            if parsed is not None:
                self._entries[str(key)] = parsed

    def _serialize_entries_locked(self) -> Dict[str, Dict[str, Any]]:
        now = time.time()
        out: Dict[str, Dict[str, Any]] = {}
        expired: list[str] = []
        for key, (value, mono_ts) in self._entries.items():
            age = time.monotonic() - mono_ts
            if age >= self.ttl_s:
                expired.append(key)
                continue
            out[key] = self._row_to_disk(key, value, mono_ts, now)
        for key in expired:
            del self._entries[key]
        return out

    def _flush_locked(self, *, force: bool = False) -> None:
        if not self._dirty and not force:
            return
        now_mono = time.monotonic()
        if (
            not force
            and self._last_flush_mono > 0.0
            and (now_mono - self._last_flush_mono) < self.flush_interval_s
        ):
            return
        payload = {
            "schema_version": self.schema_version,
            "ttl_s": self.ttl_s,
            "entries": self._serialize_entries_locked(),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        with path_lock(lock_path):
            atomic_write_json(self.path, payload)
        self._dirty = False
        self._last_flush_mono = now_mono

    def get(self, key: str) -> Optional[str]:
        with self._lock:
            row = self._entries.get(key)
            if not row:
                self.misses += 1
                return None
            value, mono_ts = row
            if time.monotonic() - mono_ts > self.ttl_s:
                del self._entries[key]
                self.misses += 1
                self._dirty = True
                self._flush_locked()
                return None
            self.hits += 1
            return value

    def put(self, key: str, value: str, *, accept: Optional[Callable[[str], bool]] = None) -> None:
        if accept is not None and not accept(value):
            return
        with self._lock:
            self._entries[key] = (str(value), time.monotonic())
            self._dirty = True
            self._flush_locked()

    def flush(self) -> None:
        with self._lock:
            self._flush_locked(force=True)

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "hits": self.hits,
                "misses": self.misses,
                "entry_count": len(self._entries),
                "ttl_s": self.ttl_s,
                "path": str(self.path),
            }
