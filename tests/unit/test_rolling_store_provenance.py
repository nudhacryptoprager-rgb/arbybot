# PATH: tests/unit/test_rolling_store_provenance.py
"""
Tests for rolling_store provenance logic.

v2.0.0: SHA provenance REMOVED - timestamp-based tracking only.

Contract:
- run_context.code_sha/evidence_sha are None (deprecated)
- run_context.run_timestamp is the primary provenance field
- runs_since_timestamp replaces runs_since_sha
- All runs treated as same code identity (no per-SHA breakdown)
"""

import pytest


class TestRollingTimestampProvenance:
    """v2.0.0: Test rolling_store timestamp-based provenance."""
    
    def test_compute_quick_stats_no_args_works(self):
        """_compute_quick_stats with no run_summary works."""
        from m4.rolling_store import _compute_quick_stats
        
        result = _compute_quick_stats({"runs": []})
        
        # Should not crash
        assert "runs_since_timestamp" in result
        assert "sha" in result["runs_since_timestamp"]
        # SHA is now None (tracking removed)
        assert result["runs_since_timestamp"]["sha"] is None
    
    def test_compute_quick_stats_sha_deprecated(self):
        """_compute_quick_stats ignores target_sha (deprecated)."""
        from m4.rolling_store import _compute_quick_stats
        
        # target_sha is now ignored
        result = _compute_quick_stats(
            {"runs": [{"code_sha": "abc123", "run_kind": "NORMAL", "signals_count": 5}]},
            target_sha="abc123"
        )
        
        # SHA is None (deprecated), but runs are counted
        assert result["runs_since_timestamp"]["sha"] is None
        assert result["runs_since_timestamp"]["runs_count"] >= 0
    
    def test_run_context_sha_fields_deprecated(self):
        """Verify run_context SHA fields are deprecated but present."""
        from m4.evidence import get_git_context
        
        ctx = get_git_context()
        
        # SHA fields exist but are None
        assert "code_sha" in ctx
        assert ctx["code_sha"] is None
        assert "code_dirty" in ctx  
        assert ctx["code_dirty"] is None
        # run_timestamp is the new primary field
        assert "run_timestamp" in ctx
        assert ctx["run_timestamp"] is not None


class TestEmitToAggregatorProvenance:
    """Test emit_to_aggregator_light provenance flow."""
    
    def test_emit_uses_run_timestamp(self):
        """emit_to_aggregator_light should use run_timestamp from run_context."""
        from m4.rolling_store import emit_to_aggregator_light
        from pathlib import Path
        import tempfile
        
        with tempfile.TemporaryDirectory() as tmpdir:
            agg_path = Path(tmpdir) / "test_agg.json"
            
            run_summary = {
                "run_id": "test_run_001",
                "timestamp": "2026-02-10T12:00:00Z",
                "run_context": {
                    "code_sha": None,  # v2.0: deprecated
                    "code_dirty": None,
                    "code_desc": None,
                    "run_timestamp": "2026-02-10T12:00:00.123456Z",
                },
                "status": "PASS",
                "metrics": {
                    "signals_count": 5,
                    "total_net_usdc": 10.0,
                    "mae_net_usdc": 0.5,
                    "est_sign_correct_rate": 1.0,
                    "fragile_rate": 0,
                },
                "reasons": [],
                "inputs": {"pairs": ["WETH/USDC"], "routes": ["uniswap_v3->sushiswap_v3"]},
            }
            
            result = emit_to_aggregator_light(run_summary, agg_path)
            
            # Check that the run entry has run_timestamp
            runs = result.get("runs", [])
            assert len(runs) == 1
            assert runs[0]["run_timestamp"] == "2026-02-10T12:00:00.123456Z"
            # code_sha should be None (deprecated)
            assert runs[0]["code_sha"] is None
    
    def test_emit_sha_is_none(self):
        """emit_to_aggregator_light sets code_sha=None for all runs."""
        from m4.rolling_store import emit_to_aggregator_light
        from pathlib import Path
        import tempfile
        
        with tempfile.TemporaryDirectory() as tmpdir:
            agg_path = Path(tmpdir) / "test_agg.json"
            
            # Even with legacy run_context that has code_sha, result should be None
            run_summary = {
                "run_id": "legacy_run_001",
                "timestamp": "2026-02-10T12:00:00Z",
                "run_context": {
                    "code_sha": "legacy_sha_123",  # should be ignored
                    "code_dirty": False,
                    "code_desc": "legacy",
                },
                "status": "PASS",
                "metrics": {"signals_count": 5, "total_net_usdc": 1.0, "mae_net_usdc": 0.1, "est_sign_correct_rate": 1.0, "fragile_rate": 0},
                "reasons": [],
                "inputs": {"pairs": [], "routes": []},
            }
            
            result = emit_to_aggregator_light(run_summary, agg_path)
            
            # code_sha is None regardless of input
            runs = result.get("runs", [])
            assert len(runs) == 1
            assert runs[0]["code_sha"] is None


