"""R39w: Regression tests for repeatability-informed frontier pair promotion.

Tests that sweep_best_pair is overridden when per_pair_repeatability evidence
shows a more stable pair is significantly better than the single-best-PnL pair.
"""

import unittest
from strategy.long_scan_summary import _apply_repeatability_frontier, _compute_median


def _make_chain_stats(sweep_best_pair="WETH/USDC", per_pair_repeat=None, **kw):
    """Minimal per-chain stats dict for repeatability frontier tests."""
    base = {
        "config": "real_minimal.yaml",
        "runs": 30, "pass": 11, "no_data": 0, "fail": 19, "infra_fail": 0,
        "infra_pass": 30,
        "included_signals_total": 90,
        "net_usdc_total": 0.0,
        "profitable_roundtrips_total": 0,
        "roundtrip_evaluated_total": 0,
        "real_quote_count_total": 0,
        "best_roundtrip_net_bps": None,
        "best_measured_spread_gap_bps": None,
        "sweep_best_net_pnl_bps": -4.88,
        "sweep_best_size_usd": 100,
        "sweep_best_pair": sweep_best_pair,
        "sweep_gap_to_zero_bps": 4.88,
        "last_run_timestamp": "2026-03-27T14:00:00Z",
        "last_run_dir": "test_run",
        "last_run_summary_status": "PASS",
        "last_quality_status": "PASS",
        "last_chain_quality_level": "SIGNAL_PRODUCING",
        "last_profit_truth_available": True,
        "run_kind": "NORMAL",
        "last_cross_dex_pairs_count": 3,
        "_per_pair_repeat": per_pair_repeat or {},
        "_sweep_gap_values": [],
        "runs_with_sweep": 30,
        "_drift_rejection_rates": [],
        "_drift_median_bps_values": [],
        "accepted_fail": False,
    }
    base.update(kw)
    return base


