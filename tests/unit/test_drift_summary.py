# PATH: tests/unit/test_drift_summary.py
"""
Unit tests for NOTIONAL_DRIFT first-class artifact layer (R19→R20→R21).

Tests for:
- _build_drift_summary() contract (with per-pair bps + per_pair_signal_drift + per_pair_drift_summary)
- drift_summary propagation through truth_data
- drift fields in rolling per-run entry
- per-chain drift in rolling per_chain_frontier
- dashboard default-on (--no-dashboard opt-out)
- R21: per_pair_drift_summary, notional_drift_bps, per_chain_drift_summary
- R21: operational_truth_source, universe_split
"""

import unittest


class TestBuildDriftSummary(unittest.TestCase):
    """Test _build_drift_summary() function contract."""

    def _build(self, rejected_quotes=None, spread_signals=None):
        from strategy.artifacts import _build_drift_summary
        return _build_drift_summary(
            rejected_quotes or [],
            spread_signals or [],
        )

    def test_empty_inputs_returns_zero(self):
        result = self._build()
        self.assertEqual(result["drift_excluded_count"], 0)
        self.assertEqual(result["drift_rejection_rate"], 0)
        self.assertEqual(result["signal_drift_median_pct"], 0.0)
        self.assertEqual(result["signal_drift_p90_pct"], 0.0)
        self.assertEqual(result["worst_pairs_by_drift"], [])
        self.assertEqual(result["per_pair_signal_drift"], [])
        self.assertEqual(result["pairs_with_drift_data"], 0)
        self.assertEqual(result["pairs_with_exclusions"], 0)

    def test_required_keys_present(self):
        result = self._build()
        for key in (
            "drift_excluded_count",
            "drift_rejection_rate",
            "signal_drift_median_pct",
            "signal_drift_median_bps",
            "signal_drift_p90_pct",
            "signal_drift_p90_bps",
            "worst_pairs_by_drift",
            "per_pair_signal_drift",
            "pairs_with_drift_data",
            "pairs_with_exclusions",
        ):
            self.assertIn(key, result, f"Missing key: {key}")

    def test_drift_excluded_counted(self):
        rejects = [
            {"reason": "NOTIONAL_DRIFT_EXCLUDED", "pair": "WETH/USDC", "notional_drift_pct": 25.0},
            {"reason": "NOTIONAL_DRIFT_EXCLUDED", "pair": "WETH/USDC", "notional_drift_pct": 30.0},
            {"reason": "SUSPECT_SPREAD_HARD", "pair": "WBTC/WETH"},  # not drift
        ]
        result = self._build(rejected_quotes=rejects)
        self.assertEqual(result["drift_excluded_count"], 2)
        self.assertEqual(result["pairs_with_exclusions"], 1)

    def test_worst_pairs_sorted_by_count(self):
        rejects = [
            {"reason": "NOTIONAL_DRIFT_EXCLUDED", "pair": "WETH/USDC", "notional_drift_pct": 25},
            {"reason": "NOTIONAL_DRIFT_EXCLUDED", "pair": "WETH/USDC", "notional_drift_pct": 30},
            {"reason": "NOTIONAL_DRIFT_EXCLUDED", "pair": "WBTC/WETH", "notional_drift_pct": 50},
        ]
        result = self._build(rejected_quotes=rejects)
        worst = result["worst_pairs_by_drift"]
        self.assertGreater(len(worst), 0)
        self.assertEqual(worst[0]["pair"], "WETH/USDC")
        self.assertEqual(worst[0]["excluded_count"], 2)

    def test_worst_pairs_max_5(self):
        """worst_pairs_by_drift is capped at 5 entries."""
        rejects = [
            {"reason": "NOTIONAL_DRIFT_EXCLUDED", "pair": f"PAIR{i}/USDC", "notional_drift_pct": 25 + i}
            for i in range(10)
        ]
        result = self._build(rejected_quotes=rejects)
        self.assertLessEqual(len(result["worst_pairs_by_drift"]), 5)

    def test_signal_drift_from_spread_signals(self):
        signals = [
            {"pair": "WETH/USDC", "buy_notional_drift_pct": 5.0, "sell_notional_drift_pct": 8.0},
            {"pair": "WBTC/WETH", "buy_notional_drift_pct": 3.0, "sell_notional_drift_pct": 12.0},
        ]
        result = self._build(spread_signals=signals)
        self.assertGreater(result["signal_drift_median_pct"], 0)
        self.assertGreater(result["signal_drift_p90_pct"], 0)
        self.assertEqual(result["pairs_with_drift_data"], 2)

    def test_rejection_rate_bounded(self):
        rejects = [
            {"reason": "NOTIONAL_DRIFT_EXCLUDED", "pair": "A/B", "notional_drift_pct": 25},
        ]
        signals = [
            {"pair": "C/D", "buy_notional_drift_pct": 5.0, "sell_notional_drift_pct": 8.0},
        ]
        result = self._build(rejected_quotes=rejects, spread_signals=signals)
        self.assertGreaterEqual(result["drift_rejection_rate"], 0)
        self.assertLessEqual(result["drift_rejection_rate"], 1.0)

    def test_bps_fields_are_100x_pct(self):
        """bps fields should be pct * 100."""
        signals = [
            {"pair": "WETH/USDC", "buy_notional_drift_pct": 5.0, "sell_notional_drift_pct": 5.0},
        ]
        result = self._build(spread_signals=signals)
        self.assertEqual(result["signal_drift_median_bps"], result["signal_drift_median_pct"] * 100)
        self.assertEqual(result["signal_drift_p90_bps"], result["signal_drift_p90_pct"] * 100)

    def test_worst_pairs_have_bps_and_reason(self):
        rejects = [
            {"reason": "NOTIONAL_DRIFT_EXCLUDED", "pair": "WETH/USDC", "notional_drift_pct": 25},
        ]
        result = self._build(rejected_quotes=rejects)
        worst = result["worst_pairs_by_drift"]
        self.assertGreater(len(worst), 0)
        self.assertIn("median_drift_bps", worst[0])
        self.assertIn("max_drift_bps", worst[0])
        self.assertIn("drift_reject_reason", worst[0])
        self.assertEqual(worst[0]["drift_reject_reason"], "NOTIONAL_DRIFT_EXCLUDED")

    def test_per_pair_signal_drift(self):
        signals = [
            {"pair": "WETH/USDC", "buy_notional_drift_pct": 5.0, "sell_notional_drift_pct": 8.0},
            {"pair": "WETH/USDC", "buy_notional_drift_pct": 3.0, "sell_notional_drift_pct": 10.0},
            {"pair": "WBTC/WETH", "buy_notional_drift_pct": 2.0, "sell_notional_drift_pct": 4.0},
        ]
        result = self._build(spread_signals=signals)
        per_pair = result["per_pair_signal_drift"]
        self.assertGreater(len(per_pair), 0)
        # WETH/USDC has 4 drift values, WBTC/WETH has 2
        self.assertEqual(per_pair[0]["pair"], "WETH/USDC")
        self.assertEqual(per_pair[0]["signal_count"], 4)
        self.assertIn("median_drift_bps", per_pair[0])
        self.assertIn("p90_drift_pct", per_pair[0])

    def test_per_pair_signal_drift_max_10(self):
        signals = [
            {"pair": f"PAIR{i}/USDC", "buy_notional_drift_pct": 5.0}
            for i in range(15)
        ]
        result = self._build(spread_signals=signals)
        self.assertLessEqual(len(result["per_pair_signal_drift"]), 10)


