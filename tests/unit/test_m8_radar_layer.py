"""Unit tests for M8.2 radar layer contract."""
from __future__ import annotations

from m8.discovery.dexscreener_hints import _pair_to_hint
from m8.discovery.external_route_liveness import (
    LIVENESS_PROBE_ONLY,
    probe_0x_swap_liveness,
)
from m8.discovery.pool_hints import PoolHint
from m8.discovery.radar_layer import (
    RADAR_REASON_LIQUIDITY,
    RADAR_REASON_NEW_POOL,
    RADAR_REASON_TOKEN_PAIR,
    build_radar_candidates_artifact,
    build_radar_funnel,
    classify_radar_reason,
    run_radar_verify_pipeline,
    stamp_radar_reason,
)


def _dex_pair(**overrides):
    base = {
        "chainId": "base",
        "dexId": "uniswap",
        "pairAddress": "0xpool1111111111111111111111111111111111111111",
        "pairCreatedAt": 1710000000000,
        "baseToken": {"address": "0xabc0000000000000000000000000000000000001"},
        "quoteToken": {"address": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"},
        "liquidity": {"usd": 12000},
        "volume": {"h24": 500},
    }
    base.update(overrides)
    return base


def test_classify_radar_reason_liquidity():
    h = PoolHint(
        source="dexscreener",
        chain="base",
        dex_id="uniswap_v3",
        pool_address="0xpool1",
        token0_addr="0xa",
        token1_addr="0xb",
        liquidity_usd=5000.0,
    )
    assert classify_radar_reason(h) == RADAR_REASON_LIQUIDITY


def test_classify_radar_reason_new_pool_backfill():
    h = PoolHint(
        source="geckoterminal",
        chain="base",
        dex_id="uniswap_v4",
        pool_address="0xpool2",
        token0_addr="0xa",
        token1_addr="0xb",
        raw={"backfill_mode": "new_pools"},
    )
    assert classify_radar_reason(h) == RADAR_REASON_NEW_POOL


def test_pair_to_hint_sets_radar_reason():
    h = _pair_to_hint(
        _dex_pair(),
        chain="base",
        focus_token="0xabc0000000000000000000000000000000000001",
    )
    assert h is not None
    assert h.radar_reason in (
        RADAR_REASON_LIQUIDITY,
        RADAR_REASON_NEW_POOL,
        RADAR_REASON_TOKEN_PAIR,
    )


def test_build_radar_candidates_artifact_hint_only():
    hints = [
        stamp_radar_reason(
            PoolHint(
                source="dexscreener",
                chain="base",
                dex_id="uniswap_v3",
                pool_address="0xpool1",
                token0_addr="0xa",
                token1_addr="0xb",
            )
        )
    ]
    art = build_radar_candidates_artifact(
        chain="base", sources=["dexscreener"], hints=hints
    )
    assert art["metrics"]["truth_boundary"] == "HINT_ONLY_NO_CANONICAL"
    assert art["metrics"]["candidates_total"] == 1
    assert art["candidates"][0]["radar_reason"]


def test_build_radar_funnel_split():
    radar = build_radar_candidates_artifact(
        chain="base",
        sources=["dexscreener"],
        hints=[
            PoolHint(
                source="dexscreener",
                chain="base",
                dex_id="uniswap_v3",
                pool_address="0xpool1",
                token0_addr="0xa",
                token1_addr="0xb",
            )
        ],
    )
    hints = {
        "metrics": {"verified_second_pool_count": 2, "hint_pools_seen": 1},
    }
    expansion = {
        "summary": {
            "routes_admitted_count": 10,
            "handoff_ready": True,
            "handoff_lane": "graph_topology",
        }
    }
    funnel = build_radar_funnel(radar=radar, hints=hints, expansion=expansion)
    assert funnel["radar_seen"] == 1
    assert funnel["onchain_verified"] == 2
    assert funnel["bridge_eligible"] == 10
    assert funnel["m9_handoff"]["handoff_ready"] is True


def test_run_radar_verify_pipeline_none_mode():
    hints = [
        PoolHint(
            source="dexscreener",
            chain="base",
            dex_id="uniswap_v3",
            pool_address="0xpool1",
            token0_addr="0xa",
            token1_addr="0xb",
        )
    ]
    out = run_radar_verify_pipeline(hints, chain="base", verify_mode="none")
    assert len(out) == 1


def test_external_route_liveness_not_configured_without_key(monkeypatch):
    monkeypatch.delenv("ZEROX_API_KEY", raising=False)
    row = probe_0x_swap_liveness()
    assert row["admission"] == LIVENESS_PROBE_ONLY
    assert row["status"] == "NOT_CONFIGURED"
