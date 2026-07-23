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


def test_provider_quota_from_dict_permissive():
    from chains.provider_quota import ProviderQuota

    pq = ProviderQuota.from_dict({"max_concurrent": 8, "max_requests": 120, "window_s": 1.0})
    assert pq.max_concurrent == 8
    assert pq.max_requests == 120
    assert pq.window_s == 1.0
    # Coerces bad fields back to defaults
    pq2 = ProviderQuota.from_dict({"max_concurrent": "nonsense", "unknown": 1})
    assert pq2.max_concurrent == 4
    assert pq2.max_requests == 0


def test_build_limiter_from_provider_config_reads_yaml(tmp_path):
    """Step 6 fix: a real per-provider config in
    config/provider_quotas.yaml should drive the AsyncProviderQuotaLimiter
    instead of leaving it unreachable from production code."""
    from chains.provider_quota import (
        DEFAULT_PROVIDER_ID,
        build_limiter_from_provider_config,
    )

    yaml_path = tmp_path / "provider_quotas.yaml"
    yaml_path.write_text(
        """
default:
  max_concurrent: 4
  max_requests: 0
alchemy:
  max_concurrent: 8
  max_requests: 120
  window_s: 1.0
drpc:
  max_concurrent: 4
  max_requests: 60
  window_s: 1.0
""",
        encoding="utf-8",
    )
    limiter = build_limiter_from_provider_config(yaml_path, env={})
    assert limiter.quota_for("alchemy").max_concurrent == 8
    assert limiter.quota_for("alchemy").max_requests == 120
    assert limiter.quota_for("drpc").max_requests == 60
    # Unknown providers fall back to default quota (preserved via DEFAULT).
    assert limiter.quota_for(DEFAULT_PROVIDER_ID).max_concurrent == 4


def test_build_limiter_env_overrides_yaml(tmp_path):
    from chains.provider_quota import build_limiter_from_provider_config

    yaml_path = tmp_path / "pq.yaml"
    yaml_path.write_text(
        "alchemy:\n  max_concurrent: 8\n  max_requests: 120\n", encoding="utf-8"
    )
    env = {"ARBY_QUOTA_ALCHEMY": "2:5:1.0"}
    limiter = build_limiter_from_provider_config(yaml_path, env=env)
    assert limiter.quota_for("alchemy").max_concurrent == 2
    assert limiter.quota_for("alchemy").max_requests == 5


def test_build_limiter_handles_missing_file_and_invalid_yaml(tmp_path):
    """Missing/unreadable YAML -> fallback default quota; never crashes."""
    from chains.provider_quota import build_limiter_from_provider_config

    limiter = build_limiter_from_provider_config(
        tmp_path / "doesn_exist.yaml", env={}
    )
    # Default ProviderQuota = 4 concurrent, no rate window
    pq = limiter.quota_for("any_unknown_provider_id")
    assert pq.max_concurrent == 4
    assert pq.max_requests == 0


@pytest.mark.asyncio
async def test_batch_client_from_config_wires_real_limiter(tmp_path):
    """AsyncRpcBatchClient.from_config loads quotas from yaml so the
    production resolver path no longer constructs a limiter only in tests
    (production-readiness review issue 6)."""
    from chains.provider_quota import AsyncProviderQuotaLimiter  # noqa: F401

    yaml_path = tmp_path / "pq.yaml"
    yaml_path.write_text(
        "alchemy:\n  max_concurrent: 8\n  max_requests: 120\n  window_s: 1.0\n",
        encoding="utf-8",
    )
    client = AsyncRpcBatchClient.from_config(
        ["http://alchemy.invalid"],
        quota_yaml=yaml_path,
        provider_ids=["alchemy"],
    )
    assert client._quota_limiter is not None
    assert client._quota_limiter.quota_for("alchemy").max_concurrent == 8
    await client.close()


@pytest.mark.asyncio
async def test_batch_client_reuses_http_client_across_batches(monkeypatch):
    """Step 6 fix: the same httpx.AsyncClient must serve consecutive
    batch_call() invocations (no per-attempt client construction)."""
    creation_count = {"n": 0}

    class _FakeResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return [{"jsonrpc": "2.0", "id": 0, "result": "0x1"}]

    class _FakeClient:
        def __init__(self, timeout: float = 0) -> None:
            creation_count["n"] += 1

        async def post(self, url: str, json=None):
            return _FakeResponse()

        async def aclose(self) -> None:
            return None

    monkeypatch.setattr("httpx.AsyncClient", _FakeClient)
    client = AsyncRpcBatchClient(["http://x.invalid"])
    await client.batch_call([{"method": "eth_blockNumber", "params": []}])
    await client.batch_call([{"method": "eth_blockNumber", "params": []}])
    await client.batch_call([{"method": "eth_blockNumber", "params": []}])
    assert creation_count["n"] == 1, "httpx.AsyncClient created once and reused"
    await client.close()
