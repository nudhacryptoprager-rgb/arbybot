"""Continuous pipeline worker handlers — production adapters + test stubs."""
from __future__ import annotations

import os
from typing import Any, Dict

from core.continuous_pipeline import (
    EVENT_M9_QUOTE_RESULT,
    EVENT_METADATA_READY,
    EVENT_MIRROR_READY,
    EVENT_POOL_DISCOVERED,
    EVENT_QUOTE_READY,
    WORKER_M9_GRAPH_QUOTE,
    WORKER_M81_PROBE,
    WORKER_M82_MIRROR,
    WORKER_M83_METADATA,
    ContinuousOrchestrator,
    WorkerResult,
)
from state.repository import IdempotencyKey, PoolRecord, RouteRecord, StateRepository


def _idem(payload: Dict[str, Any], revision: str) -> IdempotencyKey:
    return IdempotencyKey(
        chain_id=int(payload.get("chain_id") or 8453),
        block_number=int(payload.get("block_number") or 0),
        entity_id=str(payload.get("pool_address") or payload.get("entity_id") or ""),
        input_revision=revision,
    )


def _stub_m81_probe(repository: StateRepository, payload: Dict[str, Any]) -> WorkerResult:
    pool_address = str(payload.get("pool_address") or "")
    session_id = str(payload.get("session_id") or "")
    with repository.transaction():
        repository.upsert_pool(
            PoolRecord(
                chain_id=int(payload.get("chain_id") or 8453),
                dex_id=str(payload.get("dex_id") or "unknown"),
                pool_address=pool_address,
                token0=str(payload.get("token0") or ""),
                token1=str(payload.get("token1") or ""),
                pool_type=str(payload.get("pool_type") or "unknown"),
                fee=None,
                status="m81_stub",
                idempotency=_idem(payload, f"m81:{session_id}"),
                extra={"stage": "m81_probe_stub"},
            )
        )
        repository.append_event(
            event_type=EVENT_POOL_DISCOVERED,
            session_id=session_id,
            entity_id=pool_address,
            payload=dict(payload),
            observed_block=int(payload.get("block_number") or 0),
        )
    return WorkerResult(worker=WORKER_M81_PROBE, ok=True, next_event=EVENT_MIRROR_READY)


def _stub_m82_mirror(repository: StateRepository, payload: Dict[str, Any]) -> WorkerResult:
    pool_address = str(payload.get("pool_address") or "")
    session_id = str(payload.get("session_id") or "")
    route_id = f"mirror:{pool_address.lower()}"
    with repository.transaction():
        repository.upsert_route(
            RouteRecord(
                chain_id=int(payload.get("chain_id") or 8453),
                route_id=route_id,
                dex_id=str(payload.get("dex_id") or "mirror"),
                token_in=str(payload.get("token0") or ""),
                token_out=str(payload.get("token1") or ""),
                pool_address=pool_address,
                status="mirror_stub",
                idempotency=_idem(payload, f"m82:{session_id}"),
                extra={"handoff_lane": "mirror_2leg_stub"},
            )
        )
        repository.append_event(
            event_type=EVENT_MIRROR_READY,
            session_id=session_id,
            entity_id=pool_address,
            payload=dict(payload),
            observed_block=int(payload.get("block_number") or 0),
        )
    return WorkerResult(worker=WORKER_M82_MIRROR, ok=True, next_event=EVENT_METADATA_READY)


def _stub_m83_metadata(repository: StateRepository, payload: Dict[str, Any]) -> WorkerResult:
    pool_address = str(payload.get("pool_address") or "")
    session_id = str(payload.get("session_id") or "")
    token0 = str(payload.get("token0") or pool_address)
    with repository.transaction():
        repository.upsert_token(
            chain_id=int(payload.get("chain_id") or 8453),
            address=token0,
            decimals=int(payload.get("decimals") or 18),
            symbol=str(payload.get("symbol") or "UNK"),
            idempotency=_idem(payload, f"m83:{session_id}"),
        )
        repository.append_event(
            event_type=EVENT_METADATA_READY,
            session_id=session_id,
            entity_id=pool_address,
            payload=dict(payload),
            observed_block=int(payload.get("block_number") or 0),
        )
    return WorkerResult(worker=WORKER_M83_METADATA, ok=True, next_event=EVENT_QUOTE_READY)


def _stub_m9_graph_quote(repository: StateRepository, payload: Dict[str, Any]) -> WorkerResult:
    pool_address = str(payload.get("pool_address") or "")
    session_id = str(payload.get("session_id") or "")
    with repository.transaction():
        repository.append_event(
            event_type=EVENT_M9_QUOTE_RESULT,
            session_id=session_id,
            entity_id=pool_address,
            payload={**dict(payload), "rpc_dispatched": False, "ok": True, "stub": True},
            observed_block=int(payload.get("block_number") or 0),
        )
    return WorkerResult(worker=WORKER_M9_GRAPH_QUOTE, ok=True, next_event=None)


STUB_HANDLERS = {
    WORKER_M81_PROBE: _stub_m81_probe,
    WORKER_M82_MIRROR: _stub_m82_mirror,
    WORKER_M83_METADATA: _stub_m83_metadata,
    WORKER_M9_GRAPH_QUOTE: _stub_m9_graph_quote,
}


def register_stub_handlers(
    orchestrator: ContinuousOrchestrator,
    repository: StateRepository,
) -> None:
    for worker, fn in STUB_HANDLERS.items():
        orchestrator.register_handler(worker, lambda p, _fn=fn: _fn(repository, p))


def register_default_handlers(
    orchestrator: ContinuousOrchestrator,
    repository: StateRepository,
) -> None:
    if os.environ.get("ARBY_CONTINUOUS_STUB_ADAPTERS") == "1":
        register_stub_handlers(orchestrator, repository)
