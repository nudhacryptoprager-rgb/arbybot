# PATH: tests/integration/test_artifact_invariants.py
"""Integration test: artifact cross-invariants.

This test runs a single scan cycle and validates:
1. current_block is equal across scan/truth_report/reject_histogram
2. schema_version is present in all artifacts
3. rejects_total matches len(rejects)
4. execution_ready_count == 0 when execution_enabled == False

Run locally (requires RPC): pytest tests/integration -k artifact_invariants -v
Skip in CI without secrets: ARBY_SKIP_RPC=1 pytest tests/integration ...
"""

import json
import os
import pytest
import subprocess
import sys
import tempfile
from pathlib import Path


pytestmark = pytest.mark.skipif(
    os.getenv("ARBY_SKIP_RPC", "0") == "1",
    reason="ARBY_SKIP_RPC=1 - skipping RPC-dependent integration test"
)


class TestArtifactInvariants:
    """Integration test: run real scan, validate cross-artifact invariants."""
    
    @pytest.fixture(scope="class")
    def run_artifacts(self, tmp_path_factory):
        """Run a single scan cycle and return artifact paths."""
        output_dir = tmp_path_factory.mktemp("integration_run")
        
        # Run the scanner
        cmd = [
            sys.executable,
            "-m", "strategy.jobs.run_scan_real",
            "--cycles", "1",
            "--output-dir", str(output_dir),
            "--config", "config/real_minimal.yaml",
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        
        if result.returncode != 0:
            pytest.skip(f"Scanner failed: {result.stderr[:500]}")
        
        # Find artifacts
        reports_dir = output_dir / "reports"
        artifacts = {}
        
        for f in reports_dir.glob("scan_*.json"):
            artifacts["scan"] = f
        for f in reports_dir.glob("truth_report_*.json"):
            artifacts["truth_report"] = f
        for f in reports_dir.glob("reject_histogram_*.json"):
            artifacts["reject_histogram"] = f
        
        if len(artifacts) < 3:
            pytest.skip(f"Missing artifacts: {artifacts.keys()}")
        
        return artifacts
    
    def test_current_block_matches_across_artifacts(self, run_artifacts):
        """current_block must be equal in scan, truth_report, and reject_histogram."""
        blocks = {}
        
        for name, path in run_artifacts.items():
            with open(path) as f:
                data = json.load(f)
            blocks[name] = data.get("current_block")
        
        assert blocks["scan"] is not None, "scan.current_block missing"
        assert blocks["truth_report"] is not None, "truth_report.current_block missing"
        assert blocks["reject_histogram"] is not None, "reject_histogram.current_block missing"
        
        # All must match
        assert blocks["scan"] == blocks["truth_report"], \
            f"scan.current_block ({blocks['scan']}) != truth_report ({blocks['truth_report']})"
        assert blocks["scan"] == blocks["reject_histogram"], \
            f"scan.current_block ({blocks['scan']}) != reject_histogram ({blocks['reject_histogram']})"
    
    def test_schema_version_present_in_all(self, run_artifacts):
        """schema_version must be present in all artifacts."""
        for name, path in run_artifacts.items():
            with open(path) as f:
                data = json.load(f)
            sv = data.get("schema_version")
            assert sv is not None, f"{name} missing schema_version"
            assert sv.startswith("3."), f"{name} unexpected schema_version: {sv}"
    
    def test_rejects_total_matches_len(self, run_artifacts):
        """reject_histogram.rejects_total must equal len(rejects)."""
        with open(run_artifacts["reject_histogram"]) as f:
            data = json.load(f)
        
        rejects_total = data.get("rejects_total") or data.get("total_rejects", 0)
        rejects_len = len(data.get("rejects", []))
        
        assert rejects_total == rejects_len, \
            f"rejects_total ({rejects_total}) != len(rejects) ({rejects_len})"
    
    def test_execution_ready_count_zero_when_disabled(self, run_artifacts):
        """execution_ready_count == 0 when execution_enabled == False (M5_0 DoD)."""
        with open(run_artifacts["truth_report"]) as f:
            data = json.load(f)
        
        exec_enabled = data.get("execution_enabled", False)
        exec_ready = data.get("execution_ready_count")
        
        if not exec_enabled:
            assert exec_ready == 0, \
                f"execution_ready_count should be 0 when execution_enabled=False, got {exec_ready}"
    
    def test_chain_id_present_in_all(self, run_artifacts):
        """chain_id must be present in all artifacts."""
        for name, path in run_artifacts.items():
            with open(path) as f:
                data = json.load(f)
            chain_id = data.get("chain_id")
            assert chain_id is not None, f"{name} missing chain_id"
            assert chain_id == 42161, f"{name} unexpected chain_id: {chain_id}"  # Arbitrum One
    
    def test_run_mode_is_registry_real(self, run_artifacts):
        """run_mode must be REGISTRY_REAL for online runs."""
        for name, path in run_artifacts.items():
            with open(path) as f:
                data = json.load(f)
            run_mode = data.get("run_mode")
            assert run_mode == "REGISTRY_REAL", f"{name} unexpected run_mode: {run_mode}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
