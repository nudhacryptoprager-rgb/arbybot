"""Vertical migration tests (Step 4): M8 sniper -> StateRepository ->
JSON projection -> read-only API.

These tests pin the contract that:
* ``m8.runtime.pool_repository_sink.ingest_sniper_pool_records`` translates
  ``new_pool_sniper_latest.json`` style ``recent_events`` into
  ``PoolRecord`` rows and commits them through any ``StateRepository``
  in one transaction.
* ``state.in_memory.InMemoryStateRepository`` behaves like the Postgres
  adapter: monotonic by ``observed_block``, idempotent by idempotency key.
* ``api.app.ApiApp`` serves the projection via ``/v1/artifacts/m8_pools/latest``.
"""
from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from api.app import ApiApp
from m8.runtime.pool_repository_sink import (
    ingest_sniper_pool_records,
    sniper_events_to_pool_records,
)
from state.in_memory import InMemoryStateRepository
from state.json_export import export_rows_to_json
from state.repository import IdempotencyKey, PoolRecord


CHAIN_ID_MAP = {"base": 8453, "arbitrum_one": 42161}


def _valid_event(*, event_id: str, pool: str = "0x" + "ab" * 20, block: int = 100):
    return {
        "event_id": event_id,
        "chain": "base",
        "dex": "uniswap_v3",
        "factory": "0x" + "f1" * 20,
        "pool": pool,
        "token0": "0x" + "0a" * 20,
        "token1": "0x" + "1b" * 20,
        "block_number": block,
        "received_ts": 1700000000.0,
        "filter_passed": True,
        "candidate": True,
        "reject_reason": None,
        "adapter_type": "uniswap_v3",
        "fee": 3000,
    }


def test_sniper_events_to_pool_records_admits_valid_events():
    events = [_valid_event(event_id="e1"), _valid_event(event_id="e2")]
    records, stats = sniper_events_to_pool_records(
        events,
        run_timestamp="2026-07-19T11:00:00Z",
        chain_id_map=CHAIN_ID_MAP,
    )
    assert stats["admitted"] == 2
    assert stats["skipped_no_pool"] == 0
    assert len(records) == 2
    rec = records[0]
    assert rec.chain_id == 8453
    assert rec.dex_id == "uniswap_v3"
    assert rec.fee == 3000
    assert rec.status == "active"
    assert rec.idempotency.entity_id == "sniper:e1"
    assert rec.idempotency.input_revision == "2026-07-19T11:00:00Z"
    assert rec.idempotency.block_number == 100
    # All legacy sniper fields are preserved in extra for the projection.
    assert rec.extra["factory"].startswith("0x")
    assert rec.extra["source_artifact_run_timestamp"] == "2026-07-19T11:00:00Z"


def test_sniper_events_to_pool_records_skips_short_or_non_pool_addresses():
    events = [
        {"event_id": "e_bad", "chain": "base", "dex": "x", "pool": "0xabc"},
        {"event_id": "e_ok", "chain": "base", "dex": "x", "pool": "0x" + "cd" * 20},
    ]
    records, stats = sniper_events_to_pool_records(
        events, run_timestamp="ts", chain_id_map=CHAIN_ID_MAP
    )
    assert stats["admitted"] == 1
    assert stats["skipped_no_pool"] == 1
    assert len(records) == 1
    assert records[0].pool_address == "0x" + "cd" * 20


def test_sniper_events_to_pool_records_skips_unknown_chain_without_writing_chain_id_zero():
    events = [
        {"event_id": "e1", "chain": "fantasy_chain", "dex": "x", "pool": "0x" + "cd" * 20}
    ]
    records, stats = sniper_events_to_pool_records(
        events, run_timestamp="ts", chain_id_map=CHAIN_ID_MAP
    )
    assert records == []
    assert stats["skipped_unknown_chain"] == 1
    assert stats["admitted"] == 0


def test_ingest_sniper_pool_records_writes_in_one_transaction_and_is_idempotent():
    repo = InMemoryStateRepository()
    art = {
        "run_context": {
            "run_timestamp": "2026-07-19T11:00:00Z",
            "session_id": "session-A",
        },
        "recent_events": [
            _valid_event(event_id="e1", block=100, pool="0x" + "a1" * 20),
            _valid_event(event_id="e2", block=101, pool="0x" + "b2" * 20),
        ],
    }
    out1 = ingest_sniper_pool_records(art, repo, chain_id_map=CHAIN_ID_MAP)
    assert out1["admitted"] == 2
    assert out1["committed"] == 2
    # Re-ingesting the same artifact is a no-op: same idempotency digest, same
    # block, so monotonic guard short-circuits and the row set stays the same.
    out2 = ingest_sniper_pool_records(art, repo, chain_id_map=CHAIN_ID_MAP)
    assert out2["committed"] == 2
    assert len(repo.pools()) == 2
    # Observed block is stored.
    blocks = sorted(int(r["observed_block"]) for r in repo.pools())
    assert blocks == [100, 101]


