"""E1.51 reviewer surface: pool_price_state deltas + sink-starved guard.

Locks the contract that ``reviewer_soak_summary.summarise_lane`` reads
the nested ``pool_price_state`` block from the rolling hot rollup,
emits ``pool_price_state_*_total`` deltas, and FAILs the lane with
``POOL_PRICE_STATE_SINK_STARVED`` when events flowed but the registry
got zero decodes.
"""
from __future__ import annotations

import io
import contextlib

import pytest


def _baseline_min() -> dict:
    """Minimal baseline rollup with all tracked scalars at zero."""
    return {
        "session_id": "BASE",
        "last_updated": "2026-05-01T09:00:00Z",
        "supervisor_end_utc": "2026-05-01T09:00:00Z",
        "events_seen_total": 0,
        "fast_path_scored_total": 0,
        "sim_attempted_total": 0,
        "sim_passed_total": 0,
        "sim_success_total": 0,
        "sim_revert_total": 0,
        "submit_ready_total": 0,
        "roundtrip_attempted_total": 0,
        "roundtrip_success_total": 0,
        "roundtrip_profitable_total": 0,
        "profit_guard_passed_total": 0,
        "windows_seen": 0,
        "strict_provider_breaches_total": 0,
        "clean_child_exits_total": 0,
        "periodic_heartbeats_total": 0,
        "pool_price_state": {
            "updates_total": 0,
            "v2_updates_total": 0,
            "decode_errors_total": 0,
            "v2_decode_errors_total": 0,
            "stale_drops_total": 0,
            "v2_stale_drops_total": 0,
            "pools_tracked": 0,
        },
    }


def _current_with(**overrides) -> dict:
    cur = _baseline_min()
    cur["session_id"] = "CUR"
    cur["last_updated"] = "2026-05-01T10:00:00Z"
    cur["supervisor_end_utc"] = "2026-05-01T10:00:00Z"
    pps_overrides = overrides.pop("pool_price_state", {})
    cur.update(overrides)
    cur["pool_price_state"] = {**cur["pool_price_state"], **pps_overrides}
    return cur


def _run_summarise(baseline: dict, current: dict) -> tuple:
    from scripts.reviewer_soak_summary import summarise_lane

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        ok, reason = summarise_lane("PROD", baseline, current)
    return ok, reason, buf.getvalue()


def test_pool_price_state_deltas_emitted():
    """Reviewer must print pool_price_state_updates_total delta."""
    base = _baseline_min()
    cur = _current_with(
        events_seen_total=10,
        fast_path_scored_total=5,
        sim_attempted_total=3,
        sim_passed_total=2,
        clean_child_exits_total=1,
        pool_price_state={
            "updates_total": 7,
            "v2_updates_total": 2,
            "pools_tracked": 4,
        },
    )
    ok, reason, output = _run_summarise(base, cur)
    assert "pool_price_state.updates_total" in output
    assert "+7" in output
    assert "pool_price_state.v2_updates_total" in output
    assert "+2" in output
    assert "pool_price_state.pools_tracked" in output


def test_sink_starved_guard_triggers():
    """events flowed but updates_delta==0 must surface POOL_PRICE_STATE_SINK_STARVED."""
    base = _baseline_min()
    cur = _current_with(
        events_seen_total=20,
        fast_path_scored_total=5,
        sim_attempted_total=2,
        sim_passed_total=1,
        clean_child_exits_total=1,
        periodic_heartbeats_total=5,
        pool_price_state={
            "updates_total": 0,
            "v2_updates_total": 0,
            "pools_tracked": 0,
        },
    )
    ok, reason, output = _run_summarise(base, cur)
    assert "POOL_PRICE_STATE_SINK_STARVED" in (reason or "") or \
        "POOL_PRICE_STATE_SINK_STARVED" in output


def test_sink_starved_quiet_ok_suppresses(monkeypatch):
    """ARBY_REVIEWER_QUIET_OK=1 must suppress the sink-starved guard."""
    monkeypatch.setenv("ARBY_REVIEWER_QUIET_OK", "1")
    base = _baseline_min()
    cur = _current_with(
        events_seen_total=20,
        fast_path_scored_total=5,
        clean_child_exits_total=1,
        pool_price_state={"updates_total": 0, "v2_updates_total": 0},
    )
    ok, reason, output = _run_summarise(base, cur)
    assert "POOL_PRICE_STATE_SINK_STARVED" not in (reason or "")


def test_sink_healthy_no_guard():
    """events flowed AND updates_delta>0 must NOT trigger the guard."""
    base = _baseline_min()
    cur = _current_with(
        events_seen_total=20,
        fast_path_scored_total=5,
        sim_attempted_total=3,
        sim_passed_total=2,
        clean_child_exits_total=1,
        periodic_heartbeats_total=5,
        pool_price_state={
            "updates_total": 12,
            "v2_updates_total": 1,
            "pools_tracked": 6,
        },
    )
    ok, reason, output = _run_summarise(base, cur)
    assert "POOL_PRICE_STATE_SINK_STARVED" not in (reason or "")
    assert "POOL_PRICE_STATE_SINK_STARVED" not in output


def test_no_pool_price_state_block_treated_as_zero():
    """Older baselines without the block must not crash; deltas default to 0."""
    base = _baseline_min()
    base.pop("pool_price_state", None)
    cur = _current_with(
        events_seen_total=5,
        clean_child_exits_total=1,
        pool_price_state={"updates_total": 3, "pools_tracked": 2},
    )
    ok, reason, output = _run_summarise(base, cur)
    assert "pool_price_state.updates_total" in output
    assert "+3" in output
