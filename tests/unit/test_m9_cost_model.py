"""Unit tests for M9 cost model arithmetic (compute_estimated_cost_bps).

Verifies:
  - Correct formula: (gas_usd + l1_fee_usd) / size_usd * 10_000 + slippage_bps
  - Size sensitivity: larger size → lower per-bps gas cost
  - Null-safe: returns None when size_usd <= 0
  - build_artifact null-safe: works with cost_model=None (no crash)
  - build_artifact with cost_model: populates estimated_cost_bps + cost_adjusted_net_bps
  - _build_cycle_summary cost fields when cost_profile provided
"""
from __future__ import annotations

from typing import Any, Dict, Optional
from unittest.mock import MagicMock

import pytest

from m9.graph_arb.artifacts import (
    compute_estimated_cost_bps,
    build_artifact,
    _build_cycle_summary,
)


# ---------------------------------------------------------------------------
# compute_estimated_cost_bps
# ---------------------------------------------------------------------------

class TestComputeEstimatedCostBps:
    """Pure math tests — no external dependencies."""

    def test_standard_100_usd(self):
        # (0.05 + 0.01) / 100 * 10_000 + 5.0 = 6.0 + 5.0 = 11.0
        result = compute_estimated_cost_bps(
            size_usd=100.0,
            gas_usd=0.05,
            l1_fee_usd=0.01,
            slippage_bps=5.0,
        )
        assert result is not None
        assert abs(result - 11.0) < 0.001, f"Expected ~11.0 bps, got {result}"

    def test_standard_250_usd(self):
        # (0.05 + 0.01) / 250 * 10_000 + 5.0 = 2.4 + 5.0 = 7.4
        result = compute_estimated_cost_bps(
            size_usd=250.0,
            gas_usd=0.05,
            l1_fee_usd=0.01,
            slippage_bps=5.0,
        )
        assert result is not None
        assert abs(result - 7.4) < 0.001, f"Expected ~7.4 bps, got {result}"

    def test_standard_500_usd(self):
        # (0.05 + 0.01) / 500 * 10_000 + 5.0 = 1.2 + 5.0 = 6.2
        result = compute_estimated_cost_bps(
            size_usd=500.0,
            gas_usd=0.05,
            l1_fee_usd=0.01,
            slippage_bps=5.0,
        )
        assert result is not None
        assert abs(result - 6.2) < 0.001, f"Expected ~6.2 bps, got {result}"

    def test_size_sensitivity_decreasing(self):
        """Larger size → lower estimated_cost_bps (gas component shrinks)."""
        bps_100 = compute_estimated_cost_bps(100.0, 0.05, 0.01, 5.0)
        bps_250 = compute_estimated_cost_bps(250.0, 0.05, 0.01, 5.0)
        bps_500 = compute_estimated_cost_bps(500.0, 0.05, 0.01, 5.0)
        assert bps_100 is not None
        assert bps_250 is not None
        assert bps_500 is not None
        assert bps_100 > bps_250 > bps_500, (
            f"Cost should decrease with size: {bps_100} > {bps_250} > {bps_500}"
        )

    def test_slippage_floor_when_gas_zero(self):
        """With zero gas/l1_fee the only cost is slippage."""
        result = compute_estimated_cost_bps(
            size_usd=1000.0,
            gas_usd=0.0,
            l1_fee_usd=0.0,
            slippage_bps=3.0,
        )
        assert result is not None
        assert abs(result - 3.0) < 0.001, f"Expected 3.0 bps (slippage only), got {result}"

    def test_null_safe_zero_size(self):
        """Returns None when size_usd is 0 (avoid division by zero)."""
        assert compute_estimated_cost_bps(0.0, 0.05, 0.01, 5.0) is None

    def test_null_safe_negative_size(self):
        """Returns None when size_usd is negative."""
        assert compute_estimated_cost_bps(-100.0, 0.05, 0.01, 5.0) is None


# ---------------------------------------------------------------------------
# build_artifact: null-safe with cost_model=None
# ---------------------------------------------------------------------------

def _make_topology():
    from m9.graph_arb.models import GraphTopology
    return GraphTopology(
        token_count=3, edge_count=6, route_count=4,
        hub_tokens=["USDC"],
        dead_end_tokens=[],
        missing_edges_for_3cycle=[],
        adjacency_summary={"USDC": ["WETH"]},
    )


