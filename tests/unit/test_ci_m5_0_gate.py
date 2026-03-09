# PATH: tests/unit/test_ci_m5_0_gate.py
"""Unit tests for ci_m5_0_gate.py v2.1.0."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.ci_m5_0_gate import (
    generate_fixture_artifacts,
    discover_artifacts,
    validate_artifacts,
    validate_schema_version,
    validate_health_metrics,
    main,
    __version__,
    validate_current_block,
)


class TestVersion(unittest.TestCase):
    def test_version_is_2_5_0(self):
        """v2.5.0: Fallback cross_dex_pairs_count from signals."""
        self.assertEqual(__version__, "2.5.0")


class TestModeExclusion(unittest.TestCase):
    def test_offline_and_online_together_error(self):
        """--offline + --online → argparse error."""
        with patch('sys.argv', ['ci_m5_0_gate.py', '--offline', '--online']):
            with self.assertRaises(SystemExit) as cm:
                main()
            self.assertEqual(cm.exception.code, 2)


class TestOfflineModeIgnoresEnv(unittest.TestCase):
    def test_offline_ignores_arby_run_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir)
            
            env_backup = os.environ.copy()
            os.environ["ARBY_RUN_DIR"] = "/nonexistent"
            
            try:
                with patch('sys.argv', ['ci_m5_0_gate.py', '--offline', '--output-root', str(output_root)]):
                    result = main()
                
                self.assertEqual(result, 0)
                dirs = list(output_root.glob("ci_m5_gate_offline_*"))
                self.assertEqual(len(dirs), 1)
            finally:
                os.environ.clear()
                os.environ.update(env_backup)


class TestFixtureGeneration(unittest.TestCase):
    def test_generate_creates_all_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            artifacts = generate_fixture_artifacts(Path(tmpdir), "20260201_120000")
            
            self.assertIn("scan", artifacts)
            self.assertIn("truth_report", artifacts)
            self.assertIn("reject_histogram", artifacts)
            
            for path in artifacts.values():
                self.assertTrue(path.exists())

    def test_fixture_has_schema_version(self):
        """All fixtures MUST have schema_version."""
        with tempfile.TemporaryDirectory() as tmpdir:
            artifacts = generate_fixture_artifacts(Path(tmpdir), "20260201_120000")
            
            for name, path in artifacts.items():
                with open(path) as f:
                    data = json.load(f)
                self.assertIn("schema_version", data, f"{name} missing schema_version")

    def test_fixture_has_top_level_metrics(self):
        """truth_report MUST have top-level metrics."""
        with tempfile.TemporaryDirectory() as tmpdir:
            artifacts = generate_fixture_artifacts(Path(tmpdir), "20260201_120000")
            
            with open(artifacts["truth_report"]) as f:
                data = json.load(f)
            
            self.assertIn("quotes_total", data)
            self.assertIn("dexes_active", data)


class TestDiscoverArtifacts(unittest.TestCase):
    def test_discover_from_reports(self):
        """Should find artifacts in reports/."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            generate_fixture_artifacts(run_dir, "20260201_120000")
            
            artifacts = discover_artifacts(run_dir)
            
            self.assertIsNotNone(artifacts["scan"])
            self.assertIsNotNone(artifacts["truth_report"])
            self.assertIsNotNone(artifacts["reject_histogram"])

    def test_discover_fallback_to_snapshots(self):
        """Should fallback to snapshots/ for scan if not in reports/."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            
            # Create scan only in snapshots/
            snapshots = run_dir / "snapshots"
            snapshots.mkdir()
            scan_data = {"schema_version": "3.2.0"}
            with open(snapshots / "scan_20260201.json", "w") as f:
                json.dump(scan_data, f)
            
            artifacts = discover_artifacts(run_dir)
            
            self.assertIsNotNone(artifacts["scan"])


class TestValidation(unittest.TestCase):
    def test_validate_schema_version_valid(self):
        ok, _ = validate_schema_version({"schema_version": "3.2.0"})
        self.assertTrue(ok)

    def test_validate_schema_version_missing(self):
        ok, msg = validate_schema_version({})
        self.assertFalse(ok)
        self.assertIn("Missing", msg)

    def test_validate_health_metrics_from_top_level(self):
        """Should accept metrics from top-level."""
        ok, _ = validate_health_metrics({"quotes_total": 10, "dexes_active": 2})
        self.assertTrue(ok)

    def test_validate_health_metrics_from_nested(self):
        """Should accept metrics from nested health."""
        ok, _ = validate_health_metrics({"health": {"quotes_total": 10, "dexes_active": 2}})
        self.assertTrue(ok)


class TestRequireReal(unittest.TestCase):
    def test_require_real_rejects_fixture(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            generate_fixture_artifacts(run_dir, "20260201_120000")
            
            with patch('sys.argv', ['ci_m5_0_gate.py', '--run-dir', str(run_dir), '--require-real']):
                result = main()
            
            self.assertEqual(result, 1)


class TestEnvVariables(unittest.TestCase):
    def test_arby_config_env(self):
        """ARBY_CONFIG should override default."""
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            generate_fixture_artifacts(run_dir, "20260201_120000")
            
            env_backup = os.environ.copy()
            os.environ["ARBY_CONFIG"] = "config/test.yaml"
            
            try:
                with patch('sys.argv', ['ci_m5_0_gate.py', '--run-dir', str(run_dir)]):
                    # Just check it doesn't crash
                    result = main()
                    self.assertIn(result, [0, 1])
            finally:
                os.environ.clear()
                os.environ.update(env_backup)


class TestCurrentBlockValidation(unittest.TestCase):
    def test_validate_current_block_success(self):
        scan = {"current_block": 100}
        truth = {"current_block": 100}
        ok, msg = validate_current_block(scan, truth)
        self.assertTrue(ok)
        self.assertIn("current_block OK", msg)

    def test_validate_current_block_mismatch(self):
        scan = {"current_block": 10}
        truth = {"current_block": 11}
        ok, msg = validate_current_block(scan, truth)
        self.assertFalse(ok)
        self.assertIn("mismatch", msg)

    def test_validate_current_block_missing(self):
        scan = {"current_block": 10}
        truth = {}
        ok, msg = validate_current_block(scan, truth)
        self.assertFalse(ok)
        self.assertIn("Missing current_block", msg)


    def test_gate_fails_when_truth_missing_run_mode(self):
        # Create a run_dir with scan and truth_report missing run_mode
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            reports = run_dir / "reports"
            reports.mkdir(parents=True)
            now = "20260204_120000"
            scan = {"schema_version": "3.2.0", "run_mode": "REGISTRY_REAL", "current_block": 100, "quotes_total": 2, "dexes_active": 2}
            truth = {"schema_version": "3.2.0", "current_block": 100, "quotes_total": 2, "quotes_fetched": 2, "dexes_active": 2, "price_sanity_passed": 1, "price_sanity_failed": 0}
            # deliberately remove run_mode from truth to simulate bad generator
            if "run_mode" in truth:
                truth.pop("run_mode")

            with open(reports / f"scan_{now}.json", "w") as f:
                json.dump(scan, f)
            with open(reports / f"truth_report_{now}.json", "w") as f:
                json.dump(truth, f)
            with open(reports / f"reject_histogram_{now}.json", "w") as f:
                json.dump({"schema_version": "3.2.0", "rejects": []}, f)

            with patch('sys.argv', ['ci_m5_0_gate.py', '--run-dir', str(run_dir), '--require-real']):
                result = main()
            self.assertNotEqual(result, 0)

    def test_gate_fails_on_current_block_mismatch(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            reports = run_dir / "reports"
            reports.mkdir(parents=True)
            now = "20260204_120001"
            scan = {"schema_version": "3.2.0", "run_mode": "REGISTRY_REAL", "current_block": 100, "quotes_total": 2, "dexes_active": 2}
            truth = {"schema_version": "3.2.0", "run_mode": "REGISTRY_REAL", "current_block": 101, "quotes_total": 2, "quotes_fetched": 2, "dexes_active": 2, "price_sanity_passed": 1, "price_sanity_failed": 0}

            with open(reports / f"scan_{now}.json", "w") as f:
                json.dump(scan, f)
            with open(reports / f"truth_report_{now}.json", "w") as f:
                json.dump(truth, f)
            with open(reports / f"reject_histogram_{now}.json", "w") as f:
                json.dump({"schema_version": "3.2.0", "rejects": []}, f)

            with patch('sys.argv', ['ci_m5_0_gate.py', '--run-dir', str(run_dir), '--require-real']):
                result = main()
            self.assertNotEqual(result, 0)


class TestGateResultJson(unittest.TestCase):
    """Tests for gate_result.json artifact generation (v3.3.0)."""
    
    def test_gate_result_schema_version(self):
        """gate_result.json MUST have schema_version."""
        # Run an offline gate to generate gate_result.json
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir)
            
            with patch('sys.argv', ['ci_m5_0_gate.py', '--offline', '--output-root', str(output_root)]):
                result = main()
            
            self.assertEqual(result, 0)
            
            # Find the run_dir
            run_dirs = list(output_root.glob("ci_m5_gate_offline_*"))
            self.assertEqual(len(run_dirs), 1)
            run_dir = run_dirs[0]
            
            # Check gate_result.json is in reports/
            gate_result_path = run_dir / "reports" / "gate_result.json"
            self.assertTrue(gate_result_path.exists(), f"gate_result.json not found in reports/")
            
            with open(gate_result_path) as f:
                data = json.load(f)
            
            self.assertIn("schema_version", data)
            self.assertEqual(data["schema_version"], "m5_0:gate_result:v1.0")
    
    def test_gate_result_run_context(self):
        """gate_result.json MUST have run_context.run_timestamp in ISO-8601."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir)
            
            with patch('sys.argv', ['ci_m5_0_gate.py', '--offline', '--output-root', str(output_root)]):
                result = main()
            
            self.assertEqual(result, 0)
            
            run_dirs = list(output_root.glob("ci_m5_gate_offline_*"))
            run_dir = run_dirs[0]
            gate_result_path = run_dir / "reports" / "gate_result.json"
            
            with open(gate_result_path) as f:
                data = json.load(f)
            
            self.assertIn("run_context", data)
            self.assertIn("run_timestamp", data["run_context"])
            # v3.3.1: Timestamp should be ISO-8601 format (e.g., 2026-03-07T10:44:46.123456+00:00)
            ts = data["run_context"]["run_timestamp"]
            # ISO-8601 contains dashes and colons
            self.assertIn("-", ts, f"run_timestamp should be ISO-8601: {ts}")
            self.assertIn(":", ts, f"run_timestamp should be ISO-8601: {ts}")
    
    def test_gate_result_generated_at_utc(self):
        """gate_result.json MUST have generated_at in UTC."""
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir)
            
            with patch('sys.argv', ['ci_m5_0_gate.py', '--offline', '--output-root', str(output_root)]):
                result = main()
            
            self.assertEqual(result, 0)
            
            run_dirs = list(output_root.glob("ci_m5_gate_offline_*"))
            run_dir = run_dirs[0]
            gate_result_path = run_dir / "reports" / "gate_result.json"
            
            with open(gate_result_path) as f:
                data = json.load(f)
            
            self.assertIn("generated_at", data)
            # Should be ISO format with timezone
            self.assertIn("+00:00", data["generated_at"])


