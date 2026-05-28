"""Minimal DODO PMM adapter skeleton for M9 pricing taxonomy.

DODO uses a Proactive Market Maker (PMM) model: an oracle-driven price curve
that concentrates liquidity around a reference price, unlike CPMM/CLMM.

This skeleton is **disabled by default** and raises a structured
:class:`~core.exceptions.QuoteError` (code ``POOL_DISABLED``) on any
quote attempt.  It exists so that:

1. ``cost_model.py`` routing can recognise ``dodo_pmm`` as ``pmm_oracle``
   (see ``adapter_pricing_model()``).
2. The pool_depth_probe and bridge_builder can classify DODO pools
   without silently falling through to an unknown adapter.
3. Future PMM live integration has a clear place to land.

Activation checklist (do NOT activate without completing all steps):
  - [ ] Obtain DODO V2 PMM pool ABI for querySellBase / querySellQuote
  - [ ] Verify pool_address → base/quote token ordering on-chain
  - [ ] Add integration tests with fixture RPC responses
  - [ ] Set ``enabled: true`` in config/exotic_base_anchor.yaml under
        dexes.dodo_pmm once tests pass
"""
from __future__ import annotations

from typing import Any, Optional

from core.exceptions import ErrorCode, QuoteError
from core.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Approximate gas cost for a DODO PMM swap (conservative estimate).
_DODO_PMM_GAS_ESTIMATE = 120_000


class DodoPmmAdapter:
    """Adapter skeleton for DODO V2 PMM pools.

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

    ADAPTER_TYPE: str = "dodo_pmm"

    def __init__(
        self,
        provider: Any,
        enabled: bool = False,
        dex_id: str = "dodo",
    ) -> None:
        self.provider = provider
        self.enabled = enabled
        self.dex_id = dex_id

        if not self.enabled:
            logger.debug(
                "DodoPmmAdapter initialised in DISABLED state — "
                "set enabled=True after completing activation checklist"
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
        """Quote a DODO PMM pool.

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
                    f"dodo_pmm adapter is disabled — pool {pool_address!r} "
                    "cannot be quoted until activation checklist is complete"
                ),
                details={"adapter_type": self.ADAPTER_TYPE, "pool_address": pool_address},
            )

        # --- Placeholder for live implementation ---
        # When enabled, this should call:
        #   DODO V2 PMM: querySellBase(amount) or querySellQuote(amount)
        # depending on whether token_in is the base or quote token of the pool.
        raise NotImplementedError(
            "DodoPmmAdapter live quoting not yet implemented — "
            "complete activation checklist before enabling"
        )

    def supports_fee_tiers(self) -> bool:
        """PMM pools do not use discrete fee tiers."""
        return False
