# PATH: tests/unit/test_adapter_readiness.py
"""
Adapter Readiness Tests — R27 (additive rollout contract).

Contract:
- Every DEX in config/dexes.yaml with a registered adapter_type must have
  a matching adapter class in dex/registry.py
- Every DEX declared as executable in onboard_* configs must have
  factory + quoter addresses in dexes.yaml
- DEXes with unimplemented adapter_type (ve33) are explicitly flagged
"""

import pytest
import yaml
from pathlib import Path


DEXES_YAML = Path(__file__).parent.parent.parent / "config" / "dexes.yaml"
CHAINS_YAML = Path(__file__).parent.parent.parent / "config" / "chains.yaml"

# Chains in dexes.yaml
ALL_CHAINS = ["arbitrum_one", "base", "linea", "mantle", "scroll", "zksync"]

# adapter_types that have a registered class in dex/registry.py
IMPLEMENTED_ADAPTERS = {"uniswap_v3", "algebra"}

# adapter_types that are known but NOT yet implemented
UNIMPLEMENTED_ADAPTERS = {"ve33"}

# DEXes that use ve33 (known gap) - these MUST fail readiness
VE33_DEXES = {
    ("base", "aerodrome"),
    ("mantle", "stratum"),
}


@pytest.fixture(scope="module")
def dexes_config():
    with open(DEXES_YAML) as f:
        return yaml.safe_load(f)


class TestAdapterReadinessPerChain:
    """Every chain's DEXes must have adapter_type → registered class."""

    @pytest.mark.parametrize("chain", ALL_CHAINS)
    def test_all_dexes_have_adapter_type(self, chain, dexes_config):
        """Every DEX entry must declare an adapter_type."""
        chain_dexes = dexes_config.get(chain, {})
        for dex_name, dex_data in chain_dexes.items():
            assert "adapter_type" in dex_data, (
                f"{chain}/{dex_name} missing adapter_type in dexes.yaml"
            )

    @pytest.mark.parametrize("chain", ALL_CHAINS)
    def test_implemented_dexes_have_adapter_class(self, chain, dexes_config):
        """DEXes with implemented adapter_type must have a registered class."""
        from dex.registry import get_adapter_class

        chain_dexes = dexes_config.get(chain, {})
        for dex_name, dex_data in chain_dexes.items():
            adapter_type = dex_data.get("adapter_type", "")
            if adapter_type in IMPLEMENTED_ADAPTERS:
                cls = get_adapter_class(adapter_type)
                assert cls is not None, (
                    f"{chain}/{dex_name}: adapter_type={adapter_type} "
                    f"not registered in dex/registry.py"
                )

    @pytest.mark.parametrize("chain", ALL_CHAINS)
    def test_implemented_dexes_have_quoter(self, chain, dexes_config):
        """DEXes with implemented adapters must have quoter_v2 or quoter address."""
        chain_dexes = dexes_config.get(chain, {})
        for dex_name, dex_data in chain_dexes.items():
            adapter_type = dex_data.get("adapter_type", "")
            if adapter_type in IMPLEMENTED_ADAPTERS:
                quoter = dex_data.get("quoter_v2") or dex_data.get("quoter")
                assert quoter and quoter.startswith("0x"), (
                    f"{chain}/{dex_name}: implemented adapter but no quoter address"
                )

    @pytest.mark.parametrize("chain", ALL_CHAINS)
    def test_all_dexes_have_factory(self, chain, dexes_config):
        """Every DEX must have a factory address."""
        chain_dexes = dexes_config.get(chain, {})
        for dex_name, dex_data in chain_dexes.items():
            factory = dex_data.get("factory", "")
            assert factory and factory.startswith("0x"), (
                f"{chain}/{dex_name} missing factory address in dexes.yaml"
            )


