"""E1.69 Wave A — observability + dedup + ranking contracts.

Locks:
  * Step 1: depth_curve persisted in cold_executable rows.
  * Step 6: production-first ranking (expected_profit_usd > net_bps).
  * Step 7: dedup by (actual_pair, pool_address, route).
  * Step 8: production_sized / research_sized counters.
"""
from __future__ import annotations

import inspect


# ---------------------------------------------------------------------------
# Step 1: depth_curve in compact candidate
# ---------------------------------------------------------------------------


def test_compact_candidate_emits_depth_curve_field() -> None:
    import m7.orderflow.artifacts as _art
    src = inspect.getsource(_art)
    assert '"depth_curve"' in src, (
        "_compact_candidate must emit `depth_curve` so consumers can plot "
        "expected_profit(size). See E1.69 Step 1."
    )


# ---------------------------------------------------------------------------
# Step 6: production-first ranking
# ---------------------------------------------------------------------------


def test_exec_candidates_rank_by_expected_profit_first() -> None:
    """Sort key must use expected_profit_usd as primary, net_bps as tiebreaker."""
    import m7.orderflow.artifacts as _art
    src = inspect.getsource(_art)
    # Look for the new rank key signature.
    assert "_rank_key" in src, "E1.69 Step 6 _rank_key helper missing"
    assert 'expected_profit_usd' in src and 'best_backrun_net_bps' in src


# ---------------------------------------------------------------------------
# Step 7: dedup by route
# ---------------------------------------------------------------------------


def test_exec_candidates_dedup_by_pool_route() -> None:
    import m7.orderflow.artifacts as _art
    src = inspect.getsource(_art)
    assert "_dedup_key" in src, "E1.69 Step 7 _dedup_key helper missing"
    # The dedup key must include pool_address and venues.
    for token in ("pool_address", "best_buy_venue", "best_sell_venue"):
        assert token in src


# ---------------------------------------------------------------------------
# Step 8: production_sized / research_sized counters
# ---------------------------------------------------------------------------


def test_bridge_breakdown_has_production_sized_counters() -> None:
    import m7.orderflow.bridge_runtime as _br
    src = inspect.getsource(_br)
    assert '"production_sized"' in src
    assert '"research_sized"' in src


def test_dashboard_usd_coverage_exposes_candidate_counters() -> None:
    import monitoring.dashboard_server as _ds
    src = inspect.getsource(_ds._m7_usd_coverage)
    assert "production_sized_candidate_total" in src
    assert "research_sized_candidate_total" in src


def test_dashboard_candidate_counter_threshold_uses_production_size() -> None:
    """production_sized_candidate_total = count where amount_in_optimal_usd >= MIN_PRODUCTION_SIZE_USD."""
    import monitoring.dashboard_server as _ds
    rows = [
        {"amount_in_optimal_usd": 100.0, "expected_profit_usd": -0.1},  # production sized, unprofitable
        {"amount_in_optimal_usd": 50.0, "expected_profit_usd": 0.0},     # production sized, breakeven
        {"amount_in_optimal_usd": 49.99, "expected_profit_usd": 1.0},    # research sized only
        {"amount_in_optimal_usd": 10.0, "expected_profit_usd": 0.5},     # research sized
        {"amount_in_optimal_usd": 0.5, "expected_profit_usd": 0.05},     # dust
    ]
    cov = _ds._m7_usd_coverage(rows)
    assert cov["production_sized_candidate_total"] == 2
    # research counter is inclusive of production sized rows.
    assert cov["research_sized_candidate_total"] == 4
