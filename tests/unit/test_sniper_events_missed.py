"""Tests for events_potentially_missed estimator (todo_RPC_blockers Phase 2)."""
from monitoring.sniper_funnel import (
    FunnelTracker,
    _estimate_events_potentially_missed,
)


def test_estimate_zero_when_no_errors():
    assert _estimate_events_potentially_missed(
        polls_ok={"uniswap_v3": 100}, raw_logs={"uniswap_v3": 50}, errors={},
    ) == 0


def test_estimate_zero_when_no_polls_ok():
    """Cannot estimate if zero successful polls."""
    assert _estimate_events_potentially_missed(
        polls_ok={}, raw_logs={}, errors={"uniswap_v3": 10},
    ) == 0


def test_estimate_proportional():
    # 100 successful polls produced 200 logs → 2 logs/poll average.
    # 10 errors → ~20 missed.
    assert _estimate_events_potentially_missed(
        polls_ok={"uniswap_v3": 100},
        raw_logs={"uniswap_v3": 200},
        errors={"uniswap_v3": 10},
    ) == 20


def test_estimate_multi_dex():
    # uniswap_v3: 50 polls × 4 logs/poll * 5 errors = 20
    # aerodrome: 200 polls × 1 log/poll * 10 errors = 10
    result = _estimate_events_potentially_missed(
        polls_ok={"uniswap_v3": 50, "aerodrome": 200},
        raw_logs={"uniswap_v3": 200, "aerodrome": 200},
        errors={"uniswap_v3": 5, "aerodrome": 10},
    )
    assert result == 30


def test_funnel_snapshot_includes_events_potentially_missed():
    f = FunnelTracker()
    f.inc_dex("uniswap_v3", "polls_ok", 100)
    f.inc_dex("uniswap_v3", "raw_logs", 200)
    f.inc_dex("uniswap_v3", "error", 5)
    snap = f.snapshot()
    assert "events_potentially_missed" in snap
    assert snap["events_potentially_missed"] == 10  # 5 errors × (200/100)


def test_funnel_snapshot_empty_state_returns_zero():
    f = FunnelTracker()
    snap = f.snapshot()
    assert snap.get("events_potentially_missed", 0) == 0
