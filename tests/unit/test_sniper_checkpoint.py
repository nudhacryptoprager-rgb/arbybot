"""Tests for sniper streaming checkpoint artifact."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from m8.runtime.sniper_checkpoint import (
    CHECKPOINT_SCHEMA_VERSION,
    load_checkpoint,
    validate_checkpoint_for_batch,
    write_checkpoint_artifact,
)


def test_checkpoint_write_and_validate(tmp_path):
    path = tmp_path / "checkpoint.json"
    write_checkpoint_artifact(
        str(path),
        session_id="sess_ck",
        chain="base",
        rpc_url="https://rpc.example",
        factory_config_fingerprint="fp123",
        self_test_results={"uniswap_v3": "PASS"},
        batch_index=1,
    )
    ck = load_checkpoint(str(path))
    assert ck is not None
    assert ck["schema_version"] == CHECKPOINT_SCHEMA_VERSION
    blockers = validate_checkpoint_for_batch(
        ck,
        batch_index=2,
        session_id="sess_ck",
        chain="base",
        rpc_url="https://rpc.example",
        factory_config_fingerprint="fp123",
        now_utc=datetime(2026, 7, 26, 12, 0, 0, tzinfo=timezone.utc),
    )
    assert blockers == []


def test_checkpoint_rejects_session_mismatch(tmp_path):
    path = tmp_path / "checkpoint.json"
    write_checkpoint_artifact(
        str(path),
        session_id="sess_a",
        chain="base",
        rpc_url="https://rpc.example",
        factory_config_fingerprint="fp123",
        self_test_results={"ok": True},
    )
    blockers = validate_checkpoint_for_batch(
        load_checkpoint(str(path)),
        batch_index=2,
        session_id="sess_b",
        chain="base",
        rpc_url="https://rpc.example",
        factory_config_fingerprint="fp123",
    )
    assert "SNIPER_CHECKPOINT_SESSION_MISMATCH" in blockers


def test_checkpoint_rejects_empty_session_on_write(tmp_path):
    with pytest.raises(ValueError, match="non-empty session_id"):
        write_checkpoint_artifact(
            str(tmp_path / "checkpoint.json"),
            session_id="",
            chain="base",
            rpc_url="https://rpc.example",
            factory_config_fingerprint="fp123",
            self_test_results={"ok": True},
        )


def test_checkpoint_rejects_missing_expected_session(tmp_path):
    path = tmp_path / "checkpoint.json"
    write_checkpoint_artifact(
        str(path),
        session_id="sess_a",
        chain="base",
        rpc_url="https://rpc.example",
        factory_config_fingerprint="fp123",
        self_test_results={"ok": True},
    )
    blockers = validate_checkpoint_for_batch(
        load_checkpoint(str(path)),
        batch_index=2,
        session_id="",
        chain="base",
        rpc_url="https://rpc.example",
        factory_config_fingerprint="fp123",
    )
    assert "SNIPER_CHECKPOINT_SESSION_EXPECTED_MISSING" in blockers
