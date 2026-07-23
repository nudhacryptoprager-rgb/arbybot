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


# ---------------------------------------------------------------------------
# Step 7 — typed outcome as part of stage result (review issue 7)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_batch_client_last_failure_summary_returns_non_retryable_when_internal_unknown(monkeypatch):
    """When every attempt ended in INTERNAL_UNKNOWN, ``last_failure_summary``
    must return a non-retryable Outcome so the caller can surface it as
    stage FAILED (not silently treat the empty return as "no data")."""

    class _FakeClient:
        def __init__(self, timeout: float = 0) -> None:
            pass

        async def post(self, url: str, json=None):
            # Duck-typed to trigger INTERNAL_UNKNOWN through outcome_from_exception.
            class _WeirdError(Exception):
                pass
            raise _WeirdError("unknown")

    monkeypatch.setattr("httpx.AsyncClient", _FakeClient)
    client = AsyncRpcBatchClient(["http://x.invalid"])
    out = await client.batch_call([{"method": "eth_blockNumber", "params": []}])
    assert out == []
    summary = client.last_failure_summary()
    assert summary is not None
    assert summary.ok is False
    assert summary.retryable is False
    assert summary.reason_code == ReasonCode.INTERNAL_UNKNOWN


@pytest.mark.asyncio
async def test_batch_client_last_failure_summary_returns_none_when_no_outcomes(monkeypatch):
    """An empty batch returns [] with no recorded outcomes; the summary must
    report None so callers cannot mistake an intentional no-op for a failure."""
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: None)
    client = AsyncRpcBatchClient(["http://x.invalid"])
    out = await client.batch_call([])  # no payloads -> legacy contract = []
    assert out == []
    assert client.last_failure_summary() is None


def test_stage_result_hard_failure_distinguishes_retryable_and_hard():
    """StageResult.hard_failure must be True only for non-retryable typed
    failures, so a downstream stage can choose to retry transient failures
    instead of failing the whole pipeline."""
    from application.pipeline_stage import StageResult

    # Succeeded stage: no typed outcome
    ok = StageResult(name="s", exit_code=0, duration_s=0.1, outcome="ok")
    assert ok.hard_failure is False
    # Hard failure: INTERNAL_UNKNOWN (non-retryable)
    hard_outcome = Outcome.failure(
        ReasonCode.INTERNAL_UNKNOWN, detail="boom", stage="s"
    )
    hard = StageResult(
        name="s",
        exit_code=1,
        duration_s=0.1,
        outcome="failed",
        typed_outcome=hard_outcome,
    )
    assert hard.hard_failure is True
    # Retryable failure (rate-limited, transient) is NOT a hard failure
    retryable = Outcome.failure(
        ReasonCode.RPC_RATE_LIMITED, detail="rtt", retryable=True
    )
    soft = StageResult(
        name="s",
        exit_code=1,
        duration_s=0.1,
        outcome="failed",
        typed_outcome=retryable,
    )
    assert soft.hard_failure is False


def test_classify_typed_outcome_prefers_non_retryable_over_retryable():
    from application.pipeline_stage import classify_typed_outcome

    recorded = [
        Outcome.failure(ReasonCode.RPC_TIMEOUT, retryable=True),
        Outcome.failure(ReasonCode.INTERNAL_UNKNOWN, retryable=False),
        Outcome.failure(ReasonCode.RPC_RATE_LIMITED, retryable=True),
    ]
    result = classify_typed_outcome(exit_code=1, fail_reason=None, typed_failures=recorded)
    assert result is not None
    assert result.reason_code == ReasonCode.INTERNAL_UNKNOWN
    assert result.retryable is False


def test_classify_typed_outcome_falls_back_to_retryable_when_only_retryables_present():
    from application.pipeline_stage import classify_typed_outcome

    recorded = [
        Outcome.failure(ReasonCode.RPC_TIMEOUT, retryable=True),
        Outcome.failure(ReasonCode.RPC_RATE_LIMITED, retryable=True),
    ]
    result = classify_typed_outcome(exit_code=1, fail_reason=None, typed_failures=recorded)
    assert result is not None
    assert result.retryable is True


def test_classify_typed_outcome_maps_hard_timeout_to_retryable_timeout():
    from application.pipeline_stage import classify_typed_outcome

    result = classify_typed_outcome(
        exit_code=124, fail_reason="hard_timeout_60s", typed_failures=[]
    )
    assert result is not None
    assert result.reason_code == ReasonCode.RPC_TIMEOUT
    assert result.retryable is True


def test_classify_typed_outcome_no_records_no_fail_reason_is_internal_unknown():
    from application.pipeline_stage import classify_typed_outcome

    result = classify_typed_outcome(exit_code=2, fail_reason=None, typed_failures=[])
    assert result is not None
    assert result.reason_code == ReasonCode.INTERNAL_UNKNOWN
    assert result.retryable is False


def test_classify_typed_outcome_zero_exit_is_success():
    from application.pipeline_stage import classify_typed_outcome

    result = classify_typed_outcome(exit_code=0, fail_reason=None, typed_failures=[])
    assert result is not None and result.ok is True
