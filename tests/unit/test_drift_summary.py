# PATH: tests/unit/test_drift_summary.py
"""
Unit tests for NOTIONAL_DRIFT first-class artifact layer (R19).

Tests for:
- _build_drift_summary() contract
- drift_summary propagation through truth_data
- drift fields in rolling per-run entry
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

    def test_required_keys_present(self):
        result = self._build()
        for key in (
            "drift_excluded_count",
            "drift_rejection_rate",
            "signal_drift_median_pct",
            "signal_drift_p90_pct",
            "worst_pairs_by_drift",
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
            {"buy_notional_drift_pct": 5.0, "sell_notional_drift_pct": 8.0},
            {"buy_notional_drift_pct": 3.0, "sell_notional_drift_pct": 12.0},
        ]
        result = self._build(spread_signals=signals)
        self.assertGreater(result["signal_drift_median_pct"], 0)
        self.assertGreater(result["signal_drift_p90_pct"], 0)

    def test_rejection_rate_bounded(self):
        rejects = [
            {"reason": "NOTIONAL_DRIFT_EXCLUDED", "pair": "A/B", "notional_drift_pct": 25},
        ]
        signals = [
            {"buy_notional_drift_pct": 5.0, "sell_notional_drift_pct": 8.0},
        ]
        result = self._build(rejected_quotes=rejects, spread_signals=signals)
        self.assertGreaterEqual(result["drift_rejection_rate"], 0)
        self.assertLessEqual(result["drift_rejection_rate"], 1.0)


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


class TestStartDashboardFlag(unittest.TestCase):
    """Test start.py --dashboard argument parsing."""

    def test_dashboard_flag_defaults_false(self):
        import start
        args = start.parse_args(["--config", "test.yaml"])
        self.assertFalse(args.dashboard)

    def test_dashboard_flag_parsed(self):
        import start
        args = start.parse_args(["--config", "test.yaml", "--dashboard"])
        self.assertTrue(args.dashboard)

    def test_dashboard_port_default(self):
        import start
        args = start.parse_args(["--config", "test.yaml", "--dashboard"])
        self.assertEqual(args.dashboard_port, 8099)

    def test_dashboard_port_custom(self):
        import start
        args = start.parse_args(["--config", "test.yaml", "--dashboard", "--dashboard-port", "9000"])
        self.assertEqual(args.dashboard_port, 9000)


if __name__ == "__main__":
    unittest.main()
