"""Tests for stale-aware mirror recall verification."""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from m8.discovery.mirror_discovery_recall import (
    build_stale_mirror_backlog,
    build_verify_rca,
    mirror_row_from_hint,
    run_mirror_selection_pass,
    verify_supported_hints,
)
from m8.discovery.mirror_recall_verify import (
    STALE_BUT_POOL_EXISTS,
    mirror_age_bucket,
    verify_hint_for_recall,
)
from m8.discovery.pool_hints import (
    HINT_ONCHAIN_VERIFIED,
    HINT_STALE,
    RECALL_HOT_STALE_HOURS,
    PoolHint,
    hint_is_stale,
    hint_is_stale_for_recall,
)


def _stale_hint(*, dex_id: str = "uniswap_v3", pool: str = "0x" + "a" * 40) -> PoolHint:
    old = datetime.now(tz=timezone.utc) - timedelta(days=30)
    return PoolHint(
        source="dexscreener",
        chain="base",
        dex_id=dex_id,
        pool_address=pool,
        token0_addr="0x" + "1" * 40,
        token1_addr="0x" + "2" * 40,
        focus_token="0x" + "1" * 40,
        created_at=old.strftime("%Y-%m-%dT%H:%M:%SZ"),
        raw={"support_status": "supported", "raw_dex_id": "uniswap"},
    )


@pytest.fixture(autouse=True)
def _clear_skip_rpc(monkeypatch):
    monkeypatch.delenv("ARBY_SKIP_RPC", raising=False)


def test_mirror_age_bucket_buckets():
    now = datetime(2026, 6, 29, 12, 0, tzinfo=timezone.utc)
    base = dict(
        source="dexscreener",
        chain="base",
        dex_id="uniswap_v3",
        pool_address="0x" + "a" * 40,
        token0_addr="0x" + "1" * 40,
        token1_addr="0x" + "2" * 40,
    )
    fresh = PoolHint(**base, created_at="2026-06-29T11:30:00Z")
    week = PoolHint(**base, created_at="2026-06-20T12:00:00Z")
    assert mirror_age_bucket(fresh, now=now) == "<1h"
    assert mirror_age_bucket(week, now=now) == ">7d"
    assert mirror_age_bucket(PoolHint(**base)) == "unknown"


def test_recall_staleness_splits_hot_vs_audit_window():
    base = dict(
        source="dexscreener",
        chain="base",
        dex_id="uniswap_v3",
        pool_address="0x" + "a" * 40,
        token0_addr="0x" + "1" * 40,
        token1_addr="0x" + "2" * 40,
    )
    three_days = datetime.now(tz=timezone.utc) - timedelta(hours=72)
    hint = PoolHint(**base, created_at=three_days.strftime("%Y-%m-%dT%H:%M:%SZ"))
    assert hint_is_stale_for_recall(hint, max_age_hours=RECALL_HOT_STALE_HOURS) is True
    assert hint_is_stale(hint) is False


def test_missing_created_at_is_stale_for_recall_not_audit():
    hint = PoolHint(
        source="dexscreener",
        chain="base",
        dex_id="uniswap_v3",
        pool_address="0x" + "a" * 40,
        token0_addr="0x" + "1" * 40,
        token1_addr="0x" + "2" * 40,
    )
    assert hint_is_stale_for_recall(hint) is True
    assert hint_is_stale(hint) is False


@patch("m8.discovery.mirror_recall_verify.verify_factory_pool", return_value=(True, "factory_getPool"))
def test_missing_created_at_routes_to_existence_not_selection(mock_factory):
    hint = PoolHint(
        source="dexscreener",
        chain="base",
        dex_id="uniswap_v3",
        pool_address="0x" + "a" * 40,
        token0_addr="0x" + "1" * 40,
        token1_addr="0x" + "2" * 40,
        focus_token="0x" + "1" * 40,
        raw={"support_status": "supported", "raw_dex_id": "uniswap"},
    )
    verified = verify_hint_for_recall(hint, chain="base")
    raw = verified.raw or {}
    assert raw["is_stale_hint"] is True
    assert raw["recall_verified_pool_exists"] is True
    assert raw["selection_verified_fresh"] is False
    assert raw["selection_verification_status"] == "selection_blocked_stale"
    mock_factory.assert_called_once()


