"""Unit tests for M8/M8.2 fresh_delta / wide_recall / audit lanes."""
from __future__ import annotations

import time

from m8.discovery.fresh_delta_lane import (
    REFRESH_LANE_AUDIT,
    REFRESH_LANE_FRESH_DELTA,
    REFRESH_LANE_WIDE_RECALL,
    apply_watchlist_lane_policy,
    build_radar_token_list,
    classify_refresh_lane,
)


def _entry(**kwargs):
    base = {
        "token_class": "fresh_long_tail",
        "first_seen_ts": time.time(),
        "last_scan_ts": 0.0,
        "second_pool_verified": False,
        "first_pool": "0x" + "a" * 40,
        "first_dex": "uniswap_v3",
    }
    base.update(kwargs)
    return base


def test_fresh_unresolved_1_to_2_is_fresh_delta_lane():
    now = time.time()
    lane = classify_refresh_lane(
        _entry(token_class="fresh_long_tail", first_seen_ts=now - 60),
        config={},
        now_ts=now,
    )
    assert lane == REFRESH_LANE_FRESH_DELTA


def test_stale_without_second_venue_moves_to_audit_lane():
    now = time.time()
    lane = classify_refresh_lane(
        _entry(
            token_class="unknown",
            first_seen_ts=now - 10 * 24 * 3600,
            last_scan_ts=now - 2 * 24 * 3600,
        ),
        config={},
        now_ts=now,
        audit_ttl_s=7 * 24 * 3600,
        stale_scan_ttl_s=24 * 3600,
    )
    assert lane == REFRESH_LANE_AUDIT


def test_build_radar_token_list_fresh_before_wide_recall():
    now = time.time()
    watchlist = {
        "tokens": {
            "0x" + "1" * 40: _entry(
                token_class="fresh_long_tail",
                first_seen_ts=now - 30,
            ),
            "0x" + "2" * 40: _entry(
                token_class="unknown",
                first_seen_ts=now - 5 * 24 * 3600,
                second_pool_verified=True,
            ),
        }
    }
    selected, meta = build_radar_token_list(
        watchlist,
        config={},
        max_tokens=2,
        fresh_first=True,
        now_ts=now,
    )
    assert meta["fresh_delta_count"] == 1
    assert meta["wide_recall_count"] == 1
    assert selected[0] == "0x" + "1" * 40
    assert apply_watchlist_lane_policy(watchlist, config={}, now_ts=now)[REFRESH_LANE_WIDE_RECALL] == 1
