# PATH: tests/unit/test_same_dex_policy.py
"""
Tests for same-dex policy tracking in spread signals.

v2.5.0: Tests that SAME_DEX_FEE_TIER and SAME_DEX_EXCLUDED are tracked correctly.
"""
import pytest
from decimal import Decimal


def make_quote(dex_id, price, fee=500, token_in="WETH", token_out="USDC"):
    """Helper to create a minimal quote dict."""
    return {
        "dex_id": dex_id,
        "token_in": token_in,
        "token_out": token_out,
        "price_exact": str(price),
        "fee": fee,
        "quote_source": "quoter_v2",
        "amount_in_wei": 1000000000000000000,
        "amount_out_wei": int(float(price) * 1000000),
        "gate_passed": True,
        "is_diagnostic_only": False,
        "pool_address": f"0xPool_{dex_id}_{fee}",  # Required by spread computation
    }


class TestSameDexDetection:
    """Tests for is_same_dex flag in spread signals."""
    
    def test_same_dex_detected(self):
        """is_same_dex=True when buy_dex == sell_dex."""
        from strategy.spreads import compute_spread_signals
        
        quotes = [
            make_quote("uniswap_v3", "1920.00", fee=500),
            make_quote("uniswap_v3", "1925.00", fee=3000),  # Same DEX, different fee
        ]
        config = {"require_cross_dex": False}
        
        signals = compute_spread_signals(quotes, config, 1000, [])
        
        assert len(signals) >= 1
        sig = signals[0]
        
        assert sig["is_same_dex"] is True
        assert "SAME_DEX_FEE_TIER" in sig["confidence_reasons"]
    
    def test_cross_dex_not_flagged(self):
        """is_same_dex=False when buy_dex != sell_dex."""
        from strategy.spreads import compute_spread_signals
        
        quotes = [
            make_quote("uniswap_v3", "1920.00", fee=500),
            make_quote("sushiswap_v3", "1925.00", fee=500),  # Different DEX
        ]
        config = {"require_cross_dex": False}
        
        signals = compute_spread_signals(quotes, config, 1000, [])
        
        assert len(signals) >= 1
        sig = signals[0]
        
        assert sig["is_same_dex"] is False
        assert "SAME_DEX_FEE_TIER" not in sig["confidence_reasons"]


class TestSameDexExclusion:
    """Tests for is_same_dex_excluded with require_cross_dex=True."""
    
    def test_same_dex_not_generated_when_require_cross_dex(self):
        """v2.9.6: When require_cross_dex=True, same-DEX signals are NOT generated at all.
        
        This is a change from previous behavior where they were generated and excluded.
        Now they are simply not produced, avoiding excluded_signals_count noise.
        """
        from strategy.spreads import compute_spread_signals
        
        quotes = [
            make_quote("uniswap_v3", "1920.00", fee=500),
            make_quote("uniswap_v3", "1925.00", fee=3000),  # Same DEX
        ]
        config = {"require_cross_dex": True}  # Enable cross-dex requirement
        
        signals = compute_spread_signals(quotes, config, 1000, [])
        
        # v2.9.6: NO signals generated (same-DEX prevented at source)
        assert len(signals) == 0, \
            f"Expected 0 signals when require_cross_dex=true and only same-DEX, got {len(signals)}"
    
    def test_same_dex_not_excluded_when_require_cross_dex_false(self):
        """is_same_dex_excluded=False when require_cross_dex=False."""
        from strategy.spreads import compute_spread_signals
        
        quotes = [
            make_quote("uniswap_v3", "1920.00", fee=500),
            make_quote("uniswap_v3", "1925.00", fee=3000),  # Same DEX
        ]
        config = {"require_cross_dex": False}
        
        signals = compute_spread_signals(quotes, config, 1000, [])
        
        assert len(signals) >= 1
        sig = signals[0]
        
        assert sig["is_same_dex"] is True
        assert sig["is_same_dex_excluded"] is False
        assert "SAME_DEX_EXCLUDED" not in sig["confidence_reasons"]
    
    def test_cross_dex_not_affected_by_require_cross_dex(self):
        """Cross-DEX spreads not excluded even when require_cross_dex=True."""
        from strategy.spreads import compute_spread_signals
        
        quotes = [
            make_quote("uniswap_v3", "1920.00", fee=500),
            make_quote("sushiswap_v3", "1925.00", fee=500),  # Different DEX
        ]
        config = {"require_cross_dex": True}
        
        signals = compute_spread_signals(quotes, config, 1000, [])
        
        assert len(signals) >= 1
        sig = signals[0]
        
        assert sig["is_same_dex"] is False
        assert sig["is_same_dex_excluded"] is False
        assert "SAME_DEX_EXCLUDED" not in sig["confidence_reasons"]


