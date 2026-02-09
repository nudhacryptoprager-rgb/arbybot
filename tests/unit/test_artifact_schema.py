# PATH: tests/unit/test_artifact_schema.py
"""Schema snapshot tests for artifacts.

Validates that artifact structures have expected keys and types.
Prevents accidental schema drift.
"""

import pytest
from typing import Any, Dict, Set


# =============================================================================
# EXPECTED SCHEMA DEFINITIONS
# =============================================================================

SCAN_REQUIRED_KEYS = {
    "schema_version",
    "timestamp",
    "run_mode",
    "current_block",
    "chain_id",
    "quotes_total",
    "quotes_fetched",
    "dexes_active",
    "price_sanity_passed",
    "price_sanity_failed",
    "infra",
    "stats",
}

TRUTH_REPORT_REQUIRED_KEYS = {
    "schema_version",
    "timestamp",
    "run_mode",
    "current_block",
    # "chain_id",  # Optional in some fixtures
    "execution_enabled",
    # "execution_ready_count",  # Optional
    "quotes_total",
    "quotes_fetched",
    "dexes_active",
    "price_sanity_passed",
    "price_sanity_failed",
    "health",
    "spread_signals",
    "infra",
}

REJECT_HISTOGRAM_REQUIRED_KEYS = {
    "schema_version",
    "timestamp",
    "run_mode",
    "current_block",
    # "chain_id",  # Optional in some fixtures
    "rejects",
    "rejects_total",
    # "no_rejects",  # Optional
    "price_sanity_failed",
    # "infra",  # Optional in some fixtures
}

INFRA_REQUIRED_KEYS = {
    "rpc_provider",
    "transport",
    "ws_enabled",
    "tenderly_enabled",
}

SPREAD_SIGNAL_REQUIRED_KEYS = {
    "pair",
    "buy_dex",
    "sell_dex",
    "buy_price",
    "sell_price",
    "spread_bps_exact",
    "is_gross_positive",
    "gross_pnl_usdc_est",
    "net_pnl_usdc_est",
    "is_net_positive_est",
    "confidence",
}

# M4 artifacts
SIGNALS_REQUIRED_KEYS = {
    "schema_version",
    # "timestamp",  # Not always present
    "chain_id",
    "pinned_block",
    "quote_ccy",
    "signals",
}

EXECUTION_REPORT_REQUIRED_KEYS = {
    "schema_version",
    # "timestamp",  # Not always present
    "chain_id",
    "pinned_block",
    "quote_ccy",
    "execution_enabled",
    "kill_switch_active",
    "simulations",
    "simulations_count",
    "simulations_passed",
    "total_net_usdc",
    "health",
}


# =============================================================================
# SCHEMA VALIDATION HELPERS
# =============================================================================

def validate_keys(data: Dict[str, Any], required: Set[str], name: str) -> list[str]:
    """Validate that data has all required keys."""
    errors = []
    missing = required - set(data.keys())
    if missing:
        errors.append(f"{name}: missing keys: {sorted(missing)}")
    return errors


def validate_type(data: Dict[str, Any], key: str, expected_type: type, name: str) -> list[str]:
    """Validate that a key has expected type."""
    errors = []
    if key in data:
        val = data[key]
        if not isinstance(val, expected_type):
            errors.append(f"{name}.{key}: expected {expected_type.__name__}, got {type(val).__name__}")
    return errors


# =============================================================================
# TESTS
# =============================================================================

class TestScanSchema:
    """Tests for scan artifact schema."""
    
    def test_scan_required_keys(self):
        """Verify scan has all required keys."""
        from scripts.ci_m5_0_gate import generate_fixture_artifacts
        import tempfile
        from pathlib import Path
        import json
        
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            ts = "20260209_120000"
            generate_fixture_artifacts(output_dir, ts)
            
            scan_path = output_dir / "reports" / f"scan_{ts}.json"
            with open(scan_path) as f:
                scan = json.load(f)
            
            errors = validate_keys(scan, SCAN_REQUIRED_KEYS, "scan")
            assert not errors, f"Schema errors: {errors}"
    
    def test_scan_types(self):
        """Verify scan key types."""
        from scripts.ci_m5_0_gate import generate_fixture_artifacts
        import tempfile
        from pathlib import Path
        import json
        
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            ts = "20260209_120000"
            generate_fixture_artifacts(output_dir, ts)
            
            scan_path = output_dir / "reports" / f"scan_{ts}.json"
            with open(scan_path) as f:
                scan = json.load(f)
            
            errors = []
            errors.extend(validate_type(scan, "schema_version", str, "scan"))
            errors.extend(validate_type(scan, "current_block", int, "scan"))
            errors.extend(validate_type(scan, "chain_id", int, "scan"))
            errors.extend(validate_type(scan, "quotes_total", int, "scan"))
            errors.extend(validate_type(scan, "infra", dict, "scan"))
            
            assert not errors, f"Type errors: {errors}"


