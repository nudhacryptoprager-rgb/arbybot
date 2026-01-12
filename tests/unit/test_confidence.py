"""
Unit tests for confidence scoring.

M3 requirement: confidence must be a real signal, not a placeholder.
"""

import pytest
from monitoring.truth_report import calculate_confidence


class TestConfidenceComponents:
    """Test individual confidence score components."""
    
    def test_confidence_has_breakdown(self):
        """Confidence calculation returns breakdown dict."""
        spread = {
            "spread_bps": 50,
            "gas_cost_bps": 5,
            "net_pnl_bps": 45,
            "executable": True,
            "buy_leg": {
                "latency_ms": 100,
                "ticks_crossed": 5,
                "verified_for_execution": True,
            },
            "sell_leg": {
                "latency_ms": 100,
                "ticks_crossed": 5,
                "verified_for_execution": True,
            },
        }
        
        score, breakdown = calculate_confidence(spread)
        
        assert isinstance(breakdown, dict)
        assert "freshness" in breakdown
        assert "ticks" in breakdown
        assert "verification" in breakdown
        assert "profitability" in breakdown
        assert "gas_efficiency" in breakdown
        assert "rpc_health" in breakdown
        assert "plausibility" in breakdown
        assert "final" in breakdown
    
    def test_high_ticks_lowers_confidence(self):
        """High ticks_crossed should lower confidence."""
        base_spread = {
            "spread_bps": 50,
            "gas_cost_bps": 5,
            "net_pnl_bps": 45,
            "executable": True,
            "buy_leg": {"latency_ms": 100, "verified_for_execution": True},
            "sell_leg": {"latency_ms": 100, "verified_for_execution": True},
        }
        
        # Low ticks
        low_ticks = {**base_spread}
        low_ticks["buy_leg"] = {**base_spread["buy_leg"], "ticks_crossed": 3}
        low_ticks["sell_leg"] = {**base_spread["sell_leg"], "ticks_crossed": 3}
        
        # High ticks
        high_ticks = {**base_spread}
        high_ticks["buy_leg"] = {**base_spread["buy_leg"], "ticks_crossed": 20}
        high_ticks["sell_leg"] = {**base_spread["sell_leg"], "ticks_crossed": 20}
        
        low_score, _ = calculate_confidence(low_ticks)
        high_score, _ = calculate_confidence(high_ticks)
        
        assert low_score > high_score, "High ticks should lower confidence"
    
    def test_high_latency_lowers_confidence(self):
        """High latency should lower freshness score."""
        base_spread = {
            "spread_bps": 50,
            "gas_cost_bps": 5,
            "net_pnl_bps": 45,
            "executable": True,
            "buy_leg": {"ticks_crossed": 5, "verified_for_execution": True},
            "sell_leg": {"ticks_crossed": 5, "verified_for_execution": True},
        }
        
        # Low latency
        fast = {**base_spread}
        fast["buy_leg"] = {**base_spread["buy_leg"], "latency_ms": 50}
        fast["sell_leg"] = {**base_spread["sell_leg"], "latency_ms": 50}
        
        # High latency
        slow = {**base_spread}
        slow["buy_leg"] = {**base_spread["buy_leg"], "latency_ms": 800}
        slow["sell_leg"] = {**base_spread["sell_leg"], "latency_ms": 800}
        
        _, fast_breakdown = calculate_confidence(fast)
        _, slow_breakdown = calculate_confidence(slow)
        
        assert fast_breakdown["freshness"] > slow_breakdown["freshness"]
    
    def test_unverified_lowers_confidence(self):
        """Unverified DEXes should lower verification score."""
        base_spread = {
            "spread_bps": 50,
            "gas_cost_bps": 5,
            "net_pnl_bps": 45,
            "executable": False,
            "buy_leg": {"latency_ms": 100, "ticks_crossed": 5},
            "sell_leg": {"latency_ms": 100, "ticks_crossed": 5},
        }
        
        # Verified
        verified = {**base_spread, "executable": True}
        verified["buy_leg"] = {**base_spread["buy_leg"], "verified_for_execution": True}
        verified["sell_leg"] = {**base_spread["sell_leg"], "verified_for_execution": True}
        
        # Unverified
        unverified = {**base_spread}
        unverified["buy_leg"] = {**base_spread["buy_leg"], "verified_for_execution": False}
        unverified["sell_leg"] = {**base_spread["sell_leg"], "verified_for_execution": False}
        
        _, verified_breakdown = calculate_confidence(verified)
        _, unverified_breakdown = calculate_confidence(unverified)
        
        assert verified_breakdown["verification"] > unverified_breakdown["verification"]
    
    def test_very_high_spread_suspicious(self):
        """Very high spread (>500 bps) should be marked suspicious."""
        suspicious_spread = {
            "spread_bps": 600,  # 6% - very suspicious
            "gas_cost_bps": 5,
            "net_pnl_bps": 595,
            "executable": True,
            "buy_leg": {
                "latency_ms": 100,
                "ticks_crossed": 5,
                "verified_for_execution": True,
            },
            "sell_leg": {
                "latency_ms": 100,
                "ticks_crossed": 5,
                "verified_for_execution": True,
            },
        }
        
        _, breakdown = calculate_confidence(suspicious_spread)
        
        assert breakdown["plausibility"] < 0.5, "Very high spread should be suspicious"
    
    def test_unprofitable_caps_confidence(self):
        """Unprofitable spread should have confidence capped at 0.3."""
        unprofitable = {
            "spread_bps": 10,
            "gas_cost_bps": 15,
            "net_pnl_bps": -5,
            "executable": False,
            "buy_leg": {
                "latency_ms": 100,
                "ticks_crossed": 5,
                "verified_for_execution": True,
            },
            "sell_leg": {
                "latency_ms": 100,
                "ticks_crossed": 5,
                "verified_for_execution": True,
            },
        }
        
        score, _ = calculate_confidence(unprofitable)
        
        assert score <= 0.3, "Unprofitable spread confidence capped at 0.3"
    
    def test_rpc_health_affects_confidence(self):
        """Low RPC health should lower confidence."""
        spread = {
            "spread_bps": 50,
            "gas_cost_bps": 5,
            "net_pnl_bps": 45,
            "executable": True,
            "buy_leg": {
                "latency_ms": 100,
                "ticks_crossed": 5,
                "verified_for_execution": True,
            },
            "sell_leg": {
                "latency_ms": 100,
                "ticks_crossed": 5,
                "verified_for_execution": True,
            },
        }
        
        healthy, _ = calculate_confidence(spread, rpc_success_rate=1.0)
        unhealthy, _ = calculate_confidence(spread, rpc_success_rate=0.5)
        
        assert healthy > unhealthy, "Low RPC health should lower confidence"


