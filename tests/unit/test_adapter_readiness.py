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
IMPLEMENTED_ADAPTERS = {"uniswap_v3", "algebra", "ve33", "uniswap_v2", "iziswap", "syncswap", "ambient"}

# adapter_types that are known but NOT yet implemented (registered as stubs)
# R30: iziswap, syncswap, ambient are registered stubs — raise QuoteError on all calls
UNIMPLEMENTED_ADAPTERS = set()

# DEXes that use ve33 (now implemented — R27.4)
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
        """DEXes with implemented adapters must have quoter_v2/quoter (or router for ve33)."""
        chain_dexes = dexes_config.get(chain, {})
        for dex_name, dex_data in chain_dexes.items():
            adapter_type = dex_data.get("adapter_type", "")
            if adapter_type in IMPLEMENTED_ADAPTERS:
                if adapter_type in ("ve33", "uniswap_v2", "syncswap"):
                    # ve33/V2/syncswap quote on-pool, router is optional
                    continue
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


class TestVe33AdapterRegistered:
    """R27.4: ve33 adapter is now implemented and registered."""

    def test_ve33_registered(self):
        """ve33 adapter_type must be in registry."""
        from dex.registry import get_adapter_class

        cls = get_adapter_class("ve33")
        assert cls is not None, "ve33 adapter should be registered after R27.4"

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


class TestNarrativeConsistency:
    """Docs and configs must not contradict each other (R27 lead issue #6/#7/#10)."""

    MATRIX_PATH = Path(__file__).parent.parent.parent / "docs" / "ONBOARDING_MATRIX.md"
    SCROLL_STAGE1_PATH = Path(__file__).parent.parent.parent / "config" / "onboard_scroll_stage1.yaml"
    ARB_CANDIDATE_PATH = Path(__file__).parent.parent.parent / "config" / "onboard_arbitrum_one_candidate.yaml"

    def test_scroll_nuri_v3_enabled_in_stage_config(self):
        """nuri_v3 must be in onboard_scroll_stage1.yaml dexes."""
        with open(self.SCROLL_STAGE1_PATH) as f:
            data = yaml.safe_load(f)
        assert "nuri_v3" in data.get("dexes", []), (
            "nuri_v3 must be in onboard_scroll_stage1.yaml dexes list"
        )

    def test_scroll_blocker_text_no_algebra_incompatible(self):
        """onboard_scroll_stage1.yaml blocker_reason must not claim algebra-incompatible."""
        with open(self.SCROLL_STAGE1_PATH) as f:
            content = f.read()
        data = yaml.safe_load(content)
        reason = data.get("blocker_reason", "")
        assert "algebra-incompatible" not in reason, (
            f"blocker_reason still claims algebra-incompatible: {reason}"
        )

    def test_matrix_scroll_nuri_not_excluded(self):
        """ONBOARDING_MATRIX.md must not say nuri_v3 is EXCLUDED if config enables it."""
        text = self.MATRIX_PATH.read_text(encoding="utf-8")
        # Find the nuri_v3 row
        for line in text.splitlines():
            if "nuri_v3" in line and "scroll" in line.lower():
                assert "EXCLUDED" not in line, (
                    f"Matrix says nuri_v3 EXCLUDED but coverage config enables it: {line}"
                )
                assert "algebra-incompatible" not in line, (
                    f"Matrix still claims algebra-incompatible: {line}"
                )
                break
        else:
            pytest.fail("nuri_v3 row not found in ONBOARDING_MATRIX.md")

    def test_matrix_camelot_not_excluded_if_in_candidate(self):
        """If camelot_v3 is in onboard_arbitrum_one_candidate.yaml, matrix cannot say EXCLUDED."""
        with open(self.ARB_CANDIDATE_PATH) as f:
            candidate = yaml.safe_load(f)
        if "camelot_v3" not in candidate.get("dexes", []):
            pytest.skip("camelot_v3 not in arb candidate config")

        text = self.MATRIX_PATH.read_text(encoding="utf-8")
        for line in text.splitlines():
            if "camelot_v3" in line and "arbitrum" in line.lower():
                assert "EXCLUDED" not in line, (
                    f"Matrix says camelot_v3 EXCLUDED but candidate config includes it: {line}"
                )
                break
        else:
            pytest.fail("camelot_v3 row not found in ONBOARDING_MATRIX.md")

    def test_stage_config_dexes_match_matrix_entries(self):
        """DEXes in stage configs must exist in ONBOARDING_MATRIX.md table."""
        text = self.MATRIX_PATH.read_text(encoding="utf-8")
        configs = [
            self.SCROLL_STAGE1_PATH,
            self.ARB_CANDIDATE_PATH,
        ]
        for cfg_path in configs:
            with open(cfg_path) as f:
                data = yaml.safe_load(f)
            chain = data["chain"]
            for dex in data["dexes"]:
                found = any(
                    dex in line and chain in line.lower()
                    for line in text.splitlines()
                    if "|" in line
                )
                assert found, (
                    f"DEX '{dex}' (chain={chain}) from {cfg_path.name} "
                    f"not found in ONBOARDING_MATRIX.md table"
                )


