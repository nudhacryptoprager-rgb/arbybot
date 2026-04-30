"""E1.42 Iter 3 — derived rate_metrics block in hot rollup.

Tests the math directly without invoking the full rollup pipeline,
since computing the block requires a stable rollup dict but no
external dependencies.
"""

from __future__ import annotations

import json

from m7.orderflow.hot_runtime_artifacts import _compute_rate_metrics


def test_active_session_rates() -> None:
    rollup = {
        "session": {
            "session_elapsed_minutes": 60.0,
            "session_windows_seen": 100,
            "rate_baseline": {
                "roundtrip_attempted_total": 0,
                "roundtrip_profitable_total": 0,
                "windows_events_without_fast_score_total": 0,
            },
        },
        "roundtrip_attempted_total": 20,
        "roundtrip_profitable_total": 1,
        "windows_events_without_fast_score_total": 5,
    }
    rm = _compute_rate_metrics(rollup)
    assert rm["roundtrip_attempt_rate_per_hour"] == 20.0
    assert rm["profitable_event_rate_per_hour"] == 1.0
    assert rm["scoring_blackhole_rate"] == 0.05
    assert rm["session_elapsed_minutes"] == 60.0
    assert rm["session_windows_seen"] == 100
    assert rm["roundtrip_attempted_delta"] == 20
    assert rm["rate_basis"] == "current_worker_session_delta"


def test_zero_elapsed_yields_none() -> None:
    rollup = {
        "session": {"session_elapsed_minutes": 0, "session_windows_seen": 0},
        "roundtrip_attempted_total": 0,
        "roundtrip_profitable_total": 0,
        "windows_events_without_fast_score_total": 0,
    }
    rm = _compute_rate_metrics(rollup)
    assert rm["roundtrip_attempt_rate_per_hour"] is None
    assert rm["profitable_event_rate_per_hour"] is None
    assert rm["scoring_blackhole_rate"] is None


def test_market_quiet_window() -> None:
    """30 min, 100 windows, 0 events scored, 0 attempts → all rates 0."""
    rollup = {
        "session": {
            "session_elapsed_minutes": 30.0,
            "session_windows_seen": 100,
            "rate_baseline": {
                "roundtrip_attempted_total": 0,
                "roundtrip_profitable_total": 0,
                "windows_events_without_fast_score_total": 0,
            },
        },
        "roundtrip_attempted_total": 0,
        "roundtrip_profitable_total": 0,
        "windows_events_without_fast_score_total": 100,
    }
    rm = _compute_rate_metrics(rollup)
    assert rm["roundtrip_attempt_rate_per_hour"] == 0.0
    assert rm["profitable_event_rate_per_hour"] == 0.0
    assert rm["scoring_blackhole_rate"] == 1.0


def test_blackhole_partial() -> None:
    rollup = {
        "session": {
            "session_elapsed_minutes": 30.0,
            "session_windows_seen": 200,
            "rate_baseline": {
                "roundtrip_attempted_total": 0,
                "roundtrip_profitable_total": 0,
                "windows_events_without_fast_score_total": 0,
            },
        },
        "roundtrip_attempted_total": 5,
        "roundtrip_profitable_total": 0,
        "windows_events_without_fast_score_total": 50,
    }
    rm = _compute_rate_metrics(rollup)
    assert rm["roundtrip_attempt_rate_per_hour"] == 10.0  # 5 in 30 min = 10/hr
    assert rm["scoring_blackhole_rate"] == 0.25


def test_rates_subtract_cumulative_baseline_after_worker_restart() -> None:
    """Historical totals must not be divided by a tiny restarted session."""
    rollup = {
        "session": {
            "session_elapsed_minutes": 0.017,
            "session_windows_seen": 1,
            "rate_baseline": {
                "roundtrip_attempted_total": 7,
                "roundtrip_profitable_total": 0,
                "windows_events_without_fast_score_total": 25,
            },
        },
        "roundtrip_attempted_total": 7,
        "roundtrip_profitable_total": 0,
        "windows_events_without_fast_score_total": 26,
    }
    rm = _compute_rate_metrics(rollup)
    assert rm["roundtrip_attempt_rate_per_hour"] == 0.0
    assert rm["profitable_event_rate_per_hour"] == 0.0
    assert rm["scoring_blackhole_rate"] == 1.0
    assert rm["roundtrip_attempted_delta"] == 0
    assert rm["scoring_blackhole_windows_delta"] == 1


def test_production_path_writes_rate_metrics_key() -> None:
    """Smoke test that production code path includes the new key."""
    import inspect
    from m7.orderflow import hot_runtime_artifacts

    src = inspect.getsource(hot_runtime_artifacts)
    assert "rate_metrics" in src
    assert "profitable_event_rate_per_hour" in src
    assert "roundtrip_attempt_rate_per_hour" in src
    assert "scoring_blackhole_rate" in src


