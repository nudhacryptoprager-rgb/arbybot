"""
dex/adapters/aerodrome_slipstream.py — Aerodrome Slipstream (CL) quoting adapter.

Aerodrome Slipstream is a concentrated-liquidity DEX on Base, derived from
Uniswap V3 but with `tickSpacing` driving the pool identity instead of `fee`.
Each pool's fee is stored per-pool (often dynamic), so the pool is located by
(tokenA, tokenB, tickSpacing) rather than (tokenA, tokenB, fee).

Differences vs. UniswapV3Adapter:
- QuoterV2 struct param uses `int24 tickSpacing` instead of `uint24 fee`.
  ABI static-tuple encoding is byte-identical for non-negative values
  (tickSpacing is always > 0 in practice), so the selector still resolves.
- Factory.getPool(tokenA, tokenB, tickSpacing) returns the pool address.
- Known on-chain tickSpacing values on Base: {1, 50, 100, 200, 2000}.
  Per-pool fees (bps) observed: {1, 5, 30, 100, 500, 1000, 3000, ...}.

Status (E1.35 P1.1):
- Calldata encoding + quote decoding: IMPLEMENTED + unit-tested.
- Quoter/router addresses: config-driven via `config/dexes.yaml`
  (aerodrome_slipstream entry).  Execution-side wiring into
  `m7/orderflow/execution_gate.py` is a follow-up step (not this patch).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from core.exceptions import ErrorCode, QuoteError
from core.logging import get_logger
from core.models import Pool, Quote, Token
from core.time import now_ms

logger = get_logger(__name__)


# =============================================================================
# ABI ENCODING
# =============================================================================

# Slipstream QuoterV2 ABI derived from
#   struct QuoteExactInputSingleParams {
#       address tokenIn;
#       address tokenOut;
#       uint256 amountIn;
#       int24   tickSpacing;      # <-- was `uint24 fee` in Uniswap V3
#       uint160 sqrtPriceLimitX96;
#   }
# keccak256("quoteExactInputSingle((address,address,uint256,int24,uint160))")[:4]
# Per Slipstream repo (velodrome-finance/slipstream) the selector is
# 0xbd6d894d.  We hold it here as a constant; tests verify it does not drift.
SELECTOR_QUOTE_EXACT_INPUT_SINGLE_SLIPSTREAM = "0xbd6d894d"


def encode_quote_exact_input_single(
    token_in: str,
    token_out: str,
    amount_in: int,
    tick_spacing: int,
    sqrt_price_limit_x96: int = 0,
) -> str:
    """Encode Slipstream QuoterV2.quoteExactInputSingle(struct) calldata.

    The struct is static-only so the tuple is laid out inline (no offset
    pointer), identical to Uniswap V3 QuoterV2.

    Parameters
    ----------
    token_in, token_out : hex-address strings (checksummed or lower-case).
    amount_in : uint256 wei.
    tick_spacing : int24 > 0.  Slipstream uses signed int24; we encode as
        two's-complement just like a uint24 for the positive range.
    sqrt_price_limit_x96 : uint160, 0 = no limit.
    """
    if tick_spacing <= 0:
        raise QuoteError(
            code=ErrorCode.QUOTE_REVERT,
            message=f"tick_spacing must be positive, got {tick_spacing}",
        )
    if tick_spacing >= (1 << 23):  # int24 positive range cap
        raise QuoteError(
            code=ErrorCode.QUOTE_REVERT,
            message=f"tick_spacing out of int24 range: {tick_spacing}",
        )

    token_in_padded = token_in[2:].lower().zfill(64)
    token_out_padded = token_out[2:].lower().zfill(64)
    amount_in_hex = hex(amount_in)[2:].zfill(64)
    tick_spacing_hex = hex(tick_spacing)[2:].zfill(64)
    sqrt_price_hex = hex(sqrt_price_limit_x96)[2:].zfill(64)

    return (
        f"{SELECTOR_QUOTE_EXACT_INPUT_SINGLE_SLIPSTREAM}"
        f"{token_in_padded}"
        f"{token_out_padded}"
        f"{amount_in_hex}"
        f"{tick_spacing_hex}"
        f"{sqrt_price_hex}"
    )


def decode_quote_response(hex_result: str) -> tuple[int, int, int, int]:
    """Decode Slipstream quoteExactInputSingle response.

    Response layout matches Uniswap V3 QuoterV2:
      (uint256 amountOut, uint160 sqrtPriceX96After,
       uint32  initializedTicksCrossed, uint256 gasEstimate)
    """
    if not hex_result or hex_result == "0x":
        raise QuoteError(
            code=ErrorCode.QUOTE_REVERT,
            message="Empty Slipstream quote response",
        )

    data = hex_result[2:] if hex_result.startswith("0x") else hex_result
    if len(data) < 256:
        raise QuoteError(
            code=ErrorCode.QUOTE_REVERT,
            message=f"Slipstream quote response too short: {len(data)} chars",
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
class AerodromeSlipstreamQuoteResult:
    amount_out: int
    sqrt_price_x96_after: int
    ticks_crossed: int
    gas_estimate: int
    latency_ms: int


class AerodromeSlipstreamAdapter:
    """Adapter for Aerodrome Slipstream (CL) quoting via QuoterV2.

    Pool identity is (tokenA, tokenB, tickSpacing).  The pool's runtime fee
    is read from the pool contract itself; the adapter does not require it
    at quote-time (QuoterV2 simulates the swap end-to-end).

    Parameters
    ----------
    provider : chains.providers.RPCProvider
    quoter_address : Slipstream QuoterV2 contract address.
    dex_id : registry key, default "aerodrome_slipstream".
    """

    def __init__(
        self,
        provider,
        quoter_address: str,
        dex_id: str = "aerodrome_slipstream",
    ) -> None:
        self.provider = provider
        self.quoter_address = quoter_address
        self.dex_id = dex_id

    async def get_quote_raw(
        self,
        token_in: str,
        token_out: str,
        amount_in: int,
        tick_spacing: int,
        block_number: Optional[int] = None,
    ) -> AerodromeSlipstreamQuoteResult:
        call_data = encode_quote_exact_input_single(
            token_in=token_in,
            token_out=token_out,
            amount_in=amount_in,
            tick_spacing=tick_spacing,
        )
        block_tag = hex(block_number) if block_number else "latest"

        try:
            response = await self.provider.eth_call(
                to=self.quoter_address,
                data=call_data,
                block=block_tag,
            )
            amount_out, sqrt_price, ticks, gas = decode_quote_response(
                response.result
            )
            return AerodromeSlipstreamQuoteResult(
                amount_out=amount_out,
                sqrt_price_x96_after=sqrt_price,
                ticks_crossed=ticks,
                gas_estimate=gas,
                latency_ms=response.latency_ms,
            )
        except QuoteError:
            raise
        except Exception as exc:  # pragma: no cover — defensive
            raise QuoteError(
                code=ErrorCode.QUOTE_REVERT,
                message=f"Slipstream quote call failed: {exc}",
                details={
                    "token_in": token_in,
                    "token_out": token_out,
                    "amount_in": amount_in,
                    "tick_spacing": tick_spacing,
                    "quoter": self.quoter_address,
                },
            )

    async def get_quote(
        self,
        pool: Pool,
        token_in: Token,
        token_out: Token,
        amount_in: int,
        block_number: Optional[int] = None,
    ) -> Quote:
        # Direction same as uniswap_v3.
        if token_in.address.lower() == pool.token0.address.lower():
            direction = "0to1"
        else:
            direction = "1to0"

        # In Slipstream, Pool.fee semantics differ from Uniswap V3 (per-pool
        # configured fee in pips), but pool identity is tickSpacing.  We
        # accept tick_spacing either from `pool.tick_spacing` (preferred)
        # or fall back to `pool.fee` if callers have routed it there.
        tick_spacing = getattr(pool, "tick_spacing", None) or pool.fee
        if not tick_spacing or tick_spacing <= 0:
            raise QuoteError(
                code=ErrorCode.QUOTE_REVERT,
                message=f"Pool {pool} missing tick_spacing for Slipstream",
            )

        result = await self.get_quote_raw(
            token_in=token_in.address,
            token_out=token_out.address,
            amount_in=amount_in,
            tick_spacing=int(tick_spacing),
            block_number=block_number,
        )

        return Quote(
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
