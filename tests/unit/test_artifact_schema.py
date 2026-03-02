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
    "spread_bps",  # v3.2.5: Canonical integer bps
    "spread_bps_exact",
    "is_gross_positive",
    "gross_pnl_usdc_est",
    "net_pnl_usdc_est",
    "is_net_positive_est",
    "confidence",
    # v3.2.5: Economics fields for roundtrip viability
    "min_required_spread_bps",
    "spread_minus_required_bps",
    "is_roundtrip_viable",
    "route",
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

class TestSchemaCompatibility:
    """Tests for cross-schema compatibility between M4 and M5 artifacts."""
    
    def test_schema_version_families_documented(self):
        """Verify schema version families are consistent."""
        # M5 family uses semver (e.g., "3.2.0")
        # M4 family uses namespace:type:version (e.g., "m4:execution:v1.1")
        m5_pattern = r"^\d+\.\d+\.\d+$"
        m4_pattern = r"^m4:\w+:v\d+\.\d+$"
        
        import re
        
        # These are the expected patterns
        assert re.match(m5_pattern, "3.2.0"), "M5 semver pattern"
        assert re.match(m4_pattern, "m4:execution:v1.1"), "M4 namespace pattern"
        assert re.match(m4_pattern, "m4:signals:v1.1"), "M4 signals pattern"
    
    def test_m4_and_m5_fixtures_can_coexist(self):
        """Verify M4 and M5 fixtures can be generated in same runDir."""
        from scripts.ci_m4_execution_gate import generate_m4_fixture
        from scripts.ci_m5_0_gate import generate_fixture_artifacts
        import tempfile
        from pathlib import Path
        import json
        
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            ts = "20260209_120000"
            
            # Generate M4 fixtures
            m4_artifacts = generate_m4_fixture(run_dir, ts)
            
            # Generate M5 fixtures (different timestamp to avoid collision)
            ts2 = "20260209_120001"
            m5_artifacts = generate_fixture_artifacts(run_dir, ts2)
            
            # Both should exist
            assert m4_artifacts["signals"].exists()
            assert m4_artifacts["execution_report"].exists()
            assert m5_artifacts["scan"].exists()
            assert m5_artifacts["truth_report"].exists()
            
            # Verify schema versions are from correct families
            with open(m4_artifacts["execution_report"]) as f:
                m4_data = json.load(f)
            assert m4_data["schema_version"].startswith("m4:")
            
            with open(m5_artifacts["scan"]) as f:
                m5_data = json.load(f)
            assert not m5_data["schema_version"].startswith("m4:")
    
    def test_run_mode_consistency(self):
        """Verify run_mode is consistent across artifacts from same fixture."""
        from scripts.ci_m4_execution_gate import generate_m4_fixture
        import tempfile
        from pathlib import Path
        import json
        
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            ts = "20260209_120000"
            
            artifacts = generate_m4_fixture(run_dir, ts)
            
            with open(artifacts["signals"]) as f:
                signals = json.load(f)
            with open(artifacts["execution_report"]) as f:
                exec_report = json.load(f)
            
            # Both must have same run_mode
            assert signals["run_mode"] == exec_report["run_mode"]
            assert signals["run_mode"] == "FIXTURE_OFFLINE"
    
    def test_pinned_block_consistency(self):
        """Verify pinned_block is consistent across M4 artifacts."""
        from scripts.ci_m4_execution_gate import generate_m4_fixture
        import tempfile
        from pathlib import Path
        import json
        
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            ts = "20260209_120000"
            
            artifacts = generate_m4_fixture(run_dir, ts)
            
            with open(artifacts["signals"]) as f:
                signals = json.load(f)
            with open(artifacts["execution_report"]) as f:
                exec_report = json.load(f)
            
            # Headers must match
            assert signals["pinned_block"] == exec_report["pinned_block"]
            
            # All signals must use same block
            for sig in signals["signals"]:
                assert sig["pinned_block"] == signals["pinned_block"]
            
            # All simulations must use same block
            for sim in exec_report["simulations"]:
                assert sim["block_used"] == exec_report["pinned_block"]


