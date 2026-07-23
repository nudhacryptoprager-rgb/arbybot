"""Tests for mirror discovery max-recall lane."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from m8.discovery.dex_coverage_gate import classify_dex_support_status
from m8.discovery.dexscreener_hints import _pair_to_hint
from m8.discovery.dexscreener_hints import filter_anchor_mirror_pairs
from m8.discovery.mirror_discovery_recall import (
    EXISTENCE_VERIFY_QUEUE_PATH,
    QUOTE_READY_QUEUE_PATH,
    RECALL_CANDIDATES_PATH,
    build_coverage_matrix,
    build_dex_alias_backlog,
    build_second_venue_rca,
    compute_recall_metrics,
    evaluate_m9_admission_gate,
    evaluate_mirror_recall_gate,
    evaluate_selection_verified_fresh_gate,
    hint_support_status,
    mirror_row_from_hint,
    run_mirror_discovery_recall,
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


def test_fresh_quote_smoke_updates_hint_status_and_selection(tmp_path):
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
    sel = run_mirror_selection_pass(
        payload,
        hints=[h],
        output_path=tmp_path / "selection_hints.json",
        selection_artifact_path=tmp_path / "selection_latest.json",
        run_stale_quote_smoke=False,
    )
    assert sel["quote_ready_count"] == 1
    assert sel["fresh_target_ready"] is True
    assert sel["m9_admission_ready"] is False
    assert sel["selection_stages"]["quote_ready"] == 1
    assert sel["selection_stages"]["second_venue_ready"] == 0


def test_fresh_quote_smoke_skips_when_arby_skip_rpc(tmp_path):
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
        result = run_fresh_mirror_quote_smoke(
            [h],
            chain="base",
            checkpoint_path=tmp_path / "fresh_quote_smoke.json",
        )
        assert result["reason"] == "NO_FRESH_CANDIDATES" or result.get("skipped")
        assert h.hint_status != QUOTE_SMOKE_OK
    finally:
        if old is None:
            os.environ.pop("ARBY_SKIP_RPC", None)
        else:
            os.environ["ARBY_SKIP_RPC"] = old


def test_second_venue_ready_counts_productive_plus_observer(tmp_path):
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
    sel = run_mirror_selection_pass(
        payload,
        hints=[productive, observer],
        output_path=tmp_path / "selection_hints_1.json",
        selection_artifact_path=tmp_path / "selection_latest_1.json",
        run_stale_quote_smoke=False,
    )
    assert sel["second_venue_ready_count"] == 1
    assert sel["selection_stages"]["second_venue_ready"] == 1
    assert sel["quote_ready_second_venue_count"] == 0
    assert sel["m9_admission_ready"] is False  # quote_ready still empty

    productive.hint_status = QUOTE_SMOKE_OK
    sel_quote_one = run_mirror_selection_pass(
        payload,
        hints=[productive, observer],
        output_path=tmp_path / "selection_hints_2.json",
        selection_artifact_path=tmp_path / "selection_latest_2.json",
        run_stale_quote_smoke=False,
    )
    assert sel_quote_one["quote_ready_count"] == 1
    assert sel_quote_one["second_venue_ready_count"] == 1
    assert sel_quote_one["quote_ready_second_venue_count"] == 0
    assert sel_quote_one["m9_admission_ready"] is False

    # Mark both venues quote-ready for the same focus token -> admission opens.
    productive.hint_status = QUOTE_SMOKE_OK
    observer.hint_status = QUOTE_SMOKE_OK
    sel2 = run_mirror_selection_pass(
        payload,
        hints=[productive, observer],
        output_path=tmp_path / "selection_hints_3.json",
        selection_artifact_path=tmp_path / "selection_latest_3.json",
        run_stale_quote_smoke=False,
    )
    assert sel2["quote_ready_count"] == 2
    assert sel2["second_venue_ready_count"] == 1
    assert sel2["quote_ready_second_venue_count"] == 1
    assert sel2["m9_admission_ready"] is True


def test_run_recall_payload_has_top_level_m9_admission_blocker(monkeypatch):
    import m8.discovery.mirror_discovery_recall as recall_mod
    import m8.discovery.token_pool_universe as token_universe

    focus = "0x" + "f" * 40
    anchor = "0x" + "a" * 40
    created_at = (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )
    hint = PoolHint(
        source="factory_log",
        chain="base",
        dex_id="uniswap_v3",
        pool_address="0x" + "1" * 40,
        token0_addr=anchor,
        token1_addr=focus,
        focus_token=focus,
        created_at=created_at,
        hint_status="HINT_FACTORY_VERIFIED",
        raw={"support_status": "supported"},
    )

    monkeypatch.setattr(
        token_universe,
        "load_factory_recall_hints",
        lambda *args, **kwargs: [hint],
    )
    monkeypatch.setattr(recall_mod, "write_verify_rca", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        recall_mod,
        "write_recall_hints_checkpoint",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        recall_mod,
        "write_mirror_queue_artifacts",
        lambda *args, **kwargs: {},
    )

    _hints, payload = run_mirror_discovery_recall(
        [focus],
        config={
            "tokens": {"WETH": {"address": anchor}},
            "dexes": {"uniswap_v3": {"enabled": True, "adapter_type": "uniswap_v3"}},
        },
        dry_run=True,
        use_dexscreener=False,
        token_pool_universe=True,
        graph_closure_only=True,
    )

    assert payload["selection_verified_fresh_total"] == 1
    assert payload["quote_ready_total"] == 0
    assert payload["m9_admission_blocker"] == "QUOTE_READY_ZERO"
    assert payload["verify_rca"]["m9_admission_blocker"] == "QUOTE_READY_ZERO"


def _hint(
    *,
    focus: str,
    dex: str,
    source: str = "factory_log",
    pool: str = "0x" + "p" * 40,
    quote_ready: bool = False,
    verified: bool = True,
) -> PoolHint:
    return PoolHint(
        source=source,
        chain="base",
        dex_id=dex,
        pool_address=pool,
        token0_addr=focus,
        token1_addr="0x" + "a" * 40,
        focus_token=focus,
        hint_status=QUOTE_SMOKE_OK if quote_ready else "HINT_FACTORY_VERIFIED",
        raw={"recall_verified_pool_exists": verified, "selection_verified_fresh": verified},
    )


def test_build_coverage_matrix_counts_by_source_and_dex():
    focus = "0x" + "f" * 40
    hints = [
        _hint(focus=focus, dex="uniswap_v3", source="factory_log", pool="0x11"),
        _hint(focus=focus, dex="uniswap_v3", source="dexscreener", pool="0x22", quote_ready=True),
        _hint(focus=focus, dex="alien_base_v2", source="observer_factory_log", pool="0x33"),
    ]
    cfg = _config()
    matrix = build_coverage_matrix(hints, cfg)
    assert matrix["schema_version"] == "m8_recall_coverage_matrix_v1"
    rows = {r["dex_id"]: r for r in matrix["rows"]}
    assert rows["uniswap_v3"]["verified_total"] == 2
    assert rows["uniswap_v3"]["verified_by_source"]["factory_log"] == 1
    assert rows["uniswap_v3"]["verified_by_source"]["dexscreener"] == 1
    assert rows["uniswap_v3"]["quote_ready_total"] == 1
    assert rows["alien_base_v2"]["verified_total"] == 1
    assert rows["alien_base_v2"]["verified_by_source"]["observer_factory_log"] == 1
    assert "uniswap_v3" in matrix["quote_ready_dexes"]
    assert matrix["source_totals"]["factory_log"] == 1
    assert matrix["source_totals"]["dexscreener"] == 1
    assert matrix["source_totals"]["observer_factory_log"] == 1


def test_build_second_venue_rca_records_quote_blocker():
    focus = "0x" + "f" * 40
    hints = [
        _hint(focus=focus, dex="uniswap_v3", source="factory_log", quote_ready=True),
        _hint(focus=focus, dex="alien_base_v2", source="dexscreener"),
    ]
    rca = build_second_venue_rca(hints)
    assert len(rca) == 1
    row = rca[0]
    assert row["focus_token"] == focus
    assert row["verified_dexes"] == ["alien_base_v2", "uniswap_v3"]
    assert row["quote_ready_dexes"] == ["uniswap_v3"]
    assert row["blocker_reason"] == "QUOTE_READY_SINGLE_VENUE"


def test_build_second_venue_rca_skips_fully_ready_and_single_venue():
    focus_ready = "0x" + "a" * 40
    focus_single = "0x" + "b" * 40
    hints = [
        _hint(focus=focus_ready, dex="uniswap_v3", quote_ready=True),
        _hint(focus=focus_ready, dex="alien_base_v2", quote_ready=True),
        _hint(focus=focus_single, dex="uniswap_v3"),
    ]
    rca = build_second_venue_rca(hints)
    assert len(rca) == 0


# ---------------------------------------------------------------------------
# Step 10 — wide-recall funnel split + freshness gate + second-venue persistence
# ---------------------------------------------------------------------------


def test_build_per_token_per_dex_funnel_splits_recall_and_quote():
    """The per-token / per-DEX funnel must let operators see which token
    leaks at which stage (recall / onchain verified / quote-ready)."""
    from m8.discovery.mirror_discovery_recall import build_per_token_per_dex_funnel

    f1 = "0x" + "a" * 40
    f2 = "0x" + "b" * 40
    hints = [
        _hint(focus=f1, dex="uniswap_v3", quote_ready=True, verified=True),
        _hint(focus=f1, dex="alien_base_v2", quote_ready=False, verified=True),
        _hint(focus=f2, dex="uniswap_v3", quote_ready=False, verified=True),
        # Third hint for f2 is verified=False so it should count toward
        # recall_candidates but NOT onchain_verified.
        _hint(focus=f2, dex="alien_base_v2", quote_ready=False, verified=False),
    ]
    funnel = build_per_token_per_dex_funnel(hints)
    f1_row = funnel[f1]
    assert f1_row["recall_candidates_total"] == 2
    assert f1_row["onchain_verified_total"] == 2
    assert f1_row["quote_ready_total"] == 1
    assert f1_row["verified_dex_count"] == 2  # second venue verified
    assert f1_row["quote_ready_dex_count"] == 1
    assert f1_row["second_venue_ready"] is True
    f2_row = funnel[f2]
    # f2 has recall_candidates=2, onchain_verified=1 (the verified=False one drops)
    assert f2_row["recall_candidates_total"] == 2
    assert f2_row["onchain_verified_total"] == 1
    assert f2_row["verified_dex_count"] == 1
    assert f2_row["second_venue_ready"] is False


def test_second_venue_candidate_records_keeps_verified_candidates_without_quote():
    """Step 10 fix: verified second-venue candidates must be persisted
    BEFORE quote reprobe so a failing quote smoke does not discard them."""
    from m8.discovery.mirror_discovery_recall import second_venue_candidate_records

    f1 = "0x" + "a" * 40
    f2 = "0x" + "b" * 40
    f3 = "0x" + "c" * 40
    hints = [
        # f1 has two verified DEXes; only one quote-ready. Must still surface
        # as a second-venue candidate (the missing quote is the next-step
        # reprobe target, not a discard reason).
        _hint(focus=f1, dex="uniswap_v3", quote_ready=True, verified=True),
        _hint(focus=f1, dex="alien_base_v2", quote_ready=False, verified=True),
        # f2 has only one verified DEX; must NOT surface.
        _hint(focus=f2, dex="uniswap_v3", verified=True),
        # f3 has two DEXes but one is not verified; must NOT surface.
        _hint(focus=f3, dex="uniswap_v3", verified=True),
        _hint(focus=f3, dex="alien_base_v2", verified=False),
    ]
    rows = second_venue_candidate_records(hints)
    focuses = sorted(r["focus_token"] for r in rows)
    assert focuses == [f1]
    f1_row = rows[0]
    assert f1_row["verified_dex_count"] == 2
    assert sorted(f1_row["verified_dexes"]) == ["alien_base_v2", "uniswap_v3"]
    assert f1_row["second_venue_verified"] is True
    assert f1_row["quote_ready_second_venue"] is True


def test_write_second_venue_candidates_overwrites_artifact(tmp_path, monkeypatch):
    """Step 10 fix: candidate persistence is overwritten (rolling), not
    multiplied per recall run."""
    from m8.discovery import mirror_discovery_recall as mdr

    out_path = tmp_path / "second_venue_latest.json"
    monkeypatch.setattr(mdr, "SECOND_VENUE_CANDIDATES_PATH", out_path)
    candidates = [
        {
            "focus_token": "0x" + "a" * 40,
            "verified_dexes": ["uniswap_v3", "alien_base_v2"],
            "verified_dex_count": 2,
            "verified_pools_per_dex": {
                "uniswap_v3": ["0x" + "1" * 40],
                "alien_base_v2": ["0x" + "2" * 40],
            },
            "quote_status_per_dex": {
                "uniswap_v3": "QUOTE_SMOKE_OK",
                "alien_base_v2": "HINT_FACTORY_VERIFIED",
            },
            "second_venue_verified": True,
            "quote_ready_second_venue": True,
        }
    ]
    p = mdr.write_second_venue_candidates(candidates, chain="base", source_artifact_run_timestamp="2026-07-19T10:00:00Z")
    assert Path(p) == out_path
    raw1 = json.loads(out_path.read_text(encoding="utf-8"))
    assert raw1["candidate_count"] == 1
    # Overwrite (rolling) — second call does not multiply.
    p = mdr.write_second_venue_candidates([], chain="base")
    raw2 = json.loads(out_path.read_text(encoding="utf-8"))
    assert raw2["candidate_count"] == 0
    assert raw2["chain"] == "base"


def test_evaluate_upstream_freshness_gate_blocks_stale_sniper():
    """Wide-lane recall must refuse admission when the upstream M8 sniper
    artifact is older than 30 minutes (Step 10 fix)."""
    from m8.discovery.mirror_discovery_recall import evaluate_upstream_freshness_gate

    now = datetime(2026, 7, 19, 12, 0, 0, tzinfo=timezone.utc)
    fresh_ts = "2026-07-19T11:50:00Z"  # 10 min old
    stale_ts = "2026-07-19T10:00:00Z"  # 2h old
    ok, blockers, audit = evaluate_upstream_freshness_gate(
        sniper_artifact={"generated_at_utc": fresh_ts}, now=now
    )
    assert ok is True
    assert blockers == []
    assert audit["status"] == "fresh"
    ok, blockers, audit = evaluate_upstream_freshness_gate(
        sniper_artifact={"generated_at_utc": stale_ts}, now=now
    )
    assert ok is False
    assert "SNIPER_STALE" in blockers
    assert audit["status"] == "stale"
    assert audit["age_seconds"] > 30 * 60


def test_evaluate_upstream_freshness_gate_prefers_run_timestamp():
    """run_context.run_timestamp is canonical; generated_at_utc is fallback."""
    from m8.discovery.mirror_discovery_recall import evaluate_upstream_freshness_gate

    now = datetime(2026, 7, 19, 12, 0, 0, tzinfo=timezone.utc)
    fresh_rt = "2026-07-19T11:55:00Z"
    stale_gat = "2026-07-19T09:00:00Z"
    ok, blockers, audit = evaluate_upstream_freshness_gate(
        sniper_artifact={
            "run_context": {"run_timestamp": fresh_rt},
            "generated_at_utc": stale_gat,
        },
        now=now,
    )
    assert ok is True
    assert audit["timestamp"] == fresh_rt
    assert audit["status"] == "fresh"


def test_evaluate_upstream_freshness_gate_returns_ok_when_no_sniper():
    """Absence of a sniper artifact is a config gap, not an evidence
    failure — the strict runtime-truth gate handles the strict path. The
    wide-lane freshness gate must not block when no artifact is supplied."""
    from m8.discovery.mirror_discovery_recall import evaluate_upstream_freshness_gate

    ok, blockers, audit = evaluate_upstream_freshness_gate(sniper_artifact=None)
    assert ok is True
    assert blockers == []
    assert audit["status"] == "no_sniper_artifact"


def test_evaluate_upstream_freshness_gate_blocks_missing_or_unparseable_timestamp():
    from m8.discovery.mirror_discovery_recall import evaluate_upstream_freshness_gate

    ok, blockers, _ = evaluate_upstream_freshness_gate(
        sniper_artifact={"no_timestamp_here": True}
    )
    assert ok is False
    assert "SNIPER_TIMESTAMP_MISSING" in blockers
    ok, blockers, _ = evaluate_upstream_freshness_gate(
        sniper_artifact={"generated_at_utc": "not-a-timestamp"}
    )
    assert ok is False
    assert "SNIPER_TIMESTAMP_UNPARSEABLE" in blockers
