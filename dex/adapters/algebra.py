"""
dex/adapters/algebra.py - Algebra V3 (Camelot) adapter.

Algebra V3 is a fork of Uniswap V3 with dynamic fees.
Used by Camelot DEX on Arbitrum.

Key differences from Uniswap V3:
- No fixed fee tiers (dynamic fees based on volatility)
- Different quoter interface
- Pool address computed differently
"""

from dataclasses import dataclass
import time

from core.logging import get_logger
from core.exceptions import ErrorCode, QuoteError
from core.models import Token, Pool, Quote
from core.time import now_ms
from chains.providers import RPCProvider

logger = get_logger(__name__)


# =============================================================================
# ABI ENCODING (Algebra Quoter V1)
# =============================================================================

# Algebra Quoter.quoteExactInputSingle selector
# function quoteExactInputSingle(address tokenIn, address tokenOut, uint256 amountIn, uint160 limitSqrtPrice)
# Returns: (uint256 amountOut, uint16 fee)
# Selector: keccak256("quoteExactInputSingle(address,address,uint256,uint160)")[:4] = 0x2d9ebd1d
SELECTOR_QUOTE_EXACT_INPUT_SINGLE = "2d9ebd1d"


def encode_quote_exact_input_single(
    token_in: str,
    token_out: str,
    amount_in: int,
    limit_sqrt_price: int = 0,
) -> str:
    """
    Encode quoteExactInputSingle call for Algebra Quoter V1.
    
    Algebra V1 Quoter signature:
    quoteExactInputSingle(address tokenIn, address tokenOut, uint256 amountIn, uint160 limitSqrtPrice)
    returns (uint256 amountOut, uint16 fee)
    
    Note: Algebra doesn't use fee tiers - fee is returned by quoter.
    """
    # Remove 0x and pad to 32 bytes
    token_in_padded = token_in.lower().replace("0x", "").zfill(64)
    token_out_padded = token_out.lower().replace("0x", "").zfill(64)
    amount_in_hex = hex(amount_in)[2:].zfill(64)
    limit_sqrt_price_hex = hex(limit_sqrt_price)[2:].zfill(64)
    
    return (
        f"0x{SELECTOR_QUOTE_EXACT_INPUT_SINGLE}"
        f"{token_in_padded}"
        f"{token_out_padded}"
        f"{amount_in_hex}"
        f"{limit_sqrt_price_hex}"
    )


def decode_quote_response(hex_result: str) -> tuple[int, int]:
    """
    Decode Algebra quoteExactInputSingle response.
    
    Returns:
        (amountOut, fee)
    """
    if not hex_result or hex_result == "0x":
        raise QuoteError(
            code=ErrorCode.QUOTE_REVERT,
            message="Empty Algebra quote response",
        )
    
    # Remove 0x prefix
    data = hex_result[2:] if hex_result.startswith("0x") else hex_result
    
    # Response: (uint256 amountOut, uint16 fee)
    # amountOut: 32 bytes, fee: 32 bytes (padded)
    if len(data) < 128:  # 2 * 64
        raise QuoteError(
            code=ErrorCode.QUOTE_REVERT,
            message=f"Algebra quote response too short: {len(data)} chars",
            details={"data_length": len(data), "raw": hex_result[:100]},
        )
    
    amount_out = int(data[0:64], 16)
    fee = int(data[64:128], 16)
    
    return amount_out, fee


# =============================================================================
# ADAPTER
# =============================================================================

@dataclass
class AlgebraQuoteResult:
    """Result from Algebra quote."""
    amount_out: int
    fee: int  # Dynamic fee in hundredths of bip
    latency_ms: int