class TestRepeatabilityFrontierPromotion(unittest.TestCase):
    """R39w: sweep_best_pair must reflect repeatability evidence."""

    def test_stable_pair_promoted_over_weth_usdc(self):
        """USDC/DAI with median_gap=8.77 must replace WETH/USDC with median_gap=49.98."""
        per_chain = {
            "base": _make_chain_stats(
                sweep_best_pair="WETH/USDC",
                per_pair_repeat={
                    "USDC/DAI": {"runs_with_signals": 30, "runs_with_sweep_truth": 30,
                                 "_gap_values": [8.0, 8.5, 9.0, 8.8, 9.5]},
                    "USDC/USDT": {"runs_with_signals": 30, "runs_with_sweep_truth": 30,
                                  "_gap_values": [9.0, 9.2, 9.5, 9.1, 9.3]},
                    "WETH/USDC": {"runs_with_signals": 30, "runs_with_sweep_truth": 30,
                                  "_gap_values": [45.0, 50.0, 55.0, 48.0, 52.0]},
                },
            ),
        }
        _apply_repeatability_frontier(per_chain)
        base = per_chain["base"]
        self.assertEqual(base["sweep_best_pair"], "USDC/DAI")
        self.assertEqual(base["sweep_benchmark_pair"], "WETH/USDC")
        self.assertEqual(base["sweep_best_pair_source"], "repeatability")

    def test_benchmark_pair_preserved_in_diagnostics(self):
        """Original WETH/USDC must remain visible as sweep_benchmark_pair."""
        per_chain = {
            "base": _make_chain_stats(
                sweep_best_pair="WETH/USDC",
                per_pair_repeat={
                    "USDC/DAI": {"runs_with_signals": 30, "runs_with_sweep_truth": 30,
                                 "_gap_values": [8.0, 9.0, 8.5]},
                    "WETH/USDC": {"runs_with_signals": 30, "runs_with_sweep_truth": 30,
                                  "_gap_values": [50.0, 48.0, 52.0]},
                },
            ),
        }
        _apply_repeatability_frontier(per_chain)
        base = per_chain["base"]
        self.assertEqual(base["sweep_benchmark_pair"], "WETH/USDC")
        self.assertAlmostEqual(base["sweep_benchmark_median_gap_bps"], 50.0, places=1)
        self.assertAlmostEqual(base["frontier_median_gap_bps"], 8.5, places=1)

    def test_no_promotion_when_current_pair_is_best(self):
        """No promotion when current sweep_best_pair already has the best median gap."""
        per_chain = {
            "arb": _make_chain_stats(
                sweep_best_pair="USDC/DAI",
                per_pair_repeat={
                    "USDC/DAI": {"runs_with_signals": 31, "runs_with_sweep_truth": 31,
                                 "_gap_values": [25.0, 26.0, 25.5]},
                    "WETH/USDC": {"runs_with_signals": 21, "runs_with_sweep_truth": 19,
                                  "_gap_values": [200.0, 210.0, 220.0]},
                },
            ),
        }
        _apply_repeatability_frontier(per_chain)
        self.assertEqual(per_chain["arb"]["sweep_best_pair"], "USDC/DAI")
        self.assertNotIn("sweep_benchmark_pair", per_chain["arb"])

    def test_no_promotion_below_ratio_threshold(self):
        """No promotion when gap ratio is below 2x threshold."""
        per_chain = {
            "base": _make_chain_stats(
                sweep_best_pair="WETH/USDC",
                per_pair_repeat={
                    "USDC/DAI": {"runs_with_signals": 30, "runs_with_sweep_truth": 30,
                                 "_gap_values": [15.0, 16.0, 14.0]},
                    "WETH/USDC": {"runs_with_signals": 30, "runs_with_sweep_truth": 30,
                                  "_gap_values": [25.0, 26.0, 24.0]},
                },
            ),
        }
        _apply_repeatability_frontier(per_chain)
        # Ratio ~1.67x < 2.0x threshold — no promotion
        self.assertEqual(per_chain["base"]["sweep_best_pair"], "WETH/USDC")
        self.assertNotIn("sweep_benchmark_pair", per_chain["base"])

    def test_promotion_when_current_pair_has_no_repeatability_data(self):
        """Promote when current best has no repeatability samples."""
        per_chain = {
            "base": _make_chain_stats(
                sweep_best_pair="WETH/USDC",
                per_pair_repeat={
                    "USDC/DAI": {"runs_with_signals": 30, "runs_with_sweep_truth": 30,
                                 "_gap_values": [8.0, 9.0, 8.5]},
                    "WETH/USDC": {"runs_with_signals": 5, "runs_with_sweep_truth": 1,
                                  "_gap_values": [4.88]},  # Only 1 sample < minimum 3
                },
            ),
        }
        _apply_repeatability_frontier(per_chain)
        self.assertEqual(per_chain["base"]["sweep_best_pair"], "USDC/DAI")
        self.assertEqual(per_chain["base"]["sweep_benchmark_pair"], "WETH/USDC")

    def test_insufficient_samples_skips_promotion(self):
        """No promotion when no pair has enough samples."""
        per_chain = {
            "base": _make_chain_stats(
                sweep_best_pair="WETH/USDC",
                per_pair_repeat={
                    "USDC/DAI": {"runs_with_signals": 2, "runs_with_sweep_truth": 2,
                                 "_gap_values": [8.0, 9.0]},  # Only 2 < minimum 3
                    "WETH/USDC": {"runs_with_signals": 1, "runs_with_sweep_truth": 1,
                                  "_gap_values": [50.0]},
                },
            ),
        }
        _apply_repeatability_frontier(per_chain)
        self.assertEqual(per_chain["base"]["sweep_best_pair"], "WETH/USDC")
        self.assertNotIn("sweep_benchmark_pair", per_chain["base"])

    def test_empty_per_pair_repeat_skips(self):
        """No crash or promotion when _per_pair_repeat is empty."""
        per_chain = {
            "base": _make_chain_stats(
                sweep_best_pair="WETH/USDC",
                per_pair_repeat={},
            ),
        }
        _apply_repeatability_frontier(per_chain)
        self.assertEqual(per_chain["base"]["sweep_best_pair"], "WETH/USDC")

    def test_frontier_ranking_surfaces_promoted_pair(self):
        """build_summary frontier_ranking must reflect the promoted pair."""
        from strategy.long_scan_summary import build_summary
        from strategy.chain_stats import new_chain_stats

        stats = new_chain_stats()
        stats.update({
            "config": "real_minimal.yaml", "runs": 30, "pass": 11, "fail": 19,
            "infra_fail": 0, "infra_pass": 30,
            "included_signals_total": 90,
            "sweep_best_net_pnl_bps": -4.88,
            "sweep_best_pair": "WETH/USDC",
            "sweep_gap_to_zero_bps": 4.88,
            "_sweep_gap_values": [4.88],
            "runs_with_sweep": 30,
            "_per_pair_repeat": {
                "USDC/DAI": {"runs_with_signals": 30, "runs_with_sweep_truth": 30,
                             "_gap_values": [8.0, 8.5, 9.0, 8.8, 9.5]},
                "WETH/USDC": {"runs_with_signals": 30, "runs_with_sweep_truth": 30,
                              "_gap_values": [45.0, 50.0, 55.0, 48.0, 52.0]},
            },
        })
        per_chain = {"base": stats}
        summary = build_summary(per_chain, 600.0, [])
        ranking = summary["frontier_ranking"]
        self.assertEqual(len(ranking), 1)
        entry = ranking[0]
        self.assertEqual(entry["frontier_pair"], "USDC/DAI")
        self.assertEqual(entry["frontier_pair_source"], "repeatability")
        self.assertEqual(entry["sweep_benchmark_pair"], "WETH/USDC")

    def test_promotion_breakeven_alternative(self):
        """Promote when best alternative has median gap ≤ 0 (profitable/breakeven)."""
        per_chain = {
            "base": _make_chain_stats(
                sweep_best_pair="WETH/USDC",
                per_pair_repeat={
                    "USDC/DAI": {"runs_with_signals": 30, "runs_with_sweep_truth": 30,
                                 "_gap_values": [-1.0, 0.0, 0.5]},
                    "WETH/USDC": {"runs_with_signals": 30, "runs_with_sweep_truth": 30,
                                  "_gap_values": [10.0, 12.0, 11.0]},
                },
            ),
        }
        _apply_repeatability_frontier(per_chain)
        self.assertEqual(per_chain["base"]["sweep_best_pair"], "USDC/DAI")


if __name__ == "__main__":
    unittest.main()