def test_ingest_does_not_clobber_newer_observation_with_older_replay():
    repo = InMemoryStateRepository()
    fresh_art = {
        "run_context": {"run_timestamp": "2026-07-19T12:00:00Z"},
        "recent_events": [_valid_event(event_id="e1", block=200)],
    }
    ingest_sniper_pool_records(fresh_art, repo, chain_id_map=CHAIN_ID_MAP)
    # Now an older artifact (same event_id, same pool, but earlier block)
    # arrives and must NOT overwrite the block-200 row.
    stale_art = {
        "run_context": {"run_timestamp": "2026-07-19T10:00:00Z"},
        "recent_events": [
            {
                **_valid_event(event_id="e1", block=50),
                "dex": "uniswap_v2",
                "fee": 10000,
                "pool_type": "v2",
            }
        ],
    }
    ingest_sniper_pool_records(stale_art, repo, chain_id_map=CHAIN_ID_MAP)
    rows = repo.pools()
    assert len(rows) == 1
    row = rows[0]
    assert row["dex_id"] == "uniswap_v3"  # not stale'd to v2
    assert int(row["observed_block"]) == 200
    assert row["extra"]["source_artifact_run_timestamp"] == "2026-07-19T12:00:00Z"


def test_projection_roundtrips_decimal_in_extra_safe():
    """The exported m8_pools projection carries extra decimals as strings
    (Roadmap §3.2 no-float-money applies to repository exports too)."""
    repo = InMemoryStateRepository()
    pool = PoolRecord(
        chain_id=8453,
        dex_id="uniswap_v3",
        pool_address="0x" + "ab" * 20,
        token0="0x" + "0a" * 20,
        token1="0x" + "1b" * 20,
        pool_type="v3",
        fee=3000,
        status="active",
        idempotency=IdempotencyKey(
            chain_id=8453,
            block_number=100,
            entity_id="sniper:e1",
            input_revision="2026-07-19T12:00:00Z",
        ),
        extra={
            "liquidity_usd": Decimal("123456.789012345678901234"),
            "price_wei": Decimal("0.000000000000000001"),
        },
    )
    with repo.transaction():
        repo.upsert_pool(pool)
    rows = repo.pools()
    rows_for_export = [
        {
            "chain_id": r["chain_id"],
            "pool_address": r["pool_address"],
            "dex_id": r["dex_id"],
            "extra": r["extra"],
            "idempotency_key": r["idempotency_key"],
        }
        for r in rows
    ]
    out = export_rows_to_json(rows_for_export, "data/tmp/m8_pools_repository_projection_latest_test.json")
    raw = json.loads(out.read_text(encoding="utf-8"))
    extra = raw["items"][0]["extra"]
    assert extra["liquidity_usd"] == "123456.789012345678901234"
    assert extra["price_wei"] == "0.000000000000000001"


def test_api_serves_m8_pools_artifact_when_present(tmp_path):
    payload = {
        "items": [
            {
                "chain_id": 8453,
                "pool_address": "0x" + "ab" * 20,
                "dex_id": "uniswap_v3",
                "extra": {"liquidity_usd": "1000.0"},
            }
        ]
    }
    art_dir = tmp_path / "data" / "tmp"
    art_dir.mkdir(parents=True, exist_ok=True)
    art_path = art_dir / "m8_pools_repository_projection_latest.json"
    art_path.write_text(json.dumps(payload), encoding="utf-8")
    app = ApiApp(repo_root=tmp_path)
    status, _headers, body = app.handle("GET", "/v1/artifacts/m8_pools/latest")
    assert status == 200
    data = json.loads(body.decode("utf-8"))
    assert data["items"][0]["pool_address"] == "0x" + "ab" * 20


def test_api_m8_pools_404_when_projection_absent():
    app = ApiApp(repo_root=".")
    status, _headers, _body = app.handle("GET", "/v1/artifacts/m8_pools/latest")
    assert status == 404


def test_load_chain_id_map_handles_missing_yaml(tmp_path):
    """load_chain_id_map is resilient: missing config/yaml returns an empty
    map so callers skip unknown-chain events instead of crashing."""
    from collections.abc import Mapping

    from m8.runtime.pool_repository_sink import load_chain_id_map

    result = load_chain_id_map(tmp_path / "nonexistent.yaml")
    assert isinstance(result, Mapping)
    assert dict(result) == {}


def test_load_chain_id_map_parses_real_or_empty(tmp_path):
    from m8.runtime.pool_repository_sink import load_chain_id_map

    path = tmp_path / "chains.yaml"
    path.write_text("base:\n  chain_id: 8453\narbitrum_one:\n  chain_id: 42161\n", encoding="utf-8")
    result = load_chain_id_map(path)
    assert result == {"base": 8453, "arbitrum_one": 42161}