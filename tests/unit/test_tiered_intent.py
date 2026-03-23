# PATH: tests/unit/test_tiered_intent.py
"""
Unit tests for tiered intent generation (R39d — quality-ranked pair selection).

Tests:
  1. classify_token() returns correct tiers based on metadata
  2. Productive contour matches lead's per-chain P0 directives
  3. Stable/stable, LST/LRT excluded from productive
  4. Exploratory tier includes productive + exploratory tokens
  5. Diagnostic tier isolates LST and stablecoin pairs
  6. core_tokens.yaml metadata contract: all tokens have tier fields
"""

import pytest
import yaml
from pathlib import Path

# Import from the generate_intent script
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
from generate_intent import (
    classify_token,
    generate_pairs_for_chain,
    generate_intent,
    load_core_tokens,
    INFRA_TOKENS,
    KNOWN_LST,
)


# ──────────────────────────────────────────────────────────────
# classify_token tests
# ──────────────────────────────────────────────────────────────

class TestClassifyToken:
    """Tests for classify_token() tier classification."""

    def test_productive_token(self):
        meta = {"productive_default": True, "volatility_tier": "high"}
        assert classify_token("ARB", meta) == "productive"

    def test_infra_token_always_diagnostic(self):
        """Stablecoin infra tokens are diagnostic even with productive_default=True."""
        meta = {"productive_default": True}
        assert classify_token("USDC", meta) == "diagnostic"
        assert classify_token("USDT", meta) == "diagnostic"
        assert classify_token("DAI", meta) == "diagnostic"

    def test_lst_token_diagnostic(self):
        """LST/LRT tokens with accounting_sensitive=True are diagnostic."""
        meta = {"accounting_sensitive": True, "productive_default": False}
        assert classify_token("wstETH", meta) == "diagnostic"

    def test_lst_fallback_without_metadata(self):
        """Known LST tokens are diagnostic even without explicit metadata."""
        assert classify_token("wstETH", {}) == "diagnostic"
        assert classify_token("mETH", {}) == "diagnostic"
        assert classify_token("ezETH", {}) == "diagnostic"

    def test_exploratory_token(self):
        meta = {"productive_default": False, "volatility_tier": "high"}
        assert classify_token("BRETT", meta) == "exploratory"

    def test_weth_always_productive(self):
        assert classify_token("WETH", {}) == "productive"

    def test_wmnt_always_productive(self):
        assert classify_token("WMNT", {}) == "productive"

    def test_near_stable_diagnostic(self):
        """Near-stable tokens (FRAX, LUSD, USDE) are infra → diagnostic."""
        for sym in ["FRAX", "LUSD", "USDE"]:
            assert classify_token(sym, {}) == "diagnostic"


# ──────────────────────────────────────────────────────────────
# Per-chain productive contour tests (lead's P0 directives)
# ──────────────────────────────────────────────────────────────

class TestArbitrumP0:
    """Arb P0: ARB/USDC, WETH/ARB, PENDLE/USDC, WETH/PENDLE, LINK/USDC, WETH/LINK, WBTC/USDC, WETH/USDC."""

    def test_arb_productive_pairs(self):
        data = load_core_tokens()
        pairs = generate_pairs_for_chain("arbitrum_one", data["arbitrum_one"], "productive")
        pair_set = set(pairs)

        # All lead-mandated P0 pairs must be present
        required = {
            "arbitrum_one:ARB/USDC",
            "arbitrum_one:WETH/ARB",
            "arbitrum_one:PENDLE/USDC",
            "arbitrum_one:WETH/PENDLE",
            "arbitrum_one:LINK/USDC",
            "arbitrum_one:WETH/LINK",
            "arbitrum_one:WBTC/USDC",
            "arbitrum_one:WETH/USDC",
        }
        assert required.issubset(pair_set), f"Missing: {required - pair_set}"

    def test_arb_demoted_absent(self):
        """Demoted tokens (DPX, GRAIL, GNS, JOE, MAGIC, RDNT, TBTC, LUSD, USDE) not in productive."""
        data = load_core_tokens()
        pairs = generate_pairs_for_chain("arbitrum_one", data["arbitrum_one"], "productive")
        pair_text = " ".join(pairs)
        for demoted in ["DPX", "GRAIL", "GNS", "JOE", "MAGIC", "RDNT", "TBTC"]:
            assert demoted not in pair_text, f"{demoted} should not be in productive"

    def test_arb_lst_absent(self):
        """LST tokens not in productive."""
        data = load_core_tokens()
        pairs = generate_pairs_for_chain("arbitrum_one", data["arbitrum_one"], "productive")
        pair_text = " ".join(pairs)
        for lst in ["wstETH", "rETH"]:
            assert lst not in pair_text, f"{lst} should not be in productive"

    def test_arb_stable_absent(self):
        """Stable/stable pairs (USDC/DAI, USDC/USDT) not in productive."""
        data = load_core_tokens()
        pairs = generate_pairs_for_chain("arbitrum_one", data["arbitrum_one"], "productive")
        pair_set = set(pairs)
        assert "arbitrum_one:USDC/DAI" not in pair_set
        assert "arbitrum_one:USDC/USDT" not in pair_set


