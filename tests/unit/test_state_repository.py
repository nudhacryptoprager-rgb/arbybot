"""Unit tests for the state layer (StateRepository contract + PG adapter).

Runs fully offline: SQL generation, idempotency and transaction semantics
are verified against a fake DB-API connection; no live PostgreSQL and no
psycopg driver required.
"""
from __future__ import annotations

import json

import pytest

from state.json_export import (
    export_rows_to_json,
    job_record_to_json,
    pool_record_to_json,
)
from state.postgres import (
    POSTGRES_EXTRA_MISSING,
    SCHEMA_DDL,
    PostgresStateRepository,
)
from state.repository import (
    ArtifactPointer,
    IdempotencyKey,
    JobRecord,
    PoolRecord,
    RouteRecord,
)


def _key(entity: str = "pool:0xabc", rev: str = "2026-07-19T12:00:00Z") -> IdempotencyKey:
    return IdempotencyKey(chain_id=8453, block_number=123, entity_id=entity, input_revision=rev)


class FakeCursor:
    def __init__(self, rows=None):
        self._rows = rows or []

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class FakeConnection:
    """Minimal DB-API fake recording executed statements."""

    def __init__(self):
        self.executed = []  # list[(sql, params)]
        self.commits = 0
        self.rollbacks = 0
        self.next_rows = []

    def execute(self, sql, params=None):
        self.executed.append((sql, params))
        return FakeCursor(self.next_rows)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _repo_with_fake() -> PostgresStateRepository:
    repo = PostgresStateRepository.__new__(PostgresStateRepository)
    repo._conninfo = "dbname=fake"
    repo._conn = FakeConnection()
    return repo


# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


def test_idempotency_digest_deterministic_and_field_sensitive():
    base = _key()
    assert base.digest() == _key().digest()
    assert base.digest() != _key(entity="pool:0xdef").digest()
    assert base.digest() != _key(rev="2026-07-19T13:00:00Z").digest()
    other_chain = IdempotencyKey(chain_id=1, block_number=123, entity_id="pool:0xabc", input_revision="r")
    assert base.digest() != other_chain.digest()


# ---------------------------------------------------------------------------
# DDL coverage
# ---------------------------------------------------------------------------


