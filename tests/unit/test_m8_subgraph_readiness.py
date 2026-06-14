"""Tests for M8.2 subgraph readiness helpers."""
from __future__ import annotations

from m8.discovery.cross_dex_expand import (
    evaluate_mirror_readiness,
    evaluate_subgraph_readiness,
    normalize_resolve_reject_reason,
    subgraph_missing_reason,
)


def test_subgraph_missing_reason_one_dex():
    assert (
        subgraph_missing_reason(
            token_seen_on_dexes=1,
            connector_tokens=2,
            active_routes=10,
            unique_tokens=5,
        )
        == "TOKEN_SEEN_ON_ONE_DEX"
    )


def test_evaluate_subgraph_readiness_includes_debug_fields():
    sg = evaluate_subgraph_readiness(
        token_seen_on_dexes=2,
        connector_tokens=1,
        active_routes=3,
        unique_tokens=4,
        same_pair_routes=1,
        connector_routes=2,
    )
    assert sg["subgraph_ready"] is False
    assert sg["missing_reason"] == "ACTIVE_ROUTES_LT_4"
    assert sg["same_pair_routes"] == 1
    assert sg["connector_routes"] == 2


def test_tweth_mirror_topology_ready_not_subgraph():
    """T/WETH on two DEXes is mirror-ready but not 3+ token subgraph-ready."""
    mirror = evaluate_mirror_readiness(
        token_seen_on_dexes=2,
        same_pair_routes=2,
        same_pair_dexes=2,
        quoteable_same_pair_routes=0,
    )
    sg = evaluate_subgraph_readiness(
        token_seen_on_dexes=2,
        connector_tokens=0,
        active_routes=2,
        unique_tokens=2,
        same_pair_routes=2,
    )
    assert mirror["mirror_topology_ready"] is True
    assert mirror["mirror_quote_ready"] is False
    assert mirror["missing_reason"] == "SAME_PAIR_QUOTES_LT_2"
    assert sg["subgraph_ready"] is False
    assert sg["missing_reason"] == "NO_CONNECTOR_TOKEN"


def test_normalize_resolve_reject_reason_specialized_and_v4():
    assert (
        normalize_resolve_reject_reason(
            "ADAPTER_RESOLVE_PENDING", adapter="curve_stable", dex_id="curve_stable"
        )
        == "SPECIALIZED_INDEX_ONLY"
    )
    assert (
        normalize_resolve_reject_reason(
            "ADAPTER_RESOLVE_PENDING", adapter="uniswap_v4", dex_id="uniswap_v4"
        )
        == "V4_EVENT_INDEX_ONLY"
    )
    assert (
        normalize_resolve_reject_reason("CURVE_INDEX_NO_MATCH", dex_id="curve_stable")
        == "SPECIALIZED_INDEX_NO_MATCH"
    )
