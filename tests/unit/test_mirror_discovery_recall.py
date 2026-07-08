"""Tests for mirror discovery max-recall lane."""
from __future__ import annotations

import json

from m8.discovery.dex_coverage_gate import classify_dex_support_status
from m8.discovery.dexscreener_hints import _pair_to_hint
from m8.discovery.dexscreener_hints import filter_anchor_mirror_pairs
from m8.discovery.mirror_discovery_recall import (
    EXISTENCE_VERIFY_QUEUE_PATH,
    QUOTE_READY_QUEUE_PATH,
    RECALL_CANDIDATES_PATH,
    build_dex_alias_backlog,
    compute_recall_metrics,
    evaluate_m9_admission_gate,
    evaluate_mirror_recall_gate,
    evaluate_selection_verified_fresh_gate,
    hint_support_status,
    mirror_row_from_hint,
    run_fresh_mirror_quote_smoke,
    run_mirror_selection_pass,
    write_mirror_queue_artifacts,
)
from m8.discovery.pool_hints import PoolHint, QUOTE_SMOKE_OK


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
    assert row["token0_addr"] == "0x" + "1" * 40
    assert row["token1_addr"] == "0x" + "2" * 40


def test_mirror_row_from_hint_preserves_empty_tokens():
    """Factory recall hints without enrichment still serialize (empty but present)."""
    hint = PoolHint(
        source="onchain_factory",
        chain="base",
        dex_id="uniswap_v3",
        pool_address="0x" + "d" * 40,
        token0_addr="",
        token1_addr="",
        focus_token="0x" + "1" * 40,
        raw={"support_status": "supported", "raw_dex_id": "uniswap"},
    )
    row = mirror_row_from_hint(hint)
    assert "token0_addr" in row
    assert "token1_addr" in row
    assert row["token0_addr"] == ""
    assert row["token1_addr"] == ""


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


def test_quote_ready_queue_contains_only_quote_smoke_ok_hints(tmp_path, monkeypatch):
    """Quote-ready queue must not include fresh-but-not-quote-ready tokens."""
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
    fresh_not_ready = PoolHint(
        source="dexscreener",
        chain="base",
        dex_id="uniswap_v3",
        pool_address="0x" + "d" * 40,
        token0_addr="0x" + "1" * 40,
        token1_addr="0x" + "2" * 40,
        focus_token="0x" + "1" * 40,
        hint_status="HINT_FACTORY_VERIFIED",
        raw={"support_status": "supported", "selection_verified_fresh": True},
    )
    quote_ready = PoolHint(
        source="dexscreener",
        chain="base",
        dex_id="uniswap_v3",
        pool_address="0x" + "e" * 40,
        token0_addr="0x" + "3" * 40,
        token1_addr="0x" + "4" * 40,
        focus_token="0x" + "3" * 40,
        hint_status="QUOTE_SMOKE_OK",
        raw={"support_status": "supported", "selection_verified_fresh": True},
    )
    payload = {"mirrors": [{"token": "0x" + "1" * 40}, {"token": "0x" + "3" * 40}], "all_dex_mirrors_total": 2}
    write_mirror_queue_artifacts(payload, hints=[fresh_not_ready, quote_ready], chain="base")
    doc = json.loads((tmp_path / "quote_ready.json").read_text(encoding="utf-8"))
    assert doc["queue_count"] == 1
    assert doc["hints"][0]["focus_token"] == "0x" + "3" * 40


def test_m9_admission_gate_blocks_without_quote_ready():
    """Fresh target alone must not open M9 admission; quote-ready + second venue required."""
    ok, reason = evaluate_m9_admission_gate({
        "selection_verified_fresh_total": 9,
        "quote_ready_total": 0,
        "second_venue_ready_total": 0,
    })
    assert ok is False
    assert reason == "QUOTE_READY_ZERO"


def test_m9_admission_gate_blocks_without_second_venue():
    ok, reason = evaluate_m9_admission_gate({
        "selection_verified_fresh_total": 9,
        "quote_ready_total": 3,
        "second_venue_ready_total": 0,
    })
    assert ok is False
    assert reason == "SECOND_VENUE_ZERO"


def test_m9_admission_gate_opens_with_quote_and_second_venue():
    ok, reason = evaluate_m9_admission_gate({
        "selection_verified_fresh_total": 9,
        "quote_ready_total": 3,
        "second_venue_ready_total": 2,
    })
    assert ok is True
    assert reason == "M9_ADMISSION_POSSIBLE"


def test_filter_anchor_mirror_pairs_keeps_only_focus_anchor_pairs():
    anchor = "0x" + "a" * 40
    focus = "0x" + "f" * 40
    random_tok = "0x" + "r" * 40
    kept, metrics = filter_anchor_mirror_pairs(
        [
            PoolHint(
                source="dexscreener",
                chain="base",
                dex_id="uniswap_v3",
                pool_address="0x" + "p" * 40,
                token0_addr=focus,
                token1_addr=anchor,
                focus_token=focus,
            ),
            PoolHint(
                source="dexscreener",
                chain="base",
                dex_id="uniswap_v3",
                pool_address="0x" + "q" * 40,
                token0_addr=focus,
                token1_addr=random_tok,
                focus_token=focus,
            ),
            PoolHint(
                source="dexscreener",
                chain="base",
                dex_id="uniswap_v3",
                pool_address="0x" + "s" * 40,
                token0_addr=anchor,
                token1_addr=random_tok,
                focus_token=anchor,
            ),
        ],
        anchor_addrs={anchor},
    )
    assert len(kept) == 1
    assert kept[0].focus_token == focus
    assert metrics["dexscreener_pairs_seen"] == 3
    assert metrics["anchor_pairs_seen"] == 1
    assert metrics["anchor_pair_rejects"]["ANCHOR_UNKNOWN"] == 2
    assert metrics["anchor_pair_rejects"]["PAIR_NOT_FOCUS_ANCHOR"] == 0