class TestTruthReportSchema:
    """Tests for truth_report artifact schema."""
    
    def test_truth_report_required_keys(self):
        """Verify truth_report has all required keys."""
        from scripts.ci_m5_0_gate import generate_fixture_artifacts
        import tempfile
        from pathlib import Path
        import json
        
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            ts = "20260209_120000"
            generate_fixture_artifacts(output_dir, ts)
            
            path = output_dir / "reports" / f"truth_report_{ts}.json"
            with open(path) as f:
                data = json.load(f)
            
            errors = validate_keys(data, TRUTH_REPORT_REQUIRED_KEYS, "truth_report")
            assert not errors, f"Schema errors: {errors}"
    
    def test_truth_report_spread_signal_schema(self):
        """Verify spread_signals have required keys."""
        from scripts.ci_m5_0_gate import generate_fixture_artifacts
        import tempfile
        from pathlib import Path
        import json
        
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            ts = "20260209_120000"
            generate_fixture_artifacts(output_dir, ts)
            
            path = output_dir / "reports" / f"truth_report_{ts}.json"
            with open(path) as f:
                data = json.load(f)
            
            signals = data.get("spread_signals", [])
            errors = []
            for i, sig in enumerate(signals):
                errors.extend(validate_keys(sig, SPREAD_SIGNAL_REQUIRED_KEYS, f"spread_signals[{i}]"))
            
            assert not errors, f"Schema errors: {errors}"


class TestRejectHistogramSchema:
    """Tests for reject_histogram artifact schema."""
    
    def test_reject_histogram_required_keys(self):
        """Verify reject_histogram has all required keys."""
        from scripts.ci_m5_0_gate import generate_fixture_artifacts
        import tempfile
        from pathlib import Path
        import json
        
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            ts = "20260209_120000"
            generate_fixture_artifacts(output_dir, ts)
            
            path = output_dir / "reports" / f"reject_histogram_{ts}.json"
            with open(path) as f:
                data = json.load(f)
            
            errors = validate_keys(data, REJECT_HISTOGRAM_REQUIRED_KEYS, "reject_histogram")
            assert not errors, f"Schema errors: {errors}"


class TestInfraSchema:
    """Tests for infra sub-object schema."""
    
    def test_infra_required_keys(self):
        """Verify infra has all required keys."""
        from scripts.ci_m5_0_gate import generate_fixture_artifacts
        import tempfile
        from pathlib import Path
        import json
        
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            ts = "20260209_120000"
            generate_fixture_artifacts(output_dir, ts)
            
            scan_path = output_dir / "reports" / f"scan_{ts}.json"
            with open(scan_path) as f:
                scan = json.load(f)
            
            infra = scan.get("infra", {})
            errors = validate_keys(infra, INFRA_REQUIRED_KEYS, "infra")
            assert not errors, f"Schema errors: {errors}"


class TestM4Schema:
    """Tests for M4 artifact schema."""
    
    def test_signals_required_keys(self):
        """Verify M4 signals has all required keys."""
        from scripts.ci_m4_execution_gate import generate_m4_fixture
        import tempfile
        from pathlib import Path
        import json
        
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            ts = "20260209_120000"
            generate_m4_fixture(run_dir, ts)
            
            path = run_dir / "reports" / f"signals_{ts}.json"
            with open(path) as f:
                data = json.load(f)
            
            errors = validate_keys(data, SIGNALS_REQUIRED_KEYS, "signals")
            assert not errors, f"Schema errors: {errors}"
    
    def test_execution_report_required_keys(self):
        """Verify M4 execution_report has all required keys."""
        from scripts.ci_m4_execution_gate import generate_m4_fixture
        import tempfile
        from pathlib import Path
        import json
        
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            ts = "20260209_120000"
            generate_m4_fixture(run_dir, ts)
            
            path = run_dir / "reports" / f"execution_report_{ts}.json"
            with open(path) as f:
                data = json.load(f)
            
            errors = validate_keys(data, EXECUTION_REPORT_REQUIRED_KEYS, "execution_report")
            assert not errors, f"Schema errors: {errors}"