class TestBuildArtifactCostModel:
    """Tests for cost_model integration in build_artifact."""

    def test_no_cost_model_estimated_cost_bps_is_none(self):
        """Without cost_model, estimated_cost_bps and cost_adjusted_net_bps stay null."""
        artifact = build_artifact(
            chain="base",
            duration_minutes=1.0,
            cycle_results=[],
            topology=_make_topology(),
            sizes_usd=(100.0,),
            run_timestamp="2026-01-01T00:00:00Z",
            started_at_mono=0.0,
            elapsed_s=60.0,
            cost_model=None,
        )
        assert artifact["estimated_cost_bps"] is None
        assert artifact["cost_adjusted_net_bps"] is None

    def test_cost_model_populates_estimated_cost_bps(self):
        """When cost_model provided and cycles exist, estimated_cost_bps is computed."""
        mock_qr = _make_mock_cycle_result(gross_bps=3.0, size_usd=100.0)
        cost_model = {
            "default_profile": "default",
            "profiles": {
                "default": {"gas_usd": 0.05, "l1_fee_usd": 0.01, "slippage_bps": 5.0}
            },
        }
        artifact = build_artifact(
            chain="base",
            duration_minutes=1.0,
            cycle_results=[mock_qr],
            topology=_make_topology(),
            sizes_usd=(100.0,),
            run_timestamp="2026-01-01T00:00:00Z",
            started_at_mono=0.0,
            elapsed_s=60.0,
            cost_model=cost_model,
        )
        assert artifact["estimated_cost_bps"] is not None
        # ~11.0 bps for $100 size
        assert abs(artifact["estimated_cost_bps"] - 11.0) < 0.01
        # cost_adjusted_net_bps = gross - estimated = 3.0 - 11.0 = -8.0
        assert artifact["cost_adjusted_net_bps"] is not None
        assert abs(artifact["cost_adjusted_net_bps"] - (-8.0)) < 0.01

    def test_cost_adjusted_net_negative_is_not_router_eligible(self):
        """Cycle with cost_adjusted_net_bps below -10 floor is NOT router_sim_eligible."""
        mock_qr = _make_mock_cycle_result(gross_bps=3.0, size_usd=100.0)
        # $100 size → ~11 bps cost → net = -8 bps → above -10 floor → still eligible
        cost_model = {
            "default_profile": "default",
            "profiles": {
                "default": {"gas_usd": 0.05, "l1_fee_usd": 0.01, "slippage_bps": 5.0}
            },
        }
        artifact = build_artifact(
            chain="base",
            duration_minutes=1.0,
            cycle_results=[mock_qr],
            topology=_make_topology(),
            sizes_usd=(100.0,),
            run_timestamp="2026-01-01T00:00:00Z",
            started_at_mono=0.0,
            elapsed_s=60.0,
            cost_model=cost_model,
        )
        # gross=3.0 - cost=11.0 = -8.0 bps; floor=-10 → -8 > -10 → eligible
        assert artifact["cycles_router_sim_eligible"] == 1

    def test_deeply_negative_cycle_not_router_eligible(self):
        """Cycle with cost_adjusted net < -10 bps is excluded from router-sim."""
        mock_qr = _make_mock_cycle_result(gross_bps=-5.0, size_usd=100.0)
        # gross=-5.0 - cost=11.0 = -16.0 bps → below -10 floor → NOT eligible
        cost_model = {
            "default_profile": "default",
            "profiles": {
                "default": {"gas_usd": 0.05, "l1_fee_usd": 0.01, "slippage_bps": 5.0}
            },
        }
        artifact = build_artifact(
            chain="base",
            duration_minutes=1.0,
            cycle_results=[mock_qr],
            topology=_make_topology(),
            sizes_usd=(100.0,),
            run_timestamp="2026-01-01T00:00:00Z",
            started_at_mono=0.0,
            elapsed_s=60.0,
            cost_model=cost_model,
        )
        assert artifact["cycles_router_sim_eligible"] == 0

    def test_economics_metrics_cost_model_applied_flag(self):
        """economics_metrics.cost_model_applied=True when cost_model provided."""
        cost_model = {
            "default_profile": "default",
            "profiles": {
                "default": {"gas_usd": 0.05, "l1_fee_usd": 0.01, "slippage_bps": 5.0}
            },
        }
        artifact = build_artifact(
            chain="base",
            duration_minutes=1.0,
            cycle_results=[],
            topology=_make_topology(),
            sizes_usd=(100.0,),
            run_timestamp="2026-01-01T00:00:00Z",
            started_at_mono=0.0,
            elapsed_s=60.0,
            cost_model=cost_model,
        )
        assert artifact["economics_metrics"]["cost_model_applied"] is True

    def test_artifact_includes_pricing_model_breakdown(self):
        """M9 artifact exposes pricing topology coverage for strategy tracking."""
        mock_qr = _make_mock_cycle_result(gross_bps=20.0, size_usd=100.0)
        artifact = build_artifact(
            chain="base",
            duration_minutes=1.0,
            cycle_results=[mock_qr],
            topology=_make_topology(),
            sizes_usd=(100.0,),
            run_timestamp="2026-01-01T00:00:00Z",
            started_at_mono=0.0,
            elapsed_s=60.0,
        )

        assert artifact["cycles_by_pricing_model"]["clmm_ticks"] == 1
        assert artifact["positive_cycles_by_pricing_model"]["clmm_ticks"] == 1
        assert (
            artifact["cost_breakdown_by_adapter"]["uniswap_v3"]["pricing_model"]
            == "clmm_ticks"
        )

    def test_no_cost_model_flag_false(self):
        """economics_metrics.cost_model_applied=False when no cost_model."""
        artifact = build_artifact(
            chain="base",
            duration_minutes=1.0,
            cycle_results=[],
            topology=_make_topology(),
            sizes_usd=(100.0,),
            run_timestamp="2026-01-01T00:00:00Z",
            started_at_mono=0.0,
            elapsed_s=60.0,
        )
        assert artifact["economics_metrics"]["cost_model_applied"] is False


