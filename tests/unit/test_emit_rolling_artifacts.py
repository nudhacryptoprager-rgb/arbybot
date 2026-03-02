"""
Unit tests for emit_rolling_artifacts function.

v2.1.0: Tests for the --refresh-rolling functionality in ci_m5_0_gate.py.
Ensures the import works and function doesn't no-op silently.
"""
import json
import tempfile
from pathlib import Path
from unittest import TestCase


class TestEmitRollingArtifactsImport(TestCase):
    """Test that emit_rolling_artifacts can be imported and called."""
    
    def test_import_from_m4_rolling_store(self):
        """emit_rolling_artifacts must be importable from m4.rolling_store."""
        from m4.rolling_store import emit_rolling_artifacts
        self.assertIsNotNone(emit_rolling_artifacts)
        self.assertTrue(callable(emit_rolling_artifacts))
    
    def test_import_from_m4_init(self):
        """emit_rolling_artifacts must be importable from m4 top-level."""
        from m4 import emit_rolling_artifacts
        self.assertIsNotNone(emit_rolling_artifacts)
        self.assertTrue(callable(emit_rolling_artifacts))
    
    def test_raises_on_missing_rundir(self):
        """emit_rolling_artifacts must raise FileNotFoundError for missing runDir."""
        from m4.rolling_store import emit_rolling_artifacts
        
        with self.assertRaises(FileNotFoundError):
            emit_rolling_artifacts(Path("/nonexistent/path/ci_m5_gate_fake"))
    
    def test_raises_on_missing_run_summary(self):
        """emit_rolling_artifacts must raise FileNotFoundError if no run_summary found."""
        from m4.rolling_store import emit_rolling_artifacts
        
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir) / "ci_m5_gate_test"
            run_dir.mkdir()
            
            with self.assertRaises(FileNotFoundError) as ctx:
                emit_rolling_artifacts(run_dir)
            
            self.assertIn("run_summary", str(ctx.exception))


