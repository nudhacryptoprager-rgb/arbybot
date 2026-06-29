"""Tests for M9 route-level depth contract."""
from __future__ import annotations

from m9.graph_arb.depth_contract import (
    DEPTH_CONTRACT_KEYS,
    depth_error_code_from_probe,
    normalize_route_depth_contract,
)


def test_depth_contract_keys_present():
    route = {"route_id": "r1", "effective_depth_usd": 120.0, "depth_probe_status": "MEASURED_CAPACITY"}
    normalize_route_depth_contract(route, block_number=12345, depth_source="marginal_anchor")
    for key in DEPTH_CONTRACT_KEYS:
        assert key in route
    assert route["usable_depth_usd"] == 120.0
    assert route["depth_block_number"] == 12345
    assert route["depth_error_code"] is None


def test_depth_error_code_from_probe_no_liquidity():
    code = depth_error_code_from_probe(
        probe_error="V2_ZERO_RESERVES",
        depth_probe_status=None,
        effective_depth_usd=None,
    )
    assert code == "NO_LIQUIDITY"
