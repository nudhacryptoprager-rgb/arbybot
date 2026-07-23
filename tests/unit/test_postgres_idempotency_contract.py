"""Offline contract tests for state.postgres.

These tests pin the migration ledger and SQL guarantees without requiring a
real PostgreSQL instance. They give CI deterministic coverage of the
production-readiness review's blocker (issue 3: idempotency + monotonic
guards + IdempotencyKey reconstruction). Real PostgreSQL integration is
exercised by ``tests/integration/test_postgres_monotonic_contract.py`` when a
``PG_TEST_DSN`` env var is supplied (skip otherwise).
"""
from __future__ import annotations

import re

from state.postgres import MIGRATIONS, SCHEMA_DDL


def test_migrations_are_sorted_and_unique():
    ids = [m[0] for m in MIGRATIONS]
    assert ids == sorted(ids)
    assert len(ids) == len(set(ids))
    assert ids[0] == 1
    names = [m[1] for m in MIGRATIONS]
    assert len(names) == len(set(names))


def test_migrations_have_names_and_sql():
    for migration_id, name, sql in MIGRATIONS:
        assert isinstance(migration_id, int) and migration_id > 0
        assert isinstance(name, str) and name
        assert isinstance(sql, str) and sql.strip()
        # Each migration must be idempotent at the DDL level so the ledger
        # can resume after a partial apply.
        assert "IF NOT EXISTS" in sql or "DROP CONSTRAINT" in sql, (
            f"migration {migration_id} ({name}) must use idempotent DDL"
        )


def test_migration_0001_is_initial_schema():
    assert MIGRATIONS[0][0] == 1
    assert MIGRATIONS[0][1] == "initial_schema"


def test_migration_0002_adds_monotonic_idempotency_columns():
    sql = MIGRATIONS[1][2]
    assert "observed_block" in sql
    assert "ALTER TABLE pools" in sql
    assert "ALTER TABLE routes" in sql
    assert "ALTER TABLE tokens" in sql
    # Unique idempotency_key constraints on pools / routes / tokens.
    assert "pools_idempotency_key_key" in sql
    assert "routes_idempotency_key_key" in sql
    assert "tokens_idempotency_key_key" in sql
    # Persist IdempotencyKey components on artifact_pointers.
    assert "idempotency_chain_id" in sql
    assert "idempotency_block" in sql
    assert "idempotency_entity_id" in sql
    assert "idempotency_input_revision" in sql


def test_upsert_pool_sql_has_monotonic_where_guard():
    from state.postgres import PostgresStateRepository

    sql = PostgresStateRepository.upsert_pool.__doc__ or ""
    # Pull the function source from the actual code object instead.
    import inspect

    src = inspect.getsource(PostgresStateRepository.upsert_pool)
    assert "observed_block" in src
    assert "WHERE pools.observed_block <= EXCLUDED.observed_block" in src


def test_upsert_route_sql_has_monotonic_where_guard():
    import inspect

    from state.postgres import PostgresStateRepository

    src = inspect.getsource(PostgresStateRepository.upsert_route)
    assert "WHERE routes.observed_block <= EXCLUDED.observed_block" in src


def test_upsert_token_sql_has_monotonic_where_guard():
    import inspect

    from state.postgres import PostgresStateRepository

    src = inspect.getsource(PostgresStateRepository.upsert_token)
    assert "WHERE tokens.observed_block <= EXCLUDED.observed_block" in src


def test_latest_artifact_pointer_reads_persisted_idempotency_components():
    import inspect

    from state.postgres import PostgresStateRepository

    src = inspect.getsource(PostgresStateRepository.latest_artifact_pointer)
    assert "idempotency_chain_id" in src
    assert "idempotency_block" in src
    assert "idempotency_entity_id" in src
    assert "idempotency_input_revision" in src


def test_ensure_schema_creates_migration_ledger():
    import inspect

    from state.postgres import PostgresStateRepository

    src = inspect.getsource(PostgresStateRepository.ensure_schema)
    assert "schema_migrations" in src
    assert "INSERT INTO schema_migrations" in src
    # Must apply migrations in id order and skip already-applied ids.
    assert "ORDER BY migration_id" in src or "for migration_id" in src or "in applied" in src


def test_schema_ddl_union_matches_migrations():
    """SCHEMA_DDL backward-compat constant is the union of migration SQL."""
    expected = "\n\n".join(sql for _, _, sql in MIGRATIONS)
    assert SCHEMA_DDL == expected


def test_migration_0002_constraint_drop_then_create_is_idempotent():
    """Each UNIQUE constraint is DROP-then-ADD so pre-existing deployments
    (where a constraint of the same name already exists) can still apply
    migration 0002 without raising 'relation already exists'. The DROP
    uses ``IF EXISTS`` (PostgreSQL does not support ``IF NOT EXISTS`` for
    DROP CONSTRAINT), so a fresh DB applies without error too."""
    sql = MIGRATIONS[1][2]
    drops = re.findall(r"DROP CONSTRAINT IF EXISTS (\w+)", sql)
    creates = re.findall(r"ADD CONSTRAINT (\w+) UNIQUE", sql)
    assert set(drops) == set(creates), (
        f"DROP/CREATE constraints mismatch: drops={set(drops)} creates={set(creates)}"
    )
    for name in creates:
        full_drop = f"DROP CONSTRAINT IF EXISTS {name}"
        assert full_drop in sql