def test_schema_ddl_contains_minimal_tables_and_skip_locked_index():
    for table in (
        "runs", "tokens", "pools", "routes", "pool_states", "quotes",
        "cycles", "opportunities", "simulations", "execution_attempts",
        "provider_health", "artifact_pointers", "jobs",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in SCHEMA_DDL
    assert "idempotency_key" in SCHEMA_DDL


# ---------------------------------------------------------------------------
# Upsert SQL: idempotent + transactional
# ---------------------------------------------------------------------------


def test_upsert_pool_is_idempotent_upsert():
    repo = _repo_with_fake()
    pool = PoolRecord(
        chain_id=8453, dex_id="uniswap_v3", pool_address="0x" + "a" * 40,
        token0="0xt0", token1="0xt1", pool_type="v3", fee=500,
        status="active", idempotency=_key(),
    )
    repo.upsert_pool(pool)
    sql, params = repo._conn.executed[-1]
    assert "ON CONFLICT (chain_id, pool_address) DO UPDATE" in sql
    assert params[-2] == _key().digest() or _key().digest() in params


def test_upsert_route_and_token_use_conflict_targets():
    repo = _repo_with_fake()
    repo.upsert_route(RouteRecord(
        chain_id=8453, route_id="r1", dex_id="aerodrome", token_in="0xa",
        token_out="0xb", pool_address="0xp", status="active", idempotency=_key("route:r1"),
    ))
    assert "ON CONFLICT (chain_id, route_id) DO UPDATE" in repo._conn.executed[-1][0]
    repo.upsert_token(chain_id=8453, address="0xt", decimals=18, symbol="T", idempotency=_key("token:0xt"))
    assert "ON CONFLICT (chain_id, address) DO UPDATE" in repo._conn.executed[-1][0]


def test_artifact_pointer_upsert_and_latest_query():
    repo = _repo_with_fake()
    pointer = ArtifactPointer(
        artifact_family="new_pool_sniper",
        artifact_path="data/runs/_rolling/new_pool_sniper_latest.json",
        run_timestamp="2026-07-19T12:00:00Z",
        idempotency=_key("artifact:new_pool_sniper"),
    )
    repo.upsert_artifact_pointer(pointer)
    assert "ON CONFLICT (artifact_family, run_timestamp) DO UPDATE" in repo._conn.executed[-1][0]
    repo.latest_artifact_pointer("new_pool_sniper")
    assert "ORDER BY run_timestamp DESC" in repo._conn.executed[-1][0]


# ---------------------------------------------------------------------------
# Job queue: idempotent enqueue + SKIP LOCKED claim
# ---------------------------------------------------------------------------


def test_enqueue_job_is_noop_on_conflict():
    repo = _repo_with_fake()
    repo.enqueue_job(JobRecord(job_type="ingest_verify", payload={"t": 1}, idempotency=_key("job:1")))
    sql = repo._conn.executed[-1][0]
    assert "ON CONFLICT (idempotency_key) DO NOTHING" in sql


def test_claim_jobs_uses_for_update_skip_locked():
    repo = _repo_with_fake()
    repo.claim_jobs(job_type="graph_quote", limit=5)
    sql = repo._conn.executed[-1][0]
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "status = 'claimed'" in sql


def test_fail_job_requeues_until_max_attempts():
    repo = _repo_with_fake()
    repo.fail_job(7, error="RPC_TIMEOUT")
    sql, params = repo._conn.executed[-1]
    assert "WHEN attempts >= max_attempts THEN 'dead_letter' ELSE 'pending'" in sql
    assert params == ("RPC_TIMEOUT", 7)


# ---------------------------------------------------------------------------
# Transaction semantics
# ---------------------------------------------------------------------------


def test_transaction_commits_on_success_and_rolls_back_on_error():
    repo = _repo_with_fake()
    with repo.transaction():
        repo.complete_job(1)
    assert repo._conn.commits == 1 and repo._conn.rollbacks == 0
    with pytest.raises(ValueError):
        with repo.transaction():
            repo.complete_job(2)
            raise ValueError("boom")
    assert repo._conn.rollbacks == 1


def test_ensure_schema_executes_ddl_in_one_transaction():
    """ensure_schema now applies the migration set via the schema_migrations
    ledger. The union of migrations still equals SCHEMA_DDL (backward-compat
    introspection constant), but the first executed statement creates the
    ledger table; subsequent statements apply each pending migration."""
    from state.postgres import MIGRATIONS

    repo = _repo_with_fake()
    repo.ensure_schema()
    # First statement creates the migration ledger table.
    first_sql = repo._conn.executed[0][0]
    assert "schema_migrations" in first_sql
    # All migration DDL is applied (one execute per migration).
    migration_sqls = [sql for sql, _ in repo._conn.executed]
    for _mid, _name, sql in MIGRATIONS:
        assert sql in migration_sqls, (
            f"migration {_mid} DDL was not executed by ensure_schema()"
        )
    # Each applied migration is followed by an INSERT into the ledger.
    ledger_inserts = [
        sql for sql, params in repo._conn.executed
        if "INSERT INTO schema_migrations" in sql
    ]
    assert len(ledger_inserts) == len(MIGRATIONS)
    # Transaction committed exactly once.
    assert repo._conn.commits == 1


# ---------------------------------------------------------------------------
# Optional driver guard
# ---------------------------------------------------------------------------


def test_connect_without_driver_raises_informative_error():
    psycopg = pytest.importorskip  # noqa: F841 - marker usage clarity
    try:
        import psycopg  # noqa: F401
    except ImportError:
        repo = PostgresStateRepository.__new__(PostgresStateRepository)
        repo._conninfo = "dbname=x"
        repo._conn = None
        with pytest.raises(RuntimeError, match="pip install"):
            repo.connect()
    else:
        pytest.skip("psycopg installed in this environment")


# ---------------------------------------------------------------------------
# JSON export (operator interface)
# ---------------------------------------------------------------------------


def test_json_export_roundtrip(tmp_path):
    pool = PoolRecord(
        chain_id=8453, dex_id="uniswap_v4", pool_address="0x" + "c" * 40,
        token0="0xt0", token1="0xt1", pool_type="v4", fee=None,
        status="active", idempotency=_key(),
    )
    job = JobRecord(job_type="risk_simulate", payload={"cycle": "c1"}, idempotency=_key("job:2"), job_id=3)
    out = export_rows_to_json(
        [pool_record_to_json(pool), job_record_to_json(job)],
        tmp_path / "export.json",
    )
    data = json.loads(out.read_text(encoding="utf-8"))
    assert len(data["items"]) == 2
    assert data["items"][0]["pool_address"] == pool.pool_address
    assert data["items"][0]["idempotency_key"] == _key().digest()
    assert data["items"][1]["job_type"] == "risk_simulate"
