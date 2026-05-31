# PATH: tests/unit/test_config_contracts.py
"""
Config contract tests for coverage configs and DEX configurations.

v3.2.37: Validates that coverage configs have required fields and reference
valid DEXes from dexes.yaml with proper factory/quoter addresses.
This ensures the config/code contract is not broken by ad-hoc changes.
"""

import pytest
import yaml
from pathlib import Path
from datetime import datetime, timezone
import re


# =============================================================================
# PATHS
# =============================================================================

PROJECT_ROOT = Path(__file__).parent.parent.parent
CONFIG_DIR = PROJECT_ROOT / "config"
DEXES_YAML = CONFIG_DIR / "dexes.yaml"

# Onboard/staged rollout config files that must be validated
COVERAGE_CONFIGS = [
    "onboard_base_stage1.yaml",
    "onboard_scroll_stage1.yaml",
    "onboard_linea_stage1.yaml",
    "onboard_mantle_stage1.yaml",
    "onboard_zksync_candidate.yaml",
    "onboard_arbitrum_one_candidate.yaml",
]

# Required fields for coverage configs
COVERAGE_REQUIRED_FIELDS = {
    "chain",
    "chain_id",
    "rpc_endpoints",
    "universe_source",
    "dexes",
    "min_spread_bps",
}

# Required DEX fields for UniswapV3-style adapters
DEX_REQUIRED_FIELDS_V3 = {
    "adapter_type",
    "factory",
}

# DEX types that require quoter
DEX_TYPES_REQUIRING_QUOTER = {"uniswap_v3", "algebra"}


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def dexes_config():
    """Load dexes.yaml configuration."""
    with open(DEXES_YAML) as f:
        return yaml.safe_load(f)


# =============================================================================
# COVERAGE CONFIG TESTS
# =============================================================================

class TestCoverageConfigContracts:
    """Contract tests for coverage config files."""
    
    @pytest.mark.parametrize("config_name", COVERAGE_CONFIGS)
    def test_coverage_config_has_required_fields(self, config_name):
        """All coverage configs must have required fields."""
        config_path = CONFIG_DIR / config_name
        if not config_path.exists():
            pytest.skip(f"{config_name} does not exist")
        
        with open(config_path) as f:
            config = yaml.safe_load(f)
        
        missing = COVERAGE_REQUIRED_FIELDS - set(config.keys())
        assert not missing, f"{config_name} missing required fields: {missing}"
    
    @pytest.mark.parametrize("config_name", COVERAGE_CONFIGS)
    def test_coverage_config_dexes_exist_in_dexes_yaml(self, config_name, dexes_config):
        """All DEXes referenced in coverage configs must exist in dexes.yaml."""
        config_path = CONFIG_DIR / config_name
        if not config_path.exists():
            pytest.skip(f"{config_name} does not exist")
        
        with open(config_path) as f:
            config = yaml.safe_load(f)
        
        chain = config.get("chain")
        dexes_list = config.get("dexes", [])
        
        if chain not in dexes_config:
            pytest.skip(f"Chain '{chain}' not in dexes.yaml")
        
        chain_dexes = dexes_config[chain]
        for dex in dexes_list:
            assert dex in chain_dexes, \
                f"{config_name}: DEX '{dex}' not found in dexes.yaml for chain '{chain}'"
    
    @pytest.mark.parametrize("config_name", COVERAGE_CONFIGS)
    def test_coverage_config_has_at_least_two_dexes_for_cross_dex(self, config_name):
        """Coverage configs with require_cross_dex=true must have >=2 DEXes."""
        config_path = CONFIG_DIR / config_name
        if not config_path.exists():
            pytest.skip(f"{config_name} does not exist")
        
        with open(config_path) as f:
            config = yaml.safe_load(f)
        
        require_cross_dex = config.get("require_cross_dex", True)
        dexes_list = config.get("dexes", [])
        
        if require_cross_dex:
            assert len(dexes_list) >= 2, \
                f"{config_name}: require_cross_dex=true but only {len(dexes_list)} DEX(es) configured"