class TestBaseP0:
    """Base P0: AERO/USDC, WETH/AERO, VIRTUAL/USDC, WETH/VIRTUAL, cbBTC/USDC, cbBTC/WETH, WETH/USDC."""

    def test_base_productive_pairs(self):
        data = load_core_tokens()
        pairs = generate_pairs_for_chain("base", data["base"], "productive")
        pair_set = set(pairs)

        required = {
            "base:AERO/USDC",
            "base:WETH/AERO",
            "base:VIRTUAL/USDC",
            "base:WETH/VIRTUAL",
            "base:cbBTC/USDC",
            "base:cbBTC/WETH",
            "base:WETH/USDC",
        }
        assert required.issubset(pair_set), f"Missing: {required - pair_set}"

    def test_base_exploratory_absent(self):
        """BRETT/DEGEN/TOSHI/WELL not in productive."""
        data = load_core_tokens()
        pairs = generate_pairs_for_chain("base", data["base"], "productive")
        pair_text = " ".join(pairs)
        for explo in ["BRETT", "DEGEN", "TOSHI", "WELL"]:
            assert explo not in pair_text, f"{explo} should not be in productive"


class TestMantleP0:
    """Mantle P0: WMNT/USDC, WMNT/USDT, WETH/WMNT, WETH/USDC."""

    def test_mantle_productive_pairs(self):
        data = load_core_tokens()
        pairs = generate_pairs_for_chain("mantle", data["mantle"], "productive")
        pair_set = set(pairs)

        required = {
            "mantle:WMNT/USDC",
            "mantle:WMNT/USDT",
            "mantle:WETH/WMNT",
            "mantle:WETH/USDC",
        }
        assert required.issubset(pair_set), f"Missing: {required - pair_set}"

    def test_mantle_lst_absent(self):
        """mETH/cmETH/PUFF not in productive."""
        data = load_core_tokens()
        pairs = generate_pairs_for_chain("mantle", data["mantle"], "productive")
        pair_text = " ".join(pairs)
        for demoted in ["mETH", "cmETH", "PUFF"]:
            assert demoted not in pair_text, f"{demoted} should not be in productive"


class TestZksyncP0:
    """Zksync P0: ZK/USDC, ZK/WETH, WETH/USDC, WBTC/USDC."""

    def test_zksync_productive_pairs(self):
        data = load_core_tokens()
        pairs = generate_pairs_for_chain("zksync", data["zksync"], "productive")
        pair_set = set(pairs)

        required = {
            "zksync:ZK/USDC",
            "zksync:ZK/WETH",
            "zksync:WETH/USDC",
            "zksync:WBTC/USDC",
        }
        assert required.issubset(pair_set), f"Missing: {required - pair_set}"

    def test_zksync_removed_absent(self):
        """CHEEMS/HOLD not in productive."""
        data = load_core_tokens()
        pairs = generate_pairs_for_chain("zksync", data["zksync"], "productive")
        pair_text = " ".join(pairs)
        assert "CHEEMS" not in pair_text
        assert "HOLD" not in pair_text


class TestScrollP0:
    """Scroll P0: WETH/USDC, WBTC/USDC, WETH/WBTC."""

    def test_scroll_productive_pairs(self):
        data = load_core_tokens()
        pairs = generate_pairs_for_chain("scroll", data["scroll"], "productive")
        pair_set = set(pairs)

        required = {
            "scroll:WETH/USDC",
            "scroll:WBTC/USDC",
            "scroll:WETH/WBTC",
        }
        assert pair_set == required, f"Expected exactly {required}, got {pair_set}"

    def test_scroll_scr_exploratory(self):
        """SCR not in productive."""
        data = load_core_tokens()
        pairs = generate_pairs_for_chain("scroll", data["scroll"], "productive")
        pair_text = " ".join(pairs)
        assert "SCR" not in pair_text


# ──────────────────────────────────────────────────────────────
# Tier expansion tests
# ──────────────────────────────────────────────────────────────

