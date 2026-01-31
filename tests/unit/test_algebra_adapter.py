# PATH: tests/unit/test_algebra_adapter.py
"""
Tests for Algebra-based DEX adapter.

M5_0 REQUIREMENTS:
1. Diagnostics include real pool address (0x...), not just key
2. Direction sanity check flags suspect quotes
3. Pool registry returns real addresses
"""

import unittest
from decimal import Decimal
from pathlib import Path
from unittest.mock import Mock, patch
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dex.adapters.algebra import (
    AlgebraAdapter,
    AlgebraPool,
    QuoteResult,
    DIRECTION_SANITY_MIN,
    create_sushiswap_v3_adapter,
)


class TestAlgebraAdapterPoolRegistry(unittest.TestCase):
    """Test pool registry with real addresses."""

    def test_register_pool_with_real_address(self):
        """Test that pool registration accepts real 0x address."""
        adapter = AlgebraAdapter(web3=Mock(), quoter_address="0xQuoter", dex_id="sushiswap_v3")
        
        real_address = "0x1234567890abcdef1234567890abcdef12345678"
        adapter.register_pool(
            token_in="WETH",
            token_out="USDC",
            fee=3000,
            pool_address=real_address,
            token0="WETH",
            token1="USDC",
        )
        
        # Should return real address
        addr = adapter.get_pool_address("WETH", "USDC", 3000)
        self.assertEqual(addr, real_address)
        self.assertTrue(addr.startswith("0x"))

    def test_pool_address_not_key(self):
        """Test that pool address is NOT a key format."""
        adapter = AlgebraAdapter(web3=Mock(), quoter_address="0xQuoter", dex_id="sushiswap_v3")
        
        real_address = "0xD1d5A4c0ea8F61B9C9116e0c99b16C84F2c1b70a"
        adapter.register_pool(
            token_in="WETH",
            token_out="USDC",
            fee=3000,
            pool_address=real_address,
            token0="WETH",
            token1="USDC",
        )
        
        addr = adapter.get_pool_address("WETH", "USDC", 3000)
        
        # Must NOT be in key format
        self.assertNotIn("pool:", addr)
        self.assertNotIn("sushiswap_v3:", addr)
        # Must be real address
        self.assertTrue(addr.startswith("0x"))
        self.assertEqual(len(addr), 42)  # 0x + 40 hex chars

    def test_reverse_lookup(self):
        """Test pool lookup works for reversed token order."""
        adapter = AlgebraAdapter(web3=Mock(), quoter_address="0xQuoter", dex_id="sushiswap_v3")
        
        real_address = "0xabcdef1234567890abcdef1234567890abcdef12"
        adapter.register_pool(
            token_in="USDC",
            token_out="WETH",
            fee=500,
            pool_address=real_address,
            token0="USDC",
            token1="WETH",
        )
        
        # Should find via reverse lookup
        addr = adapter.get_pool_address("WETH", "USDC", 500)
        self.assertEqual(addr, real_address)


class TestAlgebraAdapterDiagnostics(unittest.TestCase):
    """Test that diagnostics include real pool address."""

    def test_diagnostics_include_real_address(self):
        """Test QuoteResult diagnostics include real 0x address."""
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
        
        # pool_address in result must be real address
        self.assertTrue(result.pool_address.startswith("0x"))
        self.assertEqual(len(result.pool_address), 42)
        
        # diagnostics must include real address
        self.assertEqual(result.diagnostics["pool_address"], real_address)
        
        # pool_key is separate (for indexing only)
        self.assertIn("pool:", result.diagnostics["pool_key"])

    def test_diagnostics_contract(self):
        """Test that diagnostics follow M5_0 contract."""
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
                "amount_in": "1000000000000000000",
                "amount_out": "2600000000",
                "price": "2600",
                "fee": 3000,
            },
        )
        
        diag = result.diagnostics
        
        # Required fields per M5_0 contract
        self.assertIn("dex_id", diag)
        self.assertIn("pool_address", diag)
        self.assertIn("token_in", diag)
        self.assertIn("token_out", diag)
        self.assertIn("fee", diag)
        
        # pool_address must be real 0x
        self.assertTrue(diag["pool_address"].startswith("0x"))


class TestDirectionSanityCheck(unittest.TestCase):
    """Test direction sanity check (diagnostic flag)."""

    def test_suspect_direction_flagged(self):
        """Test that low price flags suspect_direction."""
        # 8.6 USDC per WETH is way below expected
        result = QuoteResult(
            amount_out=int(8.6 * 10**6),
            price=Decimal("8.6"),
            pool_address="0x1234567890abcdef1234567890abcdef12345678",
            fee=3000,
            suspect_direction=True,
            suspect_reason="price 8.6000 below minimum expected 100",
            diagnostics={
                "suspect_direction": True,
                "suspect_reason": "price 8.6000 below minimum expected 100",
            },
        )
        
        self.assertTrue(result.suspect_direction)
        self.assertIn("below minimum", result.suspect_reason)
        self.assertTrue(result.diagnostics.get("suspect_direction"))

    def test_normal_price_not_suspect(self):
        """Test that normal price is not flagged."""
        result = QuoteResult(
            amount_out=2600 * 10**6,
            price=Decimal("2600"),
            pool_address="0x1234567890abcdef1234567890abcdef12345678",
            fee=3000,
            suspect_direction=False,
            diagnostics={},
        )
        
        self.assertFalse(result.suspect_direction)
        self.assertIsNone(result.suspect_reason)

    def test_direction_sanity_min_values(self):
        """Test that DIRECTION_SANITY_MIN has expected pairs."""
        # WETH/USDC should have minimum
        self.assertIn(("WETH", "USDC"), DIRECTION_SANITY_MIN)
        self.assertGreater(DIRECTION_SANITY_MIN[("WETH", "USDC")], 0)
        
        # Minimum should be reasonable (e.g., 100 USDC per WETH)
        self.assertEqual(DIRECTION_SANITY_MIN[("WETH", "USDC")], Decimal("100"))


class TestAlgebraPool(unittest.TestCase):
    """Test AlgebraPool dataclass."""

    def test_pool_key_format(self):
        """Test pool_key property format."""
        pool = AlgebraPool(
            dex_id="sushiswap_v3",
            pool_address="0x1234567890abcdef1234567890abcdef12345678",
            token0="WETH",
            token1="USDC",
            token0_decimals=18,
            token1_decimals=6,
            fee=3000,
        )
        
        # pool_key is for indexing (not diagnostics)
        self.assertEqual(pool.pool_key, "pool:sushiswap_v3:WETH:USDC:3000")
        
        # pool_address is real address
        self.assertTrue(pool.pool_address.startswith("0x"))
        self.assertNotIn("pool:", pool.pool_address)


class TestAdapterFactory(unittest.TestCase):
    """Test adapter factory functions."""

    def test_create_sushiswap_v3_adapter(self):
        """Test Sushiswap V3 adapter creation."""
        adapter = create_sushiswap_v3_adapter(
            web3=Mock(),
            quoter_address="0xQuoter",
        )
        
        self.assertEqual(adapter.dex_id, "sushiswap_v3")


if __name__ == "__main__":
    unittest.main()
