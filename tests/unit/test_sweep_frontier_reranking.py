"""R39x: Regression tests for sweep-frontier truth-probe reranking.

Tests that top_opportunities reflects measured multi-size sweep economics
(gap_to_zero_bps from frontier_curves) instead of seed-size
spread_minus_required_bps when truth_mode_m42 is active and sweep
results exist.

Also tests curve-quality guard: pairs with catastrophic slippage
(>= 10000 bps) or ROUTE_KILL at larger sizes are penalised and
do not auto-beat pairs with stable curves.
"""

import logging
import unittest

from strategy.jobs.run_scan_real import _rerank_top_opportunities_by_sweep_frontier


def _make_stats(
    seed_top=None,
    sweep_results=None,
    truth_mode_m42=True,
):
    """Build minimal stats dict for reranking tests."""
    oe = {
        "enabled": True,
        "top_opportunities": seed_top or [],
        "truth_mode_m42": truth_mode_m42,
    }
    rt = {}
    if sweep_results is not None:
        rt["dynamic_sweep"] = {
            "enabled": True,
            "results": sweep_results,
        }
    return {
        "opportunity_engine": oe,
        "roundtrip": rt,
    }


def _make_sweep_result(pair, gap_to_zero_bps, best_net_pnl_bps=None,
                        best_slippage_bps=None, frontier_reason="BREAKEVEN_FRONTIER",
                        points=None, buy_dex="uniswap_v3", sell_dex="uniswap_v3"):
    """Build a single SizeSweepResult-like dict."""
    if best_net_pnl_bps is None:
        best_net_pnl_bps = -gap_to_zero_bps if gap_to_zero_bps is not None else None
    return {
        "pair": pair,
        "buy_dex": buy_dex,
        "sell_dex": sell_dex,
        "gap_to_zero_bps": gap_to_zero_bps,
        "best_net_pnl_bps": best_net_pnl_bps,
        "best_slippage_bps": best_slippage_bps or 5.0,
        "frontier_reason": frontier_reason,
        "points": points or [],
    }


def _make_seed_signal(pair, spread_minus_required_bps):
    """Build a minimal seed-signal dict (like spread_signals entry)."""
    return {
        "pair": pair,
        "spread_minus_required_bps": spread_minus_required_bps,
        "measured_slippage_bps": 5.0,
    }


_logger = logging.getLogger("test_sweep_frontier_reranking")