class TestStartBlockerClassification(unittest.TestCase):
    """Test start.py reads blocker_classification from config YAML."""

    def test_reads_blocker_classification(self):
        import tempfile, os
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("chain: zksync\nrun_kind: COVERAGE\nblocker_classification: SYSTEM\nblocker_reason: single_dex_fallback\n")
            f.flush()
            import start
            meta = start.read_config_meta(f.name)
        os.unlink(f.name)
        self.assertEqual(meta["blocker_classification"], "SYSTEM")
        self.assertEqual(meta["blocker_reason"], "single_dex_fallback")

    def test_blocker_defaults_to_none(self):
        import tempfile, os
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("chain: arbitrum_one\nrun_kind: NORMAL\n")
            f.flush()
            import start
            meta = start.read_config_meta(f.name)
        os.unlink(f.name)
        self.assertIsNone(meta["blocker_classification"])
        self.assertIsNone(meta["blocker_reason"])


class TestStartDashboardDefaultOn(unittest.TestCase):
    """Test start.py dashboard default-on (R20: --no-dashboard opt-out)."""

    def test_dashboard_on_by_default(self):
        """Without any dashboard flag, dashboard should be ON (no_dashboard=False)."""
        import start
        args = start.parse_args(["--config", "test.yaml"])
        self.assertFalse(args.no_dashboard)

    def test_no_dashboard_disables(self):
        import start
        args = start.parse_args(["--config", "test.yaml", "--no-dashboard"])
        self.assertTrue(args.no_dashboard)

    def test_dashboard_flag_backward_compat(self):
        """--dashboard still accepted (no-op, backward compat)."""
        import start
        args = start.parse_args(["--config", "test.yaml", "--dashboard"])
        self.assertTrue(args.dashboard)
        self.assertFalse(args.no_dashboard)

    def test_dashboard_port_default(self):
        import start
        args = start.parse_args(["--config", "test.yaml"])
        self.assertEqual(args.dashboard_port, 8099)

    def test_dashboard_port_custom(self):
        import start
        args = start.parse_args(["--config", "test.yaml", "--dashboard-port", "9000"])
        self.assertEqual(args.dashboard_port, 9000)


