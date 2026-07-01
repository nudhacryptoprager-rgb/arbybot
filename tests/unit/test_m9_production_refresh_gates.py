"""Unit tests for production refresh runtime gates."""
from __future__ import annotations

import json
from pathlib import Path

from scripts.m9_production_refresh_gates import (
    gate_capacity_shadow,
    gate_fresh_delta_subset,
    gate_m83_acceptance,
    gate_negative_cache_stats,
    gate_selection_verified_fresh,
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
                "cycles_total": 0,
                "cycles_at_production_floor": 0,
                "cycles_by_profile": {
                    "production_conservative": {"cycles_at_floor": 0},
                },
            }
        ),
        encoding="utf-8",
    )
    assert gate_capacity_shadow(path) == 2


def test_gate_narrow_shadow_blocks_non_target_universe(tmp_path: Path):
    from scripts.m9_production_refresh_gates import gate_narrow_shadow

    cap = tmp_path / "cap.json"
    bridge = tmp_path / "bridge.json"
    cap.write_text(
        json.dumps(
            {
                "cycles_total": 5,
                "cycles_by_profile": {
                    "diagnostic_near_econ": {"cycles_at_floor": 2},
                },
            }
        ),
        encoding="utf-8",
    )
    bridge.write_text(
        json.dumps(
            {
                "fresh_long_tail_quote_ready_tokens": 1,
                "active_routes": [
                    {"token_class": "known_major", "refresh_lane": "audit_lane"}
                ],
            }
        ),
        encoding="utf-8",
    )
    assert gate_narrow_shadow(cap, bridge) == 2


def test_gate_target_narrow_universe_blocks_without_fresh_quote_ready(tmp_path: Path):
    from scripts.m9_production_refresh_gates import gate_target_narrow_universe

    bridge = tmp_path / "bridge.json"
    bridge.write_text(
        json.dumps(
            {
                "active_routes": [],
                "fresh_long_tail_quote_ready_tokens": 0,
                "quote_ready_token_count": 0,
            }
        ),
        encoding="utf-8",
    )
    assert gate_target_narrow_universe(bridge) == 2


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


def test_gate_selection_verified_fresh_blocks_when_zero(tmp_path: Path):
    path = tmp_path / "recall.json"
    path.write_text(
        json.dumps(
            {
                "selection_verified_fresh_total": 0,
                "recall_verified_pool_exists_total": 2,
                "recall_run_id": "2026-06-30T08:11:43Z",
            }
        ),
        encoding="utf-8",
    )
    assert gate_selection_verified_fresh(path) == 2


def test_gate_selection_verified_fresh_passes_when_positive(tmp_path: Path):
    path = tmp_path / "recall.json"
    path.write_text(
        json.dumps({"selection_verified_fresh_total": 1, "recall_run_id": "run-1"}),
        encoding="utf-8",
    )
    assert gate_selection_verified_fresh(path) == 0
