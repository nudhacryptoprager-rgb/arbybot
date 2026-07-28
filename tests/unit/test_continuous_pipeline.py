"""Contract tests for event-driven continuous pipeline architecture."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from core.continuous_pipeline import (
    EVENT_QUOTE_READY,
    WORKER_M9_GRAPH_QUOTE,
    ContinuousOrchestrator,
    PipelineEvent,
)
from core.pipeline_runtime_config import load_pipeline_runtime_config
from core.timeout_policy import TimeoutPolicy, resolve_step_timeout_seconds
from state.in_memory import InMemoryStateRepository


def test_event_to_m9_latency_without_m8_completion():
    """quote_ready must enqueue M9 without waiting for M8 ingest idle."""
    repo = InMemoryStateRepository()
    config = load_pipeline_runtime_config()
    policy = TimeoutPolicy.from_config(config, continuous=True)
    orch = ContinuousOrchestrator(
        repository=repo,
        config=config,
        policy=policy,
        session_id="test-session",
    )
    latency_s = orch.simulate_pool_to_m9("0xabc123", block_number=42)
    assert latency_s < 1.0
    m9_jobs = [j for j in repo._jobs if j["job_type"] == WORKER_M9_GRAPH_QUOTE]
    assert len(m9_jobs) >= 1
    assert m9_jobs[0]["payload"]["event_type"] == EVENT_QUOTE_READY


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

    from core.continuous_pipeline import WORKER_M81_PROBE

    orch.register_handler(WORKER_M81_PROBE, _rpc_timeout_handler)
    orch.emit(
        PipelineEvent(
            event_type=EVENT_QUOTE_READY,
            session_id="test-session",
            payload={"pool_address": "0xdead", "chain_id": 8453},
            entity_id="0xdead",
        )
    )
    first = orch.process_worker_jobs(WORKER_M81_PROBE, limit=1)
    assert first and not first[0].ok
    # Orchestrator remains usable after RPC timeout (no orphan service kill).
    second = orch.process_worker_jobs(WORKER_M81_PROBE, limit=1)
    assert isinstance(second, list)


def test_continuous_mode_has_no_global_step_timeout():
    config = load_pipeline_runtime_config()
    policy = TimeoutPolicy.from_config(config, continuous=True)
    step = {"name": "continuous_m81_probe", "internal": "continuous_worker"}
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
    # Deployment addresses must come from config/protocol_deployments.yaml loaders.
    assert "protocol_deployments" in text or "protocol_address" in text or "anchor_addr_to_symbol" in text
    # No literal Base mainnet deployment constants in these modules.
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
