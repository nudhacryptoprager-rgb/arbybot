"""
Unit tests for dex/adapters/iziswap.py.

Tests:
- ABI encoding for Quoter.swapAmount(uint128, address, address, uint24, bool)
- Decoding swapAmount response (uint256 acquire, int24 pointAfter)
- Token ordering convention (tokenX < tokenY)
- Adapter registration in registry
- Adapter interface: get_quote, supports_fee_tiers
- Error handling (empty response, short response, missing quoter)
"""

import pytest
from unittest.mock import Mock

from dex.adapters.iziswap import (
    IziSwapAdapter,
    encode_swap_amount,
    decode_swap_amount,
    SELECTOR_SWAP_AMOUNT,
    MAX_UINT128,
)
from core.exceptions import QuoteError


class TestEncoding:
    """ABI encoding for swapAmount(uint128, address, address, uint24, bool)."""

    def test_selector_value(self):
        """swapAmount selector is 0x75ceafe6."""
        assert SELECTOR_SWAP_AMOUNT == "0x75ceafe6"

    def test_encode_basic_length(self):
        """Encoded calldata has correct length: 8 (sel) + 5 * 64 (params) = 328."""
        result = encode_swap_amount(
            amount=1000,
            token_x="0x0000000000000000000000000000000000000001",
            token_y="0x0000000000000000000000000000000000000002",
            fee=3000,
            sell_x_earn_y=True,
        )
        assert len(result) == 328

    def test_encode_starts_with_selector(self):
        """Encoded calldata starts with selector (without 0x prefix)."""
        result = encode_swap_amount(
            amount=1, token_x="0x01", token_y="0x02", fee=500, sell_x_earn_y=False
        )
        assert result.startswith("75ceafe6")

    def test_encode_amount_field(self):
        """Amount is encoded in first parameter slot."""
        result = encode_swap_amount(
            amount=0xBEEF,
            token_x="0x0000000000000000000000000000000000000001",
            token_y="0x0000000000000000000000000000000000000002",
            fee=3000,
            sell_x_earn_y=True,
        )
        amount_segment = result[8 : 8 + 64]
        assert int(amount_segment, 16) == 0xBEEF

    def test_encode_uint128_clamp(self):
        """Amounts exceeding uint128 max are clamped."""
        huge = MAX_UINT128 + 1000
        result = encode_swap_amount(
            amount=huge,
            token_x="0x0000000000000000000000000000000000000001",
            token_y="0x0000000000000000000000000000000000000002",
            fee=3000,
            sell_x_earn_y=True,
        )
        amount_segment = result[8 : 8 + 64]
        assert int(amount_segment, 16) == MAX_UINT128

    def test_encode_fee_field(self):
        """Fee tier is encoded correctly."""
        result = encode_swap_amount(
            amount=1,
            token_x="0x0000000000000000000000000000000000000001",
            token_y="0x0000000000000000000000000000000000000002",
            fee=10000,
            sell_x_earn_y=True,
        )
        # Fee is 4th param: sel(8) + 3*64 = starts at 200
        fee_segment = result[200 : 200 + 64]
        assert int(fee_segment, 16) == 10000

    def test_encode_sell_x_earn_y_true(self):
        """sell_x_earn_y=True encodes as 1."""
        result = encode_swap_amount(
            amount=1, token_x="0x01", token_y="0x02", fee=3000, sell_x_earn_y=True
        )
        bool_segment = result[264:]
        assert int(bool_segment, 16) == 1

    def test_encode_sell_x_earn_y_false(self):
        """sell_x_earn_y=False encodes as 0."""
        result = encode_swap_amount(
            amount=1, token_x="0x01", token_y="0x02", fee=3000, sell_x_earn_y=False
        )
        bool_segment = result[264:]
        assert int(bool_segment, 16) == 0


