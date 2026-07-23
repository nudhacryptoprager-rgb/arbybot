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
        self.queue_wait_s = 0.0
        self.rpc_service_s = 0.0
        self.backoff_s = 0.0
        self._stats_lock = threading.Lock()

    def _sem_for(self, rpc_url: str) -> threading.Semaphore:
        key = str(rpc_url or "default").strip().lower()
        with self._lock:
            if key not in self._semaphores:
                self._semaphores[key] = threading.Semaphore(self.max_concurrent)
            return self._semaphores[key]

    def _is_rate_limit(self, exc: BaseException) -> bool:
        msg = str(exc).upper()
        return "429" in msg or "RATE" in msg or "TOO MANY" in msg

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
            queue_t0 = time.monotonic()
            acquired = sem.acquire(timeout=self.timeout_s)
            with self._stats_lock:
                self.queue_wait_s += max(0.0, time.monotonic() - queue_t0)
            if not acquired:
                with self._stats_lock:
                    self.provider_errors += 1
                raise TimeoutError(f"quote lane timeout waiting for {rpc_url}")

            released = False
            service_t0 = time.monotonic()
            try:
                return fn(*args, **kwargs)
            except Exception as exc:
                last_exc = exc
                if self._is_rate_limit(exc) and attempt + 1 < self.max_retries:
                    with self._stats_lock:
                        self.provider_errors += 1
                    sem.release()
                    released = True
                    sleep_s = min(8.0, 0.25 * (2**attempt))
                    with self._stats_lock:
                        self.backoff_s += sleep_s
                    time.sleep(sleep_s)
                    continue
                raise
            finally:
                if not released:
                    with self._stats_lock:
                        self.rpc_service_s += max(0.0, time.monotonic() - service_t0)
                    sem.release()
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("quote lane call failed without exception")

    def stats(self) -> Dict[str, Any]:
        with self._stats_lock:
            return {
                "provider_errors": int(self.provider_errors),
                "queue_wait_s": round(self.queue_wait_s, 3),
                "rpc_service_s": round(self.rpc_service_s, 3),
                "backoff_s": round(self.backoff_s, 3),
                "rpc_wait_s": round(
                    self.queue_wait_s + self.rpc_service_s + self.backoff_s,
                    3,
                ),
                "endpoints": len(self._semaphores),
            }