class TestRollingIntegrationContract:
    """Integration tests for rolling artifact consistency."""
    
    def test_emit_aggregator_tracks_timestamp(self):
        """emit_to_aggregator_light must record run_timestamp in run entry."""
        from m4.rolling_store import emit_to_aggregator_light
        from pathlib import Path
        import tempfile
        
        with tempfile.TemporaryDirectory() as tmpdir:
            agg_path = Path(tmpdir) / "m4_stability_agg.json"
            
            run_summary = {
                "run_id": "consistency_test_001",
                "timestamp": "2026-02-10T15:00:00Z",
                "run_context": {
                    "code_sha": None,
                    "code_dirty": None,
                    "code_desc": None,
                    "run_timestamp": "2026-02-10T15:00:00.000000Z",
                },
                "status": "PASS",
                "metrics": {"signals_count": 5, "total_net_usdc": 5.0, "mae_net_usdc": 0.3, "est_sign_correct_rate": 1.0, "fragile_rate": 0},
                "reasons": [],
                "inputs": {"pairs": ["A/B"], "routes": ["dex1->dex2"]},
            }
            
            agg_data = emit_to_aggregator_light(run_summary, agg_path)
            
            # Verify: run entry has run_timestamp
            runs = agg_data.get("runs", [])
            assert len(runs) == 1
            assert "run_timestamp" in runs[0]
            assert runs[0]["code_sha"] is None
    
    def test_multiple_runs_append_to_aggregator(self):
        """Multiple emits append to runs, not overwrite."""
        from m4.rolling_store import emit_to_aggregator_light
        from pathlib import Path
        import tempfile
        
        with tempfile.TemporaryDirectory() as tmpdir:
            agg_path = Path(tmpdir) / "m4_stability_agg.json"
            
            base_summary = {
                "timestamp": "2026-02-10T15:00:00Z",
                "run_context": {"code_sha": None, "code_dirty": None, "code_desc": None, "run_timestamp": "2026-02-10T15:00:00Z"},
                "status": "PASS",
                "metrics": {"signals_count": 5, "total_net_usdc": 1.0, "mae_net_usdc": 0.3, "est_sign_correct_rate": 1.0, "fragile_rate": 0},
                "reasons": [],
                "inputs": {"pairs": ["A/B"], "routes": ["dex1->dex2"]},
            }
            
            # First run
            run1 = {**base_summary, "run_id": "run_001", "run_context": {**base_summary["run_context"], "run_timestamp": "2026-02-10T15:00:01Z"}}
            agg1 = emit_to_aggregator_light(run1, agg_path)
            
            # Second run (should append)
            run2 = {**base_summary, "run_id": "run_002", "run_context": {**base_summary["run_context"], "run_timestamp": "2026-02-10T15:00:02Z"}}
            agg2 = emit_to_aggregator_light(run2, agg_path)
            
            # Aggregator should have 2 runs
            assert len(agg2.get("runs", [])) == 2
            # code_sha is None for both
            assert agg2["runs"][0]["code_sha"] is None
            assert agg2["runs"][1]["code_sha"] is None
            # But run_timestamps are preserved
            assert agg2["runs"][0]["run_timestamp"] == "2026-02-10T15:00:01Z"
            assert agg2["runs"][1]["run_timestamp"] == "2026-02-10T15:00:02Z"


