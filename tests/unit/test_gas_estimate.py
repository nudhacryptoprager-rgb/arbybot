# PATH: tests/unit/test_gas_estimate.py
"""
Tests for execution/gas_estimate.py

v2.1.0-fix: ABI encoding, contract consistency
"""

import pytest
from execution.gas_estimate import (
    build_exact_input_single_calldata,
    estimate_roundtrip_gas,
    get_router_address,
    validate_gas_headroom,
    DEFAULT_V3_SWAP_GAS,
)


class TestBuildExactInputSingleCalldata:
    """Tests for exactInputSingle ABI encoding."""

    def test_calldata_starts_with_selector(self):
        """Calldata should start with exactInputSingle selector."""
        calldata = build_exact_input_single_calldata(
            token_in="0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",  # WETH
            token_out="0xaf88d065e77c8cC2239327C5EDb3A432268e5831",  # USDC
            fee=3000,
            recipient="0x0000000000000000000000000000000000000001",
            amount_in=10**18,
        )
        
        # exactInputSingle selector: 0x414bf389
        assert calldata[:4] == bytes.fromhex("414bf389")

    def test_calldata_length(self):
        """Calldata should be 4 (selector) + 8*32 (params) = 260 bytes."""
        calldata = build_exact_input_single_calldata(
            token_in="0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
            token_out="0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
            fee=3000,
            recipient="0x0000000000000000000000000000000000000001",
            amount_in=10**18,
        )
        
        # 4 bytes selector + 8 * 32 bytes params = 260 bytes
        assert len(calldata) == 4 + 8 * 32

    def test_token_addresses_encoded_correctly(self):
        """Token addresses should be ABI-encoded in calldata."""
        token_in = "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1"
        token_out = "0xaf88d065e77c8cC2239327C5EDb3A432268e5831"
        
        calldata = build_exact_input_single_calldata(
            token_in=token_in,
            token_out=token_out,
            fee=3000,
            recipient="0x0000000000000000000000000000000000000001",
            amount_in=10**18,
        )
        
        # Extract first param (tokenIn) - bytes 4:36
        token_in_encoded = calldata[4:36]
        # Should be left-padded with zeros
        assert token_in_encoded[-20:].hex() == token_in.lower()[2:]

    def test_fee_encoded_correctly(self):
        """Fee should be ABI-encoded as uint24 in 32 bytes."""
        calldata = build_exact_input_single_calldata(
            token_in="0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
            token_out="0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
            fee=3000,
            recipient="0x0000000000000000000000000000000000000001",
            amount_in=10**18,
        )
        
        # Fee is 3rd param (bytes 68:100)
        fee_encoded = calldata[68:100]
        fee_value = int.from_bytes(fee_encoded, "big")
        assert fee_value == 3000

    def test_amount_in_encoded_correctly(self):
        """amount_in should be correctly encoded."""
        amount_in = 10**18
        
        calldata = build_exact_input_single_calldata(
            token_in="0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
            token_out="0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
            fee=3000,
            recipient="0x0000000000000000000000000000000000000001",
            amount_in=amount_in,
        )
        
        # amountIn is 6th param (bytes 164:196)
        amount_encoded = calldata[164:196]
        amount_value = int.from_bytes(amount_encoded, "big")
        assert amount_value == amount_in


class TestEstimateRoundtripGas:
    """Tests for estimate_roundtrip_gas return contract."""

    def test_returns_leg1_leg2_source(self):
        """Should return (leg1_gas, leg2_gas, source) tuple."""
        # Mock w3 with failing estimate_gas
        class MockW3:
            class eth:
                @staticmethod
                def estimate_gas(params):
                    raise Exception("No RPC")
                
                @staticmethod
                def to_checksum_address(addr):
                    return addr
            
            @staticmethod
            def to_checksum_address(addr):
                return addr
        
        w3 = MockW3()
        
        result = estimate_roundtrip_gas(
            w3,
            leg1_calldata=b"\x00" * 100,
            leg1_router="0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45",
            leg2_calldata=b"\x00" * 100,
            leg2_router="0x8A21F6768C1f8075791D08546Dadf6daA0bE820c",
            sender_address="0x0000000000000000000000000000000000000001",
        )
        
        # Should be 3-tuple
        assert len(result) == 3
        leg1_gas, leg2_gas, source = result
        
        # Should fall back to default
        assert leg1_gas == DEFAULT_V3_SWAP_GAS
        assert leg2_gas == DEFAULT_V3_SWAP_GAS
        assert source == "default"


class TestGetRouterAddress:
    """Tests for get_router_address."""

    def test_uniswap_v3_router(self):
        """Should return Uniswap V3 SwapRouter02."""
        router = get_router_address("uniswap_v3", 42161)
        assert router == "0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45"

    def test_sushiswap_v3_router(self):
        """Should return SushiSwap V3 router."""
        router = get_router_address("sushiswap_v3", 42161)
        assert router == "0x8A21F6768C1f8075791D08546Dadf6daA0bE820c"

    def test_unknown_dex_returns_none(self):
        """Unknown DEX should return None."""
        router = get_router_address("unknown_dex", 42161)
        assert router is None


class TestValidateGasHeadroom:
    """Tests for validate_gas_headroom."""

    def test_valid_headroom(self):
        """Should pass when headroom is sufficient."""
        is_valid, msg = validate_gas_headroom(150_000, 200_000, 0.1)
        assert is_valid is True
        assert "OK" in msg

    def test_over_limit(self):
        """Should fail when estimate exceeds limit."""
        is_valid, msg = validate_gas_headroom(250_000, 200_000, 0.1)
        assert is_valid is False
        assert "OVER_LIMIT" in msg

    def test_low_headroom(self):
        """Should fail when headroom is too low."""
        is_valid, msg = validate_gas_headroom(195_000, 200_000, 0.1)
        assert is_valid is False
        assert "LOW_HEADROOM" in msg
