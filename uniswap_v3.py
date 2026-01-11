"""
dex/adapters/uniswap_v3.py - Uniswap V3 quoting adapter.

Implements quoting via QuoterV2 contract.
Supports:
- Single-hop quotes (quoteExactInputSingle)
- Fee tier selection
- Slippage/price impact from sqrtPriceX96
"""

from dataclasses import dataclass
from decimal import Decimal

from core.logging import get_logger
from core.models import Token, Pool, Quote
from core.time import now_ms
from core.exceptions import QuoteError, ErrorCode
from chains.providers import RPCProvider

logger = get_logger(__name__)


# =============================================================================
# ABI ENCODING
# =============================================================================

# Function selector: quoteExactInputSingle((address,address,uint256,uint24,uint160))
# keccak256("quoteExactInputSingle((address,address,uint256,uint24,uint160))")[:4]
SELECTOR_QUOTE_EXACT_INPUT_SINGLE = "0xc6a5026a"


def encode_quote_exact_input_single(
    token_in: str,
    token_out: str,
    amount_in: int,
    fee: int,
    sqrt_price_limit_x96: int = 0,
) -> str:
    """
    Encode quoteExactInputSingle call data for QuoterV2.
    
    QuoterV2 uses a struct parameter:
    struct QuoteExactInputSingleParams {
        address tokenIn;
        address tokenOut;
        uint256 amountIn;
        uint24 fee;
        uint160 sqrtPriceLimitX96;
    }
    
    For a tuple of static types, encoding is simply: selector + fields (no offset).
    """
    # Encode struct fields (each padded to 32 bytes)
    token_in_padded = token_in[2:].lower().zfill(64)
    token_out_padded = token_out[2:].lower().zfill(64)
    amount_in_hex = hex(amount_in)[2:].zfill(64)
    fee_hex = hex(fee)[2:].zfill(64)
    sqrt_price_hex = hex(sqrt_price_limit_x96)[2:].zfill(64)
    
    # Static tuple: selector + 5 words (no offset needed)
    return (
        f"{SELECTOR_QUOTE_EXACT_INPUT_SINGLE}"
        f"{token_in_padded}"
        f"{token_out_padded}"
        f"{amount_in_hex}"
        f"{fee_hex}"
        f"{sqrt_price_hex}"
    )


def decode_quote_response(hex_result: str) -> tuple[int, int, int, int]:
    """
    Decode quoteExactInputSingle response.
    
    Returns:
        (amountOut, sqrtPriceX96After, initializedTicksCrossed, gasEstimate)
    """
    if not hex_result or hex_result == "0x":
        raise QuoteError(
            code=ErrorCode.QUOTE_REVERT,
            message="Empty quote response",
        )
    
    # Remove 0x prefix
    data = hex_result[2:] if hex_result.startswith("0x") else hex_result
    
    # Response: (uint256 amountOut, uint160 sqrtPriceX96After, uint32 initializedTicksCrossed, uint256 gasEstimate)
    # Each value is 32 bytes (64 hex chars)
    if len(data) < 256:  # 4 * 64
        raise QuoteError(
            code=ErrorCode.QUOTE_REVERT,
            message=f"Quote response too short: {len(data)} chars",
            details={"data_length": len(data), "raw": hex_result[:100]},
        )
    
    amount_out = int(data[0:64], 16)
    sqrt_price_x96_after = int(data[64:128], 16)
    ticks_crossed = int(data[128:192], 16)
    gas_estimate = int(data[192:256], 16)
    
    return amount_out, sqrt_price_x96_after, ticks_crossed, gas_estimate


# =============================================================================
# ADAPTER
# =============================================================================

@dataclass
class UniswapV3QuoteResult:
    """Result from Uniswap V3 quote."""
    amount_out: int
    sqrt_price_x96_after: int
    ticks_crossed: int
    gas_estimate: int
    latency_ms: int


