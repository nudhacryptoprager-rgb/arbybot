"""Token metadata and malformed address tests."""
from __future__ import annotations

from unittest.mock import MagicMock

from m8.metadata.acceptance import evaluate_m8_3_acceptance
from m8.metadata.registry import (
    ERROR_DECIMALS_CONFLICT,
    ERROR_ERC20_DECIMALS_REVERT,
    SOURCE_CORE_CONFIG,
    SOURCE_ERC20,
    SOURCE_EXTERNAL_HINT,
    SOURCE_UNRESOLVED,
    apply_registry_to_route,
    build_token_metadata_registry,
    is_economics_grade_entry,
    resolve_token_entry,
)
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


def test_m8_3_registry_precedence_core_config_over_hint():
    addr = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
    entry = resolve_token_entry(
        addr,
        external_hints={addr: {"decimals": 9, "symbol": "USDC_HINT"}},
    )
    assert entry["decimals"] == 6
    assert entry["source"] in (SOURCE_CORE_CONFIG, "known_address")
    assert is_economics_grade_entry(entry)


def test_m8_3_external_hint_not_economics_grade_without_onchain():
    addr = "0xdead000000000000000000000000000000000001"
    entry = resolve_token_entry(
        addr,
        external_hints={addr: {"decimals": 18, "symbol": "DEAD"}},
    )
    assert entry["decimals"] == 18
    assert entry["source"] == SOURCE_EXTERNAL_HINT
    assert not is_economics_grade_entry(entry)


def test_m8_3_conflict_when_sources_disagree():
    addr = "0xbeef000000000000000000000000000000000002"
    entry = resolve_token_entry(
        addr,
        m82_hints={addr: {"decimals": 18}},
        registry_cache={addr: {"decimals": 9, "source": "registry_cache"}},
    )
    assert entry["error_code"] == ERROR_DECIMALS_CONFLICT
    assert entry["decimals"] is None


def test_m8_3_erc20_revert_when_no_other_source():
    addr = "0xdead000000000000000000000000000000000001"
    w3 = MagicMock()
    w3.eth.call.side_effect = RuntimeError("revert")
    entry = resolve_token_entry(addr, w3=w3)
    assert entry["error_code"] == ERROR_ERC20_DECIMALS_REVERT


def test_m8_3_no_default_18_economics_grade():
    addr = "0xdead000000000000000000000000000000000001"
    entry = resolve_token_entry(addr)
    assert entry["decimals"] is None
    assert entry["source"] == SOURCE_UNRESOLVED


def test_m8_3_apply_registry_to_route():
    addr = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
    registry = {
        "tokens": {
            addr: {
                "address": addr,
                "decimals": 6,
                "source": SOURCE_ERC20,
                "economics_grade": "verified_onchain",
            }
        }
    }
    route = {
        "token0_addr": addr,
        "token1_addr": "0x4200000000000000000000000000000000000006",
    }
    apply_registry_to_route(route, registry)
    assert route["token0_decimals"] == 6
    assert route["token0_decimals_source"].startswith("m8_3_")


def test_m8_3_acceptance_strict_blocked_without_registry():
    report = evaluate_m8_3_acceptance(None, strict=True)
    assert report["goal_status"] == "BLOCKED"
    assert "M8_3_REGISTRY_MISSING" in report["m8_3_blockers"]


def test_m8_3_build_registry_route_coverage():
    bridge = {
        "active_routes": [
            {
                "route_id": "r1",
                "token0_addr": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
                "token1_addr": "0x4200000000000000000000000000000000000006",
            }
        ]
    }
    doc = build_token_metadata_registry(bridge=bridge)
    assert doc["schema_version"] == "m8_3_token_metadata_registry_v2"
    assert doc["route_coverage"]["active_routes"]["routes_count"] == 1
