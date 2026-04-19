"""E1.35 P1.1 step 4: Aerodrome Slipstream SwapRouter calldata builder.

Validates:
- Selector is computed via keccak-256 over the exact ABI signature and
  differs from Uniswap V3's 0x414bf389.
- Byte-exact layout (selector + 8 static words = 4 + 256 bytes).
- `tick_spacing` validation (positive, within int24 positive range).
- `tick_spacing` word contains the spacing value right-padded to 32 bytes.
"""
from __future__ import annotations

import pytest

from execution.gas_estimate import (
    SLIPSTREAM_EXACT_INPUT_SINGLE_SELECTOR,
    SLIPSTREAM_EXACT_INPUT_SINGLE_SIG,
    build_slipstream_exact_input_single_calldata,
)


TOKEN_IN = "0x4200000000000000000000000000000000000006"   # WETH on Base
TOKEN_OUT = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"  # USDC on Base
RECIPIENT = "0x0000000000000000000000000000000000000001"


class TestSelector:
    def test_selector_is_4_bytes(self):
        assert isinstance(SLIPSTREAM_EXACT_INPUT_SINGLE_SELECTOR, (bytes, bytearray))
        assert len(SLIPSTREAM_EXACT_INPUT_SINGLE_SELECTOR) == 4

    def test_selector_differs_from_uniswap_v3(self):
        # Uniswap V3 SwapRouter exactInputSingle selector is 0x414bf389
        assert (
            SLIPSTREAM_EXACT_INPUT_SINGLE_SELECTOR.hex() != "414bf389"
        ), "Slipstream ABI (int24 tickSpacing) must yield a different selector"

    def test_signature_uses_int24_tickspacing(self):
        # Sanity: the bytes constant actually carries int24, not uint24.
        assert b"int24" in SLIPSTREAM_EXACT_INPUT_SINGLE_SIG
        assert b"uint24" not in SLIPSTREAM_EXACT_INPUT_SINGLE_SIG


class TestBuilder:
    def test_length(self):
        cd = build_slipstream_exact_input_single_calldata(
            token_in=TOKEN_IN,
            token_out=TOKEN_OUT,
            tick_spacing=100,
            recipient=RECIPIENT,
            amount_in=10**18,
        )
        # 4 bytes selector + 8 words * 32 bytes = 260 bytes
        assert len(cd) == 4 + 8 * 32

    def test_selector_prefix(self):
        cd = build_slipstream_exact_input_single_calldata(
            token_in=TOKEN_IN,
            token_out=TOKEN_OUT,
            tick_spacing=50,
            recipient=RECIPIENT,
            amount_in=1,
        )
        assert cd[:4] == SLIPSTREAM_EXACT_INPUT_SINGLE_SELECTOR

    def test_tick_spacing_word_layout(self):
        cd = build_slipstream_exact_input_single_calldata(
            token_in=TOKEN_IN,
            token_out=TOKEN_OUT,
            tick_spacing=2000,
            recipient=RECIPIENT,
            amount_in=1,
            deadline=1_000_000,
        )
        body = cd[4:]
        # Word layout: [tokenIn, tokenOut, tickSpacing, recipient, deadline,
        # amountIn, amountOutMin, sqrtPriceLimit]
        tick_word = body[2 * 32 : 3 * 32]
        assert int.from_bytes(tick_word, "big") == 2000

        amount_word = body[5 * 32 : 6 * 32]
        assert int.from_bytes(amount_word, "big") == 1

        deadline_word = body[4 * 32 : 5 * 32]
        assert int.from_bytes(deadline_word, "big") == 1_000_000

    def test_rejects_non_positive_tick_spacing(self):
        for bad in (0, -1):
            with pytest.raises(ValueError):
                build_slipstream_exact_input_single_calldata(
                    token_in=TOKEN_IN,
                    token_out=TOKEN_OUT,
                    tick_spacing=bad,
                    recipient=RECIPIENT,
                    amount_in=1,
                )

    def test_rejects_out_of_int24_range(self):
        with pytest.raises(ValueError):
            build_slipstream_exact_input_single_calldata(
                token_in=TOKEN_IN,
                token_out=TOKEN_OUT,
                tick_spacing=(1 << 23),
                recipient=RECIPIENT,
                amount_in=1,
            )

    def test_addresses_normalized_lowercase(self):
        # Pass in mixed case; output should still be deterministic.
        cd_mixed = build_slipstream_exact_input_single_calldata(
            token_in=TOKEN_IN.upper().replace("0X", "0x"),
            token_out=TOKEN_OUT,
            tick_spacing=100,
            recipient=RECIPIENT,
            amount_in=1,
            deadline=999,
        )
        cd_lower = build_slipstream_exact_input_single_calldata(
            token_in=TOKEN_IN.lower(),
            token_out=TOKEN_OUT.lower(),
            tick_spacing=100,
            recipient=RECIPIENT,
            amount_in=1,
            deadline=999,
        )
        assert cd_mixed == cd_lower
