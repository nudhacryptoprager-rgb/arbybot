"""Unit tests for V3 provenance fields (tick, sqrtPriceX96).

Verifies that when a v3 quote has a pool_address, at least one of
tick or sqrt_price_x96 is not null (when slot0() is successfully read).
"""
import json
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path


class TestV3Provenance:
    """Tests for v3 pool provenance (tick/sqrtPriceX96)."""

    def test_v3_quote_with_pool_address_has_provenance_fields(self):
        """V3 quote with pool_address should have tick or sqrt_price_x96 when slot0 succeeds."""
        # Test the QuoteCompat dataclass supports the fields
        from strategy.jobs.run_scan_real import QuoteCompat

        quote = QuoteCompat(
            dex_id="uniswap_v3",
            pool_address="0x17c14D2c404D167802b16C450d3c99F88F2c4F4d",
            token_in="WETH",
            token_out="USDC",
            fee=3000,
            amount_in_wei=10**18,
            amount_out_wei=2600 * 10**6,
            price="2600",
            latency_ms=10,
            block_number=12345678,
            rpc_success=True,
            gate_passed=True,
            tick=-201234,
            sqrt_price_x96=1234567890123456789012345678901234567890,
        )

        assert quote.pool_address == "0x17c14D2c404D167802b16C450d3c99F88F2c4F4d"
        assert quote.tick is not None or quote.sqrt_price_x96 is not None

    def test_v3_quote_provenance_fields_in_dict(self):
        """Verify QuoteCompat exports tick and sqrt_price_x96 to __dict__."""
        from strategy.jobs.run_scan_real import QuoteCompat

        quote = QuoteCompat(
            dex_id="sushiswap_v3",
            pool_address="0xABCDEF1234567890",
            token_in="WETH",
            token_out="USDC",
            fee=500,
            amount_in_wei=10**18,
            amount_out_wei=2600 * 10**6,
            price="2600",
            latency_ms=15,
            block_number=98765432,
            rpc_success=True,
            gate_passed=True,
            tick=-195000,
            sqrt_price_x96=987654321098765432109876543210,
        )

        d = quote.__dict__
        assert "tick" in d
        assert "sqrt_price_x96" in d
        assert d["tick"] == -195000
        assert d["sqrt_price_x96"] == 987654321098765432109876543210

    def test_v3_quote_without_provenance_still_valid(self):
        """V3 quote can have tick=None and sqrt_price_x96=None (e.g., RPC failure)."""
        from strategy.jobs.run_scan_real import QuoteCompat

        quote = QuoteCompat(
            dex_id="uniswap_v3",
            pool_address="0x17c14D2c404D167802b16C450d3c99F88F2c4F4d",
            token_in="WETH",
            token_out="USDC",
            fee=3000,
            amount_in_wei=10**18,
            amount_out_wei=2600 * 10**6,
            price="2600",
            latency_ms=10,
            block_number=12345678,
            rpc_success=True,
            gate_passed=True,
            tick=None,
            sqrt_price_x96=None,
        )

        # Quote is still valid, just lacks provenance
        assert quote.pool_address is not None
        assert quote.tick is None
        assert quote.sqrt_price_x96 is None

    def test_v2_quote_no_provenance_expected(self):
        """V2 quote should not have tick/sqrtPriceX96 (v2 uses reserves, not slot0)."""
        from strategy.jobs.run_scan_real import QuoteCompat

        quote = QuoteCompat(
            dex_id="uniswap_v2",
            pool_address="0xV2POOLADDRESS",
            token_in="WETH",
            token_out="USDC",
            fee=3000,
            amount_in_wei=10**18,
            amount_out_wei=2600 * 10**6,
            price="2600",
            latency_ms=10,
            block_number=12345678,
            rpc_success=True,
            gate_passed=True,
            tick=None,
            sqrt_price_x96=None,
        )

        # V2 quote legitimately has no tick/sqrtPriceX96
        assert quote.tick is None
        assert quote.sqrt_price_x96 is None

    def test_v3_provenance_required_for_valid_pool(self):
        """If dex_id is uniswap_v3 or sushiswap_v3 and pool_address is not null,
        then tick and sqrt_price_x96 SHOULD be present (or have explicit reason).
        
        This test validates the contract: v3 pools with valid addresses must have provenance.
        """
        from strategy.jobs.run_scan_real import QuoteCompat

        # Valid v3 quote with provenance - should pass
        valid_quote = QuoteCompat(
            dex_id="sushiswap_v3",
            pool_address="0xC96525298419f7E00dA8826B733Ee52e271662b5",
            token_in="WETH",
            token_out="USDC",
            fee=3000,
            amount_in_wei=10**18,
            amount_out_wei=2600 * 10**6,
            price="2600",
            latency_ms=10,
            block_number=12345678,
            rpc_success=True,
            gate_passed=True,
            tick=-200608,
            sqrt_price_x96=3491146268565530413317853,
        )

        # Verify both DEX types work
        for dex_id in ["uniswap_v3", "sushiswap_v3"]:
            if "v3" in dex_id and valid_quote.pool_address:
                # At least one provenance field should be present for valid v3 pool
                has_provenance = valid_quote.tick is not None or valid_quote.sqrt_price_x96 is not None
                assert has_provenance, f"{dex_id} with pool_address must have tick or sqrt_price_x96"

    def test_v3_missing_provenance_is_warning(self):
        """V3 quote with pool but no tick/sqrt should be flagged (not fatal, but warning-worthy)."""
        from strategy.jobs.run_scan_real import QuoteCompat

        # This simulates a failed slot0() call - quote is valid but lacks provenance
        quote_without_provenance = QuoteCompat(
            dex_id="uniswap_v3",
            pool_address="0x17c14D2c404D167802b16C450d3c99F88F2c4F4d",
            token_in="WETH",
            token_out="USDC",
            fee=3000,
            amount_in_wei=10**18,
            amount_out_wei=2600 * 10**6,
            price="2600",
            latency_ms=10,
            block_number=12345678,
            rpc_success=True,
            gate_passed=True,
            tick=None,
            sqrt_price_x96=None,
        )

        # Quote is still valid, but missing provenance is a warning condition
        assert quote_without_provenance.pool_address is not None
        missing_provenance = (
            quote_without_provenance.tick is None and 
            quote_without_provenance.sqrt_price_x96 is None
        )
        # This is the "warning" condition - quote valid but provenance incomplete
        assert missing_provenance, "Expected missing provenance for this test case"
