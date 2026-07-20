"""Unit tests for core.typed_outcomes and its scan_batch wiring."""
from __future__ import annotations

import asyncio
import json

import pytest

from core.typed_outcomes import (
    Outcome,
    ReasonCode,
    outcome_from_exception,
    outcome_from_http_status,
)
from m8.discovery.scan_batch import AsyncRpcBatchClient


# ---------------------------------------------------------------------------
# Taxonomy
# ---------------------------------------------------------------------------


def test_http_status_mapping_and_retryability():
    assert outcome_from_http_status(408).reason_code == ReasonCode.RPC_REQUEST_TIMEOUT
    assert outcome_from_http_status(408).retryable is True
    assert outcome_from_http_status(429).reason_code == ReasonCode.RPC_RATE_LIMITED
    assert outcome_from_http_status(429).retryable is True
    assert outcome_from_http_status(503).reason_code == ReasonCode.RPC_SERVER_ERROR
    assert outcome_from_http_status(503).retryable is True
    unknown = outcome_from_http_status(418)
    assert unknown.reason_code == ReasonCode.INTERNAL_UNKNOWN
    assert unknown.retryable is False


def test_exception_classification():
    assert (
        outcome_from_exception(TimeoutError("t")).reason_code == ReasonCode.RPC_TIMEOUT
    )
    assert (
        outcome_from_exception(asyncio.TimeoutError()).reason_code
        == ReasonCode.RPC_TIMEOUT
    )
    assert (
        outcome_from_exception(ConnectionResetError("x")).reason_code
        == ReasonCode.RPC_CONNECTION_ERROR
    )
    assert (
        outcome_from_exception(json.JSONDecodeError("m", "doc", 0)).reason_code
        == ReasonCode.ARTIFACT_DECODE_ERROR
    )
    assert (
        outcome_from_exception(OSError("disk")).reason_code
        == ReasonCode.ARTIFACT_IO_ERROR
    )


def test_unknown_exception_maps_to_internal_unknown_non_retryable():
    class WeirdError(Exception):
        pass

    outcome = outcome_from_exception(WeirdError("strange"), stage="m9_shadow")
    assert outcome.ok is False
    assert outcome.reason_code == ReasonCode.INTERNAL_UNKNOWN
    assert outcome.retryable is False
    assert outcome.stage == "m9_shadow"
    assert "WeirdError" in (outcome.detail or "")


def test_httpx_style_status_error_duck_typed():
    class Resp:
        status_code = 429

    class HTTPStatusError(Exception):
        response = Resp()

    outcome = outcome_from_exception(HTTPStatusError("rate"))
    assert outcome.reason_code == ReasonCode.RPC_RATE_LIMITED
    assert outcome.retryable is True


def test_outcome_success_and_to_dict():
    ok = Outcome.success(provider="alchemy", stage="ingest")
    assert ok.ok and ok.provider == "alchemy"
    d = ok.to_dict()
    assert d["ok"] is True and d["stage"] == "ingest"


# ---------------------------------------------------------------------------
# AsyncRpcBatchClient wiring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_client_records_typed_outcome_on_429(monkeypatch):
    class _FakeResponse:
        status_code = 429

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {}

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
    monkeypatch.setattr(asyncio, "sleep", _instant_sleep)
    client = AsyncRpcBatchClient(["http://p1.invalid"], provider_ids=["alchemy"])
    out = await client.batch_call([{"method": "eth_blockNumber", "params": []}])
    assert out == []
    assert client.stats["429"] == 1
    assert client.last_outcomes
    assert client.last_outcomes[0].reason_code == ReasonCode.RPC_RATE_LIMITED
    assert client.last_outcomes[0].retryable is True
    assert client.last_outcomes[0].provider == "alchemy"


@pytest.mark.asyncio
async def test_batch_client_records_typed_outcome_on_exception(monkeypatch):
    class _FakeClient:
        def __init__(self, timeout: float = 0) -> None:
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url: str, json=None):
            raise TimeoutError("slow")

    monkeypatch.setattr("httpx.AsyncClient", _FakeClient)
    client = AsyncRpcBatchClient(["http://p1.invalid"], provider_ids=["drpc"])
    out = await client.batch_call([{"method": "eth_blockNumber", "params": []}])
    assert out == []
    assert client.stats["errors"] == 1
    assert client.last_outcomes[0].reason_code == ReasonCode.RPC_TIMEOUT
    assert client.last_outcomes[0].retryable is True


async def _instant_sleep(_seconds: float) -> None:
    return None