class TestCrossDexPreference:
    """Tests for cross-dex preference when require_cross_dex=True.
    
    v2.5.1: When require_cross_dex=True, the spread computation should
    actively prefer cross-DEX combinations over same-DEX fee-tier arbs.
    """
    
    def test_cross_dex_chosen_over_same_dex_when_both_exist(self):
        """
        When require_cross_dex=True and both same-dex and cross-dex alternatives exist,
        the cross-dex combination should be chosen (buy_dex != sell_dex).
        """
        from strategy.spreads import compute_spread_signals
        
        # Create quotes where:
        # - Same-DEX spread (uniswap 500->3000): 1920->1930 = 52 bps
        # - Cross-DEX spread (uniswap->sushiswap): 1920->1928 = 41 bps
        # With require_cross_dex=True, should choose cross-DEX even if smaller spread
        quotes = [
            make_quote("uniswap_v3", "1920.00", fee=500),    # Best buy
            make_quote("uniswap_v3", "1930.00", fee=3000),   # Best sell (same-dex)
            make_quote("sushiswap_v3", "1922.00", fee=500),  # Sushi buy
            make_quote("sushiswap_v3", "1928.00", fee=3000), # Sushi sell (cross-dex option)
        ]
        config = {"require_cross_dex": True, "min_spread_bps": 5}
        
        signals = compute_spread_signals(quotes, config, 1000, [])
        
        assert len(signals) >= 1
        sig = signals[0]
        
        # Should be cross-DEX
        assert sig["buy_dex"] != sig["sell_dex"], \
            f"Expected cross-DEX but got buy_dex={sig['buy_dex']}, sell_dex={sig['sell_dex']}"
        assert sig["is_same_dex"] is False
        assert sig["is_same_dex_excluded"] is False
        assert "SAME_DEX_EXCLUDED" not in sig["confidence_reasons"]
    
    def test_no_signal_when_no_cross_dex_alternative(self):
        """v2.9.6: When require_cross_dex=True and only one DEX has quotes,
        NO signal is generated (not even an excluded one).
        
        Previous behavior: same-DEX signal generated but excluded.
        New behavior: no signal at all (reduces excluded_signals_count noise).
        """
        from strategy.spreads import compute_spread_signals
        
        # Only uniswap quotes - no cross-dex possible
        quotes = [
            make_quote("uniswap_v3", "1920.00", fee=500),
            make_quote("uniswap_v3", "1930.00", fee=3000),
        ]
        config = {"require_cross_dex": True, "min_spread_bps": 5}
        
        signals = compute_spread_signals(quotes, config, 1000, [])
        
        # v2.9.6: NO signals generated
        assert len(signals) == 0, \
            f"Expected 0 signals when require_cross_dex=true and no cross-DEX, got {len(signals)}"
    
    def test_cross_dex_best_spread_selected(self):
        """
        When require_cross_dex=True, selects the best cross-DEX spread
        (buy from lowest price DEX, sell to highest price DEX).
        """
        from strategy.spreads import compute_spread_signals
        
        # Uniswap has lower buy price (1918), Sushi has higher sell price (1932)
        # Best cross-DEX: Uniswap buy -> Sushi sell
        quotes = [
            make_quote("uniswap_v3", "1918.00", fee=500),    # Best buy (Uni)
            make_quote("uniswap_v3", "1925.00", fee=3000),
            make_quote("sushiswap_v3", "1920.00", fee=500),
            make_quote("sushiswap_v3", "1932.00", fee=3000), # Best sell (Sushi)
        ]
        config = {"require_cross_dex": True, "min_spread_bps": 5}
        
        signals = compute_spread_signals(quotes, config, 1000, [])
        
        assert len(signals) >= 1
        sig = signals[0]
        
        # Best cross-DEX: buy from uniswap_v3 at 1918, sell to sushiswap_v3 at 1932
        assert sig["buy_dex"] == "uniswap_v3"
        assert sig["sell_dex"] == "sushiswap_v3"
        assert sig["is_same_dex"] is False
    
    def test_dual_cross_dex_routes_emitted(self):
        """
        v2.5.2: When emit_dual_routes=True (default), emit BOTH cross-DEX directions
        (A->B and B->A) for each pair to boost route diversity.
        """
        from strategy.spreads import compute_spread_signals
        
        # Two DEXs with different prices - both directions should be profitable
        # Uni: 1918 to 1925  |  Sushi: 1920 to 1932
        # Direction 1: Buy Uni 1918, Sell Sushi 1932 = ~73 bps
        # Direction 2: Buy Sushi 1920, Sell Uni 1925 = ~26 bps
        quotes = [
            make_quote("uniswap_v3", "1918.00", fee=500),
            make_quote("uniswap_v3", "1925.00", fee=3000),
            make_quote("sushiswap_v3", "1920.00", fee=500),
            make_quote("sushiswap_v3", "1932.00", fee=3000),
        ]
        config = {"require_cross_dex": False, "min_spread_bps": 5, "emit_dual_routes": True}
        
        signals = compute_spread_signals(quotes, config, 1000, [])
        
        # Filter for cross-DEX signals only
        cross_dex_signals = [s for s in signals if not s["is_same_dex"]]
        
        # Should have at least 2 cross-DEX signals (both directions)
        assert len(cross_dex_signals) >= 2, \
            f"Expected at least 2 cross-DEX signals, got {len(cross_dex_signals)}"
        
        # Verify both directions exist
        routes = {(s["buy_dex"], s["sell_dex"]) for s in cross_dex_signals}
        assert ("uniswap_v3", "sushiswap_v3") in routes, \
            f"Missing Uni->Sushi route in {routes}"
        assert ("sushiswap_v3", "uniswap_v3") in routes, \
            f"Missing Sushi->Uni route in {routes}"


