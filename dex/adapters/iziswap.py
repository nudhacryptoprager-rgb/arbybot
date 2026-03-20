# PATH: dex/adapters/iziswap.py
# R30: iZUMi Finance (iZiSwap) adapter stub
# iZUMi uses "Discretized Concentrated Liquidity" (liquidity boxes) — different from UniV3 ticks.
# Deployed on: Scroll, zkSync, Linea, BNB, Mantle, and others.
# Docs: https://docs.izumi.finance/
#
# STATUS: STUB — raises QuoteError on all calls. Implement when adding iZUMi DEXes to dexes.yaml.
from typing import Any, Optional

from core.exceptions import QuoteError, ErrorCode
from core.logging import get_logger

logger = get_logger(__name__)


class IziSwapAdapter:
    """iZUMi Finance adapter stub (liquidity box model)."""

    def __init__(self, provider: Any, quoter_address: str = "", dex_id: str = "iziswap"):
        self.provider = provider
        self.quoter_address = quoter_address
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
        raise QuoteError(
            code=ErrorCode.QUOTE_REVERT,
            message=f"{self.dex_id}: adapter not implemented (STUB)",
        )

    def supports_fee_tiers(self) -> bool:
        return True  # iZUMi uses fee tiers similar to UniV3
