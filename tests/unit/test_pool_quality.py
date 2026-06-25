"""Tests for m9.graph_arb.pool_quality state machine."""
from __future__ import annotations

from m9.graph_arb.depth_capacity_probe import DEPTH_PROBE_ANALYTICAL_SUSPECT
from m9.graph_arb.pool_quality import (
    STATE_DISCOVERED,
    STATE_FACTORY_VERIFIED,
    STATE_PRODUCTIVE_READY,
    STATE_QUARANTINED,
    annotate_route_pool_quality,
    productive_admission_fail_reason,
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


def test_false_positive_toxic_not_quarantined():
    route = {
        "factory_verified": True,
        "adapter_type": "uniswap_v3",
        "depth_reject_reason": "TOXIC_PRICE_IMPACT",
        "effective_depth_usd": 10.2,
        "price_impact_at_100usd": 0.92,
        "depth_probe_source": "distinct_depth_probe",
    }
    assert annotate_route_pool_quality(route) != STATE_QUARANTINED
    assert route.get("depth_reprobe_required") is True
    assert productive_admission_ok(route) is False  # depth below floor, not quarantine


def test_depth_optional_without_env():
    route = {
        "factory_verified": True,
        "adapter_type": "uniswap_v3",
    }
    assert productive_admission_ok(route) is True
    assert annotate_route_pool_quality(route) in (STATE_FACTORY_VERIFIED, STATE_PRODUCTIVE_READY)


def test_distinct_route_unknown_depth_not_economics_admitted():
    from m9.graph_arb.pool_quality import economics_admission_fail_reason

    route = {
        "factory_verified": True,
        "adapter_type": "maverick_v2",
        "dex_id": "maverick_v2",
        "expansion_productive_admit": True,
    }
    assert productive_admission_ok(route) is True
    assert economics_admission_fail_reason(route) == "missing_depth"


def test_v4_measured_depth_overrides_expansion_productive_false():
    route = {
        "factory_verified": True,
        "adapter_type": "uniswap_v4",
        "dex_id": "uniswap_v4",
        "expansion_productive_admit": False,
        "depth_probe_status": "MEASURED_CAPACITY",
        "effective_depth_usd": 2500.0,
    }
    assert productive_admission_ok(route) is True


def test_analytical_suspect_depth_rejected_from_economics():
    route = {
        "factory_verified": True,
        "adapter_type": "uniswap_v3",
        "dex_id": "uniswap_v3",
        "depth_probe_status": DEPTH_PROBE_ANALYTICAL_SUSPECT,
        "depth_analytical_suspect_usd": 31_000_000_000_000.0,
        "effective_depth_usd": None,
    }
    assert productive_admission_ok(route) is False
    assert productive_admission_fail_reason(route) == "missing_depth"
