# PATH: dex/adapters/ve33.py
"""
ve33 / Solidly-style quoting adapter.

Implements quoting via direct pool getAmountOut() calls.
Supports:
- Aerodrome volatile pools  (x*y=k variant, high-fee)
- Aerodrome stable pools    (x^3*y + x*y^3 = k, peg-preserving, low cost)
- Stratum (Mantle), Velodrome, and other Solidly forks

ve33 pools do NOT use fee tiers — pricing is per-pool (stable vs volatile).
Quote method: pool.getAmountOut(amountIn, tokenIn) -> amountOut
  (The pool contract itself applies the correct invariant branch.)

Ve33StableAdapter also exposes a pure-Python ``verify_stable_k`` helper that
computes the Solidly stable invariant value so unit tests can validate math
without an RPC connection.
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


# ---------------------------------------------------------------------------
# Stable invariant helpers (pure Python — no RPC, used for tests + diagnostics)
# ---------------------------------------------------------------------------

def stable_k(x: int, y: int) -> int:
    """Compute the Solidly stable invariant k = x³·y + x·y³.

    Equivalent to ``x·y·(x² + y²)``.
    Works on raw token units (no decimal normalisation needed for equality check).
    """
    return x * x * x * y + x * y * y * y


def verify_stable_k(
    reserve_x: int,
    reserve_y: int,
    amount_in: int,
    amount_out: int,
    *,
    fee_bps: int = 1,
) -> bool:
    """Verify that a stable-swap quote preserves the Solidly invariant.

    Applies a 0.01% fee (1 bps) by default, matching Aerodrome stable pools.
    Returns True when the post-trade k is >= the pre-trade k (net of fee rounding).

    This is a *diagnostic helper* for unit tests.  The authoritative quote
    comes from the on-chain ``getAmountOut()`` call.

    Parameters
    ----------
    reserve_x, reserve_y:
        Pool reserves in token units (raw, no decimals applied).
    amount_in:
        Token-in amount (raw).
    amount_out:
        Expected token-out amount from the pool (raw).
    fee_bps:
        Fee in basis points (default 1 = 0.01%).
    """
    fee_denom = 10_000
    # Amount that enters reserves: full amount_in minus fee
    amount_in_net = amount_in * (fee_denom - fee_bps) // fee_denom
    k_before = stable_k(reserve_x, reserve_y)
    k_after = stable_k(reserve_x + amount_in_net, reserve_y - amount_out)
    # Post-trade k must be at least as large as pre-trade k (rounding tolerance 1 unit)
    return k_after + 1 >= k_before


class Ve33StableAdapter(Ve33Adapter):
    """Adapter for Aerodrome/Solidly *stable* pools (``x³y + xy³ = k``).

    Quoting uses the same ``pool.getAmountOut(amountIn, tokenIn)`` RPC call
    as the volatile adapter because the pool contract itself implements the
    correct invariant.

    The distinction matters for:
    - Cost model: stable pools have lower slippage → cheaper (4 bps vs 12 bps).
    - Adapter family tagging in M9 artifact breakdowns.
    - Unit test math verification via ``verify_stable_k()``.
    """

    ADAPTER_TYPE: str = "ve33_stable"

    def __init__(
        self,
        provider: Any,
        router_address: str = "",
        dex_id: str = "aerodrome_v2_stable",
    ) -> None:
        super().__init__(provider, router_address=router_address, dex_id=dex_id)

    def get_quote(
        self,
        pool_address: str,
        token_in: str,
        token_out: str,
        amount_in: int,
        fee: Optional[int] = None,
        block_number: Optional[int] = None,
    ) -> dict:
        """Quote via on-chain getAmountOut() — stable pool variant.

        Identical to Ve33Adapter.get_quote() but tags ``quote_source`` with
        ``ve33_stable_getAmountOut`` so downstream cost model can apply the
        lower cost estimate.
        """
        result = super().get_quote(
            pool_address=pool_address,
            token_in=token_in,
            token_out=token_out,
            amount_in=amount_in,
            fee=fee,
            block_number=block_number,
        )
        result["quote_source"] = "ve33_stable_getAmountOut"
        result["adapter_type"] = self.ADAPTER_TYPE
        result["gas_estimate"] = 90_000  # stable math is slightly more expensive
        return result
