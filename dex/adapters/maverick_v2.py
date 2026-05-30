# PATH: dex/adapters/maverick_v2.py
"""Maverick V2 directional-liquidity adapter for M9 pricing taxonomy.

Maverick V2 introduces *bins* (directional liquidity modes) where LPs can
concentrate liquidity in a way that automatically shifts with price movement.
Unlike Uniswap V3 static ticks, Maverick bins can be set to ``mode=both``,
``mode=left`` (follows price down), or ``mode=right`` (follows price up).

Quoting uses the PoolInformation view contract which off-chains the swap
simulation:

    ``calculateSwap(pool, amount, tokenAIn, exactOutput, sqrtPriceLimit)``

Maverick V2 on Base
--------------------
- Router / Position Manager: ``0x32AED3Bce901DA12ca8489788F3A99fCe1056e14``
- PoolInformation (``calculateSwap``): ``0x67b70f73BeE50AB48F0e8d75b94d4F6dCed6Ad72``
- Factory: ``0x0A7e848Aca42d879EF06507Fca0E7b33A0a63c1E``

Function selectors (keccak256 of ABI signature):
- ``calculateSwap(address,uint128,bool,bool,uint256)`` → ``0x2764cd0b``
- ``tokenA()``  → ``0x0fc63d10``
- ``tokenB()``  → ``0x5f64b55b``

Token ordering
--------------
Each pool has a fixed tokenA and tokenB.  The direction flag ``tokenAIn``
must be ``True`` when swapping tokenA→tokenB.  This ordering is stored in
``config/adapter_metadata.yaml`` as ``token_a: <address>`` per pool (resolved
by ``m9/graph_arb/builder.py`` and stored as a field on the inventory route).

If ``token_a`` is not configured for a pool, the adapter falls back to a live
``eth_call tokenA()`` lookup (1 extra RPC call, cached in the instance).
"""
from __future__ import annotations

from typing import Any, Optional

from core.exceptions import ErrorCode, QuoteError
from core.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Maverick V2 PoolInformation contract on Base (calculateSwap view function)
MAVERICK_V2_POOL_INFO_ADDRESS: str = "0x67b70f73BeE50AB48F0e8d75b94d4F6dCed6Ad72"

#: Maverick V2 Factory on Base
MAVERICK_V2_FACTORY_ADDRESS: str = "0x0A7e848Aca42d879EF06507Fca0E7b33A0a63c1E"

#: Approximate gas cost for a Maverick V2 swap (directional bins add overhead).
_MAVERICK_V2_GAS_ESTIMATE = 150_000

# ---------------------------------------------------------------------------
# ABI selectors (verified by keccak256 of function signature)
# ---------------------------------------------------------------------------

# calculateSwap(address,uint128,bool,bool,uint256) → 0x2764cd0b
_SELECTOR_CALCULATE_SWAP: bytes = bytes.fromhex("2764cd0b")

# tokenA() → 0x0fc63d10
_SELECTOR_TOKEN_A: bytes = bytes.fromhex("0fc63d10")

# tokenB() → 0x5f64b55b
_SELECTOR_TOKEN_B: bytes = bytes.fromhex("5f64b55b")


# ---------------------------------------------------------------------------
# ABI encoding helpers (no web3 dependency)
# ---------------------------------------------------------------------------

def _encode_calculate_swap(
    pool_address: str,
    amount_in: int,
    token_a_in: bool,
    exact_output: bool = False,
    sqrt_price_limit: int = 0,
) -> str:
    """Encode calldata for ``PoolInformation.calculateSwap``.

    ABI layout (each param padded to 32 bytes):
      bytes4  selector
      bytes32 pool address (right-aligned)
      bytes32 amount (uint128, right-aligned)
      bytes32 tokenAIn (bool, 0 or 1, right-aligned)
      bytes32 exactOutput (bool, 0 or 1, right-aligned)
      bytes32 sqrtPriceLimit (uint256, right-aligned)

    Parameters
    ----------
    pool_address:
        Pool contract address (0x-prefixed, lowercase).
    amount_in:
        Input token amount in raw units (int, fits in uint128).
    token_a_in:
        True when swapping tokenA→tokenB; False for tokenB→tokenA.
    exact_output:
        Always False for GIVEN_IN quoting.
    sqrt_price_limit:
        0 means no price limit (full liquidity traversal).

    Returns
    -------
    str
        Hex-encoded calldata (0x-prefixed).
    """
    addr_bytes = int(pool_address, 16).to_bytes(32, "big")
    amount_bytes = amount_in.to_bytes(32, "big")
    token_a_in_bytes = (1 if token_a_in else 0).to_bytes(32, "big")
    exact_output_bytes = (1 if exact_output else 0).to_bytes(32, "big")
    price_limit_bytes = sqrt_price_limit.to_bytes(32, "big")

    calldata = (
        _SELECTOR_CALCULATE_SWAP
        + addr_bytes
        + amount_bytes
        + token_a_in_bytes
        + exact_output_bytes
        + price_limit_bytes
    )
    return "0x" + calldata.hex()


def _decode_calculate_swap(hex_result: str) -> tuple[int, int]:
    """Decode the response of ``PoolInformation.calculateSwap``.

    Returns tuple (return_amount, end_sqrt_price) both as uint256.

    The return_amount is the output token amount when exactOutput=False.
    """
    raw = hex_result[2:] if hex_result.startswith("0x") else hex_result
    if len(raw) < 128:
        raise ValueError(
            f"calculateSwap response too short: {len(raw)} hex chars, expected >= 128"
        )
    return_amount = int(raw[:64], 16)
    end_sqrt_price = int(raw[64:128], 16)
    return return_amount, end_sqrt_price