# =============================================================================
# DEX CONFIG TESTS
# =============================================================================

class TestDexConfigContracts:
    """Contract tests for dexes.yaml configuration."""
    
    def test_dexes_yaml_exists(self):
        """dexes.yaml must exist."""
        assert DEXES_YAML.exists(), f"dexes.yaml not found at {DEXES_YAML}"
    
    def test_all_dexes_have_factory(self, dexes_config):
        """All DEXes must have a factory address."""
        for chain, dexes in dexes_config.items():
            if not isinstance(dexes, dict):
                continue
            for dex_name, dex_config in dexes.items():
                if not isinstance(dex_config, dict):
                    continue
                assert "factory" in dex_config, \
                    f"DEX '{chain}.{dex_name}' missing 'factory' address"
    
    def test_v3_dexes_have_quoter(self, dexes_config):
        """UniswapV3/Algebra DEXes must have quoter or quoter_v2."""
        for chain, dexes in dexes_config.items():
            if not isinstance(dexes, dict):
                continue
            for dex_name, dex_config in dexes.items():
                if not isinstance(dex_config, dict):
                    continue
                adapter_type = dex_config.get("adapter_type", "")
                if adapter_type in DEX_TYPES_REQUIRING_QUOTER:
                    has_quoter = "quoter" in dex_config or "quoter_v2" in dex_config
                    assert has_quoter, \
                        f"DEX '{chain}.{dex_name}' (adapter_type={adapter_type}) missing quoter/quoter_v2"
    
    def test_factory_addresses_are_valid_hex(self, dexes_config):
        """Factory addresses must be valid 0x-prefixed hex strings."""
        hex_pattern = re.compile(r"^0x[a-fA-F0-9]{40}$")
        
        for chain, dexes in dexes_config.items():
            if not isinstance(dexes, dict):
                continue
            for dex_name, dex_config in dexes.items():
                if not isinstance(dex_config, dict):
                    continue
                factory = dex_config.get("factory", "")
                if factory:  # Only validate if present
                    assert hex_pattern.match(factory), \
                        f"DEX '{chain}.{dex_name}' has invalid factory address: {factory}"


# =============================================================================
# ISO-8601 TIMESTAMP TESTS
# =============================================================================

class TestTimestampContracts:
    """Contract tests for ISO-8601 timestamp formatting."""
    
    def test_utc_isoformat_with_z_suffix_is_valid(self):
        """UTC timestamps with Z suffix must be valid ISO-8601."""
        # Correct format: 2026-03-08T09:06:52.611725Z
        ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        
        # Must not have both +00:00 and Z
        assert "+00:00Z" not in ts, f"Malformed timestamp: {ts}"
        
        # Must end with Z
        assert ts.endswith("Z"), f"UTC timestamp must end with Z: {ts}"
        
        # Must be parseable (strip Z for fromisoformat)
        parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        assert parsed.tzinfo is not None, f"Timestamp must have timezone info"
    
    def test_malformed_timestamp_detection(self):
        """Detect malformed +00:00Z timestamps."""
        # WRONG: isoformat() already has +00:00, appending Z creates malformed string
        malformed = datetime.now(timezone.utc).isoformat() + "Z"
        assert "+00:00Z" in malformed, "Test setup: expected malformed timestamp"
        
        # CORRECT: replace +00:00 with Z
        correct = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        assert "+00:00Z" not in correct, f"Correct timestamp should not have +00:00Z"


# =============================================================================
# CROSS-CHAIN COVERAGE TESTS
# =============================================================================

