"""Regression: unit tests must not write M9 rolling shadow artifacts."""
from __future__ import annotations

from pathlib import Path


def test_gate_tests_do_not_target_rolling_m9_graph():
    text = Path("tests/unit/test_m9_runner_config_gates.py").read_text(encoding="utf-8")
    assert "data/runs/_rolling/m9_graph_latest.json" not in text
    assert "_GATE_ARTIFACT" in text
