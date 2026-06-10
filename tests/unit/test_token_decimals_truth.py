"""Token decimals truth layer tests."""
from __future__ import annotations

from m9.graph_arb.token_decimals import (
    DECIMALS_SOURCE_CORE_CONFIG,
    DECIMALS_SOURCE_HINT,
    DECIMALS_SOURCE_TOPOLOGY_PROBE,
    DECIMALS_STATUS_UNKNOWN_DIAGNOSTIC,
    TOPOLOGY_PROBE_DECIMALS_FALLBACK,
    decimals_skip_extra,
    enrich_route_decimals,
    is_economics_grade_decimals_source,
    resolve_decimals_with_source,
)


def test_topology_probe_fallback():
    dec, src = resolve_decimals_with_source(
        "0xdead000000000000000000000000000000000001",
        topology_probe=True,
    )
    assert dec == TOPOLOGY_PROBE_DECIMALS_FALLBACK
    assert src == DECIMALS_SOURCE_TOPOLOGY_PROBE


def test_production_mode_no_fallback():
    dec, src = resolve_decimals_with_source(
        "0xdead000000000000000000000000000000000001",
        topology_probe=False,
    )
    assert dec is None
    assert src == "fallback_unknown"


def test_hint_metadata_source():
    dec, src = resolve_decimals_with_source(
        "0xdead000000000000000000000000000000000001",
        route={"token0_decimals_hint": 9},
        dec_key="token0_decimals",
        topology_probe=False,
    )
    assert dec == 9
    assert src == DECIMALS_SOURCE_HINT


def test_hint_not_economics_grade():
    assert is_economics_grade_decimals_source(DECIMALS_SOURCE_HINT) is False
    assert is_economics_grade_decimals_source(DECIMALS_SOURCE_CORE_CONFIG) is True


def test_enrich_route_sets_sources():
    route = {
        "token0_addr": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
        "token1_addr": "0x4200000000000000000000000000000000000006",
        "token0": "USDC",
        "token1": "WETH",
    }
    enrich_route_decimals(route, topology_probe=False)
    assert route["token0_decimals"] == 6
    assert route["token0_decimals_source"] == "known_address"
    assert route["decimals_status"] == "resolved"


def test_enrich_topology_probe_diagnostic_status():
    route = {
        "token0_addr": "0xdead000000000000000000000000000000000001",
        "token1_addr": "0xbeef000000000000000000000000000000000002",
    }
    enrich_route_decimals(route, topology_probe=True)
    assert route["token0_decimals"] == TOPOLOGY_PROBE_DECIMALS_FALLBACK
    assert route["decimals_status"] == DECIMALS_STATUS_UNKNOWN_DIAGNOSTIC


def test_decimals_skip_extra_payload():
    extra = decimals_skip_extra(
        {
            "token0_addr": "0xabc",
            "token1_addr": "0xdef",
            "token0_decimals_source": "hint_metadata",
        }
    )
    assert extra["token0_addr"] == "0xabc"
    assert extra["token0_decimals_source"] == "hint_metadata"
