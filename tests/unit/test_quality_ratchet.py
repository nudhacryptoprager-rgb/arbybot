"""Unit tests for the quality ratchet gate (parsing + compare logic)."""
from __future__ import annotations

import scripts.check_quality_ratchet as ratchet


def test_parse_ruff_count():
    assert ratchet.parse_ruff_count("Found 11019 errors.\n[*] 9329 fixable") == 11019
    assert ratchet.parse_ruff_count("Found 1 error.\n") == 1
    assert ratchet.parse_ruff_count("All checks passed!\n") == 0
    assert ratchet.parse_ruff_count("garbage") is None


def test_parse_mypy_count():
    assert (
        ratchet.parse_mypy_count("Found 1132 errors in 249 files (checked 946 source files)")
        == 1132
    )
    assert ratchet.parse_mypy_count("Found 1 error in 1 file") == 1
    assert ratchet.parse_mypy_count("Success: no issues found in 100 source files") == 0
    assert ratchet.parse_mypy_count("garbage") is None


def test_baseline_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(ratchet, "BASELINE_DIR", tmp_path)
    assert ratchet.read_baseline("ruff") is None
    ratchet.write_baseline("ruff", 42)
    assert ratchet.read_baseline("ruff") == 42
    (tmp_path / "mypy_baseline.txt").write_text("not-a-number", encoding="utf-8")
    assert ratchet.read_baseline("mypy") is None


def test_ratchet_fails_only_on_regression(tmp_path, monkeypatch):
    monkeypatch.setattr(ratchet, "BASELINE_DIR", tmp_path)
    ratchet.write_baseline("ruff", 100)

    monkeypatch.setattr(ratchet, "run_tool", lambda tool: (100, "ok"))
    assert ratchet.check_tool("ruff") is True  # equal counts pass

    monkeypatch.setattr(ratchet, "run_tool", lambda tool: (99, "ok"))
    assert ratchet.check_tool("ruff") is True  # improvement passes

    monkeypatch.setattr(ratchet, "run_tool", lambda tool: (101, "ok"))
    assert ratchet.check_tool("ruff") is False  # regression fails


def test_unparseable_output_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(ratchet, "BASELINE_DIR", tmp_path)
    ratchet.write_baseline("mypy", 10)
    monkeypatch.setattr(ratchet, "run_tool", lambda tool: (None, "weird"))
    assert ratchet.check_tool("mypy") is False


def test_update_baseline_rewrites(tmp_path, monkeypatch):
    monkeypatch.setattr(ratchet, "BASELINE_DIR", tmp_path)
    monkeypatch.setattr(ratchet, "run_tool", lambda tool: (77, "ok"))
    assert ratchet.check_tool("ruff", update_baseline=True) is True
    assert ratchet.read_baseline("ruff") == 77
