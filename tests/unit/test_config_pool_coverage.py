# PATH: tests/unit/test_config_pool_coverage.py
"""
Unit tests for config pool coverage validation (v2.9.6).

Contract:
- Every pool_key generated from (dex, pair, fee_tier) must either:
  1. Have an address in pools: section, OR
  2. Be listed in disabled_pools: section
- This prevents POOL_MISSING surprises at runtime
"""

import os
import pytest
import yaml


class TestConfigPoolCoverage:
    """Validate that config has complete pool coverage."""
    
    @pytest.fixture
    def real_minimal_config(self):
        """Load real_minimal.yaml for testing."""
        config_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "config", "real_minimal.yaml"
        )
        with open(config_path, "r") as f:
            return yaml.safe_load(f)
    
    def test_all_pool_keys_covered(self, real_minimal_config):
        """Every pool_key from pairs×dexes×fee_tiers must be in pools or disabled_pools."""
        config = real_minimal_config
        dexes = config.get("dexes", [])
        pairs = config.get("pairs", [])
        pools = config.get("pools", {})
        disabled_pools = config.get("disabled_pools", {})
        
        missing_keys = []
        
        for pair_cfg in pairs:
            token_in = pair_cfg.get("token_in")
            token_out = pair_cfg.get("token_out")
            fee_tiers = pair_cfg.get("fee_tiers", [500, 3000])
            pair_tag = f"{token_in}_{token_out}"
            
            for dex in dexes:
                for fee_tier in fee_tiers:
                    pool_key = f"{dex}_{pair_tag}_{fee_tier}"
                    
                    in_pools = pool_key in pools
                    in_disabled = pool_key in disabled_pools
                    
                    if not in_pools and not in_disabled:
                        missing_keys.append(pool_key)
        
        if missing_keys:
            # Sort for readability
            missing_keys.sort()
            msg = (
                f"Found {len(missing_keys)} pool_keys not covered by pools or disabled_pools:\n"
                + "\n".join(f"  - {k}" for k in missing_keys[:20])
            )
            if len(missing_keys) > 20:
                msg += f"\n  ... and {len(missing_keys) - 20} more"
            pytest.fail(msg)
    
    def test_disabled_pools_keys_match_expected_format(self, real_minimal_config):
        """Disabled pool keys should follow dex_TOKENIN_TOKENOUT_FEE format."""
        disabled_pools = real_minimal_config.get("disabled_pools", {})
        
        import re
        pattern = r'^[a-z_]+_v[0-9]_[A-Z]+_[A-Z]+_\d+$'
        
        for key in disabled_pools.keys():
            assert re.match(pattern, key), f"Invalid disabled_pools key format: {key}"
    
    def test_pool_missing_count_zero_contract(self, real_minimal_config):
        """Contract: with complete coverage, pool_missing_count should be 0 at runtime."""
        # This is a static validation - runtime check happens in ONLINE scans
        # Here we verify the contract by checking coverage
        config = real_minimal_config
        dexes = config.get("dexes", [])
        pairs = config.get("pairs", [])
        pools = config.get("pools", {})
        disabled_pools = config.get("disabled_pools", {})
        
        total_expected = 0
        covered = 0
        
        for pair_cfg in pairs:
            token_in = pair_cfg.get("token_in")
            token_out = pair_cfg.get("token_out")
            fee_tiers = pair_cfg.get("fee_tiers", [500, 3000])
            pair_tag = f"{token_in}_{token_out}"
            
            for dex in dexes:
                for fee_tier in fee_tiers:
                    total_expected += 1
                    pool_key = f"{dex}_{pair_tag}_{fee_tier}"
                    if pool_key in pools or pool_key in disabled_pools:
                        covered += 1
        
        coverage_rate = covered / total_expected if total_expected > 0 else 0
        assert coverage_rate == 1.0, (
            f"Pool coverage is {coverage_rate:.1%}, expected 100%."
            f" {total_expected - covered} keys missing."
        )
