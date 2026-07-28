"""Continuous pipeline broker — long-lived worker loop with lease reclaim."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from core.continuous_ingest import handle_m8_ingest_poll
from core.continuous_pipeline import (
    EVENT_POOL_DISCOVERED,
    ContinuousOrchestrator,
    PipelineEvent,
    build_continuous_worker_names,
)
from core.continuous_workers import register_default_handlers
from core.pipeline_runtime_config import PipelineRuntimeConfig, load_pipeline_runtime_config
from core.protocol_deployments import chain_deployments
from core.timeout_policy import TimeoutPolicy
from state.repository import StateRepository
from state.repository_context import get_shared_repository


@dataclass
class BrokerRunResult:
    rounds: int
    jobs_processed: int
    m9_quoted: int
    m9_quote_results: int = 0
    idle_rounds: int = 0


def build_orchestrator(
    session_id: str,
    *,
    repository: Optional[StateRepository] = None,
    config: Optional[PipelineRuntimeConfig] = None,
) -> ContinuousOrchestrator:
    repo = repository or get_shared_repository()
    cfg = config or load_pipeline_runtime_config()
    policy = TimeoutPolicy.from_config(cfg, continuous=True)
    orch = ContinuousOrchestrator(
        repository=repo,
        config=cfg,
        policy=policy,
        session_id=session_id,
    )
    register_default_handlers(orch, repo)
    return orch


def run_broker_round(
    orchestrator: ContinuousOrchestrator,
    *,
    jobs_per_worker: int = 8,
) -> BrokerRunResult:
    """Single broker poll round — ingest + all workers once."""
    workers = build_continuous_worker_names(orchestrator.config)
    lease_s = orchestrator.policy.work_item_lease_s
    orchestrator.repository.reclaim_expired_leases(lease_s=lease_s)
    processed = 0
    m9_results = 0
    for worker in workers:
        if worker == "m8_ingest":
            handle_m8_ingest_poll(orchestrator, {})
            continue
        results = orchestrator.process_worker_jobs(
            worker,
            limit=jobs_per_worker,
            lease_s=lease_s,
        )
        processed += len(results)
        if worker == "m9_graph_quote":
            m9_results += sum(1 for r in results if r.ok)
    return BrokerRunResult(
        rounds=1,
        jobs_processed=processed,
        m9_quoted=m9_results,
        m9_quote_results=m9_results,
        idle_rounds=0 if processed else 1,
    )


def run_broker_loop(
    orchestrator: ContinuousOrchestrator,
    *,
    max_rounds: int = 100,
    jobs_per_worker: int = 8,
    idle_exit_rounds: int = 2,
) -> BrokerRunResult:
    """Drain mode — for tests/CI only. Ingest via m8_ingest inside each round."""
    processed = 0
    idle = 0
    rounds = 0
    m9_results = 0

    for _ in range(max_rounds):
        rounds += 1
        round_result = run_broker_round(orchestrator, jobs_per_worker=jobs_per_worker)
        processed += round_result.jobs_processed
        m9_results += round_result.m9_quote_results
        if round_result.jobs_processed == 0:
            idle += 1
            if idle >= idle_exit_rounds:
                break
        else:
            idle = 0
        time.sleep(0.01)

    return BrokerRunResult(
        rounds=rounds,
        jobs_processed=processed,
        m9_quoted=m9_results,
        m9_quote_results=m9_results,
        idle_rounds=idle,
    )


def _default_quote_token(chain_id: int = 8453) -> str:
    chain = "base" if chain_id == 8453 else "base"
    anchors = (chain_deployments(chain) or {}).get("anchor_tokens") or {}
    if isinstance(anchors, dict) and anchors:
        return str(next(iter(anchors.keys())))
    return ""


def seed_pool_discovered(
    orchestrator: ContinuousOrchestrator,
    *,
    pool_address: str,
    chain_id: int = 8453,
    block_number: int = 1,
    **extra: object,
) -> None:
    token1 = str(extra.get("token1") or _default_quote_token(chain_id))
    orchestrator.emit(
        PipelineEvent(
            event_type=EVENT_POOL_DISCOVERED,
            session_id=orchestrator.session_id,
            payload={
                "pool_address": pool_address,
                "chain_id": chain_id,
                "block_number": block_number,
                "token0": extra.get("token0", pool_address),
                "token1": token1,
                "dex_id": extra.get("dex_id", "uniswap_v4"),
                "decimals": extra.get("decimals", 18),
                "symbol": extra.get("symbol", "TEST"),
            },
            observed_block=block_number,
            entity_id=pool_address,
        )
    )


def run_pool_through_pipeline(
    orchestrator: ContinuousOrchestrator,
    pool_address: str,
    *,
    chain_id: int = 8453,
    block_number: int = 1,
) -> BrokerRunResult:
    """Seed one pool and run broker until M9 quoted or idle."""
    seed_pool_discovered(
        orchestrator,
        pool_address=pool_address,
        chain_id=chain_id,
        block_number=block_number,
    )
    return run_broker_loop(orchestrator, max_rounds=50, idle_exit_rounds=1)
