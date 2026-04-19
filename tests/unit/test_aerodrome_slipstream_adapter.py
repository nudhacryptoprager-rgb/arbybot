"""
E1.35 P1.1: Aerodrome Slipstream adapter — unit tests (calldata + decoder).

Covers:
- Selector / layout of encode_quote_exact_input_single (byte-exact).
- Input validation for tick_spacing (positive, within int24 range).
- Decoder on well-formed and malformed responses.
- Registry wiring: "aerodrome_slipstream" is registered.
"""
from __future__ import annotations

import pytest

from core.exceptions import ErrorCode, QuoteError
from dex.adapters.aerodrome_slipstream import (
    SELECTOR_QUOTE_EXACT_INPUT_SINGLE_SLIPSTREAM,
    decode_quote_response,
    encode_quote_exact_input_single,
)


TOKEN_IN = "0x4200000000000000000000000000000000000006"   # WETH on Base
TOKEN_OUT = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"  # USDC on Base


class TestSelector:
    def test_selector_constant_is_not_empty(self):
        assert SELECTOR_QUOTE_EXACT_INPUT_SINGLE_SLIPSTREAM.startswith("0x")
        # 4-byte selector = 10 hex chars including "0x"
        assert len(SELECTOR_QUOTE_EXACT_INPUT_SINGLE_SLIPSTREAM) == 10

    def test_selector_differs_from_uniswap_v3(self):
        """Slipstream uses int24 tickSpacing vs uint24 fee — selector must differ."""
        from dex.adapters.uniswap_v3 import SELECTOR_QUOTE_EXACT_INPUT_SINGLE
        assert (
            SELECTOR_QUOTE_EXACT_INPUT_SINGLE_SLIPSTREAM
            != SELECTOR_QUOTE_EXACT_INPUT_SINGLE
        )


class TestEncoder:
    def test_encode_layout_static_tuple_length(self):
        """Selector (4 bytes) + 5 static words (5 * 32 bytes) = 324 hex chars."""
        data = encode_quote_exact_input_single(
            token_in=TOKEN_IN,
            token_out=TOKEN_OUT,
            amount_in=10**18,
            tick_spacing=100,
        )
        # "0x" (2) + selector (8) + 5 * 64 = 10 + 320 = 330
        assert len(data) == 330
        assert data.startswith(SELECTOR_QUOTE_EXACT_INPUT_SINGLE_SLIPSTREAM)

    def test_encode_fields_layout(self):
        data = encode_quote_exact_input_single(
            token_in=TOKEN_IN,
            token_out=TOKEN_OUT,
            amount_in=1234,
            tick_spacing=200,
            sqrt_price_limit_x96=0,
        )
        # Strip "0x" + 8-char selector → 5 words of 64 chars each.
        body = data[10:]
        word = lambda i: body[i * 64 : (i + 1) * 64]  # noqa: E731
        assert word(0).endswith(TOKEN_IN[2:].lower())
        assert word(1).endswith(TOKEN_OUT[2:].lower())
        assert int(word(2), 16) == 1234
        assert int(word(3), 16) == 200
        assert int(word(4), 16) == 0

    def test_encode_rejects_non_positive_tick_spacing(self):
        for bad in (0, -1):
            with pytest.raises(QuoteError) as exc_info:
                encode_quote_exact_input_single(
                    TOKEN_IN, TOKEN_OUT, 1, tick_spacing=bad
                )
            assert exc_info.value.code == ErrorCode.QUOTE_REVERT

    def test_encode_rejects_out_of_int24_range(self):
        # int24 positive max = 2**23 - 1; anything >= 2**23 is invalid.
        with pytest.raises(QuoteError):
            encode_quote_exact_input_single(
                TOKEN_IN, TOKEN_OUT, 1, tick_spacing=(1 << 23)
            )

    def test_encode_checksum_addresses_normalized_to_lowercase(self):
        data = encode_quote_exact_input_single(
            token_in=TOKEN_IN,   # mixed case in source
            token_out=TOKEN_OUT,
            amount_in=1,
            tick_spacing=50,
        )
        # Body should not contain any uppercase hex chars from addresses.
        body = data[10:]
        assert body.lower() == body


class TestDecoder:
    def _pack(self, amount_out, sqrt_price, ticks, gas):
        return "0x" + "".join(
            hex(v)[2:].zfill(64) for v in (amount_out, sqrt_price, ticks, gas)
        )

    def test_decode_well_formed(self):
        raw = self._pack(10**18, 2**96, 3, 200_000)
        amount_out, sqrt_price, ticks, gas = decode_quote_response(raw)
        assert amount_out == 10**18
        assert sqrt_price == 2**96
        assert ticks == 3
        assert gas == 200_000

    def test_decode_empty_raises(self):
        for empty in ("", "0x", None):
            with pytest.raises(QuoteError) as exc_info:
                decode_quote_response(empty)  # type: ignore[arg-type]
            assert exc_info.value.code == ErrorCode.QUOTE_REVERT

    def test_decode_too_short_raises(self):
        with pytest.raises(QuoteError):
            decode_quote_response("0x" + "00" * 64)  # only 1 word, need 4


class TestRegistryWiring:
    def test_aerodrome_slipstream_registered(self):
        from dex.registry import get_adapter_class
        cls = get_adapter_class("aerodrome_slipstream")
        assert cls is not None
        assert cls.__name__ == "AerodromeSlipstreamAdapter"


class TestConfigWiring:
    def test_aerodrome_slipstream_present_on_base(self):
        from config import get_dex_config
        cfg = get_dex_config("base", "aerodrome_slipstream")
        assert cfg["adapter_type"] == "aerodrome_slipstream"
        # All three canonical addresses must be real (verified from
        # aerodrome.finance/security).
        for key in ("factory", "router", "quoter_v2"):
            val = cfg.get(key)
            assert isinstance(val, str) and val.startswith("0x") and len(val) == 42, (
                f"{key} must be a verified 0x-address, got {val!r}"
            )
        assert cfg.get("verified") is True
        # Known on-chain tick spacings on Base (sanity check).
        tick_spacings = cfg.get("tick_spacings") or []
        assert set(tick_spacings) >= {1, 50, 100, 200, 2000}
