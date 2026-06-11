"""Unit tests for iterative depth capacity probe."""
from __future__ import annotations

from m9.graph_arb.depth_capacity_probe import (
    DEPTH_PROBE_LOWER_BOUND_AT_MAX,
    DEPTH_PROBE_MEASURED_CAPACITY,
    DEPTH_PROBE_TOO_THIN,
    PROBE_LADDER_USD,
    capacity_usd_at_threshold,
    finalize_marginal_depth,
    merge_ladder_results,
    v2_analytical_depth_usd,
)


def test_capacity_interpolates_when_impact_high():
    assert capacity_usd_at_threshold(100.0, 0.20) == 50.0


def test_finalize_measured_capacity():
    res = finalize_marginal_depth(0.25, 1000.0, at_max_ladder_rung=False)
    assert res["depth_probe_status"] == DEPTH_PROBE_MEASURED_CAPACITY
    assert res["effective_depth_usd"] == 400.0


def test_finalize_lower_bound_at_max_rung():
    res = finalize_marginal_depth(0.0, 50_000.0, at_max_ladder_rung=True)
    assert res["depth_probe_status"] == DEPTH_PROBE_LOWER_BOUND_AT_MAX
    assert res["effective_depth_usd"] == 50_000.0


def test_finalize_toxic():
    res = finalize_marginal_depth(0.60, 100.0, at_max_ladder_rung=True)
    assert res["depth_probe_status"] == DEPTH_PROBE_TOO_THIN
    assert res["depth_reject_reason"] == "TOXIC_PRICE_IMPACT"


def test_merge_ladder_prefers_first_measured_rung():
    rungs = [
        finalize_marginal_depth(0.0, 100.0, at_max_ladder_rung=False),
        finalize_marginal_depth(0.15, 500.0, at_max_ladder_rung=False),
    ]
    merged = merge_ladder_results(rungs)
    assert merged["depth_probe_status"] == DEPTH_PROBE_MEASURED_CAPACITY
    assert merged["effective_depth_usd"] < 500.0


def test_merge_ladder_max_when_no_impact():
    rungs = [finalize_marginal_depth(0.0, PROBE_LADDER_USD[-1], at_max_ladder_rung=True)]
    merged = merge_ladder_results(rungs)
    assert merged["effective_depth_usd"] == PROBE_LADDER_USD[-1]


def test_v2_analytical_depth_positive():
    depth = v2_analytical_depth_usd(
        reserve_in_raw=10**21,
        dec_in=18,
        price_in_usd=1.0,
        fee_bps=30,
    )
    assert depth > 100.0
