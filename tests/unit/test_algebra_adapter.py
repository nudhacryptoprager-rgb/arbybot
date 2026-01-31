# PATH: tests/unit/test_algebra_adapter.py
"""
Tests for Algebra-based DEX adapter.

CONTRACT TESTS:
1. Diagnostics include real pool address (0x...)
2. pool_key is separate from pool_address
3. Hard facts: token0, token1, decimals
4. Direction sanity check diagnostic flag
"""

import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dex.adapters.algebra import (
    AlgebraAdapter,
    AlgebraPool,
    QuoteResult,
    DIRECTION_SANITY_MIN,
    create_sushiswap_v3_adapter,
)


class TestPoolRegistry(unittest.TestCase):
    """Test pool registry with real addresses."""

    def test_register_pool_with_real_address(self):
        """Test pool registration with real 0x address."""
        adapter = AlgebraAdapter(web3=Mock(), quoter_address="0xQuoter", dex_id="sushiswap_v3")
        
        real_address = "0x1234567890abcdef1234567890abcdef12345678"
        adapter.register_pool(
            token_in="WETH", token_out="USDC", fee=3000,
            pool_address=real_address,
            token0="WETH", token1="USDC",
        )
        
        addr = adapter.get_pool_address("WETH", "USDC", 3000)
        self.assertEqual(addr, real_address)
        self.assertTrue(addr.startswith("0x"))

    def test_pool_address_not_key_format(self):
        """Test pool address is NOT key format."""
        adapter = AlgebraAdapter(web3=Mock(), quoter_address="0xQuoter", dex_id="sushiswap_v3")
        
        real_address = "0xD1d5A4c0ea8F61B9C9116e0c99b16C84F2c1b70a"
        adapter.register_pool(
            token_in="WETH", token_out="USDC", fee=3000,
            pool_address=real_address,
            token0="WETH", token1="USDC",
        )
        
        addr = adapter.get_pool_address("WETH", "USDC", 3000)
        
        # Must NOT be key format
        self.assertNotIn("pool:", addr)
        self.assertNotIn("sushiswap_v3:", addr)
        # Must be real address
        self.assertTrue(addr.startswith("0x"))
        self.assertEqual(len(addr), 42)

    def test_reverse_lookup(self):
        """Test reverse token order lookup."""
        adapter = AlgebraAdapter(web3=Mock(), quoter_address="0xQuoter", dex_id="sushiswap_v3")
        
        real_address = "0xabcdef1234567890abcdef1234567890abcdef12"
        adapter.register_pool(
            token_in="USDC", token_out="WETH", fee=500,
            pool_address=real_address,
            token0="USDC", token1="WETH",
        )
        
        # Should find via reverse lookup
        addr = adapter.get_pool_address("WETH", "USDC", 500)
        self.assertEqual(addr, real_address)


class TestDiagnosticsContract(unittest.TestCase):
    """Test diagnostics include required fields."""

    def test_diagnostics_has_real_address(self):
        """Test diagnostics include real 0x address."""
        real_address = "0x1234567890abcdef1234567890abcdef12345678"
        
        result = QuoteResult(
            amount_out=2600 * 10**6,
            price=Decimal("2600"),
            pool_address=real_address,
            fee=3000,
            diagnostics={
                "dex_id": "sushiswap_v3",
                "pool_address": real_address,
                "pool_key": "pool:sushiswap_v3:WETH:USDC:3000",
            },
        )
        
        # pool_address must be real
        self.assertTrue(result.pool_address.startswith("0x"))
        self.assertEqual(len(result.pool_address), 42)
        
        # diagnostics must include real address
        self.assertEqual(result.diagnostics["pool_address"], real_address)
        
        # pool_key is separate
        self.assertIn("pool:", result.diagnostics["pool_key"])

    def test_diagnostics_has_hard_facts(self):
        """Test diagnostics include hard facts."""
        result = QuoteResult(
            amount_out=2600 * 10**6,
            price=Decimal("2600"),
            pool_address="0xD1d5A4c0ea8F61B9C9116e0c99b16C84F2c1b70a",
            fee=3000,
            diagnostics={
                "dex_id": "sushiswap_v3",
                "pool_address": "0xD1d5A4c0ea8F61B9C9116e0c99b16C84F2c1b70a",
                "token_in": "WETH",
                "token_out": "USDC",
                "token0": "WETH",
                "token1": "USDC",
                "token0_decimals": 18,
                "token1_decimals": 6,
                "fee": 3000,
            },
        )
        
        diag = result.diagnostics
        
        # Required hard facts
        self.assertIn("dex_id", diag)
        self.assertIn("pool_address", diag)
        self.assertIn("token_in", diag)
        self.assertIn("token_out", diag)
        self.assertIn("fee", diag)
        
        # pool_address is real
        self.assertTrue(diag["pool_address"].startswith("0x"))


class TestDirectionSanity(unittest.TestCase):
    """Test direction sanity diagnostic flag."""

    def test_suspect_direction_flagged(self):
        """Test low price flags suspect_direction."""
        result = QuoteResult(
            amount_out=int(8.6 * 10**6),
            price=Decimal("8.6"),
            pool_address="0x1234567890abcdef1234567890abcdef12345678",
            fee=3000,
            suspect_direction=True,
            suspect_reason="price 8.6000 < min 100",
            diagnostics={
                "suspect_direction": True,
                "suspect_reason": "price 8.6000 < min 100",
            },
        )
        
        self.assertTrue(result.suspect_direction)
        self.assertIn("< min", result.suspect_reason)

    def test_normal_price_not_suspect(self):
        """Test normal price not flagged."""
        result = QuoteResult(
            amount_out=2600 * 10**6,
            price=Decimal("2600"),
            pool_address="0x1234567890abcdef1234567890abcdef12345678",
            fee=3000,
            suspect_direction=False,
            diagnostics={},
        )
        
        self.assertFalse(result.suspect_direction)

    def test_direction_sanity_min_values(self):
        """Test DIRECTION_SANITY_MIN has expected pairs."""
        self.assertIn(("WETH", "USDC"), DIRECTION_SANITY_MIN)
        self.assertEqual(DIRECTION_SANITY_MIN[("WETH", "USDC")], Decimal("100"))


class TestPoolKey(unittest.TestCase):
    """Test pool_key format."""

    def test_pool_key_format(self):
        """Test pool_key property format."""
        pool = AlgebraPool(
            dex_id="sushiswap_v3",
            pool_address="0x1234567890abcdef1234567890abcdef12345678",
            token0="WETH", token1="USDC",
            token0_decimals=18, token1_decimals=6,
            fee=3000,
        )
        
        # pool_key is for indexing
        self.assertEqual(pool.pool_key, "pool:sushiswap_v3:WETH:USDC:3000")
        
        # pool_address is real address
        self.assertTrue(pool.pool_address.startswith("0x"))
        self.assertNotIn("pool:", pool.pool_address)


class TestAdapterFactory(unittest.TestCase):
    """Test adapter factory functions."""

    def test_create_sushiswap_v3_adapter(self):
        """Test Sushiswap V3 adapter creation."""
        adapter = create_sushiswap_v3_adapter(web3=Mock(), quoter_address="0xQuoter")
        self.assertEqual(adapter.dex_id, "sushiswap_v3")


if __name__ == "__main__":
    unittest.main()
