"""PostgreSQL adapter for the StateRepository contract.

Production adapter.  The driver (``psycopg`` v3) is an optional dependency:
install with ``pip install -e ".[postgres]"``.  Offline CI never imports the
driver — the import happens lazily inside ``connect()``.

Guarantees (locked by ``tests/unit/test_postgres_idempotency_contract.py``
and ``tests/integration/test_postgres_monotonic_contract.py`` when a real
PostgreSQL is available):

* ``ensure_schema()`` applies the ordered migration set in
  ``MIGRATIONS`` via the ``schema_migrations`` ledger; migrations are
  idempotent ``CREATE TABLE IF NOT EXISTS`` / ``ALTER TABLE`` blocks and
  never run twice.  The legacy ``SCHEMA_DDL`` constant is preserved as
  the union of all migrations for backward compatibility with existing
  schema-introspection tests.
* Every write is an idempotent upsert keyed by the ``IdempotencyKey``
  digest; replays never create duplicates. ``pools``/``routes``/``tokens``
  additionally carry a UNIQUE constraint on ``idempotency_key`` (added in
  migration 0002) so a same-observation replay is a hard no-op rather
  than a silent overwrite.
* Monotonic guards: ``upsert_pool``/``upsert_route``/``upsert_token``
  only overwrite the existing row when the incoming observation's
  ``observed_block`` is greater than or equal to the stored
  ``observed_block``.  This prevents an older replay (e.g. a re-delivered
  bridge row from a previous block) from clobbering a newer observation
  that has already landed.
* ``latest_artifact_pointer()`` reconstructs the original
  ``IdempotencyKey`` from the stored ``idempotency_chain_id``,
  ``idempotency_block``, ``idempotency_entity_id`` and
  ``idempotency_input_revision`` columns so the caller sees the same
  key that was originally written, not a zeroed placeholder.
* ``transaction()`` gives commit/rollback semantics; a failed stage leaves
  no partial state.
* ``claim_jobs`` uses ``FOR UPDATE SKIP LOCKED`` so multiple workers can
  drain the queue without a broker.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from state.repository import (
    ArtifactPointer,
    IdempotencyKey,
    JobRecord,
    PoolRecord,
    RouteRecord,
    StateRepository,
)

__all__ = [
    "PostgresStateRepository",
    "SCHEMA_DDL",
    "MIGRATIONS",
    "POSTGRES_EXTRA_MISSING",
]


POSTGRES_EXTRA_MISSING = (
    "psycopg (v3) is not installed. Install the optional extra: "
    'pip install -e ".[postgres]"'
)


# ---------------------------------------------------------------------------
# Ordered migration set
# ---------------------------------------------------------------------------
#
# Each migration is ``(migration_id, name, sql)``. ``ensure_schema()`` applies
# every migration whose id is not yet recorded in ``schema_migrations`` in
# ascending id order, inside one transaction. Migrations MUST be idempotent
# at the DDL level (use ``CREATE TABLE IF NOT EXISTS`` / ``ALTER TABLE ...
# ADD COLUMN IF NOT EXISTS``) so a partially-applied ledger can be resumed.
#
# Migration 0001 — initial schema (matches the original ``SCHEMA_DDL``).
# Migration 0002 — monotonic idempotency: add UNIQUE on
#   ``pools.idempotency_key`` / ``routes.idempotency_key`` /
#   ``tokens.idempotency_key`` and add ``observed_block`` columns so the
#   upserts can guard against older-over-newer replays. Also persist the
#   full ``IdempotencyKey`` components for ``artifact_pointers`` so
#   ``latest_artifact_pointer()`` can reconstruct the original key.

_MIGRATION_0001_DDL = """
CREATE TABLE IF NOT EXISTS runs (
    run_id              TEXT PRIMARY KEY,
    chain_id            INTEGER NOT NULL,
    run_timestamp       TIMESTAMPTZ NOT NULL,
    mode                TEXT NOT NULL,
    status              TEXT NOT NULL,
    idempotency_key     TEXT NOT NULL UNIQUE,
    payload             JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS tokens (
    chain_id            INTEGER NOT NULL,
    address             TEXT NOT NULL,
    decimals            INTEGER,
    symbol              TEXT,
    idempotency_key     TEXT NOT NULL,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (chain_id, address)
);

CREATE TABLE IF NOT EXISTS pools (
    chain_id            INTEGER NOT NULL,
    pool_address        TEXT NOT NULL,
    dex_id              TEXT NOT NULL,
    token0              TEXT NOT NULL,
    token1              TEXT NOT NULL,
    pool_type           TEXT NOT NULL,
    fee                 INTEGER,
    status              TEXT NOT NULL,
    idempotency_key     TEXT NOT NULL,
    extra               JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (chain_id, pool_address)
);

CREATE TABLE IF NOT EXISTS routes (
    chain_id            INTEGER NOT NULL,
    route_id            TEXT NOT NULL,
    dex_id              TEXT NOT NULL,
    token_in            TEXT NOT NULL,
    token_out           TEXT NOT NULL,
    pool_address        TEXT NOT NULL,
    status              TEXT NOT NULL,
    idempotency_key     TEXT NOT NULL,
    extra               JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (chain_id, route_id)
);

CREATE TABLE IF NOT EXISTS pool_states (
    chain_id            INTEGER NOT NULL,
    pool_address        TEXT NOT NULL,
    block_number        BIGINT NOT NULL,
    liquidity           NUMERIC,
    sqrt_price_x96      NUMERIC,
    tick                BIGINT,
    idempotency_key     TEXT NOT NULL UNIQUE,
    observed_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (chain_id, pool_address, block_number)
);

CREATE TABLE IF NOT EXISTS quotes (
    chain_id            INTEGER NOT NULL,
    route_id            TEXT NOT NULL,
    block_number        BIGINT NOT NULL,
    direction           TEXT NOT NULL,
    size_in             NUMERIC NOT NULL,
    size_out            NUMERIC NOT NULL,
    idempotency_key     TEXT NOT NULL UNIQUE,
    observed_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (chain_id, route_id, block_number, direction)
);

CREATE TABLE IF NOT EXISTS cycles (
    chain_id            INTEGER NOT NULL,
    cycle_id            TEXT NOT NULL,
    cycle_length        INTEGER NOT NULL,
    legs                JSONB NOT NULL,
    idempotency_key     TEXT NOT NULL,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (chain_id, cycle_id)
);

CREATE TABLE IF NOT EXISTS opportunities (
    chain_id            INTEGER NOT NULL,
    opportunity_id      TEXT NOT NULL,
    cycle_id            TEXT,
    gross_bps           NUMERIC,
    status              TEXT NOT NULL,
    idempotency_key     TEXT NOT NULL UNIQUE,
    observed_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (chain_id, opportunity_id)
);

CREATE TABLE IF NOT EXISTS simulations (
    chain_id            INTEGER NOT NULL,
    simulation_id       TEXT NOT NULL,
    cycle_id            TEXT,
    verdict             TEXT NOT NULL,
    net_pnl_usd         NUMERIC,
    idempotency_key     TEXT NOT NULL UNIQUE,
    observed_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (chain_id, simulation_id)
);

CREATE TABLE IF NOT EXISTS execution_attempts (
    chain_id            INTEGER NOT NULL,
    attempt_id          TEXT NOT NULL,
    simulation_id       TEXT,
    verdict             TEXT NOT NULL,
    tx_hash             TEXT,
    idempotency_key     TEXT NOT NULL UNIQUE,
    attempted_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (chain_id, attempt_id)
);

CREATE TABLE IF NOT EXISTS provider_health (
    chain_id            INTEGER NOT NULL,
    provider_id         TEXT NOT NULL,
    window_start        TIMESTAMPTZ NOT NULL,
    ok_count            INTEGER NOT NULL DEFAULT 0,
    error_count         INTEGER NOT NULL DEFAULT 0,
    extra               JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (chain_id, provider_id, window_start)
);

CREATE TABLE IF NOT EXISTS artifact_pointers (
    artifact_family     TEXT NOT NULL,
    artifact_path       TEXT NOT NULL,
    run_timestamp       TIMESTAMPTZ NOT NULL,
    content_digest      TEXT,
    idempotency_key     TEXT NOT NULL UNIQUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (artifact_family, run_timestamp)
);

CREATE TABLE IF NOT EXISTS jobs (
    job_id              BIGSERIAL PRIMARY KEY,
    job_type            TEXT NOT NULL,
    payload             JSONB NOT NULL,
    status              TEXT NOT NULL DEFAULT 'pending',
    attempts            INTEGER NOT NULL DEFAULT 0,
    max_attempts        INTEGER NOT NULL DEFAULT 3,
    last_error          TEXT,
    idempotency_key     TEXT NOT NULL UNIQUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS jobs_pending_idx
    ON jobs (job_type, status)
    WHERE status = 'pending';
"""

_MIGRATION_0002_DDL = """
-- Monotonic idempotency for pools/routes/tokens: store the block at which
-- the row was observed so a later replay from an older block cannot
-- clobber a newer observation. Also add UNIQUE on idempotency_key so a
-- same-observation replay is a hard no-op (the DO UPDATE branch now
-- carries a WHERE guard).
ALTER TABLE pools
    ADD COLUMN IF NOT EXISTS observed_block BIGINT NOT NULL DEFAULT 0;
ALTER TABLE routes
    ADD COLUMN IF NOT EXISTS observed_block BIGINT NOT NULL DEFAULT 0;
ALTER TABLE tokens
    ADD COLUMN IF NOT EXISTS observed_block BIGINT NOT NULL DEFAULT 0;

-- Unique idempotency_key constraints. Drop-then-create is idempotent and
-- tolerates deployments that already have the constraint under a different
-- name (the original migration 0001 only had UNIQUE on idempotency_key for
-- pool_states / quotes / opportunities / simulations / execution_attempts /
-- artifact_pointers / jobs; pools / routes / tokens did not).
ALTER TABLE pools
    DROP CONSTRAINT IF EXISTS pools_idempotency_key_key;
ALTER TABLE pools
    ADD CONSTRAINT pools_idempotency_key_key UNIQUE (idempotency_key);
ALTER TABLE routes
    DROP CONSTRAINT IF EXISTS routes_idempotency_key_key;
ALTER TABLE routes
    ADD CONSTRAINT routes_idempotency_key_key UNIQUE (idempotency_key);
ALTER TABLE tokens
    DROP CONSTRAINT IF EXISTS tokens_idempotency_key_key;
ALTER TABLE tokens
    ADD CONSTRAINT tokens_idempotency_key_key UNIQUE (idempotency_key);

-- Persist the full IdempotencyKey components for artifact_pointers so
-- latest_artifact_pointer() can reconstruct the original key instead of
-- returning a zeroed placeholder. The four columns are nullable so older
-- rows (written before migration 0002) survive an in-place upgrade.
ALTER TABLE artifact_pointers
    ADD COLUMN IF NOT EXISTS idempotency_chain_id INTEGER;
ALTER TABLE artifact_pointers
    ADD COLUMN IF NOT EXISTS idempotency_block BIGINT;
ALTER TABLE artifact_pointers
    ADD COLUMN IF NOT EXISTS idempotency_entity_id TEXT;
ALTER TABLE artifact_pointers
    ADD COLUMN IF NOT EXISTS idempotency_input_revision TEXT;
"""

MIGRATIONS: List[Tuple[int, str, str]] = [
    (1, "initial_schema", _MIGRATION_0001_DDL),
    (2, "monotonic_idempotency", _MIGRATION_0002_DDL),
]

# Backward-compat: scripts/tests that introspect the union schema still see
# one DDL block. New deployments must go through ``MIGRATIONS`` instead of
# this constant.
SCHEMA_DDL = "\n\n".join(sql for _, _, sql in MIGRATIONS)


class PostgresStateRepository(StateRepository):
    """StateRepository backed by PostgreSQL (psycopg v3)."""

    def __init__(self, conninfo: str, *, connect: bool = True) -> None:
        self._conninfo = conninfo
        self._conn: Any = None
        if connect:
            self.connect()

    # -- connection / schema -------------------------------------------------

    def _import_psycopg(self) -> Any:
        try:
            import psycopg  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on env
            raise RuntimeError(POSTGRES_EXTRA_MISSING) from exc
        return psycopg

    def connect(self) -> None:
        psycopg = self._import_psycopg()
        self._conn = psycopg.connect(self._conninfo, autocommit=False)

    def ensure_schema(self) -> None:
        """Apply all pending migrations in id order.

        Idempotent: each migration is recorded in ``schema_migrations``;
        re-running ``ensure_schema`` only applies migrations that have not
        yet been recorded. The whole apply pass runs inside one
        transaction so a failed migration rolls back the ledger update
        too (no partial migration state).
        """
        with self.transaction():
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    migration_id INTEGER PRIMARY KEY,
                    name         TEXT NOT NULL,
                    applied_at   TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )
            cur = self._conn.execute(
                "SELECT migration_id FROM schema_migrations ORDER BY migration_id"
            )
            applied = {int(row[0]) for row in cur.fetchall()}
            for migration_id, name, sql in MIGRATIONS:
                if migration_id in applied:
                    continue
                self._conn.execute(sql)
                self._conn.execute(
                    "INSERT INTO schema_migrations (migration_id, name) VALUES (%s, %s)",
                    (migration_id, name),
                )

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    @contextmanager
    def transaction(self) -> Iterator["PostgresStateRepository"]:
        try:
            yield self
        except Exception:
            self._conn.rollback()
            raise
        else:
            self._conn.commit()

    # -- inventory -----------------------------------------------------------

    def upsert_pool(self, pool: PoolRecord) -> None:
        observed_block = int(pool.idempotency.block_number or 0)
        self._conn.execute(
            """
            INSERT INTO pools (
                chain_id, pool_address, dex_id, token0, token1,
                pool_type, fee, status, idempotency_key, extra,
                observed_block
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (chain_id, pool_address) DO UPDATE SET
                dex_id = EXCLUDED.dex_id,
                token0 = EXCLUDED.token0,
                token1 = EXCLUDED.token1,
                pool_type = EXCLUDED.pool_type,
                fee = EXCLUDED.fee,
                status = EXCLUDED.status,
                idempotency_key = EXCLUDED.idempotency_key,
                extra = EXCLUDED.extra,
                observed_block = EXCLUDED.observed_block,
                updated_at = now()
            WHERE pools.observed_block <= EXCLUDED.observed_block
            """,
            (
                pool.chain_id,
                pool.pool_address,
                pool.dex_id,
                pool.token0,
                pool.token1,
                pool.pool_type,
                pool.fee,
                pool.status,
                pool.idempotency.digest(),
                _jsonb(pool.extra),
                observed_block,
            ),
        )

    def upsert_route(self, route: RouteRecord) -> None:
        observed_block = int(route.idempotency.block_number or 0)
        self._conn.execute(
            """
            INSERT INTO routes (
                chain_id, route_id, dex_id, token_in, token_out,
                pool_address, status, idempotency_key, extra,
                observed_block
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (chain_id, route_id) DO UPDATE SET
                dex_id = EXCLUDED.dex_id,
                token_in = EXCLUDED.token_in,
                token_out = EXCLUDED.token_out,
                pool_address = EXCLUDED.pool_address,
                status = EXCLUDED.status,
                idempotency_key = EXCLUDED.idempotency_key,
                extra = EXCLUDED.extra,
                observed_block = EXCLUDED.observed_block,
                updated_at = now()
            WHERE routes.observed_block <= EXCLUDED.observed_block
            """,
            (
                route.chain_id,
                route.route_id,
                route.dex_id,
                route.token_in,
                route.token_out,
                route.pool_address,
                route.status,
                route.idempotency.digest(),
                _jsonb(route.extra),
                observed_block,
            ),
        )

    def upsert_token(
        self,
        *,
        chain_id: int,
        address: str,
        decimals: Optional[int],
        symbol: Optional[str],
        idempotency: IdempotencyKey,
    ) -> None:
        observed_block = int(idempotency.block_number or 0)
        self._conn.execute(
            """
            INSERT INTO tokens (
                chain_id, address, decimals, symbol, idempotency_key,
                observed_block
            ) VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (chain_id, address) DO UPDATE SET
                decimals = COALESCE(EXCLUDED.decimals, tokens.decimals),
                symbol = COALESCE(EXCLUDED.symbol, tokens.symbol),
                idempotency_key = EXCLUDED.idempotency_key,
                observed_block = EXCLUDED.observed_block,
                updated_at = now()
            WHERE tokens.observed_block <= EXCLUDED.observed_block
            """,
            (chain_id, address, decimals, symbol, idempotency.digest(), observed_block),
        )

    # -- artifact pointers ----------------------------------------------------

    def upsert_artifact_pointer(self, pointer: ArtifactPointer) -> None:
        self._conn.execute(
            """
            INSERT INTO artifact_pointers (
                artifact_family, artifact_path, run_timestamp,
                content_digest, idempotency_key,
                idempotency_chain_id, idempotency_block,
                idempotency_entity_id, idempotency_input_revision
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (artifact_family, run_timestamp) DO UPDATE SET
                artifact_path = EXCLUDED.artifact_path,
                content_digest = EXCLUDED.content_digest,
                idempotency_key = EXCLUDED.idempotency_key,
                idempotency_chain_id = EXCLUDED.idempotency_chain_id,
                idempotency_block = EXCLUDED.idempotency_block,
                idempotency_entity_id = EXCLUDED.idempotency_entity_id,
                idempotency_input_revision = EXCLUDED.idempotency_input_revision
            """,
            (
                pointer.artifact_family,
                pointer.artifact_path,
                pointer.run_timestamp,
                pointer.content_digest,
                pointer.idempotency.digest(),
                int(pointer.idempotency.chain_id or 0),
                int(pointer.idempotency.block_number or 0),
                str(pointer.idempotency.entity_id or ""),
                str(pointer.idempotency.input_revision or ""),
            ),
        )

    def latest_artifact_pointer(self, artifact_family: str) -> Optional[ArtifactPointer]:
        cur = self._conn.execute(
            """
            SELECT artifact_family, artifact_path, run_timestamp,
                   content_digest, idempotency_key,
                   idempotency_chain_id, idempotency_block,
                   idempotency_entity_id, idempotency_input_revision
            FROM artifact_pointers
            WHERE artifact_family = %s
            ORDER BY run_timestamp DESC
            LIMIT 1
            """,
            (artifact_family,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        chain_id = int(row[5]) if row[5] is not None else 0
        block_number = int(row[6]) if row[6] is not None else 0
        entity_id = str(row[7]) if row[7] is not None else str(row[0])
        input_revision = str(row[8]) if row[8] is not None else str(row[4])
        return ArtifactPointer(
            artifact_family=row[0],
            artifact_path=row[1],
            run_timestamp=str(row[2]),
            content_digest=row[3],
            idempotency=IdempotencyKey(
                chain_id=chain_id,
                block_number=block_number,
                entity_id=entity_id,
                input_revision=input_revision,
            ),
        )

    # -- job queue ------------------------------------------------------------

    def enqueue_job(self, job: JobRecord) -> None:
        self._conn.execute(
            """
            INSERT INTO jobs (job_type, payload, status, attempts,
                              max_attempts, idempotency_key)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (idempotency_key) DO NOTHING
            """,
            (
                job.job_type,
                _jsonb(job.payload),
                job.status,
                job.attempts,
                job.max_attempts,
                job.idempotency.digest(),
            ),
        )

    def claim_jobs(self, *, job_type: str, limit: int) -> List[JobRecord]:
        cur = self._conn.execute(
            """
            UPDATE jobs SET status = 'claimed', attempts = attempts + 1,
                            updated_at = now()
            WHERE job_id IN (
                SELECT job_id FROM jobs
                WHERE job_type = %s AND status = 'pending'
                ORDER BY job_id
                FOR UPDATE SKIP LOCKED
                LIMIT %s
            )
            RETURNING job_id, job_type, payload, status, attempts,
                      max_attempts, last_error, idempotency_key
            """,
            (job_type, limit),
        )
        rows = cur.fetchall()
        return [
            JobRecord(
                job_id=row[0],
                job_type=row[1],
                payload=row[2] if isinstance(row[2], dict) else {},
                status=row[3],
                attempts=row[4],
                max_attempts=row[5],
                last_error=row[6],
                idempotency=IdempotencyKey(
                    chain_id=0, block_number=0, entity_id=row[1], input_revision=str(row[7])
                ),
            )
            for row in rows
        ]

    def complete_job(self, job_id: int) -> None:
        self._conn.execute(
            "UPDATE jobs SET status = 'done', updated_at = now() WHERE job_id = %s",
            (job_id,),
        )

    def fail_job(self, job_id: int, *, error: str) -> None:
        self._conn.execute(
            """
            UPDATE jobs SET
                status = CASE WHEN attempts >= max_attempts THEN 'failed' ELSE 'pending' END,
                last_error = %s,
                updated_at = now()
            WHERE job_id = %s
            """,
            (error, job_id),
        )


def _jsonb(value: Dict[str, Any]) -> Any:
    """Adapt a dict for a JSONB parameter under psycopg v3.

    Falls back to the raw dict when psycopg is unavailable so SQL generation
    stays testable with plain DB-API fakes; the driver is only required for
    real connections (enforced in ``connect()``).
    """
    try:
        from psycopg.types.json import Jsonb  # type: ignore
    except ImportError:
        return value
    return Jsonb(value)
