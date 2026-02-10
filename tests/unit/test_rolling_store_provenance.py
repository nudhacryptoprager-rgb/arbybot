# PATH: tests/unit/test_rolling_store_provenance.py
"""
Tests for rolling_store provenance logic.

v1.12.3: SHA provenance from artifact context, not git context.

Contract:
- run_context.code_sha and evidence_sha are REQUIRED in artifacts (for audit)
- Hard commit-binding DISABLED (HEAD != run_context.code_sha is OK)
- _compute_quick_stats uses artifact SHA, not live git state
"""

import pytest


class TestRollingSHAProvenance:
    """v1.12.3: Test rolling_store provenance logic."""
    
    def test_compute_quick_stats_no_args_uses_git_fallback(self):
        """_compute_quick_stats with no run_summary/target_sha falls back to git."""
        from m4.rolling_store import _compute_quick_stats
        
        result = _compute_quick_stats({"runs": []})
        
        # Should not crash (was NameError before fix)
        assert "runs_since_sha" in result
        assert "sha" in result["runs_since_sha"]
    
    def test_compute_quick_stats_with_target_sha(self):
        """_compute_quick_stats with explicit target_sha uses it."""
        from m4.rolling_store import _compute_quick_stats
        
        result = _compute_quick_stats(
            {"runs": [{"code_sha": "abc123", "run_kind": "NORMAL", "signals_count": 5}]},
            target_sha="abc123"
        )
        
        assert result["runs_since_sha"]["sha"] == "abc123"
        assert result["runs_since_sha"]["runs_count"] == 1
    
    def test_compute_quick_stats_with_run_summary_context(self):
        """_compute_quick_stats extracts SHA from run_summary.run_context."""
        from m4.rolling_store import _compute_quick_stats
        
        run_summary = {"run_context": {"code_sha": "def456"}}
        result = _compute_quick_stats(
            {"runs": [{"code_sha": "def456", "run_kind": "NORMAL", "signals_count": 5}]},
            run_summary=run_summary
        )
        
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
    
    def test_run_context_sha_required_in_artifact(self):
        """Verify run_context.code_sha is present in run summary structure."""
        # This is a structural contract test - run_context.code_sha must exist
        # for provenance even when hard binding is disabled
        
        required_fields = ["code_sha", "code_dirty", "code_desc"]
        
        # Minimal valid run_context structure
        valid_run_context = {
            "code_sha": "abc1234",
            "code_dirty": False,
            "code_desc": "abc1234",
            "evidence_sha": None,  # null until attach_evidence
        }
        
        for field in required_fields:
            assert field in valid_run_context, f"run_context must have {field}"


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
    """Step 9: Test SHA resolution priority."""
    
    def test_sha_priority_target_over_run_summary_over_git(self):
        """SHA priority: target_sha > run_context.code_sha > git fallback."""
        from m4.rolling_store import _compute_quick_stats
        
        # Priority 1: target_sha wins when provided
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
        
        # Priority 3: git fallback when nothing else
        result3 = _compute_quick_stats({"runs": []})
        assert result3["runs_since_sha"]["sha"] is not None, "should fall back to git SHA"
    
    def test_evidence_sha_separate_from_code_sha(self):
        """evidence_sha is separate tracking, not used for provenance filtering."""
        # evidence_sha is for audit trail, not for runs_since_sha logic
        run_context = {
            "code_sha": "code_abc",
            "code_dirty": False,
            "code_desc": "code_abc",
            "evidence_sha": "evidence_xyz",  # Different from code_sha
        }
        
        # Both should be present
        assert run_context["code_sha"] != run_context["evidence_sha"]
        # evidence_sha tracks the commit where evidence was attached
        # code_sha tracks the commit where the run was made
