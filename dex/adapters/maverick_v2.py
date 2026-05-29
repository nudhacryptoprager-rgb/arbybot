# PATH: dex/adapters/maverick_v2.py
"""Maverick V2 directional-liquidity adapter skeleton for M9 pricing taxonomy.

Maverick V2 introduces *bins* (directional liquidity modes) where LPs can
concentrate liquidity in a way that automatically shifts with price movement.
Unlike Uniswap V3 static ticks, Maverick bins can be set to ``mode=both``,
``mode=left`` (follows price down), or ``mode=right`` (follows price up).

This skeleton is **disabled by default** and raises a structured
:class:`~core.exceptions.QuoteError` (code ``POOL_DISABLED``) on any
quote attempt.  It exists so that:

1. ``cost_model.py`` routing can recognise ``maverick_v2`` as
   ``maverick_directional`` (see ``adapter_pricing_model()``).
2. The pool_depth_probe and bridge_builder can classify Maverick V2 pools
   without silently falling through to an unknown adapter.
3. Future live integration has a clear place to land.

Maverick V2 on Base
--------------------
- Router / Position Manager: ``0x32AED3Bce901DA12ca8489788F3A99fCe1056e14``
- PoolInformation (``calculateSwap``): ``0x67b70f73BeE50AB48F0e8d75b94d4F6dCed6Ad72``
- Factory: ``0x0A7e848Aca42d879EF06507Fca0E7b33A0a63c1E``

Activation checklist (do NOT activate without completing all steps):
  - [ ] Implement ``_encode_calculate_swap()`` calldata builder
  - [ ] Implement ``_decode_calculate_swap()`` response decoder
  - [ ] Verify token ordering (tokenA/tokenB) vs token_in/token_out direction
  - [ ] Add integration tests with fixture RPC responses
  - [ ] Add ``maverick_v2`` to ``_DEX_ID_TO_ADAPTER_TYPE`` in bridge_builder.py
  - [ ] Add ``maverick_v2`` branch to ``raw_http_probe.py``
  - [ ] Add dex entry to config/exotic_base_anchor.yaml
  - [ ] Set ``enabled=True`` only after all integration tests pass
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


class MaverickV2Adapter:
    """Adapter skeleton for Maverick V2 directional-liquidity pools.

    All ``get_quote()`` calls raise :class:`~core.exceptions.QuoteError`
    with code ``POOL_DISABLED`` until the adapter is activated.

    Parameters
    ----------
    provider:
        Injected RPC provider (unused in skeleton mode).
    enabled:
        When ``False`` (default), every quote raises ``POOL_DISABLED``.
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

        if not self.enabled:
            logger.debug(
                "MaverickV2Adapter initialised in DISABLED state — "
                "complete the activation checklist before enabling"
            )

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
    ) -> dict:
        """Get a quote from a Maverick V2 pool.

        Raises
        ------
        QuoteError(POOL_DISABLED)
            Always raised in skeleton mode until adapter is activated.
        """
        if not self.enabled:
            raise QuoteError(
                code=ErrorCode.POOL_DISABLED,
                message=(
                    "MaverickV2Adapter is disabled. "
                    "Complete the activation checklist in maverick_v2.py before enabling."
                ),
            )

        # ----------------------------------------------------------------
        # TODO: Live implementation
        # ----------------------------------------------------------------
        # 1. Encode PoolInformation.calculateSwap(pool, amount, tokenAIn, exactOutput)
        #    selector: look up in Maverick V2 ABI
        # 2. eth_call to MAVERICK_V2_POOL_INFO_ADDRESS
        # 3. Decode (amountIn, amountOut) from response
        # 4. Return standard quote dict
        # ----------------------------------------------------------------
        raise QuoteError(
            code=ErrorCode.POOL_DISABLED,
            message="MaverickV2Adapter live implementation not yet complete.",
        )

    def supports_fee_tiers(self) -> bool:
        """Maverick V2 uses bin-based liquidity, not discrete fee tiers."""
        return False