class TestConfidenceRanges:
    """Test that confidence values are in expected ranges."""
    
    def test_confidence_between_0_and_1(self):
        """Confidence must be between 0 and 1."""
        # Best case
        best_spread = {
            "spread_bps": 50,
            "gas_cost_bps": 2,
            "net_pnl_bps": 48,
            "executable": True,
            "buy_leg": {
                "latency_ms": 50,
                "ticks_crossed": 2,
                "verified_for_execution": True,
            },
            "sell_leg": {
                "latency_ms": 50,
                "ticks_crossed": 2,
                "verified_for_execution": True,
            },
        }
        
        # Worst case
        worst_spread = {
            "spread_bps": 1000,
            "gas_cost_bps": 1100,
            "net_pnl_bps": -100,
            "executable": False,
            "buy_leg": {
                "latency_ms": 2000,
                "ticks_crossed": 50,
                "verified_for_execution": False,
            },
            "sell_leg": {
                "latency_ms": 2000,
                "ticks_crossed": 50,
                "verified_for_execution": False,
            },
        }
        
        best_score, _ = calculate_confidence(best_spread)
        worst_score, _ = calculate_confidence(worst_spread)
        
        assert 0 <= best_score <= 1
        assert 0 <= worst_score <= 1
        assert best_score > worst_score
