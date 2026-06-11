"""Depth telemetry classification tests."""
from __future__ import annotations

from m9.graph_arb.depth_telemetry import (
    DEPTH_STATUS_UNKNOWN,
    REJECT_OVERSIZED_VS_UNKNOWN_DEPTH_FALLBACK,
    depth_known_rate,
    oversized_reject_for_depth,
)


def test_depth_known_rate_zero_when_unset():
    routes = [{"pool_address": "0x" + "a" * 40}, {"pool_address": "0x" + "b" * 40}]
    assert depth_known_rate(routes) == 0.0


def test_depth_known_rate_counts_positive_depth():
    routes = [
        {"pool_address": "0x" + "a" * 40, "effective_depth_usd": 50.0},
        {"pool_address": "0x" + "b" * 40},
    ]
    assert depth_known_rate(routes) == 0.5


def test_oversized_unknown_when_depth_missing():
    status, reason = oversized_reject_for_depth(None, gross_bps=-900.0)
    assert reason == REJECT_OVERSIZED_VS_UNKNOWN_DEPTH_FALLBACK


def test_route_without_depth_is_unknown_status():
    from m9.graph_arb.depth_telemetry import classify_route_depth_status

    assert classify_route_depth_status({"pool_address": "0x" + "a" * 40}) == DEPTH_STATUS_UNKNOWN
