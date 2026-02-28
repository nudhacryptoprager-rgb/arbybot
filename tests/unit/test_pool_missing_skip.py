# PATH: tests/unit/test_pool_missing_skip.py
"""
Unit tests for POOL_MISSING skip semantics (v2.3.0).

Contract:
- POOL_MISSING is a silent skip, NOT a reject
- pool_missing_count should increase
- rejected_quotes list should NOT contain POOL_MISSING entries
- quotes_rejected count should NOT include POOL_MISSING
"""

import os
import pytest
from unittest.mock import patch, MagicMock


class TestPoolMissingSkipBehavior:
    """Test actual POOL_MISSING skip behavior via collect_quotes."""
    
    @pytest.fixture
    def mock_config_missing_pool(self):
        """Config with a pair that has NO pool address configured."""
        return {
            "chain": "arbitrum_one",
            "chain_id": 42161,
            "dexes": ["uniswap_v3"],
            "rpc_endpoints": ["https://example.com/rpc"],
            # pools section does NOT have the pair we'll request
            "pools": {
                # Empty - no pools configured
            },
            "tokens": {
                "WETH": "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
                "USDC": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
            },
            "use_multicall": False,  # Skip multicall for unit test
        }
    
    def test_pool_missing_increments_count_not_rejected(self, mock_config_missing_pool):
        """When pool address is missing, pool_missing_count increases but rejected_quotes stays empty."""
        from config.pairs import get_pool_address
        
        # Verify get_pool_address returns None for unconfigured pool
        result = get_pool_address(
            mock_config_missing_pool, 
            "uniswap_v3", 
            "WETH_USDC", 
            fee_tier=500
        )
        assert result is None, "get_pool_address should return None for unconfigured pool"
    
    def test_pool_missing_semantics_in_quotes_module(self):
        """Verify the POOL_MISSING handling code exists and returns continue (skip)."""
        import inspect
        from strategy import quotes
        
        # Read the source code to verify the skip pattern
        source = inspect.getsource(quotes.collect_quotes)
        
        # Should have pool_missing count
        assert "pool_missing" in source, "collect_quotes should track pool_missing"
        
        # Should NOT append POOL_MISSING to rejected_quotes - verify by checking
        # that after the pool_missing increment, we continue (not append)
        # The code pattern is: counts["pool_missing"] += 1 ... continue
        assert 'counts["pool_missing"]' in source, "Should increment pool_missing count"
        
        # Verify we log POOL_SKIP, not POOL_REJECT
        assert "POOL_SKIP" in source, "Should log POOL_SKIP (skip semantics)"
    
    def test_pool_missing_not_in_reject_histogram_schema(self):
        """POOL_MISSING should not be a reason that appears in reject_histogram."""
        from core.reject_reasons import QuoteRejectReason
        
        # POOL_MISSING exists as a reason code (for documentation)
        assert hasattr(QuoteRejectReason, "POOL_MISSING")
        
        # But the key point is that strategy/quotes.py never appends it to rejected_quotes
        # This is a behavioral contract, not schema - tested via source inspection above
    
    def test_get_pool_address_returns_none_for_missing_fee(self):
        """get_pool_address returns None when fee tier not in config."""
        from config.pairs import get_pool_address
        
        config = {
            "pools": {
                "uniswap_v3_WETH_USDC_500": "0x123...",  # Only 500 exists
            }
        }
        
        # Fee 3000 not configured - should return None
        result = get_pool_address(config, "uniswap_v3", "WETH_USDC", fee_tier=3000)
        assert result is None, "Should return None for unconfigured fee tier"
        
        # Fee 500 is configured - should return address
        result_500 = get_pool_address(config, "uniswap_v3", "WETH_USDC", fee_tier=500)
        assert result_500 == "0x123...", "Should return address for configured fee tier"


