"""Curve StableSwap adapter for M9 graph-arb scanner.

Quotes Curve stable pools via direct RPC call to ``pool.get_dy(i, j, dx)``.

Supported pool types
--------------------
- 2-coin stable (e.g. USDC/USDT, USDC/DAI)
- 3-coin stable (e.g. 3pool: DAI/USDC/USDT)
- 4-coin stable / base pool variants

How it works
------------
Curve stable pools expose ``get_dy(i, j, dx) → dy`` (view function) that
returns the amount of token j received for dx of token i.  We encode the
call manually to avoid depending on an ABI file.

Selector: keccak256("get_dy(int128,int128,uint256)")[:4] = 0x5e0d443f
(old Vyper interface uses int128; newer pools use uint256 for indices)

The adapter tries the int128 selector first, then falls back to the uint256
variant (``get_dy(uint256,uint256,uint256)`` selector 0x4fb08c5e).

Integration with M9
-------------------
1. bridge_builder.py maps dex_id "curve" → adapter_type "curve_stable".
2. quote_probe.py needs a new elif branch for "curve_stable":
      route.pool_address → get_dy(route.token_in_index, route.token_out_index, amount_in)
   (token indices must be stored in the route from config/discovery; see DexRoute.fee
   field — fee is overloaded as token_in_index by convention, tick_spacing as token_out_index)
3. cost_model.py already maps "curve_stable" → 3.0 bps.

Configuration (config/dexes.yaml or discovery)
----------------------------------------------
Curve pools should be onboarded with:
  dex_id: curve
  adapter_type: curve_stable
  pool_address: <pool>
  token_in_index: <i>   (stored in fee field, range 0-3)
  token_out_index: <j>  (stored in tick_spacing field, range 0-3)

Known Curve pools on Base (as of 2026-05)
------------------------------------------
  - 4pool (USDC/USDT/DAI/USDe): 0x0Def4d2Cbfb4E5B6D70C0B6E22c1dC3c33FC37Fa  (verify on Basescan)
  - crvUSD/USDC:               (check https://curve.finance/#/base/pools)

Note: pool addresses must be verified on-chain before adding to base inventory.
"""
from __future__ import annotations

from typing import Optional, Any

from core.logging import get_logger
from core.exceptions import QuoteError, ErrorCode

logger = get_logger(__name__)

# Selector: get_dy(int128,int128,uint256) — used by older Curve/Vyper contracts
_SELECTOR_GET_DY_INT128 = bytes.fromhex("5e0d443f")
# Selector: get_dy(uint256,uint256,uint256) — used by newer Curve pool contracts
_SELECTOR_GET_DY_UINT256 = bytes.fromhex("4fb08c5e")


def encode_get_dy(i: int, j: int, dx: int, *, use_uint256: bool = False) -> bytes:
    """Encode a Curve pool get_dy(i, j, dx) call.

    Parameters
    ----------
    i, j:
        Token indices (0-3).
    dx:
        Amount of token i (raw, in token's native decimals).
    use_uint256:
        When True, uses the uint256-indexed selector instead of int128.
    """
    selector = _SELECTOR_GET_DY_UINT256 if use_uint256 else _SELECTOR_GET_DY_INT128
    i_enc = i.to_bytes(32, "big")
    j_enc = j.to_bytes(32, "big")
    dx_enc = dx.to_bytes(32, "big")
    return selector + i_enc + j_enc + dx_enc


def decode_get_dy(hex_result: str) -> int:
    """Decode get_dy response (single uint256 = amount out)."""
    raw = hex_result[2:] if hex_result.startswith("0x") else hex_result
    if len(raw) < 64:
        raise QuoteError(
            code=ErrorCode.QUOTE_REVERT,
            message=f"curve get_dy response too short: {len(raw)} hex chars",
        )
    return int(raw[:64], 16)


class CurveStableAdapter:
    """Adapter for Curve StableSwap pools.

    Quotes via ``pool.get_dy(i, j, dx)`` RPC call.
    Tries int128 selector first, falls back to uint256 on revert.

    Parameters
    ----------
    provider:
        Provider object with ``eth_call(to, data, block) -> str`` method.
    dex_id:
        DEX identifier (default "curve").
    """

    ADAPTER_TYPE: str = "curve_stable"

    def __init__(self, provider: Any, dex_id: str = "curve") -> None:
        self.provider = provider
        self.dex_id = dex_id

    def get_quote(
        self,
        pool_address: str,
        token_in: str,
        token_out: str,
        amount_in: int,
        token_in_index: int = 0,
        token_out_index: int = 1,
        fee: Optional[int] = None,          # ignored for Curve
        block_number: Optional[int] = None,
    ) -> dict:
        """Quote via Curve pool get_dy(i, j, dx).

        Parameters
        ----------
        pool_address:
            Curve pool contract address.
        token_in, token_out:
            Token addresses (not used in the call but kept for API consistency).
        amount_in:
            Token-in amount (raw, in token's native decimals).
        token_in_index:
            Index of token_in in the pool's coin list (0-based).
        token_out_index:
            Index of token_out in the pool's coin list (0-based).
        """
        if not pool_address:
            raise QuoteError(
                code=ErrorCode.QUOTE_REVERT,
                message="curve: pool_address required",
            )
        if token_in_index == token_out_index:
            raise QuoteError(
                code=ErrorCode.QUOTE_REVERT,
                message=f"curve: token_in_index == token_out_index = {token_in_index}",
            )
        if amount_in <= 0:
            raise QuoteError(
                code=ErrorCode.QUOTE_REVERT,
                message=f"curve: amount_in must be positive, got {amount_in}",
            )

        # Try int128 selector first
        for use_u256 in (False, True):
            calldata = "0x" + encode_get_dy(
                token_in_index, token_out_index, amount_in, use_uint256=use_u256
            ).hex()
            try:
                result = self.provider.eth_call(
                    to=pool_address,
                    data=calldata,
                    block=block_number,
                )
                amount_out = decode_get_dy(result)
                if amount_out > 0:
                    return {
                        "amount_out": amount_out,
                        "gas_estimate": 100_000,  # Curve stable math is gas-moderate
                        "quote_source": f"curve_stable_get_dy_{'uint256' if use_u256 else 'int128'}",
                        "adapter_type": self.ADAPTER_TYPE,
                        "token_in_index": token_in_index,
                        "token_out_index": token_out_index,
                        "sqrt_price_after": 0,
                        "ticks_crossed": 0,
                    }
                # amount_out == 0 with success → raise so caller handles QUOTE_ZERO_OUTPUT
                raise QuoteError(
                    code=ErrorCode.QUOTE_REVERT,
                    message=f"curve get_dy returned 0 for pool {pool_address}",
                )
            except QuoteError:
                if not use_u256:
                    # Retry with uint256 selector
                    continue
                raise
            except Exception as e:
                if not use_u256:
                    continue
                raise QuoteError(
                    code=ErrorCode.QUOTE_REVERT,
                    message=f"curve get_dy failed: {e}",
                ) from e

        # Should not reach here
        raise QuoteError(
            code=ErrorCode.QUOTE_REVERT,
            message=f"curve get_dy failed for pool {pool_address} (both selectors)",
        )

    def supports_fee_tiers(self) -> bool:
        """Curve stable pools do not use discrete fee tiers."""
        return False
