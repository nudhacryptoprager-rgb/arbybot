# tests/unit/test_mantle_mixed_source.py
"""
Tests for Mantle MIXED_SOURCE behavior and single-DEX config.

Mantle previously had two DEXes:
- agni_v3 (uniswap_v3 adapter) → uses quoter_v2
- stratum (ve33 adapter) → uses getAmountOut (ve33_getAmountOut)

Cross-dex routes (stratum<->agni_v3) triggered MIXED_SOURCE because
the quote sources are different. stratum was removed to eliminate
MIXED_SOURCE noise; Mantle now runs agni_v3 only with fee-tier arb.
"""

import pytest
import yaml


class TestMantleMixedSourcePolicy:
    """Test Mantle config handles MIXED_SOURCE correctly."""

    def test_mantle_config_has_require_cross_dex_false(self):
        """Coverage config for Mantle should have require_cross_dex=false."""
        with open("config/coverage_intent_mantle.yaml") as f:
            config = yaml.safe_load(f)
        
        # Key assertion: require_cross_dex must be false for Mantle
        # because ALL cross-dex routes are stratum<->agni_v3 = MIXED_SOURCE
        assert config.get("require_cross_dex") is False, (
            "Mantle require_cross_dex should be false to avoid MIXED_SOURCE. "
            "Cross-dex routes (stratum<->agni_v3) have different quote sources "
            "(ve33_getAmountOut vs quoter_v2)."
        )

    def test_mantle_has_one_dex(self):
        """Mantle should have exactly 1 DEX (agni_v3) after stratum removal."""
        with open("config/coverage_intent_mantle.yaml") as f:
            config = yaml.safe_load(f)
        
        dexes = config.get("dexes", [])
        assert len(dexes) == 1, f"Expected 1 DEX (stratum removed), got {len(dexes)}"
        assert "agni_v3" in dexes, "agni_v3 (uniswap_v3) required"

    def test_mantle_dexes_yaml_has_correct_adapter_types(self):
        """Verify dexes.yaml has correct adapter types for Mantle DEXes."""
        with open("config/dexes.yaml") as f:
            dexes = yaml.safe_load(f)
        
        mantle_dexes = dexes.get("mantle", {})
        
        # agni_v3 should be uniswap_v3 (quoter_v2)
        assert mantle_dexes.get("agni_v3", {}).get("adapter_type") == "uniswap_v3", (
            "agni_v3 must use uniswap_v3 adapter (quoter_v2 source)"
        )
        
        # stratum should be ve33 (getAmountOut)
        assert mantle_dexes.get("stratum", {}).get("adapter_type") == "ve33", (
            "stratum must use ve33 adapter (getAmountOut source)"
        )


class TestMixedSourceDetection:
    """Test MIXED_SOURCE detection logic."""

    def test_mixed_source_when_different_quote_sources(self):
        """MIXED_SOURCE should be true when buy/sell have different sources."""
        from strategy.spreads import compute_spread_signals
        
        # Simulate quotes with different sources
        quotes = [
            {
                "pair": "TEST/USDC",
                "dex_id": "stratum",
                "price": "1.0",
                "quote_source": "ve33_getAmountOut",
                "fee": 3000,
                "pool_address": "0x1111",
                "amount_in": "100",
                "amount_out": "100",
            },
            {
                "pair": "TEST/USDC",
                "dex_id": "agni_v3",
                "price": "1.01",
                "quote_source": "quoter_v2",
                "fee": 3000,
                "pool_address": "0x2222",
                "amount_in": "100",
                "amount_out": "101",
            },
        ]
        
        config = {
            "min_spread_bps": 1,
            "paper_size_usd": 100,
            "gas_usd_estimate": 0.02,
            "paper_slippage_bps": 5,
            "truth_mode_m42": True,
            "require_cross_dex": False,  # Allow single-dex, but test cross-dex
        }
        
        rejected_quotes = []
        signals = compute_spread_signals(quotes, config, current_block=12345678, rejected_quotes=rejected_quotes)
        
        # Should produce signals but with MIXED_SOURCE_DIAGNOSTIC
        assert len(signals) > 0, "Should produce at least one signal"
        
        # Find cross-dex signal
        cross_dex = [s for s in signals if s["route"] == "stratum->agni_v3"]
        if cross_dex:
            sig = cross_dex[0]
            assert "MIXED_SOURCE_DIAGNOSTIC" in sig["confidence_reasons"], (
                "Cross-dex stratum->agni_v3 should have MIXED_SOURCE_DIAGNOSTIC"
            )


