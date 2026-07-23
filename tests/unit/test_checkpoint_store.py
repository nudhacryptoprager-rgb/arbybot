"""Tests for content-based checkpoint fingerprints."""
from __future__ import annotations

from application.checkpoint_store import fingerprint_paths


def test_fingerprint_changes_when_content_changes(tmp_path):
    artifact = tmp_path / "artifact.json"
    artifact.write_text("{}", encoding="utf-8")
    fp1 = fingerprint_paths([artifact])
    artifact.write_text('{"changed": true}', encoding="utf-8")
    fp2 = fingerprint_paths([artifact])
    assert fp1 != fp2
