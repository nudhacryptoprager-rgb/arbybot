# PATH: core/rpc_rate_limiter.py
"""Global RPC rate limiter — token-bucket algorithm.

Ensures total RPC calls across all code paths stay below a configurable
requests-per-second (RPS) limit.  Designed to keep dRPC free-tier (100 RPS)
happy without any paid plan.

Usage:
    from core.rpc_rate_limiter import rpc_throttle

    rpc_throttle.acquire()          # blocks until a token is available
    rpc_throttle.acquire(n=3)       # acquire multiple tokens (e.g. for V2 pair)

Environment variables:
    ARBY_RPC_RPS_LIMIT   — max requests/sec  (default: 80, safe under 100 RPS free tier)
    ARBY_RPC_RPS_BURST   — burst bucket size (default: 30, allows short bursts)
    ARBY_RPC_THROTTLE    — set "0" to disable throttling entirely
"""
from __future__ import annotations

import logging
import os
import threading
import time

logger = logging.getLogger("core.rpc_rate_limiter")

_RPS_LIMIT = int(os.environ.get("ARBY_RPC_RPS_LIMIT", "80"))
_BURST = int(os.environ.get("ARBY_RPC_RPS_BURST", "30"))
_ENABLED = os.environ.get("ARBY_RPC_THROTTLE", "1") != "0"


class TokenBucketRateLimiter:
    """Thread-safe token-bucket rate limiter."""

    def __init__(self, rps: int = _RPS_LIMIT, burst: int = _BURST):
        self.rps = max(rps, 1)
        self.burst = max(burst, 1)
        self._tokens = float(self.burst)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()
        self._total_waited_ms = 0.0
        self._total_acquired = 0
        self._total_waits = 0  # times we actually had to sleep

    def acquire(self, n: int = 1) -> None:
        """Block until *n* tokens are available, then consume them."""
        if not _ENABLED:
            return
        for _ in range(n):
            self._acquire_one()

    def _acquire_one(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                elapsed = now - self._last_refill
                self._tokens = min(
                    self.burst,
                    self._tokens + elapsed * self.rps,
                )
                self._last_refill = now

                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    self._total_acquired += 1
                    return

                # Calculate wait time for 1 token
                deficit = 1.0 - self._tokens
                wait_s = deficit / self.rps

            # Sleep outside lock
            self._total_waits += 1
            self._total_waited_ms += wait_s * 1000
            time.sleep(wait_s)

    def stats(self) -> dict:
        """Return throttle statistics."""
        return {
            "rps_limit": self.rps,
            "burst": self.burst,
            "total_acquired": self._total_acquired,
            "total_waits": self._total_waits,
            "total_waited_ms": round(self._total_waited_ms, 1),
            "enabled": _ENABLED,
        }


# Module-level singleton
rpc_throttle = TokenBucketRateLimiter()