class TestEmitRollingArtifactsFunctional(TestCase):
    """Functional tests for emit_rolling_artifacts with real data."""
    
    def test_emit_creates_rolling_artifacts(self):
        """emit_rolling_artifacts must create _latest.json and run_summary_latest.json."""
        from m4.rolling_store import emit_rolling_artifacts
        
        with tempfile.TemporaryDirectory() as tmpdir:
            runs_dir = Path(tmpdir) / "data" / "runs"
            runs_dir.mkdir(parents=True)
            
            run_dir = runs_dir / "ci_m5_gate_test_20260215_120000"
            run_dir.mkdir()
            reports_dir = run_dir / "reports"
            reports_dir.mkdir()
            
            # Create minimal run_summary
            run_summary = {
                "schema_version": "m4:run_summary:v2.0",
                "run_id": "ci_m5_gate_test_20260215_120000",
                "status": "PASS",
                "run_context": {
                    "run_timestamp": "2026-02-15T12:00:00Z",
                    "code_identity": "ts:2026-02-15T12:00:00Z",
                },
                "metrics": {
                    "signals_count": 5,
                    "included_signals_count": 5,
                    "total_net_usdc": 50.0,
                    "mae_net_usdc": 0.5,
                    "est_sign_correct_rate": 1.0,
                },
                "inputs": {
                    "run_mode": "REGISTRY_REAL",
                    "run_dir_name": "ci_m5_gate_test_20260215_120000",
                },
                "thresholds": {
                    "threshold_profile_name": "profit",
                },
            }
            
            run_summary_path = reports_dir / "run_summary_20260215_120000.json"
            with open(run_summary_path, "w") as f:
                json.dump(run_summary, f)
            
            # Call emit_rolling_artifacts
            result = emit_rolling_artifacts(run_dir)
            
            # Verify return value
            self.assertIn("updated_at", result)
            self.assertEqual(result["run_id"], "ci_m5_gate_test_20260215_120000")
            self.assertIn("agg_status", result)
            
            # Verify rolling artifacts created
            rolling_dir = runs_dir / "_rolling"
            self.assertTrue(rolling_dir.exists(), "_rolling directory not created")
            
            latest_path = rolling_dir / "_latest.json"
            self.assertTrue(latest_path.exists(), "_latest.json not created")
            
            run_summary_latest_path = rolling_dir / "run_summary_latest.json"
            self.assertTrue(run_summary_latest_path.exists(), "run_summary_latest.json not created")
            
            agg_path = rolling_dir / "m4_stability_agg.json"
            self.assertTrue(agg_path.exists(), "m4_stability_agg.json not created")
            
            # Verify _latest.json content
            with open(latest_path) as f:
                latest_data = json.load(f)
            
            self.assertEqual(latest_data["schema_version"], "m4:latest:v2.0")
            self.assertEqual(latest_data["run_status"], "PASS")
            self.assertIn("updated_at", latest_data)
    
    def test_run_dir_name_in_latest_json(self):
        """v3.2.3: _latest.json must include run_dir_name in run_context and inputs."""
        from m4.rolling_store import emit_rolling_artifacts
        
        with tempfile.TemporaryDirectory() as tmpdir:
            runs_dir = Path(tmpdir) / "data" / "runs"
            runs_dir.mkdir(parents=True)
            
            run_dir = runs_dir / "ci_m5_gate_provenance_test"
            run_dir.mkdir()
            reports_dir = run_dir / "reports"
            reports_dir.mkdir()
            
            # Create run_summary with run_dir_name
            run_summary = {
                "schema_version": "m4:run_summary:v2.0",
                "run_id": "ci_m5_gate_provenance_test",
                "status": "PASS",
                "run_context": {
                    "run_timestamp": "2026-03-01T12:00:00Z",
                    "code_identity": "ts:2026-03-01T12:00:00Z",
                },
                "metrics": {
                    "signals_count": 3,
                    "included_signals_count": 3,
                    "total_net_usdc": 25.0,
                    "mae_net_usdc": 0.2,
                    "est_sign_correct_rate": 1.0,
                },
                "inputs": {
                    "run_mode": "REGISTRY_REAL",
                    "run_dir_name": "ci_m5_gate_provenance_test",  # KEY FIELD
                    "config_path": "config/test.yaml",
                },
                "thresholds": {
                    "threshold_profile_name": "profit",
                },
            }
            
            run_summary_path = reports_dir / "run_summary_20260301_120000.json"
            with open(run_summary_path, "w") as f:
                json.dump(run_summary, f)
            
            # Call emit_rolling_artifacts
            emit_rolling_artifacts(run_dir)
            
            # Verify _latest.json has run_dir_name in run_context
            rolling_dir = runs_dir / "_rolling"
            latest_path = rolling_dir / "_latest.json"
            
            with open(latest_path) as f:
                latest_data = json.load(f)
            
            # v3.2.3: run_dir_name must be in run_context
            self.assertIn("run_context", latest_data)
            self.assertEqual(
                latest_data["run_context"].get("run_dir_name"),
                "ci_m5_gate_provenance_test",
                "run_context.run_dir_name must match inputs.run_dir_name"
            )
            
            # v3.2.3: inputs section must also exist with run_dir_name
            self.assertIn("inputs", latest_data)
            self.assertEqual(
                latest_data["inputs"].get("run_dir_name"),
                "ci_m5_gate_provenance_test",
                "inputs.run_dir_name must match from run_summary"
            )

    def test_validates_run_summary_fields(self):
        """emit_rolling_artifacts must raise ValueError for invalid run_summary."""
        from m4.rolling_store import emit_rolling_artifacts
        
        with tempfile.TemporaryDirectory() as tmpdir:
            runs_dir = Path(tmpdir) / "data" / "runs"
            runs_dir.mkdir(parents=True)
            
            run_dir = runs_dir / "ci_m5_gate_invalid"
            run_dir.mkdir()
            
            # Create invalid run_summary (missing metrics)
            invalid_summary = {
                "schema_version": "m4:run_summary:v2.0",
                "run_id": "ci_m5_gate_invalid",
                "status": "PASS",
                # Missing: metrics
            }
            
            run_summary_path = run_dir / "run_summary_test.json"
            with open(run_summary_path, "w") as f:
                json.dump(invalid_summary, f)
            
            with self.assertRaises(ValueError) as ctx:
                emit_rolling_artifacts(run_dir)
            
            self.assertIn("metrics", str(ctx.exception))
    
    def test_deterministic_run_summary_selection(self):
        """v2.1.0: When multiple run_summary files exist, select latest by timestamp."""
        from m4.rolling_store import emit_rolling_artifacts
        
        with tempfile.TemporaryDirectory() as tmpdir:
            runs_dir = Path(tmpdir) / "data" / "runs"
            runs_dir.mkdir(parents=True)
            
            run_dir = runs_dir / "ci_m5_gate_multi_summary"
            run_dir.mkdir()
            reports_dir = run_dir / "reports"
            reports_dir.mkdir()
            
            # Base template for run_summary
            def make_summary(run_id: str, net_usdc: float):
                return {
                    "schema_version": "m4:run_summary:v2.0",
                    "run_id": run_id,
                    "status": "PASS",
                    "run_context": {
                        "run_timestamp": "2026-02-15T12:00:00Z",
                        "code_identity": "ts:2026-02-15T12:00:00Z",
                    },
                    "metrics": {
                        "signals_count": 5,
                        "included_signals_count": 5,
                        "total_net_usdc": net_usdc,  # Unique marker
                        "mae_net_usdc": 0.5,
                        "est_sign_correct_rate": 1.0,
                    },
                    "inputs": {
                        "run_mode": "REGISTRY_REAL",
                        "run_dir_name": run_id,
                    },
                    "thresholds": {
                        "threshold_profile_name": "profit",
                    },
                }
            
            # Create OLDER run_summary (earlier timestamp)
            old_summary = make_summary("ci_m5_gate_multi_summary", net_usdc=10.0)
            old_path = reports_dir / "run_summary_20260215_100000.json"
            with open(old_path, "w") as f:
                json.dump(old_summary, f)
            
            # Create NEWER run_summary (later timestamp)
            new_summary = make_summary("ci_m5_gate_multi_summary", net_usdc=99.99)
            new_path = reports_dir / "run_summary_20260215_120000.json"
            with open(new_path, "w") as f:
                json.dump(new_summary, f)
            
            # Call emit_rolling_artifacts
            result = emit_rolling_artifacts(run_dir)
            
            # Verify it picked the NEWER one (net_usdc=99.99)
            rolling_dir = runs_dir / "_rolling"
            run_summary_latest_path = rolling_dir / "run_summary_latest.json"
            
            with open(run_summary_latest_path) as f:
                latest_summary = json.load(f)
            
            # The selected run_summary should have the newer net_usdc
            self.assertEqual(
                latest_summary["metrics"]["total_net_usdc"], 99.99,
                "Should select run_summary with latest timestamp (120000 > 100000)"
            )