class TestDecoding:
    """Decoding swapAmount response (uint256 acquire, int24 pointAfter)."""

    def test_decode_simple(self):
        """Decode valid response with positive acquire and positive point."""
        acquire_val = 500_000
        point_val = 100
        hex_result = "0x" + hex(acquire_val)[2:].zfill(64) + hex(point_val)[2:].zfill(64)

        acquire, point = decode_swap_amount(hex_result)
        assert acquire == 500_000
        assert point == 100

    def test_decode_zero(self):
        """Decode zero acquire, zero point."""
        hex_result = "0x" + "0" * 128
        acquire, point = decode_swap_amount(hex_result)
        assert acquire == 0
        assert point == 0

    def test_decode_negative_point(self):
        """Decode negative pointAfter (int24, stored as int256 two's complement)."""
        acquire_val = 1000
        # -50 in two's complement (256-bit): (2^256) - 50
        point_neg = (1 << 256) - 50
        hex_result = (
            "0x" + hex(acquire_val)[2:].zfill(64) + hex(point_neg)[2:].zfill(64)
        )

        acquire, point = decode_swap_amount(hex_result)
        assert acquire == 1000
        assert point == -50

    def test_decode_large_acquire(self):
        """Decode large uint256 acquire value."""
        large = 10**30
        hex_result = "0x" + hex(large)[2:].zfill(64) + "0" * 64
        acquire, point = decode_swap_amount(hex_result)
        assert acquire == large

    def test_decode_empty_raises(self):
        """Empty response raises QuoteError."""
        with pytest.raises(QuoteError):
            decode_swap_amount("0x")

    def test_decode_none_raises(self):
        """Empty string raises QuoteError."""
        with pytest.raises(QuoteError):
            decode_swap_amount("")

    def test_decode_too_short_raises(self):
        """Response shorter than 128 hex chars raises QuoteError."""
        with pytest.raises(QuoteError):
            decode_swap_amount("0x" + "00" * 30)  # only 60 hex chars


class TestTokenOrdering:
    """iZiSwap convention: tokenX < tokenY."""

    def test_adapter_sell_x_earn_y_when_token_in_lower(self):
        """When token_in < token_out, sell_x_earn_y should be True."""
        mock_provider = Mock()
        mock_provider.eth_call.return_value = "0x" + "0" * 128

        adapter = IziSwapAdapter(
            provider=mock_provider,
            quoter_address="0xQuoter",
            dex_id="iziswap_test",
        )
        adapter.get_quote(
            pool_address="0xPool",
            token_in="0x0000000000000000000000000000000000000AAA",
            token_out="0x0000000000000000000000000000000000000BBB",
            amount_in=1000,
            fee=3000,
        )

        # Verify the calldata includes sell_x_earn_y=True (last param = 1)
        call_data = mock_provider.eth_call.call_args.kwargs["data"]
        # Last 64 chars of calldata (bool param)
        bool_segment = call_data[-64:]
        assert int(bool_segment, 16) == 1

    def test_adapter_sell_y_earn_x_when_token_in_higher(self):
        """When token_in > token_out, sell_x_earn_y should be False."""
        mock_provider = Mock()
        mock_provider.eth_call.return_value = "0x" + "0" * 128

        adapter = IziSwapAdapter(
            provider=mock_provider,
            quoter_address="0xQuoter",
            dex_id="iziswap_test",
        )
        adapter.get_quote(
            pool_address="0xPool",
            token_in="0x0000000000000000000000000000000000000BBB",
            token_out="0x0000000000000000000000000000000000000AAA",
            amount_in=1000,
            fee=3000,
        )

        call_data = mock_provider.eth_call.call_args.kwargs["data"]
        bool_segment = call_data[-64:]
        assert int(bool_segment, 16) == 0


class TestRegistration:
    """iZiSwap adapter registered in dex/registry.py."""

    def test_iziswap_registered(self):
        """iziswap adapter_type must be in registry."""
        from dex.registry import get_adapter_class

        cls = get_adapter_class("iziswap")
        assert cls is not None, "iziswap adapter should be registered"
        assert cls is IziSwapAdapter

    def test_adapter_in_list(self):
        """iziswap appears in list_adapter_types()."""
        from dex.registry import list_adapter_types

        types = list_adapter_types()
        assert "iziswap" in types


