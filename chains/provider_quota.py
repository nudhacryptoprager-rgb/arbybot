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
* ``build_limiter_from_provider_config`` — load per-provider budgets from a
  canonical ``config/provider_quotas.yaml`` file or an in-process dict so
  the production resolver/clients construct the limiter from *real provider
  configuration* (Step 6 of the production-readiness review) instead of
  leaving ``AsyncProviderQuotaLimiter`` unreferenced outside tests.

The limiter is dependency-free and offline-testable.
"""
from __future__ import annotations

import asyncio
import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator, Dict, Mapping, Optional

__all__ = [
    "ProviderQuota",
    "AsyncProviderQuotaLimiter",
    "build_limiter_from_provider_config",
    "DEFAULT_PROVIDER_QUOTAS_YAML",
    "DEFAULT_PROVIDER_ID",
]


# Default path for the canonical per-provider quota config. The file is
# optional — when absent the limiter falls back to ``ProviderQuota()``
# (max_concurrent=4, no rate window).
DEFAULT_PROVIDER_QUOTAS_YAML = Path("config") / "provider_quotas.yaml"

# Provider id used when no explicit provider mapping is supplied. Callers
# can label every RPC URL with this id so the limiter applies *some*
# throttling even without per-provider budgets.
DEFAULT_PROVIDER_ID = "default"


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

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "ProviderQuota":
        """Permissive builder: ignore unknown keys; coerce major fields."""
        try:
            max_concurrent = int(data.get("max_concurrent", 4))
        except (TypeError, ValueError):
            max_concurrent = 4
        try:
            max_requests = int(data.get("max_requests", 0))
        except (TypeError, ValueError):
            max_requests = 0
        try:
            window_s = float(data.get("window_s", 1.0))
        except (TypeError, ValueError):
            window_s = 1.0
        return cls(
            max_concurrent=max_concurrent,
            max_requests=max_requests,
            window_s=window_s,
        )


def build_limiter_from_provider_config(
    yaml_path: Optional[Path] = None,
    *,
    env: Optional[Mapping[str, str]] = None,
) -> AsyncProviderQuotaLimiter:
    """Build an ``AsyncProviderQuotaLimiter`` from provider configuration.

    Loads a YAML mapping of ``provider_id -> {max_concurrent, max_requests,
    window_s}``. When the file is missing or unparseable, the limiter
    falls back to a single ``DEFAULT_PROVIDER_ID`` quota of 4 concurrent /
    no rate window — still better than no limiter, and resilient.

    Environment overrides (per-provider ``ARBY_QUOTA_<PROVIDER_ID>`` of the
    form ``max_concurrent:max_requests:window_s``) take precedence over the
    YAML file so operators can tune a quota without editing the repo.
    """
    quotas: Dict[str, ProviderQuota] = {}
    path = Path(yaml_path) if yaml_path is not None else DEFAULT_PROVIDER_QUOTAS_YAML
    try:
        import yaml  # type: ignore

        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    except (OSError, ValueError, ImportError):
        data = {}

    if isinstance(data, Mapping):
        for key, value in data.items():
            if not isinstance(value, Mapping):
                continue
            try:
                quotas[str(key)] = ProviderQuota.from_dict(value)
            except ValueError:
                continue

    env_map = env if env is not None else os.environ
    for ek, ev in env_map.items():
        if not ek.startswith("ARBY_QUOTA_"):
            continue
        pid = ek[len("ARBY_QUOTA_"):].lower()
        if not pid:
            continue
        parts = str(ev).split(":")
        if len(parts) < 2:
            continue
        try:
            mc = int(parts[0])
            mr = int(parts[1])
            ws = float(parts[2]) if len(parts) >= 3 else 1.0
            quotas[pid] = ProviderQuota(
                max_concurrent=mc, max_requests=mr, window_s=ws
            )
        except ValueError:
            continue

    default_quota = quotas.pop(DEFAULT_PROVIDER_ID, None) or ProviderQuota()
    return AsyncProviderQuotaLimiter(
        quotas=quotas,
        default_quota=default_quota,
    )


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
