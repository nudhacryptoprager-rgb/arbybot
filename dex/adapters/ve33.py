# PATH: dex/adapters/ve33.py
"""
ve33 / Solidly-style quoting adapter.

Implements quoting via direct pool getAmountOut() calls.
Supports:
- Aerodrome (Base)
- Stratum (Mantle)
- Other Velodrome/Solidly forks

ve33 pools do NOT use fee tiers — pricing is per-pool (stable vs volatile).
Quote method: pool.getAmountOut(amountIn, tokenIn) -> amountOut
"""

from typing import Optional, Any

from core.logging import get_logger
from core.exceptions import QuoteError, ErrorCode

logger = get_logger(__name__)

# ABI for getAmountOut(uint256 amountIn, address tokenIn) -> uint256 amountOut
# selector: keccak256("getAmountOut(uint256,address)")[:4] = 0xf140a35a
SELECTOR_GET_AMOUNT_OUT = "0xf140a35a"


def encode_get_amount_out(amount_in: int, token_in: str) -> str:
    """Encode getAmountOut(uint256, address) call data."""
    amount_hex = hex(amount_in)[2:].zfill(64)
    token_padded = token_in[2:].lower().zfill(64)
    return f"{SELECTOR_GET_AMOUNT_OUT[2:]}{amount_hex}{token_padded}"


def decode_get_amount_out(hex_result: str) -> int:
    """Decode getAmountOut response (single uint256)."""
    if not hex_result or hex_result == "0x":
        raise QuoteError(
            code=ErrorCode.QUOTE_REVERT,
            message="ve33 getAmountOut returned empty",
        )
    clean = hex_result.replace("0x", "")
    if len(clean) < 64:
        raise QuoteError(
            code=ErrorCode.QUOTE_REVERT,
            message=f"ve33 getAmountOut response too short: {len(clean)} hex chars",
        )
    return int(clean[:64], 16)


class Ve33Adapter:
    """
    Adapter for ve33/Solidly-style DEXes (Aerodrome, Stratum, Velodrome).

    Unlike V3 adapters, ve33 quotes directly on the pool contract
    via getAmountOut(amountIn, tokenIn). No quoter contract needed.
    """

    def __init__(self, provider: Any, router_address: str = "", dex_id: str = "ve33"):
        self.provider = provider
        self.router_address = router_address
        self.dex_id = dex_id

    def get_quote(
        self,
        pool_address: str,
        token_in: str,
        token_out: str,
        amount_in: int,
        fee: Optional[int] = None,
        block_number: Optional[int] = None,
    ) -> dict:
        """
        Get quote from ve33 pool via getAmountOut().

        Returns dict with: amount_out, gas_estimate, quote_source
        """
        if not pool_address or not token_in:
            raise QuoteError(
                code=ErrorCode.QUOTE_REVERT,
                message="ve33: pool_address and token_in required",
            )

        calldata = "0x" + encode_get_amount_out(amount_in, token_in)

        try:
            result = self.provider.eth_call(
                to=pool_address,
                data=calldata,
                block=block_number,
            )
            amount_out = decode_get_amount_out(result)
        except QuoteError:
            raise
        except Exception as e:
            raise QuoteError(
                code=ErrorCode.QUOTE_REVERT,
                message=f"ve33 getAmountOut failed: {e}",
            )

        return {
            "amount_out": amount_out,
            "gas_estimate": 80_000,
            "quote_source": "ve33_getAmountOut",
            "sqrt_price_after": 0,
            "ticks_crossed": 0,
        }

    def supports_fee_tiers(self) -> bool:
        """ve33 pools do not use discrete fee tiers."""
        return False