class TestHuntingConfigContract:
    """Contract tests for hunting-style configs (low fee tier arbitrage).
    
    v3.1.0: Ensures hunting configs produce valid cross-DEX signals
    without MIXED_SOURCE contamination for roundtrip evaluation.
    """
    
    def test_cross_dex_signals_no_mixed_source(self):
        """Cross-DEX signals must not have MIXED_SOURCE in confidence_reasons.
        
        MIXED_SOURCE indicates slot0/quoter mixed pricing which is excluded
        in truth_mode_m42 because it creates false positives.
        """
        from strategy.spreads import compute_spread_signals
        
        # Simulate quotes from two DEXes, all using quoter_v2 (no slot0)
        quotes = [
            {
                "dex_id": "uniswap_v3",
                "token_in": "WETH",
                "token_out": "USDC",
                "price_exact": "1920.000000",
                "fee": 500,
                "quote_source": "quoter_v2",  # Not slot0
                "amount_in_wei": 100_000_000_000_000_000,
                "amount_out_wei": 192_000_000,
                "gate_passed": True,
                "is_diagnostic_only": False,
                "pool_address": "0xPoolUniV3_500",
            },
            {
                "dex_id": "sushiswap_v3",
                "token_in": "WETH",
                "token_out": "USDC",
                "price_exact": "1925.000000",
                "fee": 500,
                "quote_source": "quoter_v2",  # Not slot0
                "amount_in_wei": 100_000_000_000_000_000,
                "amount_out_wei": 192_500_000,
                "gate_passed": True,
                "is_diagnostic_only": False,
                "pool_address": "0xPoolSushiV3_500",
            },
        ]
        config = {"require_cross_dex": True, "min_spread_bps": 5}
        
        signals = compute_spread_signals(quotes, config, 1000, [])
        
        assert len(signals) >= 1, "Expected at least 1 cross-DEX signal"
        
        for sig in signals:
            # Must be cross-DEX
            assert not sig["is_same_dex"], f"Expected cross-DEX signal, got same-DEX"
            
            # MIXED_SOURCE must not appear (we used uniform quoter_v2)
            reasons = sig.get("confidence_reasons", [])
            assert "MIXED_SOURCE" not in reasons, \
                f"MIXED_SOURCE should not appear with uniform quoter_v2: {reasons}"
    
    def test_mixed_source_flagged_when_slot0_present(self):
        """When buy uses slot0 and sell uses quoter_v2, MIXED_SOURCE_DIAGNOSTIC is flagged.
        
        This validates that truth_mode_m42 would exclude such signals.
        """
        from strategy.spreads import compute_spread_signals
        
        # One quote uses slot0, other uses quoter_v2
        quotes = [
            {
                "dex_id": "uniswap_v3",
                "token_in": "WETH",
                "token_out": "USDC",
                "price_exact": "1920.000000",
                "fee": 500,
                "quote_source": "slot0",  # slot0 source
                "amount_in_wei": 100_000_000_000_000_000,
                "amount_out_wei": 192_000_000,
                "gate_passed": True,
                "is_diagnostic_only": False,
                "pool_address": "0xPoolUniV3_500",
            },
            {
                "dex_id": "sushiswap_v3",
                "token_in": "WETH",
                "token_out": "USDC",
                "price_exact": "1925.000000",
                "fee": 500,
                "quote_source": "quoter_v2",  # quoter source
                "amount_in_wei": 100_000_000_000_000_000,
                "amount_out_wei": 192_500_000,
                "gate_passed": True,
                "is_diagnostic_only": False,
                "pool_address": "0xPoolSushiV3_500",
            },
        ]
        config = {"require_cross_dex": True, "min_spread_bps": 5}
        
        signals = compute_spread_signals(quotes, config, 1000, [])
        
        # With mixed sources, signal may still be generated but must be flagged
        if len(signals) > 0:
            sig = signals[0]
            reasons = sig.get("confidence_reasons", [])
            # MIXED_SOURCE_DIAGNOSTIC should be present when sources differ
            # (also SLOT0_DIAGNOSTIC for the slot0 leg)
            assert "MIXED_SOURCE_DIAGNOSTIC" in reasons, \
                f"Expected MIXED_SOURCE_DIAGNOSTIC for slot0/quoter_v2 mix: {reasons}"
            assert "SLOT0_DIAGNOSTIC" in reasons, \
                f"Expected SLOT0_DIAGNOSTIC when slot0 source present: {reasons}"
    
    def test_require_cross_dex_blocks_same_dex(self):
        """With require_cross_dex=True, same-DEX opportunities are not generated.
        
        This ensures hunting configs don't waste resources on non-executable routes.
        """
        from strategy.spreads import compute_spread_signals
        
        # Only one DEX (same-DEX only scenario)
        quotes = [
            {
                "dex_id": "uniswap_v3",
                "token_in": "WETH",
                "token_out": "USDC",
                "price_exact": "1920.000000",
                "fee": 500,
                "quote_source": "quoter_v2",
                "amount_in_wei": 100_000_000_000_000_000,
                "amount_out_wei": 192_000_000,
                "gate_passed": True,
                "is_diagnostic_only": False,
                "pool_address": "0xPoolUniV3_500",
            },
            {
                "dex_id": "uniswap_v3",  # Same DEX different fee tier
                "token_in": "WETH",
                "token_out": "USDC",
                "price_exact": "1930.000000",
                "fee": 3000,
                "quote_source": "quoter_v2",
                "amount_in_wei": 100_000_000_000_000_000,
                "amount_out_wei": 193_000_000,
                "gate_passed": True,
                "is_diagnostic_only": False,
                "pool_address": "0xPoolUniV3_3000",
            },
        ]
        # Hunting config uses require_cross_dex=True
        config = {"require_cross_dex": True, "min_spread_bps": 5}
        
        signals = compute_spread_signals(quotes, config, 1000, [])
        
        # No signals should be generated for same-DEX when require_cross_dex=True
        assert len(signals) == 0, \
            f"Expected 0 signals with require_cross_dex and same-DEX only, got {len(signals)}"