class UniswapV3Adapter:
    """
    Adapter for Uniswap V3 quoting via QuoterV2.
    
    Usage:
        adapter = UniswapV3Adapter(provider, quoter_address)
        quote = await adapter.get_quote(pool, token_in, token_out, amount_in)
    """
    
    def __init__(
        self,
        provider: RPCProvider,
        quoter_address: str,
        dex_id: str = "uniswap_v3",
    ):
        self.provider = provider
        self.quoter_address = quoter_address
        self.dex_id = dex_id
    
    async def get_quote_raw(
        self,
        token_in: str,
        token_out: str,
        amount_in: int,
        fee: int,
        block_number: int | None = None,
    ) -> UniswapV3QuoteResult:
        """
        Get raw quote from QuoterV2.
        
        Args:
            token_in: Input token address
            token_out: Output token address
            amount_in: Input amount in wei
            fee: Fee tier (100, 500, 3000, 10000)
            block_number: Block number to query at (None = latest)
            
        Returns:
            UniswapV3QuoteResult with amounts and gas estimate
        """
        call_data = encode_quote_exact_input_single(
            token_in=token_in,
            token_out=token_out,
            amount_in=amount_in,
            fee=fee,
        )
        
        # Block tag: hex(block_number) or "latest"
        block_tag = hex(block_number) if block_number else "latest"
        
        try:
            response = await self.provider.eth_call(
                to=self.quoter_address,
                data=call_data,
                block=block_tag,
            )
            
            amount_out, sqrt_price, ticks, gas = decode_quote_response(response.result)
            
            return UniswapV3QuoteResult(
                amount_out=amount_out,
                sqrt_price_x96_after=sqrt_price,
                ticks_crossed=ticks,
                gas_estimate=gas,
                latency_ms=response.latency_ms,
            )
            
        except QuoteError:
            raise
        except Exception as e:
            raise QuoteError(
                code=ErrorCode.QUOTE_REVERT,
                message=f"Quote call failed: {e}",
                details={
                    "token_in": token_in,
                    "token_out": token_out,
                    "amount_in": amount_in,
                    "fee": fee,
                    "quoter": self.quoter_address,
                    "call_data_len": len(call_data),
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
            block_number: Block number for the quote (used in eth_call)
            
        Returns:
            Quote model with all fields populated
        """
        # Determine direction
        if token_in.address.lower() == pool.token0.address.lower():
            direction = "0to1"
        else:
            direction = "1to0"
        
        # Get raw quote with pinned block
        result = await self.get_quote_raw(
            token_in=token_in.address,
            token_out=token_out.address,
            amount_in=amount_in,
            fee=pool.fee,
            block_number=block_number,
        )
        
        # Build Quote model with all V3-specific fields
        quote = Quote(
            pool=pool,
            direction=direction,
            amount_in=amount_in,
            amount_out=result.amount_out,
            token_in=token_in,
            token_out=token_out,
            timestamp_ms=now_ms(),
            block_number=block_number or 0,
            gas_estimate=result.gas_estimate,
            ticks_crossed=result.ticks_crossed,
            sqrt_price_x96_after=result.sqrt_price_x96_after,
            latency_ms=result.latency_ms,
        )
        
        logger.debug(
            f"Quote: {token_in.symbol}->{token_out.symbol} "
            f"{amount_in} -> {result.amount_out} "
            f"(fee={pool.fee}, ticks={result.ticks_crossed}, latency={result.latency_ms}ms)"
        )
        
        return quote
    
    async def get_quotes_multi_size(
        self,
        pool: Pool,
        token_in: Token,
        token_out: Token,
        amounts_in: list[int],
        block_number: int | None = None,
    ) -> list[Quote]:
        """
        Get quotes for multiple input sizes.
        
        Args:
            pool: Pool to quote
            token_in: Input token
            token_out: Output token
            amounts_in: List of input amounts in wei
            block_number: Block number for quotes
            
        Returns:
            List of Quote models
        """
        quotes = []
        for amount_in in amounts_in:
            try:
                quote = await self.get_quote(
                    pool=pool,
                    token_in=token_in,
                    token_out=token_out,
                    amount_in=amount_in,
                    block_number=block_number,
                )
                quotes.append(quote)
            except QuoteError as e:
                logger.warning(
                    f"Quote failed for amount {amount_in}: {e.message}"
                )
                # Continue with other sizes
        
        return quotes
