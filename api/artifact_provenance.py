"""Detect test/fixture artifacts that must not drive M_control or live gates."""
from __future__ import annotations

from typing import Any, Mapping, Optional

_TEST_CONFIG_MARKERS = (
    "_nonexistent_config",
    "_gate_test",
    "/tmp/",
    "pytest",
)

_TEST_SOURCE_MARKERS = (
    "test_fixture",
    "unit_test",
    "gate_test",
)


def is_test_or_fixture_artifact(doc: Optional[Mapping[str, Any]]) -> bool:
    """True when artifact provenance indicates unit-test or gate-fixture origin."""
    if not doc or not isinstance(doc, Mapping):
        return False
    if doc.get("test_fixture") is True or doc.get("is_test_fixture") is True:
        return True
    source = str(doc.get("source") or doc.get("artifact_source") or "").lower()
    if any(m in source for m in _TEST_SOURCE_MARKERS):
        return True
    for key in ("config_path", "inventory_path"):
        raw = str(doc.get(key) or "")
        rc = doc.get("run_context")
        if isinstance(rc, Mapping):
            raw = raw or str(rc.get(key) or "")
        if any(m in raw for m in _TEST_CONFIG_MARKERS):
            return True
    runner_outcome = str(doc.get("runner_outcome") or "")
    if runner_outcome == "GATE_TEST_FIXTURE":
        return True
    return False
