"""Event-driven continuous pipeline — independent workers over StateRepository."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

from core.pipeline_runtime_config import PipelineRuntimeConfig
from core.timeout_policy import TimeoutPolicy
from state.repository import IdempotencyKey, JobRecord, StateRepository

# Immutable event chain (worker handoff contract).
EVENT_POOL_DISCOVERED = "pool_discovered"
EVENT_METADATA_READY = "metadata_ready"
EVENT_MIRROR_READY = "mirror_ready"
EVENT_QUOTE_READY = "quote_ready"
EVENT_M9_QUOTED = "m9_quoted"

WORKER_M8_INGEST = "m8_ingest"
WORKER_M81_PROBE = "m81_probe"
WORKER_M82_MIRROR = "m82_mirror"
WORKER_M83_METADATA = "m83_metadata"
WORKER_M9_GRAPH_QUOTE = "m9_graph_quote"

WORKER_FOR_EVENT: Dict[str, str] = {
    EVENT_POOL_DISCOVERED: WORKER_M8_INGEST,
    EVENT_METADATA_READY: WORKER_M83_METADATA,
    EVENT_MIRROR_READY: WORKER_M82_MIRROR,
    EVENT_QUOTE_READY: WORKER_M81_PROBE,
}

NEXT_EVENT: Dict[str, str] = {
    EVENT_POOL_DISCOVERED: EVENT_METADATA_READY,
    EVENT_METADATA_READY: EVENT_MIRROR_READY,
    EVENT_MIRROR_READY: EVENT_QUOTE_READY,
    EVENT_QUOTE_READY: EVENT_M9_QUOTED,
}


class ContinuousPipelineMode(str, Enum):
    CONTINUOUS = "continuous"
    BATCHED_STREAMING = "batched_streaming"


@dataclass
class PipelineEvent:
    event_type: str
    session_id: str
    payload: Dict[str, Any]
    observed_block: int = 0
    entity_id: str = ""

    def idempotency(self) -> IdempotencyKey:
        eid = self.entity_id or str(self.payload.get("pool_address") or self.payload.get("event_id") or "")
        return IdempotencyKey(
            chain_id=int(self.payload.get("chain_id") or 8453),
            block_number=int(self.observed_block or 0),
            entity_id=eid,
            input_revision=f"{self.event_type}:{self.session_id}",
        )


@dataclass
class WorkerResult:
    worker: str
    ok: bool
    next_event: Optional[str] = None
    error: Optional[str] = None
    latency_s: float = 0.0


@dataclass
class ContinuousOrchestrator:
    """Drains worker jobs; M9 triggers on ``quote_ready`` without waiting for M8 completion."""

    repository: StateRepository
    config: PipelineRuntimeConfig
    policy: TimeoutPolicy
    session_id: str
    _handlers: Dict[str, Callable[[Dict[str, Any]], WorkerResult]] = field(
        default_factory=dict
    )
    _m9_pending: Set[str] = field(default_factory=set)
    _event_latencies: List[float] = field(default_factory=list)

    def register_handler(
        self,
        worker: str,
        handler: Callable[[Dict[str, Any]], WorkerResult],
    ) -> None:
        self._handlers[worker] = handler

    def emit(self, event: PipelineEvent) -> None:
        worker = WORKER_FOR_EVENT.get(event.event_type)
        if worker and self.config.workers.get(worker, {}).get("enabled", True):
            self.repository.enqueue_job(
                JobRecord(
                    job_type=worker,
                    payload={
                        "event_type": event.event_type,
                        "session_id": event.session_id,
                        **event.payload,
                    },
                    idempotency=event.idempotency(),
                    max_attempts=self.policy.retry_budget,
                )
            )
        if (
            event.event_type == EVENT_QUOTE_READY
            and self.config.m9_trigger_event == EVENT_QUOTE_READY
            and self.config.workers.get(WORKER_M9_GRAPH_QUOTE, {}).get("enabled", True)
        ):
            entity = event.entity_id or str(event.payload.get("pool_address") or "")
            if entity and entity not in self._m9_pending:
                self._m9_pending.add(entity)
                self.repository.enqueue_job(
                    JobRecord(
                        job_type=WORKER_M9_GRAPH_QUOTE,
                        payload={
                            "event_type": EVENT_QUOTE_READY,
                            "session_id": event.session_id,
                            **event.payload,
                        },
                        idempotency=IdempotencyKey(
                            chain_id=int(event.payload.get("chain_id") or 8453),
                            block_number=int(event.observed_block or 0),
                            entity_id=entity,
                            input_revision=f"m9_quote:{event.session_id}",
                        ),
                        max_attempts=self.policy.retry_budget,
                    )
                )

    def process_worker_jobs(
        self,
        worker: str,
        *,
        limit: int = 1,
    ) -> List[WorkerResult]:
        results: List[WorkerResult] = []
        jobs = self.repository.claim_jobs(job_type=worker, limit=limit)
        handler = self._handlers.get(worker)
        for job in jobs:
            started = time.monotonic()
            try:
                if handler is None:
                    result = self._default_handler(worker, job.payload)
                else:
                    result = handler(job.payload)
                latency = time.monotonic() - started
                result.latency_s = latency
                if result.ok:
                    self.repository.complete_job(int(job.job_id or 0))
                    if result.next_event:
                        self.emit(
                            PipelineEvent(
                                event_type=result.next_event,
                                session_id=str(job.payload.get("session_id") or self.session_id),
                                payload=dict(job.payload),
                                observed_block=int(job.payload.get("block_number") or 0),
                                entity_id=str(job.payload.get("pool_address") or ""),
                            )
                        )
                else:
                    self.repository.fail_job(
                        int(job.job_id or 0),
                        error=str(result.error or "worker_failed"),
                    )
                results.append(result)
            except Exception as exc:
                self.repository.fail_job(int(job.job_id or 0), error=str(exc)[:200])
                results.append(
                    WorkerResult(worker=worker, ok=False, error=str(exc)[:200])
                )
        return results

    def _default_handler(self, worker: str, payload: Dict[str, Any]) -> WorkerResult:
        if worker == WORKER_M9_GRAPH_QUOTE:
            return WorkerResult(
                worker=worker,
                ok=True,
                next_event=EVENT_M9_QUOTED,
            )
        event_type = str(payload.get("event_type") or EVENT_POOL_DISCOVERED)
        nxt = NEXT_EVENT.get(event_type)
        return WorkerResult(worker=worker, ok=True, next_event=nxt)

    def simulate_pool_to_m9(
        self,
        pool_address: str,
        *,
        chain_id: int = 8453,
        block_number: int = 1,
    ) -> float:
        """Emit full chain; return seconds until M9 job is enqueued (not M8 idle)."""
        started = time.monotonic()
        event = PipelineEvent(
            event_type=EVENT_POOL_DISCOVERED,
            session_id=self.session_id,
            payload={"pool_address": pool_address, "chain_id": chain_id},
            observed_block=block_number,
            entity_id=pool_address,
        )
        self.emit(event)
        # Fast-forward through metadata + mirror + quote without waiting for ingest idle.
        for evt in (EVENT_METADATA_READY, EVENT_MIRROR_READY, EVENT_QUOTE_READY):
            self.emit(
                PipelineEvent(
                    event_type=evt,
                    session_id=self.session_id,
                    payload={"pool_address": pool_address, "chain_id": chain_id},
                    observed_block=block_number,
                    entity_id=pool_address,
                )
            )
        return time.monotonic() - started

    def m9_jobs_enqueued(self) -> int:
        jobs_fn = getattr(self.repository, "_jobs", None)
        if not isinstance(jobs_fn, list):
            claim = self.repository.claim_jobs(job_type=WORKER_M9_GRAPH_QUOTE, limit=1000)
            count = len(claim)
            for job in claim:
                self.repository.fail_job(int(job.job_id or 0), error="test_requeue")
            return count
        return sum(
            1
            for j in jobs_fn
            if j.get("job_type") == WORKER_M9_GRAPH_QUOTE
        )


def build_continuous_worker_names(config: PipelineRuntimeConfig) -> List[str]:
    order = [
        WORKER_M8_INGEST,
        WORKER_M81_PROBE,
        WORKER_M82_MIRROR,
        WORKER_M83_METADATA,
        WORKER_M9_GRAPH_QUOTE,
    ]
    return [w for w in order if config.workers.get(w, {}).get("enabled", True)]


def build_continuous_pipeline_steps(
    *,
    session_id: str,
    config: PipelineRuntimeConfig,
) -> List[Dict[str, Any]]:
    """Internal continuous steps — no global service timeouts."""
    steps: List[Dict[str, Any]] = []
    for worker in build_continuous_worker_names(config):
        steps.append(
            {
                "name": f"continuous_{worker}",
                "internal": "continuous_worker",
                "worker": worker,
                "session_id": session_id,
                "timeout_seconds": None,
            }
        )
    steps.append(
        {
            "name": "m8_2_acceptance_aggregate",
            "internal": "session_aggregate_acceptance",
            "session_id": session_id,
            "timeout_seconds": None,
        }
    )
    steps.append(
        {
            "name": "m9_bridge_from_aggregate",
            "internal": "session_aggregate_bridge",
            "session_id": session_id,
            "timeout_seconds": None,
        }
    )
    if config.shadow.duration_minutes > 0:
        steps.append(
            {
                "name": "m9_shadow",
                "internal": "continuous_m9_shadow",
                "session_id": session_id,
                "duration_minutes": config.shadow.duration_minutes,
                "timeout_seconds": None,
            }
        )
    return steps
