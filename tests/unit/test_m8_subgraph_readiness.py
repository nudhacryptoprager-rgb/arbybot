"""Tests for M8.2 subgraph readiness helpers."""
from __future__ import annotations

from m8.discovery.cross_dex_expand import (
    evaluate_subgraph_readiness,
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
