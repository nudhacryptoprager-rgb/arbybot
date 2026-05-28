"""RFQ (Request-for-Quote) adapter skeleton for M9 pricing taxonomy.

RFQ protocols (e.g. Hashflow, Bebop, Native) provide off-chain prices
via signed quotes rather than on-chain AMM invariants.  This makes them
fundamentally different from CPMM/CLMM pools: the price is not a
deterministic function of reserves but is provided by a market maker.

This skeleton is **disabled by default** (``enabled=False``) and raises a
structured :class:`~core.exceptions.QuoteError` with code ``POOL_DISABLED``
on any quote attempt.  No off-chain requests are made, no API keys are read.

Taxonomy coverage
-----------------
The cost_model already maps the following adapter_types to the
``rfq_offchain`` pricing model family:

    "rfq"          → rfq_offchain
    "hashflow_rfq" → rfq_offchain
    "bebop_rfq"    → rfq_offchain
    "native_rfq"   → rfq_offchain

This skeleton covers the generic ``rfq`` family.  Protocol-specific
adapters (hashflow, bebop, etc.) should subclass and set ADAPTER_TYPE.

Activation checklist (do NOT enable without completing all steps):
  - [ ] Obtain and securely store API keys / signing secrets outside code
  - [ ] Implement the off-chain quote request (HTTP/WebSocket) with timeout
  - [ ] Parse and validate the signed quote payload
  - [ ] Add an on-chain validity check (expiry, signature)
  - [ ] Add integration tests with mocked HTTP responses
  - [ ] Set ``enabled: true`` in config after tests pass
"""
from __future__ import annotations

from typing import Any, Optional

from core.exceptions import ErrorCode, QuoteError
from core.logging import get_logger

logger = get_logger(__name__)


class RfqAdapter:
    """Generic RFQ adapter skeleton (off-chain quote surface).

    All ``get_quote()`` calls raise :class:`~core.exceptions.QuoteError`
    with code ``POOL_DISABLED`` until the adapter is activated.

    Parameters
    ----------
    provider:
        Injected RPC provider (unused in skeleton; needed for on-chain
        signature / expiry validation once live).
    enabled:
        When ``False`` (default) every quote raises ``POOL_DISABLED``.
    dex_id:
        Label used in logging and ``quote_source`` tags.
    """

    ADAPTER_TYPE: str = "rfq"

    def __init__(
        self,
        provider: Any,
        enabled: bool = False,
        dex_id: str = "rfq",
    ) -> None:
        self.provider = provider
        self.enabled = enabled
        self.dex_id = dex_id

        if not self.enabled:
            logger.debug(
                "RfqAdapter initialised in DISABLED state — "
                "complete activation checklist before enabling"
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
        """Request an RFQ quote.

        Raises
        ------
        QuoteError
            Always raised with ``POOL_DISABLED`` until the adapter is
            activated (``enabled=True``).
        """
        if not self.enabled:
            raise QuoteError(
                code=ErrorCode.POOL_DISABLED,
                message=(
                    f"rfq adapter is disabled — cannot quote "
                    f"{token_in!r} → {token_out!r} via {self.dex_id!r}; "
                    "complete activation checklist before enabling"
                ),
                details={
                    "adapter_type": self.ADAPTER_TYPE,
                    "dex_id": self.dex_id,
                    "token_in": token_in,
                    "token_out": token_out,
                },
            )

        # --- Placeholder for live implementation ---
        # When enabled, this should:
        #   1. Send an off-chain HTTP/WebSocket request to the RFQ endpoint
        #   2. Parse the signed quote response
        #   3. Validate expiry and signature on-chain (or via provider)
        #   4. Return: {"amount_out": int, "gas_estimate": int, "quote_source": str}
        raise NotImplementedError(
            "RfqAdapter live quoting not yet implemented — "
            "complete activation checklist before enabling"
        )

    def supports_fee_tiers(self) -> bool:
        """RFQ adapters do not use on-chain fee tiers."""
        return False
