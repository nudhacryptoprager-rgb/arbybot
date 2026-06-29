"""Tests for mirror discovery max-recall lane."""
from __future__ import annotations

from m8.discovery.dex_coverage_gate import classify_dex_support_status
from m8.discovery.dexscreener_hints import _pair_to_hint
from m8.discovery.mirror_discovery_recall import (
    build_dex_alias_backlog,
    compute_recall_metrics,
    evaluate_mirror_recall_gate,
    hint_support_status,
    mirror_row_from_hint,
)
from m8.discovery.pool_hints import PoolHint


def _config():
    return {
        "dexes": {
            "uniswap_v3": {
                "adapter_type": "uniswap_v3",
                "factory": "0x33128a8fc17869897dce68ed026d694621f6fdfd",
                "quoter": "0x3d4e44eb1374240ce5f1b871ab261cd16335b76a",
                "enabled": True,
            },
            "alien_base_v2": {
                "adapter_type": "uniswap_v2",
                "factory": "0x3e84d913803b02a4a7f027165e8ca42c14c0fde7",
                "enabled": True,
            },
        }
    }


def test_classify_dex_support_status_buckets():
    cfg = _config()
    _, supported = classify_dex_support_status(
        source="dexscreener", raw_dex_id="uniswap", config=cfg
    )
    assert supported == "supported"
    _, unknown = classify_dex_support_status(
        source="dexscreener", raw_dex_id="totally-new-dex", config=cfg
    )
    assert unknown == "unknown_alias"
    _, unsupported = classify_dex_support_status(
        source="dexscreener", raw_dex_id="baseswap", config=cfg
    )
    assert unsupported == "unsupported"


def test_pair_to_hint_max_recall_keeps_unknown_dex():
    pair = {
        "chainId": "base",
        "dexId": "brand-new-launchpad",
        "pairAddress": "0x" + "a" * 40,
        "baseToken": {"address": "0x" + "b" * 40},
        "quoteToken": {"address": "0x" + "c" * 40},
        "liquidity": {"usd": 1200},
        "volume": {"h24": 50},
        "pairCreatedAt": 1_700_000_000_000,
    }
    hint = _pair_to_hint(
        pair,
        chain="base",
        focus_token="0x" + "b" * 40,
        max_recall=True,
        dex_config=_config(),
    )
    assert hint is not None
    assert hint_support_status(hint) == "unknown_alias"


def test_compute_recall_metrics_and_gate():
    mirrors = [
        {
            "token": "0xaaa",
            "support_status": "supported",
            "raw_dex_id": "uniswap",
            "liquidity_usd": 100.0,
        },
        {
            "token": "0xbbb",
            "support_status": "unknown_alias",
            "raw_dex_id": "brand-new-launchpad",
            "liquidity_usd": 50.0,
        },
    ]
    metrics = compute_recall_metrics(mirrors)
    assert metrics["mirrors_total"] == 2
    assert metrics["all_dex_mirrors_total"] == 2
    assert metrics["mirrors_supported"] == 1
    assert metrics["unknown_alias_mirrors_total"] == 1
    assert metrics["mirror_seen_any_dex"] == 2
    backlog = build_dex_alias_backlog(mirrors)
    assert len(backlog) == 2
    ok, reason = evaluate_mirror_recall_gate({"mirrors_total": 2})
    assert ok is True
    assert reason == "MIRROR_RECALL_READY"


def test_mirror_row_from_hint_fields():
    hint = PoolHint(
        source="dexscreener",
        chain="base",
        dex_id="uniswap_v3",
        pool_address="0x" + "d" * 40,
        token0_addr="0x" + "1" * 40,
        token1_addr="0x" + "2" * 40,
        focus_token="0x" + "1" * 40,
        liquidity_usd=500.0,
        volume_24h=25.0,
        raw={"support_status": "supported", "raw_dex_id": "uniswap", "dexId": "uniswap"},
    )
    row = mirror_row_from_hint(hint)
    assert row["support_status"] == "supported"
    assert row["source"] == "dexscreener"
    assert row["liquidity_usd"] == 500.0
