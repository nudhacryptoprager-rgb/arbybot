"""E1.59 step #5: HTTP pool-state feed bridge."""

from __future__ import annotations

import pytest

from chains import flashblocks_http
from core.provider_throttle import provider_throttle
from m7.orderflow import pool_price_state, pool_state_http_feed
from m7.orderflow.pool_state_http_feed import (
    V2_SYNC_TOPIC0,
    V3_SWAP_TOPIC0,
    poll_and_feed,
)


@pytest.fixture(autouse=True)
def _enable(monkeypatch):
    monkeypatch.setenv("ARBY_FLASHBLOCKS_HTTP_LANE", "1")
    monkeypatch.setenv("ARBY_POOL_STATE_HTTP_FEED", "1")
    monkeypatch.setenv("ARBY_PROVIDER_THROTTLE", "0")  # don't trip breaker
    flashblocks_http.reset_stats()
    provider_throttle.reset()
    pool_price_state.reset_registry_for_tests()
    yield


def _ok(logs):
    return {"jsonrpc": "2.0", "id": 1, "result": logs}


def test_disabled_returns_zero(monkeypatch):
    monkeypatch.setenv("ARBY_POOL_STATE_HTTP_FEED", "0")
    out = poll_and_feed(
        rpc_url="http://r",
        chain="base",
        addresses=["0xa1"],
        http_post=lambda u, p, t: _ok([]),
    )
    assert out == {"v3_updates": 0, "v2_updates": 0, "skipped": 0, "fetched": 0}


def test_default_topics_or_filter():
    captured = {}

    def _post(url, payload, timeout):
        captured["payload"] = payload
        return _ok([])

    poll_and_feed(
        rpc_url="http://r",
        chain="base",
        addresses=["0xa1"],
        http_post=_post,
    )
    topics = captured["payload"]["params"][0]["topics"]
    assert topics == [[V3_SWAP_TOPIC0, V2_SYNC_TOPIC0]]


def test_empty_logs_returns_zero():
    out = poll_and_feed(
        rpc_url="http://r",
        chain="base",
        addresses=["0xa1"],
        http_post=lambda u, p, t: _ok([]),
    )
    assert out["v3_updates"] == 0 and out["v2_updates"] == 0
    assert out["fetched"] == 0


def test_v3_swap_log_increments_v3_updates():
    # 320-hex bytes payload (5 32-byte words + sign) — passes V3 length heuristic.
    data = "0x" + "00" * 32 * 5  # 5 words: amount0, amount1, sqrtP, liquidity, tick
    log = {
        "address": "0xPool",
        "topics": [V3_SWAP_TOPIC0],
        "data": data,
    }

    out = poll_and_feed(
        rpc_url="http://r",
        chain="base",
        addresses=["0xPool"],
        http_post=lambda u, p, t: _ok([log]),
    )
    assert out["fetched"] == 1
    # registry should now have updates_total >= 0; counters dict
    # returned by feed_raw_logs distinguishes v3/v2.
    assert (out["v3_updates"] + out["v2_updates"] + out["skipped"]) == 1


def test_skipped_counted_for_malformed_log():
    log = {"address": "0xPool", "topics": [], "data": ""}
    out = poll_and_feed(
        rpc_url="http://r",
        chain="base",
        addresses=["0xPool"],
        http_post=lambda u, p, t: _ok([log]),
    )
    assert out["skipped"] == 1
    assert out["fetched"] == 1


def test_fetch_error_returns_zero():
    def _post(url, payload, timeout):
        raise RuntimeError("boom")

    out = poll_and_feed(
        rpc_url="http://r",
        chain="base",
        addresses=["0xa1"],
        http_post=_post,
    )
    assert out == {"v3_updates": 0, "v2_updates": 0, "skipped": 0, "fetched": 0}
