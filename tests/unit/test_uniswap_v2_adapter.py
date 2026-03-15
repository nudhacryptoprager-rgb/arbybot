# PATH: tests/unit/test_uniswap_v2_adapter.py
"""
Unit tests for dex/adapters/uniswap_v2.py.

Tests:
- ABI encoding/decoding for getReserves()
- Constant product formula (calculate_v2_output)
- Adapter registration in registry
"""

import pytest

from dex.adapters.uniswap_v2 import (
    UniswapV2Adapter,
    encode_get_reserves,
    decode_get_reserves,
    calculate_v2_output,
    SELECTOR_GET_RESERVES,
)
from core.exceptions import QuoteError


class TestEncoding:
    """ABI encoding for getReserves()."""

    def test_encode_get_reserves_selector(self):
        """getReserves() selector is 0x0902f1ac."""
        assert encode_get_reserves() == "0x0902f1ac"

    def test_decode_get_reserves_valid(self):
        """Decode a valid getReserves response."""
        # reserve0=1000000 (0xF4240), reserve1=2000000 (0x1E8480), ts=1700000000
        r0_hex = hex(1_000_000)[2:].zfill(64)
        r1_hex = hex(2_000_000)[2:].zfill(64)
        ts_hex = hex(1_700_000_000)[2:].zfill(64)
        hex_result = "0x" + r0_hex + r1_hex + ts_hex

        reserve0, reserve1, block_ts = decode_get_reserves(hex_result)
        assert reserve0 == 1_000_000
        assert reserve1 == 2_000_000
        assert block_ts == 1_700_000_000

    def test_decode_get_reserves_empty(self):
        """Empty response raises QuoteError."""
        with pytest.raises(QuoteError):
            decode_get_reserves("0x")

    def test_decode_get_reserves_too_short(self):
        """Short response raises QuoteError."""
        with pytest.raises(QuoteError):
            decode_get_reserves("0x" + "00" * 10)


class TestConstantProduct:
    """V2 constant product formula."""

    def test_standard_swap(self):
        """Standard V2 swap with 0.3% fee."""
        # Pool: 1M USDC (6 dec) / 500 WETH (18 dec)
        reserve_in = 1_000_000 * 10**6   # 1M USDC
        reserve_out = 500 * 10**18       # 500 WETH
        amount_in = 1000 * 10**6         # 1000 USDC

        amount_out = calculate_v2_output(amount_in, reserve_in, reserve_out)
        # With 0.3% fee: amountOut ≈ 0.4985 WETH (slightly less than 0.5 due to fee + slippage)
        assert amount_out > 0
        # Exact: (1000e6 * 9970 * 500e18) / (1000000e6 * 10000 + 1000e6 * 9970)
        # = (4985e27) / (10009970e12) ≈ 498003e12 ≈ 0.498 WETH
        assert amount_out < 500 * 10**15  # Less than 0.5 WETH

    def test_zero_reserves(self):
        """Zero reserves returns 0."""
        assert calculate_v2_output(1000, 0, 1000) == 0
        assert calculate_v2_output(1000, 1000, 0) == 0

    def test_zero_amount_in(self):
        """Zero input returns 0."""
        assert calculate_v2_output(0, 1000, 1000) == 0

    def test_custom_fee(self):
        """Custom fee (e.g., SushiSwap V2 with 0.3%)."""
        reserve_in = 10**18
        reserve_out = 10**18
        amount_in = 10**16  # 0.01 ETH

        out_30bps = calculate_v2_output(amount_in, reserve_in, reserve_out, fee_bps=30)
        out_25bps = calculate_v2_output(amount_in, reserve_in, reserve_out, fee_bps=25)
        # Lower fee = more output
        assert out_25bps > out_30bps

    def test_symmetry_check(self):
        """Equal reserves: output < input (due to fee)."""
        reserve = 10**18
        amount_in = 10**16
        amount_out = calculate_v2_output(amount_in, reserve, reserve, fee_bps=30)
        assert 0 < amount_out < amount_in


class TestRegistration:
    """V2 adapter registered in dex/registry.py."""

    def test_uniswap_v2_registered(self):
        """uniswap_v2 adapter_type must be in registry."""
        from dex.registry import get_adapter_class

        cls = get_adapter_class("uniswap_v2")
        assert cls is not None, "uniswap_v2 adapter should be registered"
        assert cls is UniswapV2Adapter

    def test_adapter_in_list(self):
        """uniswap_v2 appears in list_adapter_types()."""
        from dex.registry import list_adapter_types

        types = list_adapter_types()
        assert "uniswap_v2" in types


class TestAdapterInterface:
    """V2 adapter follows the expected interface."""

    def test_supports_fee_tiers_false(self):
        """V2 does not use discrete fee tiers."""
        adapter = UniswapV2Adapter(provider=None, router_address="", dex_id="test_v2")
        assert adapter.supports_fee_tiers() is False

    def test_get_quote_requires_pool_address(self):
        """get_quote raises QuoteError without pool_address."""
        adapter = UniswapV2Adapter(provider=None)
        with pytest.raises(QuoteError):
            adapter.get_quote(
                pool_address="",
                token_in="0xabc",
                token_out="0xdef",
                amount_in=1000,
            )