class AlgebraAdapter:
    """
    Adapter for Algebra V3 (Camelot) quoting.
    
    Usage:
        adapter = AlgebraAdapter(provider, quoter_address)
        quote = await adapter.get_quote(pool, token_in, token_out, amount_in)
    """
    
    def __init__(
        self,
        provider: RPCProvider,
        quoter_address: str,
        dex_id: str = "camelot_v3",
    ):
        self.provider = provider
        self.quoter_address = quoter_address
        self.dex_id = dex_id
    
    async def get_quote_raw(
        self,
        token_in: str,
        token_out: str,
        amount_in: int,
        block_number: int | None = None,
    ) -> AlgebraQuoteResult:
        """
        Get raw quote from Algebra QuoterV2.
        
        Args:
            token_in: Input token address
            token_out: Output token address
            amount_in: Input amount in wei
            block_number: Block number to query at (None = latest)
            
        Returns:
            AlgebraQuoteResult with amounts and dynamic fee
        """
        call_data = encode_quote_exact_input_single(
            token_in=token_in,
            token_out=token_out,
            amount_in=amount_in,
        )
        
        block_tag = hex(block_number) if block_number else "latest"
        
        try:
            start_ms = int(time.time() * 1000)
            response = await self.provider.eth_call(
                to=self.quoter_address,
                data=call_data,
                block=block_tag,
            )
            latency_ms = int(time.time() * 1000) - start_ms
            
            # Check for RPC-level error
            if response.result is None:
                raise QuoteError(
                    code=ErrorCode.QUOTE_REVERT,
                    message="Algebra quote returned null result",
                    details={
                        "quoter": self.quoter_address,
                        "block_tag": block_tag,
                        "call_data_prefix": call_data[:18],  # selector + first bytes
                    },
                )
            
            amount_out, fee = decode_quote_response(response.result)
            
            return AlgebraQuoteResult(
                amount_out=amount_out,
                fee=fee,
                latency_ms=latency_ms,
            )
            
        except QuoteError:
            raise
        except Exception as e:
            # Capture full error context for debugging
            error_msg = str(e)
            raise QuoteError(
                code=ErrorCode.QUOTE_REVERT,
                message=f"Algebra quote call failed: {error_msg}",
                details={
                    "token_in": token_in,
                    "token_out": token_out,
                    "amount_in": amount_in,
                    "quoter": self.quoter_address,
                    "block_tag": block_tag,
                    "call_data_prefix": call_data[:18],
                    "error_type": type(e).__name__,
                    "error_message": error_msg,
                },
            )
    
    async def get_quote(
        self,
        pool: Pool,
        token_in: Token,
        token_out: Token,
        amount_in: int,
        block_number: int | None = None,
    ) -> Quote:
        """
        Get quote for a pool.
        
        Args:
            pool: Pool to quote
            token_in: Input token
            token_out: Output token
            amount_in: Input amount in wei
            block_number: Block number for the quote
            
        Returns:
            Quote model with all fields populated
        """
        # Determine direction
        if token_in.address.lower() == pool.token0.address.lower():
            direction = "0to1"
        else:
            direction = "1to0"
        
        # Get raw quote
        result = await self.get_quote_raw(
            token_in=token_in.address,
            token_out=token_out.address,
            amount_in=amount_in,
            block_number=block_number,
        )
        
        # Algebra doesn't report gas estimate in quote, use estimate
        # Typical Algebra swap: 150k-250k gas
        gas_estimate = 200_000
        
        quote = Quote(
            pool=pool,
            direction=direction,
            amount_in=amount_in,
            amount_out=result.amount_out,
            token_in=token_in,
            token_out=token_out,
            timestamp_ms=now_ms(),
            block_number=block_number if block_number else 0,
            gas_estimate=gas_estimate,
            ticks_crossed=0,  # Algebra doesn't report this; default to 0
            sqrt_price_x96_after=None,
            latency_ms=result.latency_ms,
        )
        
        logger.debug(
            f"Algebra quote: {token_in.symbol}->{token_out.symbol} "
            f"{amount_in} -> {result.amount_out} "
            f"(fee={result.fee}, latency={result.latency_ms}ms)"
        )
        
        return quote
