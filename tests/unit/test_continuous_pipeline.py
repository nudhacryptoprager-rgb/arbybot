"""Contract tests for event-driven continuous pipeline architecture."""
from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from core.continuous_broker import build_orchestrator, run_pool_through_pipeline
from core.continuous_pipeline import (
    EVENT_M9_QUOTE_RESULT,
    EVENT_POOL_DISCOVERED,
    WORKER_M81_PROBE,
    WORKER_M9_GRAPH_QUOTE,
    ContinuousOrchestrator,
    PipelineEvent,
)
from scripts.continuous_adapters import adapter_m82_mirror
from core.pipeline_runtime_config import load_pipeline_runtime_config
from core.timeout_policy import TimeoutPolicy, resolve_step_timeout_seconds
from state.in_memory import InMemoryStateRepository
from state.repository_context import reset_shared_repository


@pytest.fixture(autouse=True)
def _stub_adapters(monkeypatch):
    monkeypatch.setenv("ARBY_CONTINUOUS_STUB_ADAPTERS", "1")
    reset_shared_repository()
    yield
    reset_shared_repository()


def test_event_to_m9_latency_without_m8_completion():
    """Stub path: quote_ready enqueues M9 without waiting for M8 ingest idle."""
    repo = InMemoryStateRepository()
    orch = build_orchestrator("test-session", repository=repo)
    result = run_pool_through_pipeline(orch, "0xabc123", block_number=42)
    assert result.m9_quote_results >= 1
    events = repo.list_events(session_id="test-session")
    assert any(e.event_type == EVENT_M9_QUOTE_RESULT for e in events)


def test_production_adapter_fails_closed_without_rpc(monkeypatch):
    monkeypatch.delenv("ARBY_CONTINUOUS_STUB_ADAPTERS", raising=False)
    monkeypatch.setenv("ARBY_SKIP_RPC", "1")
    repo = InMemoryStateRepository()
    payload = {
        "pool_address": "0xabc",
        "session_id": "s",
        "token0": "0x1",
        "token1": "0x2",
        "filter_passed": True,
        "provenance": "m8_sniper",
    }
    result = adapter_m82_mirror(repo, payload)
    assert not result.ok
    assert result.error


def test_continuous_worker_survives_rpc_timeout():
    repo = InMemoryStateRepository()
    config = load_pipeline_runtime_config()
    policy = TimeoutPolicy.from_config(config, continuous=True)
    orch = ContinuousOrchestrator(
        repository=repo,
        config=config,
        policy=policy,
        session_id="test-session",
    )

    def _rpc_timeout_handler(_payload):
        raise TimeoutError("rpc timeout")

    orch.register_handler(WORKER_M81_PROBE, _rpc_timeout_handler)
    orch.emit(
        PipelineEvent(
            event_type=EVENT_POOL_DISCOVERED,
            session_id="test-session",
            payload={"pool_address": "0xdead", "chain_id": 8453},
            entity_id="0xdead",
        )
    )
    first = orch.process_worker_jobs(WORKER_M81_PROBE, limit=1)
    assert first and not first[0].ok
    second = orch.process_worker_jobs(WORKER_M81_PROBE, limit=1)
    assert isinstance(second, list)


def test_continuous_mode_has_no_global_step_timeout():
    config = load_pipeline_runtime_config()
    policy = TimeoutPolicy.from_config(config, continuous=True)
    step = {"name": "continuous_broker", "internal": "continuous_broker"}
    assert resolve_step_timeout_seconds(step, policy=policy, config=config) is None


_EVM_ADDR_RE = re.compile(r"0x[a-fA-F0-9]{40}")


@pytest.mark.parametrize(
    "rel_path",
    [
        "m8/discovery/hint_verifier.py",
    ],
)
def test_production_modules_delegate_deployments_to_config(rel_path: str):
    text = Path(rel_path).read_text(encoding="utf-8")
    assert "protocol_deployments" in text or "protocol_address" in text or "anchor_addr_to_symbol" in text
    literals = _EVM_ADDR_RE.findall(text)
    allowed = {
        "0x0000000000000000000000000000000000000000",
    }
    assert set(literals).issubset(allowed)


def test_economics_missing_config_fails_closed(monkeypatch):
    from m9.graph_arb.size_truth import (
        ECONOMICS_INPUT_UNAVAILABLE,
        EconomicsInputUnavailable,
        require_cost_model,
    )

    monkeypatch.setenv("ARBY_ECONOMICS_STRICT", "1")
    monkeypatch.setattr(
        "m9.graph_arb.size_truth.load_cost_model",
        lambda _path: {},
    )
    with pytest.raises(EconomicsInputUnavailable) as exc:
        require_cost_model("missing.yaml")
    assert exc.value.code == ECONOMICS_INPUT_UNAVAILABLE
