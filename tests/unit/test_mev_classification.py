# PATH: tests/unit/test_mev_classification.py
"""
Tests for R39m MEV-informed classification: chain roles, pair roles,
MEV crowding, lane assignments, and long_scan lane summary.
"""

import pytest

from core.constants import (
    CHAIN_ROLES,
    LANE_ASSIGNMENTS,
    MEV_CROWDING_PENALTY_BPS,
    PAIR_ROLES,
    STRUCTURAL_ADVANTAGE_REQUIRED,
    get_pair_role,
)


# ============================================================
# Chain roles
# ============================================================


class TestChainRoles:
    def test_base_is_primary_profit(self):
        assert CHAIN_ROLES["base"] == "primary_profit"

    def test_zksync_is_exploratory(self):
        assert CHAIN_ROLES["zksync"] == "exploratory"

    def test_arbitrum_is_benchmark(self):
        assert CHAIN_ROLES["arbitrum_one"] == "benchmark"

    def test_all_six_chains_have_roles(self):
        expected = {"base", "zksync", "arbitrum_one", "linea", "scroll", "mantle"}
        assert expected.issubset(set(CHAIN_ROLES.keys()))


# ============================================================
# Structural advantage requirement
# ============================================================


class TestStructuralAdvantage:
    def test_base_requires_flashblocks(self):
        assert STRUCTURAL_ADVANTAGE_REQUIRED["base"] == "flashblocks_preconf"

    def test_arbitrum_does_not_require_structural(self):
        assert "arbitrum_one" not in STRUCTURAL_ADVANTAGE_REQUIRED

    def test_zksync_does_not_require_structural(self):
        assert "zksync" not in STRUCTURAL_ADVANTAGE_REQUIRED


# ============================================================
# Pair roles
# ============================================================


class TestPairRoles:
    def test_base_cbbtc_usdc_is_alpha(self):
        assert get_pair_role("base", "cbBTC/USDC") == "alpha"

    def test_base_cbbtc_weth_is_alpha(self):
        assert get_pair_role("base", "cbBTC/WETH") == "alpha"

    def test_base_aero_usdc_is_alpha(self):
        assert get_pair_role("base", "AERO/USDC") == "alpha"

    def test_base_weth_usdc_is_benchmark(self):
        assert get_pair_role("base", "WETH/USDC") == "benchmark"

    def test_arb_weth_usdc_is_benchmark(self):
        assert get_pair_role("arbitrum_one", "WETH/USDC") == "benchmark"

    def test_any_chain_usdc_dai_is_calibration(self):
        assert get_pair_role("arbitrum_one", "USDC/DAI") == "calibration"
        assert get_pair_role("base", "USDC/DAI") == "calibration"
        assert get_pair_role("zksync", "USDC/DAI") == "calibration"

    def test_any_chain_usdc_usdt_is_calibration(self):
        assert get_pair_role("arbitrum_one", "USDC/USDT") == "calibration"
        assert get_pair_role("base", "USDC/USDT") == "calibration"

    def test_unknown_pair_is_unclassified(self):
        assert get_pair_role("arbitrum_one", "WETH/ARB") == "unclassified"

    def test_wildcard_takes_precedence_over_default(self):
        """Wildcard *:USDC/DAI should match any chain."""
        assert get_pair_role("linea", "USDC/DAI") == "calibration"

    def test_exact_match_beats_wildcard(self):
        """Exact chain:pair should beat *:pair wildcard.

        base:AERO/USDC is alpha even though there's no *:AERO/USDC.
        """
        assert get_pair_role("base", "AERO/USDC") == "alpha"


# ============================================================
# MEV crowding penalty
# ============================================================


