"""M8 origin_source provenance contract tests."""
from __future__ import annotations

from m8.discovery.origin_source import (
    ORIGIN_EXPLORATION,
    ORIGIN_M8_SNIPER,
    ORIGIN_M8_WATCHLIST_HINT,
    ORIGIN_SPECIALIZED_INDEX_FOR_M8_TOKEN,
    build_sniper_provenance_from_events,
    infer_origin_source,
    partition_canonical_routes,
)


def test_infer_m8_sniper_route():
    route = {"source": "m8_sniper", "pool_address": "0xabc"}
    assert infer_origin_source(route) == ORIGIN_M8_SNIPER


def test_infer_specialized_index_for_m8_token():
    tok = "0xea1d939bb7991f41d7858eddfab8df10a1a97b07"
    route = {
        "source": "m8_cross_dex_expansion",
        "resolve_source": "specialized_index",
        "focus_token_address": tok,
    }
    assert (
        infer_origin_source(route, {tok})
        == ORIGIN_SPECIALIZED_INDEX_FOR_M8_TOKEN
    )


def test_infer_exploration_without_m8_token():
    route = {
        "source": "curve_factory_discovery",
        "pool_address": "0x1",
    }
    assert infer_origin_source(route, {"0x2"}) == ORIGIN_EXPLORATION


def test_partition_canonical_routes():
    m8_tok = "0xea1d939bb7991f41d7858eddfab8df10a1a97b07"
    routes = [
        {"source": "m8_sniper"},
        {
            "source": "m8_cross_dex_expansion",
            "focus_token_address": m8_tok,
        },
        {"source": "adapter_metadata", "metadata_seeded": True},
    ]
    canonical, exploration = partition_canonical_routes(routes, {m8_tok})
    assert len(canonical) == 2
    assert len(exploration) == 1
    assert exploration[0]["origin_source"] == ORIGIN_EXPLORATION


def test_build_sniper_provenance_from_events():
    events = [
        {
            "token0": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
            "token1": "0xea1d939bb7991f41d7858eddfab8df10a1a97b07",
            "token0_symbol": "USDC",
            "token1_symbol": "FOO",
        }
    ]
    prov = build_sniper_provenance_from_events(events)
    assert "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913" in prov["anchor_token_addrs"]
    assert "0xea1d939bb7991f41d7858eddfab8df10a1a97b07" in prov["candidate_token_addrs"]
