"""StateRepository contract — idempotent, transactional persistence.

Design rules (from the production-readiness review):

* Writes are idempotent: every entity carries an ``IdempotencyKey`` of
  ``chain_id + block_number + entity_id + input_revision``.  Re-applying
  the same observation is a no-op upsert, never a duplicate row.
* Writes are transactional: a stage either commits its whole bundle or
  rolls back; half-valid state must not be visible to readers.
* JSON artifacts stay the operator export interface only; they are rendered
  from repository rows (see ``state.json_export``), never the system of
  record.
* Job queue semantics use ``FOR UPDATE SKIP LOCKED`` so multiple workers
  can drain the queue without a broker.

All amounts are integer strings (wei) or Decimal-as-string; no float money.
"""
from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional

# ---------------------------------------------------------------------------
# Idempotency
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IdempotencyKey:
    """Canonical idempotency key for one observed entity.

    ``entity_id`` is the natural id of the row: pool address, route id,
    cycle id, run id, etc. ``input_revision`` pins the exact input bundle
    (e.g. bridge/generated_at_utc or scan input hash) that produced the row.
    """

    chain_id: int
    block_number: int
    entity_id: str
    input_revision: str

    def digest(self) -> str:
        """Deterministic digest string used as the DB idempotency key."""
        raw = f"{self.chain_id}:{self.block_number}:{self.entity_id}:{self.input_revision}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ArtifactPointer:
    """Pointer from a run to the JSON artifact it exported."""

    artifact_family: str  # e.g. "new_pool_sniper", "m9_bridge_inventory"
    artifact_path: str
    run_timestamp: str
    idempotency: IdempotencyKey
    content_digest: Optional[str] = None


@dataclass(frozen=True)
class JobRecord:
    """One unit of work for the SKIP LOCKED job queue."""

    job_type: str  # e.g. "ingest_verify", "graph_quote", "risk_simulate"
    payload: Dict[str, Any]
    idempotency: IdempotencyKey
    status: str = "pending"  # pending | claimed | done | failed | dead_letter
    attempts: int = 0
    max_attempts: int = 3
    last_error: Optional[str] = None
    job_id: Optional[int] = None
    available_at: Optional[float] = None
    lease_expires_at: Optional[float] = None


@dataclass(frozen=True)
class PipelineEventRecord:
    """Immutable event ledger row for continuous pipeline handoff."""

    event_type: str
    session_id: str
    entity_id: str
    payload: Dict[str, Any]
    observed_block: int = 0
    event_offset: int = 0
    created_at_utc: Optional[str] = None


@dataclass(frozen=True)
class PoolRecord:
    chain_id: int
    dex_id: str
    pool_address: str
    token0: str
    token1: str
    pool_type: str
    fee: Optional[int]
    status: str
    idempotency: IdempotencyKey
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RouteRecord:
    chain_id: int
    route_id: str
    dex_id: str
    token_in: str
    token_out: str
    pool_address: str
    status: str
    idempotency: IdempotencyKey
    extra: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Repository contract
# ---------------------------------------------------------------------------


class StateRepository(ABC):
    """Transactional, idempotent persistence contract."""

    @contextmanager
    def transaction(self) -> Iterator["StateRepository"]:
        """Run a block of writes in one transaction (commit/rollback)."""
        raise NotImplementedError

    # -- inventory ---------------------------------------------------------
    @abstractmethod
    def upsert_pool(self, pool: PoolRecord) -> None: ...

    @abstractmethod
    def upsert_route(self, route: RouteRecord) -> None: ...

    @abstractmethod
    def upsert_token(
        self,
        *,
        chain_id: int,
        address: str,
        decimals: Optional[int],
        symbol: Optional[str],
        idempotency: IdempotencyKey,
    ) -> None: ...

    # -- artifact pointers --------------------------------------------------
    @abstractmethod
    def upsert_artifact_pointer(self, pointer: ArtifactPointer) -> None: ...

    @abstractmethod
    def latest_artifact_pointer(self, artifact_family: str) -> Optional[ArtifactPointer]: ...

    # -- job queue ----------------------------------------------------------
    @abstractmethod
    def enqueue_job(self, job: JobRecord) -> None:
        """Idempotent enqueue: same idempotency digest is a no-op."""

    @abstractmethod
    def claim_jobs(
        self,
        *,
        job_type: str,
        limit: int,
        lease_s: float = 300.0,
    ) -> List[JobRecord]:
        """Claim pending jobs with FOR UPDATE SKIP LOCKED semantics."""

    @abstractmethod
    def complete_job(self, job_id: int) -> None: ...

    @abstractmethod
    def fail_job(self, job_id: int, *, error: str) -> None: ...

    # -- continuous pipeline (event ledger + lease reclaim) -----------------
    def append_event(
        self,
        *,
        event_type: str,
        session_id: str,
        entity_id: str,
        payload: Dict[str, Any],
        observed_block: int = 0,
    ) -> PipelineEventRecord:
        raise NotImplementedError

    def list_events(
        self,
        *,
        session_id: Optional[str] = None,
        since_offset: int = 0,
    ) -> List[PipelineEventRecord]:
        raise NotImplementedError

    def reclaim_expired_leases(self, *, lease_s: float) -> int:
        raise NotImplementedError

    # -- inventory reads (continuous aggregate projection) ----------------
    def list_pools(self) -> List[Dict[str, Any]]:
        fn = getattr(self, "pools", None)
        return list(fn()) if callable(fn) else []

    def list_routes(self) -> List[Dict[str, Any]]:
        fn = getattr(self, "routes", None)
        return list(fn()) if callable(fn) else []

    def list_tokens(self) -> List[Dict[str, Any]]:
        fn = getattr(self, "tokens", None)
        return list(fn()) if callable(fn) else []

    # -- ingest cursor (atomic, per session) ------------------------------
    def get_ingest_cursor(self, session_id: str) -> Dict[str, Any]:
        raise NotImplementedError

    def set_ingest_cursor(self, session_id: str, cursor: Dict[str, Any]) -> None:
        raise NotImplementedError
