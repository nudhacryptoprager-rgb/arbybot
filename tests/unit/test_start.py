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

    @patch("start.run_gate_once")
    @patch("start.read_config_meta")
    @patch("start.prune_run_dirs")
    def test_rolling_only_for_normal(self, mock_prune, mock_meta, mock_gate):
        """Round-robin 2 configs: NORMAL gets rolling, COVERAGE does not."""
        normal_yaml = "config/real_minimal.yaml"
        coverage_yaml = "config/coverage_intent_base.yaml"

        def meta_side(path):
            if "real_minimal" in path:
                return {"chain": "arbitrum_one", "run_kind": "NORMAL"}
            return {"chain": "base", "run_kind": "COVERAGE"}

        mock_meta.side_effect = meta_side

        # Each run returns exit_code=0, dummy runDir=None
        mock_gate.return_value = (0, None)

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

    def test_summary_schema(self):
        per_chain = {
            "arb": {
                "config": "real_minimal.yaml",
                "runs": 2, "pass": 1, "no_data": 1, "fail": 0, "infra_fail": 0,
                "infra_pass": 2,
                "included_signals_total": 3,
                "net_usdc_total": 10.5,
                "profitable_roundtrips_total": 0,
                "last_run_timestamp": "2026-03-10T10:00:00Z",
                "last_run_dir": "ci_m5_gate_20260310_100000",
            },
        }
        summary = start.build_summary(per_chain, 120.5, ["WARN_TEST"])
        self.assertEqual(summary["schema"], "start:long_scan_summary:v1.0")
        self.assertEqual(summary["total_runs"], 2)
        self.assertEqual(summary["total_pass"], 1)
        self.assertEqual(summary["total_no_data"], 1)
        self.assertIn("WARN_TEST", summary["warnings"])
        self.assertIn("arb", summary["per_chain"])


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


if __name__ == "__main__":
    unittest.main()