class TestMultiChainCoverageReadiness:
    """Tests for multi-chain coverage readiness."""
    
    def test_all_coverage_chains_have_dex_config(self, dexes_config):
        """All chains with coverage configs must have DEX configurations."""
        for config_name in COVERAGE_CONFIGS:
            config_path = CONFIG_DIR / config_name
            if not config_path.exists():
                continue
            
            with open(config_path) as f:
                config = yaml.safe_load(f)
            
            chain = config.get("chain")
            assert chain in dexes_config, \
                f"Coverage config {config_name} references chain '{chain}' not in dexes.yaml"
    
    def test_base_has_minimum_three_dexes(self, dexes_config):
        """Base chain must have at least 3 DEXes for good cross-DEX coverage."""
        base_dexes = dexes_config.get("base", {})
        assert len(base_dexes) >= 3, \
            f"Base should have >=3 DEXes for good coverage, has {len(base_dexes)}"
    
    def test_scroll_has_minimum_two_dexes(self, dexes_config):
        """Scroll chain must have at least 2 DEXes (no longer blocked)."""
        scroll_dexes = dexes_config.get("scroll", {})
        assert len(scroll_dexes) >= 2, \
            f"Scroll should have >=2 DEXes (no longer BLOCKED_BY_SECOND_DEX), has {len(scroll_dexes)}"


# =============================================================================
# DISABLED POOLS CONTRACT TESTS
# =============================================================================

class TestDisabledPoolsContracts:
    """Contract tests for disabled_pools configuration."""
    
    # Required fields in disabled_pools entries
    DISABLED_POOL_REQUIRED_FIELDS = {"address", "reason", "disabled_date"}
    
    @pytest.mark.parametrize("config_name", COVERAGE_CONFIGS)
    def test_disabled_pools_have_required_fields(self, config_name):
        """All disabled_pools entries must have required fields."""
        config_path = CONFIG_DIR / config_name
        if not config_path.exists():
            pytest.skip(f"{config_name} does not exist")
        
        with open(config_path) as f:
            config = yaml.safe_load(f)
        
        disabled_pools = config.get("disabled_pools", {})
        for pool_key, pool_info in disabled_pools.items():
            if not isinstance(pool_info, dict):
                continue
            missing = self.DISABLED_POOL_REQUIRED_FIELDS - set(pool_info.keys())
            assert not missing, \
                f"{config_name}: disabled_pool '{pool_key}' missing fields: {missing}"
    
    @pytest.mark.parametrize("config_name", COVERAGE_CONFIGS)
    def test_disabled_pools_addresses_are_valid_hex(self, config_name):
        """Disabled pool addresses must be valid 0x-prefixed hex strings."""
        config_path = CONFIG_DIR / config_name
        if not config_path.exists():
            pytest.skip(f"{config_name} does not exist")
        
        hex_pattern = re.compile(r"^0x[a-fA-F0-9]{40}$")
        
        with open(config_path) as f:
            config = yaml.safe_load(f)
        
        disabled_pools = config.get("disabled_pools", {})
        for pool_key, pool_info in disabled_pools.items():
            if not isinstance(pool_info, dict):
                continue
            address = pool_info.get("address", "")
            assert hex_pattern.match(address), \
                f"{config_name}: disabled_pool '{pool_key}' has invalid address: {address}"
    
    @pytest.mark.parametrize("config_name", COVERAGE_CONFIGS)
    def test_disabled_pools_keys_match_format(self, config_name):
        """Disabled pool keys must follow {dex}_{token0}_{token1}_{fee} format."""
        config_path = CONFIG_DIR / config_name
        if not config_path.exists():
            pytest.skip(f"{config_name} does not exist")
        
        # Pattern: dex_TOKEN0_TOKEN1_fee (e.g., sushiswap_v3_WETH_USDC_500)
        key_pattern = re.compile(r"^[a-z_0-9]+_[A-Z0-9]+_[A-Z0-9]+_\d+$")
        
        with open(config_path) as f:
            config = yaml.safe_load(f)
        
        disabled_pools = config.get("disabled_pools", {})
        for pool_key in disabled_pools.keys():
            assert key_pattern.match(pool_key), \
                f"{config_name}: disabled_pool key '{pool_key}' does not match expected format"
    
    def test_scroll_has_price_scale_quarantine(self):
        """Scroll config must have PRICE_SCALE violating pools quarantined."""
        config_path = CONFIG_DIR / "onboard_scroll_stage1.yaml"
        if not config_path.exists():
            pytest.skip("onboard_scroll_stage1.yaml does not exist")
        
        with open(config_path) as f:
            config = yaml.safe_load(f)
        
        disabled_pools = config.get("disabled_pools", {})
        if not disabled_pools:
            pytest.skip("onboard_scroll_stage1.yaml has no disabled_pools (discovery_runtime mode)")
        
        # Known PRICE_SCALE violating pools that must be quarantined
        required_quarantines = [
            "sushiswap_v3_WETH_USDC_10000",  # price=50.3, low liquidity
            "sushiswap_v3_WETH_USDT_500",    # price=7.65, low liquidity
        ]
        
        for pool_key in required_quarantines:
            assert pool_key in disabled_pools, \
                f"Scroll config missing quarantined pool: {pool_key}"
            assert disabled_pools[pool_key].get("reason") == "PRICE_SCALE_VIOLATION", \
                f"Pool {pool_key} should have reason PRICE_SCALE_VIOLATION"


