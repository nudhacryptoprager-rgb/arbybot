"""Tests for mirror discovery max-recall lane."""
from __future__ import annotations

import json

from m8.discovery.dex_coverage_gate import classify_dex_support_status
from m8.discovery.dexscreener_hints import _pair_to_hint
from m8.discovery.mirror_discovery_recall import (
    EXISTENCE_VERIFY_QUEUE_PATH,
    QUOTE_READY_QUEUE_PATH,
    RECALL_CANDIDATES_PATH,
    build_dex_alias_backlog,
    compute_recall_metrics,
    evaluate_mirror_recall_gate,
    evaluate_selection_verified_fresh_gate,
    hint_support_status,
    mirror_row_from_hint,
    write_mirror_queue_artifacts,
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
    assert unsupported == "unknown_alias"


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


def test_selection_verified_fresh_gate():
    ok, reason = evaluate_selection_verified_fresh_gate({"selection_verified_fresh_total": 0})
    assert ok is False
    assert reason == "SELECTION_VERIFIED_FRESH_ZERO"
    ok2, reason2 = evaluate_selection_verified_fresh_gate({"selection_verified_fresh_total": 2})
    assert ok2 is True
    assert reason2 == "selection_verified_fresh_ready"


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


def test_write_mirror_queue_artifacts_splits_queues(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "m8.discovery.mirror_discovery_recall.RECALL_CANDIDATES_PATH",
        tmp_path / "recall_candidates.json",
    )
    monkeypatch.setattr(
        "m8.discovery.mirror_discovery_recall.EXISTENCE_VERIFY_QUEUE_PATH",
        tmp_path / "existence_queue.json",
    )
    monkeypatch.setattr(
        "m8.discovery.mirror_discovery_recall.QUOTE_READY_QUEUE_PATH",
        tmp_path / "quote_ready.json",
    )
    monkeypatch.setattr(
        "m8.discovery.mirror_discovery_recall.EXISTENCE_VERIFY_SUBSET_PATH",
        tmp_path / "existence_subset.json",
    )
    hint = PoolHint(
        source="dexscreener",
        chain="base",
        dex_id="uniswap_v3",
        pool_address="0x" + "d" * 40,
        token0_addr="0x" + "1" * 40,
        token1_addr="0x" + "2" * 40,
        focus_token="0x" + "1" * 40,
        raw={"support_status": "supported", "raw_dex_id": "uniswap"},
    )
    payload = {"mirrors": [{"token": "0x" + "1" * 40}], "all_dex_mirrors_total": 1}
    paths = write_mirror_queue_artifacts(payload, hints=[hint], chain="base")
    assert paths["recall_candidates"] == str(tmp_path / "recall_candidates.json")
    assert (tmp_path / "existence_subset.json").is_file()
    existence = json.loads((tmp_path / "existence_queue.json").read_text(encoding="utf-8"))
    assert existence["queue_count"] == 1