class TestM8ToM9BridgeCoverage:
    """Contract: M8→M9 bridge must not silently drop DEXes with factory events.

    Step 9 (GPT): every dex_id that has M8 factory events must either
    be fully adapter-supported OR have an explicit quarantine_reason
    in _PENDING_ADAPTER_REASONS.  No silent 'unsupported' adapter fallback.
    """

    # DEX IDs known to produce live factory events on Base (confirmed via probe)
    KNOWN_ACTIVE_DEX_IDS = {
        "uniswap_v4",        # 1758 events per 5000 blocks (factory probe)
        "uniswap_v2",        # 113 events per 5000 blocks
        "uniswap_v3",        # 48 events per 5000 blocks
        "aerodrome",         # 3 events per 5000 blocks
        "aerodrome_slipstream",  # 1 event per 5000 blocks
    }

    def test_all_active_dex_ids_in_bridge_map(self):
        """Every DEX that produces live M8 events must appear in _DEX_ID_TO_ADAPTER_TYPE."""
        from m9.graph_arb.bridge_builder import _DEX_ID_TO_ADAPTER_TYPE
        for dex_id in self.KNOWN_ACTIVE_DEX_IDS:
            assert dex_id in _DEX_ID_TO_ADAPTER_TYPE, (
                f"dex_id={dex_id!r} produces live M8 events but is missing from "
                f"bridge_builder._DEX_ID_TO_ADAPTER_TYPE — add mapping to avoid silent graph loss"
            )

    def test_no_generic_unsupported_for_known_active_dexes(self):
        """No dex_id that produces events should silently map to 'unsupported' adapter."""
        from m9.graph_arb.bridge_builder import _DEX_ID_TO_ADAPTER_TYPE, _UNSUPPORTED_ADAPTER
        for dex_id in self.KNOWN_ACTIVE_DEX_IDS:
            at = _DEX_ID_TO_ADAPTER_TYPE.get(dex_id)
            assert at != _UNSUPPORTED_ADAPTER, (
                f"dex_id={dex_id!r} maps to 'unsupported' adapter — "
                f"use the real adapter_type string and add to _PENDING_ADAPTER_TYPES "
                f"if quote adapter is not ready"
            )

    def test_v4_maps_to_uniswap_v4_not_unsupported(self):
        """uniswap_v4 must map to 'uniswap_v4' adapter_type (not 'unsupported')."""
        from m9.graph_arb.bridge_builder import _DEX_ID_TO_ADAPTER_TYPE
        assert _DEX_ID_TO_ADAPTER_TYPE.get("uniswap_v4") == "uniswap_v4", (
            "uniswap_v4 must map to 'uniswap_v4' adapter_type, "
            "not 'unsupported' — use _PENDING_ADAPTER_TYPES for quarantine"
        )

    def test_v4_in_pending_adapter_types(self):
        """uniswap_v4 must NOT be in _PENDING_ADAPTER_TYPES once M9 quote adapter is active."""
        from m9.graph_arb.bridge_builder import _PENDING_ADAPTER_TYPES
        assert "uniswap_v4" not in _PENDING_ADAPTER_TYPES, (
            "uniswap_v4 has an active M9 quote adapter (aa9d21cb selector, V4 Quoter). "
            "Remove it from _PENDING_ADAPTER_TYPES so V4 pools enter active_routes."
        )

    def test_pending_adapters_have_quarantine_reason(self):
        """Every entry in _PENDING_ADAPTER_TYPES must have a documented quarantine reason."""
        from m9.graph_arb.bridge_builder import _PENDING_ADAPTER_TYPES, _PENDING_ADAPTER_REASONS
        for adapter_type in _PENDING_ADAPTER_TYPES:
            assert adapter_type in _PENDING_ADAPTER_REASONS, (
                f"adapter_type={adapter_type!r} is in _PENDING_ADAPTER_TYPES but has no "
                f"entry in _PENDING_ADAPTER_REASONS — add a quarantine reason string"
            )
            reason = _PENDING_ADAPTER_REASONS[adapter_type]
            assert "PENDING" in reason.upper(), (
                f"_PENDING_ADAPTER_REASONS[{adapter_type!r}]={reason!r} must contain 'PENDING'"
            )


