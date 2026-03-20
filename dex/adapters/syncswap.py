# PATH: dex/adapters/syncswap.py
# R30: SyncSwap adapter stub
# SyncSwap uses a multi-pool router with Classic and Stable pool types.
# Deployed on: zkSync Era, Linea, Scroll.
# Docs: https://docs.syncswap.xyz/
#
# STATUS: STUB — raises QuoteError on all calls. Implement when adding SyncSwap DEXes to dexes.yaml.
from typing import Any, Optional

from core.exceptions import QuoteError, ErrorCode
from core.logging import get_logger

logger = get_logger(__name__)


class SyncSwapAdapter:
    """SyncSwap adapter stub (Classic + Stable pool model)."""

    def __init__(self, provider: Any, router_address: str = "", dex_id: str = "syncswap"):
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
        raise QuoteError(
            code=ErrorCode.QUOTE_REVERT,
            message=f"{self.dex_id}: adapter not implemented (STUB)",
        )

    def supports_fee_tiers(self) -> bool:
        return False  # SyncSwap uses pool types, not fee tiers
