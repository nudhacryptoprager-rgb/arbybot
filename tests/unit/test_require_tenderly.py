# PATH: tests/unit/test_require_tenderly.py
"""Unit tests for --require-tenderly flag in ci_m5_0_gate."""

import json
import tempfile
from pathlib import Path
from datetime import datetime, timezone

import pytest


class TestRequireTenderly:
    """Tests for --require-tenderly validation."""
    
    @pytest.fixture
    def temp_run_dir(self, tmp_path):
        """Create a temporary run directory with minimal fixtures."""
        reports_dir = tmp_path / "reports"
        reports_dir.mkdir(parents=True)
        return tmp_path
    
    def _create_artifacts(self, run_dir: Path, tenderly_enabled: bool, tenderly_ok: bool = None, tenderly_error: str = None, run_mode: str = "REGISTRY_REAL"):
        """Create test artifacts with specified tenderly state."""
        reports_dir = run_dir / "reports"
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        now = datetime.now(timezone.utc).isoformat()
        
        infra = {
            "rpc_provider": "alchemy",
            "rpc_http_host": "arb-mainnet.g.alchemy.com",
            "transport": "http",
            "ws_enabled": False,
            "tenderly_enabled": tenderly_enabled,
        }
        if tenderly_ok is not None:
            infra["tenderly_ok"] = tenderly_ok
        if tenderly_error is not None:
            infra["tenderly_error"] = tenderly_error
        
        scan_data = {
            "schema_version": "3.2.0",
            "timestamp": now,
            "run_mode": run_mode,
            "current_block": 100000000,
            "chain_id": 42161,
            "infra": infra,
            "quotes_total": 6,
            "quotes_fetched": 6,
            "dexes_active": 2,
            "price_sanity_passed": 6,
            "price_sanity_failed": 0,
            "stats": {"quotes_total": 6, "quotes_fetched": 6},
            "quotes": [],
        }
        
        truth_data = {
            "schema_version": "3.2.0",
            "timestamp": now,
            "run_mode": run_mode,
            "current_block": 100000000,
            "chain_id": 42161,
            "infra": infra,
            "execution_enabled": False,
            "execution_ready_count": 0,
            "quotes_total": 6,
            "quotes_fetched": 6,
            "dexes_active": 2,
            "price_sanity_passed": 6,
            "price_sanity_failed": 0,
            "health": {"quotes_total": 6, "quotes_fetched": 6},
            "spread_signals": [],
        }
        
        reject_data = {
            "schema_version": "3.2.0",
            "timestamp": now,
            "run_mode": run_mode,
            "current_block": 100000000,
            "chain_id": 42161,
            "infra": infra,
            "rejects": [],
            "rejects_total": 0,
            "total_rejects": 0,
            "no_rejects": True,
            "price_sanity_failed": 0,
        }
        
        scan_path = reports_dir / f"scan_{ts}.json"
        truth_path = reports_dir / f"truth_report_{ts}.json"
        reject_path = reports_dir / f"reject_histogram_{ts}.json"
        
        scan_path.write_text(json.dumps(scan_data, indent=2))
        truth_path.write_text(json.dumps(truth_data, indent=2))
        reject_path.write_text(json.dumps(reject_data, indent=2))
        
        return scan_path, truth_path, reject_path
    
    def test_tenderly_disabled_passes_without_require(self, temp_run_dir):
        """When tenderly_enabled=false and --require-tenderly not set, should pass."""
        from scripts.ci_m5_0_gate import validate_artifacts
        
        scan_path, truth_path, reject_path = self._create_artifacts(temp_run_dir, tenderly_enabled=False)
        
        artifacts = {
            "scan": scan_path,
            "truth_report": truth_path,
            "reject_histogram": reject_path,
        }
        
        passed, messages = validate_artifacts(artifacts, require_tenderly=False)
        
        assert passed, f"Should pass but got: {messages}"
    
    def test_tenderly_disabled_passes_with_require(self, temp_run_dir):
        """When tenderly_enabled=false and --require-tenderly set, should still pass."""
        from scripts.ci_m5_0_gate import validate_artifacts
        
        scan_path, truth_path, reject_path = self._create_artifacts(temp_run_dir, tenderly_enabled=False)
        
        artifacts = {
            "scan": scan_path,
            "truth_report": truth_path,
            "reject_histogram": reject_path,
        }
        
        passed, messages = validate_artifacts(artifacts, require_tenderly=True)
        
        # Should pass because tenderly_enabled=false means we don't require tenderly
        assert passed, f"Should pass but got: {messages}"
    
    def test_tenderly_enabled_ok_passes(self, temp_run_dir):
        """When tenderly_enabled=true and tenderly_ok=true, should pass."""
        from scripts.ci_m5_0_gate import validate_artifacts
        
        scan_path, truth_path, reject_path = self._create_artifacts(temp_run_dir, tenderly_enabled=True, tenderly_ok=True)
        
        artifacts = {
            "scan": scan_path,
            "truth_report": truth_path,
            "reject_histogram": reject_path,
        }
        
        passed, messages = validate_artifacts(artifacts, require_tenderly=True)
        
        assert passed, f"Should pass but got: {messages}"
    
    def test_tenderly_enabled_no_ok_fails_with_require(self, temp_run_dir):
        """When tenderly_enabled=true but no tenderly_ok and --require-tenderly, should fail."""
        from scripts.ci_m5_0_gate import validate_artifacts
        
        scan_path, truth_path, reject_path = self._create_artifacts(temp_run_dir, tenderly_enabled=True, tenderly_ok=None)
        
        artifacts = {
            "scan": scan_path,
            "truth_report": truth_path,
            "reject_histogram": reject_path,
        }
        
        passed, messages = validate_artifacts(artifacts, require_tenderly=True)
        
        # Should fail because tenderly_enabled but no tenderly_ok
        assert not passed, f"Should fail but passed: {messages}"
        assert any("tenderly" in m.lower() for m in messages), f"Should mention tenderly: {messages}"
    
    def test_tenderly_enabled_no_ok_warns_without_require(self, temp_run_dir):
        """When tenderly_enabled=true but no tenderly_ok and --require-tenderly not set, should warn but pass."""
        from scripts.ci_m5_0_gate import validate_artifacts
        
        scan_path, truth_path, reject_path = self._create_artifacts(temp_run_dir, tenderly_enabled=True, tenderly_ok=None)
        
        artifacts = {
            "scan": scan_path,
            "truth_report": truth_path,
            "reject_histogram": reject_path,
        }
        
        passed, messages = validate_artifacts(artifacts, require_tenderly=False)
        
        # Should pass but with warning
        assert passed, f"Should pass but got: {messages}"
        assert any("WARN" in m and "tenderly" in m.lower() for m in messages), f"Should have tenderly warning: {messages}"
    
    def test_tenderly_with_error_passes(self, temp_run_dir):
        """When tenderly_enabled=true with tenderly_error, should pass (error documented)."""
        from scripts.ci_m5_0_gate import validate_artifacts
        
        scan_path, truth_path, reject_path = self._create_artifacts(
            temp_run_dir, 
            tenderly_enabled=True, 
            tenderly_ok=False, 
            tenderly_error="connection_timeout"
        )
        
        artifacts = {
            "scan": scan_path,
            "truth_report": truth_path,
            "reject_histogram": reject_path,
        }
        
        passed, messages = validate_artifacts(artifacts, require_tenderly=True)
        
        # Should pass because tenderly_error is documented
        assert passed, f"Should pass but got: {messages}"

    def test_require_simulation_alias(self, temp_run_dir):
        """E1.12.4A: --require-simulation is an alias for --require-tenderly validation."""
        from scripts.ci_m5_0_gate import validate_artifacts

        scan_path, truth_path, reject_path = self._create_artifacts(
            temp_run_dir,
            tenderly_enabled=True,
            tenderly_ok=True,
        )

        artifacts = {
            "scan": scan_path,
            "truth_report": truth_path,
            "reject_histogram": reject_path,
        }

        # require_tenderly=True (which --require-simulation sets)
        passed, messages = validate_artifacts(artifacts, require_tenderly=True)
        assert passed, f"Should pass but got: {messages}"
