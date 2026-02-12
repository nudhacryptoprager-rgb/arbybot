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