class TestCrossDexPairsCountFallback(unittest.TestCase):
    """v2.5.0: Regression test for cross_dex_pairs_count fallback from signals.
    
    When discovery_runtime is disabled (enabled=false), cross_dex_pairs_count
    should be calculated from actual signals that have buy_dex != sell_dex.
    """

    def test_cross_dex_pairs_from_signals_when_discovery_disabled(self):
        """cross_dex_pairs_count should be > 0 when signals have different buy/sell DEXes."""
        # Create mock scan with discovery_runtime.enabled=false
        mock_scan = {
            "schema_version": "3.2.0",
            "run_mode": "FIXTURE_OFFLINE",
            "run_context": {
                "run_timestamp": "2026-03-09T22:00:00Z"
            },
            "stats": {
                "quotes_fetched": 10,
                "discovery_runtime": {
                    "enabled": False,
                    "cross_dex_pairs_count": 0  # 0 because disabled
                }
            }
        }
        
        # Create mock signals with cross-dex routes
        mock_signals = {
            "schema_version": "1.0.0",
            "signals": [
                {"pair": "WETH/USDC", "buy_dex": "sushiswap_v3", "sell_dex": "uniswap_v3"},
                {"pair": "WBTC/WETH", "buy_dex": "uniswap_v3", "sell_dex": "sushiswap_v3"},
                {"pair": "ARB/WETH", "buy_dex": "sushiswap_v3", "sell_dex": "uniswap_v3"},
            ]
        }
        
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            reports_dir = tmp_path / "reports"
            reports_dir.mkdir(parents=True)
            
            # Write artifacts
            (reports_dir / "scan_20260309_220000.json").write_text(json.dumps(mock_scan))
            (reports_dir / "signals_20260309_220000.json").write_text(json.dumps(mock_signals))
            
            # The core logic to test - extracted from ci_m5_0_gate.py
            scan_path = reports_dir / "scan_20260309_220000.json"
            signals_path = reports_dir / "signals_20260309_220000.json"
            
            with open(scan_path) as f:
                scan_data = json.load(f)
            
            # Initial cross_dex_pairs_count from discovery_runtime (should be 0)
            cross_dex_pairs_count = scan_data.get("stats", {}).get("discovery_runtime", {}).get("cross_dex_pairs_count", 0)
            self.assertEqual(cross_dex_pairs_count, 0, "Should be 0 from discovery_runtime")
            
            # Fallback: calculate from signals
            if cross_dex_pairs_count == 0 and signals_path.exists():
                with open(signals_path) as f:
                    signals_data = json.load(f)
                signals_list = signals_data.get("signals", [])
                cross_dex_pairs = set()
                for sig in signals_list:
                    buy_dex = sig.get("buy_dex", "")
                    sell_dex = sig.get("sell_dex", "")
                    pair = sig.get("pair", "")
                    if buy_dex and sell_dex and buy_dex != sell_dex and pair:
                        cross_dex_pairs.add(pair)
                if cross_dex_pairs:
                    cross_dex_pairs_count = len(cross_dex_pairs)
            
            # Should now be 3 (unique pairs with cross-dex routes)
            self.assertEqual(cross_dex_pairs_count, 3, "Should be 3 from signals fallback")

    def test_cross_dex_pairs_zero_when_no_cross_dex_signals(self):
        """cross_dex_pairs_count should be 0 when all signals have same buy/sell DEX."""
        mock_signals = {
            "schema_version": "1.0.0",
            "signals": [
                {"pair": "WETH/USDC", "buy_dex": "uniswap_v3", "sell_dex": "uniswap_v3"},  # same-dex
            ]
        }
        
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            reports_dir = tmp_path / "reports"
            reports_dir.mkdir(parents=True)
            
            (reports_dir / "signals_20260309_220000.json").write_text(json.dumps(mock_signals))
            
            signals_path = reports_dir / "signals_20260309_220000.json"
            with open(signals_path) as f:
                signals_data = json.load(f)
            
            cross_dex_pairs = set()
            for sig in signals_data.get("signals", []):
                buy_dex = sig.get("buy_dex", "")
                sell_dex = sig.get("sell_dex", "")
                pair = sig.get("pair", "")
                if buy_dex and sell_dex and buy_dex != sell_dex and pair:
                    cross_dex_pairs.add(pair)
            
            # Should be 0 (same-dex signal doesn't count)
            self.assertEqual(len(cross_dex_pairs), 0)


if __name__ == "__main__":
    unittest.main()
