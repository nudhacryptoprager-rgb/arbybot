# PATH: tests/unit/test_dynamic_sweep_runtime.py
"""
Contract tests for strategy/dynamic_sweep_runtime.py.

Verifies outlier filtering, stats assembly, and executable evidence promotion.
"""

from unittest.mock import MagicMock

from strategy.dynamic_sweep_runtime import (
    SUSPECT_ROUNDTRIP_OUTLIER_BPS,
    _build_sweep_stats,
)


def _make_sweep_result(pair="WETH_USDC", best_net_pnl_bps=-10.0, best_size_usd=500,
                       frontier_reason="GAP", gap_to_zero_bps=10.0):
    sr = MagicMock()
    sr.pair = pair
    sr.best_net_pnl_bps = best_net_pnl_bps
    sr.best_size_usd = best_size_usd
    sr.frontier_reason = frontier_reason
    sr.gap_to_zero_bps = gap_to_zero_bps
    sr.best_gas_bps = 2.0
    sr.best_fee_bps = 10.0
    sr.best_slippage_bps = 5.0
    sr.best_total_cost_bps = 17.0
    sr.to_dict.return_value = {"pair": pair, "best_net_pnl_bps": best_net_pnl_bps}
    return sr


class TestOutlierFilter:
    def test_outlier_threshold(self):
        assert SUSPECT_ROUNDTRIP_OUTLIER_BPS == 500

    def test_clean_results_pass(self):
        results = [_make_sweep_result(best_net_pnl_bps=-20.0)]
        stats, evidence = _build_sweep_stats(results)
        assert stats["routes_clean"] == 1
        assert stats["suspect_outlier_count"] == 0

    def test_outlier_filtered(self):
        results = [_make_sweep_result(best_net_pnl_bps=600.0)]
        stats, evidence = _build_sweep_stats(results)
        assert stats["routes_clean"] == 0
        assert stats["suspect_outlier_count"] == 1
        assert stats["best_frontier_reason"] == "ALL_SUSPECT_OUTLIER"

    def test_negative_outlier_filtered(self):
        results = [_make_sweep_result(best_net_pnl_bps=-600.0)]
        stats, evidence = _build_sweep_stats(results)
        assert stats["routes_clean"] == 0
        assert stats["suspect_outlier_count"] == 1

    def test_empty_results(self):
        stats, evidence = _build_sweep_stats([])
        assert stats["routes_swept"] == 0
        assert evidence["executable_evidence"] == "NO_SWEEP_DATA"


class TestExecutableEvidence:
    def test_sweep_profitable(self):
        results = [_make_sweep_result(best_net_pnl_bps=5.0)]
        stats, evidence = _build_sweep_stats(results)
        assert evidence["executable_evidence"] == "SWEEP_PROFITABLE"
        assert evidence["best_executable_pnl_bps"] == 5.0

    def test_sweep_gap_to_zero(self):
        results = [_make_sweep_result(best_net_pnl_bps=-3.0, gap_to_zero_bps=3.0)]
        stats, evidence = _build_sweep_stats(results)
        assert evidence["executable_evidence"] == "SWEEP_GAP_TO_ZERO"

    def test_no_sweep_data(self):
        stats, evidence = _build_sweep_stats([])
        assert evidence["executable_evidence"] == "NO_SWEEP_DATA"
        assert evidence["best_executable_size_usd"] is None


class TestSweepStats:
    def test_best_sweep_selected(self):
        results = [
            _make_sweep_result(pair="A", best_net_pnl_bps=-20.0),
            _make_sweep_result(pair="B", best_net_pnl_bps=-5.0),
        ]
        stats, evidence = _build_sweep_stats(results)
        assert stats["best_pair"] == "B"
        assert stats["routes_swept"] == 2
        assert stats["routes_clean"] == 2
