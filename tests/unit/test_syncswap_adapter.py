"""
Unit tests for dex/adapters/syncswap.py.

Tests:
- ABI encoding for getAmountOut(address, uint256, address)
- Decoding getAmountOut response (single uint256)
- Adapter registration in registry
- Adapter interface: get_quote, supports_fee_tiers
- Error handling (empty response, short response, missing pool_address)
"""

import pytest
from unittest.mock import Mock

from dex.adapters.syncswap import (
    SyncSwapAdapter,
    encode_get_amount_out,
    decode_get_amount_out,
    SELECTOR_GET_AMOUNT_OUT,
    ZERO_ADDRESS,
)
from core.exceptions import QuoteError


class TestEncoding:
    """ABI encoding for getAmountOut(address tokenIn, uint256 amountIn, address sender)."""

    def test_selector_value(self):
        """getAmountOut(address,uint256,address) selector is 0x18a13086."""
        assert SELECTOR_GET_AMOUNT_OUT == "0x18a13086"

    def test_encode_basic(self):
        """Encode with known token and amount."""
        token_in = "0xdAC17F958D2ee523a2206206994597C13D831ec7"
        amount_in = 1_000_000  # 1 USDT (6 dec)

        result = encode_get_amount_out(token_in, amount_in)

        # Starts with selector (without 0x)
        assert result.startswith("18a13086")
        # Total length: 8 (selector) + 3 * 64 (three params) = 200
        assert len(result) == 200

    def test_encode_includes_token_padded(self):
        """Token address is left-padded to 32 bytes."""
        token_in = "0xff00ff00ff00ff00ff00ff00ff00ff00ff00ff00"
        result = encode_get_amount_out(token_in, 0)

        # Token starts after selector (pos 8), left-padded with 24 zeros
        token_segment = result[8 : 8 + 64]
        assert token_segment == "000000000000000000000000ff00ff00ff00ff00ff00ff00ff00ff00ff00ff00"

    def test_encode_amount_field(self):
        """Amount is hex-encoded as uint256."""
        amount_in = 0xDEADBEEF
        result = encode_get_amount_out(
            "0x0000000000000000000000000000000000000001", amount_in
        )
        # Amount field: selector(8) + token(64) = starts at 72
        amount_segment = result[72 : 72 + 64]
        assert int(amount_segment, 16) == 0xDEADBEEF

    def test_encode_default_sender_is_zero(self):
        """Default sender is zero address."""
        result = encode_get_amount_out(
            "0x0000000000000000000000000000000000000001", 1
        )
        # Sender field: selector(8) + token(64) + amount(64) = starts at 136
        sender_segment = result[136:]
        assert int(sender_segment, 16) == 0

    def test_encode_custom_sender(self):
        """Custom sender is encoded correctly."""
        sender = "0x000000000000000000000000000000000000CAFE"
        result = encode_get_amount_out(
            "0x0000000000000000000000000000000000000001", 1, sender=sender
        )
        sender_segment = result[136:]
        assert int(sender_segment, 16) == 0xCAFE


class TestDecoding:
    """Decoding getAmountOut response."""

    def test_decode_simple(self):
        """Decode a valid single uint256 response."""
        # 500000 = 0x7A120
        hex_result = "0x" + hex(500_000)[2:].zfill(64)
        assert decode_get_amount_out(hex_result) == 500_000

    def test_decode_zero(self):
        """Decode zero output."""
        hex_result = "0x" + "0" * 64
        assert decode_get_amount_out(hex_result) == 0

    def test_decode_large_value(self):
        """Decode large uint256 value."""
        large_val = 10**30
        hex_result = "0x" + hex(large_val)[2:].zfill(64)
        assert decode_get_amount_out(hex_result) == large_val

    def test_decode_empty_raises(self):
        """Empty response raises QuoteError."""
        with pytest.raises(QuoteError):
            decode_get_amount_out("0x")

    def test_decode_none_raises(self):
        """None response raises QuoteError."""
        with pytest.raises(QuoteError):
            decode_get_amount_out("")

    def test_decode_too_short_raises(self):
        """Short response raises QuoteError."""
        with pytest.raises(QuoteError):
            decode_get_amount_out("0x" + "00" * 10)