class TestDriftPropagationContract(unittest.TestCase):
    """Test drift fields propagate correctly through the artifact chain."""

    def test_truth_data_has_drift_summary(self):
        """build_truth_data() must include drift_summary with all R20 keys."""
        from strategy.artifacts import build_truth_data
        config = {"chain_id": 42161, "chain": "arbitrum_one", "paper_size_usd": 1000, "gas_usd_estimate": 0.10}
        stats = {"quotes_total": 10, "quotes_fetched": 8, "dexes_active": 2,
                 "price_sanity_passed": 8, "price_sanity_failed": 2}
        truth = build_truth_data(config, stats, 12345, [], [], {}, 50, 10)
        ds = truth["drift_summary"]
        for key in ("drift_excluded_count", "drift_rejection_rate",
                     "signal_drift_median_pct", "signal_drift_median_bps",
                     "signal_drift_p90_pct", "signal_drift_p90_bps",
                     "worst_pairs_by_drift", "per_pair_signal_drift",
                     "pairs_with_drift_data", "pairs_with_exclusions"):
            self.assertIn(key, ds, f"Missing drift key: {key}")

    def test_rolling_per_run_drift_fields(self):
        """Per-run entry in rolling agg must have drift fields including bps."""
        import tempfile, json
        from pathlib import Path
        from m4.rolling_store import emit_to_aggregator_light
        with tempfile.TemporaryDirectory() as td:
            agg_path = Path(td) / "agg.json"
            run_summary = {
                "run_id": "test_run_1",
                "timestamp": "2026-03-13T00:00:00Z",
                "status": "PASS",
                "metrics": {
                    "total_net_usdc": 1.0,
                    "included_signals_count": 3,
                    "drift_summary": {
                        "drift_excluded_count": 2,
                        "drift_rejection_rate": 0.1,
                        "signal_drift_median_pct": 5.0,
                        "signal_drift_p90_pct": 12.0,
                        "signal_drift_median_bps": 500.0,
                        "pairs_with_drift_data": 3,
                        "pairs_with_exclusions": 1,
                    },
                },
                "inputs": {"run_mode": "REGISTRY_REAL", "chain_id": 42161, "chain_key": "arbitrum_one"},
            }
            result = emit_to_aggregator_light(run_summary, agg_path, max_runs=200)
            run_entry = result["runs"][-1]
            self.assertEqual(run_entry["drift_excluded_count"], 2)
            self.assertEqual(run_entry["drift_signal_median_bps"], 500.0)
            self.assertEqual(run_entry["drift_pairs_with_data"], 3)

    def test_per_chain_frontier_has_drift(self):
        """per_chain_frontier in quick_stats must include per-chain drift aggregates."""
        from m4.rolling_store import _compute_per_chain_frontier
        runs = [
            {"chain_key": "arb", "sweep_gap_to_zero_bps": 5.0,
             "drift_excluded_count": 1, "drift_rejection_rate": 0.05,
             "drift_signal_median_pct": 3.0},
            {"chain_key": "arb", "sweep_gap_to_zero_bps": 8.0,
             "drift_excluded_count": 2, "drift_rejection_rate": 0.10,
             "drift_signal_median_pct": 4.0},
        ]
        result = _compute_per_chain_frontier(runs, {"arb"}, lambda vals, p: sorted(vals)[len(vals)//2] if vals else None)
        arb = result["arb"]
        self.assertEqual(arb["drift_excluded_total"], 3)
        self.assertIsNotNone(arb["drift_rejection_rate_median"])
        self.assertIsNotNone(arb["drift_signal_median_pct_p50"])


class TestDashboardHtmlPanels(unittest.TestCase):
    """Test dashboard.html has all 10 panels."""

    def test_all_10_panels_present(self):
        from pathlib import Path
        html = (Path(__file__).parent.parent.parent / "monitoring" / "dashboard.html").read_text(encoding="utf-8")
        for i in range(1, 11):
            self.assertIn(f"<h2>{i}.", html, f"Missing panel {i}")

    def test_panel_10_is_truth_probe_targets(self):
        from pathlib import Path
        html = (Path(__file__).parent.parent.parent / "monitoring" / "dashboard.html").read_text(encoding="utf-8")
        self.assertIn("Truth-Probe Targets", html)
        self.assertIn("renderProbeTargets", html)

    def test_drift_panel_has_bps_fields(self):
        from pathlib import Path
        html = (Path(__file__).parent.parent.parent / "monitoring" / "dashboard.html").read_text(encoding="utf-8")
        self.assertIn("median_drift_bps", html)
        self.assertIn("per_pair_signal_drift", html)


class TestR21PerPairDriftSummary(unittest.TestCase):
    """R21: Test per_pair_drift_summary unified block."""

    def _build(self, rejected_quotes=None, spread_signals=None):
        from strategy.artifacts import _build_drift_summary
        return _build_drift_summary(
            rejected_quotes or [],
            spread_signals or [],
        )

    def test_per_pair_drift_summary_present(self):
        result = self._build()
        self.assertIn("per_pair_drift_summary", result)
        self.assertIsInstance(result["per_pair_drift_summary"], list)

    def test_per_pair_drift_summary_merges_excluded_and_included(self):
        rejects = [
            {"reason": "NOTIONAL_DRIFT_EXCLUDED", "pair": "WETH/USDC", "notional_drift_pct": 25.0},
        ]
        signals = [
            {"pair": "WETH/USDC", "buy_notional_drift_pct": 5.0, "sell_notional_drift_pct": 8.0},
        ]
        result = self._build(rejected_quotes=rejects, spread_signals=signals)
        summary = result["per_pair_drift_summary"]
        self.assertGreater(len(summary), 0)
        weth = next(p for p in summary if p["pair"] == "WETH/USDC")
        self.assertEqual(weth["excluded_count"], 1)
        self.assertEqual(weth["included_count"], 2)
        self.assertIn("notional_drift_median_bps", weth)
        self.assertIn("notional_drift_p90_bps", weth)
        self.assertIn("notional_drift_max_bps", weth)

    def test_per_pair_drift_summary_sorted_by_median_desc(self):
        signals = [
            {"pair": "WETH/USDC", "buy_notional_drift_pct": 5.0},
            {"pair": "WBTC/WETH", "buy_notional_drift_pct": 20.0},
        ]
        result = self._build(spread_signals=signals)
        summary = result["per_pair_drift_summary"]
        if len(summary) >= 2:
            self.assertGreaterEqual(
                summary[0]["notional_drift_median_bps"],
                summary[1]["notional_drift_median_bps"],
            )

    def test_notional_drift_bps_canonical_field(self):
        """R21: notional_drift_bps should be present as canonical aggregate."""
        signals = [
            {"pair": "WETH/USDC", "buy_notional_drift_pct": 5.0, "sell_notional_drift_pct": 8.0},
        ]
        result = self._build(spread_signals=signals)
        self.assertIn("notional_drift_bps", result)
        self.assertIsInstance(result["notional_drift_bps"], float)
        # Should be signal_drift_median_bps alias
        self.assertEqual(result["notional_drift_bps"], result["signal_drift_median_bps"])

    def test_per_pair_drift_summary_excluded_only_pair(self):
        rejects = [
            {"reason": "NOTIONAL_DRIFT_EXCLUDED", "pair": "BAD/PAIR", "notional_drift_pct": 50.0},
        ]
        result = self._build(rejected_quotes=rejects)
        summary = result["per_pair_drift_summary"]
        self.assertGreater(len(summary), 0)
        bad = next(p for p in summary if p["pair"] == "BAD/PAIR")
        self.assertEqual(bad["excluded_count"], 1)
        self.assertEqual(bad["included_count"], 0)
        self.assertEqual(bad["drift_reject_reason"], "NOTIONAL_DRIFT_EXCLUDED")

    def test_per_pair_drift_summary_included_only_pair(self):
        signals = [
            {"pair": "GOOD/PAIR", "buy_notional_drift_pct": 2.0, "sell_notional_drift_pct": 3.0},
        ]
        result = self._build(spread_signals=signals)
        summary = result["per_pair_drift_summary"]
        good = next(p for p in summary if p["pair"] == "GOOD/PAIR")
        self.assertEqual(good["excluded_count"], 0)
        self.assertEqual(good["included_count"], 2)
        self.assertIsNone(good["drift_reject_reason"])


class TestR21OperationalTruth(unittest.TestCase):
    """R21: Test operational_truth_source field in truth_data."""

    def test_truth_data_has_operational_truth_source(self):
        from strategy.artifacts import build_truth_data
        config = {"chain_id": 42161, "chain": "arbitrum_one", "paper_size_usd": 1000, "gas_usd_estimate": 0.10}
        stats = {"quotes_total": 10, "quotes_fetched": 8, "dexes_active": 2,
                 "price_sanity_passed": 8, "price_sanity_failed": 2}
        truth = build_truth_data(config, stats, 12345, [], [], {}, 50, 10)
        self.assertEqual(truth["operational_truth_source"], "measured_economics")
        self.assertIn("measured_economics", truth)


class TestR21PerChainDriftSummary(unittest.TestCase):
    """R21: Test per_chain_drift_summary in start.py."""

    def test_compute_per_chain_drift_summary(self):
        from start import _compute_per_chain_drift_summary
        per_chain = {
            "arb": {
                "_drift_rejection_rates": [0.05, 0.10],
                "_drift_median_bps_values": [2.0, 3.0],
                "drift_excluded_total": 5,
                "drift_pairs_with_data_total": 8,
            },
            "base": {
                "_drift_rejection_rates": [],
                "_drift_median_bps_values": [],
                "drift_excluded_total": 0,
                "drift_pairs_with_data_total": 0,
            },
        }
        result = _compute_per_chain_drift_summary(per_chain)
        self.assertIn("arb", result)
        self.assertIn("base", result)
        self.assertEqual(result["arb"]["drift_excluded_total"], 5)
        self.assertIsNotNone(result["arb"]["notional_drift_median_bps"])
        self.assertIsNone(result["base"]["notional_drift_median_bps"])
        self.assertEqual(result["arb"]["runs_sampled"], 2)

    def test_compute_universe_split(self):
        from start import _compute_universe_split
        per_chain = {
            "arb": {"run_kind": "NORMAL", "accepted_fail": False},
            "base": {"run_kind": "COVERAGE", "accepted_fail": False},
            "scroll": {"run_kind": "COVERAGE", "accepted_fail": True},
        }
        result = _compute_universe_split(per_chain, ["arb"], ["scroll"])
        self.assertEqual(result["truth_probe_chains"], ["arb"])
        self.assertEqual(result["discovery_chains"], ["base"])
        self.assertEqual(result["monitoring_only_chains"], ["scroll"])
        self.assertEqual(result["total_chains"], 3)


class TestR21FrontierDrift(unittest.TestCase):
    """R21: Test frontier_ranking includes drift metrics."""

    def test_frontier_ranking_has_drift_fields(self):
        from start import _compute_frontier_ranking
        per_chain = {
            "arb": {
                "sweep_gap_to_zero_bps": 5.0,
                "sweep_best_net_pnl_bps": -3.0,
                "included_signals_total": 10,
                "last_cross_dex_pairs_count": 3,
                "accepted_fail": False,
                "sweep_best_size_usd": 100,
                "sweep_best_pair": "WETH/USDC",
                "sweep_measured_gas_bps": 1.5,
                "sweep_measured_fee_bps": 0.5,
                "sweep_measured_slippage_bps": 2.0,
                "sweep_measured_total_cost_bps": 4.0,
                "_sweep_gap_values": [5.0, 6.0],
                "runs_with_sweep": 2,
                "_drift_rejection_rates": [0.05],
                "_drift_median_bps_values": [2.5],
                "drift_excluded_total": 3,
                "drift_pairs_with_data_total": 5,
            },
        }
        ranking = _compute_frontier_ranking(per_chain)
        self.assertGreater(len(ranking), 0)
        arb = ranking[0]
        self.assertIn("drift_rejection_rate_median", arb)
        self.assertIn("notional_drift_median_bps", arb)
        self.assertIn("drift_excluded_total", arb)
        self.assertIn("drift_pairs_with_data_total", arb)

    def test_rolling_per_chain_frontier_has_notional_drift_bps(self):
        """R21: per_chain_frontier must include notional_drift_median_bps."""
        from m4.rolling_store import _compute_per_chain_frontier
        runs = [
            {"chain_key": "arb", "sweep_gap_to_zero_bps": 5.0,
             "drift_excluded_count": 1, "drift_rejection_rate": 0.05,
             "drift_signal_median_pct": 3.0, "notional_drift_bps": 300.0},
        ]
        result = _compute_per_chain_frontier(runs, {"arb"}, lambda vals, p: sorted(vals)[len(vals)//2] if vals else None)
        self.assertIn("notional_drift_median_bps", result["arb"])
        self.assertEqual(result["arb"]["notional_drift_median_bps"], 300.0)


class TestR21DashboardEnhancements(unittest.TestCase):
    """R21: Test dashboard enhancements."""

    def test_dashboard_has_drift_bps_in_frontier(self):
        from pathlib import Path
        html = (Path(__file__).parent.parent.parent / "monitoring" / "dashboard.html").read_text(encoding="utf-8")
        self.assertIn("notional_drift_median_bps", html)
        self.assertIn("Drift bps", html)

    def test_dashboard_has_per_pair_drift_summary(self):
        from pathlib import Path
        html = (Path(__file__).parent.parent.parent / "monitoring" / "dashboard.html").read_text(encoding="utf-8")
        self.assertIn("per_pair_drift_summary", html)

    def test_dashboard_has_measured_cost_in_probes(self):
        from pathlib import Path
        html = (Path(__file__).parent.parent.parent / "monitoring" / "dashboard.html").read_text(encoding="utf-8")
        self.assertIn("measured_total_cost_bps", html)
        self.assertIn("Cost bps", html)


if __name__ == "__main__":
    unittest.main()
