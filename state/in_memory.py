"""In-memory ``StateRepository`` for dev / CI / local runs.

Implements the same monotonic + idempotency + transactional contract as
``PostgresStateRepository`` so a vertical migration (Step 4) can run end-to-end
without a real PostgreSQL instance and produce the same observable behavior.

Design notes:
* Writes are idempotent by ``IdempotencyKey.digest()``; same-observation
  replays are no-ops.
* ``upsert_pool`` / ``upsert_route`` / ``upsert_token`` only overwrite the
  stored row when the incoming ``observed_block`` is greater than or equal
  to the stored one — mirrors the ``WHERE ... observed_block <=
  EXCLUDED.observed_block`` clause in PostgresStateRepository.
* ``transaction()`` keeps a working copy of the row maps; on exception the
  working copy is discarded (rollback); on success the working copy
  replaces the committed one.
* ``latest_artifact_pointer()`` reconstructs the original ``IdempotencyKey``
  from the persisted components (mirrors migration 0002's
  ``idempotency_chain_id`` / ``idempotency_block`` / ... columns).
"""
from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
from typing import Any, Dict, Iterator, List, Optional

from state.repository import (
    ArtifactPointer,
    IdempotencyKey,
    JobRecord,
    PoolRecord,
    RouteRecord,
    StateRepository,
)

__all__ = ["InMemoryStateRepository"]


