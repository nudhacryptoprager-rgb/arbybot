"""Regression: unit tests must not write M9 rolling shadow artifacts."""
from __future__ import annotations

from pathlib import Path

import pytest

_ROLLING_M9 = "data/runs/_rolling/m9_graph_latest.json"
_WRITE_MARKERS = (
    "write_text(",
    "write_artifact(",
    "os.replace(",
    '.open("w"',
    ".open('w'",
)


def test_gate_tests_do_not_target_rolling_m9_graph():
    text = Path("tests/unit/test_m9_runner_config_gates.py").read_text(encoding="utf-8")
    assert _ROLLING_M9 not in text
    assert "_GATE_ARTIFACT" in text


def test_no_test_writes_to_canonical_rolling_m9_graph():
    violations: list[str] = []
    for py in Path("tests").rglob("*.py"):
        if py.name == "test_rolling_artifact_write_policy.py":
            continue
        text = py.read_text(encoding="utf-8")
        if _ROLLING_M9 not in text:
            continue
        if not any(marker in text for marker in _WRITE_MARKERS):
            continue
        if "tmp_path" in text or "_GATE_ARTIFACT" in text:
            continue
        violations.append(str(py))
    assert violations == []


def test_write_artifact_guard_blocks_rolling_under_pytest(monkeypatch):
    from m9.graph_arb.artifacts import write_artifact

    monkeypatch.setenv("PYTEST_CURRENT_TEST", "test_write_artifact_guard")
    with pytest.raises(RuntimeError, match="must not write rolling artifacts"):
        write_artifact({"cycles_found": 0}, "data/runs/_rolling/m9_graph_latest.json")
