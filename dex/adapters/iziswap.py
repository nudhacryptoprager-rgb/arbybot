# PATH: dex/adapters/iziswap.py
# R36: iZUMi Finance (iZiSwap) real adapter.
# iZUMi uses "Discretized Concentrated Liquidity" (liquidity boxes).
# Deployed on: Scroll, zkSync, Linea, BNB, Mantle, and others.
# Docs: https://docs.izumi.finance/
#
# Quoting via Quoter.swapAmount(uint128 amount, address tokenX, address tokenY, uint24 fee, bool sellXEarnY)
# Returns: (uint256 acquire, int24 pointAfter)
from typing import Any, Optional

from core.exceptions import QuoteError, ErrorCode
from core.logging import get_logger

logger = get_logger(__name__)

# iZiSwap Quoter ABI:
# swapAmount(uint128 amount, address tokenX, address tokenY, uint24 fee, bool sellXEarnY)
# → (uint256 acquire, int24 pointAfter)
# NOTE: tokenX < tokenY always (sorted by address), sellXEarnY indicates direction
#
# keccak256("swapAmount(uint128,address,address,uint24,bool)")[:4]
SELECTOR_SWAP_AMOUNT = "0x75ceafe6"

MAX_UINT128 = (1 << 128) - 1


def encode_swap_amount(
    amount: int, token_x: str, token_y: str, fee: int, sell_x_earn_y: bool
) -> str:
    """Encode iZiSwap Quoter.swapAmount() call data."""
    amount_hex = hex(min(amount, MAX_UINT128))[2:].zfill(64)
    token_x_padded = token_x[2:].lower().zfill(64)
    token_y_padded = token_y[2:].lower().zfill(64)
    fee_hex = hex(fee)[2:].zfill(64)
    bool_hex = "0000000000000000000000000000000000000000000000000000000000000001" if sell_x_earn_y else "0" * 64
    return f"{SELECTOR_SWAP_AMOUNT[2:]}{amount_hex}{token_x_padded}{token_y_padded}{fee_hex}{bool_hex}"


def decode_swap_amount(hex_result: str) -> tuple[int, int]:
    """Decode swapAmount response: (uint256 acquire, int24 pointAfter)."""
    if not hex_result or hex_result == "0x":
        raise QuoteError(
            code=ErrorCode.QUOTE_REVERT,
            message="iZiSwap swapAmount returned empty",
        )
    clean = hex_result.replace("0x", "")
    if len(clean) < 128:  # 2 * 64
        raise QuoteError(
            code=ErrorCode.QUOTE_REVERT,
            message=f"iZiSwap swapAmount response too short: {len(clean)} hex chars",
        )
    acquire = int(clean[0:64], 16)
    # pointAfter is int24 (signed)
    point_raw = int(clean[64:128], 16)
    if point_raw >= (1 << 255):
        point_raw -= (1 << 256)
    return acquire, point_raw


class IziSwapAdapter:
    """
    iZUMi Finance adapter for Discretized Concentrated Liquidity.

    Quotes via the Quoter contract's swapAmount() method.
    Uses fee tiers similar to Uniswap V3.
    """

    def __init__(self, provider: Any, quoter_address: str = "", dex_id: str = "iziswap"):
        self.provider = provider
        self.quoter_address = quoter_address
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
        Get quote from iZiSwap via Quoter.swapAmount().

        Returns dict with: amount_out, gas_estimate, quote_source, point_after
        """
        if not self.quoter_address or not token_in or not token_out:
            raise QuoteError(
                code=ErrorCode.QUOTE_REVERT,
                message="iziswap: quoter_address, token_in, and token_out required",
            )

        if fee is None:
            fee = 3000  # default fee tier

        # iZiSwap convention: tokenX < tokenY (sorted by address)
        token_in_lower = token_in.lower()
        token_out_lower = token_out.lower()
        sell_x_earn_y = token_in_lower < token_out_lower

        token_x = min(token_in, token_out, key=str.lower)
        token_y = max(token_in, token_out, key=str.lower)

        calldata = "0x" + encode_swap_amount(amount_in, token_x, token_y, fee, sell_x_earn_y)

        try:
            result = self.provider.eth_call(
                to=self.quoter_address,
                data=calldata,
                block=block_number,
            )
            acquire, point_after = decode_swap_amount(result)
        except QuoteError:
            raise
        except Exception as e:
            raise QuoteError(
                code=ErrorCode.QUOTE_REVERT,
                message=f"iziswap swapAmount failed: {e}",
            )

        return {
            "amount_out": acquire,
            "gas_estimate": 150_000,  # iZiSwap is slightly heavier than UniV3
            "quote_source": "iziswap_swapAmount",
            "sqrt_price_after": 0,
            "ticks_crossed": 0,
            "point_after": point_after,
        }

    def supports_fee_tiers(self) -> bool:
        """iZUMi uses fee tiers similar to Uniswap V3."""
        return True