class TestTierExpansion:
    """Tests for exploratory and all tier modes."""

    def test_exploratory_includes_productive(self):
        """Exploratory tier is a superset of productive."""
        data = load_core_tokens()
        for chain in ["arbitrum_one", "base", "zksync"]:
            prod = set(generate_pairs_for_chain(chain, data[chain], "productive"))
            explo = set(generate_pairs_for_chain(chain, data[chain], "exploratory"))
            assert prod.issubset(explo), f"{chain}: productive not subset of exploratory"

    def test_exploratory_adds_demoted(self):
        """Exploratory tier includes demoted tokens."""
        data = load_core_tokens()
        explo = generate_pairs_for_chain("arbitrum_one", data["arbitrum_one"], "exploratory")
        explo_text = " ".join(explo)
        # At least some demoted tokens should appear in exploratory
        found = any(t in explo_text for t in ["GMX", "UNI", "GNS", "GRAIL", "JOE"])
        assert found, "Exploratory should include some demoted arb tokens"

    def test_all_includes_diagnostic(self):
        """All tier includes LST and stable pairs."""
        data = load_core_tokens()
        all_pairs = generate_pairs_for_chain("arbitrum_one", data["arbitrum_one"], "all")
        all_text = " ".join(all_pairs)
        # LST tokens should appear in 'all'
        assert "wstETH" in all_text or "rETH" in all_text

    def test_base_exploratory_has_brett(self):
        """Base exploratory includes BRETT/DEGEN/TOSHI/WELL."""
        data = load_core_tokens()
        explo = generate_pairs_for_chain("base", data["base"], "exploratory")
        explo_text = " ".join(explo)
        for token in ["BRETT", "DEGEN", "TOSHI", "WELL"]:
            assert token in explo_text, f"{token} should be in base exploratory"

    def test_scroll_exploratory_has_scr(self):
        """Scroll exploratory includes SCR."""
        data = load_core_tokens()
        explo = generate_pairs_for_chain("scroll", data["scroll"], "exploratory")
        explo_text = " ".join(explo)
        assert "SCR" in explo_text


# ──────────────────────────────────────────────────────────────
# Metadata contract: core_tokens.yaml must have tier fields
# ──────────────────────────────────────────────────────────────

class TestCoreTokensMetadata:
    """All tokens in core_tokens.yaml must have tier metadata."""

    def test_all_tokens_have_productive_default(self):
        """Every token must have productive_default field."""
        data = load_core_tokens()
        missing = []
        for chain, tokens in data.items():
            for sym, meta in tokens.items():
                if meta is None:
                    meta = {}
                if "productive_default" not in meta:
                    missing.append(f"{chain}:{sym}")
        assert not missing, f"Missing productive_default: {missing}"

    def test_all_tokens_have_volatility_tier(self):
        data = load_core_tokens()
        missing = []
        for chain, tokens in data.items():
            for sym, meta in tokens.items():
                if meta is None:
                    meta = {}
                if "volatility_tier" not in meta:
                    missing.append(f"{chain}:{sym}")
        assert not missing, f"Missing volatility_tier: {missing}"

    def test_all_tokens_have_cross_dex_expected(self):
        data = load_core_tokens()
        missing = []
        for chain, tokens in data.items():
            for sym, meta in tokens.items():
                if meta is None:
                    meta = {}
                if "cross_dex_expected" not in meta:
                    missing.append(f"{chain}:{sym}")
        assert not missing, f"Missing cross_dex_expected: {missing}"

    def test_lst_tokens_have_accounting_sensitive(self):
        """LST/LRT tokens must have accounting_sensitive=True."""
        data = load_core_tokens()
        missing = []
        for chain, tokens in data.items():
            for sym, meta in tokens.items():
                if meta is None:
                    meta = {}
                if sym.lower() in KNOWN_LST and not meta.get("accounting_sensitive"):
                    missing.append(f"{chain}:{sym}")
        assert not missing, f"LST tokens without accounting_sensitive: {missing}"


# ──────────────────────────────────────────────────────────────
# Productive pair count / sanity
# ──────────────────────────────────────────────────────────────

class TestProductiveSanity:
    """Sanity checks on productive contour size."""

    def test_total_productive_pairs_reasonable(self):
        """Productive contour should have 25-40 pairs (focused, not bloated)."""
        generated = generate_intent("productive")
        lines = [l for l in generated.split("\n") if l and not l.startswith("#")]
        assert 25 <= len(lines) <= 40, f"Expected 25-40 productive pairs, got {len(lines)}"

    def test_each_chain_has_weth_usdc(self):
        """Every chain must have WETH/USDC anchor in productive."""
        data = load_core_tokens()
        for chain in ["arbitrum_one", "base", "linea", "scroll", "mantle", "zksync"]:
            pairs = generate_pairs_for_chain(chain, data[chain], "productive")
            assert f"{chain}:WETH/USDC" in pairs, f"{chain} missing WETH/USDC anchor"