class TestSameDexPolicy:
    """Test SAME_DEX_FEE_TIER behavior for Mantle fallback."""

    def test_same_dex_signal_not_excluded_when_require_cross_dex_false(self):
        """Same-DEX signals should NOT be excluded when require_cross_dex=false."""
        from strategy.spreads import compute_spread_signals
        
        # Simulate two pools on same DEX (agni_v3) with different fee tiers
        quotes = [
            {
                "pair": "CMETH/METH",
                "dex_id": "agni_v3",
                "price": "0.998",
                "quote_source": "quoter_v2",
                "fee": 100,  # 0.01%
                "pool_address": "0x1111",
                "amount_in": "100",
                "amount_out": "99.8",
            },
            {
                "pair": "CMETH/METH",
                "dex_id": "agni_v3",
                "price": "1.002",
                "quote_source": "quoter_v2",
                "fee": 2500,  # 0.25%
                "pool_address": "0x2222",
                "amount_in": "100",
                "amount_out": "100.2",
            },
        ]
        
        config = {
            "min_spread_bps": 1,
            "paper_size_usd": 100,
            "gas_usd_estimate": 0.02,
            "paper_slippage_bps": 5,
            "truth_mode_m42": True,
            "require_cross_dex": False,  # Allow same-dex
        }
        
        rejected_quotes = []
        signals = compute_spread_signals(quotes, config, current_block=12345678, rejected_quotes=rejected_quotes)
        
        # Should get a same-dex signal
        same_dex = [s for s in signals if s["is_same_dex"]]
        assert len(same_dex) > 0, "Should produce same-dex signal"
        
        # Should NOT be excluded (is_same_dex_excluded=false)
        sig = same_dex[0]
        assert sig["is_same_dex_excluded"] is False, (
            "Same-dex signal should NOT be excluded when require_cross_dex=false"
        )
        assert "SAME_DEX_FEE_TIER" in sig["confidence_reasons"]
        assert "SAME_DEX_EXCLUDED" not in sig["confidence_reasons"]

    def test_same_dex_signal_excluded_when_require_cross_dex_true(self):
        """Same-DEX signals should be excluded when require_cross_dex=true."""
        from strategy.spreads import compute_spread_signals
        
        quotes = [
            {
                "pair": "TEST/USDC",
                "dex_id": "agni_v3",
                "price": "1.0",
                "quote_source": "quoter_v2",
                "fee": 100,
                "pool_address": "0x1111",
                "amount_in": "100",
                "amount_out": "100",
            },
            {
                "pair": "TEST/USDC",
                "dex_id": "agni_v3",
                "price": "1.01",
                "quote_source": "quoter_v2",
                "fee": 500,
                "pool_address": "0x2222",
                "amount_in": "100",
                "amount_out": "101",
            },
        ]
        
        config = {
            "min_spread_bps": 1,
            "paper_size_usd": 100,
            "gas_usd_estimate": 0.02,
            "paper_slippage_bps": 5,
            "truth_mode_m42": True,
            "require_cross_dex": True,  # Require cross-dex
        }
        
        rejected_quotes = []
        signals = compute_spread_signals(quotes, config, current_block=12345678, rejected_quotes=rejected_quotes)
        
        # Same-dex signal should be excluded
        same_dex = [s for s in signals if s["is_same_dex"]]
        if same_dex:
            sig = same_dex[0]
            assert sig["is_same_dex_excluded"] is True, (
                "Same-dex signal should be excluded when require_cross_dex=true"
            )
            assert "SAME_DEX_EXCLUDED" in sig["confidence_reasons"]
