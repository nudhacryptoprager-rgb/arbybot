"""Tests for pipeline session binding before M9 step construction."""
from __future__ import annotations

import os

import pytest

import start
from core.pipeline_provenance import ENV_PIPELINE_SESSION_ID, new_pipeline_session_id
from m8.runtime.sniper_checkpoint import resolve_streaming_checkpoint_path
from m9.graph_arb.effective_inventory import ENV_EFFECTIVE_INVENTORY_PATH, sanitize_session_token


def _m8_m9_args():
    return start.parse_args(["-m8_m9", "--no-dashboard"])


def _effective_paths_from_steps(steps: list[dict]) -> list[str]:
    paths: list[str] = []
    for step in steps:
        env = step.get("env") or {}
        path = str(env.get(ENV_EFFECTIVE_INVENTORY_PATH) or "").strip()
        if path:
            paths.append(path)
    return paths


def test_m8_m9_steps_never_use_unknown_effective_inventory(monkeypatch):
    monkeypatch.delenv(ENV_PIPELINE_SESSION_ID, raising=False)
    monkeypatch.delenv(ENV_EFFECTIVE_INVENTORY_PATH, raising=False)
    monkeypatch.delenv(ENV_PIPELINE_SESSION_ID, raising=False)
    session_id = "2026-07-26T12:34:56Z"
    os.environ[ENV_PIPELINE_SESSION_ID] = session_id
    steps = start.build_project_pipeline_steps(_m8_m9_args())
    paths = _effective_paths_from_steps(steps)
    assert paths, "expected M9 steps to carry effective inventory path"
    token = sanitize_session_token(session_id)
    for path in paths:
        assert "_unknown" not in path
        assert token in path


def test_pipeline_session_must_precede_step_build(monkeypatch):
    monkeypatch.delenv(ENV_PIPELINE_SESSION_ID, raising=False)
    session_id = new_pipeline_session_id()
    os.environ[ENV_PIPELINE_SESSION_ID] = session_id
    steps = start.build_project_pipeline_steps(_m8_m9_args())
    paths = _effective_paths_from_steps(steps)
    assert paths
    assert all("_unknown" not in p for p in paths)


def test_streaming_checkpoint_path_is_session_namespaced(monkeypatch):
    monkeypatch.setenv(ENV_PIPELINE_SESSION_ID, "2026-07-26T12:34:56Z")
    path = resolve_streaming_checkpoint_path()
    assert "_unknown" not in path
    assert "2026-07-26T12_34_56Z" in path.replace("\\", "/")


def test_materialize_requires_live_writer_flag(monkeypatch, tmp_path):
    from m9.graph_arb.effective_inventory import materialize_effective_inventory

    bridge = tmp_path / "bridge.json"
    bridge.write_text(
        '{"active_routes":[],"depth_enrichment":{"post_depth_content_hash":"x","depth_enrichment_session_id":"s"}}',
        encoding="utf-8",
    )
    monkeypatch.delenv("ARBY_M9_ALLOW_LIVE_EFFECTIVE_INVENTORY_MATERIALIZE", raising=False)
    with pytest.raises(ValueError, match="live effective inventory materialization disabled"):
        materialize_effective_inventory(
            str(bridge),
            "config/exotic_base_anchor.yaml",
            output_path=str(tmp_path / "out.json"),
            session_id="sess",
            token_prices={"0xt0": 1.0},
        )
