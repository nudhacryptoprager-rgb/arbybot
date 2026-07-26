"""Tests for M_control read-only API projections."""
from __future__ import annotations

import json

from api.control_projection import (
    build_control_funnel,
    build_control_traces,
    sanitize_repo_relative_json_path,
)


def test_control_funnel_economics_not_yet_tested(tmp_path):
    (tmp_path / "data/tmp").mkdir(parents=True)
    (tmp_path / "data/runs/_rolling").mkdir(parents=True)
    (tmp_path / "data/tmp/m9_bridge_inventory_production_latest.json").write_text(
        json.dumps({"fresh_long_tail_quote_ready_tokens": 0, "session_id": "sess_a"}),
        encoding="utf-8",
    )
    (tmp_path / "data/runs/_rolling/m9_graph_latest.json").write_text(
        json.dumps(
            {
                "cycles_found": 100,
                "cycles_quoteable": 0,
                "quote_size_truth": {"econ_rpc_quote_attempts": 0},
                "cycle_reject_histogram": {"DEPTH_BELOW_ECONOMICS_FLOOR": 100},
                "run_context": {"session_id": "sess_a"},
            }
        ),
        encoding="utf-8",
    )
    funnel = build_control_funnel(tmp_path)
    assert funnel["schema_version"] == "m_control_funnel_v2"
    assert funnel["economics_not_yet_tested"] is True
    assert funnel["session_id"] == "sess_a"
    assert "DEPTH_BELOW_ECONOMICS_FLOOR" in funnel["reason_histogram"]


def test_control_traces_capacity_ids(tmp_path):
    (tmp_path / "data/tmp").mkdir(parents=True)
    ids = [f"cid_{i}" for i in range(12)]
    (tmp_path / "data/tmp/m9_capacity_cycle_diagnostic_latest.json").write_text(
        json.dumps({"capacity_valid_cycle_ids": ids}),
        encoding="utf-8",
    )
    traces = build_control_traces(tmp_path)
    assert traces["cycles"]["capacity_valid_total"] == 12


def test_control_funnel_uses_pipeline_shadow_path(tmp_path):
    (tmp_path / "data/tmp").mkdir(parents=True)
    (tmp_path / "data/runs/_rolling").mkdir(parents=True)
    (tmp_path / "data/tmp/m9_bridge_inventory_production_latest.json").write_text(
        json.dumps({"session_id": "sess_x"}),
        encoding="utf-8",
    )
    (tmp_path / "data/tmp/m9_shadow_capacity_smoke.json").write_text(
        json.dumps(
            {
                "cycles_found": 5,
                "cycles_quoteable": 0,
                "quote_size_truth": {"econ_rpc_quote_attempts": 0},
                "run_context": {"session_id": "sess_x"},
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "data/runs/_rolling/m9_graph_latest.json").write_text(
        json.dumps({"cycles_found": 0, "quote_size_truth": {"econ_rpc_quote_attempts": 0}}),
        encoding="utf-8",
    )
    (tmp_path / "data/tmp/start_pipeline_current.json").write_text(
        json.dumps({"shadow_artifact_path": "data/tmp/m9_shadow_capacity_smoke.json"}),
        encoding="utf-8",
    )
    funnel = build_control_funnel(tmp_path)
    assert funnel["shadow_source_path"] == "data/tmp/m9_shadow_capacity_smoke.json"
    assert funnel["economics_not_yet_tested"] is True


def test_sanitize_repo_relative_json_path_rejects_absolute_and_dotdot(tmp_path):
    (tmp_path / "data/tmp").mkdir(parents=True)
    good = tmp_path / "data/tmp/ok.json"
    good.write_text("{}", encoding="utf-8")
    assert sanitize_repo_relative_json_path(tmp_path, "data/tmp/ok.json") == "data/tmp/ok.json"
    assert sanitize_repo_relative_json_path(tmp_path, str(good)) is None
    assert sanitize_repo_relative_json_path(tmp_path, "data/tmp/../secret.json") is None
    assert sanitize_repo_relative_json_path(tmp_path, "data/tmp/missing.json") is None


def test_control_funnel_marks_fixture_shadow_not_runtime_evidence(tmp_path):
    (tmp_path / "data/tmp").mkdir(parents=True)
    (tmp_path / "data/runs/_rolling").mkdir(parents=True)
    (tmp_path / "data/runs/_rolling/m9_graph_latest.json").write_text(
        json.dumps(
            {
                "config_path": "_nonexistent_config_for_gate_test.yaml",
                "cycles_found": 10,
                "quote_size_truth": {"econ_rpc_quote_attempts": 0},
            }
        ),
        encoding="utf-8",
    )
    funnel = build_control_funnel(tmp_path)
    assert funnel["shadow_runtime_evidence_status"] == "NOT_RUNTIME_EVIDENCE"
    assert funnel["shadow_fixture_rejected"] is True
