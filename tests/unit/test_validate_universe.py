"""
Unit tests for scripts/validate_universe.py run_kind gating.

Tests that:
- NORMAL/COVERAGE runs FAIL on viability issues (<2 DEX, 0 pairs)
- SMOKE runs get WARN only (non-blocking)

v3.2.12: Initial implementation
"""
import sys
from pathlib import Path

import pytest

# Add project root
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.validate_universe import validate_universe


class TestRunKindGating:
    """Tests for run_kind-aware viability gating."""
    
    @pytest.fixture
    def make_temp_config(self, tmp_path):
        """Create temporary config file."""
        import yaml
        
        def _make_config(config_dict):
            config_path = tmp_path / "test_config.yaml"
            with open(config_path, "w") as f:
                yaml.dump(config_dict, f)
            return config_path
        
        return _make_config
    
    def test_normal_run_fail_on_less_than_2_dex(self, make_temp_config):
        """NORMAL run with <2 DEX should FAIL."""
        config_path = make_temp_config({
            "run_kind": "NORMAL",
            "chain": "arbitrum_one",
            "dexes": ["uniswap_v3"],  # Only 1 DEX
            "require_cross_dex": True,
            "pairs": [{"token_in": "WETH", "token_out": "USDC"}],
        })
        
        result = validate_universe(config_path)
        
        assert any("VIABILITY_FAIL" in e for e in result["errors"]), \
            f"Expected VIABILITY_FAIL error for <2 DEX, got: {result['errors']}"
    
    def test_coverage_run_fail_on_less_than_2_dex(self, make_temp_config):
        """COVERAGE run with <2 DEX should FAIL (same as NORMAL)."""
        config_path = make_temp_config({
            "run_kind": "COVERAGE",
            "chain": "arbitrum_one",
            "dexes": ["uniswap_v3"],  # Only 1 DEX
            "require_cross_dex": True,
            "pairs": [{"token_in": "WETH", "token_out": "USDC"}],
        })
        
        result = validate_universe(config_path)
        
        assert any("VIABILITY_FAIL" in e for e in result["errors"]), \
            f"Expected VIABILITY_FAIL error for COVERAGE <2 DEX, got: {result['errors']}"
    
    def test_smoke_run_warn_on_less_than_2_dex(self, make_temp_config):
        """SMOKE run with <2 DEX should WARN, not FAIL."""
        config_path = make_temp_config({
            "run_kind": "SMOKE",
            "chain": "arbitrum_one",
            "dexes": ["uniswap_v3"],  # Only 1 DEX
            "require_cross_dex": True,
            "pairs": [{"token_in": "WETH", "token_out": "USDC"}],
        })
        
        result = validate_universe(config_path)
        
        # Should NOT have VIABILITY_FAIL error
        assert not any("VIABILITY_FAIL" in e for e in result["errors"]), \
            f"SMOKE should not FAIL on <2 DEX, got: {result['errors']}"
        # Should have warning instead
        assert any("<2 DEX" in w.lower() or "dexes" in w.lower() for w in result["warnings"]), \
            f"Expected warning about <2 DEX, got: {result['warnings']}"
    
    def test_normal_run_fail_on_zero_pairs(self, make_temp_config):
        """NORMAL run with 0 pairs should FAIL."""
        config_path = make_temp_config({
            "run_kind": "NORMAL",
            "chain": "arbitrum_one",
            "dexes": ["uniswap_v3", "sushiswap_v3"],
            "pairs": [],  # No pairs
        })
        
        result = validate_universe(config_path)
        
        assert any("no pairs" in e.lower() for e in result["errors"]), \
            f"Expected FAIL for 0 pairs, got: {result['errors']}"
    
    def test_coverage_run_fail_on_zero_pairs(self, make_temp_config):
        """COVERAGE run with 0 pairs should FAIL."""
        config_path = make_temp_config({
            "run_kind": "COVERAGE",
            "chain": "arbitrum_one",
            "dexes": ["uniswap_v3", "sushiswap_v3"],
            "pairs": [],  # No pairs
        })
        
        result = validate_universe(config_path)
        
        assert any("no pairs" in e.lower() for e in result["errors"]), \
            f"Expected FAIL for COVERAGE 0 pairs, got: {result['errors']}"
    
    def test_smoke_run_warn_on_zero_pairs(self, make_temp_config):
        """SMOKE run with 0 pairs should WARN, not FAIL."""
        config_path = make_temp_config({
            "run_kind": "SMOKE",
            "chain": "arbitrum_one",
            "dexes": ["uniswap_v3", "sushiswap_v3"],
            "pairs": [],  # No pairs
        })
        
        result = validate_universe(config_path)
        
        assert not any("no pairs" in e.lower() for e in result["errors"]), \
            f"SMOKE should not FAIL on 0 pairs, got: {result['errors']}"
        assert any("no pairs" in w.lower() for w in result["warnings"]), \
            f"Expected warning about 0 pairs, got: {result['warnings']}"
    
    def test_default_run_kind_is_normal(self, make_temp_config):
        """Missing run_kind should default to NORMAL (strict)."""
        config_path = make_temp_config({
            # No run_kind - should default to NORMAL
            "chain": "arbitrum_one",
            "dexes": ["uniswap_v3"],  # Only 1 DEX
            "require_cross_dex": True,
            "pairs": [{"token_in": "WETH", "token_out": "USDC"}],
        })
        
        result = validate_universe(config_path)
        
        # Default to NORMAL = strict = should FAIL
        assert any("VIABILITY_FAIL" in e for e in result["errors"]), \
            f"Default run_kind should be NORMAL (strict), got: {result['errors']}"
        assert result["summary"].get("run_kind") == "NORMAL"
    
    def test_valid_config_passes(self, make_temp_config):
        """Valid config with 2+ DEX and pairs should PASS."""
        config_path = make_temp_config({
            "run_kind": "NORMAL",
            "chain": "arbitrum_one",
            "dexes": ["uniswap_v3", "sushiswap_v3"],
            "pairs": [{"token_in": "WETH", "token_out": "USDC"}],
        })
        
        result = validate_universe(config_path)
        
        # Should not have VIABILITY_FAIL errors
        viability_fails = [e for e in result["errors"] if "VIABILITY_FAIL" in e]
        assert len(viability_fails) == 0, f"Valid config should pass, got: {viability_fails}"
