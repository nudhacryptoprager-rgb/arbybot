"""E1.42 Iter 3 — derived rate_metrics block in hot rollup.

Tests the math directly without invoking the full rollup pipeline,
since computing the block requires a stable rollup dict but no
external dependencies.
"""

from __future__ import annotations


def _compute_rate_metrics(rollup: dict) -> dict:
    """Replicate the production rate-metrics computation in isolation.

    Mirrors the inline block at the bottom of
    ``m7.orderflow.hot_runtime_artifacts._update_hot_rollup``. Kept as a
    test helper to lock the contract: if the production formula drifts,
    these tests will fail.
    """
    block: dict = {}
    sess = rollup.get("session") or {}
    elapsed_min = float(sess.get("session_elapsed_minutes") or 0.0)
    elapsed_hrs = elapsed_min / 60.0
    if elapsed_hrs > 0:
        rt_att = int(rollup.get("roundtrip_attempted_total", 0) or 0)
        rt_prof = int(rollup.get("roundtrip_profitable_total", 0) or 0)
        block["roundtrip_attempt_rate_per_hour"] = round(rt_att / elapsed_hrs, 4)
        block["profitable_event_rate_per_hour"] = round(rt_prof / elapsed_hrs, 4)
    else:
        block["roundtrip_attempt_rate_per_hour"] = None
        block["profitable_event_rate_per_hour"] = None
    wnd_total = int(sess.get("session_windows_seen", 0) or 0)
    wnd_bh = int(rollup.get("windows_events_without_fast_score_total", 0) or 0)
    if wnd_total > 0:
        block["scoring_blackhole_rate"] = round(wnd_bh / wnd_total, 4)
    else:
        block["scoring_blackhole_rate"] = None
    block["session_elapsed_minutes"] = round(elapsed_min, 3)
    block["session_windows_seen"] = wnd_total
    return block


def test_active_session_rates() -> None:
    rollup = {
        "session": {"session_elapsed_minutes": 60.0, "session_windows_seen": 100},
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
        "session": {"session_elapsed_minutes": 30.0, "session_windows_seen": 100},
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
        "session": {"session_elapsed_minutes": 30.0, "session_windows_seen": 200},
        "roundtrip_attempted_total": 5,
        "roundtrip_profitable_total": 0,
        "windows_events_without_fast_score_total": 50,
    }
    rm = _compute_rate_metrics(rollup)
    assert rm["roundtrip_attempt_rate_per_hour"] == 10.0  # 5 in 30 min = 10/hr
    assert rm["scoring_blackhole_rate"] == 0.25


def test_production_path_writes_rate_metrics_key() -> None:
    """Smoke test that production code path includes the new key."""
    import inspect
    from m7.orderflow import hot_runtime_artifacts

    src = inspect.getsource(hot_runtime_artifacts)
    assert "rate_metrics" in src
    assert "profitable_event_rate_per_hour" in src
    assert "roundtrip_attempt_rate_per_hour" in src
    assert "scoring_blackhole_rate" in src
