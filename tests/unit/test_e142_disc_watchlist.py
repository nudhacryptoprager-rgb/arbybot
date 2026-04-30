"""E1.42 Iter 2 — DISC→PROD watchlist with TTL: unit tests."""

from __future__ import annotations

import json
import os
import tempfile

import pytest

from m7.orderflow import disc_watchlist as wl


@pytest.fixture
def tmp_path_isolated(tmp_path, monkeypatch):
    p = tmp_path / "m7_disc_watchlist.json"
    monkeypatch.setenv("ARBY_DISC_WATCHLIST_PATH", str(p))
    yield str(p)


def test_read_empty_returns_canonical_payload(tmp_path_isolated):
    payload = wl.read_watchlist()
    assert payload == {
        "schema_version": "1.0",
        "updated_at_epoch": 0,
        "entries": [],
    }


def test_record_then_read(tmp_path_isolated):
    wl.record_profitable_pair(
        pair_address="0x4bfaa776991e85e5f8b1255461cbbd216cfc714f",
        token_a="0xaaa",
        token_b="0xbbb",
        buy_venue="pancakeswap_v3",
        buy_fee=500,
        sell_venue="uniswap_v3",
        sell_fee=10000,
        profit_bps=91.0771,
        scoring_path="registry_fast",
        session_id="5749662e",
        ttl_seconds=3600,
        now_epoch=1_000_000,
    )
    payload = wl.read_watchlist()
    assert len(payload["entries"]) == 1
    e = payload["entries"][0]
    assert e["pair_address"] == "0x4bfaa776991e85e5f8b1255461cbbd216cfc714f"
    assert e["profit_bps"] == 91.0771
    assert e["expires_at_epoch"] == 1_000_000 + 3600
    assert e["scoring_path"] == "registry_fast"


def test_dedup_replaces_existing_entry(tmp_path_isolated):
    pair = "0xPAIR"
    wl.record_profitable_pair(
        pair_address=pair, profit_bps=10.0, ttl_seconds=3600, now_epoch=1000
    )
    wl.record_profitable_pair(
        pair_address=pair, profit_bps=20.0, ttl_seconds=3600, now_epoch=1500
    )
    payload = wl.read_watchlist()
    assert len(payload["entries"]) == 1
    assert payload["entries"][0]["profit_bps"] == 20.0
    assert payload["entries"][0]["promoted_at_epoch"] == 1500


def test_prune_drops_expired(tmp_path_isolated):
    wl.record_profitable_pair(
        pair_address="0xOLD", profit_bps=5.0, ttl_seconds=100, now_epoch=1000
    )
    wl.record_profitable_pair(
        pair_address="0xNEW", profit_bps=15.0, ttl_seconds=10000, now_epoch=1000
    )
    pruned = wl.prune_expired(wl.read_watchlist(), now_epoch=2000)
    addrs = [e["pair_address"] for e in pruned["entries"]]
    assert "0xnew" in addrs
    assert "0xold" not in addrs


def test_is_pair_active_respects_ttl(tmp_path_isolated):
    wl.record_profitable_pair(
        pair_address="0xABC", profit_bps=5.0, ttl_seconds=100, now_epoch=1000
    )
    assert wl.is_pair_active("0xabc", now_epoch=1050) is True
    assert wl.is_pair_active("0xABC", now_epoch=1050) is True
    assert wl.is_pair_active("0xabc", now_epoch=2000) is False
    assert wl.is_pair_active("0xother", now_epoch=1050) is False


def test_active_pair_addresses(tmp_path_isolated):
    wl.record_profitable_pair(
        pair_address="0xAAA", profit_bps=5.0, ttl_seconds=10000, now_epoch=1000
    )
    wl.record_profitable_pair(
        pair_address="0xBBB", profit_bps=8.0, ttl_seconds=50, now_epoch=1000
    )
    addrs = wl.active_pair_addresses(now_epoch=1100)
    assert "0xaaa" in addrs
    assert "0xbbb" not in addrs


def test_invalid_inputs_rejected(tmp_path_isolated):
    with pytest.raises(ValueError):
        wl.record_profitable_pair(pair_address="", profit_bps=1.0)
    with pytest.raises(ValueError):
        wl.record_profitable_pair(pair_address="0xX", profit_bps=1.0, ttl_seconds=0)


def test_corrupted_file_returns_empty(tmp_path_isolated):
    p = os.environ["ARBY_DISC_WATCHLIST_PATH"]
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write("not json")
    payload = wl.read_watchlist()
    assert payload["entries"] == []


def test_atomic_write_persists_to_disk(tmp_path_isolated):
    wl.record_profitable_pair(
        pair_address="0xPERSIST", profit_bps=12.5, ttl_seconds=600, now_epoch=2000
    )
    p = os.environ["ARBY_DISC_WATCHLIST_PATH"]
    with open(p, "r", encoding="utf-8") as f:
        raw = json.load(f)
    assert raw["schema_version"] == "1.0"
    assert raw["updated_at_epoch"] == 2000
    assert any(e["pair_address"] == "0xpersist" for e in raw["entries"])