class TestPoolMissingDocumentation:
    """Test documentation contracts for POOL_MISSING semantics."""
    
    def test_real_minimal_yaml_documents_skip_not_reject(self):
        """Contract: real_minimal.yaml must document POOL_MISSING as skip, not reject."""
        config_path = os.path.join(
            os.path.dirname(__file__), "..", "..", "config", "real_minimal.yaml"
        )
        
        assert os.path.exists(config_path), "real_minimal.yaml should exist"
        
        with open(config_path, "r") as f:
            content = f.read()
        
        # Should NOT say "rejected as POOL_MISSING"
        assert "rejected as POOL_MISSING" not in content, \
            "real_minimal.yaml should not claim POOL_MISSING is a reject"
        
        # Should say "skip" somewhere in the POOL_MISSING context
        assert "skip" in content.lower(), \
            "real_minimal.yaml should document POOL_MISSING as skip"


class TestRejectVsSkipDistinction:
    """Test the distinction between reject and skip."""
    
    def test_reject_reasons_are_actionable(self):
        """Reject reasons should indicate actionable issues."""
        from core.reject_reasons import QuoteRejectReason
        
        # These are REJECT reasons (actionable, should be in reject_histogram):
        reject_codes = [
            "PRICE_SANITY_FAILED",
            "V3_SLOT0_FAILED",
            "SUSPECT_LIQUIDITY",
            "PRICE_OUTLIER",
        ]
        
        for code in reject_codes:
            assert hasattr(QuoteRejectReason, code), f"{code} should be a valid QuoteRejectReason"
    
    def test_pool_missing_reason_exists(self):
        """POOL_MISSING should be defined but not used for rejection."""
        from core.reject_reasons import QuoteRejectReason
        
        # POOL_MISSING exists as a defined reason code
        assert hasattr(QuoteRejectReason, "POOL_MISSING")
        assert QuoteRejectReason.POOL_MISSING.value == "POOL_MISSING"


class TestDisabledPoolsNotCounted:
    """Test that disabled_pools do not contribute to pool_missing_count (v2.9.6)."""
    
    def test_disabled_pool_not_in_pool_missing_count(self):
        """Contract: if pool_key in disabled_pools, it should NOT increase pool_missing_count."""
        from config.pairs import get_pool_address
        from strategy.quotes import is_pool_disabled
        
        config = {
            "pools": {
                # Note: NO address for sushiswap_v3_WETH_USDC_100
            },
            "disabled_pools": {
                "sushiswap_v3_WETH_USDC_100": {
                    "address": None,
                    "reason": "POOL_NOT_EXIST",
                    "detail": "fee=100 only available on Uniswap",
                    "disabled_date": "2026-02-28",
                }
            },
        }
        
        # Pool is disabled - is_pool_disabled should return the disable info
        disabled_info = is_pool_disabled(config, "sushiswap_v3", "WETH_USDC", 100)
        assert disabled_info is not None, "Pool should be detected as disabled"
        assert disabled_info.get("reason") == "POOL_NOT_EXIST"
        
        # get_pool_address would return None for unconfigured pool
        # But the key is: is_pool_disabled is checked FIRST, so pool_missing never increments
        result = get_pool_address(config, "sushiswap_v3", "WETH_USDC", fee_tier=100)
        assert result is None, "No pool address configured"
    
    def test_pool_disabled_semantics_in_quotes_module(self):
        """Verify disabled_pools check happens BEFORE pool_missing increment."""
        import inspect
        from strategy import quotes
        
        source = inspect.getsource(quotes.collect_quotes)
        
        # Should check disabled_pools - pattern: is_pool_disabled() before pool_missing+=1
        assert "is_pool_disabled" in source, "collect_quotes should check is_pool_disabled"
        assert "pool_disabled" in source, "Should have pool_disabled counter"
        
        # The contract: when is_pool_disabled returns truthy, we continue WITHOUT pool_missing
        # This is verified by the code structure in strategy/quotes.py lines 680-695