def test_filter_anchor_mirror_pairs_rejects_missing_focus():
    anchor = "0x" + "a" * 40
    kept, metrics = filter_anchor_mirror_pairs(
        [
            PoolHint(
                source="dexscreener",
                chain="base",
                dex_id="uniswap_v3",
                pool_address="0x" + "p" * 40,
                token0_addr=anchor,
                token1_addr="0x" + "b" * 40,
                focus_token="",
            ),
        ],
        anchor_addrs={anchor},
    )
    assert kept == []
    assert metrics["anchor_pair_rejects"]["FOCUS_MISSING"] == 1


def test_fresh_quote_smoke_updates_hint_status_and_selection():
    focus = "0x" + "f" * 40
    anchor = "0x" + "a" * 40
    h = PoolHint(
        source="dexscreener",
        chain="base",
        dex_id="uniswap_v3",
        pool_address="0x" + "p" * 40,
        token0_addr=anchor,
        token1_addr=focus,
        focus_token=focus,
        hint_status="HINT_FACTORY_VERIFIED",
        raw={
            "support_status": "supported",
            "recall_verified_pool_exists": True,
            "selection_verified_fresh": True,
            "fresh_quote_candidate": True,
        },
    )
    # Simulate the smoke update path without RPC.
    h.hint_status = QUOTE_SMOKE_OK
    (h.raw or {})["quote_smoke_status"] = "QUOTE_OK_MIRROR_SMOKE"

    payload = {
        "chain": "base",
        "all_dex_mirrors_total": 1,
        "mirrors_total": 1,
    }
    sel = run_mirror_selection_pass(payload, hints=[h], run_stale_quote_smoke=False)
    assert sel["quote_ready_count"] == 1
    assert sel["fresh_target_ready"] is True
    assert sel["m9_admission_ready"] is False
    assert sel["selection_stages"]["quote_ready"] == 1
    assert sel["selection_stages"]["second_venue_ready"] == 0


def test_fresh_quote_smoke_skips_when_arby_skip_rpc():
    import os

    old = os.environ.get("ARBY_SKIP_RPC")
    os.environ["ARBY_SKIP_RPC"] = "1"
    try:
        h = PoolHint(
            source="factory_log",
            chain="base",
            dex_id="uniswap_v3",
            pool_address="0x" + "p" * 40,
            token0_addr="0x" + "a" * 40,
            token1_addr="0x" + "f" * 40,
            focus_token="0x" + "f" * 40,
            raw={"fresh_quote_candidate": True},
        )
        result = run_fresh_mirror_quote_smoke([h], chain="base")
        assert result["reason"] == "NO_FRESH_CANDIDATES" or result.get("skipped")
        assert h.hint_status != QUOTE_SMOKE_OK
    finally:
        if old is None:
            os.environ.pop("ARBY_SKIP_RPC", None)
        else:
            os.environ["ARBY_SKIP_RPC"] = old


def test_second_venue_ready_counts_productive_plus_observer():
    focus = "0x" + "f" * 40
    anchor = "0x" + "a" * 40
    productive = PoolHint(
        source="factory_log",
        chain="base",
        dex_id="uniswap_v3",
        pool_address="0x" + "p" * 40,
        token0_addr=anchor,
        token1_addr=focus,
        focus_token=focus,
        hint_status="HINT_FACTORY_VERIFIED",
        raw={
            "support_status": "supported",
            "recall_verified_pool_exists": True,
            "selection_verified_fresh": True,
            "fresh_quote_candidate": True,
        },
    )
    observer = PoolHint(
        source="observer_factory_log",
        chain="base",
        dex_id="uniswap_v2",
        pool_address="0x" + "q" * 40,
        token0_addr=anchor,
        token1_addr=focus,
        focus_token=focus,
        hint_status="HINT_FACTORY_VERIFIED",
        raw={
            "support_status": "supported",
            "recall_verified_pool_exists": True,
            "selection_verified_fresh": True,
            "fresh_quote_candidate": True,
        },
    )
    payload = {"chain": "base", "all_dex_mirrors_total": 2, "mirrors_total": 2}
    sel = run_mirror_selection_pass(payload, hints=[productive, observer], run_stale_quote_smoke=False)
    assert sel["second_venue_ready_count"] == 1
    assert sel["selection_stages"]["second_venue_ready"] == 1
    assert sel["m9_admission_ready"] is False  # quote_ready still empty

    # Mark both quote-ready -> admission opens.
    productive.hint_status = QUOTE_SMOKE_OK
    observer.hint_status = QUOTE_SMOKE_OK
    sel2 = run_mirror_selection_pass(payload, hints=[productive, observer], run_stale_quote_smoke=False)
    assert sel2["quote_ready_count"] == 2
    assert sel2["second_venue_ready_count"] == 1
    assert sel2["m9_admission_ready"] is True