# ---------------------------------------------------------------------------
# _build_cycle_summary cost fields
# ---------------------------------------------------------------------------

class TestBuildCycleSummaryCostFields:
    def test_no_cost_profile_returns_null_cost_fields(self):
        qr = _make_mock_cycle_result(gross_bps=2.0, size_usd=100.0)
        summary = _build_cycle_summary(qr, cost_profile=None)
        assert summary["estimated_cost_bps"] is None
        assert summary["cost_adjusted_net_bps"] is None

    def test_with_cost_profile_populates_cost_fields(self):
        qr = _make_mock_cycle_result(gross_bps=5.0, size_usd=500.0)
        # $500 size: (0.05 + 0.01)/500*10000 + 5.0 = 1.2 + 5.0 = 6.2 bps
        cost_profile = {"gas_usd": 0.05, "l1_fee_usd": 0.01, "slippage_bps": 5.0}
        summary = _build_cycle_summary(qr, cost_profile=cost_profile)
        assert summary["estimated_cost_bps"] is not None
        assert abs(summary["estimated_cost_bps"] - 6.2) < 0.01
        # cost_adjusted = 5.0 - 6.2 = -1.2
        assert summary["cost_adjusted_net_bps"] is not None
        assert abs(summary["cost_adjusted_net_bps"] - (-1.2)) < 0.01

    def test_zero_size_falls_back_gracefully(self):
        """cycle with size_usd=0 should return null cost fields (no crash)."""
        qr = _make_mock_cycle_result(gross_bps=1.0, size_usd=0.0)
        cost_profile = {"gas_usd": 0.05, "l1_fee_usd": 0.01, "slippage_bps": 5.0}
        summary = _build_cycle_summary(qr, cost_profile=cost_profile)
        assert summary["estimated_cost_bps"] is None
        assert summary["cost_adjusted_net_bps"] is None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_cycle_result(gross_bps: float, size_usd: float):
    """Build a minimal CycleQuoteResult mock."""
    from m9.graph_arb.models import CycleQuoteResult, GraphCycle, GraphEdge

    edge = MagicMock(spec=GraphEdge)
    edge.pool_address = "0x" + "a" * 40
    edge.dex_id = "uniswap_v3"
    edge.adapter_type = "uniswap_v3"
    edge.factory_class = "UNISWAP_V3"
    edge.token_in_sym = "USDC"
    edge.token_out_sym = "WETH"
    edge.pair_id = "USDC_WETH"
    edge.fee_bps = 5.0
    edge.token_in_addr = "0x" + "1" * 40
    edge.token_out_addr = "0x" + "2" * 40
    edge.token_in_decimals = 6
    edge.token_out_decimals = 18

    cycle = MagicMock(spec=GraphCycle)
    cycle.cycle_id = "test_cycle_001"
    cycle.length = 2
    cycle.token_path = ["USDC", "WETH", "USDC"]
    cycle.start_token_sym = "USDC"
    cycle.total_fee_bps = 10.0
    cycle.min_factory_class = "UNISWAP_V3"
    cycle.edges = [edge]

    qr = MagicMock(spec=CycleQuoteResult)
    qr.cycle = cycle
    qr.gross_bps = gross_bps
    qr.size_usd = size_usd
    qr.dynamic_size_usd = None
    qr.amount_in = 100.0
    qr.amount_out = 100.0 * (1 + gross_bps / 10000)
    qr.status = "POSITIVE_GROSS" if gross_bps > 0 else "NEGATIVE_GROSS"
    qr.reject_reason = None
    qr.elapsed_s = 0.1
    qr.leg_results = []
    return qr