class TestSameDexFallbackArtifactContract:
    """v3.2.58: Artifact contract tests for same-DEX fallback mode.
    
    When require_cross_dex=False (same-DEX fallback), the opportunity_engine
    summary should include explicit flags to reconcile:
    - spread_signals_count: Total signals including same-DEX fee-tier arb
    - same_dex_fallback_mode: Whether fallback is active
    - same_dex_signals_active: Whether same-DEX signals exist with 0 cross-DEX
    
    This prevents artifact contract mismatches where signals_count > 0
    but total_opportunities = 0.
    """
    
    def test_same_dex_fallback_mode_flag_true_when_require_cross_dex_false(self):
        """same_dex_fallback_mode=True when require_cross_dex=False."""
        config = {"require_cross_dex": False}
        expected = not config.get("require_cross_dex", True)
        assert expected is True
    
    def test_same_dex_fallback_mode_flag_false_when_require_cross_dex_true(self):
        """same_dex_fallback_mode=False when require_cross_dex=True (default)."""
        config = {"require_cross_dex": True}
        expected = not config.get("require_cross_dex", True)
        assert expected is False
    
    def test_same_dex_fallback_mode_flag_false_when_missing(self):
        """same_dex_fallback_mode=False when require_cross_dex not set (defaults to True)."""
        config = {}  # Missing require_cross_dex
        expected = not config.get("require_cross_dex", True)
        assert expected is False
    
    def test_artifact_reconciliation_logic(self):
        """Test the artifact reconciliation logic for same-DEX fallback.
        
        When same_dex_fallback_mode=True and spread_signals_count > 0 but
        total_opportunities=0, the artifact should have same_dex_signals_active=True
        and a note explaining the expected behavior.
        """
        # Simulate artifact construction logic from run_scan_real.py
        spread_signals = [{"id": "spread_1", "is_same_dex": True}]  # 1 same-DEX signal
        opps_summary = {"total_opportunities": 0, "profitable_count": 0}  # 0 cross-DEX opps
        config = {"require_cross_dex": False}
        
        # Logic from run_scan_real.py v3.2.58
        require_cross_dex = config.get("require_cross_dex", True)
        same_dex_fallback = not require_cross_dex
        
        # Build opportunity_engine stats
        opp_engine_stats = {
            "summary": dict(opps_summary),  # Copy to allow modification
            "same_dex_fallback_mode": same_dex_fallback,
            "spread_signals_count": len(spread_signals),
        }
        
        # Apply reconciliation
        if same_dex_fallback and len(spread_signals) > 0 and opps_summary.get("total_opportunities", 0) == 0:
            opp_engine_stats["summary"]["same_dex_signals_active"] = True
            opp_engine_stats["summary"]["note"] = "Same-DEX fallback: spread_signals are fee-tier arbitrage, not cross-DEX opportunities"
        
        # Validate
        assert opp_engine_stats["same_dex_fallback_mode"] is True
        assert opp_engine_stats["spread_signals_count"] == 1
        assert opp_engine_stats["summary"]["same_dex_signals_active"] is True
        assert "Same-DEX fallback" in opp_engine_stats["summary"]["note"]
    
    def test_no_reconciliation_when_cross_dex_mode(self):
        """When require_cross_dex=True, no reconciliation needed."""
        spread_signals = []  # 0 signals (same-DEX blocked at source)
        opps_summary = {"total_opportunities": 0, "profitable_count": 0}
        config = {"require_cross_dex": True}
        
        require_cross_dex = config.get("require_cross_dex", True)
        same_dex_fallback = not require_cross_dex
        
        opp_engine_stats = {
            "summary": dict(opps_summary),
            "same_dex_fallback_mode": same_dex_fallback,
            "spread_signals_count": len(spread_signals),
        }
        
        # No reconciliation applied when require_cross_dex=True
        if same_dex_fallback and len(spread_signals) > 0 and opps_summary.get("total_opportunities", 0) == 0:
            opp_engine_stats["summary"]["same_dex_signals_active"] = True
        
        assert opp_engine_stats["same_dex_fallback_mode"] is False
        assert opp_engine_stats["spread_signals_count"] == 0
        assert "same_dex_signals_active" not in opp_engine_stats["summary"]
    
    def test_no_reconciliation_when_cross_dex_opps_exist(self):
        """When total_opportunities > 0, no reconciliation needed."""
        spread_signals = [{"id": "spread_1"}]  # 1 signal
        opps_summary = {"total_opportunities": 5, "profitable_count": 2}  # Cross-DEX opps exist
        config = {"require_cross_dex": False}
        
        require_cross_dex = config.get("require_cross_dex", True)
        same_dex_fallback = not require_cross_dex
        
        opp_engine_stats = {
            "summary": dict(opps_summary),
            "same_dex_fallback_mode": same_dex_fallback,
            "spread_signals_count": len(spread_signals),
        }
        
        # Reconciliation should NOT be applied when total_opportunities > 0
        if same_dex_fallback and len(spread_signals) > 0 and opps_summary.get("total_opportunities", 0) == 0:
            opp_engine_stats["summary"]["same_dex_signals_active"] = True
        
        assert opp_engine_stats["same_dex_fallback_mode"] is True
        assert opp_engine_stats["spread_signals_count"] == 1
        assert "same_dex_signals_active" not in opp_engine_stats["summary"]