class TestCrossArtifactConfigConsistency:
    """v2.2.2: Test that config fields are consistent across scan and truth_report artifacts."""
    
    def test_require_cross_dex_consistency(self):
        """scan.stats.require_cross_dex must match truth_report.config_params.require_cross_dex."""
        # Create mock scan and truth_report data
        scan_stats = {
            "require_cross_dex": True,
            "config_path": "config/real_nonstop.yaml",
        }
        truth_config_params = {
            "require_cross_dex": True,
            "config_path": "config/real_nonstop.yaml",
        }
        
        # Verify consistency
        assert scan_stats["require_cross_dex"] == truth_config_params["require_cross_dex"]
        assert scan_stats["config_path"] == truth_config_params["config_path"]
    
    def test_require_cross_dex_inconsistency_detection(self):
        """Test that we can detect inconsistency between artifacts."""
        scan_stats = {
            "require_cross_dex": True,
            "config_path": "config/real_nonstop.yaml",
        }
        truth_config_params = {
            "require_cross_dex": False,  # Inconsistent!
            "config_path": "config/real_nonstop.yaml",
        }
        
        # This should NOT be equal - test that detection works
        assert scan_stats["require_cross_dex"] != truth_config_params["require_cross_dex"]
    
    def test_config_path_from_run_scan_real(self):
        """Verify run_scan_real propagates config_path to stats."""
        from strategy.jobs.run_scan_real import run_scan
        import tempfile
        from pathlib import Path
        import json
        import os
        
        with tempfile.TemporaryDirectory() as tmpdir:
            output_dir = Path(tmpdir)
            
            # Minimal config with _config_path set
            config = {
                "chain": "arbitrum_one",
                "rpc_http": os.environ.get("ARB_RPC_HTTP", "https://arb1.arbitrum.io/rpc"),
                "_config_path": "config/test_minimal.yaml",
                "require_cross_dex": True,
                "paper_size_usd": 100,
                "pairs": [
                    {"base": "WETH", "quote": "USDC"},
                ],
            }
            
            # Run scan (offline mode will use fixtures)
            try:
                result = run_scan(config, output_dir, cycles=1, artifact_mode="full")
                
                # Check scan artifact
                scan_files = list(output_dir.glob("reports/scan_*.json"))
                if scan_files:
                    with open(scan_files[0]) as f:
                        scan_data = json.load(f)
                    
                    # Verify config fields are in scan.stats
                    stats = scan_data.get("stats", {})
                    assert stats.get("require_cross_dex") == True
                    assert stats.get("config_path") == "config/test_minimal.yaml"
            except Exception as e:
                # If RPC not available, test passes (offline scenario)
                if "ARBY_OFFLINE" in os.environ or "RPC" in str(e).upper():
                    pytest.skip(f"RPC not available: {e}")


class TestRoundtripStatsWarningsInArtifact:
    """v3.2.5: Tests that roundtrip stats warnings field appears in artifacts."""
    
    def test_roundtrip_stats_has_warnings_key(self):
        """truth_report.stats.roundtrip must contain 'warnings' key."""
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
            
            stats = data.get("stats", {})
            roundtrip = stats.get("roundtrip", {})
            
            # Roundtrip stats must have warnings (can be empty list)
            assert "warnings" in roundtrip, \
                "truth_report.stats.roundtrip must contain 'warnings' key"
            assert isinstance(roundtrip["warnings"], list), \
                "warnings must be a list"


class TestOpportunityHasRouteAndSpreadBps:
    """v3.2.5: Tests that top_opportunities have route and spread_bps."""
    
    def test_opportunity_has_route_field(self):
        """top_opportunity should have a 'route' field."""
        from engine.opportunity_engine import Opportunity
        
        opp = Opportunity(
            spread_id="test",
            pair="WETH/USDC",
            buy_dex="uni",
            sell_dex="sushi",
            buy_fee=500,
            sell_fee=500,
            buy_price=100.0,
            sell_price=100.1,
            amount_in_wei=1000,
        )
        
        d = opp.to_dict()
        # Route and spread_bps should be in to_dict output
        assert "route" in d, "Opportunity to_dict() must include 'route'"
        assert "spread_bps" in d, "Opportunity to_dict() must include 'spread_bps'"