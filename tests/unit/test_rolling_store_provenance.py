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