class TestTimestampProvenance:
    """Test timestamp-based provenance is now primary."""
    
    def test_timestamp_is_primary_provenance(self):
        """run_timestamp is now the primary provenance field."""
        from m4.evidence import get_git_context
        
        ctx = get_git_context()
        
        # SHA fields are deprecated (None)
        assert ctx["code_sha"] is None
        assert ctx["code_dirty"] is None
        
        # Timestamp is the new primary
        assert "run_timestamp" in ctx
        assert ctx["run_timestamp"] is not None
        assert "T" in ctx["run_timestamp"]  # ISO format
    
    def test_schema_version_is_v2(self):
        """Rolling aggregator uses v2.0 schema."""
        from m4.rolling_store import _compute_quick_stats
        
        result = _compute_quick_stats({"runs": []})
        
        assert result.get("schema_version") == "m4:stability_agg:v2.0"


class TestV20ContractEnforcement:
    """v2.0 contract enforcement tests."""
    
    def test_no_runs_by_code_sha_after_v2(self):
        """v2.0: runs_by_code_sha should not exist, replaced by runs_by_date."""
        from m4.rolling_store import emit_to_aggregator_light
        from pathlib import Path
        import tempfile
        
        with tempfile.TemporaryDirectory() as tmpdir:
            agg_path = Path(tmpdir) / "test_agg.json"
            
            run_summary = {
                "run_id": "test_run_v2",
                "timestamp": "2026-02-11T12:00:00Z",
                "run_context": {
                    "run_timestamp": "2026-02-11T12:00:00Z",
                    "code_sha": None,
                },
                "run_kind": "NORMAL",
                "metrics": {"signals_count": 5, "total_net_usdc": 1.0, "mae_net_usdc": 0.1, "fragile_rate": 0.1},
                "status": "PASS",
                "reasons": [],
            }
            
            emit_to_aggregator_light(run_summary, agg_path)
            
            import json
            agg = json.loads(agg_path.read_text())
            
            # runs_by_code_sha should NOT exist
            assert "runs_by_code_sha" not in agg
            # runs_by_date SHOULD exist
            assert "runs_by_date" in agg
            assert "2026-02-11" in agg["runs_by_date"]
    
    def test_run_timestamp_always_filled(self):
        """run_timestamp must always be filled in run entries."""
        from m4.rolling_store import emit_to_aggregator_light
        from pathlib import Path
        import tempfile
        
        with tempfile.TemporaryDirectory() as tmpdir:
            agg_path = Path(tmpdir) / "test_agg.json"
            
            run_summary = {
                "run_id": "test_run_ts",
                "timestamp": "2026-02-11T12:00:00Z",
                "run_context": {
                    "run_timestamp": "2026-02-11T12:00:00Z",
                    "code_sha": None,
                },
                "run_kind": "NORMAL",
                "metrics": {"signals_count": 2, "total_net_usdc": 0.5, "mae_net_usdc": 0.2, "fragile_rate": 0.0},
                "status": "PASS",
                "reasons": [],
            }
            
            emit_to_aggregator_light(run_summary, agg_path)
            
            import json
            agg = json.loads(agg_path.read_text())
            
            # All runs must have run_timestamp
            for run in agg["runs"]:
                assert "run_timestamp" in run
                assert run["run_timestamp"] is not None
                assert "T" in run["run_timestamp"]  # ISO format
                # code_sha should be None
                assert run["code_sha"] is None


