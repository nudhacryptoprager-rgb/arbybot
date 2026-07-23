"""JSON export helpers — operators' read interface over repository state.

The repository (``state.repository.StateRepository``) is the system of
record; JSON artifacts under ``data/**`` are *exports* rendered from
repository rows for operators and for the downstream tools that already
consume the canonical rolling artifacts.  Exports are written atomically
via ``core.json_io.atomic_write_json`` using the money-safe
``decimal_mode="str"`` serializer (Roadmap В§3.2: no float money).

No float money: numeric amounts are exported as integer strings (wei) or
Decimal-as-string.  ``Decimal`` amounts stored in ``PoolRecord.extra``,
``RouteRecord.extra``, or ``JobRecord.payload`` are serialized as exact
fixed-point strings so a re-import / re-projection cannot silently turn
a precise ``Decimal("0.000000000000000001")`` into ``0.0``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Union

from core.json_io import atomic_write_json
from state.repository import ArtifactPointer, JobRecord, PoolRecord, RouteRecord

__all__ = [
    "pool_record_to_json",
    "route_record_to_json",
    "artifact_pointer_to_json",
    "job_record_to_json",
    "export_rows_to_json",
]


def pool_record_to_json(pool: PoolRecord) -> Dict[str, Any]:
    return {
        "chain_id": pool.chain_id,
        "dex_id": pool.dex_id,
        "pool_address": pool.pool_address,
        "token0": pool.token0,
        "token1": pool.token1,
        "pool_type": pool.pool_type,
        "fee": pool.fee,
        "status": pool.status,
        "idempotency_key": pool.idempotency.digest(),
        "extra": dict(pool.extra),
    }


def route_record_to_json(route: RouteRecord) -> Dict[str, Any]:
    return {
        "chain_id": route.chain_id,
        "route_id": route.route_id,
        "dex_id": route.dex_id,
        "token_in": route.token_in,
        "token_out": route.token_out,
        "pool_address": route.pool_address,
        "status": route.status,
        "idempotency_key": route.idempotency.digest(),
        "extra": dict(route.extra),
    }


def artifact_pointer_to_json(pointer: ArtifactPointer) -> Dict[str, Any]:
    return {
        "artifact_family": pointer.artifact_family,
        "artifact_path": pointer.artifact_path,
        "run_timestamp": pointer.run_timestamp,
        "content_digest": pointer.content_digest,
        "idempotency_key": pointer.idempotency.digest(),
    }


def job_record_to_json(job: JobRecord) -> Dict[str, Any]:
    return {
        "job_id": job.job_id,
        "job_type": job.job_type,
        "payload": dict(job.payload),
        "status": job.status,
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
        "last_error": job.last_error,
        "idempotency_key": job.idempotency.digest(),
    }


def export_rows_to_json(
    rows: Iterable[Dict[str, Any]],
    path: Union[str, Path],
    *,
    envelope: str = "items",
) -> Path:
    """Render repository rows to a canonical operator-facing JSON export.

    Money-safe: ``Decimal`` values inside any row's ``extra``/``payload``
    are serialized via ``decimal_mode="str"`` so a subsequent re-import
    cannot silently lose precision (Roadmap В§3.2: no float money).
    """
    items: List[Dict[str, Any]] = [dict(r) for r in rows]
    return atomic_write_json(
        Path(path),
        {envelope: items},
        decimal_mode="str",
    )