class TestProvenanceFallback(TestCase):
    """Test provenance handling when runDir has missing artifacts."""
    
    def test_provenance_uses_run_summary_when_no_scan(self):
        """v2.3.2: When no scan_*.json exists, use run_summary.run_context.run_timestamp."""
        from m4.rolling_store import emit_rolling_artifacts
        
        with tempfile.TemporaryDirectory() as tmpdir:
            runs_dir = Path(tmpdir) / "data" / "runs"
            runs_dir.mkdir(parents=True)
            
            run_dir = runs_dir / "ci_m5_gate_no_scan_20260215_130000"
            run_dir.mkdir()
            reports_dir = run_dir / "reports"
            reports_dir.mkdir()
            
            expected_ts = "2026-02-15T13:00:00.000000+00:00"
            
            # Create run_summary WITHOUT scan_*.json
            run_summary = {
                "schema_version": "m4:run_summary:v2.0",
                "run_id": "ci_m5_gate_no_scan_20260215_130000",
                "status": "PASS",
                "run_context": {
                    "run_timestamp": expected_ts,
                    "code_identity": f"ts:{expected_ts}",
                },
                "metrics": {
                    "signals_count": 3,
                    "included_signals_count": 3,
                    "total_net_usdc": 25.0,
                    "mae_net_usdc": 0.3,
                    "est_sign_correct_rate": 1.0,
                },
                "inputs": {
                    "run_mode": "REGISTRY_REAL",
                    "run_dir_name": "ci_m5_gate_no_scan_20260215_130000",
                },
                "thresholds": {
                    "threshold_profile_name": "profit",
                },
            }
            
            run_summary_path = reports_dir / "run_summary_20260215_130000.json"
            with open(run_summary_path, "w") as f:
                json.dump(run_summary, f)
            
            # Call emit_rolling_artifacts (no scan file exists)
            result = emit_rolling_artifacts(run_dir)
            
            # Verify the returned run_id is correct (function should not crash)
            self.assertEqual(result["run_id"], "ci_m5_gate_no_scan_20260215_130000")
            
            # Verify rolling artifacts were created
            rolling_dir = runs_dir / "_rolling"
            self.assertTrue((rolling_dir / "_latest.json").exists())
            self.assertTrue((rolling_dir / "run_summary_latest.json").exists())
            
            # Verify run_timestamp in rolling matches expected
            with open(rolling_dir / "run_summary_latest.json") as f:
                latest = json.load(f)
            self.assertEqual(
                latest["run_context"]["run_timestamp"],
                expected_ts,
                "Should use run_summary.run_context.run_timestamp when no scan exists"
            )


