"""Tests for mirror quote smoke and v4 index metrics."""
from __future__ import annotations

from m8.discovery.cross_dex_expand import compute_v4_event_index_coverage
from m8.discovery.mirror_quote_smoke import (
    aggregate_mirror_readiness_from_routes,
    is_same_pair_mirror_route,
    smoke_mirror_same_pair_routes,
)


def test_v4_event_index_hit_rate_capped_at_one():
    cov = compute_v4_event_index_coverage(
        reject_rows=[],
        routes_admitted=[
            {"dex_id": "uniswap_v4", "resolve_source": "hint"},
            {"dex_id": "uniswap_v4", "resolve_source": "hint"},
        ],
        scan_telemetry={"active_scan_attempted_by_dex": {"uniswap_v4": 1}},
    )
    assert cov["v4_event_index_hit_rate"] == 1.0
    assert cov["v4_event_index_coverage_rate"] == 1.0
    assert cov["v4_routes_admitted"] == 2


def test_mirror_smoke_dry_run_skips_rpc():
    routes = [
        {
            "focus_token_symbol": "FOO",
            "focus_token_address": "0xabc",
            "token0": "FOO",
            "token1": "WETH",
            "token0_addr": "0xabc",
            "token1_addr": "0x1",
            "dex_id": "uniswap_v3",
            "adapter_type": "uniswap_v3",
            "quote_smoke_status": "not_run",
        }
    ]
    stats = smoke_mirror_same_pair_routes(
        routes, chain="base", config={}, dry_run=True
    )
    assert stats["reason"] == "SKIPPED_DRY_RUN"
    assert is_same_pair_mirror_route(routes[0]) is True


def test_aggregate_mirror_topology_without_quote():
    routes = [
        {
            "focus_token_symbol": "FOO",
            "focus_token_address": "0xabc",
            "token0": "FOO",
            "token1": "WETH",
            "dex_id": "uniswap_v3",
            "quote_smoke_status": "not_run",
        },
        {
            "focus_token_symbol": "FOO",
            "focus_token_address": "0xabc",
            "token0": "FOO",
            "token1": "WETH",
            "dex_id": "uniswap_v4",
            "quote_smoke_status": "skipped_registry",
        },
    ]
    topology, quote, same_pair, debug = aggregate_mirror_readiness_from_routes(routes)
    assert topology == 1
    assert quote == 0
    assert same_pair == 1
    assert debug[0]["missing_reason"] == "SAME_PAIR_QUOTES_LT_2"
