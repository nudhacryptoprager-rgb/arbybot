"""Tests for state repository factory ingest."""
from __future__ import annotations

import pytest

from m8.runtime.state_repository_ingest import ingest_sniper_artifact_to_repository


def test_ingest_disabled_by_default():
    stats = ingest_sniper_artifact_to_repository({"recent_events": []})
    assert stats.get("enabled") is False


def test_ingest_requires_explicit_backend_when_enabled(monkeypatch):
    monkeypatch.setenv("ARBY_STATE_REPOSITORY_ENABLED", "1")
    with pytest.raises(ValueError, match="ARBY_STATE_REPOSITORY_BACKEND required"):
        ingest_sniper_artifact_to_repository({"recent_events": []})


def test_ingest_in_memory_commits_with_chain_map(monkeypatch):
    monkeypatch.setenv("ARBY_STATE_REPOSITORY_ENABLED", "1")
    artifact = {
        "generated_at_utc": "2026-07-26T12:00:00Z",
        "recent_events": [
            {
                "event_id": "e1",
                "chain": "base",
                "dex": "uniswap_v3",
                "factory": "0x" + "f1" * 20,
                "pool": "0x" + "ab" * 20,
                "token0": "0x" + "0a" * 20,
                "token1": "0x" + "1b" * 20,
                "block_number": 100,
                "filter_passed": True,
                "candidate": True,
            }
        ],
    }
    stats = ingest_sniper_artifact_to_repository(artifact, backend="in_memory")
    assert stats.get("enabled") is True
    assert stats.get("committed", 0) >= 1


def test_ingest_writes_stats_into_artifact(monkeypatch):
    monkeypatch.setenv("ARBY_STATE_REPOSITORY_ENABLED", "1")
    artifact = {
        "generated_at_utc": "2026-07-26T12:00:00Z",
        "recent_events": [
            {
                "event_id": "e1",
                "chain": "base",
                "dex": "uniswap_v3",
                "factory": "0x" + "f1" * 20,
                "pool": "0x" + "ab" * 20,
                "token0": "0x" + "0a" * 20,
                "token1": "0x" + "1b" * 20,
                "block_number": 100,
                "filter_passed": True,
                "candidate": True,
            }
        ],
    }
    ingest_sniper_artifact_to_repository(artifact, backend="in_memory", mutate_artifact=artifact)
    assert "state_repository_ingest" in artifact
    assert artifact["state_repository_ingest"].get("enabled") is True
