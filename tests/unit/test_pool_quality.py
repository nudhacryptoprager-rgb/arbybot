"""Tests for m9.graph_arb.pool_quality state machine."""
from __future__ import annotations

from m9.graph_arb.pool_quality import (
    STATE_DISCOVERED,
    STATE_FACTORY_VERIFIED,
    STATE_PRODUCTIVE_READY,
    STATE_QUARANTINED,
    annotate_route_pool_quality,
    productive_admission_ok,
)


def test_discovered_without_factory():
    route = {"factory_verified": False, "adapter_type": "uniswap_v3"}
    assert annotate_route_pool_quality(route) == STATE_DISCOVERED


def test_productive_ready_when_depth_and_factory():
    route = {
        "factory_verified": True,
        "adapter_type": "uniswap_v3",
        "effective_depth_usd": 500.0,
        "quote_smoke_status": "QUOTE_OK",
    }
    assert annotate_route_pool_quality(route) == STATE_PRODUCTIVE_READY
    assert productive_admission_ok(route) is True


def test_quarantined_toxic():
    route = {
        "factory_verified": True,
        "adapter_type": "uniswap_v3",
        "depth_reject_reason": "TOXIC_PRICE_IMPACT",
    }
    assert annotate_route_pool_quality(route) == STATE_QUARANTINED
    assert productive_admission_ok(route) is False


def test_depth_optional_without_env():
    route = {
        "factory_verified": True,
        "adapter_type": "uniswap_v3",
    }
    assert productive_admission_ok(route) is True
    assert annotate_route_pool_quality(route) in (STATE_FACTORY_VERIFIED, STATE_PRODUCTIVE_READY)