class TestRollingStoreDoD202Fields:
    """v2.0.2: Test rolling_store DoD verification fields.
    
    Contract: m4_stability_agg.json.runs[] must contain fields needed
    for DoD verification without manually inspecting runDir bundles:
    - run_mode: REGISTRY_REAL or FIXTURE_OFFLINE
    - chain_id: e.g. 42161 for Arbitrum
    - pinned_block: real block number
    - block_is_synthetic: false for real runs
    """
    
    def test_emit_includes_run_mode(self):
        """emit_to_aggregator_light should include run_mode from inputs."""
        from m4.rolling_store import emit_to_aggregator_light
        from pathlib import Path
        import tempfile
        
        with tempfile.TemporaryDirectory() as tmpdir:
            agg_path = Path(tmpdir) / "test_agg.json"
            
            run_summary = {
                "run_id": "dod_test_001",
                "timestamp": "2026-02-13T12:00:00Z",
                "run_context": {"run_timestamp": "2026-02-13T12:00:00Z", "code_sha": None},
                "status": "PASS",
                "metrics": {"signals_count": 5, "total_net_usdc": 10.0, "mae_net_usdc": 0.5, "est_sign_correct_rate": 1.0, "fragile_rate": 0},
                "reasons": [],
                "inputs": {
                    "run_mode": "REGISTRY_REAL",
                    "chain_id": 42161,
                    "pinned_block": 431000000,
                    "block_is_synthetic": False,
                    "pairs": ["WETH/USDC"],
                    "routes": ["uniswap_v3->sushiswap_v3"],
                },
            }
            
            result = emit_to_aggregator_light(run_summary, agg_path)
            
            runs = result.get("runs", [])
            assert len(runs) == 1
            assert runs[0]["run_mode"] == "REGISTRY_REAL"
            assert runs[0]["chain_id"] == 42161
            assert runs[0]["pinned_block"] == 431000000
            assert runs[0]["block_is_synthetic"] is False
    
    def test_emit_dod_fields_offline(self):
        """emit_to_aggregator_light should store FIXTURE_OFFLINE mode correctly."""
        from m4.rolling_store import emit_to_aggregator_light
        from pathlib import Path
        import tempfile
        
        with tempfile.TemporaryDirectory() as tmpdir:
            agg_path = Path(tmpdir) / "test_agg.json"
            
            run_summary = {
                "run_id": "dod_test_offline_001",
                "timestamp": "2026-02-13T12:00:00Z",
                "run_context": {"run_timestamp": "2026-02-13T12:00:00Z", "code_sha": None},
                "status": "PASS",
                "metrics": {"signals_count": 5, "total_net_usdc": 10.0, "mae_net_usdc": 0.5, "est_sign_correct_rate": 1.0, "fragile_rate": 0},
                "reasons": [],
                "inputs": {
                    "run_mode": "FIXTURE_OFFLINE",
                    "chain_id": 42161,
                    "pinned_block": 429900000,  # synthetic
                    "block_is_synthetic": True,
                    "pairs": [],
                    "routes": [],
                },
            }
            
            result = emit_to_aggregator_light(run_summary, agg_path)
            
            runs = result.get("runs", [])
            assert len(runs) == 1
            assert runs[0]["run_mode"] == "FIXTURE_OFFLINE"
            assert runs[0]["block_is_synthetic"] is True

    def test_emit_dod_fields_unknown_defaults(self):
        """emit_to_aggregator_light should handle missing inputs gracefully."""
        from m4.rolling_store import emit_to_aggregator_light
        from pathlib import Path
        import tempfile
        
        with tempfile.TemporaryDirectory() as tmpdir:
            agg_path = Path(tmpdir) / "test_agg.json"
            
            # No inputs section
            run_summary = {
                "run_id": "dod_test_missing_001",
                "timestamp": "2026-02-13T12:00:00Z",
                "run_context": {"run_timestamp": "2026-02-13T12:00:00Z", "code_sha": None},
                "status": "PASS",
                "metrics": {"signals_count": 5, "total_net_usdc": 10.0, "mae_net_usdc": 0.5, "est_sign_correct_rate": 1.0, "fragile_rate": 0},
                "reasons": [],
                # Note: no inputs section
            }
            
            result = emit_to_aggregator_light(run_summary, agg_path)
            
            runs = result.get("runs", [])
            assert len(runs) == 1
            # Should have default/unknown values
            assert runs[0]["run_mode"] == "UNKNOWN"
            assert runs[0]["chain_id"] is None
            assert runs[0]["pinned_block"] is None
            assert runs[0]["block_is_synthetic"] is None


