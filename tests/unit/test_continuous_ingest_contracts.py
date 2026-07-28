"""Contract tests for continuous ingest, adapters, and repository reads."""
from __future__ import annotations

from unittest.mock import patch

from scripts.continuous_adapters import _resolve_mirror_route, adapter_m83_metadata
from core.continuous_broker import run_broker_round
from core.continuous_ingest import poll_sniper_ingest
from core.continuous_pipeline import ContinuousOrchestrator
from core.pipeline_runtime_config import load_pipeline_runtime_config
from core.timeout_policy import TimeoutPolicy
from state.in_memory import InMemoryStateRepository


def _orch(repo: InMemoryStateRepository, session_id: str = "ingest-test") -> ContinuousOrchestrator:
    cfg = load_pipeline_runtime_config()
    policy = TimeoutPolicy.from_config(cfg, continuous=True)
    return ContinuousOrchestrator(
        repository=repo,
        config=cfg,
        policy=policy,
        session_id=session_id,
    )


def test_single_ingest_poll_per_broker_round():
    repo = InMemoryStateRepository()
    orch = _orch(repo)
    with patch("core.continuous_ingest.poll_sniper_ingest", wraps=poll_sniper_ingest) as mocked:
        run_broker_round(orch, jobs_per_worker=1)
        assert mocked.call_count == 1


def test_ingest_cursor_stored_in_repository(tmp_path, monkeypatch):
    repo = InMemoryStateRepository()
    orch = _orch(repo, "cursor-sess")
    sniper = tmp_path / "sniper.json"
    sniper.write_text(
        '{"run_context":{"run_timestamp":"2099-01-01T00:00:00Z"},'
        '"recent_events":[{"event_id":"e1","pool":"0xabc","chain":"base",'
        '"filter_passed":true,"token0":"0x1","token1":"0x2","dex":"uni"}]}',
        encoding="utf-8",
    )
    monkeypatch.setenv("ARBY_SNIPER_MAX_ARTIFACT_AGE_S", "999999")
    emitted = poll_sniper_ingest(orch, sniper_path=sniper, repository=repo)
    assert emitted == 1
    cursor = repo.get_ingest_cursor("cursor-sess")
    assert "e1" in cursor.get("seen_event_ids", [])


def test_mirror_route_requires_distinct_pool():
    route, err = _resolve_mirror_route(
        "0xorigin",
        "0xtoken0",
        "0xtoken1",
        {},
    )
    assert route is None
    assert err == "MIRROR_ROUTE_UNRESOLVED"


def test_m83_requires_both_decimals(monkeypatch):
    monkeypatch.setenv("ARBY_SKIP_RPC", "1")
    repo = InMemoryStateRepository()
    result = adapter_m83_metadata(
        repo,
        {
            "pool_address": "0xpool",
            "session_id": "s",
            "token0": "0xt0",
            "token1": "0xt1",
            "factory_verified": True,
        },
    )
    assert not result.ok
    assert result.error == "DECIMALS_UNKNOWN"


def test_repository_list_api_for_aggregate():
    repo = InMemoryStateRepository()
    assert repo.list_pools() == []
    assert repo.list_routes() == []
    assert repo.list_tokens() == []