class TestMEVCrowdingPenalty:
    def test_alpha_no_penalty(self):
        assert MEV_CROWDING_PENALTY_BPS["alpha"] == 0.0

    def test_benchmark_moderate_penalty(self):
        assert MEV_CROWDING_PENALTY_BPS["benchmark"] == 50.0

    def test_calibration_highest_penalty(self):
        assert MEV_CROWDING_PENALTY_BPS["calibration"] == 100.0

    def test_unclassified_mild_penalty(self):
        assert MEV_CROWDING_PENALTY_BPS["unclassified"] == 25.0

    def test_penalty_ranking_order(self):
        """Alpha < unclassified < benchmark < calibration."""
        p = MEV_CROWDING_PENALTY_BPS
        assert p["alpha"] < p["unclassified"] < p["benchmark"] < p["calibration"]


# ============================================================
# Lane assignments
# ============================================================


class TestLaneAssignments:
    def test_base_is_lane_a(self):
        assert LANE_ASSIGNMENTS["base"] == "A_quantity_profit"

    def test_zksync_is_lane_b(self):
        assert LANE_ASSIGNMENTS["zksync"] == "B_inefficiency_probe"

    def test_arbitrum_is_benchmark_control(self):
        assert LANE_ASSIGNMENTS["arbitrum_one"] == "benchmark_control"

    def test_all_six_chains_assigned(self):
        expected = {"base", "zksync", "arbitrum_one", "linea", "scroll", "mantle"}
        assert expected.issubset(set(LANE_ASSIGNMENTS.keys()))


# ============================================================
# Lane summary builder
# ============================================================


class TestLaneSummary:
    """Test _compute_lane_summary from long_scan_summary."""

    @staticmethod
    def _make_chain_stats(
        runs=5, pass_count=5, signals=20, profitable_rt=0, gap=None
    ):
        return {
            "runs": runs,
            "pass": pass_count,
            "fail": 0,
            "no_data": 0,
            "infra_fail": 0,
            "included_signals_total": signals,
            "profitable_roundtrips_total": profitable_rt,
            "sweep_gap_to_zero_bps": gap,
        }

    def test_lane_summary_separates_chains(self):
        from strategy.long_scan_summary import _compute_lane_summary

        per_chain = {
            "base": self._make_chain_stats(runs=3, signals=50, gap=15.0),
            "arbitrum_one": self._make_chain_stats(runs=5, signals=30, gap=27.0),
            "zksync": self._make_chain_stats(runs=2, signals=10, gap=40.0),
        }
        result = _compute_lane_summary(per_chain)

        assert "A_quantity_profit" in result
        assert "benchmark_control" in result
        assert "B_inefficiency_probe" in result

        # Base is Lane A
        a = result["A_quantity_profit"]
        assert "base" in a["chains"]
        assert a["total_runs"] == 3
        assert a["total_signals"] == 50
        assert a["best_gap_to_zero_bps"] == 15.0

        # Arbitrum is benchmark
        bench = result["benchmark_control"]
        assert "arbitrum_one" in bench["chains"]
        assert bench["total_runs"] == 5

        # zkSync is Lane B
        b = result["B_inefficiency_probe"]
        assert "zksync" in b["chains"]

    def test_structural_advantage_not_met_for_base(self):
        from strategy.long_scan_summary import _compute_lane_summary

        per_chain = {
            "base": self._make_chain_stats(runs=3, signals=50),
        }
        result = _compute_lane_summary(per_chain)
        a = result["A_quantity_profit"]
        # Base requires Flashblocks but it's not integrated yet
        assert a["structural_advantage_met"] is False

    def test_lane_b_structural_advantage_met(self):
        from strategy.long_scan_summary import _compute_lane_summary

        per_chain = {
            "zksync": self._make_chain_stats(runs=2, signals=10),
        }
        result = _compute_lane_summary(per_chain)
        b = result["B_inefficiency_probe"]
        # zkSync has no structural requirement
        assert b["structural_advantage_met"] is True

    def test_best_gap_picks_minimum(self):
        from strategy.long_scan_summary import _compute_lane_summary

        per_chain = {
            "linea": self._make_chain_stats(runs=2, signals=5, gap=50.0),
            "scroll": self._make_chain_stats(runs=3, signals=8, gap=35.0),
        }
        result = _compute_lane_summary(per_chain)
        b = result["B_inefficiency_probe"]
        assert b["best_gap_to_zero_bps"] == 35.0