class TestUniqueRoutesCrossDex:
    """v2.0.8: Test unique_routes_cross_dex metric in quick_stats."""
    
    def test_unique_routes_cross_dex_exists_in_quick_stats(self):
        """quick_stats must have unique_routes_cross_dex key."""
        from m4.rolling_store import _compute_quick_stats
        
        # Run with cross-DEX and intra-DEX routes
        runs = [
            {
                "run_kind": "NORMAL",
                "signals_count": 3,
                "net_usdc": 5.0,
                "run_status": "PASS",
                "routes": ["sushiswap_v3->uniswap_v3", "sushiswap_v3->sushiswap_v3"],
                "pairs": ["WETH/USDC"],
            }
        ]
        
        result = _compute_quick_stats({"runs": runs})
        
        qs = result.get("quick_stats", {})
        # Key must exist and be an integer
        assert "unique_routes_cross_dex" in qs, "unique_routes_cross_dex missing"
        assert isinstance(qs["unique_routes_cross_dex"], int), "unique_routes_cross_dex must be int"
    
    def test_unique_routes_cross_dex_excludes_intra_dex(self):
        """unique_routes_cross_dex excludes same-DEX routes."""
        from m4.rolling_store import _compute_quick_stats
        
        # One cross-DEX route, one intra-DEX route
        runs = [
            {
                "run_kind": "NORMAL",
                "signals_count": 3,
                "net_usdc": 5.0,
                "run_status": "PASS",
                "routes": ["sushiswap_v3->uniswap_v3", "uniswap_v3->uniswap_v3"],
                "pairs": ["WETH/USDC"],
            }
        ]
        
        result = _compute_quick_stats({"runs": runs})
        qs = result.get("quick_stats", {})
        
        # unique_routes includes both (2), cross_dex only includes 1
        assert qs["unique_routes"] == 2
        assert qs["unique_routes_cross_dex"] == 1
    
    def test_is_cross_dex_route_function(self):
        """is_cross_dex_route correctly identifies cross-DEX routes."""
        from m4.rolling_store import is_cross_dex_route
        
        # Cross-DEX routes
        assert is_cross_dex_route("sushiswap_v3->uniswap_v3") is True
        assert is_cross_dex_route("uniswap_v3->sushiswap_v3") is True
        
        # Intra-DEX routes
        assert is_cross_dex_route("sushiswap_v3->sushiswap_v3") is False
        assert is_cross_dex_route("uniswap_v3->uniswap_v3") is False
        
        # Edge cases
        assert is_cross_dex_route("invalid") is False
        assert is_cross_dex_route("") is False