class TestSweepFrontierReranking(unittest.TestCase):
    """R39x: top_opportunities must reflect sweep frontier, not seed-size signal."""

    def test_weth_usdc_better_seed_but_worse_sweep_not_first(self):
        """WETH/USDC: seed surplus=-12, sweep gap=71.
        USDC/DAI: seed surplus=-17, sweep gap=8.67.
        After reranking, USDC/DAI must come first."""
        seed_top = [
            _make_seed_signal("WETH/USDC", -12.27),
            _make_seed_signal("USDC/DAI", -17.28),
        ]
        sweep_results = [
            _make_sweep_result("WETH/USDC", gap_to_zero_bps=71.36, best_slippage_bps=22.59),
            _make_sweep_result("USDC/DAI", gap_to_zero_bps=8.67, best_slippage_bps=4.44),
        ]
        stats = _make_stats(seed_top=seed_top, sweep_results=sweep_results)
        _rerank_top_opportunities_by_sweep_frontier(stats, _logger)

        top = stats["opportunity_engine"]["top_opportunities"]
        self.assertEqual(len(top), 2)
        self.assertEqual(top[0]["pair"], "USDC/DAI")
        self.assertEqual(top[1]["pair"], "WETH/USDC")
        self.assertEqual(top[0]["ranking_source"], "sweep_frontier")
        # Seed-signal list preserved for diagnostics
        seed_preserved = stats["opportunity_engine"]["_seed_signal_top_opportunities"]
        self.assertEqual(seed_preserved[0]["pair"], "WETH/USDC")
        self.assertTrue(stats["opportunity_engine"]["_sweep_frontier_reranked"])

    def test_usdc_usdt_curve_degraded_does_not_beat_usdc_dai(self):
        """USDC/USDT: gap=8.69 at $25 but catastrophic slippage=10000 at $50.
        USDC/DAI: gap=8.67 stable across all sizes.
        Despite nearly identical gap, USDC/USDT must NOT rank above USDC/DAI
        because its curve is degraded."""
        seed_top = [
            _make_seed_signal("USDC/USDT", -8.69),
            _make_seed_signal("USDC/DAI", -17.28),
        ]
        sweep_results = [
            _make_sweep_result(
                "USDC/USDT", gap_to_zero_bps=8.69, best_slippage_bps=2.59,
                points=[
                    {"size_usd": 25, "net_pnl_bps": -8.69, "measured_slippage_bps": 2.59, "error": None},
                    {"size_usd": 50, "net_pnl_bps": -969.63, "measured_slippage_bps": 10000, "error": "ROUTE_KILL_GROSS_NEGATIVE"},
                    {"size_usd": 75, "net_pnl_bps": -3979.75, "measured_slippage_bps": 10000, "error": "ROUTE_KILL_GROSS_NEGATIVE"},
                ],
            ),
            _make_sweep_result(
                "USDC/DAI", gap_to_zero_bps=8.67, best_slippage_bps=4.44,
                points=[
                    {"size_usd": 25, "net_pnl_bps": -11.0, "measured_slippage_bps": 1.48, "error": None},
                    {"size_usd": 50, "net_pnl_bps": -8.67, "measured_slippage_bps": 4.44, "error": None},
                    {"size_usd": 75, "net_pnl_bps": -10.2, "measured_slippage_bps": 4.44, "error": None},
                ],
            ),
        ]
        stats = _make_stats(seed_top=seed_top, sweep_results=sweep_results)
        _rerank_top_opportunities_by_sweep_frontier(stats, _logger)

        top = stats["opportunity_engine"]["top_opportunities"]
        self.assertEqual(top[0]["pair"], "USDC/DAI")
        self.assertEqual(top[1]["pair"], "USDC/USDT")
        # USDC/USDT is marked as degraded
        self.assertTrue(top[1]["curve_degraded"])
        self.assertFalse(top[0]["curve_degraded"])

    def test_no_sweep_results_no_reranking(self):
        """When no sweep results exist, top_opportunities is unchanged."""
        seed_top = [_make_seed_signal("WETH/USDC", -12.27)]
        stats = _make_stats(seed_top=seed_top, sweep_results=None)
        _rerank_top_opportunities_by_sweep_frontier(stats, _logger)

        top = stats["opportunity_engine"]["top_opportunities"]
        # Unchanged — still seed-signal format
        self.assertEqual(top[0]["pair"], "WETH/USDC")
        self.assertNotIn("ranking_source", top[0])
        self.assertNotIn("_sweep_frontier_reranked", stats["opportunity_engine"])

    def test_empty_sweep_results_no_reranking(self):
        """When sweep results exist but are empty, no reranking."""
        seed_top = [_make_seed_signal("WETH/USDC", -12.27)]
        stats = _make_stats(seed_top=seed_top, sweep_results=[])
        _rerank_top_opportunities_by_sweep_frontier(stats, _logger)

        top = stats["opportunity_engine"]["top_opportunities"]
        self.assertEqual(top[0]["pair"], "WETH/USDC")
        self.assertNotIn("_sweep_frontier_reranked", stats["opportunity_engine"])

    def test_three_pairs_full_ranking(self):
        """Full Base scenario: WETH/USDC (gap=71), USDC/DAI (gap=8.67),
        USDC/USDT (gap=8.69 + degraded). Expected order:
        1. USDC/DAI (stable, gap=8.67)
        2. WETH/USDC (stable, gap=71.36) — stable beats degraded despite worse gap
        Actually: WETH/USDC gap=71.36 vs USDC/USDT adjusted=10008.69.
        So order: USDC/DAI, WETH/USDC, USDC/USDT."""
        sweep_results = [
            _make_sweep_result("WETH/USDC", gap_to_zero_bps=71.36, best_slippage_bps=22.59,
                               points=[
                                   {"size_usd": 25, "net_pnl_bps": -71.36, "measured_slippage_bps": 22.59, "error": None},
                                   {"size_usd": 50, "net_pnl_bps": -79.45, "measured_slippage_bps": 38.25, "error": None},
                               ]),
            _make_sweep_result("USDC/DAI", gap_to_zero_bps=8.67, best_slippage_bps=4.44,
                               points=[
                                   {"size_usd": 25, "net_pnl_bps": -11.0, "measured_slippage_bps": 1.48, "error": None},
                                   {"size_usd": 50, "net_pnl_bps": -8.67, "measured_slippage_bps": 4.44, "error": None},
                               ]),
            _make_sweep_result("USDC/USDT", gap_to_zero_bps=8.69, best_slippage_bps=2.59,
                               points=[
                                   {"size_usd": 25, "net_pnl_bps": -8.69, "measured_slippage_bps": 2.59, "error": None},
                                   {"size_usd": 50, "net_pnl_bps": -969.63, "measured_slippage_bps": 10000, "error": "ROUTE_KILL_GROSS_NEGATIVE"},
                               ]),
        ]
        seed_top = [
            _make_seed_signal("WETH/USDC", -12.27),
            _make_seed_signal("USDC/DAI", -17.28),
            _make_seed_signal("USDC/USDT", -8.69),
        ]
        stats = _make_stats(seed_top=seed_top, sweep_results=sweep_results)
        _rerank_top_opportunities_by_sweep_frontier(stats, _logger)

        top = stats["opportunity_engine"]["top_opportunities"]
        self.assertEqual(len(top), 3)
        self.assertEqual(top[0]["pair"], "USDC/DAI")
        self.assertEqual(top[1]["pair"], "WETH/USDC")
        self.assertEqual(top[2]["pair"], "USDC/USDT")
        # USDC/USDT degraded, others not
        self.assertFalse(top[0]["curve_degraded"])
        self.assertFalse(top[1]["curve_degraded"])
        self.assertTrue(top[2]["curve_degraded"])

    def test_route_kill_error_triggers_degradation(self):
        """A point with ROUTE_KILL error (no slippage=10000) still triggers degradation."""
        sweep_results = [
            _make_sweep_result(
                "PAIR_A", gap_to_zero_bps=5.0,
                points=[
                    {"size_usd": 25, "net_pnl_bps": -5.0, "measured_slippage_bps": 3.0, "error": None},
                    {"size_usd": 50, "net_pnl_bps": -50.0, "measured_slippage_bps": 40.0, "error": "ROUTE_KILL_GROSS_NEGATIVE"},
                ],
            ),
            _make_sweep_result(
                "PAIR_B", gap_to_zero_bps=6.0,
                points=[
                    {"size_usd": 25, "net_pnl_bps": -6.0, "measured_slippage_bps": 3.0, "error": None},
                    {"size_usd": 50, "net_pnl_bps": -7.0, "measured_slippage_bps": 4.0, "error": None},
                ],
            ),
        ]
        stats = _make_stats(sweep_results=sweep_results)
        _rerank_top_opportunities_by_sweep_frontier(stats, _logger)

        top = stats["opportunity_engine"]["top_opportunities"]
        # PAIR_B (stable, gap=6) beats PAIR_A (degraded, gap=5)
        self.assertEqual(top[0]["pair"], "PAIR_B")
        self.assertEqual(top[1]["pair"], "PAIR_A")
        self.assertTrue(top[1]["curve_degraded"])

    def test_gap_none_ranked_last(self):
        """Pairs with gap_to_zero_bps=None get worst rank (99999),
        even below degraded pairs with real data."""
        sweep_results = [
            _make_sweep_result("PAIR_A", gap_to_zero_bps=None, frontier_reason="ALL_FAILED"),
            _make_sweep_result("PAIR_B", gap_to_zero_bps=50.0),
        ]
        # Patch: gap=None → set explicitly
        sweep_results[0]["gap_to_zero_bps"] = None
        stats = _make_stats(sweep_results=sweep_results)
        _rerank_top_opportunities_by_sweep_frontier(stats, _logger)

        top = stats["opportunity_engine"]["top_opportunities"]
        self.assertEqual(top[0]["pair"], "PAIR_B")
        self.assertEqual(top[1]["pair"], "PAIR_A")
        self.assertFalse(top[1].get("has_data", True))

    def test_no_data_ranked_below_degraded(self):
        """Pairs with no data (gap=None, all LEG1_QUOTE_FAIL) must rank
        BELOW degraded pairs that have real executable data.
        This is the arb_one scenario: USDC/DAI (gap=25.72, degraded at $15)
        must beat WETH/PENDLE (all LEG1_QUOTE_FAIL, no data)."""
        sweep_results = [
            _make_sweep_result(
                "WETH/PENDLE", gap_to_zero_bps=None, frontier_reason="ALL_FAILED",
                points=[
                    {"size_usd": 25, "net_pnl_bps": None, "measured_slippage_bps": None, "error": "LEG1_QUOTE_FAIL"},
                    {"size_usd": 50, "net_pnl_bps": None, "measured_slippage_bps": None, "error": "LEG1_QUOTE_FAIL"},
                ],
            ),
            _make_sweep_result(
                "USDC/DAI", gap_to_zero_bps=25.72,
                points=[
                    {"size_usd": 5, "net_pnl_bps": -25.72, "measured_slippage_bps": 10.29, "error": None},
                    {"size_usd": 15, "net_pnl_bps": None, "measured_slippage_bps": None, "error": "ROUTE_KILL_GROSS_NEGATIVE"},
                ],
            ),
        ]
        # Fix None gap
        sweep_results[0]["gap_to_zero_bps"] = None
        stats = _make_stats(sweep_results=sweep_results)
        _rerank_top_opportunities_by_sweep_frontier(stats, _logger)

        top = stats["opportunity_engine"]["top_opportunities"]
        # USDC/DAI (degraded, gap=25.72 → adjusted=10025.72) beats WETH/PENDLE (no data → 99999)
        self.assertEqual(top[0]["pair"], "USDC/DAI")
        self.assertEqual(top[1]["pair"], "WETH/PENDLE")
        self.assertTrue(top[0]["curve_degraded"])
        self.assertFalse(top[1].get("has_data", True))


if __name__ == "__main__":
    unittest.main()
