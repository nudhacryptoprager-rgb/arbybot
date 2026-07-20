"""PostgreSQL adapter for the StateRepository contract.

Production adapter.  The driver (``psycopg`` v3) is an optional dependency:
install with ``pip install -e ".[postgres]"``.  Offline CI never imports the
driver — the import happens lazily inside ``connect()``.

Guarantees:

* ``ensure_schema()`` creates the minimal production tables (runs, tokens,
  pools, routes, pool_states, quotes, cycles, opportunities, simulations,
  execution_attempts, provider_health, artifact_pointers, jobs).
* Every write is an idempotent upsert keyed by the ``IdempotencyKey``
  digest; replays never create duplicates.
* ``transaction()`` gives commit/rollback semantics; a failed stage leaves
  no partial state.
* ``claim_jobs`` uses ``FOR UPDATE SKIP LOCKED`` so multiple workers can
  drain the queue without a broker.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

from state.repository import (
    ArtifactPointer,
    IdempotencyKey,
    JobRecord,
    PoolRecord,
    RouteRecord,
    StateRepository,
)

__all__ = ["PostgresStateRepository", "SCHEMA_DDL", "POSTGRES_EXTRA_MISSING"]


POSTGRES_EXTRA_MISSING = (
    "psycopg (v3) is not installed. Install the optional extra: "
    'pip install -e ".[postgres]"'
)


SCHEMA_DDL = """
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
        with self.transaction():
            self._conn.execute(SCHEMA_DDL)

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
        self._conn.execute(
            """
            INSERT INTO pools (
                chain_id, pool_address, dex_id, token0, token1,
                pool_type, fee, status, idempotency_key, extra
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (chain_id, pool_address) DO UPDATE SET
                dex_id = EXCLUDED.dex_id,
                token0 = EXCLUDED.token0,
                token1 = EXCLUDED.token1,
                pool_type = EXCLUDED.pool_type,
                fee = EXCLUDED.fee,
                status = EXCLUDED.status,
                idempotency_key = EXCLUDED.idempotency_key,
                extra = EXCLUDED.extra,
                updated_at = now()
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
            ),
        )

    def upsert_route(self, route: RouteRecord) -> None:
        self._conn.execute(
            """
            INSERT INTO routes (
                chain_id, route_id, dex_id, token_in, token_out,
                pool_address, status, idempotency_key, extra
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (chain_id, route_id) DO UPDATE SET
                dex_id = EXCLUDED.dex_id,
                token_in = EXCLUDED.token_in,
                token_out = EXCLUDED.token_out,
                pool_address = EXCLUDED.pool_address,
                status = EXCLUDED.status,
                idempotency_key = EXCLUDED.idempotency_key,
                extra = EXCLUDED.extra,
                updated_at = now()
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
        self._conn.execute(
            """
            INSERT INTO tokens (chain_id, address, decimals, symbol, idempotency_key)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (chain_id, address) DO UPDATE SET
                decimals = COALESCE(EXCLUDED.decimals, tokens.decimals),
                symbol = COALESCE(EXCLUDED.symbol, tokens.symbol),
                idempotency_key = EXCLUDED.idempotency_key,
                updated_at = now()
            """,
            (chain_id, address, decimals, symbol, idempotency.digest()),
        )

    # -- artifact pointers ----------------------------------------------------

    def upsert_artifact_pointer(self, pointer: ArtifactPointer) -> None:
        self._conn.execute(
            """
            INSERT INTO artifact_pointers (
                artifact_family, artifact_path, run_timestamp,
                content_digest, idempotency_key
            ) VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (artifact_family, run_timestamp) DO UPDATE SET
                artifact_path = EXCLUDED.artifact_path,
                content_digest = EXCLUDED.content_digest,
                idempotency_key = EXCLUDED.idempotency_key
            """,
            (
                pointer.artifact_family,
                pointer.artifact_path,
                pointer.run_timestamp,
                pointer.content_digest,
                pointer.idempotency.digest(),
            ),
        )

    def latest_artifact_pointer(self, artifact_family: str) -> Optional[ArtifactPointer]:
        cur = self._conn.execute(
            """
            SELECT artifact_family, artifact_path, run_timestamp,
                   content_digest, idempotency_key
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
        return ArtifactPointer(
            artifact_family=row[0],
            artifact_path=row[1],
            run_timestamp=str(row[2]),
            content_digest=row[3],
            idempotency=IdempotencyKey(
                chain_id=0, block_number=0, entity_id=row[0], input_revision=str(row[4])
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
