# PATH: tests/unit/test_m9_capacity_cycle_diagnostic_provenance.py
"""Unit tests for capacity diagnostic provenance stamping (Patch 4).

Locks the contract that ``scripts/m9_capacity_cycle_diagnostic.py`` stamps
every emitted artifact with ``generated_at_utc`` so the M9 lane freshness
gate (Patch 3) does not surface a spurious ``CAPACITY_TIMESTAMP_MISSING``
blocker on a freshly generated artifact.

Both the normal (cycles present) and empty / no-graph paths must receive the
same provenance stamp.
"""
from __future__ import annotations

import re

from scripts.m9_capacity_cycle_diagnostic import stamp_capacity_provenance

_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


def _normal_report() -> dict:
    return {
        "schema_version": "m9_capacity_cycle_diagnostic.2",
        "inventory_path": "data/tmp/m9_bridge_inventory_graph_handoff_latest.json",
        "config_path": "config/exotic_base_anchor.yaml",
        "lane": "productive",
        "cycle_lengths": [2, 3, 4],
        "capacity_floors_usd": [25.0, 50.0, 100.0, 180.0],
        "active_economics_profile": "production_conservative",
        "economic_size_floor_usd": 180.0,
        "production_conservative_floor_usd": 180.0,
        "cycles_total": 3768,
        "cycles_with_all_legs_depth_known": 39,
        "cycles_by_usable_capacity_floor": {"25": 5, "50": 1, "100": 0, "180": 0},
        "cycles_by_profile": {
            "production_conservative": {"cycles_at_floor": 0},
            "diagnostic_near_econ": {"cycles_at_floor": 6},
        },
        "cycles_at_econ_floor": 5,
        "cycles_at_production_floor": 0,
        "blocker_hint": "NO_ECON_CAPACITY_CYCLES_AT_PRODUCTION_FLOOR",
        "shadow_gate": {"blocked": True, "reason": "ZERO_CYCLES_AT_FLOOR"},
        "top_bottleneck_legs": [],
    }


def _empty_report() -> dict:
    return {
        "schema_version": "m9_capacity_cycle_diagnostic.2",
        "inventory_path": "data/tmp/missing.json",
        "config_path": "config/exotic_base_anchor.yaml",
        "lane": "productive",
        "cycle_lengths": [2, 3, 4],
        "capacity_floors_usd": [25.0, 50.0, 100.0, 180.0],
        "active_economics_profile": "production_conservative",
        "economic_size_floor_usd": 180.0,
        "production_conservative_floor_usd": 180.0,
        "cycles_total": 0,
        "cycles_with_all_legs_depth_known": 0,
        "cycles_by_usable_capacity_floor": {"25": 0, "50": 0, "100": 0, "180": 0},
        "cycles_at_econ_floor": 0,
        "cycles_at_production_floor": 0,
        "blocker_hint": "NO_GRAPH_OR_NO_CYCLES",
    }


def test_normal_report_gets_iso_timestamp():
    report = stamp_capacity_provenance(_normal_report(), now_utc="2026-07-09T11:49:48Z")
    assert report["generated_at_utc"] == "2026-07-09T11:49:48Z"
    # No other keys removed; schema additive.
    assert report["cycles_total"] == 3768
    assert report["blocker_hint"] == "NO_ECON_CAPACITY_CYCLES_AT_PRODUCTION_FLOOR"


def test_empty_no_cycles_path_gets_iso_timestamp():
    report = stamp_capacity_provenance(_empty_report(), now_utc="2026-07-09T11:49:48Z")
    assert report["generated_at_utc"] == "2026-07-09T11:49:48Z"
    assert report["cycles_total"] == 0
    assert report["blocker_hint"] == "NO_GRAPH_OR_NO_CYCLES"


def test_default_now_stamp_matches_iso_format():
    report = stamp_capacity_provenance(_normal_report())
    ts = report["generated_at_utc"]
    assert isinstance(ts, str) and _ISO_RE.match(ts) is not None, (
        f"generated_at_utc must be ISO-8601 'YYYY-MM-DDTHH:MM:SSZ', got: {ts!r}"
    )


def test_stamp_is_idempotent_when_now_utc_passed():
    report = _normal_report()
    out1 = stamp_capacity_provenance(report, now_utc="2026-07-09T11:49:48Z")
    out2 = stamp_capacity_provenance(out1, now_utc="2026-07-09T11:49:48Z")
    assert out1 is out2
    assert out2["generated_at_utc"] == "2026-07-09T11:49:48Z"