class TestDataRunRateWarnStatus(TestCase):
    """v2.2.2: Test that DATA_RUN_RATE_WARN triggers WARN_QUALITY agg_status."""
    
    def test_data_run_rate_warn_triggers_warn_quality(self):
        """DATA_RUN_RATE_WARN(0.47<0.5) must set agg_status=WARN_QUALITY."""
        from m4.rolling_store import _compute_quick_stats
        from m4.policy import Thresholds
        
        # Create runs where data_run_rate would be 0.47 (below WARN threshold)
        # We need 100 total runs, 47 with data (status != NO_DATA)
        # Add diversity to avoid DIVERSITY_*_FAIL thresholds
        pairs = ["WETH/USDC", "ARB/WETH", "LINK/WETH", "wstETH/WETH"]
        # Use correct format: "buy_dex->sell_dex"
        routes = [
            "uniswap_v3->sushiswap_v3",
            "sushiswap_v3->uniswap_v3",
        ]
        
        runs = []
        for i in range(47):
            runs.append({
                "run_id": f"run_{i:03d}",
                "status": "PASS",
                "run_timestamp": f"2026-02-25T{10+i//60:02d}:{i%60:02d}:00Z",
                "net_usdc": 10.0 + (i % 10) * 5 - 20,  # Vary net_usdc to avoid sanity check
                "signals_count": 5,
                "direction_correct": i % 3 != 0,  # Some incorrect to avoid sanity check
                "run_mode": "REGISTRY_REAL",
                # Use correct field names: "pairs" (list) and "routes" (list)
                "pairs": [pairs[i % len(pairs)]],
                "routes": [routes[i % len(routes)]],
                "included_pairs": [pairs[i % len(pairs)]],
                "included_routes": [routes[i % len(routes)]],
            })
        for i in range(53):
            runs.append({
                "run_id": f"run_no_data_{i:03d}",
                "status": "NO_DATA",
                "run_timestamp": f"2026-02-25T{12+i//60:02d}:{i%60:02d}:00Z",
                "net_usdc": 0.0,
                "signals_count": 0,
                "direction_correct": None,
                "run_mode": "REGISTRY_REAL",
            })
        
        # Build minimal agg_data structure
        agg_data = {
            "runs": runs,
            "quick_stats": {},
            "policy_version": "test",
        }
        
        # Minimal run_summary (not used for aggregation in this test)
        run_summary = {
            "metrics": {
                "signals_count": 5,
                "included_signals_count": 5,
                "total_net_usdc": 10.0,
                "mae_net_usdc": 0.5,
                "est_sign_correct_rate": 0.8,
            },
        }
        
        # Verify data_run_rate calculation: 47/(47+53) = 0.47
        data_run_count = len([r for r in runs if r["status"] != "NO_DATA"])
        self.assertEqual(data_run_count, 47)
        data_run_rate = data_run_count / len(runs)
        self.assertAlmostEqual(data_run_rate, 0.47, places=2)
        
        # Verify this is below WARN threshold but above FAIL threshold
        self.assertLess(data_run_rate, Thresholds.AGG_DATA_RUN_RATE_WARN)
        self.assertGreaterEqual(data_run_rate, Thresholds.AGG_DATA_RUN_RATE_FAIL)
        
        # Compute aggregation
        result = _compute_quick_stats(agg_data, run_summary=run_summary, target_sha=None)
        
        # Verify agg_status is WARN_QUALITY (not PASS)
        self.assertEqual(
            result["agg_status"], "WARN_QUALITY",
            f"DATA_RUN_RATE_WARN should trigger WARN_QUALITY, got {result['agg_status']}. "
            f"agg_reasons={result['agg_reasons']}, quality_warnings={result.get('quality_warnings', [])}"
        )
        
        # Verify agg_reasons includes DATA_RUN_RATE_WARN
        self.assertIn(
            "DATA_RUN_RATE_WARN", result["agg_reasons"],
            f"agg_reasons should include DATA_RUN_RATE_WARN, got {result['agg_reasons']}"
        )
        
        # Verify quality_warnings has the full message
        warn_msgs = [w for w in result.get("quality_warnings", []) if "DATA_RUN_RATE_WARN" in w]
        self.assertEqual(len(warn_msgs), 1, "Should have exactly one DATA_RUN_RATE_WARN message")
        self.assertIn("0.47", warn_msgs[0])
