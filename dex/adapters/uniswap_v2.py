# PATH: dex/adapters/uniswap_v2.py
"""
Uniswap V2 quoting adapter.

Implements quoting via direct pair getReserves() + constant product formula.
Supports:
- Uniswap V2 and forks (SushiSwap V2, PancakeSwap V2, etc.)
- Standard 0.3% fee (30 bps), configurable per-call

Quote method: pair.getReserves() -> (reserve0, reserve1), then calculate output.
No quoter contract needed — reads reserves from the pair itself.
"""

from typing import Optional, Any

from core.logging import get_logger
from core.exceptions import QuoteError, ErrorCode

logger = get_logger(__name__)

# =============================================================================
# ABI ENCODING
# =============================================================================

# getReserves() -> (uint112 reserve0, uint112 reserve1, uint32 blockTimestampLast)
# keccak256("getReserves()")[:4] = 0x0902f1ac
SELECTOR_GET_RESERVES = "0x0902f1ac"


def encode_get_reserves() -> str:
    """Encode getReserves() call data (no args)."""
    return SELECTOR_GET_RESERVES


def decode_get_reserves(hex_result: str) -> tuple[int, int, int]:
    """
    Decode getReserves response.

    Returns:
        (reserve0, reserve1, blockTimestampLast)
    """
    if not hex_result or hex_result == "0x":
        raise QuoteError(
            code=ErrorCode.QUOTE_REVERT,
            message="V2 getReserves returned empty",
        )
    clean = hex_result[2:] if hex_result.startswith("0x") else hex_result
    if len(clean) < 192:  # 3 * 64 hex chars
        raise QuoteError(
            code=ErrorCode.QUOTE_REVERT,
            message=f"V2 getReserves response too short: {len(clean)} hex chars",
        )
    reserve0 = int(clean[0:64], 16)
    reserve1 = int(clean[64:128], 16)
    block_ts = int(clean[128:192], 16)
    return reserve0, reserve1, block_ts


def calculate_v2_output(
    amount_in: int, reserve_in: int, reserve_out: int, fee_bps: int = 30
) -> int:
    """
    Calculate V2 output using constant product formula.

    Standard V2 fee is 0.3% (30 bps).
    amountOut = (amountIn * (10000 - fee_bps) * reserveOut) /
                (reserveIn * 10000 + amountIn * (10000 - fee_bps))
    """
    if reserve_in == 0 or reserve_out == 0:
        return 0
    amount_in_with_fee = amount_in * (10000 - fee_bps)
    numerator = amount_in_with_fee * reserve_out
    denominator = reserve_in * 10000 + amount_in_with_fee
    return numerator // denominator


# =============================================================================
# ADAPTER
# =============================================================================


class UniswapV2Adapter:
    """
    Adapter for Uniswap V2 and forks.

    Quotes via direct pair getReserves() + constant product formula.
    No quoter contract needed — reads reserves from the pair itself.
    """

    def __init__(self, provider: Any, router_address: str = "", dex_id: str = "uniswap_v2"):
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
        Get quote from V2 pair via getReserves() + constant product.

        Args:
            pool_address: V2 pair contract address
            token_in: Input token address
            token_out: Output token address
            amount_in: Input amount in wei
            fee: Fee in bps (default 30 = 0.3%)
            block_number: Block number to query at

        Returns:
            dict with: amount_out, gas_estimate, quote_source, sqrt_price_after, ticks_crossed
        """
        if not pool_address or not token_in:
            raise QuoteError(
                code=ErrorCode.QUOTE_REVERT,
                message="V2: pool_address and token_in required",
            )

        calldata = encode_get_reserves()

        try:
            result = self.provider.eth_call(
                to=pool_address,
                data=calldata,
                block=block_number,
            )
            reserve0, reserve1, _ = decode_get_reserves(result)
        except QuoteError:
            raise
        except Exception as e:
            raise QuoteError(
                code=ErrorCode.QUOTE_REVERT,
                message=f"V2 getReserves failed: {e}",
            )

        # V2 pair invariant: token0 < token1 by address
        token_in_lower = token_in.lower()
        token_out_lower = token_out.lower()

        if token_in_lower < token_out_lower:
            reserve_in, reserve_out = reserve0, reserve1
        else:
            reserve_in, reserve_out = reserve1, reserve0

        fee_bps = fee if fee is not None else 30
        amount_out = calculate_v2_output(amount_in, reserve_in, reserve_out, fee_bps)

        return {
            "amount_out": amount_out,
            "gas_estimate": 60_000,
            "quote_source": "v2_getReserves",
            "sqrt_price_after": 0,
            "ticks_crossed": 0,
        }

    def supports_fee_tiers(self) -> bool:
        """V2 pools have a fixed fee (typically 0.3%)."""
        return False
