"""Integration tests for state.postgres against a real PostgreSQL instance.

Skipped unless ``PG_TEST_DSN`` env var is set. Run locally with:

    PG_TEST_DSN="dbname=arby_test user=postgres" \\
        py -3.11 -m pytest tests/integration/test_postgres_monotonic_contract.py -q

These tests pin the production-readiness review's blocker (issue 3):

* Pools/routes/tokens upserts are monotone: an older replay must NOT
  overwrite a newer observation.
* Same-observation replays are idempotent ( UNIQUE on idempotency_key).
* ``latest_artifact_pointer()`` returns the original ``IdempotencyKey``
  (not the zeroed placeholder from a previous regression).
* ``ensure_schema()`` is idempotent: applying the migration set twice
  yields the same ledger and does not error.
"""
from __future__ import annotations

import os
import uuid

import pytest

pg_dsn = os.environ.get("PG_TEST_DSN")
pytestmark = pytest.mark.skipif(
    not pg_dsn,
    reason="PG_TEST_DSN not set; set it to a test-database DSN to enable "
    "real-PostgreSQL integration tests.",
)


def _repo():
    from state.postgres import PostgresStateRepository

    repo = PostgresStateRepository(pg_dsn)  # type: ignore[arg-type]
    repo.ensure_schema()
    # Truncate the inventory tables we mutate so tests start from a clean
    # state; the migrations ledger is preserved.
    with repo.transaction():
        repo._conn.execute(  # type: ignore[attr-defined]
            "TRUNCATE pools, routes, tokens, artifact_pointers RESTART IDENTITY CASCADE"
        )
    return repo


def _key(entity_id: str, *, block_number: int = 100, chain_id: int = 8453):
    from state.repository import IdempotencyKey

    return IdempotencyKey(
        chain_id=chain_id,
        block_number=block_number,
        entity_id=entity_id,
        input_revision=str(uuid.uuid4()),
    )


def test_ensure_schema_is_idempotent():
    repo = _repo()
    repo.ensure_schema()
    repo.ensure_schema()
    cur = repo._conn.execute(  # type: ignore[attr-defined]
        "SELECT migration_id FROM schema_migrations ORDER BY migration_id"
    )
    ids = [int(row[0]) for row in cur.fetchall()]
    from state.postgres import MIGRATIONS

    assert ids == [m[0] for m in MIGRATIONS]


def test_pool_monotonic_guard_older_replay_does_not_clobber_newer():
    from state.repository import PoolRecord

    repo = _repo()
    pool_addr = "0x" + "ab" * 20
    with repo.transaction():
        repo.upsert_pool(
            PoolRecord(
                chain_id=8453,
                dex_id="uniswap_v3",
                pool_address=pool_addr,
                token0="0xT0",
                token1="0xT1",
                pool_type="v3",
                fee=3000,
                status="active",
                idempotency=_key(pool_addr, block_number=100),
                extra={"liquidity_usd": "1000"},
            )
        )
        repo.upsert_pool(
            PoolRecord(
                chain_id=8453,
                dex_id="uniswap_v3",
                pool_address=pool_addr,
                token0="0xT0",
                token1="0xT1",
                pool_type="v3",
                fee=3000,
                status="active",
                idempotency=_key(pool_addr, block_number=200),
                extra={"liquidity_usd": "2500"},
            )
        )
        # Older replay from block 50 must not overwrite the block-200 row.
        repo.upsert_pool(
            PoolRecord(
                chain_id=8453,
                dex_id="uniswap_v2",
                pool_address=pool_addr,
                token0="0xT0_OLD",
                token1="0xT1_OLD",
                pool_type="v2",
                fee=None,
                status="dead",
                idempotency=_key(pool_addr, block_number=50),
                extra={"liquidity_usd": "5"},
            )
        )
    cur = repo._conn.execute(  # type: ignore[attr-defined]
        "SELECT dex_id, status, extra->>'liquidity_usd', observed_block "
        "FROM pools WHERE chain_id = 8453 AND pool_address = %s",
        (pool_addr,),
    )
    row = cur.fetchone()
    assert row is not None
    assert row[0] == "uniswap_v3"
    assert row[1] == "active"
    assert row[2] == "2500"
    assert int(row[3]) == 200


