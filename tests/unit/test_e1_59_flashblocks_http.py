"""E1.59 step #3: HTTP-only Flashblocks pending-logs lane."""

from __future__ import annotations

import pytest

from chains import flashblocks_http
from core.provider_throttle import provider_throttle


@pytest.fixture(autouse=True)
def _enable(monkeypatch):
    monkeypatch.setenv("ARBY_FLASHBLOCKS_HTTP_LANE", "1")
    monkeypatch.setenv("ARBY_PROVIDER_THROTTLE", "1")
    flashblocks_http.reset_stats()
    provider_throttle.reset()
    yield


def _ok_response(logs):
    return {"jsonrpc": "2.0", "id": 1, "result": logs}


def test_disabled_returns_empty(monkeypatch):
    monkeypatch.setenv("ARBY_FLASHBLOCKS_HTTP_LANE", "0")

    def _post(url, payload, timeout):
        raise AssertionError("must not be called")

    out = flashblocks_http.fetch_pending_pool_logs(
        rpc_url="http://x", addresses=["0xabc"], http_post=_post,
    )
    assert out == []


def test_empty_addresses_rejected():
    def _post(url, payload, timeout):
        raise AssertionError("must not be called")

    out = flashblocks_http.fetch_pending_pool_logs(
        rpc_url="http://x", addresses=[], http_post=_post,
    )
    assert out == []


def test_payload_uses_pending_tag_and_addresses_and_topics():
    captured = {}

    def _post(url, payload, timeout):
        captured["url"] = url
        captured["payload"] = payload
        captured["timeout"] = timeout
        return _ok_response([])

    flashblocks_http.fetch_pending_pool_logs(
        rpc_url="http://rpc",
        addresses=["0xa1", "0xa2"],
        topics=["0xtopic0"],
        http_post=_post,
        timeout_s=2.5,
    )
    p = captured["payload"]
    assert p["method"] == "eth_getLogs"
    assert p["params"][0]["fromBlock"] == "pending"
    assert p["params"][0]["toBlock"] == "pending"
    assert p["params"][0]["address"] == ["0xa1", "0xa2"]
    assert p["params"][0]["topics"] == ["0xtopic0"]
    assert captured["timeout"] == 2.5
    assert captured["url"] == "http://rpc"


def test_single_address_unwrapped():
    captured = {}

    def _post(url, payload, timeout):
        captured["payload"] = payload
        return _ok_response([])

    flashblocks_http.fetch_pending_pool_logs(
        rpc_url="http://rpc", addresses=["0xa1"], http_post=_post,
    )
    assert captured["payload"]["params"][0]["address"] == "0xa1"


def test_ok_returns_logs_and_updates_stats():
    logs = [{"address": "0xa1"}, {"address": "0xa1"}, {"address": "0xa1"}]

    def _post(url, payload, timeout):
        return _ok_response(logs)

    out = flashblocks_http.fetch_pending_pool_logs(
        rpc_url="http://rpc", addresses=["0xa1"], http_post=_post,
    )
    assert out == logs
    s = flashblocks_http.stats()
    assert s["calls_attempted"] == 1
    assert s["calls_ok"] == 1
    assert s["logs_returned_total"] == 3


def test_timeout_records_408_and_opens_breaker():
    def _post(url, payload, timeout):
        raise TimeoutError("slow")

    out = flashblocks_http.fetch_pending_pool_logs(
        rpc_url="http://rpc", addresses=["0xa1"], http_post=_post,
    )
    assert out == []
    s = flashblocks_http.stats()
    assert s["calls_408"] == 1
    snap = provider_throttle.snapshot()
    assert snap["logs"]["breaker_open"] is True


def test_429_in_error_envelope_recorded():
    def _post(url, payload, timeout):
        return {"jsonrpc": "2.0", "id": 1, "error": {"code": -32005, "message": "rate limit exceeded"}}

    out = flashblocks_http.fetch_pending_pool_logs(
        rpc_url="http://rpc", addresses=["0xa1"], http_post=_post,
    )
    assert out == []
    s = flashblocks_http.stats()
    assert s["calls_429"] == 1
    assert provider_throttle.snapshot()["logs"]["breaker_open"] is True


def test_breaker_blocks_subsequent_calls():
    # Pre-trip the breaker.
    provider_throttle.record_response("logs", status_code=429)
    called = {"n": 0}

    def _post(url, payload, timeout):
        called["n"] += 1
        return _ok_response([])

    out = flashblocks_http.fetch_pending_pool_logs(
        rpc_url="http://rpc", addresses=["0xa1"], http_post=_post,
    )
    assert out == []
    assert called["n"] == 0
    assert flashblocks_http.stats()["calls_blocked_by_breaker"] == 1


def test_non_list_result_handled():
    def _post(url, payload, timeout):
        return {"jsonrpc": "2.0", "id": 1, "result": "not-a-list"}

    out = flashblocks_http.fetch_pending_pool_logs(
        rpc_url="http://rpc", addresses=["0xa1"], http_post=_post,
    )
    assert out == []
    assert flashblocks_http.stats()["calls_other_error"] == 1


def test_transport_exception_other_error():
    def _post(url, payload, timeout):
        raise RuntimeError("boom")

    out = flashblocks_http.fetch_pending_pool_logs(
        rpc_url="http://rpc", addresses=["0xa1"], http_post=_post,
    )
    assert out == []
    s = flashblocks_http.stats()
    assert s["calls_other_error"] == 1
    assert "boom" in (s["last_error"] or "")
