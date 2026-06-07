"""Hot-path WS health metrics for soak acceptance."""
from __future__ import annotations

import time

from m8.discovery.hot_path_ws import compute_ws_health_status
from m8.runtime.ws_listener import WSListenerStats


def test_ws_health_ok_with_events():
    stats = WSListenerStats(log_events_emitted=5, last_event_seen_ts=time.time())
    assert (
        compute_ws_health_status(
            stats=stats,
            run_started_ts=time.time() - 60,
            now_ts=time.time(),
            hot_path_events_seen=3,
        )
        == "OK"
    )


def test_ws_health_ok_reconnected():
    stats = WSListenerStats(
        disconnects=1,
        reconnect_attempts=1,
        log_events_emitted=2,
        last_event_seen_ts=time.time(),
    )
    assert (
        compute_ws_health_status(
            stats=stats,
            run_started_ts=time.time() - 600,
            now_ts=time.time(),
            hot_path_events_seen=2,
        )
        == "OK_RECONNECTED"
    )


def test_ws_health_dead_no_events_after_disconnect():
    stats = WSListenerStats(disconnects=2, reconnect_attempts=1, log_events_emitted=0)
    now = time.time()
    assert (
        compute_ws_health_status(
            stats=stats,
            run_started_ts=now - 600,
            now_ts=now,
            hot_path_events_seen=0,
        )
        == "DEAD_NO_EVENTS_AFTER_DISCONNECT"
    )
