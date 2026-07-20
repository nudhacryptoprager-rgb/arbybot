"""Unit tests for chains.provider_quota and its AsyncRpcBatchClient wiring."""
from __future__ import annotations

import asyncio
import time

import pytest

from chains.provider_quota import AsyncProviderQuotaLimiter, ProviderQuota
from m8.discovery.scan_batch import AsyncRpcBatchClient


def test_quota_validation():
    with pytest.raises(ValueError):
        ProviderQuota(max_concurrent=0)
    with pytest.raises(ValueError):
        ProviderQuota(max_requests=-1)
    with pytest.raises(ValueError):
        ProviderQuota(window_s=0)


@pytest.mark.asyncio
async def test_concurrency_bound_enforced():
    limiter = AsyncProviderQuotaLimiter(
        {"alchemy": ProviderQuota(max_concurrent=2)},
    )
    in_flight = {"cur": 0, "max": 0}

    async def _job() -> None:
        async with limiter.acquire("alchemy"):
            in_flight["cur"] += 1
            in_flight["max"] = max(in_flight["max"], in_flight["cur"])
            await asyncio.sleep(0.02)
            in_flight["cur"] -= 1

    await asyncio.gather(*[_job() for _ in range(6)])
    assert in_flight["max"] <= 2
    assert limiter.stats["acquired"] == 6


@pytest.mark.asyncio
async def test_rate_window_throttles_and_recovers():
    limiter = AsyncProviderQuotaLimiter(
        {"drpc": ProviderQuota(max_concurrent=10, max_requests=2, window_s=0.15)},
    )

    async def _one() -> None:
        async with limiter.acquire("drpc"):
            return None

    t0 = time.monotonic()
    await asyncio.gather(*[_one() for _ in range(5)])
    elapsed = time.monotonic() - t0
    # 5 acquisitions at 2/window -> at least 2 window waits (~0.3s floor).
    assert elapsed >= 0.25
    assert limiter.stats["throttled"] >= 2
    assert limiter.stats["acquired"] == 5


@pytest.mark.asyncio
async def test_default_quota_applies_to_unknown_provider():
    limiter = AsyncProviderQuotaLimiter(
        {},
        default_quota=ProviderQuota(max_concurrent=1),
    )
    in_flight = {"cur": 0, "max": 0}

    async def _job() -> None:
        async with limiter.acquire("unknown_provider"):
            in_flight["cur"] += 1
            in_flight["max"] = max(in_flight["max"], in_flight["cur"])
            await asyncio.sleep(0.01)
            in_flight["cur"] -= 1

    await asyncio.gather(*[_job() for _ in range(3)])
    assert in_flight["max"] == 1


@pytest.mark.asyncio
async def test_independent_providers_do_not_share_windows():
    limiter = AsyncProviderQuotaLimiter(
        {
            "a": ProviderQuota(max_concurrent=1, max_requests=1, window_s=0.2),
            "b": ProviderQuota(max_concurrent=1, max_requests=1, window_s=0.2),
        }
    )

    async def _one(pid: str) -> None:
        async with limiter.acquire(pid):
            return None

    t0 = time.monotonic()
    await asyncio.gather(_one("a"), _one("b"))
    elapsed = time.monotonic() - t0
    # Distinct providers run in parallel — no cross-provider throttle.
    assert elapsed < 0.2


@pytest.mark.asyncio
async def test_batch_client_uses_quota_limiter(monkeypatch):
    calls: list[str] = []

    class _FakeResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return [{"jsonrpc": "2.0", "id": 0, "result": "0x1"}]

    class _FakeClient:
        def __init__(self, timeout: float = 0) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url: str, json=None):
            calls.append(url)
            return _FakeResponse()

    monkeypatch.setattr("httpx.AsyncClient", _FakeClient)
    limiter = AsyncProviderQuotaLimiter(
        {"p1": ProviderQuota(max_concurrent=1, max_requests=5, window_s=1.0)}
    )
    client = AsyncRpcBatchClient(
        ["http://p1.invalid"],
        quota_limiter=limiter,
        provider_ids=["p1"],
    )
    out = await client.batch_call([{"method": "eth_blockNumber", "params": []}])
    assert out and out[0]["result"] == "0x1"
    assert calls == ["http://p1.invalid"]
    assert limiter.stats["acquired"] == 1


@pytest.mark.asyncio
async def test_batch_client_without_limiter_keeps_legacy_behavior(monkeypatch):
    class _FakeResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return [{"jsonrpc": "2.0", "id": 0, "result": "0x2"}]

    class _FakeClient:
        def __init__(self, timeout: float = 0) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url: str, json=None):
            return _FakeResponse()

    monkeypatch.setattr("httpx.AsyncClient", _FakeClient)
    client = AsyncRpcBatchClient(["http://legacy.invalid"])
    out = await client.batch_call([{"method": "eth_blockNumber", "params": []}])
    assert out and out[0]["result"] == "0x2"


def test_batch_client_provider_ids_must_align():
    with pytest.raises(ValueError):
        AsyncRpcBatchClient(["http://a", "http://b"], provider_ids=["only-one"])
