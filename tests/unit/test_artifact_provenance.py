"""Tests for artifact provenance / fixture rejection."""
from __future__ import annotations

from api.artifact_provenance import is_test_or_fixture_artifact


def test_fixture_detected_by_config_path():
    assert is_test_or_fixture_artifact(
        {"config_path": "data/tmp/_nonexistent_config_for_gate_test.yaml"}
    )


def test_production_artifact_not_fixture():
    assert not is_test_or_fixture_artifact(
        {
            "config_path": "config/exotic_base_anchor.yaml",
            "cycles_found": 100,
        }
    )