class TestDiversityRoutesLowUsesCrossDex:
    """v2.0.8: Test DIVERSITY_ROUTES_LOW warning uses unique_routes_cross_dex."""
    
    def test_diversity_routes_low_uses_cross_dex_not_total_routes(self):
        """DIVERSITY_ROUTES_LOW should trigger based on unique_routes_cross_dex, not unique_routes.
        
        v2.3.2: DIVERSITY_ROUTES_TARGET changed from 4 to 2 to match 2-DEX reality.
        With target=2 and min=2, if cross_dex>=2, no warning is triggered.
        Test uses only intra-DEX routes (same DEX on both sides) to trigger warning.
        """
        from m4.rolling_store import _compute_quick_stats
        from m4.policy import Thresholds
        
        # Scenario: 5 total routes but ZERO cross-DEX routes (all intra-DEX)
        # Note: route format is "buy_dex->sell_dex", same DEX = intra-DEX
        runs = [
            {
                "run_kind": "NORMAL",
                "signals_count": 3,
                "net_usdc": 5.0,
                "run_status": "PASS",
                "routes": [
                    "sushiswap_v3->sushiswap_v3",    # intra-DEX
                    "uniswap_v3->uniswap_v3",        # intra-DEX
                    "curve->curve",                   # intra-DEX
                    "balancer->balancer",             # intra-DEX
                    "pancake->pancake",               # intra-DEX
                ],
                "pairs": ["WETH/USDC", "LINK/USDC", "ARB/USDC", "GMX/USDC", "ARB/USDT"],
            }
        ]
        
        result = _compute_quick_stats({"runs": runs})
        qs = result.get("quick_stats", {})
        warnings = result.get("quality_warnings", [])
        
        # unique_routes=5, unique_routes_cross_dex=0 (all intra-DEX)
        assert qs["unique_routes"] == 5, f"Expected unique_routes=5, got {qs['unique_routes']}"
        assert qs["unique_routes_cross_dex"] == 0, f"Expected cross_dex=0, got {qs['unique_routes_cross_dex']}"
        
        # DIVERSITY_ROUTES warning should trigger (0 < 2 min)
        diversity_warnings = [w for w in warnings if w.startswith("DIVERSITY_ROUTES_LOW") or w.startswith("DIVERSITY_ROUTES_FAIL")]
        assert len(diversity_warnings) == 1, f"Expected DIVERSITY_ROUTES warning, got {warnings}"
        
        # The warning should reference cross_dex value (0<2), not total routes (5)
        assert "0<" in diversity_warnings[0], f"Warning should show 0<2: {diversity_warnings[0]}"
        assert "5<" not in diversity_warnings[0], f"Warning should NOT show 5: {diversity_warnings[0]}"
    
    def test_diversity_routes_passes_with_enough_cross_dex(self):
        """DIVERSITY_ROUTES_LOW should NOT trigger if unique_routes_cross_dex >= threshold."""
        from m4.rolling_store import _compute_quick_stats
        from m4.policy import Thresholds
        
        # Scenario: 4 cross-DEX routes + 2 intra-DEX = 6 total
        # unique_routes=6, unique_routes_cross_dex=4 >= threshold(4)
        runs = [
            {
                "run_kind": "NORMAL",
                "signals_count": 3,
                "net_usdc": 5.0,
                "run_status": "PASS",
                "routes": [
                    "sushiswap_v3->uniswap_v3", 
                    "uniswap_v3->sushiswap_v3",
                    "curve->uniswap_v3",
                    "sushiswap_v3->curve",
                    "sushiswap_v3->sushiswap_v3",  # intra
                    "uniswap_v3->uniswap_v3",      # intra
                ],
                "pairs": ["WETH/USDC", "LINK/USDC", "ARB/USDC", "GMX/USDC"],
            }
        ]
        
        result = _compute_quick_stats({"runs": runs})
        qs = result.get("quick_stats", {})
        warnings = result.get("quality_warnings", [])
        
        # unique_routes=6, unique_routes_cross_dex=4
        assert qs["unique_routes"] == 6
        assert qs["unique_routes_cross_dex"] == 4
        
        # DIVERSITY_ROUTES_LOW should NOT be in warnings (4 >= 4)
        diversity_warnings = [w for w in warnings if w.startswith("DIVERSITY_ROUTES_LOW")]
        assert len(diversity_warnings) == 0, f"Unexpected DIVERSITY_ROUTES_LOW: {warnings}"


