"""Unit tests for iterative depth capacity probe."""
from __future__ import annotations

from m9.graph_arb.depth_capacity_probe import (
    DEPTH_PROBE_ANALYTICAL_SUSPECT,
    DEPTH_PROBE_LOWER_BOUND_AT_MAX,
    DEPTH_PROBE_MEASURED_CAPACITY,
    DEPTH_PROBE_TOO_THIN,
    PROBE_LADDER_USD,
    capacity_usd_at_threshold,
    finalize_marginal_depth,
    mark_analytical_depth_suspect,
    merge_depth_with_analytical,
    merge_ladder_results,
    v2_analytical_depth_usd,
    v3_liquidity_depth_lower_bound_usd,
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


def test_v3_insane_analytical_depth_marked_suspect():
    merged = merge_depth_with_analytical(
        {"effective_depth_usd": 100.0, "depth_probe_status": DEPTH_PROBE_MEASURED_CAPACITY},
        31_000_000_000_000.0,
        analytical_method="v3_liquidity_bound",
    )
    assert merged["depth_probe_status"] == DEPTH_PROBE_ANALYTICAL_SUSPECT
    assert merged["effective_depth_usd"] is None
    assert merged["depth_analytical_suspect_usd"] == 31_000_000_000_000.0


def test_mark_analytical_depth_suspect_on_probe_row():
    flagged = mark_analytical_depth_suspect(
        {"effective_depth_usd": 20_000_000.0, "depth_probe_status": DEPTH_PROBE_MEASURED_CAPACITY}
    )
    assert flagged["depth_probe_status"] == DEPTH_PROBE_ANALYTICAL_SUSPECT
    assert flagged["effective_depth_usd"] is None


def test_v3_liquidity_bound_sane_for_typical_pool():
    depth = v3_liquidity_depth_lower_bound_usd(
        liquidity_raw=10**18,
        sqrt_price_x96=2**96,
        dec_in=18,
        price_in_usd=3000.0,
    )
    assert depth is not None
    assert depth < 10_000_000.0
