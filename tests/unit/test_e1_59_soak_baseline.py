"""E1.59 step #1: soak baseline snapshot on supervisor start.

Verifies that ``mark_supervisor_start``:
  * clears stale ``supervisor_end_utc`` from a previous run,
  * snapshots reviewer-relevant counters under ``soak_baseline.counters``,
  * stamps a fresh ``soak_baseline_session_id`` and timestamps,
  * writes both PROD and DISC sibling rollups.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from m7.orderflow import runtime_io as _rio
from m7.orderflow.hot_runtime_artifacts import (
    _SOAK_BASELINE_KEYS,
    mark_supervisor_start,
)


@pytest.fixture
def temp_rollups(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    prod = tmp_path / "m7_hot_rollup_latest.json"
    disc = tmp_path / "m7_hot_rollup_latest_discovery.json"
    monkeypatch.setattr(_rio, "_HOT_ROLLUP_PATH", str(prod))
    return prod, disc


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_mark_start_clears_stale_supervisor_end(temp_rollups):
    prod, _ = temp_rollups
    _write_json(
        prod,
        {
            "supervisor_end_utc": "2026-04-04T10:00:00Z",
            "submit_ready_total": 7,
        },
    )
    mark_supervisor_start(chain="base")
    out = _read_json(prod)
    assert "supervisor_end_utc" not in out
    assert "supervisor_start_utc" in out
    assert "soak_baseline_at" in out


def test_mark_start_snapshots_counters(temp_rollups):
    prod, _ = temp_rollups
    snap = {k: 11 + i for i, k in enumerate(_SOAK_BASELINE_KEYS)}
    snap["chain"] = "base"
    _write_json(prod, snap)
    mark_supervisor_start(chain="base")
    out = _read_json(prod)
    baseline = out["soak_baseline"]
    assert "counters" in baseline
    for i, k in enumerate(_SOAK_BASELINE_KEYS):
        assert baseline["counters"][k] == 11 + i
    assert "soak_baseline_session_id" in baseline
    assert len(baseline["soak_baseline_session_id"]) >= 8


def test_mark_start_session_id_is_fresh(temp_rollups):
    prod, _ = temp_rollups
    _write_json(prod, {"chain": "base"})
    mark_supervisor_start(chain="base")
    s1 = _read_json(prod)["soak_baseline"]["soak_baseline_session_id"]
    mark_supervisor_start(chain="base")
    s2 = _read_json(prod)["soak_baseline"]["soak_baseline_session_id"]
    assert s1 != s2


def test_mark_start_writes_both_lanes(temp_rollups):
    prod, disc = temp_rollups
    _write_json(prod, {"chain": "base", "submit_ready_total": 3})
    _write_json(disc, {"chain": "base", "submit_ready_total": 5})
    mark_supervisor_start(chain="base")
    p = _read_json(prod)
    d = _read_json(disc)
    assert p["soak_baseline"]["counters"]["submit_ready_total"] == 3
    assert d["soak_baseline"]["counters"]["submit_ready_total"] == 5
    assert p["soak_baseline"]["soak_baseline_session_id"] != d["soak_baseline"]["soak_baseline_session_id"]


def test_mark_start_creates_disc_if_missing(temp_rollups):
    prod, disc = temp_rollups
    _write_json(prod, {"chain": "base"})
    assert not disc.exists()
    mark_supervisor_start(chain="base")
    assert disc.exists()
    out = _read_json(disc)
    assert out.get("chain") == "base"
    assert "soak_baseline" in out


def test_mark_start_preserves_existing_counters(temp_rollups):
    prod, _ = temp_rollups
    _write_json(
        prod,
        {
            "chain": "base",
            "submit_ready_total": 9,
            "roundtrip_profitable_total": 4,
            "some_other_field": "keep_me",
        },
    )
    mark_supervisor_start(chain="base")
    out = _read_json(prod)
    assert out["submit_ready_total"] == 9
    assert out["roundtrip_profitable_total"] == 4
    assert out["some_other_field"] == "keep_me"