class TestPoolVerifierCoverage:
    """Contract: pool_verifier must support factory queries for all active Base DEXes.

    Step 4-6 (GPT): V2, ve33, and V4 (explicit quarantine) must be handled.
    """

    def test_uniswap_v2_selector_defined(self):
        """_GETPAIR_V2_SEL must be the correct 4-byte selector for getPair(address,address)."""
        from m9.graph_arb.pool_verifier import _GETPAIR_V2_SEL
        # keccak256("getPair(address,address)")[:4] = 0xe6a43905 (well-known)
        assert _GETPAIR_V2_SEL == "e6a43905", (
            f"V2 getPair selector mismatch: got {_GETPAIR_V2_SEL!r}, expected 'e6a43905'"
        )

    def test_ve33_selector_computable(self):
        """_get_ve33_selector() must return a non-empty 8-hex-char selector."""
        from m9.graph_arb.pool_verifier import _get_ve33_selector
        sel = _get_ve33_selector()
        assert sel and len(sel) == 8, (
            f"ve33 getPool(address,address,bool) selector invalid: {sel!r}"
        )

    def test_v4_in_pending_quote_adapters(self):
        """uniswap_v4 must NOT be in pool_verifier._PENDING_QUOTE_ADAPTERS once adapter is active."""
        from m9.graph_arb.pool_verifier import _PENDING_QUOTE_ADAPTERS
        assert "uniswap_v4" not in _PENDING_QUOTE_ADAPTERS, (
            "uniswap_v4 has an active M9 quote adapter (selector aa9d21cb, V4 Quoter). "
            "Remove it from pool_verifier._PENDING_QUOTE_ADAPTERS — "
            "V4 pools are discovered via M8 sniper, not static factory enumeration."
        )

    def test_build_getpair_v2_calldata_no_fee_param(self):
        """V2 getPair calldata must be exactly 4 + 32 + 32 = 68 bytes (no fee slot)."""
        from m9.graph_arb.pool_verifier import _build_getpair_v2_calldata
        addr_a = "0xaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaA"
        addr_b = "0xbBbBbBbBbBbBbBbBbBbBbBbBbBbBbBbBbBbBbBb"
        cd = _build_getpair_v2_calldata(addr_a, addr_b)
        assert cd.startswith("0x"), "calldata must start with 0x"
        # 0x + selector(4B=8chars) + addr_a(32B=64chars) + addr_b(32B=64chars) = 0x + 136 chars
        assert len(cd) == 2 + 8 + 64 + 64, (
            f"V2 getPair calldata length wrong: expected {2+8+64+64}, got {len(cd)}"
        )

    def test_build_getpool_ve33_calldata_volatile_vs_stable(self):
        """ve33 calldata must include the bool stable slot (total 4+32+32+32 bytes)."""
        from m9.graph_arb.pool_verifier import _build_getpool_ve33_calldata
        addr_a = "0xaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaAaA"
        addr_b = "0xbBbBbBbBbBbBbBbBbBbBbBbBbBbBbBbBbBbBbBb"
        # volatile (stable=False) vs stable (stable=True) must differ
        cd_volatile = _build_getpool_ve33_calldata(addr_a, addr_b, stable=False)
        cd_stable = _build_getpool_ve33_calldata(addr_a, addr_b, stable=True)
        # Length: 0x + selector(8) + addr_a(64) + addr_b(64) + bool(64) = 0x + 200 chars
        assert len(cd_volatile) == 2 + 8 + 64 + 64 + 64
        assert len(cd_stable) == 2 + 8 + 64 + 64 + 64
        assert cd_volatile != cd_stable, "volatile and stable calldata must differ"
