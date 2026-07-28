"""Event-driven continuous pipeline — shared StateRepository + worker broker."""
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
EVENT_M9_QUOTE_RESULT = "m9_quote_result"
EVENT_M9_QUOTED = "m9_quoted"  # legacy alias — do not emit in production adapters

WORKER_M8_INGEST = "m8_ingest"
WORKER_M81_PROBE = "m81_probe"
WORKER_M82_MIRROR = "m82_mirror"
WORKER_M83_METADATA = "m83_metadata"
WORKER_M9_GRAPH_QUOTE = "m9_graph_quote"

# pool_discovered → m81 → m82 → m83 → quote_ready → m9
WORKER_FOR_EVENT: Dict[str, str] = {
    EVENT_POOL_DISCOVERED: WORKER_M81_PROBE,
    EVENT_MIRROR_READY: WORKER_M82_MIRROR,
    EVENT_METADATA_READY: WORKER_M83_METADATA,
    EVENT_QUOTE_READY: WORKER_M9_GRAPH_QUOTE,
}

NEXT_EVENT: Dict[str, str] = {
    EVENT_POOL_DISCOVERED: EVENT_MIRROR_READY,
    EVENT_MIRROR_READY: EVENT_METADATA_READY,
    EVENT_METADATA_READY: EVENT_QUOTE_READY,
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
    """Drains worker jobs; M9 runs on ``quote_ready`` without batch completion."""

    repository: StateRepository
    config: PipelineRuntimeConfig
    policy: TimeoutPolicy
    session_id: str
    _handlers: Dict[str, Callable[[Dict[str, Any]], WorkerResult]] = field(
        default_factory=dict
    )
    _m9_pending: Set[str] = field(default_factory=set)

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

    def process_worker_jobs(
        self,
        worker: str,
        *,
        limit: int = 1,
        lease_s: Optional[float] = None,
    ) -> List[WorkerResult]:
        results: List[WorkerResult] = []
        claim_lease = float(lease_s if lease_s is not None else self.policy.work_item_lease_s)
        jobs = self.repository.claim_jobs(job_type=worker, limit=limit, lease_s=claim_lease)
        handler = self._handlers.get(worker)
        for job in jobs:
            started = time.monotonic()
            try:
                if handler is None:
                    result = self._default_handler(worker, job.payload)
                else:
                    result = handler(job.payload)
                result.latency_s = time.monotonic() - started
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
        event_type = str(payload.get("event_type") or EVENT_POOL_DISCOVERED)
        nxt = NEXT_EVENT.get(event_type)
        return WorkerResult(worker=worker, ok=True, next_event=nxt)

    def m9_jobs_done(self) -> int:
        events = self.repository.list_events(
            session_id=self.session_id,
            since_offset=0,
        )
        return sum(
            1 for e in events if e.event_type in (EVENT_M9_QUOTE_RESULT, EVENT_M9_QUOTED)
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
    broker_drain: bool = False,
) -> List[Dict[str, Any]]:
    """Continuous mode steps. Default: spawn background services then one-shot projections."""
    shadow_minutes = int(getattr(config.shadow, "duration_minutes", None) or 10)
    if broker_drain:
        return [
            {
                "name": "continuous_broker",
                "internal": "continuous_broker",
                "session_id": session_id,
                "timeout_seconds": None,
            },
            {
                "name": "session_aggregate_acceptance",
                "internal": "session_aggregate_acceptance",
                "session_id": session_id,
                "timeout_seconds": None,
            },
            {
                "name": "session_aggregate_bridge",
                "internal": "session_aggregate_bridge",
                "session_id": session_id,
                "timeout_seconds": None,
            },
            {
                "name": "continuous_m9_raw_route_diagnostic",
                "internal": "continuous_m9_shadow",
                "session_id": session_id,
                "duration_minutes": shadow_minutes,
                "timeout_seconds": None,
            },
        ]
    return [
        {
            "name": "continuous_m8_sniper_spawn",
            "internal": "continuous_m8_sniper_spawn",
            "session_id": session_id,
            "timeout_seconds": None,
        },
        {
            "name": "continuous_broker_spawn",
            "internal": "continuous_broker_spawn",
            "session_id": session_id,
            "timeout_seconds": None,
        },
        {
            "name": "session_aggregate_acceptance",
            "internal": "session_aggregate_acceptance",
            "session_id": session_id,
            "timeout_seconds": None,
        },
        {
            "name": "session_aggregate_bridge",
            "internal": "session_aggregate_bridge",
            "session_id": session_id,
            "timeout_seconds": None,
        },
        {
            "name": "continuous_m9_raw_route_diagnostic",
            "internal": "continuous_m9_shadow",
            "session_id": session_id,
            "duration_minutes": shadow_minutes,
            "timeout_seconds": None,
        },
        {
            "name": "continuous_services_stop",
            "internal": "continuous_services_stop",
            "session_id": session_id,
            "timeout_seconds": None,
        },
    ]