def test_route_monotonic_guard():
    from state.repository import RouteRecord

    repo = _repo()
    route_id = "r_1"
    with repo.transaction():
        for blk, dex in [(100, "uniswap_v3"), (200, "aerodrome"), (50, "sushi")]:
            repo.upsert_route(
                RouteRecord(
                    chain_id=8453,
                    route_id=route_id,
                    dex_id=dex,
                    token_in="0xT0",
                    token_out="0xT1",
                    pool_address="0x" + "cd" * 20,
                    status="active" if blk != 50 else "dead",
                    idempotency=_key(route_id, block_number=blk),
                    extra={"v": str(blk)},
                )
            )
    cur = repo._conn.execute(  # type: ignore[attr-defined]
        "SELECT dex_id, status, extra->>'v', observed_block "
        "FROM routes WHERE chain_id = 8453 AND route_id = %s",
        (route_id,),
    )
    row = cur.fetchone()
    assert row is not None
    assert row[0] == "aerodrome"
    assert int(row[3]) == 200


def test_token_monotonic_guard_and_idempotent_replay():
    repo = _repo()
    address = "0x" + "ef" * 20
    with repo.transaction():
        repo.upsert_token(
            chain_id=8453,
            address=address,
            decimals=18,
            symbol="FOO",
            idempotency=_key(address, block_number=100),
        )
        repo.upsert_token(
            chain_id=8453,
            address=address,
            decimals=6,
            symbol="BAR",
            idempotency=_key(address, block_number=200),
        )
        # Older replay with confuse-decimals must NOT overwrite.
        repo.upsert_token(
            chain_id=8453,
            address=address,
            decimals=2,
            symbol="OLD",
            idempotency=_key(address, block_number=50),
        )
    cur = repo._conn.execute(  # type: ignore[attr-defined]
        "SELECT decimals, symbol, observed_block FROM tokens "
        "WHERE chain_id = 8453 AND address = %s",
        (address,),
    )
    row = cur.fetchone()
    assert row is not None
    assert int(row[0]) == 6
    assert row[1] == "BAR"
    assert int(row[2]) == 200


def test_latest_artifact_pointer_reconstructs_original_idempotency_key():
    from state.repository import ArtifactPointer, IdempotencyKey

    repo = _repo()
    expected_key = IdempotencyKey(
        chain_id=8453,
        block_number=4242,
        entity_id="m9_bridge_inventory",
        input_revision="rev-2026-07-19T11:00:00Z",
    )
    with repo.transaction():
        repo.upsert_artifact_pointer(
            ArtifactPointer(
                artifact_family="m9_bridge_inventory",
                artifact_path="data/tmp/m9_bridge_inventory_production_latest.json",
                run_timestamp="2026-07-19T11:00:00+00:00",
                content_digest="sha256:abc",
                idempotency=expected_key,
            )
        )
    pointer = repo.latest_artifact_pointer("m9_bridge_inventory")
    assert pointer is not None
    assert pointer.idempotency.chain_id == expected_key.chain_id
    assert pointer.idempotency.block_number == expected_key.block_number
    assert pointer.idempotency.entity_id == expected_key.entity_id
    assert pointer.idempotency.input_revision == expected_key.input_revision
    assert pointer.idempotency.digest() == expected_key.digest()


def test_idempotent_replay_of_same_pool_write_is_no_op():
    """A same-observation replay (same idempotency_key) MUST not error and
    MUST not create a duplicate row in pools."""
    from state.repository import PoolRecord

    repo = _repo()
    pool_addr = "0x" + "12" * 20
    key = _key(pool_addr, block_number=100)
    pool = PoolRecord(
        chain_id=8453,
        dex_id="uniswap_v3",
        pool_address=pool_addr,
        token0="0xT0",
        token1="0xT1",
        pool_type="v3",
        fee=3000,
        status="active",
        idempotency=key,
        extra={"v": "1"},
    )
    with repo.transaction():
        repo.upsert_pool(pool)
    with repo.transaction():
        repo.upsert_pool(pool)  # identical replay
    cur = repo._conn.execute(  # type: ignore[attr-defined]
        "SELECT count(*) FROM pools WHERE chain_id = 8453 AND pool_address = %s",
        (pool_addr,),
    )
    assert int(cur.fetchone()[0]) == 1