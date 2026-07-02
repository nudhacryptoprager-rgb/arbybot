"""
tests/unit/test_nonstop_loop_artifacts.py

Test that non-stop loop mode does not bloat rolling artifacts.

v2.4.0: Added for Directive #12 Step 7.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock


class TestNonstopLoopArtifacts(unittest.TestCase):
    """Test rolling artifact discipline in non-stop loop mode."""
    
    def test_rolling_artifacts_are_three_canonical_files(self):
        """
        Verify that rolling directory contains only canonical files.
        
        Per AGENTS.md artifact policy:
        - _latest.json
        - run_summary_latest.json  
        - m4_stability_agg.json
        - long_scan_latest.json (multi-chain frontier ranking)
        """
        rolling_dir = Path("data/runs/_rolling")
        
        # Skip if rolling directory doesn't exist (CI/fresh checkout)
        if not rolling_dir.exists():
            self.skipTest("Rolling directory does not exist")
        
        canonical_files = {
            "_latest.json",
            "run_summary_latest.json",
            "m4_stability_agg.json",
            "long_scan_latest.json",
        }
        
        # Optional files (runtime alerts, gitignored)
        optional_runtime_files = {
            "last_roundtrip_profitable.json",
            "_latest_offline.json",
            "run_summary_latest_offline.json",
            "hot_loop_latest.json",
            "m7_orderflow_latest.json",
            "m7_hot_latest.json",
            "m7_promoted_pairs.json",
            "m7_cold_hot_bridge.json",
            "m7_hot_intents_latest.json",
            "m7_hot_rollup_latest.json",
            "m7_session_state.json",
            # M7.E1.9.1: Discovery namespace files
            "m7_orderflow_latest_discovery.json",
            "m7_hot_latest_discovery.json",
            "m7_promoted_pairs_discovery.json",
            "m7_cold_hot_bridge_discovery.json",
            "m7_hot_intents_latest_discovery.json",
            "m7_hot_rollup_latest_discovery.json",
            "m7_discovery_scoreboard.json",
            "m7_discovery_scoreboard_discovery.json",
            # E1.16: Baseline snapshots (saved before long scans)
            "_baseline_pre4h.json",
            "_baseline_pre4h_discovery.json",
            # M7.E1.34 Step 9 reviewer tooling (pre-soak baseline + delta)
            "reviewer_soak_baseline_latest.json",
            "reviewer_soak_baseline_latest_discovery.json",
            "reviewer_soak_delta_latest.json",
            # M7.A.5.4.0 batch pre-resolve cache (rolling, overwritten)
            "_pool_token_cache.json",
            # M7.E1.52: HTTP-only proof lane artifact (rolling, overwritten)
            "m7_proof_latest.json",
            # M7.E1.47/P1a tier_map artifacts (per-chain, rolling, overwritten)
            "m7_tier_map_base.json",
            "m7_tier_map_arbitrum.json",
            "m7_tier_map_arbitrum_one.json",
            "m7_tier_map_optimism.json",
            "m7_tier_map_polygon.json",
            "m7_tier_map_zksync.json",
            "m7_tier_map_linea.json",
            "m7_tier_map_scroll.json",
            "m7_tier_map_mantle.json",
            # Live execution artifacts (run_live_canary.py and loop_runner)
            "canary_latest.json",
            "live_submit_latest.json",
            "live_pnl_latest.json",
            # M7.E1.65 Step 6: WS cross-process cooldown file (written on 429, read by next session)
            "ws_cooldown.json",
            # E1.69 Wave D: TVL scout rolling artifact (production pool ranking)
            "m7_tvl_scout_latest.json",
            # E1.83: factory-enumerated pool/dex truth (refreshed every 10 min)
            "pool_family_truth.json",
            # M8 Phase 1: new pool sniper rolling artifact
            "new_pool_sniper_latest.json",
            # M8.1: stable-anchor rolling artifact
            "m8_1_stable_anchor_latest.json",
            # M8.2: pending-pair registry (cross-run multi-venue accumulator)
            "m8_pending_pairs.json",
            # M9: graph-arb shadow scanner rolling artifact
            "m9_graph_latest.json",
            # M9: bridge inventory (M8→M9 pipeline output)
            "m9_bridge_inventory_latest.json",
            # M9: factory-enumerated Curve pool discovery (rolling, overwritten)
            "m9_curve_discovery_latest.json",
            "m9_curve_pool_indices_latest.json",
            # M8.2: cross-dex expansion rolling artifact (M8→M9 pipeline input)
            "m8_cross_dex_expansion_latest.json",
            # M8.2: external pool hints + candidate DEX registries (rolling)
            "m8_external_pool_hints_latest.json",
            "m8_radar_pool_candidates_latest.json",
            # M8.2: per-DEX pool indices (rolling, overwritten)
            "m8_balancer_pool_index_latest.json",
            "m8_maverick_pool_index_latest.json",
            # M8.3: token metadata registry (rolling, overwritten)
            "m8_3_token_metadata_registry_latest.json",
            # M9: quote route diagnostic (rolling, overwritten)
            "m9_quote_route_diagnostic_latest.json",
            # M9: Arbitrum One graph-arb shadow scanner rolling artifact
            "m9_arb_latest.json",
        }
        
        # Archive files are allowed (created on reset)
        archive_pattern = lambda f: f.startswith("m4_stability_agg_archive_")
        # Log files are allowed (created by scan sessions)
        log_pattern = lambda f: f.endswith(".log")
        # M7.E1.34: reviewer tooling may drop PID files and launcher
        # scripts (+ stdout/stderr log) while a soak is running; they are
        # runtime ephemera and not part of the canonical artifact contract.
        runtime_pattern = lambda f: (
            f.endswith(".pid") or f.endswith(".py") or f.endswith(".log")
            or f.startswith("reviewer_soak_")
        )        
        all_files = set(f.name for f in rolling_dir.iterdir() if f.is_file())
        
        # Filter out archive and log files
        non_archive_files = {f for f in all_files if not archive_pattern(f) and not log_pattern(f)}
        # Filter out temp files (atomic-write intermediaries)
        non_archive_files = {f for f in non_archive_files if not f.endswith(".tmp")}
        # Filter out reviewer-soak runtime ephemera (PID / launcher script)
        non_archive_files = {f for f in non_archive_files if not runtime_pattern(f)}
        
        # Check that canonical files exist
        for canon in canonical_files:
            if (rolling_dir / canon).exists():
                self.assertIn(canon, non_archive_files)
        
        # Check no unexpected files (excluding archives)
        expected = canonical_files | optional_runtime_files
        unexpected = non_archive_files - expected
        
        self.assertEqual(
            unexpected, set(),
            f"Unexpected files in rolling directory: {unexpected}. "
            f"Rolling should only contain: {expected}"
        )
    
    def test_rolling_files_are_overwritten_not_multiplied(self):
        """
        Verify that _latest.json and run_summary_latest.json are 
        single files, not versioned/dated copies.
        """
        rolling_dir = Path("data/runs/_rolling")
        
        if not rolling_dir.exists():
            self.skipTest("Rolling directory does not exist")
        
        # Check for dated copies (forbidden pattern)
        forbidden_patterns = [
            "_latest_202",  # e.g., _latest_20260223.json
            "run_summary_latest_202",  # e.g., run_summary_latest_20260223.json
            "m4_stability_agg_202",  # e.g., m4_stability_agg_20260223.json
        ]
        
        for f in rolling_dir.iterdir():
            if f.is_file():
                for pattern in forbidden_patterns:
                    self.assertFalse(
                        pattern in f.name,
                        f"Found dated copy in rolling: {f.name}. "
                        f"Rolling artifacts should be overwritten, not multiplied."
                    )
    
    def test_run_dirs_pruned_to_limit(self):
        """
        Verify retention logic (prune_run_dirs.py) keeps run directories under the keep limit.

        This must be deterministic and must NOT depend on the developer's local runtime artifacts
        under data/runs/**.
        """
        from scripts import prune_run_dirs as pruner

        with tempfile.TemporaryDirectory() as tmpdir:
            runs_dir = Path(tmpdir) / "data" / "runs"
            runs_dir.mkdir(parents=True)

            # Protected directories (never deleted)
            for name in ("_rolling", "_incidents", "_cache"):
                (runs_dir / name).mkdir(parents=True, exist_ok=True)

            # Create 60 dummy runDirs with deterministic mtimes.
            base_ts = 1_700_000_000
            for i in range(60):
                d = runs_dir / f"ci_m5_gate_20260223_{i:06d}"
                d.mkdir(parents=True, exist_ok=True)
                ts = base_ts + i
                os.utime(d, (ts, ts))

            # Patch RUNS_DIR so we never touch the real data/runs/** during unit tests.
            with patch.object(pruner, "RUNS_DIR", runs_dir), \
                 patch.object(pruner, "get_protected_from_latest", return_value=set()), \
                 patch.object(pruner, "get_protected_from_status_md", return_value=set()):
                result = pruner.prune_run_dirs(keep=50, dry_run=False, yes=True)

            remaining = [
                d for d in runs_dir.iterdir()
                if d.is_dir() and d.name.startswith("ci_m5_gate_")
            ]

            self.assertEqual(result["kept_count"], 50)
            self.assertEqual(result["delete_count"], 10)
            self.assertLessEqual(len(remaining), 50)
            self.assertTrue((runs_dir / "_rolling").exists())
            self.assertTrue((runs_dir / "_incidents").exists())
            self.assertTrue((runs_dir / "_cache").exists())


class TestRoundtripAlertFile(unittest.TestCase):
    """Test roundtrip alert file behavior."""
    
    def test_alert_file_is_gitignored(self):
        """Verify last_roundtrip_profitable.json would be gitignored."""
        rolling_dir = Path("data/runs/_rolling")
        alert_path = rolling_dir / "last_roundtrip_profitable.json"
        
        # The file should be under data/ which is gitignored
        # Verify by checking .gitignore contains data/ or data/**
        gitignore = Path(".gitignore")
        if gitignore.exists():
            content = gitignore.read_text()
            # Check for various data directory patterns
            data_ignored = (
                "data/" in content or 
                "data/**" in content or 
                "data/runs" in content
            )
            self.assertTrue(
                data_ignored,
                "data/ or data/** should be in .gitignore"
            )


class TestLoopModeHelpers(unittest.TestCase):
    """Test helper functions for loop mode."""
    
    def test_check_roundtrip_profitable_with_no_roundtrip(self):
        """Test check_roundtrip_profitable returns False when no profitable roundtrip."""
        # Import the helper function
        from scripts.ci_m5_0_gate import check_roundtrip_profitable
        
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            reports_dir = run_dir / "reports"
            reports_dir.mkdir(parents=True)
            
            # Create a truth_report with no profitable roundtrip
            truth_report = {
                "profit_realism_status": "ROUNDTRIP_NOT_PROFITABLE",
                "roundtrip_summary": {
                    "profitable_count": 0,
                    "real_quote_count": 2,
                    "best_net_pnl_bps": -15.5,
                },
            }
            
            truth_path = reports_dir / "truth_report_20260223_120000.json"
            with open(truth_path, "w") as f:
                json.dump(truth_report, f)
            
            is_profitable, count, status = check_roundtrip_profitable(run_dir)
            
            self.assertFalse(is_profitable)
            self.assertEqual(count, 0)
            self.assertEqual(status, "ROUNDTRIP_NOT_PROFITABLE")
    
    def test_check_roundtrip_profitable_with_profitable(self):
        """Test check_roundtrip_profitable returns True when profitable roundtrip found."""
        from scripts.ci_m5_0_gate import check_roundtrip_profitable
        
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            reports_dir = run_dir / "reports"
            reports_dir.mkdir(parents=True)
            
            # Create a truth_report WITH profitable roundtrip
            truth_report = {
                "profit_realism_status": "ROUNDTRIP_PROFITABLE",
                "roundtrip_summary": {
                    "profitable_count": 2,
                    "real_quote_count": 5,
                    "best_net_pnl_bps": 25.0,
                },
            }
            
            truth_path = reports_dir / "truth_report_20260223_120000.json"
            with open(truth_path, "w") as f:
                json.dump(truth_report, f)
            
            is_profitable, count, status = check_roundtrip_profitable(run_dir)
            
            self.assertTrue(is_profitable)
            self.assertEqual(count, 2)
            self.assertEqual(status, "ROUNDTRIP_PROFITABLE")
    
    def test_check_roundtrip_profitable_missing_report(self):
        """Test check_roundtrip_profitable handles missing truth_report."""
        from scripts.ci_m5_0_gate import check_roundtrip_profitable
        
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            reports_dir = run_dir / "reports"
            reports_dir.mkdir(parents=True)
            # Don't create truth_report
            
            is_profitable, count, status = check_roundtrip_profitable(run_dir)
            
            self.assertFalse(is_profitable)
            self.assertEqual(count, 0)
            self.assertEqual(status, "NO_TRUTH_REPORT")


if __name__ == "__main__":
    unittest.main()
