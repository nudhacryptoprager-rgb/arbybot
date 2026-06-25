"""Unit tests for production refresh runtime gates."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.m9_production_refresh_gates import (
    gate_capacity_shadow,
    gate_fresh_delta_subset,
    gate_m83_acceptance,
    gate_negative_cache_stats,
)


def test_gate_fresh_delta_subset_ok(tmp_path: Path):
    path = tmp_path / "subset.json"
    path.write_text(
        json.dumps(
            {
                "tokens": ["0x" + "a" * 40],
                "lane_meta": {
                    "fresh_delta_count": 2,
                    "wide_recall_count": 1,
                    "audit_excluded": True,
                },
            }
        ),
        encoding="utf-8",
    )
    assert gate_fresh_delta_subset(path) == 0


def test_gate_m83_acceptance_blocks_when_not_reached(tmp_path: Path):
    path = tmp_path / "m83.json"
    path.write_text(json.dumps({"goal_status": "BLOCKED"}), encoding="utf-8")
    assert gate_m83_acceptance(path, require_reached=True) == 1


def test_gate_capacity_shadow_blocked(tmp_path: Path):
    path = tmp_path / "cap.json"
    path.write_text(
        json.dumps(
            {
                "cycles_at_production_floor": 0,
                "cycles_by_profile": {
                    "production_conservative": {"cycles_at_floor": 0},
                },
            }
        ),
        encoding="utf-8",
    )
    assert gate_capacity_shadow(path) == 2


def test_gate_negative_cache_stats(tmp_path: Path):
    path = tmp_path / "reg.json"
    path.write_text(
        json.dumps(
            {
                "negative_cache": {
                    "entries": {"k": {"error_code": "NON_ERC20"}},
                    "stats": {"entry_count": 1, "hits": 2, "bypass_count": 1},
                }
            }
        ),
        encoding="utf-8",
    )
    assert gate_negative_cache_stats(path) == 0