def test_shutdown_flush_refreshes_rate_metrics_shape(tmp_path, monkeypatch) -> None:
    """Quiet shutdown writes must not leave the pre-E1.43 rate block stuck."""
    from m7.orderflow import hot_runtime_artifacts

    rollup_path = tmp_path / "m7_hot_rollup_latest.json"
    rollup_path.write_text(
        json.dumps(
            {
                "chain": "base",
                "session": {
                    "session_elapsed_minutes": 0.017,
                    "session_windows_seen": 1,
                },
                "roundtrip_attempted_total": 7,
                "roundtrip_profitable_total": 0,
                "windows_events_without_fast_score_total": 26,
                "rate_metrics": {
                    "roundtrip_attempt_rate_per_hour": 24705.8824,
                    "scoring_blackhole_rate": 26.0,
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        hot_runtime_artifacts._rio, "_HOT_ROLLUP_PATH", str(rollup_path)
    )

    hot_runtime_artifacts.flush_rollup_shutdown(chain="base", is_supervisor_exit=True)

    refreshed = json.loads(rollup_path.read_text(encoding="utf-8"))
    rm = refreshed["rate_metrics"]
    assert rm["rate_basis"] == "current_worker_session_delta"
    assert rm["roundtrip_attempted_delta"] == 0
    assert rm["roundtrip_attempt_rate_per_hour"] == 0.0
    assert "rate_baseline" in refreshed["session"]
    assert refreshed["supervisor_end_utc"] == refreshed["shutdown_flush_at"]


def test_mark_supervisor_end_refreshes_disc_sibling_rollup(tmp_path, monkeypatch) -> None:
    """E1.45: mark_supervisor_end refreshes BOTH PROD and DISC rollups.

    Reviewer issue #7 / fix-step #6: DISC rollup must land with the
    current rate_metrics schema (rate_basis + delta keys) at supervisor
    exit, not only when m7_hot_discovery completes a cycle in-process.
    """
    from m7.orderflow import hot_runtime_artifacts as hra

    prod_path = tmp_path / "m7_hot_rollup_latest.json"
    disc_path = tmp_path / "m7_hot_rollup_latest_discovery.json"

    stale_block = {
        "chain": "base",
        "session": {
            "session_elapsed_minutes": 0.017,
            "session_windows_seen": 1,
        },
        "roundtrip_attempted_total": 9,
        "roundtrip_profitable_total": 0,
        "rate_metrics": {
            "roundtrip_attempt_rate_per_hour": 31764.7,
            "scoring_blackhole_rate": 9.0,
        },
    }
    prod_path.write_text(json.dumps(stale_block), encoding="utf-8")
    disc_path.write_text(json.dumps(stale_block), encoding="utf-8")

    monkeypatch.setattr(hra._rio, "_HOT_ROLLUP_PATH", str(prod_path))

    hra.mark_supervisor_end(chain="base")

    for path in (prod_path, disc_path):
        refreshed = json.loads(path.read_text(encoding="utf-8"))
        rm = refreshed["rate_metrics"]
        assert rm["rate_basis"] == "current_worker_session_delta", path
        assert rm["roundtrip_attempted_delta"] == 0, path
        assert rm["roundtrip_attempt_rate_per_hour"] == 0.0, path
        assert refreshed["supervisor_end_utc"] == refreshed["shutdown_flush_at"]


def test_clean_child_exit_increments_rollup_counter(tmp_path, monkeypatch) -> None:
    """E1.46 reviewer fix #3: per-child clean exit bumps clean_child_exits_total."""
    from m7.orderflow import hot_runtime_artifacts as hra

    rollup_path = tmp_path / "m7_hot_rollup_latest.json"
    rollup_path.write_text(
        json.dumps({"chain": "base", "session": {"session_windows_seen": 1}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(hra._rio, "_HOT_ROLLUP_PATH", str(rollup_path))

    # Two clean child exits (is_supervisor_exit=False).
    hra.flush_rollup_shutdown(chain="base", is_supervisor_exit=False)
    hra.flush_rollup_shutdown(chain="base", is_supervisor_exit=False)
    refreshed = json.loads(rollup_path.read_text(encoding="utf-8"))
    assert refreshed.get("clean_child_exits_total") == 2
    assert refreshed.get("last_clean_child_exit_at")
    # supervisor_end_utc must NOT be stamped on a non-supervisor flush.
    assert refreshed.get("supervisor_end_utc") in (None, "")

    # Supervisor exit must NOT increment clean_child_exits_total.
    hra.flush_rollup_shutdown(chain="base", is_supervisor_exit=True)
    refreshed = json.loads(rollup_path.read_text(encoding="utf-8"))
    assert refreshed.get("clean_child_exits_total") == 2
    assert refreshed.get("supervisor_end_utc")
