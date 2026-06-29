"""Tests for time-to-mirror hot lane SLA gate."""
from __future__ import annotations

from m8.discovery.time_to_mirror_lane import (
    build_time_to_mirror_latency_artifact,
    evaluate_hot_sla_gate,
)


def test_hot_sla_pass_within_budget():
    doc = build_time_to_mirror_latency_artifact(
        step_timings_s={"m8_2_radar_two_phase": 120.0, "m8_2_cross_dex_expand": 300.0},
        pipeline_latency_s=600.0,
        profile={"lane": "hot_delta", "hot_sla_max_s": 900},
    )
    ok, reason = evaluate_hot_sla_gate(doc, max_latency_s=900)
    assert ok is True
    assert reason == "hot_sla_pass"


def test_hot_sla_fail_when_exceeded():
    doc = build_time_to_mirror_latency_artifact(
        step_timings_s={"m8_2_radar_two_phase": 1000.0},
        pipeline_latency_s=1200.0,
        profile={"lane": "hot_delta", "hot_sla_max_s": 900},
    )
    ok, reason = evaluate_hot_sla_gate(doc, max_latency_s=900)
    assert ok is False
    assert "HOT_SLA_EXCEEDED" in reason


def test_latency_artifact_includes_run_kind():
    doc = build_time_to_mirror_latency_artifact(
        step_timings_s={"m8_2_radar_two_phase": 10.0},
        pipeline_latency_s=10.0,
        profile={"lane": "hot_delta", "hot_sla_max_s": 900, "run_kind": "cached_resume"},
    )
    assert doc["run_kind"] == "cached_resume"
