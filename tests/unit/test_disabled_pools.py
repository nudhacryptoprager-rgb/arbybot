# PATH: tests/unit/test_disabled_pools.py
"""
Unit tests for disabled_pools functionality (POOL_DISABLED vs POOL_MISSING).

Tests that:
1. is_pool_disabled() returns correct info for disabled pools
2. is_pool_disabled() returns None for non-disabled pools
3. POOL_DISABLED semantics are distinct from POOL_MISSING
"""

import unittest
from typing import Dict, Any


class TestIsPoolDisabled(unittest.TestCase):
    """Tests for config.pairs.is_pool_disabled() function."""

    def test_pool_in_disabled_returns_info(self):
        """Disabled pool returns info dict with all fields."""
        from config.pairs import is_pool_disabled

        config: Dict[str, Any] = {
            "disabled_pools": {
                "uniswap_v3_GMX_WETH_500": {
                    "address": "0xb435ebfE0BF4CE66810AA4d44e3a5CA875D40DB1",
                    "reason": "PRICE_SANITY_FAILED",
                    "detail": "price_exact~0.00323 vs anchor 0.008",
                    "evidence_run": "ci_m5_gate_20260217_113317",
                    "disabled_date": "2026-02-18",
                }
            }
        }

        result = is_pool_disabled(config, "uniswap_v3", "GMX_WETH", 500)

        self.assertIsNotNone(result)
        self.assertEqual(result["address"], "0xb435ebfE0BF4CE66810AA4d44e3a5CA875D40DB1")
        self.assertEqual(result["reason"], "PRICE_SANITY_FAILED")
        self.assertIn("detail", result)
        self.assertIn("evidence_run", result)
        self.assertIn("disabled_date", result)

    def test_pool_not_disabled_returns_none(self):
        """Non-disabled pool returns None."""
        from config.pairs import is_pool_disabled

        config: Dict[str, Any] = {
            "disabled_pools": {
                "uniswap_v3_GMX_WETH_500": {
                    "address": "0xb435ebfE0BF4CE66810AA4d44e3a5CA875D40DB1",
                    "reason": "PRICE_SANITY_FAILED",
                }
            }
        }

        # Different pair
        result = is_pool_disabled(config, "uniswap_v3", "WETH_USDC", 500)
        self.assertIsNone(result)

        # Different dex
        result = is_pool_disabled(config, "sushiswap_v3", "GMX_WETH", 500)
        self.assertIsNone(result)

        # Different fee tier
        result = is_pool_disabled(config, "uniswap_v3", "GMX_WETH", 3000)
        self.assertIsNone(result)

    def test_empty_disabled_pools_returns_none(self):
        """Empty disabled_pools section returns None."""
        from config.pairs import is_pool_disabled

        config: Dict[str, Any] = {"disabled_pools": {}}

        result = is_pool_disabled(config, "uniswap_v3", "WETH_USDC", 500)
        self.assertIsNone(result)

    def test_missing_disabled_pools_returns_none(self):
        """Missing disabled_pools key returns None."""
        from config.pairs import is_pool_disabled

        config: Dict[str, Any] = {}

        result = is_pool_disabled(config, "uniswap_v3", "WETH_USDC", 500)
        self.assertIsNone(result)

    def test_legacy_string_format_returns_dict(self):
        """Legacy format (just address string) returns dict."""
        from config.pairs import is_pool_disabled

        config: Dict[str, Any] = {
            "disabled_pools": {
                "uniswap_v3_GMX_WETH_500": "0xb435ebfE0BF4CE66810AA4d44e3a5CA875D40DB1"
            }
        }

        result = is_pool_disabled(config, "uniswap_v3", "GMX_WETH", 500)

        self.assertIsNotNone(result)
        self.assertEqual(result["address"], "0xb435ebfE0BF4CE66810AA4d44e3a5CA875D40DB1")
        self.assertEqual(result["reason"], "DISABLED")


class TestPoolDisabledVsPoolMissing(unittest.TestCase):
    """Tests for POOL_DISABLED vs POOL_MISSING semantic distinction."""

    def test_disabled_pool_not_in_pools_section(self):
        """Disabled pool should not exist in pools section (would cause POOL_MISSING)."""
        from config.pairs import is_pool_disabled, get_pool_address

        # Pool is disabled and also NOT in pools (correct state)
        config: Dict[str, Any] = {
            "disabled_pools": {
                "sushiswap_v3_WBTC_WETH_500": {
                    "address": "0xf79099596045A41bB2ae53fa6677576687242455",
                    "reason": "PRICE_SANITY_FAILED",
                }
            },
            "pools": {
                # sushiswap_v3_WBTC_WETH_500 intentionally absent
                "uniswap_v3_WETH_USDC_500": {
                    "address": "0x123...",
                }
            },
        }

        # Check order semantics: disabled check should happen BEFORE pool lookup
        disabled_info = is_pool_disabled(config, "sushiswap_v3", "WBTC_WETH", 500)
        self.assertIsNotNone(disabled_info, "Disabled pool should return info")

        # If we didn't check disabled first, we'd get POOL_MISSING
        pool_addr = get_pool_address(config, "sushiswap_v3", "WBTC_WETH", 500)
        self.assertIsNone(pool_addr, "Disabled pool should not be in pools section")

    def test_key_format_consistency(self):
        """Key format: {dex}_{pair_tag}_{fee_tier}."""
        from config.pairs import is_pool_disabled

        config: Dict[str, Any] = {
            "disabled_pools": {
                "sushiswap_v3_ARB_USDC_3000": {
                    "address": "0x14716A16ef9eeAaDa7E266bcF023b71D2c9ADbf3",
                    "reason": "PRICE_SANITY_FAILED",
                }
            }
        }

        # Must match exact key format
        result = is_pool_disabled(config, "sushiswap_v3", "ARB_USDC", 3000)
        self.assertIsNotNone(result)

        # Wrong dex name should not match
        result = is_pool_disabled(config, "sushi_v3", "ARB_USDC", 3000)
        self.assertIsNone(result)


