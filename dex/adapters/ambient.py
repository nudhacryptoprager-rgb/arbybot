# PATH: dex/adapters/ambient.py
# R30: Ambient Finance adapter stub
# Ambient uses a singleton liquidity model (all pools share one contract).
# Deployed on: Scroll, Blast, Ethereum mainnet.
# Docs: https://docs.ambient.finance/
#
# STATUS: STUB — raises QuoteError on all calls. Implement when adding Ambient DEXes to dexes.yaml.
from typing import Any, Optional

from core.exceptions import QuoteError, ErrorCode
from core.logging import get_logger

logger = get_logger(__name__)


class AmbientAdapter:
    """Ambient Finance adapter stub (singleton liquidity model)."""

    def __init__(self, provider: Any, quoter_address: str = "", dex_id: str = "ambient"):
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
        return False  # Ambient uses pool index, not fee tiers