@patch("m8.discovery.mirror_recall_verify.verify_factory_pool", return_value=(True, "factory_getPool"))
def test_stale_hint_pool_exists_counts_for_recall_not_selection(mock_factory):
    stale = _stale_hint()
    verified = verify_hint_for_recall(stale, chain="base")
    raw = verified.raw or {}
    assert raw["recall_verified_pool_exists"] is True
    assert raw["selection_verified_fresh"] is False
    assert raw["stale_recall_bucket"] == STALE_BUT_POOL_EXISTS
    assert verified.hint_status == HINT_STALE


@patch(
    "m8.discovery.uniswap_v4_pool_resolver.resolve_v4_pool_existence",
    return_value=(True, "V4_POOLID_EXISTS", "v4_stateview"),
)
def test_stale_v4_uses_poolid_path(mock_v4):
    hint = _stale_hint(
        dex_id="uniswap_v4",
        pool="0x" + "f" * 64,
    )
    verified = verify_hint_for_recall(hint, chain="base")
    mock_v4.assert_called_once()
    assert (verified.raw or {})["recall_verified_pool_exists"] is True


@patch("m8.discovery.mirror_discovery_recall.verify_hint_for_recall")
def test_verify_supported_hints_splits_recall_and_selection(mock_recall):
    hint = _stale_hint()
    recall_hint = PoolHint.from_dict(hint.to_dict())
    recall_hint.raw = {
        **(recall_hint.raw or {}),
        "recall_verified_pool_exists": True,
        "selection_verified_fresh": False,
        "pool_exists_stale": True,
        "stale_recall_bucket": STALE_BUT_POOL_EXISTS,
        "existence_rca_bucket": STALE_BUT_POOL_EXISTS,
        "selection_verification_status": "selection_blocked_stale",
        "mirror_age_bucket": ">7d",
        "is_stale_hint": True,
    }
    recall_hint.hint_status = HINT_STALE
    mock_recall.return_value = recall_hint
    out, rca, _rows = verify_supported_hints([hint], dry_run=False)
    assert rca["recall_verified_pool_exists_total"] == 1
    assert rca["pool_exists_stale_total"] == 1
    assert rca["selection_verified_fresh_total"] == 0
    assert rca["stale_recall_bucket_histogram"][STALE_BUT_POOL_EXISTS] == 1


def test_stale_mirror_backlog_and_selection_stages():
    mirrors = [
        {
            "token": "0xaaa",
            "is_stale_hint": True,
            "recall_verified_pool_exists": True,
            "selection_verified_fresh": False,
            "stale_recall_bucket": STALE_BUT_POOL_EXISTS,
        },
        {
            "token": "0xbbb",
            "is_stale_hint": True,
            "recall_verified_pool_exists": False,
            "selection_verified_fresh": False,
            "stale_recall_bucket": "STALE_POOL_NOT_FOUND",
        },
    ]
    backlog = build_stale_mirror_backlog(mirrors)
    assert len(backlog) == 1

    fresh_hint = PoolHint(
        source="dexscreener",
        chain="base",
        dex_id="uniswap_v3",
        pool_address="0x" + "b" * 40,
        token0_addr="0x" + "1" * 40,
        token1_addr="0x" + "2" * 40,
        focus_token="0x" + "1" * 40,
        hint_status=HINT_ONCHAIN_VERIFIED,
        raw={
            "support_status": "supported",
            "recall_verified_pool_exists": True,
            "selection_verified_fresh": True,
        },
    )
    selection = run_mirror_selection_pass(
        {"chain": "base", "all_dex_mirrors_total": 2},
        hints=[fresh_hint],
        output_path=__import__("pathlib").Path("data/tmp/test_mirror_selection_out.json"),
        selection_artifact_path=__import__("pathlib").Path("data/tmp/test_mirror_selection_latest.json"),
    )
    assert selection["selection_stages"]["recall"] == 2
    assert selection["selection_stages"]["pool_exists"] == 1
    assert selection["selection_stages"]["fresh_enough"] == 1
