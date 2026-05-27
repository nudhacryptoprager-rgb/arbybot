"""Unit tests for Balancer Vault adapter (dex/adapters/balancer_vault.py).

Verifies:
  - BALANCER_VAULT_ADDRESS is the canonical Balancer V2 vault
  - _encode_query_batch_swap produces correct 4-byte selector prefix
  - _decode_query_batch_swap parses int256[] deltas correctly
  - BalancerVaultAdapter.ADAPTER_TYPE == "balancer_vault"
  - get_quote() returns correct dict with mock provider
  - get_quote() validates pool_id, token addresses, and amount_in
  - get_quote() raises QuoteError on zero amount_out
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from core.exceptions import QuoteError
from dex.adapters.balancer_vault import (
    BALANCER_VAULT_ADDRESS,
    BalancerVaultAdapter,
    _decode_query_batch_swap,
    _encode_query_batch_swap,
    _SELECTOR_QUERY_BATCH_SWAP,
)

# Sample Balancer pool ID (bytes32 = 64 hex chars after 0x prefix)
# 32 bytes = 64 hex chars
POOL_ID = "0x" + "de" * 32  # 64 hex chars = 32 bytes
TOKEN_IN = "0x" + "aa" * 20
TOKEN_OUT = "0x" + "bb" * 20
AMOUNT_IN = 10 ** 18


class TestVaultAddress:
    def test_canonical_vault_address(self):
        """Balancer V2 vault uses same address on all EVM chains."""
        assert BALANCER_VAULT_ADDRESS.lower() == "0xba12222222228d8ba445958a75a0704d566bf2c8"

    def test_vault_address_is_40_char_hex(self):
        addr = BALANCER_VAULT_ADDRESS
        assert addr.startswith("0x")
        assert len(addr) == 42


class TestQueryBatchSwapSelector:
    def test_selector_is_4_bytes(self):
        assert len(_SELECTOR_QUERY_BATCH_SWAP) == 4

    def test_selector_value(self):
        """Selector for queryBatchSwap should be 0xf84d066e."""
        assert _SELECTOR_QUERY_BATCH_SWAP == bytes.fromhex("f84d066e")


class TestEncodeQueryBatchSwap:
    def test_starts_with_selector(self):
        data = _encode_query_batch_swap(
            pool_id=POOL_ID,
            token_in_addr=TOKEN_IN,
            token_out_addr=TOKEN_OUT,
            amount_in=AMOUNT_IN,
        )
        assert data[:4] == _SELECTOR_QUERY_BATCH_SWAP

    def test_minimum_length(self):
        """Encoded call must be at least 4 bytes (selector) + meaningful ABI payload."""
        data = _encode_query_batch_swap(
            pool_id=POOL_ID,
            token_in_addr=TOKEN_IN,
            token_out_addr=TOKEN_OUT,
            amount_in=AMOUNT_IN,
        )
        # At minimum: selector(4) + kind(32) + 2 dynamic offsets(64) + funds(128) + swaps+assets
        # Actual ABI layout: >=4 + 224 (static head) + swaps + assets = several hundred bytes
        assert len(data) >= 4 + 224, f"Expected >={4+224} bytes, got {len(data)}"

    def test_returns_bytes(self):
        data = _encode_query_batch_swap(
            pool_id=POOL_ID,
            token_in_addr=TOKEN_IN,
            token_out_addr=TOKEN_OUT,
            amount_in=AMOUNT_IN,
        )
        assert isinstance(data, bytes)


class TestDecodeQueryBatchSwap:
    def _make_deltas_response(self, delta0: int, delta1: int) -> str:
        """Encode int256[] deltas as ABI response."""
        # ABI: offset(32) + length(32) + [delta0(32) + delta1(32)]
        # offset = 32 (array starts at byte 32)
        offset = 32
        length = 2
        # Sign-encode int256
        d0 = delta0 % (2 ** 256)
        d1 = delta1 % (2 ** 256)
        raw = (
            offset.to_bytes(32, "big")
            + length.to_bytes(32, "big")
            + d0.to_bytes(32, "big")
            + d1.to_bytes(32, "big")
        )
        return "0x" + raw.hex()

    def test_positive_in_negative_out(self):
        """Normal swap: delta_in > 0, delta_out < 0."""
        delta0 = 10 ** 18      # vault receives token_in
        delta1 = -(10 ** 18 - 1000)  # vault sends token_out
        resp = self._make_deltas_response(delta0, delta1)
        d_in, d_out = _decode_query_batch_swap(resp)
        assert d_in == delta0
        assert d_out == delta1

    def test_amount_out_is_abs_of_delta1(self):
        delta0 = 10 ** 6
        delta1 = -(10 ** 6 - 100)
        resp = self._make_deltas_response(delta0, delta1)
        d_in, d_out = _decode_query_batch_swap(resp)
        assert abs(d_out) == abs(delta1)

    def test_too_short_response_raises(self):
        with pytest.raises(QuoteError):
            _decode_query_batch_swap("0x" + "00" * 10)


class TestBalancerVaultAdapterType:
    def test_adapter_type_constant(self):
        assert BalancerVaultAdapter.ADAPTER_TYPE == "balancer_vault"

    def test_supports_fee_tiers_false(self):
        provider = MagicMock()
        adapter = BalancerVaultAdapter(provider=provider)
        assert adapter.supports_fee_tiers() is False


class TestBalancerVaultAdapterGetQuote:
    """get_quote() with mock provider."""

    def _make_adapter_with_response(self, delta0: int, delta1: int) -> tuple:
        """Return (adapter, provider) with mock eth_call returning given deltas."""
        offset = 32
        length = 2
        d0 = delta0 % (2 ** 256)
        d1 = delta1 % (2 ** 256)
        raw = (
            offset.to_bytes(32, "big")
            + length.to_bytes(32, "big")
            + d0.to_bytes(32, "big")
            + d1.to_bytes(32, "big")
        )
        response = "0x" + raw.hex()
        provider = MagicMock()
        provider.eth_call.return_value = response
        adapter = BalancerVaultAdapter(provider=provider)
        return adapter, provider

    def test_successful_quote(self):
        amount_in = 10 ** 18
        amount_out = 10 ** 18 - 5000  # slight slippage
        adapter, _ = self._make_adapter_with_response(amount_in, -amount_out)
        result = adapter.get_quote(
            pool_id=POOL_ID,
            token_in=TOKEN_IN,
            token_out=TOKEN_OUT,
            amount_in=amount_in,
        )
        assert result["amount_out"] == amount_out
        assert result["adapter_type"] == "balancer_vault"
        assert "quote_source" in result
        assert "queryBatchSwap" in result["quote_source"]
        assert result["gas_estimate"] > 0

    def test_zero_amount_in_raises(self):
        adapter, _ = self._make_adapter_with_response(0, 0)
        with pytest.raises(QuoteError):
            adapter.get_quote(
                pool_id=POOL_ID,
                token_in=TOKEN_IN,
                token_out=TOKEN_OUT,
                amount_in=0,
            )

    def test_invalid_pool_id_raises(self):
        adapter, _ = self._make_adapter_with_response(10 ** 18, -(10 ** 18 - 1000))
        with pytest.raises(QuoteError):
            adapter.get_quote(
                pool_id="0xshort",  # too short
                token_in=TOKEN_IN,
                token_out=TOKEN_OUT,
                amount_in=AMOUNT_IN,
            )

    def test_missing_token_in_raises(self):
        adapter, _ = self._make_adapter_with_response(10 ** 18, -(10 ** 18 - 1000))
        with pytest.raises(QuoteError):
            adapter.get_quote(
                pool_id=POOL_ID,
                token_in="",
                token_out=TOKEN_OUT,
                amount_in=AMOUNT_IN,
            )

    def test_zero_amount_out_raises(self):
        """When delta_out=0, amount_out=0 → QuoteError."""
        adapter, _ = self._make_adapter_with_response(AMOUNT_IN, 0)
        with pytest.raises(QuoteError):
            adapter.get_quote(
                pool_id=POOL_ID,
                token_in=TOKEN_IN,
                token_out=TOKEN_OUT,
                amount_in=AMOUNT_IN,
            )

    def test_provider_called_with_vault_address(self):
        """eth_call must target the Vault address, not the pool directly."""
        adapter, provider = self._make_adapter_with_response(AMOUNT_IN, -(AMOUNT_IN - 100))
        adapter.get_quote(
            pool_id=POOL_ID,
            token_in=TOKEN_IN,
            token_out=TOKEN_OUT,
            amount_in=AMOUNT_IN,
        )
        call_args = provider.eth_call.call_args
        to_addr = call_args[1].get("to") or call_args[0][0]
        assert to_addr.lower() == BALANCER_VAULT_ADDRESS.lower(), (
            f"Expected eth_call to Vault {BALANCER_VAULT_ADDRESS}, got {to_addr}"
        )

    def test_default_vault_address_used_when_not_specified(self):
        provider = MagicMock()
        adapter = BalancerVaultAdapter(provider=provider)
        assert adapter.vault_address.lower() == BALANCER_VAULT_ADDRESS.lower()