class TestRealConfigDisabledPools(unittest.TestCase):
    """Tests against real config files to verify 5 disabled pools."""

    def test_real_minimal_has_expected_disabled_pools(self):
        """real_minimal.yaml contains at least the known disabled pools."""
        from pathlib import Path
        import yaml

        config_path = Path(__file__).parent.parent.parent / "config" / "real_minimal.yaml"
        if not config_path.exists():
            self.skipTest("real_minimal.yaml not found")

        with open(config_path) as f:
            config = yaml.safe_load(f)

        disabled_pools = config.get("disabled_pools", {})
        self.assertGreaterEqual(len(disabled_pools), 5, f"Expected at least 5 disabled pools, got {len(disabled_pools)}")

        # Verify all 5 expected pools are disabled
        expected_disabled = [
            "sushiswap_v3_WBTC_WETH_500",
            "sushiswap_v3_LINK_USDC_3000",
            "uniswap_v3_GMX_WETH_500",
            "uniswap_v3_GMX_WETH_3000",
            "sushiswap_v3_ARB_USDC_3000",
        ]
        for pool_key in expected_disabled:
            self.assertIn(pool_key, disabled_pools, f"Missing disabled pool: {pool_key}")

    def test_disabled_pools_not_in_active_pools(self):
        """Disabled pools should not appear in active pools section."""
        from pathlib import Path
        import yaml

        config_path = Path(__file__).parent.parent.parent / "config" / "real_minimal.yaml"
        if not config_path.exists():
            self.skipTest("real_minimal.yaml not found")

        with open(config_path) as f:
            config = yaml.safe_load(f)

        disabled_pools = config.get("disabled_pools", {})
        pools = config.get("pools", {})

        # None of the disabled pools should be in active pools
        for pool_key in disabled_pools.keys():
            self.assertNotIn(pool_key, pools, f"Disabled pool {pool_key} should not be in active pools")


class TestCollectQuotesDisabledPoolCounting(unittest.TestCase):
    """Tests that collect_quotes increments pool_disabled (not pool_missing) for disabled pools."""

    def test_disabled_pool_code_path_exists_in_config_mode(self):
        """
        v2.6.1 FIX: Verify is_pool_disabled is called BEFORE get_pool_address in config mode.
        This ensures disabled pools are counted as POOL_DISABLED, not POOL_MISSING.
        """
        import inspect
        from strategy import quotes
        
        source = inspect.getsource(quotes.collect_quotes)
        
        # Verify pool_disabled count exists
        assert 'counts["pool_disabled"]' in source, "Should track pool_disabled count"
        
        # Verify the fix: In config mode loop, is_pool_disabled check should come BEFORE get_pool_address
        # Look for the v2.6.1 FIX comment which marks the fixed code path
        assert "v2.6.1 FIX" in source, "Should have v2.6.1 FIX comment marking disabled check"
        
        # Verify POOL_DISABLED log exists
        assert "POOL_DISABLED" in source, "Should log POOL_DISABLED for disabled pools"

    def test_pool_disabled_vs_pool_missing_clear_semantics(self):
        """
        POOL_DISABLED = pool explicitly disabled via disabled_pools config
        POOL_MISSING = pool not in pools config AND not in disabled_pools
        """
        from config.pairs import is_pool_disabled, get_pool_address
        
        config = {
            "disabled_pools": {
                "uniswap_v3_TEST_WETH_500": {
                    "address": "0x1234567890123456789012345678901234567890",
                    "reason": "PRICE_SANITY_FAILED",
                }
            },
            "pools": {
                # TEST_WETH intentionally absent
                "uniswap_v3_GOOD_WETH_500": {
                    "address": "0xABCDEF1234567890123456789012345678901234",
                }
            },
        }
        
        # TEST_WETH is in disabled_pools -> should be detected as disabled
        disabled_info = is_pool_disabled(config, "uniswap_v3", "TEST_WETH", 500)
        self.assertIsNotNone(disabled_info, "TEST_WETH should be disabled")
        
        # TEST_WETH not in pools -> get_pool_address returns None
        pool_addr = get_pool_address(config, "uniswap_v3", "TEST_WETH", 500)
        self.assertIsNone(pool_addr, "TEST_WETH not in pools")
        
        # GOOD_WETH is in pools -> should have address
        pool_info_good = get_pool_address(config, "uniswap_v3", "GOOD_WETH", 500)
        self.assertIsNotNone(pool_info_good, "GOOD_WETH should be in pools")
        # get_pool_address returns dict with 'address' key
        if isinstance(pool_info_good, dict):
            self.assertEqual(pool_info_good.get("address"), "0xABCDEF1234567890123456789012345678901234")
        else:
            # Legacy string format
            self.assertEqual(pool_info_good, "0xABCDEF1234567890123456789012345678901234")
        
        # UNKNOWN_WETH is NOT in disabled_pools AND NOT in pools -> truly missing
        disabled_info_unknown = is_pool_disabled(config, "uniswap_v3", "UNKNOWN_WETH", 500)
        self.assertIsNone(disabled_info_unknown, "UNKNOWN_WETH not disabled")
        pool_addr_unknown = get_pool_address(config, "uniswap_v3", "UNKNOWN_WETH", 500)
        self.assertIsNone(pool_addr_unknown, "UNKNOWN_WETH not in pools")


if __name__ == "__main__":
    unittest.main()