# =============================================================================
# CONFIG INVENTORY GUARD (R27.4)
# =============================================================================

# Frozen active inventory: registry + primary/probes + staged rollout
ALLOWED_YAML_FILES = {
    # Registry / service configs
    "cex.yaml",
    "chains.yaml",
    "core_tokens.yaml",
    "dexes.yaml",
    "fees.yaml",
    "strategy.yaml",
    # Primary + probes
    "real_minimal.yaml",
    "real_intent_arbitrum_one.yaml",
    "real_roundtrip_probe.yaml",
    "real_roundtrip_probe_lowfee.yaml",
    "real_live_probe.yaml",
    # Staged rollout (onboard_ family)
    "onboard_arbitrum_one_candidate.yaml",
    "onboard_base_stage1.yaml",
    "onboard_base_stage2.yaml",
    "onboard_base_profit.yaml",
    "onboard_base_discovery.yaml",
    "onboard_linea_stage1.yaml",
    "onboard_mantle_stage1.yaml",
    "onboard_mantle_stage2.yaml",
    "onboard_scroll_stage1.yaml",
    "onboard_zksync_candidate.yaml",
    # M8 Phase 1 — new-pool sniping factory listener config
    "new_pool_factories.yaml",
    # M8 Phase 2 — entry-candidate enricher config (anchor prices, probe size, etc.)
    "enricher.yaml",
    # M9 Graph-Arb — exotic pairs config for Base chain (builder.py default)
    "exotic_base_anchor.yaml",
    # M9 Graph-Arb — exotic pairs config for Arbitrum One chain
    "exotic_arbitrum_anchor.yaml",
    # M9 soak profiles (Step 7 GPT fix)
    "soak_30m_base.yaml",
    "soak_60m_base.yaml",
    # M9 adapter runtime wiring — per-pool Curve/Balancer metadata registry
    "adapter_metadata.yaml",
}


class TestConfigInventoryGuard:
    """R27.4: Guard against config sprawl — only allowed YAML files in config/."""

    def test_no_unexpected_yaml_files(self):
        """config/*.yaml must only contain files from the frozen active inventory."""
        actual = {p.name for p in CONFIG_DIR.glob("*.yaml")}
        unexpected = actual - ALLOWED_YAML_FILES
        assert not unexpected, (
            f"Unexpected YAML files in config/: {sorted(unexpected)}. "
            "If intentional, add to ALLOWED_YAML_FILES in test_config_contracts.py."
        )

    def test_all_allowed_configs_exist(self):
        """Every file in the allowed inventory must actually exist."""
        missing = {f for f in ALLOWED_YAML_FILES if not (CONFIG_DIR / f).exists()}
        assert not missing, (
            f"Allowed configs missing from config/: {sorted(missing)}"
        )
