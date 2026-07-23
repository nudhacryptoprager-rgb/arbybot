"""Per-RPC-endpoint concurrency limiter with 429 backoff for quote lanes."""
from __future__ import annotations

import threading
import time
from typing import Any, Callable, Dict, Optional, TypeVar

T = TypeVar("T")

_DEFAULT_MAX_CONCURRENT = 2
_DEFAULT_TIMEOUT_S = 15.0
_DEFAULT_MAX_RETRIES = 3


class QuoteLaneLimiter:
    """Semaphore per RPC URL; retries transient rate-limit errors."""

    def __init__(
        self,
        *,
        max_concurrent: int = _DEFAULT_MAX_CONCURRENT,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        max_retries: int = _DEFAULT_MAX_RETRIES,
    ) -> None:
        self.max_concurrent = max(1, int(max_concurrent))
        self.timeout_s = float(timeout_s)
        self.max_retries = max(1, int(max_retries))
        self._semaphores: Dict[str, threading.Semaphore] = {}
        self._lock = threading.Lock()
        self.provider_errors = 0
        self.rpc_wait_s = 0.0

    def _sem_for(self, rpc_url: str) -> threading.Semaphore:
        key = str(rpc_url or "default").strip().lower()
        with self._lock:
            if key not in self._semaphores:
                self._semaphores[key] = threading.Semaphore(self.max_concurrent)
            return self._semaphores[key]

    def call(
        self,
        rpc_url: str,
        fn: Callable[..., T],
        *args: Any,
        **kwargs: Any,
    ) -> T:
        sem = self._sem_for(rpc_url)
        last_exc: Optional[BaseException] = None
        for attempt in range(self.max_retries):
            acquired = sem.acquire(timeout=self.timeout_s)
            if not acquired:
                self.provider_errors += 1
                raise TimeoutError(f"quote lane timeout waiting for {rpc_url}")
            wait_t0 = time.monotonic()
            try:
                return fn(*args, **kwargs)
            except Exception as exc:
                last_exc = exc
                msg = str(exc).upper()
                if "429" in msg or "RATE" in msg or "TOO MANY" in msg:
                    self.provider_errors += 1
                    if attempt + 1 < self.max_retries:
                        time.sleep(min(8.0, 0.25 * (2**attempt)))
                        continue
                raise
            finally:
                self.rpc_wait_s += max(0.0, time.monotonic() - wait_t0)
                sem.release()
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("quote lane call failed without exception")

    def stats(self) -> Dict[str, Any]:
        return {
            "provider_errors": int(self.provider_errors),
            "rpc_wait_s": round(self.rpc_wait_s, 3),
            "endpoints": len(self._semaphores),
        }
