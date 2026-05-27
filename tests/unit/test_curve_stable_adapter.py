"""Unit tests for Curve StableSwap adapter (dex/adapters/curve_stable.py).

Verifies:
  - encode_get_dy produces correct selector and layout
  - decode_get_dy parses uint256 response
  - CurveStableAdapter.ADAPTER_TYPE == "curve_stable"
  - get_quote() returns correct dict structure with mock provider
  - get_quote() raises QuoteError on zero output
  - get_quote() raises QuoteError for invalid inputs
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from core.exceptions import QuoteError
from dex.adapters.curve_stable import (
    CurveStableAdapter,
    encode_get_dy,
    decode_get_dy,
    _SELECTOR_GET_DY_INT128,
    _SELECTOR_GET_DY_UINT256,
)

POOL = "0x" + "11" * 20
TOKEN_IN = "0x" + "aa" * 20
TOKEN_OUT = "0x" + "bb" * 20
AMOUNT_IN = 10 ** 6  # 1 USDC (6 decimals)


class TestSelectors:
    def test_int128_selector_is_4_bytes(self):
        assert len(_SELECTOR_GET_DY_INT128) == 4

    def test_uint256_selector_is_4_bytes(self):
        assert len(_SELECTOR_GET_DY_UINT256) == 4

    def test_selectors_differ(self):
        assert _SELECTOR_GET_DY_INT128 != _SELECTOR_GET_DY_UINT256

    def test_int128_selector_value(self):
        """Verify selector for get_dy(int128,int128,uint256)."""
        assert _SELECTOR_GET_DY_INT128 == bytes.fromhex("5e0d443f")

    def test_uint256_selector_value(self):
        """Verify selector for get_dy(uint256,uint256,uint256)."""
        assert _SELECTOR_GET_DY_UINT256 == bytes.fromhex("4fb08c5e")


class TestEncodeGetDy:
    def test_length_int128(self):
        """Selector (4) + i(32) + j(32) + dx(32) = 100 bytes."""
        data = encode_get_dy(0, 1, AMOUNT_IN, use_uint256=False)
        assert len(data) == 4 + 32 + 32 + 32, f"Expected 100 bytes, got {len(data)}"

    def test_length_uint256(self):
        data = encode_get_dy(0, 1, AMOUNT_IN, use_uint256=True)
        assert len(data) == 4 + 32 + 32 + 32

    def test_starts_with_correct_selector_int128(self):
        data = encode_get_dy(0, 1, AMOUNT_IN, use_uint256=False)
        assert data[:4] == _SELECTOR_GET_DY_INT128

    def test_starts_with_correct_selector_uint256(self):
        data = encode_get_dy(0, 1, AMOUNT_IN, use_uint256=True)
        assert data[:4] == _SELECTOR_GET_DY_UINT256

    def test_amount_encoded_correctly(self):
        data = encode_get_dy(0, 1, AMOUNT_IN, use_uint256=False)
        # Last 32 bytes = dx
        dx_bytes = data[-32:]
        assert int.from_bytes(dx_bytes, "big") == AMOUNT_IN

    def test_indices_encoded(self):
        data = encode_get_dy(0, 1, AMOUNT_IN, use_uint256=False)
        i_bytes = data[4:36]
        j_bytes = data[36:68]
        assert int.from_bytes(i_bytes, "big") == 0
        assert int.from_bytes(j_bytes, "big") == 1

    def test_different_indices(self):
        data = encode_get_dy(2, 3, AMOUNT_IN, use_uint256=False)
        i_val = int.from_bytes(data[4:36], "big")
        j_val = int.from_bytes(data[36:68], "big")
        assert i_val == 2
        assert j_val == 3


class TestDecodeGetDy:
    def test_decode_valid_response(self):
        amount_out = 999_000  # ~0.999 USDT
        hex_response = "0x" + amount_out.to_bytes(32, "big").hex()
        result = decode_get_dy(hex_response)
        assert result == amount_out

    def test_decode_strips_0x_prefix(self):
        amount_out = 12345678
        hex_no_prefix = amount_out.to_bytes(32, "big").hex()
        result = decode_get_dy(hex_no_prefix)
        assert result == amount_out

    def test_too_short_raises(self):
        with pytest.raises(QuoteError):
            decode_get_dy("0x1234")  # only 2 bytes

    def test_zero_amount_decodes(self):
        result = decode_get_dy("0x" + "00" * 32)
        assert result == 0


class TestCurveStableAdapterType:
    def test_adapter_type_constant(self):
        assert CurveStableAdapter.ADAPTER_TYPE == "curve_stable"

    def test_supports_fee_tiers_false(self):
        provider = MagicMock()
        adapter = CurveStableAdapter(provider=provider)
        assert adapter.supports_fee_tiers() is False


class TestCurveStableAdapterGetQuote:
    """get_quote() with mock provider."""

    def _make_adapter(self, amount_out: int) -> tuple:
        provider = MagicMock()
        response = "0x" + amount_out.to_bytes(32, "big").hex()
        provider.eth_call.return_value = response
        adapter = CurveStableAdapter(provider=provider)
        return adapter, provider

    def test_successful_quote(self):
        amount_out = 999_800
        adapter, _ = self._make_adapter(amount_out)
        result = adapter.get_quote(
            pool_address=POOL,
            token_in=TOKEN_IN,
            token_out=TOKEN_OUT,
            amount_in=AMOUNT_IN,
            token_in_index=0,
            token_out_index=1,
        )
        assert result["amount_out"] == amount_out
        assert result["adapter_type"] == "curve_stable"
        assert "quote_source" in result
        assert "curve_stable" in result["quote_source"]
        assert result["gas_estimate"] > 0

    def test_zero_amount_in_raises(self):
        adapter, _ = self._make_adapter(999_000)
        with pytest.raises(QuoteError):
            adapter.get_quote(
                pool_address=POOL,
                token_in=TOKEN_IN,
                token_out=TOKEN_OUT,
                amount_in=0,
                token_in_index=0,
                token_out_index=1,
            )

    def test_negative_amount_in_raises(self):
        adapter, _ = self._make_adapter(999_000)
        with pytest.raises(QuoteError):
            adapter.get_quote(
                pool_address=POOL,
                token_in=TOKEN_IN,
                token_out=TOKEN_OUT,
                amount_in=-100,
            )

    def test_same_index_raises(self):
        adapter, _ = self._make_adapter(999_000)
        with pytest.raises(QuoteError):
            adapter.get_quote(
                pool_address=POOL,
                token_in=TOKEN_IN,
                token_out=TOKEN_OUT,
                amount_in=AMOUNT_IN,
                token_in_index=1,
                token_out_index=1,  # same as in
            )

    def test_missing_pool_address_raises(self):
        adapter, _ = self._make_adapter(999_000)
        with pytest.raises(QuoteError):
            adapter.get_quote(
                pool_address="",
                token_in=TOKEN_IN,
                token_out=TOKEN_OUT,
                amount_in=AMOUNT_IN,
            )

    def test_zero_output_raises(self):
        adapter, _ = self._make_adapter(0)  # provider returns 0
        with pytest.raises(QuoteError):
            adapter.get_quote(
                pool_address=POOL,
                token_in=TOKEN_IN,
                token_out=TOKEN_OUT,
                amount_in=AMOUNT_IN,
                token_in_index=0,
                token_out_index=1,
            )

    def test_fallback_to_uint256_selector(self):
        """When int128 call reverts, adapter retries with uint256 selector."""
        amount_out = 500_000
        response = "0x" + amount_out.to_bytes(32, "big").hex()

        provider = MagicMock()
        # First call raises (simulating revert), second succeeds
        provider.eth_call.side_effect = [Exception("revert"), response]

        adapter = CurveStableAdapter(provider=provider)
        result = adapter.get_quote(
            pool_address=POOL,
            token_in=TOKEN_IN,
            token_out=TOKEN_OUT,
            amount_in=AMOUNT_IN,
            token_in_index=0,
            token_out_index=1,
        )
        assert result["amount_out"] == amount_out
        # Called twice: first with int128, then with uint256
        assert provider.eth_call.call_count == 2

    def test_quote_source_reflects_selector_used(self):
        """quote_source should indicate whether int128 or uint256 selector was used."""
        amount_out = 999_800
        adapter, _ = self._make_adapter(amount_out)
        result = adapter.get_quote(
            pool_address=POOL,
            token_in=TOKEN_IN,
            token_out=TOKEN_OUT,
            amount_in=AMOUNT_IN,
        )
        # The first successful call uses int128
        assert "int128" in result["quote_source"]
