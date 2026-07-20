"""Provider quota limiter — bounded concurrency + rate windows per RPC provider.

Motivation (production-readiness review): hot-path steps must be throttled by
*provider quota*, not by a single global semaphore.  Different providers
(Alchemy, dRPC, public endpoints) have different rate budgets; exceeding
them produces 429 storms and quarantine churn.

Design:

* ``ProviderQuota`` — per-provider budget: ``max_concurrent`` in-flight
  requests plus ``max_requests`` per ``window_s`` (token-bucket rate window).
* ``AsyncProviderQuotaLimiter`` — asyncio limiter holding one semaphore and
  one rate window per provider id.  ``acquire(provider_id)`` is an async
  context manager; throttling is counted in ``stats``.

The limiter is dependency-free and offline-testable.
"""
from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Dict, Optional

__all__ = [
    "ProviderQuota",
    "AsyncProviderQuotaLimiter",
]


@dataclass(frozen=True)
class ProviderQuota:
    """Budget for one provider.

    ``max_concurrent`` caps in-flight requests; ``max_requests`` per
    ``window_s`` caps the sustained rate (0 disables the rate window).
    """

    max_concurrent: int = 4
    max_requests: int = 0          # 0 = no rate window
    window_s: float = 1.0

    def __post_init__(self) -> None:
        if self.max_concurrent < 1:
            raise ValueError("max_concurrent must be >= 1")
        if self.max_requests < 0:
            raise ValueError("max_requests must be >= 0")
        if self.window_s <= 0:
            raise ValueError("window_s must be > 0")


@dataclass
class _ProviderState:
    semaphore: asyncio.Semaphore
    window_started_mono: float = field(default_factory=time.monotonic)
    window_used: int = 0


class AsyncProviderQuotaLimiter:
    """Async limiter combining per-provider concurrency + rate windows."""

    def __init__(
        self,
        quotas: Dict[str, ProviderQuota],
        *,
        default_quota: Optional[ProviderQuota] = None,
        sleep=asyncio.sleep,
    ) -> None:
        self._quotas = dict(quotas)
        self._default_quota = default_quota or ProviderQuota()
        self._states: Dict[str, _ProviderState] = {}
        self._state_lock = asyncio.Lock()
        self._sleep = sleep
        self.stats: Dict[str, Any] = {
            "acquired": 0,
            "throttled": 0,
            "total_throttle_wait_s": 0.0,
        }

    def quota_for(self, provider_id: str) -> ProviderQuota:
        return self._quotas.get(provider_id, self._default_quota)

    async def _state_for(self, provider_id: str) -> _ProviderState:
        """Return (creating under lock) the per-provider state."""
        state = self._states.get(provider_id)
        if state is not None:
            return state
        async with self._state_lock:
            state = self._states.get(provider_id)
            if state is None:
                quota = self.quota_for(provider_id)
                state = _ProviderState(
                    semaphore=asyncio.Semaphore(quota.max_concurrent)
                )
                self._states[provider_id] = state
            return state

    async def _await_rate_window(self, provider_id: str) -> None:
        quota = self.quota_for(provider_id)
        if quota.max_requests <= 0:
            return
        state = await self._state_for(provider_id)
        while True:
            async with self._state_lock:
                now = time.monotonic()
                elapsed = now - state.window_started_mono
                if elapsed >= quota.window_s:
                    state.window_started_mono = now
                    state.window_used = 0
                    elapsed = 0.0
                if state.window_used < quota.max_requests:
                    state.window_used += 1
                    return
                wait_s = max(quota.window_s - elapsed, 0.0)
                self.stats["throttled"] += 1
                self.stats["total_throttle_wait_s"] += wait_s
            # Sleep outside the lock so other providers proceed.
            await self._sleep(wait_s)

    @asynccontextmanager
    async def acquire(self, provider_id: str) -> AsyncIterator[None]:
        """Acquire one unit of provider budget (concurrency + rate window)."""
        state = await self._state_for(provider_id)
        await state.semaphore.acquire()
        try:
            await self._await_rate_window(provider_id)
            self.stats["acquired"] += 1
            yield
        finally:
            state.semaphore.release()

    def stats_snapshot(self) -> Dict[str, Any]:
        return dict(self.stats)
