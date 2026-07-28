"""M9 continuous admission — event graph must reach m9_quote_result via broker."""
from __future__ import annotations

import pytest

from core.continuous_broker import build_orchestrator, run_pool_through_pipeline
from core.continuous_pipeline import (
    EVENT_M9_QUOTE_RESULT,
    EVENT_POOL_DISCOVERED,
    EVENT_QUOTE_READY,
    WORKER_FOR_EVENT,
    WORKER_M81_PROBE,
    WORKER_M82_MIRROR,
    WORKER_M83_METADATA,
    WORKER_M9_GRAPH_QUOTE,
)
from state.in_memory import InMemoryStateRepository
from state.repository_context import reset_shared_repository


@pytest.fixture(autouse=True)
def _stub_env(monkeypatch):
    monkeypatch.setenv("ARBY_CONTINUOUS_STUB_ADAPTERS", "1")
    reset_shared_repository()
    yield
    reset_shared_repository()


def test_event_graph_worker_mapping():
    assert WORKER_FOR_EVENT[EVENT_POOL_DISCOVERED] == WORKER_M81_PROBE
    assert WORKER_FOR_EVENT["mirror_ready"] == WORKER_M82_MIRROR
    assert WORKER_FOR_EVENT["metadata_ready"] == WORKER_M83_METADATA
    assert WORKER_FOR_EVENT[EVENT_QUOTE_READY] == WORKER_M9_GRAPH_QUOTE


def test_pool_discovered_to_m9_quote_result_via_broker():
    repo = InMemoryStateRepository()
    orch = build_orchestrator("admission-test", repository=repo)
    result = run_pool_through_pipeline(
        orch,
        "0x2222222222222222222222222222222222222222",
        block_number=99,
    )
    assert result.jobs_processed >= 4
    assert result.m9_quote_results >= 1
    events = repo.list_events(session_id="admission-test")
    types = [e.event_type for e in events]
    assert EVENT_POOL_DISCOVERED in types
    assert EVENT_M9_QUOTE_RESULT in types
    assert orch.m9_jobs_done() >= 1


def test_shared_repository_singleton_across_orchestrators():
    from state.repository_context import get_shared_repository

    r1 = get_shared_repository()
    r2 = get_shared_repository()
    assert r1 is r2


def test_continuous_production_requires_postgres(monkeypatch):
    from state.repository_context import get_shared_repository

    monkeypatch.setenv("ARBY_CONTINUOUS_PRODUCTION", "1")
    monkeypatch.setenv("ARBY_STATE_REPOSITORY_BACKEND", "in_memory")
    reset_shared_repository()
    with pytest.raises(ValueError, match="postgres"):
        get_shared_repository()
