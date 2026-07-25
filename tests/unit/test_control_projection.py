"""Tests for M_control read-only API projections."""
from __future__ import annotations

import json

from api.control_projection import build_control_funnel, build_control_traces


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
