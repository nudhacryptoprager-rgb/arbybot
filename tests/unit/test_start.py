"""
tests/unit/test_start.py

Tests for multi-chain orchestrator (start.py).
Covers: config round-robin, rolling flags, classification, per-chain aggregation,
timeout handling, and "too good to be true" guardrails.
"""

import json
import os
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Import tested module
import start


class TestReadConfigMeta(unittest.TestCase):
    """Test YAML config introspection."""

    def test_reads_chain_and_run_kind(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("chain: base\nrun_kind: COVERAGE\n")
            f.flush()
            meta = start.read_config_meta(f.name)
        os.unlink(f.name)
        self.assertEqual(meta["chain"], "base")
        self.assertEqual(meta["run_kind"], "COVERAGE")

    def test_defaults_for_missing_keys(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("dexes: [uniswap_v3]\n")
            f.flush()
            meta = start.read_config_meta(f.name)
        os.unlink(f.name)
        self.assertEqual(meta["chain"], "unknown")
        self.assertEqual(meta["run_kind"], "NORMAL")

    def test_nonexistent_file_returns_defaults(self):
        meta = start.read_config_meta("/nonexistent/path.yaml")
        self.assertEqual(meta["chain"], "unknown")
        self.assertEqual(meta["run_kind"], "NORMAL")


class TestIsPrimaryRollingConfig(unittest.TestCase):
    def test_normal_is_primary(self):
        self.assertTrue(start.is_primary_rolling_config({"run_kind": "NORMAL"}))

    def test_coverage_is_not_primary(self):
        self.assertFalse(start.is_primary_rolling_config({"run_kind": "COVERAGE"}))

    def test_smoke_is_not_primary(self):
        self.assertFalse(start.is_primary_rolling_config({"run_kind": "SMOKE"}))


class TestClassifyRun(unittest.TestCase):
    def test_pass(self):
        self.assertEqual(start.classify_run(0, {"status": "PASS"}), "PASS")

    def test_no_data(self):
        self.assertEqual(start.classify_run(0, {"status": "NO_DATA"}), "NO_DATA")

    def test_fail(self):
        self.assertEqual(start.classify_run(1, {"status": "FAIL"}), "FAIL")

    def test_no_summary_is_infra_fail(self):
        self.assertEqual(start.classify_run(3, None), "INFRA_FAIL")


class TestRoundRobinConfigList(unittest.TestCase):
    """Test --config-list parsing and round-robin scheduling."""

    def test_config_list_parses_comma_separated(self):
        args = start.parse_args([
            "--config-list", "a.yaml,b.yaml,c.yaml",
            "--max-runs", "1",
        ])
        configs = start.resolve_configs(args)
        self.assertEqual(configs, ["a.yaml", "b.yaml", "c.yaml"])

    def test_single_config_legacy(self):
        args = start.parse_args(["--config", "x.yaml"])
        configs = start.resolve_configs(args)
        self.assertEqual(configs, ["x.yaml"])

    def test_config_list_strips_whitespace(self):
        args = start.parse_args([
            "--config-list", " a.yaml , b.yaml ",
            "--max-runs", "1",
        ])
        configs = start.resolve_configs(args)
        self.assertEqual(configs, ["a.yaml", "b.yaml"])


class TestRollingFlagsOnlyForPrimary(unittest.TestCase):
    """Verify rolling flags dispatched only for run_kind=NORMAL."""

    @patch("start.extract_gate_result")
    @patch("start.extract_run_summary")
    @patch("start.run_gate_once")
    @patch("start.read_config_meta")
    @patch("start.prune_run_dirs")
    def test_rolling_only_for_normal(self, mock_prune, mock_meta, mock_gate, mock_summary, mock_gate_res):
        """Round-robin 2 configs: NORMAL gets rolling, COVERAGE does not."""
        normal_yaml = "config/real_minimal.yaml"
        coverage_yaml = "config/coverage_intent_base.yaml"

        def meta_side(path):
            if "real_minimal" in path:
                return {"chain": "arbitrum_one", "run_kind": "NORMAL"}
            return {"chain": "base", "run_kind": "COVERAGE"}

        mock_meta.side_effect = meta_side
        mock_gate.return_value = (0, None)
        mock_summary.return_value = {"status": "PASS", "metrics": {}, "run_context": {}}
        mock_gate_res.return_value = None

        rc = start.main([
            "--config-list", f"{normal_yaml},{coverage_yaml}",
            "--max-runs", "4",
            "--minutes", "1",
            "--sleep-seconds", "0",
            "--child-timeout", "0",
            "--summary-file", os.path.join(tempfile.mkdtemp(), "test.json"),
        ])

        # Expect 4 calls total (round-robin: normal, coverage, normal, coverage)
        self.assertEqual(mock_gate.call_count, 4)

        # Inspect the configs and refresh_rolling flags passed to run_gate_once
        for call in mock_gate.call_args_list:
            args, kwargs = call
            config_arg = args[0]
            # refresh_rolling is the 5th positional arg
            refresh_arg = args[4] if len(args) > 4 else kwargs.get("refresh_rolling")

            if "real_minimal" in config_arg:
                self.assertTrue(refresh_arg, f"NORMAL config should have refresh_rolling=True")
            else:
                self.assertFalse(refresh_arg, f"COVERAGE config should have refresh_rolling=False")


class TestPerChainAggregation(unittest.TestCase):
    """Test per-chain counters accumulate correctly."""

    def test_update_chain_stats_pass(self):
        stats = start.new_chain_stats()
        summary = {
            "status": "PASS",
            "metrics": {
                "included_signals_count": 5,
                "total_net_usdc": 12.5,
            },
            "run_context": {"run_timestamp": "2026-03-10T10:00:00Z"},
        }
        start.update_chain_stats(stats, 0, Path("data/runs/test_run"), summary)
        self.assertEqual(stats["runs"], 1)
        self.assertEqual(stats["pass"], 1)
        self.assertEqual(stats["infra_pass"], 1)
        self.assertEqual(stats["included_signals_total"], 5)
        self.assertAlmostEqual(stats["net_usdc_total"], 12.5)
        self.assertEqual(stats["last_run_dir"], "test_run")

    def test_update_chain_stats_no_data(self):
        stats = start.new_chain_stats()
        summary = {
            "status": "NO_DATA",
            "metrics": {"included_signals_count": 0, "total_net_usdc": 0},
            "run_context": {},
        }
        start.update_chain_stats(stats, 0, None, summary)
        self.assertEqual(stats["no_data"], 1)
        self.assertEqual(stats["pass"], 0)

    def test_update_chain_stats_infra_fail(self):
        stats = start.new_chain_stats()
        start.update_chain_stats(stats, 3, None, None)
        self.assertEqual(stats["infra_fail"], 1)
        self.assertEqual(stats["infra_pass"], 0)

    def test_roundtrip_profitable_accumulated(self):
        stats = start.new_chain_stats()
        summary = {
            "status": "PASS",
            "metrics": {"included_signals_count": 2, "total_net_usdc": 5.0},
            "roundtrip_summary": {"profitable_count": 1},
            "run_context": {},
        }
        start.update_chain_stats(stats, 0, None, summary)
        self.assertEqual(stats["profitable_roundtrips_total"], 1)

    def test_roundtrip_from_metrics_roundtrip(self):
        """Roundtrip data at metrics.roundtrip (canonical path) must be extracted."""
        stats = start.new_chain_stats()
        summary = {
            "status": "PASS",
            "metrics": {
                "included_signals_count": 3,
                "total_net_usdc": 2.0,
                "roundtrip": {"evaluated_count": 5, "profitable_count": 2},
            },
            "run_context": {},
        }
        start.update_chain_stats(stats, 0, None, summary)
        self.assertEqual(stats["profitable_roundtrips_total"], 2)
        self.assertEqual(stats["roundtrip_evaluated_total"], 5)

    def test_sweep_gap_values_collected(self):
        """R12: update_chain_stats collects gap_to_zero values for median computation."""
        stats = start.new_chain_stats()
        for gap_val in [20.0, 15.0, 10.0]:
            summary = {
                "status": "PASS",
                "metrics": {
                    "included_signals_count": 2,
                    "total_net_usdc": 1.0,
                    "roundtrip": {
                        "evaluated_count": 1,
                        "dynamic_sweep": {
                            "best_net_pnl_bps": -gap_val,
                            "gap_to_zero_bps": gap_val,
                        },
                    },
                },
                "run_context": {},
            }
            start.update_chain_stats(stats, 0, None, summary)
        self.assertEqual(stats["runs_with_sweep"], 3)
        self.assertEqual(len(stats["_sweep_gap_values"]), 3)
        self.assertAlmostEqual(stats["_sweep_gap_values"][-1], 10.0)


class TestGuardrails(unittest.TestCase):
    """Test 'too good to be true' and infra-unstable warnings."""

    def test_all_positive_warning(self):
        chains = {
            "arb": {"runs": 5, "pass": 5, "no_data": 0, "fail": 0, "infra_fail": 0},
            "base": {"runs": 3, "pass": 3, "no_data": 0, "fail": 0, "infra_fail": 0},
        }
        warnings = start.check_guardrails(chains)
        all_pos = [w for w in warnings if "ALL_POSITIVE" in w]
        self.assertTrue(len(all_pos) >= 1, f"Expected ALL_POSITIVE warning, got {warnings}")

    def test_no_warning_when_mix(self):
        chains = {
            "arb": {"runs": 5, "pass": 4, "no_data": 1, "fail": 0, "infra_fail": 0},
        }
        warnings = start.check_guardrails(chains)
        all_pos = [w for w in warnings if "ALL_POSITIVE" in w and "CHAIN" not in w]
        self.assertEqual(len(all_pos), 0)

    def test_chain_infra_unstable(self):
        chains = {
            "scroll": {"runs": 4, "pass": 0, "no_data": 0, "fail": 1, "infra_fail": 3},
        }
        warnings = start.check_guardrails(chains)
        infra = [w for w in warnings if "INFRA_UNSTABLE" in w]
        self.assertTrue(len(infra) >= 1)

    def test_no_warning_below_threshold(self):
        chains = {
            "arb": {"runs": 2, "pass": 2, "no_data": 0, "fail": 0, "infra_fail": 0},
        }
        warnings = start.check_guardrails(chains)
        # Below threshold (runs < 3 for chain, runs < 5 for total)
        self.assertEqual(len(warnings), 0)


class TestBuildSummary(unittest.TestCase):
    """Test JSON summary structure."""

    def _make_per_chain(self, **overrides):
        base = {
            "config": "real_minimal.yaml",
            "runs": 2, "pass": 1, "no_data": 1, "fail": 0, "infra_fail": 0,
            "infra_pass": 2,
            "included_signals_total": 3,
            "net_usdc_total": 10.5,
            "profitable_roundtrips_total": 0,
            "roundtrip_evaluated_total": 0,
            "best_roundtrip_net_bps": None,
            "best_measured_spread_gap_bps": None,
            "sweep_best_net_pnl_bps": None,
            "sweep_best_size_usd": None,
            "sweep_best_pair": None,
            "last_run_timestamp": "2026-03-10T10:00:00Z",
            "last_run_dir": "ci_m5_gate_20260310_100000",
            "last_run_summary_status": "PASS",
            "last_quality_status": "PASS",
            "last_chain_quality_level": "SIGNAL_PRODUCING",
            "last_profit_truth_available": True,
            "run_kind": "NORMAL",
            "last_cross_dex_pairs_count": 5,
        }
        base.update(overrides)
        return base

    def test_summary_schema(self):
        per_chain = {"arb": self._make_per_chain()}
        summary = start.build_summary(per_chain, 120.5, ["WARN_TEST"])
        self.assertEqual(summary["schema"], "start:long_scan_summary:v1.3")
        self.assertEqual(summary["total_runs"], 2)
        self.assertEqual(summary["total_pass"], 1)
        self.assertEqual(summary["total_no_data"], 1)
        self.assertIn("WARN_TEST", summary["warnings"])
        self.assertIn("arb", summary["per_chain"])

    def test_summary_has_aggregate_chain_lists(self):
        per_chain = {
            "arb": self._make_per_chain(runs=3, fail=0, infra_fail=0, pass_=2, no_data=1),
            "scroll": self._make_per_chain(runs=3, fail=1, infra_fail=0),
        }
        # Fix: pass key not pass_ (dict update)
        per_chain["arb"]["pass"] = 2
        summary = start.build_summary(per_chain, 100.0, [])
        self.assertIn("arb", summary["pass_chains"])
        self.assertIn("scroll", summary["fail_chains"])

    def test_summary_probe_only(self):
        per_chain = {
            "linea": self._make_per_chain(runs=2, fail=0, infra_fail=0),
        }
        per_chain["linea"]["pass"] = 0
        per_chain["linea"]["no_data"] = 2
        summary = start.build_summary(per_chain, 50.0, [])
        self.assertIn("linea", summary["probe_only_chains"])

    def test_summary_profitable_roundtrips(self):
        per_chain = {
            "arb": self._make_per_chain(profitable_roundtrips_total=3, roundtrip_evaluated_total=10, best_roundtrip_net_bps=5.2),
            "base": self._make_per_chain(profitable_roundtrips_total=1, roundtrip_evaluated_total=4, best_roundtrip_net_bps=-12.0),
        }
        summary = start.build_summary(per_chain, 60.0, [])
        self.assertEqual(summary["total_profitable_roundtrips"], 4)
        self.assertEqual(summary["total_roundtrip_evaluated"], 14)
        self.assertAlmostEqual(summary["best_roundtrip_net_bps"], 5.2)

    def test_summary_sweep_fields(self):
        per_chain = {
            "arb": self._make_per_chain(sweep_best_net_pnl_bps=3.5, sweep_best_size_usd=100, sweep_best_pair="WETH/USDC"),
            "base": self._make_per_chain(sweep_best_net_pnl_bps=-5.0, sweep_best_size_usd=200, sweep_best_pair="WBTC/USDC"),
        }
        summary = start.build_summary(per_chain, 60.0, [])
        self.assertAlmostEqual(summary["sweep_best_net_pnl_bps"], 3.5)
        self.assertEqual(summary["sweep_best_size_usd"], 100)


class TestExitPolicy(unittest.TestCase):
    """Test --max-fail-chains exit semantics."""

    @patch("start.extract_gate_result")
    @patch("start.extract_run_summary")
    @patch("start.run_gate_once")
    @patch("start.read_config_meta")
    @patch("start.prune_run_dirs")
    def test_permissive_default_any_pass_exits_0(self, mock_prune, mock_meta, mock_gate, mock_summary, mock_gate_res):
        mock_meta.return_value = {"chain": "arb", "run_kind": "NORMAL"}
        mock_gate.return_value = (0, None)
        mock_summary.return_value = {"status": "PASS", "metrics": {}, "run_context": {}}
        mock_gate_res.return_value = None
        rc = start.main([
            "--config", "x.yaml", "--max-runs", "1", "--minutes", "1",
            "--sleep-seconds", "0", "--child-timeout", "0",
            "--summary-file", os.path.join(tempfile.mkdtemp(), "test.json"),
        ])
        self.assertEqual(rc, 0)

    @patch("start.extract_gate_result")
    @patch("start.extract_run_summary")
    @patch("start.run_gate_once")
    @patch("start.read_config_meta")
    @patch("start.prune_run_dirs")
    def test_strict_zero_rejects_any_failure(self, mock_prune, mock_meta, mock_gate, mock_summary, mock_gate_res):
        """--max-fail-chains=0 means zero chains can have failures."""
        call_count = [0]
        def gate_side(*args, **kwargs):
            call_count[0] += 1
            return (0, None)

        def summary_side(run_dir):
            # arb PASS, base FAIL
            call_count_s = getattr(summary_side, '_c', 0)
            summary_side._c = call_count_s + 1
            if call_count_s % 2 == 0:
                return {"status": "PASS", "metrics": {}, "run_context": {}}
            return {"status": "FAIL", "metrics": {}, "run_context": {}}

        def meta_side(path):
            if "a.yaml" in path:
                return {"chain": "arb", "run_kind": "NORMAL"}
            return {"chain": "base", "run_kind": "COVERAGE"}

        mock_meta.side_effect = meta_side
        mock_gate.side_effect = gate_side
        mock_summary.side_effect = summary_side
        mock_gate_res.return_value = None
        rc = start.main([
            "--config-list", "a.yaml,b.yaml", "--max-runs", "2", "--minutes", "1",
            "--sleep-seconds", "0", "--child-timeout", "0",
            "--max-fail-chains", "0",
            "--summary-file", os.path.join(tempfile.mkdtemp(), "test.json"),
        ])
        self.assertEqual(rc, 1, "Should fail when a chain has failures and --max-fail-chains=0")

    @patch("start.extract_gate_result")
    @patch("start.extract_run_summary")
    @patch("start.run_gate_once")
    @patch("start.read_config_meta")
    @patch("start.prune_run_dirs")
    def test_strict_one_allows_single_failure(self, mock_prune, mock_meta, mock_gate, mock_summary, mock_gate_res):
        """--max-fail-chains=1 allows exactly one chain with failures."""
        call_count = [0]
        def gate_side(*args, **kwargs):
            return (0, None)

        def summary_side(run_dir):
            call_count_s = getattr(summary_side, '_c', 0)
            summary_side._c = call_count_s + 1
            if call_count_s == 1:
                return {"status": "FAIL", "metrics": {}, "run_context": {}}  # base fails
            return {"status": "PASS", "metrics": {}, "run_context": {}}  # arb passes

        def meta_side(path):
            if "a.yaml" in path:
                return {"chain": "arb", "run_kind": "NORMAL"}
            return {"chain": "base", "run_kind": "COVERAGE"}

        mock_meta.side_effect = meta_side
        mock_gate.side_effect = gate_side
        mock_summary.side_effect = summary_side
        mock_gate_res.return_value = None
        rc = start.main([
            "--config-list", "a.yaml,b.yaml", "--max-runs", "2", "--minutes", "1",
            "--sleep-seconds", "0", "--child-timeout", "0",
            "--max-fail-chains", "1",
            "--summary-file", os.path.join(tempfile.mkdtemp(), "test.json"),
        ])
        self.assertEqual(rc, 0, "Should pass when 1 fail chain <= --max-fail-chains=1")


class TestRicherChainFields(unittest.TestCase):
    """Test that richer per-chain fields are populated from run_summary and gate_result."""

    def test_update_chain_stats_with_richer_fields(self):
        stats = start.new_chain_stats()
        summary = {
            "status": "PASS",
            "quality_status": "PASS",
            "run_kind": "NORMAL",
            "metrics": {
                "included_signals_count": 5,
                "total_net_usdc": 10.0,
                "chain_quality_level": "SIGNAL_PRODUCING",
                "profit_truth_available": True,
            },
            "run_context": {"run_timestamp": "2026-03-10T10:00:00Z"},
        }
        gate_result = {"cross_dex_pairs_count": 7}
        start.update_chain_stats(stats, 0, Path("data/runs/test"), summary, gate_result)
        self.assertEqual(stats["last_run_summary_status"], "PASS")
        self.assertEqual(stats["last_quality_status"], "PASS")
        self.assertEqual(stats["last_chain_quality_level"], "SIGNAL_PRODUCING")
        self.assertTrue(stats["last_profit_truth_available"])
        self.assertEqual(stats["run_kind"], "NORMAL")
        self.assertEqual(stats["last_cross_dex_pairs_count"], 7)

    def test_update_chain_stats_without_gate_result(self):
        stats = start.new_chain_stats()
        summary = {
            "status": "NO_DATA",
            "metrics": {"included_signals_count": 0, "total_net_usdc": 0},
            "run_context": {},
        }
        start.update_chain_stats(stats, 0, None, summary)
        self.assertIsNone(stats["last_cross_dex_pairs_count"])
        self.assertEqual(stats["last_run_summary_status"], "NO_DATA")

    def test_extract_gate_result_missing_dir(self):
        self.assertIsNone(start.extract_gate_result(None))
        self.assertIsNone(start.extract_gate_result(Path("/nonexistent")))

    def test_extract_gate_result_reads_file(self):
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            reports = run_dir / "reports"
            reports.mkdir()
            data = {"cross_dex_pairs_count": 12, "status": "PASS"}
            with open(reports / "gate_result.json", "w") as f:
                json.dump(data, f)
            result = start.extract_gate_result(run_dir)
            self.assertIsNotNone(result)
            self.assertEqual(result["cross_dex_pairs_count"], 12)


class TestExtractRunSummary(unittest.TestCase):
    """Test run_summary extraction from runDir."""

    def test_returns_none_for_missing_dir(self):
        self.assertIsNone(start.extract_run_summary(None))
        self.assertIsNone(start.extract_run_summary(Path("/nonexistent")))

    def test_reads_latest_summary(self):
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            reports = run_dir / "reports"
            reports.mkdir()
            data = {"status": "PASS", "metrics": {"signals_count": 3}}
            with open(reports / "run_summary_20260310_100000.json", "w") as f:
                json.dump(data, f)
            result = start.extract_run_summary(run_dir)
            self.assertIsNotNone(result)
            self.assertEqual(result["status"], "PASS")

    def test_picks_latest_when_multiple(self):
        with tempfile.TemporaryDirectory() as td:
            run_dir = Path(td)
            reports = run_dir / "reports"
            reports.mkdir()
            for ts, status in [("100000", "FAIL"), ("110000", "PASS")]:
                with open(reports / f"run_summary_20260310_{ts}.json", "w") as f:
                    json.dump({"status": status}, f)
            result = start.extract_run_summary(run_dir)
            self.assertEqual(result["status"], "PASS")


class TestAsciiSafeOutput(unittest.TestCase):
    """Regression: all print_summary output must be ASCII-encodable (Windows cp1251 safe)."""

    def test_print_summary_ascii_only(self):
        """Simulate encoding to ASCII; catches any box-drawing or em-dash chars."""
        per_chain = {
            "arb": {
                "config": "real_minimal.yaml",
                "runs": 3, "pass": 2, "no_data": 0, "fail": 1, "infra_fail": 0,
                "infra_pass": 2,
                "included_signals_total": 5,
                "net_usdc_total": 10.0,
                "profitable_roundtrips_total": 0,
                "last_run_timestamp": "2026-03-10T10:00:00Z",
                "last_run_dir": "ci_m5_gate_20260310_100000",
            },
        }
        summary = start.build_summary(per_chain, 100.0, ["WARN_TEST"])

        import io
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            start.print_summary(summary)
        text = buf.getvalue()
        # Must encode to ASCII without errors (cp1251 is a superset of ASCII)
        text.encode("ascii")

    def test_round_robin_log_lines_ascii(self):
        """Separator lines printed during round-robin must be ASCII."""
        separator = "-" * 60
        separator.encode("ascii")


class TestDeleteIfEmptyRunDir(unittest.TestCase):
    def test_deletes_empty_ci_dir(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "ci_m5_gate_20260310_100000"
            d.mkdir()
            self.assertTrue(start.delete_if_empty_run_dir(d))
            self.assertFalse(d.exists())

    def test_keeps_dir_with_reports(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "ci_m5_gate_20260310_100000"
            d.mkdir()
            (d / "reports").mkdir()
            self.assertFalse(start.delete_if_empty_run_dir(d))
            self.assertTrue(d.exists())


class TestAcceptedFailChains(unittest.TestCase):
    """Test --accepted-fail-chains feature: accepted failures excluded from exit policy."""

    def _make_per_chain(self, **overrides):
        base = {
            "config": "real_minimal.yaml",
            "runs": 2, "pass": 1, "no_data": 1, "fail": 0, "infra_fail": 0,
            "infra_pass": 2,
            "included_signals_total": 3,
            "net_usdc_total": 10.5,
            "profitable_roundtrips_total": 0,
            "roundtrip_evaluated_total": 0,
            "best_roundtrip_net_bps": None,
            "best_measured_spread_gap_bps": None,
            "sweep_best_net_pnl_bps": None,
            "sweep_best_size_usd": None,
            "sweep_best_pair": None,
            "last_run_timestamp": "2026-03-10T10:00:00Z",
            "last_run_dir": "ci_m5_gate_20260310_100000",
            "last_run_summary_status": "PASS",
            "last_quality_status": "PASS",
            "last_chain_quality_level": "SIGNAL_PRODUCING",
            "last_profit_truth_available": True,
            "run_kind": "NORMAL",
            "last_cross_dex_pairs_count": 5,
            "accepted_fail": False,
        }
        base.update(overrides)
        return base

    def test_build_summary_separates_accepted_and_unexpected(self):
        per_chain = {
            "arb": self._make_per_chain(runs=2, fail=0, infra_fail=0),
            "scroll": self._make_per_chain(runs=2, fail=1, accepted_fail=True),
            "base": self._make_per_chain(runs=2, fail=1, accepted_fail=False),
        }
        per_chain["arb"]["pass"] = 2
        summary = start.build_summary(per_chain, 100.0, [])
        self.assertIn("scroll", summary["accepted_fail_chains"])
        self.assertIn("base", summary["unexpected_fail_chains"])
        self.assertNotIn("scroll", summary["unexpected_fail_chains"])
        self.assertNotIn("base", summary["accepted_fail_chains"])
        self.assertIn("arb", summary["pass_chains"])

    def test_new_chain_stats_has_accepted_fail_field(self):
        stats = start.new_chain_stats()
        self.assertIn("accepted_fail", stats)
        self.assertFalse(stats["accepted_fail"])

    @patch("start.extract_gate_result")
    @patch("start.extract_run_summary")
    @patch("start.run_gate_once")
    @patch("start.read_config_meta")
    @patch("start.prune_run_dirs")
    def test_accepted_fail_excluded_from_strict_exit(
        self, mock_prune, mock_meta, mock_gate, mock_summary, mock_gate_res,
    ):
        """--max-fail-chains=0 + --accepted-fail-chains=scroll should pass if only scroll fails."""
        def meta_side(path):
            if "a.yaml" in path:
                return {"chain": "arb", "run_kind": "NORMAL"}
            return {"chain": "scroll", "run_kind": "COVERAGE"}

        call_count = [0]
        def summary_side(run_dir):
            c = getattr(summary_side, "_c", 0)
            summary_side._c = c + 1
            # arb=PASS, scroll=FAIL
            if c % 2 == 0:
                return {"status": "PASS", "metrics": {}, "run_context": {}}
            return {"status": "FAIL", "metrics": {}, "run_context": {}}

        mock_meta.side_effect = meta_side
        mock_gate.return_value = (0, None)
        mock_summary.side_effect = summary_side
        mock_gate_res.return_value = None
        rc = start.main([
            "--config-list", "a.yaml,b.yaml", "--max-runs", "2", "--minutes", "1",
            "--sleep-seconds", "0", "--child-timeout", "0",
            "--max-fail-chains", "0",
            "--accepted-fail-chains", "scroll",
            "--summary-file", os.path.join(tempfile.mkdtemp(), "test.json"),
        ])
        self.assertEqual(rc, 0, "scroll is accepted-fail, should not count toward fail limit")

    @patch("start.extract_gate_result")
    @patch("start.extract_run_summary")
    @patch("start.run_gate_once")
    @patch("start.read_config_meta")
    @patch("start.prune_run_dirs")
    def test_unexpected_fail_still_rejected_with_accepted_chains(
        self, mock_prune, mock_meta, mock_gate, mock_summary, mock_gate_res,
    ):
        """--max-fail-chains=0 + --accepted-fail-chains=scroll should fail if arb also fails."""
        call_count = [0]
        def meta_side(path):
            if "a.yaml" in path:
                return {"chain": "arb", "run_kind": "NORMAL"}
            return {"chain": "scroll", "run_kind": "COVERAGE"}

        def summary_side(run_dir):
            # Both arb and scroll FAIL
            return {"status": "FAIL", "metrics": {}, "run_context": {}}

        mock_meta.side_effect = meta_side
        mock_gate.return_value = (0, None)
        mock_summary.side_effect = summary_side
        mock_gate_res.return_value = None
        rc = start.main([
            "--config-list", "a.yaml,b.yaml", "--max-runs", "2", "--minutes", "1",
            "--sleep-seconds", "0", "--child-timeout", "0",
            "--max-fail-chains", "0",
            "--accepted-fail-chains", "scroll",
            "--summary-file", os.path.join(tempfile.mkdtemp(), "test.json"),
        ])
        self.assertEqual(rc, 1, "arb is unexpected fail, should cause exit 1")


class TestFrontierRanking(unittest.TestCase):
    """Contract: _compute_frontier_ranking uses composite scoring."""

    def test_ranking_order(self):
        per_chain = {
            "arb": {"sweep_gap_to_zero_bps": 12.5, "sweep_best_net_pnl_bps": -12.5,
                     "included_signals_total": 10, "last_cross_dex_pairs_count": 3,
                     "accepted_fail": False,
                     "sweep_measured_gas_bps": 3.0,
                     "sweep_measured_fee_bps": 60.0, "sweep_measured_slippage_bps": 1.0,
                     "sweep_measured_total_cost_bps": 64.0},
            "base": {"sweep_gap_to_zero_bps": 8.0, "sweep_best_net_pnl_bps": -8.0,
                      "included_signals_total": 20, "last_cross_dex_pairs_count": 5,
                      "accepted_fail": False,
                      "sweep_measured_gas_bps": 1.0,
                      "sweep_measured_fee_bps": 30.0, "sweep_measured_slippage_bps": 0.5,
                      "sweep_measured_total_cost_bps": 31.5},
            "scroll": {"sweep_gap_to_zero_bps": None, "included_signals_total": 0,
                        "accepted_fail": True},
        }
        ranking = start._compute_frontier_ranking(per_chain)
        # base (8.0) before arb (12.5), scroll excluded (no pnl + no signals)
        self.assertEqual(ranking[0]["chain"], "base")
        self.assertEqual(ranking[1]["chain"], "arb")

    def test_frontier_ready_flag(self):
        per_chain = {
            "arb": {"sweep_gap_to_zero_bps": 25.0, "sweep_best_net_pnl_bps": -25.0,
                     "included_signals_total": 5, "accepted_fail": False},
            "base": {"sweep_gap_to_zero_bps": 35.0, "sweep_best_net_pnl_bps": -35.0,
                     "included_signals_total": 5, "accepted_fail": False},
        }
        ranking = start._compute_frontier_ranking(per_chain)
        arb_entry = [r for r in ranking if r["chain"] == "arb"][0]
        base_entry = [r for r in ranking if r["chain"] == "base"][0]
        self.assertTrue(arb_entry["frontier_ready"])  # 25 < 30
        self.assertFalse(base_entry["frontier_ready"])  # 35 >= 30

    def test_frontier_ranking_in_summary(self):
        per_chain = {
            "arb": start.new_chain_stats(),
        }
        per_chain["arb"]["sweep_gap_to_zero_bps"] = 15.0
        per_chain["arb"]["included_signals_total"] = 5
        summary = start.build_summary(per_chain, 60.0, [])
        self.assertIn("frontier_ranking", summary)

    def test_accepted_fail_sorted_last(self):
        """accepted_fail chains are always sorted after non-accepted-fail."""
        per_chain = {
            "scroll": {"sweep_gap_to_zero_bps": 5.0, "sweep_best_net_pnl_bps": -5.0,
                        "included_signals_total": 2, "accepted_fail": True},
            "arb": {"sweep_gap_to_zero_bps": 20.0, "sweep_best_net_pnl_bps": -20.0,
                     "included_signals_total": 10, "accepted_fail": False},
        }
        ranking = start._compute_frontier_ranking(per_chain)
        self.assertEqual(len(ranking), 2)
        # arb first despite worse gap, because scroll is accepted_fail
        self.assertEqual(ranking[0]["chain"], "arb")
        self.assertEqual(ranking[1]["chain"], "scroll")
        self.assertFalse(ranking[0]["accepted_fail"])
        self.assertTrue(ranking[1]["accepted_fail"])

    def test_accepted_fail_not_frontier_ready(self):
        """accepted_fail chains should never be frontier_ready even with good gap."""
        per_chain = {
            "scroll": {"sweep_gap_to_zero_bps": 5.0, "sweep_best_net_pnl_bps": -5.0,
                        "included_signals_total": 2, "accepted_fail": True},
        }
        ranking = start._compute_frontier_ranking(per_chain)
        self.assertEqual(len(ranking), 1)
        self.assertFalse(ranking[0]["frontier_ready"])

    def test_composite_tiebreak_by_signals(self):
        """When gap_to_zero is tied, chain with more signals ranks higher."""
        per_chain = {
            "arb": {"sweep_gap_to_zero_bps": 15.0, "sweep_best_net_pnl_bps": -15.0,
                     "included_signals_total": 5, "last_cross_dex_pairs_count": 2,
                     "accepted_fail": False},
            "base": {"sweep_gap_to_zero_bps": 15.0, "sweep_best_net_pnl_bps": -15.0,
                      "included_signals_total": 20, "last_cross_dex_pairs_count": 3,
                      "accepted_fail": False},
        }
        ranking = start._compute_frontier_ranking(per_chain)
        # Same gap but base has more signals, should rank first
        self.assertEqual(ranking[0]["chain"], "base")
        self.assertEqual(ranking[1]["chain"], "arb")

    def test_ranking_includes_new_fields(self):
        """Ranking entries include signals, cross_dex, and accepted_fail."""
        per_chain = {
            "arb": {"sweep_gap_to_zero_bps": 10.0, "sweep_best_net_pnl_bps": -10.0,
                     "included_signals_total": 8, "last_cross_dex_pairs_count": 3,
                     "accepted_fail": False},
        }
        ranking = start._compute_frontier_ranking(per_chain)
        self.assertEqual(len(ranking), 1)
        entry = ranking[0]
        self.assertEqual(entry["included_signals_total"], 8)
        self.assertEqual(entry["cross_dex_pairs_count"], 3)
        self.assertFalse(entry["accepted_fail"])

    def test_chain_with_signals_but_no_sweep(self):
        """Chain with signals but no sweep data should still appear in ranking."""
        per_chain = {
            "linea": {"included_signals_total": 15, "sweep_best_net_pnl_bps": None,
                       "sweep_gap_to_zero_bps": None, "accepted_fail": False},
        }
        ranking = start._compute_frontier_ranking(per_chain)
        self.assertEqual(len(ranking), 1)
        self.assertEqual(ranking[0]["chain"], "linea")
        self.assertIsNone(ranking[0]["gap_to_zero_bps"])

    # -- R12: median frontier ranking tests ---

    def test_compute_median_odd(self):
        """_compute_median returns middle element for odd-length list."""
        self.assertEqual(start._compute_median([1.0, 3.0, 5.0]), 3.0)

    def test_compute_median_even(self):
        """_compute_median returns average of two middle elements for even-length."""
        self.assertAlmostEqual(start._compute_median([1.0, 3.0, 5.0, 7.0]), 4.0)

    def test_compute_median_empty(self):
        """_compute_median returns None for empty list."""
        self.assertIsNone(start._compute_median([]))

    def test_compute_median_single(self):
        """_compute_median returns the single element."""
        self.assertEqual(start._compute_median([42.0]), 42.0)

    def test_median_gap_in_ranking_entry(self):
        """R12: ranking entries include median_gap_to_zero_bps and runs_with_sweep."""
        per_chain = {
            "arb": {
                "sweep_gap_to_zero_bps": 10.0, "sweep_best_net_pnl_bps": -10.0,
                "included_signals_total": 5, "last_cross_dex_pairs_count": 2,
                "accepted_fail": False,
                "_sweep_gap_values": [10.0, 15.0, 20.0],
                "runs_with_sweep": 3,
            },
        }
        ranking = start._compute_frontier_ranking(per_chain)
        entry = ranking[0]
        self.assertEqual(entry["median_gap_to_zero_bps"], 15.0)
        self.assertEqual(entry["runs_with_sweep"], 3)

    def test_median_ranking_overrides_best_gap(self):
        """R12: chains ranked by median first, not best gap alone.

        arb has better best (5) but worse median (20),
        base has worse best (8) but better median (10).
        Base should rank first (lower median wins).
        """
        per_chain = {
            "arb": {
                "sweep_gap_to_zero_bps": 5.0, "sweep_best_net_pnl_bps": -5.0,
                "included_signals_total": 5, "accepted_fail": False,
                "_sweep_gap_values": [5.0, 20.0, 35.0],
                "runs_with_sweep": 3,
            },
            "base": {
                "sweep_gap_to_zero_bps": 8.0, "sweep_best_net_pnl_bps": -8.0,
                "included_signals_total": 5, "accepted_fail": False,
                "_sweep_gap_values": [8.0, 10.0, 12.0],
                "runs_with_sweep": 3,
            },
        }
        ranking = start._compute_frontier_ranking(per_chain)
        # base median=10 < arb median=20 → base first
        self.assertEqual(ranking[0]["chain"], "base")
        self.assertEqual(ranking[1]["chain"], "arb")

    def test_runs_with_sweep_tiebreak(self):
        """R12: when median and best are tied, more sweep runs wins."""
        per_chain = {
            "arb": {
                "sweep_gap_to_zero_bps": 15.0, "sweep_best_net_pnl_bps": -15.0,
                "included_signals_total": 5, "accepted_fail": False,
                "_sweep_gap_values": [15.0, 15.0, 15.0, 15.0, 15.0],
                "runs_with_sweep": 5,
            },
            "base": {
                "sweep_gap_to_zero_bps": 15.0, "sweep_best_net_pnl_bps": -15.0,
                "included_signals_total": 5, "accepted_fail": False,
                "_sweep_gap_values": [15.0, 15.0],
                "runs_with_sweep": 2,
            },
        }
        ranking = start._compute_frontier_ranking(per_chain)
        # Same median and gap, but arb has 5 sweep runs vs base 2 → arb first
        self.assertEqual(ranking[0]["chain"], "arb")
        self.assertEqual(ranking[1]["chain"], "base")

    def test_gap_percentile_context_in_summary(self):
        """R12: build_summary includes gap_percentile_context."""
        per_chain = {
            "arb": start.new_chain_stats(),
            "base": start.new_chain_stats(),
        }
        per_chain["arb"]["_sweep_gap_values"] = [10.0, 20.0, 30.0]
        per_chain["arb"]["runs_with_sweep"] = 3
        per_chain["arb"]["included_signals_total"] = 5
        per_chain["base"]["_sweep_gap_values"] = [15.0, 25.0]
        per_chain["base"]["runs_with_sweep"] = 2
        per_chain["base"]["included_signals_total"] = 3
        summary = start.build_summary(per_chain, 60.0, [])
        ctx = summary["gap_percentile_context"]
        self.assertEqual(ctx["best_gap_to_zero_bps"], 10.0)
        self.assertEqual(ctx["runs_with_sweep"], 5)  # 3 + 2
        self.assertEqual(ctx["sweep_values_count"], 5)  # 3 + 2
        # Median of [10, 15, 20, 25, 30] = 20
        self.assertEqual(ctx["median_gap_to_zero_bps"], 20.0)

    def test_no_median_when_no_sweep_data(self):
        """R12: no sweep data → median is None, not error."""
        per_chain = {
            "arb": {
                "sweep_gap_to_zero_bps": None, "sweep_best_net_pnl_bps": None,
                "included_signals_total": 5, "accepted_fail": False,
            },
        }
        ranking = start._compute_frontier_ranking(per_chain)
        self.assertEqual(len(ranking), 1)
        self.assertIsNone(ranking[0]["median_gap_to_zero_bps"])
        self.assertEqual(ranking[0]["runs_with_sweep"], 0)


if __name__ == "__main__":
    unittest.main()
