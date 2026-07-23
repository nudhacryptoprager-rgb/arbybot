"""Orchestration contract: content-aware pipeline markers and truth-gate order."""
from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path
from unittest.mock import patch

import pytest

import start
from application.checkpoint_store import fingerprint_paths, write_done_record


def test_truth_gates_always_rerun_even_with_done_marker(tmp_path, monkeypatch):
    monkeypatch.setattr(start, "PIPELINE_STEP_MARKERS_DIR", tmp_path / "markers")
    done, _fail = start._step_marker_paths(
        "m8_m9_runtime_truth_gate_upstream",
        pipeline_mode="m8_m9",
    )
    write_done_record(done, fingerprint="stale")
    assert not start._should_skip_done_marker(
        "m8_m9_runtime_truth_gate_upstream",
        done,
        force_rerun=False,
    )


def test_content_aware_marker_skips_only_when_fingerprint_matches(tmp_path, monkeypatch):
    monkeypatch.setattr(start, "PIPELINE_STEP_MARKERS_DIR", tmp_path / "markers")
    artifact = tmp_path / "upstream_input.json"
    artifact.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        start,
        "_upstream_artifacts_fingerprint",
        lambda: fingerprint_paths([artifact]),
    )

    done, _fail = start._step_marker_paths("m8_2_cross_dex_expand", pipeline_mode="m8_m9")
    fp = start._pipeline_step_fingerprint("m8_2_cross_dex_expand")
    write_done_record(done, fingerprint=fp)
    assert start._should_skip_done_marker(
        "m8_2_cross_dex_expand",
        done,
        force_rerun=False,
    )

    artifact.write_text('{"changed": true}', encoding="utf-8")
    assert not start._should_skip_done_marker(
        "m8_2_cross_dex_expand",
        done,
        force_rerun=False,
    )


def test_m8_m9_plan_orders_bundle_gate_after_bridge_production():
    args = Namespace(
        pipeline="m8_m9",
        sniper_minutes=1,
        max_radar_tokens=10,
        skip_coingecko=True,
        skip_shadow=True,
        skip_preflight=True,
        radar_step_timeout_s=60,
    )
    names = [step["name"] for step in start.build_project_pipeline_steps(args)]
    idx_bridge = names.index("m9_bridge_production")
    idx_bundle_gate = names.index("m8_m9_runtime_truth_gate_bundle")
    idx_depth = names.index("m9_enrich_depth_false_positive")
    idx_post_depth = names.index("m8_m9_runtime_truth_gate_post_depth")
    assert idx_bundle_gate > idx_bridge
    assert idx_depth > idx_bundle_gate
    assert idx_post_depth > names.index("m9_enrich_depth_broad")


def test_bundle_truth_gate_blocks_on_nonzero_exit():
    args = Namespace(
        pipeline="m9",
        sniper_minutes=1,
        max_radar_tokens=10,
        skip_coingecko=True,
        skip_shadow=True,
        skip_preflight=True,
    )
    steps = {s["name"]: s for s in start.build_project_pipeline_steps(args)}
    gate = steps["m8_m9_runtime_truth_gate_bundle"]
    assert gate["allow_exit_codes"] == (0,)


def test_upstream_writer_invalidates_truth_gate_markers(tmp_path, monkeypatch):
    monkeypatch.setattr(start, "PIPELINE_STEP_MARKERS_DIR", tmp_path / "markers")
    mode = "m8_m9"
    for step in (
        "m8_m9_runtime_truth_gate_upstream",
        "m8_m9_runtime_truth_gate_bundle",
    ):
        write_done_record(
            start._step_marker_paths(step, pipeline_mode=mode)[0],
            fingerprint="x",
        )
    cleared = start._invalidate_truth_gate_markers(mode, upstream=True, bundle=True)
    assert cleared >= 2
    assert not start._step_marker_paths(
        "m8_m9_runtime_truth_gate_upstream",
        pipeline_mode=mode,
    )[0].exists()