class TestRegistration:
    """SyncSwap adapter registered in dex/registry.py."""

    def test_syncswap_registered(self):
        """syncswap adapter_type must be in registry."""
        from dex.registry import get_adapter_class

        cls = get_adapter_class("syncswap")
        assert cls is not None, "syncswap adapter should be registered"
        assert cls is SyncSwapAdapter

    def test_adapter_in_list(self):
        """syncswap appears in list_adapter_types()."""
        from dex.registry import list_adapter_types

        types = list_adapter_types()
        assert "syncswap" in types


class TestAdapterInterface:
    """SyncSwap adapter interface and behavior."""

    def test_supports_fee_tiers_false(self):
        """SyncSwap does not use discrete fee tiers."""
        adapter = SyncSwapAdapter(provider=None, router_address="", dex_id="test_sync")
        assert adapter.supports_fee_tiers() is False

    def test_get_quote_requires_pool_address(self):
        """get_quote raises QuoteError without pool_address."""
        adapter = SyncSwapAdapter(provider=None)
        with pytest.raises(QuoteError):
            adapter.get_quote(
                pool_address="",
                token_in="0xabc",
                token_out="0xdef",
                amount_in=1000,
            )

    def test_get_quote_requires_token_in(self):
        """get_quote raises QuoteError without token_in."""
        adapter = SyncSwapAdapter(provider=None)
        with pytest.raises(QuoteError):
            adapter.get_quote(
                pool_address="0xPoolAddress",
                token_in="",
                token_out="0xdef",
                amount_in=1000,
            )

    def test_get_quote_with_mock_provider(self):
        """get_quote returns correct dict when provider returns valid data."""
        mock_provider = Mock()
        # Return 999_000 as uint256
        mock_provider.eth_call.return_value = "0x" + hex(999_000)[2:].zfill(64)

        adapter = SyncSwapAdapter(provider=mock_provider, dex_id="syncswap_test")
        result = adapter.get_quote(
            pool_address="0x1234567890abcdef1234567890abcdef12345678",
            token_in="0xdAC17F958D2ee523a2206206994597C13D831ec7",
            token_out="0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",
            amount_in=1_000_000,
        )

        assert result["amount_out"] == 999_000
        assert result["gas_estimate"] == 100_000
        assert result["quote_source"] == "syncswap_getAmountOut"

    def test_get_quote_call_target(self):
        """get_quote calls eth_call with correct target (pool_address)."""
        mock_provider = Mock()
        mock_provider.eth_call.return_value = "0x" + "0" * 64

        pool = "0xPOOL"
        adapter = SyncSwapAdapter(provider=mock_provider)
        adapter.get_quote(
            pool_address=pool,
            token_in="0xABC",
            token_out="0xDEF",
            amount_in=100,
        )

        call_args = mock_provider.eth_call.call_args
        assert call_args.kwargs["to"] == pool

    def test_get_quote_provider_exception(self):
        """Provider exception is wrapped in QuoteError."""
        mock_provider = Mock()
        mock_provider.eth_call.side_effect = RuntimeError("RPC timeout")

        adapter = SyncSwapAdapter(provider=mock_provider)
        with pytest.raises(QuoteError, match="syncswap getAmountOut failed"):
            adapter.get_quote(
                pool_address="0xPool",
                token_in="0xToken",
                token_out="0xOut",
                amount_in=1000,
            )

    def test_get_quote_empty_rpc_response(self):
        """Empty RPC response raises QuoteError (via decode)."""
        mock_provider = Mock()
        mock_provider.eth_call.return_value = "0x"

        adapter = SyncSwapAdapter(provider=mock_provider)
        with pytest.raises(QuoteError):
            adapter.get_quote(
                pool_address="0xPool",
                token_in="0xToken",
                token_out="0xOut",
                amount_in=1000,
            )
