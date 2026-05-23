"""E1.59 step #2: provider throttle policy + 408/429 breaker."""

from __future__ import annotations

import os

import pytest

from core.provider_throttle import ProviderThrottle, provider_throttle


@pytest.fixture(autouse=True)
def _enable(monkeypatch):
    monkeypatch.setenv("ARBY_PROVIDER_THROTTLE", "1")
    yield


def test_default_off_returns_true(monkeypatch):
    monkeypatch.setenv("ARBY_PROVIDER_THROTTLE", "0")
    pt = ProviderThrottle()
    # Disabled => always cleared, no token consumed.
    assert pt.acquire("logs") is True
    pt.record_response("logs", status_code=429)
    assert pt.acquire("logs") is True


def test_acquire_returns_true_when_clear():
    pt = ProviderThrottle()
    assert pt.acquire("logs", blocking=False) is True
    assert pt.acquire("calls", blocking=False) is True


def test_429_opens_breaker():
    pt = ProviderThrottle()
    pt.record_response("logs", status_code=429)
    assert pt.acquire("logs", blocking=False) is False
    snap = pt.snapshot()
    assert snap["logs"]["breaker_open"] is True
    assert snap["logs"]["total_429"] == 1
    assert snap["logs"]["consec_failures"] == 1


def test_408_opens_breaker():
    pt = ProviderThrottle()
    pt.record_response("calls", status_code=408)
    assert pt.acquire("calls", blocking=False) is False
    snap = pt.snapshot()
    assert snap["calls"]["total_408"] == 1


def test_consecutive_failures_extend_cooldown():
    pt = ProviderThrottle()
    pt.record_response("logs", status_code=429)
    snap1 = pt.snapshot()["logs"]
    pt.record_response("logs", status_code=429)
    snap2 = pt.snapshot()["logs"]
    pt.record_response("logs", status_code=429)
    snap3 = pt.snapshot()["logs"]
    assert snap2["cooldown_remaining_s"] >= snap1["cooldown_remaining_s"] - 0.5
    assert snap3["consec_failures"] == 3


def test_ok_resets_consecutive_failures():
    pt = ProviderThrottle()
    pt.record_response("calls", status_code=429)
    pt.record_response("calls", status_code=429)
    pt.record_response("calls", ok=True)
    snap = pt.snapshot()["calls"]
    assert snap["consec_failures"] == 0
    assert snap["cooldown_remaining_s"] == 0.0
    assert snap["total_ok"] == 1


def test_independent_method_buckets():
    pt = ProviderThrottle()
    pt.record_response("logs", status_code=429)
    # logs blocked, calls still open.
    assert pt.acquire("logs", blocking=False) is False
    assert pt.acquire("calls", blocking=False) is True


def test_unknown_method_uses_calls_bucket():
    pt = ProviderThrottle()
    pt.record_response("calls", status_code=429)
    # An unknown method falls back to "calls", so should also be blocked.
    assert pt.acquire("eth_getBlockByNumber", blocking=False) is False


def test_blocked_attempts_counted():
    pt = ProviderThrottle()
    pt.record_response("sim", status_code=429)
    pt.acquire("sim", blocking=False)
    pt.acquire("sim", blocking=False)
    snap = pt.snapshot()["sim"]
    assert snap["total_blocked"] == 2


def test_reset_clears_all_state():
    pt = ProviderThrottle()
    pt.record_response("logs", status_code=429)
    pt.record_response("calls", status_code=408)
    pt.reset()
    snap = pt.snapshot()
    assert snap["logs"]["consec_failures"] == 0
    assert snap["logs"]["total_429"] == 0
    assert snap["calls"]["total_408"] == 0
    assert pt.acquire("logs", blocking=False) is True


def test_singleton_exists():
    assert provider_throttle is not None
    snap = provider_throttle.snapshot()
    assert "logs" in snap and "calls" in snap and "sim" in snap


def test_5xx_opens_breaker():
    pt = ProviderThrottle()
    pt.record_response("calls", status_code=500, ok=False)
    snap = pt.snapshot()["calls"]
    assert snap["breaker_open"] is True
    assert snap["total_5xx"] == 1


def test_other_error_does_not_open_breaker():
    pt = ProviderThrottle()
    pt.record_response("calls", status_code=404, ok=False)
    snap = pt.snapshot()["calls"]
    assert snap["breaker_open"] is False
    assert snap["total_other_errors"] == 1