class InMemoryStateRepository(StateRepository):
    """Process-local StateRepository — same contract as the Postgres adapter."""

    def __init__(self) -> None:
        self._pools: Dict[tuple, Dict[str, Any]] = {}
        self._routes: Dict[tuple, Dict[str, Any]] = {}
        self._tokens: Dict[tuple, Dict[str, Any]] = {}
        self._artifact_pointers: Dict[tuple, Dict[str, Any]] = {}
        self._jobs: List[Dict[str, Any]] = []
        self._job_id_seq = 0

    @contextmanager
    def transaction(self) -> Iterator["InMemoryStateRepository"]:
        # Snapshot before; commit by replacing; rollback by discarding.
        snap_pools = deepcopy(self._pools)
        snap_routes = deepcopy(self._routes)
        snap_tokens = deepcopy(self._tokens)
        snap_pointers = deepcopy(self._artifact_pointers)
        snap_jobs = deepcopy(self._jobs)
        try:
            yield self
        except Exception:
            self._pools = snap_pools
            self._routes = snap_routes
            self._tokens = snap_tokens
            self._artifact_pointers = snap_pointers
            self._jobs = snap_jobs
            raise
        # commit: nothing to do — we mutated live maps directly. Snapshot is
        # discarded and the live maps stay.

    # -- inventory -----------------------------------------------------------

    def upsert_pool(self, pool: PoolRecord) -> None:
        key = (pool.chain_id, pool.pool_address.lower())
        existing = self._pools.get(key)
        new_block = int(pool.idempotency.block_number or 0)
        if existing is not None and int(existing["observed_block"]) > new_block:
            return  # monotonic guard: older replay does not clobber newer row
        self._pools[key] = {
            "chain_id": pool.chain_id,
            "pool_address": pool.pool_address,
            "dex_id": pool.dex_id,
            "token0": pool.token0,
            "token1": pool.token1,
            "pool_type": pool.pool_type,
            "fee": pool.fee,
            "status": pool.status,
            "idempotency_key": pool.idempotency.digest(),
            "idempotency": pool.idempotency,
            "extra": dict(pool.extra),
            "observed_block": new_block,
        }

    def upsert_route(self, route: RouteRecord) -> None:
        key = (route.chain_id, route.route_id)
        existing = self._routes.get(key)
        new_block = int(route.idempotency.block_number or 0)
        if existing is not None and int(existing["observed_block"]) > new_block:
            return
        self._routes[key] = {
            "chain_id": route.chain_id,
            "route_id": route.route_id,
            "dex_id": route.dex_id,
            "token_in": route.token_in,
            "token_out": route.token_out,
            "pool_address": route.pool_address,
            "status": route.status,
            "idempotency_key": route.idempotency.digest(),
            "idempotency": route.idempotency,
            "extra": dict(route.extra),
            "observed_block": new_block,
        }

    def upsert_token(
        self,
        *,
        chain_id: int,
        address: str,
        decimals: Optional[int],
        symbol: Optional[str],
        idempotency: IdempotencyKey,
    ) -> None:
        key = (chain_id, address.lower())
        existing = self._tokens.get(key)
        new_block = int(idempotency.block_number or 0)
        if existing is not None and int(existing["observed_block"]) > new_block:
            return
        prev_decimals = existing["decimals"] if existing else None
        prev_symbol = existing["symbol"] if existing else None
        self._tokens[key] = {
            "chain_id": chain_id,
            "address": address,
            "decimals": decimals if decimals is not None else prev_decimals,
            "symbol": symbol if symbol is not None else prev_symbol,
            "idempotency_key": idempotency.digest(),
            "idempotency": idempotency,
            "observed_block": new_block,
        }

    # -- artifact pointers ----------------------------------------------------

    def upsert_artifact_pointer(self, pointer: ArtifactPointer) -> None:
        key = (pointer.artifact_family, pointer.run_timestamp)
        self._artifact_pointers[key] = {
            "artifact_family": pointer.artifact_family,
            "artifact_path": pointer.artifact_path,
            "run_timestamp": pointer.run_timestamp,
            "content_digest": pointer.content_digest,
            "idempotency_key": pointer.idempotency.digest(),
            "idempotency": pointer.idempotency,
        }

    def latest_artifact_pointer(self, artifact_family: str) -> Optional[ArtifactPointer]:
        candidates = [
            row
            for row in self._artifact_pointers.values()
            if row["artifact_family"] == artifact_family
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda r: r["run_timestamp"], reverse=True)
        row = candidates[0]
        return ArtifactPointer(
            artifact_family=row["artifact_family"],
            artifact_path=row["artifact_path"],
            run_timestamp=row["run_timestamp"],
            content_digest=row["content_digest"],
            idempotency=row["idempotency"],
        )

    # -- job queue ------------------------------------------------------------

    def enqueue_job(self, job: JobRecord) -> None:
        digest = job.idempotency.digest()
        for j in self._jobs:
            if j["idempotency_key"] == digest:
                return  # idempotent enqueue
        self._job_id_seq += 1
        self._jobs.append(
            {
                "job_id": self._job_id_seq,
                "job_type": job.job_type,
                "payload": dict(job.payload),
                "status": job.status,
                "attempts": job.attempts,
                "max_attempts": job.max_attempts,
                "last_error": job.last_error,
                "idempotency_key": digest,
                "idempotency": job.idempotency,
            }
        )

    def claim_jobs(self, *, job_type: str, limit: int) -> List[JobRecord]:
        claimed: List[JobRecord] = []
        for j in self._jobs:
            if len(claimed) >= limit:
                break
            if j["job_type"] == job_type and j["status"] == "pending":
                j["status"] = "claimed"
                j["attempts"] += 1
                claimed.append(
                    JobRecord(
                        job_id=j["job_id"],
                        job_type=j["job_type"],
                        payload=j["payload"],
                        status=j["status"],
                        attempts=j["attempts"],
                        max_attempts=j["max_attempts"],
                        last_error=j["last_error"],
                        idempotency=j["idempotency"],
                    )
                )
        return claimed

    def complete_job(self, job_id: int) -> None:
        for j in self._jobs:
            if j["job_id"] == job_id:
                j["status"] = "done"
                return

    def fail_job(self, job_id: int, *, error: str) -> None:
        for j in self._jobs:
            if j["job_id"] == job_id:
                j["last_error"] = error
                if j["attempts"] >= j["max_attempts"]:
                    j["status"] = "failed"
                else:
                    j["status"] = "pending"
                return

    # -- read helpers (used by JSON projections / API vertical slice) --------

    def pools(self) -> List[Dict[str, Any]]:
        return [dict(r) for r in self._pools.values()]

    def routes(self) -> List[Dict[str, Any]]:
        return [dict(r) for r in self._routes.values()]

    def tokens(self) -> List[Dict[str, Any]]:
        return [dict(r) for r in self._tokens.values()]