class TestSweepFrontierInRolling:
    """Contract: sweep frontier metrics must propagate through rolling pipeline."""

    def _make_run_summary(self, *, sweep_best_net_pnl_bps=-17.13, gap_to_zero_bps=17.13,
                          sweep_best_frontier_reason="BEST_NEG", sweep_best_size_usd=50):
        return {
            "run_id": "sweep_test_001",
            "timestamp": "2026-03-10T20:00:00Z",
            "run_context": {
                "code_sha": None, "code_dirty": None, "code_desc": None,
                "run_timestamp": "2026-03-10T20:00:00Z",
            },
            "status": "PASS",
            "metrics": {
                "signals_count": 5, "total_net_usdc": 1.0,
                "mae_net_usdc": 0.3, "est_sign_correct_rate": 1.0, "fragile_rate": 0,
                "roundtrip": {
                    "evaluated_count": 3, "profitable_count": 0,
                    "best_net_pnl_bps": -29.96,
                    "dynamic_sweep": {
                        "sweep_best_net_pnl_bps": sweep_best_net_pnl_bps,
                        "sweep_best_size_usd": sweep_best_size_usd,
                        "sweep_best_frontier_reason": sweep_best_frontier_reason,
                        "gap_to_zero_bps": gap_to_zero_bps,
                        "routes_swept": 3,
                    },
                },
            },
            "reasons": [],
            "inputs": {"pairs": ["WETH/USDC"], "routes": ["uniswap_v3->sushiswap_v3"]},
        }

    def test_emit_carries_sweep_per_run_fields(self):
        """emit_to_aggregator_light must record sweep fields in per-run entry."""
        from m4.rolling_store import emit_to_aggregator_light
        from pathlib import Path
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            agg_path = Path(tmpdir) / "test_agg.json"
            run_summary = self._make_run_summary()
            result = emit_to_aggregator_light(run_summary, agg_path)

            run_entry = result["runs"][0]
            assert run_entry["sweep_best_net_pnl_bps"] == -17.13
            assert run_entry["sweep_gap_to_zero_bps"] == 17.13
            assert run_entry["sweep_frontier_reason"] == "BEST_NEG"

    def test_quick_stats_aggregates_sweep(self):
        """_compute_quick_stats must aggregate sweep metrics across runs."""
        from m4.rolling_store import _compute_quick_stats

        runs = [
            {"run_kind": "NORMAL", "signals_count": 5,
             "sweep_best_net_pnl_bps": -17.13, "sweep_gap_to_zero_bps": 17.13,
             "sweep_frontier_reason": "BEST_NEG"},
            {"run_kind": "NORMAL", "signals_count": 3,
             "sweep_best_net_pnl_bps": -10.0, "sweep_gap_to_zero_bps": 10.0,
             "sweep_frontier_reason": "BEST_NEG"},
        ]

        result = _compute_quick_stats({"runs": runs})
        qs = result.get("quick_stats", {})

        assert qs["sweep_runs_count"] == 2
        # max of (-17.13, -10.0) = -10.0 (closer to zero = better)
        assert qs["sweep_best_pnl_bps_ever"] == -10.0
        # min of (17.13, 10.0) = 10.0 (closer to zero = better)
        assert qs["sweep_gap_to_zero_min"] == 10.0

    def test_quick_stats_sweep_absent_graceful(self):
        """_compute_quick_stats handles runs without sweep fields gracefully."""
        from m4.rolling_store import _compute_quick_stats

        runs = [
            {"run_kind": "NORMAL", "signals_count": 5},  # no sweep fields
        ]
        result = _compute_quick_stats({"runs": runs})
        qs = result.get("quick_stats", {})

        assert qs["sweep_runs_count"] == 0
        assert qs["sweep_best_pnl_bps_ever"] is None
        assert qs["sweep_gap_to_zero_min"] is None

    def test_emit_carries_measured_cost_fields(self):
        """emit_to_aggregator_light must record measured cost decomposition per run."""
        from m4.rolling_store import emit_to_aggregator_light
        from pathlib import Path
        import tempfile

        run_summary = self._make_run_summary()
        ds = run_summary["metrics"]["roundtrip"]["dynamic_sweep"]
        ds["measured_gas_bps"] = 3.2
        ds["measured_fee_bps"] = 60.0
        ds["measured_slippage_bps"] = 1.5
        ds["measured_total_cost_bps"] = 64.7
        ds["frontier_pair"] = "WETH/USDC"

        with tempfile.TemporaryDirectory() as tmpdir:
            agg_path = Path(tmpdir) / "test_agg.json"
            result = emit_to_aggregator_light(run_summary, agg_path)

            entry = result["runs"][0]
            assert entry.get("sweep_measured_gas_bps") == 3.2
            assert entry.get("sweep_measured_fee_bps") == 60.0
            assert entry.get("sweep_measured_slippage_bps") == 1.5
            assert entry.get("sweep_measured_total_cost_bps") == 64.7
            assert entry.get("sweep_frontier_pair") == "WETH/USDC"

    def test_quick_stats_median_and_frontier_latest(self):
        """_compute_quick_stats includes median gap/pnl and frontier_pair/chain_latest."""
        from m4.rolling_store import _compute_quick_stats

        runs = [
            {"run_kind": "NORMAL", "signals_count": 5,
             "sweep_best_net_pnl_bps": -17.0, "sweep_gap_to_zero_bps": 17.0,
             "sweep_frontier_reason": "BEST_NEG",
             "sweep_measured_gas_bps": 2.0, "sweep_measured_fee_bps": 50.0,
             "sweep_frontier_pair": "WETH/USDC"},
            {"run_kind": "NORMAL", "signals_count": 3,
             "sweep_best_net_pnl_bps": -10.0, "sweep_gap_to_zero_bps": 10.0,
             "sweep_frontier_reason": "BEST_NEG",
             "sweep_measured_gas_bps": 1.5, "sweep_measured_fee_bps": 30.0,
             "sweep_frontier_pair": "WBTC/USDC"},
        ]

        result = _compute_quick_stats({"runs": runs})
        qs = result.get("quick_stats", {})

        # Medians of [17.0, 10.0] → p50 ≈ 10.0..17.0 range
        assert qs.get("sweep_median_gap_to_zero_bps") is not None
        assert qs.get("sweep_median_net_pnl_bps") is not None
        # frontier_pair_latest = last run's frontier pair
        assert qs.get("frontier_pair_latest") == "WBTC/USDC"