class TestVe33GapExplicit:
    """ve33 adapter is NOT implemented — these tests document the gap."""

    def test_ve33_not_registered(self):
        """ve33 adapter_type must NOT be in registry (not yet implemented)."""
        from dex.registry import get_adapter_class

        cls = get_adapter_class("ve33")
        assert cls is None, "ve33 adapter should not be registered yet"

    @pytest.mark.parametrize("chain,dex_name", sorted(VE33_DEXES))
    def test_ve33_dexes_in_config(self, chain, dex_name, dexes_config):
        """ve33 DEXes must exist in dexes.yaml with adapter_type=ve33."""
        chain_dexes = dexes_config.get(chain, {})
        assert dex_name in chain_dexes, (
            f"{chain}/{dex_name} not found in dexes.yaml"
        )
        assert chain_dexes[dex_name].get("adapter_type") == "ve33", (
            f"{chain}/{dex_name} should be adapter_type=ve33"
        )


class TestScrollNuriV3Contract:
    """Scroll nuri_v3 must be declared as uniswap_v3/quoter_v2 (R27 fix)."""

    def test_nuri_v3_adapter_type_is_uniswap_v3(self, dexes_config):
        """nuri_v3 on scroll must be adapter_type=uniswap_v3 (trust anchor)."""
        scroll_dexes = dexes_config.get("scroll", {})
        assert "nuri_v3" in scroll_dexes
        assert scroll_dexes["nuri_v3"]["adapter_type"] == "uniswap_v3"

    def test_nuri_v3_has_quoter_v2(self, dexes_config):
        """nuri_v3 on scroll must have quoter_v2 address."""
        scroll_dexes = dexes_config.get("scroll", {})
        quoter = scroll_dexes["nuri_v3"].get("quoter_v2", "")
        assert quoter.startswith("0x"), (
            "nuri_v3 must have quoter_v2 (not algebra quoter)"
        )

    def test_nuri_v3_has_fee_tiers(self, dexes_config):
        """nuri_v3 must have fee_tiers (uniswap_v3 style, not Algebra dynamic)."""
        scroll_dexes = dexes_config.get("scroll", {})
        fee_tiers = scroll_dexes["nuri_v3"].get("fee_tiers")
        assert fee_tiers is not None and len(fee_tiers) > 0, (
            "nuri_v3 must have fee_tiers (uniswap_v3 adapter)"
        )


class TestOnboardConfigsExist:
    """Onboard stage configs must exist for each chain in the rollout queue."""

    EXPECTED_CONFIGS = [
        "onboard_arbitrum_one_candidate.yaml",
        "onboard_zksync_candidate.yaml",
        "onboard_base_stage1.yaml",
        "onboard_mantle_stage1.yaml",
        "onboard_linea_stage1.yaml",
        "onboard_scroll_stage1.yaml",
    ]

    @pytest.mark.parametrize("config_name", EXPECTED_CONFIGS)
    def test_onboard_config_exists(self, config_name):
        """Each chain must have an onboard stage config."""
        config_path = Path(__file__).parent.parent.parent / "config" / config_name
        assert config_path.exists(), f"Missing onboard config: config/{config_name}"

    @pytest.mark.parametrize("config_name", EXPECTED_CONFIGS)
    def test_onboard_config_valid_yaml(self, config_name):
        """Onboard configs must be valid YAML."""
        config_path = Path(__file__).parent.parent.parent / "config" / config_name
        with open(config_path) as f:
            data = yaml.safe_load(f)
        assert isinstance(data, dict)
        assert "chain" in data
        assert "dexes" in data
        assert isinstance(data["dexes"], list)

    @pytest.mark.parametrize("config_name", EXPECTED_CONFIGS)
    def test_onboard_config_dexes_in_dexes_yaml(self, config_name, dexes_config):
        """All DEXes listed in onboard config must exist in dexes.yaml."""
        config_path = Path(__file__).parent.parent.parent / "config" / config_name
        with open(config_path) as f:
            data = yaml.safe_load(f)
        chain = data["chain"]
        chain_dexes = dexes_config.get(chain, {})
        for dex in data["dexes"]:
            assert dex in chain_dexes, (
                f"{config_name}: dex '{dex}' not found in dexes.yaml for chain '{chain}'"
            )
