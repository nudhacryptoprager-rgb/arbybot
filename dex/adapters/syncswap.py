# PATH: dex/adapters/syncswap.py
# R36: SyncSwap real adapter (Classic + Stable pool model).
# SyncSwap pools expose getAmountOut(address tokenIn, uint256 amountIn, address sender).
# Deployed on: zkSync Era, Linea, Scroll.
# Docs: https://docs.syncswap.xyz/
from typing import Any, Optional

from core.exceptions import QuoteError, ErrorCode
from core.logging import get_logger

logger = get_logger(__name__)

# SyncSwap Classic/Stable Pool ABI:
# getAmountOut(address tokenIn, uint256 amountIn, address sender) → uint256 amountOut
# keccak256("getAmountOut(address,uint256,address)")[:4] = 0x18a13086
SELECTOR_GET_AMOUNT_OUT = "0x18a13086"

# Zero address used as default sender (view-only call, sender not relevant for quoting)
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


def encode_get_amount_out(token_in: str, amount_in: int, sender: str = ZERO_ADDRESS) -> str:
    """Encode SyncSwap pool.getAmountOut(address, uint256, address) call data."""
    token_padded = token_in[2:].lower().zfill(64)
    amount_hex = hex(amount_in)[2:].zfill(64)
    sender_padded = sender[2:].lower().zfill(64)
    return f"{SELECTOR_GET_AMOUNT_OUT[2:]}{token_padded}{amount_hex}{sender_padded}"


def decode_get_amount_out(hex_result: str) -> int:
    """Decode getAmountOut response (single uint256)."""
    if not hex_result or hex_result == "0x":
        raise QuoteError(
            code=ErrorCode.QUOTE_REVERT,
            message="SyncSwap getAmountOut returned empty",
        )
    clean = hex_result.replace("0x", "")
    if len(clean) < 64:
        raise QuoteError(
            code=ErrorCode.QUOTE_REVERT,
            message=f"SyncSwap getAmountOut response too short: {len(clean)} hex chars",
        )
    return int(clean[:64], 16)


class SyncSwapAdapter:
    """
    SyncSwap adapter for Classic and Stable pools.

    Quotes directly on the pool contract via
    getAmountOut(address tokenIn, uint256 amountIn, address sender).
    No quoter contract needed — reads from the pool itself.
    """

    def __init__(self, provider: Any, router_address: str = "", dex_id: str = "syncswap"):
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
        Get quote from SyncSwap pool via getAmountOut().

        Returns dict with: amount_out, gas_estimate, quote_source
        """
        if not pool_address or not token_in:
            raise QuoteError(
                code=ErrorCode.QUOTE_REVERT,
                message="syncswap: pool_address and token_in required",
            )

        calldata = "0x" + encode_get_amount_out(token_in, amount_in)

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
                message=f"syncswap getAmountOut failed: {e}",
            )

        return {
            "amount_out": amount_out,
            "gas_estimate": 100_000,  # SyncSwap pools are slightly heavier than V2
            "quote_source": "syncswap_getAmountOut",
            "sqrt_price_after": 0,
            "ticks_crossed": 0,
        }

    def supports_fee_tiers(self) -> bool:
        """SyncSwap uses pool types (Classic/Stable), not fee tiers."""
        return False
