"""Session aggregate atomic write and incremental repository refresh."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.session_aggregate import (
    SessionAggregate,
    bridge_inventory_from_aggregate,
    load_or_build_session_aggregate,
    merge_repository_into_aggregate,
    session_aggregate_path,
)
from core.pipeline_streaming import STREAMING_ROOT_DIR, sanitize_session_id
from state.in_memory import InMemoryStateRepository
from state.repository import IdempotencyKey, PoolRecord, RouteRecord
from state.repository_context import reset_shared_repository


@pytest.fixture(autouse=True)
def _reset_repo():
    reset_shared_repository()
    yield
    reset_shared_repository()


def test_session_aggregate_atomic_write(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "core.session_aggregate.STREAMING_ROOT_DIR",
        tmp_path,
    )
    agg = SessionAggregate(session_id="sess-atomic")
    agg.upsert_pool({"pool_address": "0xabc", "dex_id": "test"})
    path = session_aggregate_path("sess-atomic")
    agg.write_atomic(path)
    assert path.is_file()
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["counts"]["pools"] == 1
    assert doc["event_offset_watermark"] == 0


def test_load_or_build_refreshes_from_repository(tmp_path, monkeypatch):
    monkeypatch.setattr("core.session_aggregate.STREAMING_ROOT_DIR", tmp_path)
    repo = InMemoryStateRepository()
    repo.upsert_route(
        RouteRecord(
            chain_id=8453,
            route_id="mirror:0xpool",
            dex_id="mirror",
            token_in="0xt0",
            token_out="0xt1",
            pool_address="0xpool",
            status="mirror_ready",
            idempotency=IdempotencyKey(8453, 1, "0xpool", "m82:test"),
        )
    )
    agg = load_or_build_session_aggregate("sess-refresh", repository=repo)
    assert len(agg.routes) == 1
    path = session_aggregate_path("sess-refresh")
    assert path.is_file()


def test_bridge_inventory_from_aggregate():
    agg = SessionAggregate(session_id="sess-bridge")
    agg.upsert_route({"route_id": "r1", "pool_address": "0x1", "dex_id": "uni"})
    doc = bridge_inventory_from_aggregate(agg)
    assert doc["graph_ready_total"] == 1
    assert doc["source"] == "session_aggregate"
