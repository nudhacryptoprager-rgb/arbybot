"""Unit tests for M8.2 second-venue discovery helpers."""
from __future__ import annotations

from unittest.mock import patch

from m8.discovery.pool_hints import (
    HINT_ONCHAIN_VERIFIED,
    PoolHint,
    build_artifact,
)
from m8.discovery.second_venue_discovery import (
    apply_verified_hints_for_token,
    bump_second_venue_source,
    recall_rates,
)
from m8.discovery.thegraph_token_api_hints import _pool_row_to_hint
from m8.discovery.geckoterminal_hints import fetch_new_pools_backfill
from m8.discovery.pool_hints import normalize_dex_id


def test_normalize_dex_id_thegraph_token_api():
    assert normalize_dex_id("thegraph_token_api", "curvefi") == "curve_stable"
    assert normalize_dex_id("thegraph_token_api", "balancer") == "balancer_vault"
    assert normalize_dex_id("thegraph_token_api", "uniswap_v4") == "uniswap_v4"


def test_pool_row_to_hint_pinax():
    row = {
        "protocol": "aerodrome",
        "pool": "0xpoolaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "input_token": "0xabc0000000000000000000000000000000000001",
        "output_token": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
        "reserve_usd": 5000,
    }
    h = _pool_row_to_hint(
        row,
        chain="base",
        focus_token="0xabc0000000000000000000000000000000000001",
    )
    assert h is not None
    assert h.dex_id == "aerodrome"
    assert h.source == "thegraph_token_api"


def test_bump_second_venue_source():
    metrics: dict = {}
    bump_second_venue_source(metrics, "dexscreener")
    bump_second_venue_source(metrics, "dexscreener")
    assert metrics["second_venue_source"]["dexscreener"] == 2


def test_recall_rates():
    out = recall_rates(metrics={"transitions_1_to_2": 2}, watchlist_tokens=100, events_seen=50)
    assert out["crossdex_transition_rate"] == 0.04
    assert out["transition_candidate_rate"] == 0.0


@patch("m8.discovery.pool_hints.verify_hint_onchain")
def test_apply_verified_hints_triggers_transition(mock_verify):
    hint = PoolHint(
        source="dexscreener",
        chain="base",
        dex_id="aerodrome",
        pool_address="0xpoolbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        token0_addr="0xabc0000000000000000000000000000000000001",
        token1_addr="0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
        hint_status=HINT_ONCHAIN_VERIFIED,
        verify_method="bytecode",
        focus_token="0xabc0000000000000000000000000000000000001",
    )
    mock_verify.return_value = hint
    artifact = build_artifact(chain="base", sources=["dexscreener"], hints=[hint])
    entry = {
        "seen_on_dexes": ["uniswap_v4"],
        "second_pool_verified": False,
        "first_seen_ts": 1.0,
        "first_block": 100,
        "first_tx_hash": "0x1",
    }
    metrics: dict = {}
    dex_adapter = {"aerodrome": "aerodrome_v2", "uniswap_v4": "uniswap_v4"}
    ok = apply_verified_hints_for_token(
        token_address="0xabc0000000000000000000000000000000000001",
        entry=entry,
        hints_artifact=artifact,
        chain="base",
        dex_adapter=dex_adapter,
        metrics=metrics,
        allowed_dex_ids={"aerodrome", "uniswap_v4"},
    )
    assert ok is True
    assert entry["second_pool_verified"] is True
    assert metrics["transitions_1_to_2"] == 1
    assert metrics["second_venue_source"]["dexscreener"] == 1


@patch("m8.discovery.geckoterminal_hints.fetch_new_pool_hints")
def test_fetch_new_pools_backfill_filters_watchlist(mock_fetch):
    from m8.discovery.pool_hints import PoolHint

    mock_fetch.return_value = [
        PoolHint(
            source="geckoterminal",
            chain="base",
            dex_id="curve_stable",
            pool_address="0xpool1",
            token0_addr="0xabc0000000000000000000000000000000000001",
            token1_addr="0xdead",
        ),
        PoolHint(
            source="geckoterminal",
            chain="base",
            dex_id="uniswap_v3",
            pool_address="0xpool2",
            token0_addr="0xbeef",
            token1_addr="0xfeed",
        ),
    ]
    out = fetch_new_pools_backfill(
        {"0xabc0000000000000000000000000000000000001"},
        network="base",
        chain="base",
        max_pages=1,
    )
    assert len(out) == 1
    assert out[0].focus_token == "0xabc0000000000000000000000000000000000001"
