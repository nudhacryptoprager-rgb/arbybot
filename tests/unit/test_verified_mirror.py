"""Tests for verified mirror pool classification."""
from __future__ import annotations

from m9.graph_arb.verified_mirror import is_verified_mirror_route, verified_mirror_pool_addrs


def test_matched_m8_without_verification_is_not_mirror():
    route = {
        "pool_address": "0xabc",
        "source": "expansion",
        "matched_m8_token": True,
        "factory_verified": False,
    }
    assert not is_verified_mirror_route(route)


def test_verified_mirror_requires_factory_and_quote():
    route = {
        "pool_address": "0xdef",
        "source": "expansion",
        "matched_m8_token": True,
        "factory_verified": True,
        "productive_quote_status": "QUOTE_OK",
    }
    assert is_verified_mirror_route(route)
    pools = verified_mirror_pool_addrs([route])
    assert "0xdef" in pools


def test_topology_ready_alone_is_not_verified_mirror():
    from m9.graph_arb.verified_mirror import is_mirror_topology_ready_diagnostic

    route = {
        "pool_address": "0xabc",
        "source": "expansion",
        "matched_m8_token": True,
        "factory_verified": True,
        "mirror_topology_ready": True,
    }
    assert is_mirror_topology_ready_diagnostic(route)
    assert not is_verified_mirror_route(route)