class TestAdapterInterface:
    """iZiSwap adapter interface and behavior."""

    def test_supports_fee_tiers_true(self):
        """iZiSwap uses fee tiers (similar to UniV3)."""
        adapter = IziSwapAdapter(provider=None, quoter_address="", dex_id="test_izi")
        assert adapter.supports_fee_tiers() is True

    def test_get_quote_requires_quoter(self):
        """get_quote raises QuoteError without quoter_address."""
        adapter = IziSwapAdapter(provider=None, quoter_address="")
        with pytest.raises(QuoteError):
            adapter.get_quote(
                pool_address="0xPool",
                token_in="0xabc",
                token_out="0xdef",
                amount_in=1000,
            )

    def test_get_quote_requires_token_in(self):
        """get_quote raises QuoteError without token_in."""
        adapter = IziSwapAdapter(provider=None, quoter_address="0xQuoter")
        with pytest.raises(QuoteError):
            adapter.get_quote(
                pool_address="0xPool",
                token_in="",
                token_out="0xdef",
                amount_in=1000,
            )

    def test_get_quote_requires_token_out(self):
        """get_quote raises QuoteError without token_out."""
        adapter = IziSwapAdapter(provider=None, quoter_address="0xQuoter")
        with pytest.raises(QuoteError):
            adapter.get_quote(
                pool_address="0xPool",
                token_in="0xabc",
                token_out="",
                amount_in=1000,
            )

    def test_get_quote_default_fee(self):
        """get_quote uses fee=3000 when not specified."""
        mock_provider = Mock()
        mock_provider.eth_call.return_value = "0x" + "0" * 128

        adapter = IziSwapAdapter(
            provider=mock_provider, quoter_address="0xQuoter"
        )
        adapter.get_quote(
            pool_address="0xPool",
            token_in="0x0000000000000000000000000000000000000AAA",
            token_out="0x0000000000000000000000000000000000000BBB",
            amount_in=1000,
            fee=None,  # default
        )

        # Extract fee from calldata: sel(8) + amount(64) + tokenX(64) + tokenY(64) = 200
        call_data = mock_provider.eth_call.call_args.kwargs["data"]
        # Remove 0x prefix
        raw = call_data[2:]
        fee_segment = raw[200 : 200 + 64]
        assert int(fee_segment, 16) == 3000

    def test_get_quote_with_mock_provider(self):
        """get_quote returns correct dict when provider returns valid data."""
        mock_provider = Mock()
        acquire = 999_000
        point_after = 42
        hex_resp = "0x" + hex(acquire)[2:].zfill(64) + hex(point_after)[2:].zfill(64)
        mock_provider.eth_call.return_value = hex_resp

        adapter = IziSwapAdapter(
            provider=mock_provider,
            quoter_address="0xQuoter",
            dex_id="iziswap_test",
        )
        result = adapter.get_quote(
            pool_address="0xPool",
            token_in="0x0000000000000000000000000000000000000AAA",
            token_out="0x0000000000000000000000000000000000000BBB",
            amount_in=1_000_000,
            fee=3000,
        )

        assert result["amount_out"] == 999_000
        assert result["gas_estimate"] == 150_000
        assert result["quote_source"] == "iziswap_swapAmount"
        assert result["point_after"] == 42

    def test_get_quote_call_target(self):
        """get_quote calls eth_call with quoter_address as target."""
        mock_provider = Mock()
        mock_provider.eth_call.return_value = "0x" + "0" * 128

        quoter = "0xMyQuoter"
        adapter = IziSwapAdapter(provider=mock_provider, quoter_address=quoter)
        adapter.get_quote(
            pool_address="0xPool",
            token_in="0x0000000000000000000000000000000000000AAA",
            token_out="0x0000000000000000000000000000000000000BBB",
            amount_in=100,
            fee=3000,
        )

        call_args = mock_provider.eth_call.call_args
        assert call_args.kwargs["to"] == quoter

    def test_get_quote_provider_exception(self):
        """Provider exception is wrapped in QuoteError."""
        mock_provider = Mock()
        mock_provider.eth_call.side_effect = RuntimeError("RPC timeout")

        adapter = IziSwapAdapter(
            provider=mock_provider, quoter_address="0xQuoter"
        )
        with pytest.raises(QuoteError, match="iziswap swapAmount failed"):
            adapter.get_quote(
                pool_address="0xPool",
                token_in="0x0000000000000000000000000000000000000AAA",
                token_out="0x0000000000000000000000000000000000000BBB",
                amount_in=1000,
                fee=3000,
            )

    def test_get_quote_empty_rpc_response(self):
        """Empty RPC response raises QuoteError (via decode)."""
        mock_provider = Mock()
        mock_provider.eth_call.return_value = "0x"

        adapter = IziSwapAdapter(
            provider=mock_provider, quoter_address="0xQuoter"
        )
        with pytest.raises(QuoteError):
            adapter.get_quote(
                pool_address="0xPool",
                token_in="0x0000000000000000000000000000000000000AAA",
                token_out="0x0000000000000000000000000000000000000BBB",
                amount_in=1000,
                fee=3000,
            )
