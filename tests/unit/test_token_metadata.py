"""Token metadata and malformed address tests."""
from __future__ import annotations

from m9.graph_arb.core_tokens_loader import resolve_truncated_address
from m9.graph_arb.token_decimals import is_strict_token_address
from m9.graph_arb.token_metadata import (
    enrich_route_token_metadata,
    validate_route_token_addresses,
)


def test_malformed_truncated_address_rejected():
    assert validate_route_token_addresses({"token0_addr": "0x420000"}) == "malformed_token_address"
    assert is_strict_token_address("0x420000") is False
    assert is_strict_token_address("0x4200000000000000000000000000000000000006") is True


def test_truncated_prefix_resolves_from_route_index():
    from m9.graph_arb.core_tokens_loader import (
        build_route_address_prefix_index,
        resolve_truncated_address,
    )

    routes = [
        {
            "pair_id": "0xabc123_USDC",
            "token0": "0xabc123",
            "token1": "USDC",
            "token0_addr": "0xabc123def456789012345678901234567890abcd",
            "token1_addr": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
        }
    ]
    idx = build_route_address_prefix_index(routes, chain="base")
    assert resolve_truncated_address("0xabc123", route_index=idx) == "0xabc123def456789012345678901234567890abcd"


def test_truncated_prefix_resolves_weth():
    addr = resolve_truncated_address("0x420000")
    assert addr == "0x4200000000000000000000000000000000000006"


def test_enrich_resolves_truncated_symbol_to_full_address():
    route = {
        "token0": "0x420000",
        "token1": "0x833589",
        "token0_addr": "0x420000",
        "token1_addr": "0x833589",
    }
    enrich_route_token_metadata(route, chain="base", topology_probe=True)
    assert route.get("token0_addr") == "0x4200000000000000000000000000000000000006"
    assert route.get("token0_decimals") == 18
    assert route.get("metadata_status") in ("resolved", "partial")
