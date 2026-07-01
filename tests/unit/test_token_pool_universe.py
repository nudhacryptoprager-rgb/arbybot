"""Tests for token-scoped pool universe recall."""
from __future__ import annotations

from m8.discovery.pool_hints import PoolHint
from m8.discovery.token_pool_universe import (
    ANCHOR_CLOSURE_POOL,
    CONNECTOR_CLOSURE_POOL,
    FRESH_TOKEN_POOL,
    anchor_addresses_from_config,
    build_closure_graph,
    build_pool_universe_width,
    classify_pool_universe_type,
    filter_hot_path_hints,
    fresh_token_addresses,
    score_hint_verify_priority,
    sort_hints_for_verify,
)


def _hint(
    *,
    focus: str,
    t0: str,
    t1: str,
    source: str = "dexscreener",
) -> PoolHint:
    return PoolHint(
        source=source,
        chain="base",
        dex_id="uniswap_v3",
        pool_address="0x" + "a" * 40,
        token0_addr=t0,
        token1_addr=t1,
        focus_token=focus,
        liquidity_usd=5000.0,
        raw={"support_status": "supported"},
    )


def test_classify_fresh_and_connector_universe():
    fresh = "0x" + "1" * 40
    connector = "0x" + "2" * 40
    anchor = "0x" + "3" * 40
    fresh_set = {fresh}
    hints = [_hint(focus=fresh, t0=fresh, t1=connector)]
    graph = build_closure_graph(hints, fresh_tokens=fresh_set)
    assert classify_pool_universe_type(
        hints[0], fresh_tokens=fresh_set, closure_graph=graph, anchor_addrs={anchor}
    ) == FRESH_TOKEN_POOL
    conn_hint = _hint(focus=connector, t0=connector, t1=fresh)
    assert classify_pool_universe_type(
        conn_hint, fresh_tokens=fresh_set, closure_graph=graph, anchor_addrs={anchor}
    ) in (CONNECTOR_CLOSURE_POOL, FRESH_TOKEN_POOL)


def test_filter_hot_path_drops_anchor_anchor_only():
    fresh = "0x" + "1" * 40
    anchor_a = "0x" + "4" * 40
    anchor_b = "0x" + "5" * 40
    fresh_set = {fresh}
    hints = [
        _hint(focus=fresh, t0=fresh, t1=anchor_a),
        _hint(focus=anchor_a, t0=anchor_a, t1=anchor_b),
    ]
    out = filter_hot_path_hints(
        hints,
        fresh_tokens=fresh_set,
        anchor_addrs={anchor_a, anchor_b},
        graph_closure_only=True,
    )
    assert len(out) == 1
    assert out[0].focus_token == fresh


def test_pool_universe_width_metrics():
    fresh = "0x" + "1" * 40
    fresh_set = {fresh}
    h = _hint(focus=fresh, t0=fresh, t1="0x" + "2" * 40)
    h.raw = {**(h.raw or {}), "pool_universe_type": FRESH_TOKEN_POOL, "recall_verified_pool_exists": True}
    mirrors = [
        {
            "token": fresh,
            "raw_dex_id": "uniswap",
            "recall_verified_pool_exists": True,
            "is_stale_hint": False,
            "hint_status": "HINT_ONCHAIN_VERIFIED",
        }
    ]
    width = build_pool_universe_width([h], mirrors, fresh_tokens=fresh_set)
    assert width["fresh_tokens_scanned"] == 1
    assert width["raw_pools_seen"] == 1
    assert width["pool_exists_verified"] == 1


def test_verify_priority_fresh_before_stale():
    fresh = _hint(
        focus="0x" + "1" * 40,
        t0="0x" + "1" * 40,
        t1="0x" + "2" * 40,
    )
    fresh.created_at = "2026-06-29T12:00:00Z"
    stale = _hint(
        focus="0x" + "3" * 40,
        t0="0x" + "3" * 40,
        t1="0x" + "2" * 40,
    )
    stale.created_at = "2025-01-01T00:00:00Z"
    ordered = sort_hints_for_verify([stale, fresh])
    assert ordered[0].focus_token == fresh.focus_token