# ---------------------------------------------------------------------------
# Adapter class
# ---------------------------------------------------------------------------


class MaverickV2Adapter:
    """Adapter for Maverick V2 directional-liquidity pools.

    Quotes via ``PoolInformation.calculateSwap`` — a single stateless
    eth_call that simulates the swap without modifying state.

    Parameters
    ----------
    provider:
        Injected RPC provider for ``tokenA()`` fallback lookup.
    enabled:
        When ``False``, every quote raises ``POOL_DISABLED``.
    dex_id:
        Label used in logging / quote_source tags.
    """

    ADAPTER_TYPE: str = "maverick_v2"

    def __init__(
        self,
        provider: Any,
        enabled: bool = False,
        dex_id: str = "maverick_v2",
    ) -> None:
        self.provider = provider
        self.enabled = enabled
        self.dex_id = dex_id
        # Per-pool tokenA address cache (avoids repeated eth_call)
        self._token_a_cache: dict[str, str] = {}

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def get_quote(
        self,
        pool_address: str,
        token_in: str,
        token_out: str,
        amount_in: int,
        fee: Optional[int] = None,
        block_number: Optional[int] = None,
        token_a_address: Optional[str] = None,
    ) -> dict:
        """Get a quote from a Maverick V2 pool via PoolInformation.calculateSwap.

        Parameters
        ----------
        pool_address:
            Maverick V2 pool contract address (0x-prefixed).
        token_in:
            Input token address (0x-prefixed).
        token_out:
            Output token address (0x-prefixed).
        amount_in:
            Input amount in raw token units.
        fee:
            Unused (Maverick V2 uses dynamic bin-level fees).
        block_number:
            Unused (stateless view call always uses latest).
        token_a_address:
            Optional override for the pool's tokenA address (from adapter_metadata.yaml).
            If None, falls back to eth_call tokenA() lookup.

        Returns
        -------
        dict
            ``{amount_out: int, gas_estimate: int, quote_source: str}``

        Raises
        ------
        QuoteError(POOL_DISABLED)
            When ``enabled=False``.
        QuoteError(QUOTE_REVERT)
            On any encode/decode or direction-resolution failure.
        """
        if not self.enabled:
            raise QuoteError(
                code=ErrorCode.POOL_DISABLED,
                message="MaverickV2Adapter is disabled.",
            )

        pool_lc = pool_address.lower()
        token_in_lc = token_in.lower()

        # Resolve tokenA address (from cache, param, or live lookup)
        token_a = (
            token_a_address.lower()
            if token_a_address
            else self._token_a_cache.get(pool_lc)
        )
        if token_a is None:
            token_a = self._fetch_token_a(pool_lc)
            if token_a:
                self._token_a_cache[pool_lc] = token_a

        if token_a is None:
            raise QuoteError(
                code=ErrorCode.QUOTE_REVERT,
                message=(
                    f"Cannot determine tokenA for Maverick V2 pool {pool_address}. "
                    "Add token_a to config/adapter_metadata.yaml."
                ),
            )

        token_a_in = token_in_lc == token_a.lower()

        calldata = _encode_calculate_swap(
            pool_address=pool_lc,
            amount_in=amount_in,
            token_a_in=token_a_in,
        )

        # The raw_http_probe handles the actual eth_call; this method is used
        # when MaverickV2Adapter is called directly (e.g., from the web3 path).
        if self.provider is None:
            raise QuoteError(
                code=ErrorCode.QUOTE_REVERT,
                message="MaverickV2Adapter.get_quote requires a provider for direct eth_call.",
            )

        try:
            # Use web3 eth_call (direct_http path)
            result_hex = self.provider.eth.call(
                {"to": MAVERICK_V2_POOL_INFO_ADDRESS, "data": calldata},
                "latest",
            )
            if isinstance(result_hex, bytes):
                result_hex = "0x" + result_hex.hex()
            amount_out, _ = _decode_calculate_swap(result_hex)
        except Exception as exc:
            raise QuoteError(
                code=ErrorCode.QUOTE_REVERT,
                message=f"Maverick V2 calculateSwap failed: {exc}",
            ) from exc

        return {
            "amount_out": amount_out,
            "gas_estimate": _MAVERICK_V2_GAS_ESTIMATE,
            "quote_source": "maverick_v2_pool_info",
        }

    def supports_fee_tiers(self) -> bool:
        """Maverick V2 uses bin-based liquidity, not discrete fee tiers."""
        return False

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fetch_token_a(self, pool_address: str) -> Optional[str]:
        """Live eth_call tokenA() on the pool contract.  Returns lowercase address or None."""
        if self.provider is None:
            return None
        try:
            calldata = "0x" + _SELECTOR_TOKEN_A.hex()
            result = self.provider.eth.call(
                {"to": pool_address, "data": calldata},
                "latest",
            )
            if isinstance(result, bytes):
                result = "0x" + result.hex()
            raw = result[2:] if result.startswith("0x") else result
            if len(raw) < 64:
                return None
            return "0x" + raw[24:64]  # address is right-aligned in 32-byte word
        except Exception as exc:
            logger.debug("tokenA() lookup failed for %s: %s", pool_address, exc)
            return None