class TestPerChainFrontierAggregates:
    """R14: per_chain_frontier in quick_stats for multi-chain economics ranking."""

    def test_per_chain_frontier_exists(self):
        """quick_stats must include per_chain_frontier dict."""
        from m4.rolling_store import _compute_quick_stats

        runs = [
            {"run_kind": "NORMAL", "signals_count": 5, "chain_key": "arbitrum_one",
             "sweep_best_net_pnl_bps": -10.0, "sweep_gap_to_zero_bps": 10.0,
             "sweep_frontier_pair": "WETH/USDT"},
            {"run_kind": "NORMAL", "signals_count": 3, "chain_key": "base",
             "sweep_best_net_pnl_bps": -15.0, "sweep_gap_to_zero_bps": 15.0,
             "sweep_frontier_pair": "WETH/USDC"},
        ]
        result = _compute_quick_stats({"runs": runs})
        qs = result.get("quick_stats", {})
        assert "per_chain_frontier" in qs
        pcf = qs["per_chain_frontier"]
        assert "arbitrum_one" in pcf
        assert "base" in pcf

    def test_per_chain_frontier_gap_values(self):
        """Per-chain gap_to_zero_min and gap_to_zero_median are computed correctly."""
        from m4.rolling_store import _compute_quick_stats

        runs = [
            {"run_kind": "NORMAL", "signals_count": 5, "chain_key": "arbitrum_one",
             "sweep_best_net_pnl_bps": -10.0, "sweep_gap_to_zero_bps": 10.0,
             "sweep_frontier_pair": "WETH/USDT"},
            {"run_kind": "NORMAL", "signals_count": 5, "chain_key": "arbitrum_one",
             "sweep_best_net_pnl_bps": -20.0, "sweep_gap_to_zero_bps": 20.0,
             "sweep_frontier_pair": "WETH/USDC"},
            {"run_kind": "NORMAL", "signals_count": 3, "chain_key": "base",
             "sweep_best_net_pnl_bps": -8.0, "sweep_gap_to_zero_bps": 8.0,
             "sweep_frontier_pair": "WETH/USDC"},
        ]
        result = _compute_quick_stats({"runs": runs})
        pcf = result["quick_stats"]["per_chain_frontier"]

        arb = pcf["arbitrum_one"]
        assert arb["normal_runs"] == 2
        assert arb["sweep_runs"] == 2
        assert arb["gap_to_zero_min"] == 10.0
        assert arb["frontier_pair_latest"] == "WETH/USDC"

        base = pcf["base"]
        assert base["normal_runs"] == 1
        assert base["sweep_runs"] == 1
        assert base["gap_to_zero_min"] == 8.0

    def test_per_chain_frontier_no_sweep_data(self):
        """Chain with no sweep data has None gap values."""
        from m4.rolling_store import _compute_quick_stats

        runs = [
            {"run_kind": "NORMAL", "signals_count": 5, "chain_key": "linea"},
        ]
        result = _compute_quick_stats({"runs": runs})
        pcf = result["quick_stats"]["per_chain_frontier"]
        assert pcf["linea"]["sweep_runs"] == 0
        assert pcf["linea"]["gap_to_zero_min"] is None
        assert pcf["linea"]["gap_to_zero_median"] is None

    def test_per_chain_frontier_empty_when_no_chains(self):
        """per_chain_frontier is empty dict when no chain_keys present."""
        from m4.rolling_store import _compute_quick_stats

        runs = [
            {"run_kind": "NORMAL", "signals_count": 5},
        ]
        result = _compute_quick_stats({"runs": runs})
        pcf = result["quick_stats"]["per_chain_frontier"]
        assert pcf == {}
