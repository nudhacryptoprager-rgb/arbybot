# PATH: tests/unit/test_rolling_store_provenance.py
"""
Tests for rolling_store provenance logic.

v2.0.0: SHA provenance REMOVED - timestamp-based tracking only.

Contract:
- run_context.code_sha/evidence_sha are None (deprecated)
- run_context.run_timestamp is the primary provenance field
- _compute_quick_stats works without SHA
"""

import pytest


class TestRollingSHAProvenance:
    """v2.0.0: Test rolling_store provenance logic (SHA-free)."""
    
    def test_compute_quick_stats_no_args_works(self):
        """_compute_quick_stats with no run_summary/target_sha works."""
        from m4.rolling_store import _compute_quick_stats
        
        result = _compute_quick_stats({"runs": []})
        
        # Should not crash
        assert "runs_since_sha" in result
        assert "sha" in result["runs_since_sha"]
        # SHA is now None (tracking removed)
        assert result["runs_since_sha"]["sha"] is None
    
    def test_compute_quick_stats_with_target_sha(self):
        """_compute_quick_stats with explicit target_sha uses it (backward compat)."""
        from m4.rolling_store import _compute_quick_stats
        
        result = _compute_quick_stats(
            {"runs": [{"code_sha": "abc123", "run_kind": "NORMAL", "signals_count": 5}]},
            target_sha="abc123"
        )
        
        # Still respects explicit target_sha for backward compat
        assert result["runs_since_sha"]["sha"] == "abc123"
        assert result["runs_since_sha"]["runs_count"] == 1
    
    def test_compute_quick_stats_with_run_summary_context(self):
        """_compute_quick_stats extracts SHA from run_summary.run_context (backward compat)."""
        from m4.rolling_store import _compute_quick_stats
        
        run_summary = {"run_context": {"code_sha": "def456"}}
        result = _compute_quick_stats(
            {"runs": [{"code_sha": "def456", "run_kind": "NORMAL", "signals_count": 5}]},
            run_summary=run_summary
        )
        
        # Uses artifact SHA if provided
        assert result["runs_since_sha"]["sha"] == "def456"
        assert result["runs_since_sha"]["runs_count"] == 1
    
    def test_compute_quick_stats_target_sha_overrides_run_summary(self):
        """target_sha takes priority over run_summary.run_context.code_sha."""
        from m4.rolling_store import _compute_quick_stats
        
        run_summary = {"run_context": {"code_sha": "from_artifact"}}
        result = _compute_quick_stats(
            {"runs": [{"code_sha": "explicit_target", "run_kind": "NORMAL", "signals_count": 5}]},
            run_summary=run_summary,
            target_sha="explicit_target"
        )
        
        # target_sha wins
        assert result["runs_since_sha"]["sha"] == "explicit_target"
        assert result["runs_since_sha"]["runs_count"] == 1
    
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
    
    def test_emit_uses_artifact_sha_not_git(self):
        """emit_to_aggregator_light should use run_summary.run_context.code_sha."""
        from m4.rolling_store import emit_to_aggregator_light
        from pathlib import Path
        import tempfile
        import json
        
        with tempfile.TemporaryDirectory() as tmpdir:
            agg_path = Path(tmpdir) / "test_agg.json"
            
            run_summary = {
                "run_id": "test_run_001",
                "timestamp": "2026-02-10T12:00:00Z",
                "run_context": {
                    "code_sha": "artifact_sha_123",
                    "code_dirty": False,
                    "code_desc": "artifact_sha_123",
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
            
            # Check that the run entry uses artifact SHA
            runs = result.get("runs", [])
            assert len(runs) == 1
            assert runs[0]["code_sha"] == "artifact_sha_123"


class TestRollingIntegrationContract:
    """Step 8: Integration tests for rolling artifact consistency."""
    
    def test_emit_aggregator_tracks_run_sha(self):
        """emit_to_aggregator_light must record artifact SHA in run entry."""
        from m4.rolling_store import emit_to_aggregator_light
        from pathlib import Path
        import tempfile
        
        with tempfile.TemporaryDirectory() as tmpdir:
            agg_path = Path(tmpdir) / "m4_stability_agg.json"
            
            # Create run_summary with specific SHA
            run_summary = {
                "run_id": "consistency_test_001",
                "timestamp": "2026-02-10T15:00:00Z",
                "run_context": {
                    "code_sha": "test_sha_abc",
                    "code_dirty": False,
                    "code_desc": "test_sha_abc",
                    "evidence_sha": None,
                },
                "status": "PASS",
                "metrics": {
                    "signals_count": 5,
                    "total_net_usdc": 5.0,
                    "mae_net_usdc": 0.3,
                    "est_sign_correct_rate": 1.0,
                    "fragile_rate": 0,
                },
                "reasons": [],
                "inputs": {"pairs": ["A/B"], "routes": ["dex1->dex2"]},
            }
            
            # Emit to aggregator
            agg_data = emit_to_aggregator_light(run_summary, agg_path)
            
            # Verify consistency: run entry has artifact SHA
            runs = agg_data.get("runs", [])
            assert len(runs) == 1
            assert runs[0]["code_sha"] == "test_sha_abc"
            
            # Verify aggregator has quick_stats
            qs = agg_data.get("quick_stats", {})
            assert qs is not None
            # runs_since_sha is computed via _compute_quick_stats during gate, not emit
    
    def test_multiple_runs_append_to_aggregator(self):
        """Multiple emits append to runs, not overwrite."""
        from m4.rolling_store import emit_to_aggregator_light
        from pathlib import Path
        import tempfile
        
        with tempfile.TemporaryDirectory() as tmpdir:
            agg_path = Path(tmpdir) / "m4_stability_agg.json"
            
            base_summary = {
                "timestamp": "2026-02-10T15:00:00Z",
                "run_context": {"code_sha": "v1", "code_dirty": False, "code_desc": "v1", "evidence_sha": None},
                "status": "PASS",
                "metrics": {"signals_count": 5, "total_net_usdc": 1.0, "mae_net_usdc": 0.3, "est_sign_correct_rate": 1.0, "fragile_rate": 0},
                "reasons": [],
                "inputs": {"pairs": ["A/B"], "routes": ["dex1->dex2"]},
            }
            
            # First run
            run1 = {**base_summary, "run_id": "run_001", "run_context": {**base_summary["run_context"], "code_sha": "sha_v1"}}
            agg1 = emit_to_aggregator_light(run1, agg_path)
            
            # Second run (should append)
            run2 = {**base_summary, "run_id": "run_002", "run_context": {**base_summary["run_context"], "code_sha": "sha_v2"}}
            agg2 = emit_to_aggregator_light(run2, agg_path)
            
            # Aggregator should have 2 runs
            assert len(agg2.get("runs", [])) == 2
            assert agg2["runs"][0]["code_sha"] == "sha_v1"
            assert agg2["runs"][1]["code_sha"] == "sha_v2"


class TestSHAPriority:
    """Step 9: Test SHA resolution priority (v2.0 - SHA deprecated)."""
    
    def test_sha_priority_backward_compat(self):
        """SHA priority still works for backward compat when explicitly provided."""
        from m4.rolling_store import _compute_quick_stats
        
        # Priority 1: target_sha wins when provided (backward compat)
        run_summary = {"run_context": {"code_sha": "from_artifact"}}
        result = _compute_quick_stats(
            {"runs": [{"code_sha": "target", "run_kind": "NORMAL", "signals_count": 5}]},
            run_summary=run_summary,
            target_sha="target"
        )
        assert result["runs_since_sha"]["sha"] == "target", "target_sha should have highest priority"
        
        # Priority 2: run_summary.run_context.code_sha when no target_sha
        result2 = _compute_quick_stats(
            {"runs": [{"code_sha": "artifact", "run_kind": "NORMAL", "signals_count": 5}]},
            run_summary={"run_context": {"code_sha": "artifact"}}
        )
        assert result2["runs_since_sha"]["sha"] == "artifact", "run_context.code_sha should be used"
        
        # Priority 3: git fallback now returns None (SHA tracking removed)
        result3 = _compute_quick_stats({"runs": []})
        assert result3["runs_since_sha"]["sha"] is None, "git SHA fallback removed, should be None"
    
    def test_timestamp_is_now_primary_provenance(self):
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
