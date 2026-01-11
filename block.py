"""
chains/block.py - Block number management and pinning.

Provides:
- Block fetching with latency tracking
- Block pinning for quote consistency
- Staleness detection
"""

from dataclasses import dataclass

from core.time import now_ms, BlockPin
from core.logging import get_logger
from core.exceptions import InfraError, ErrorCode
from chains.providers import RPCProvider

logger = get_logger(__name__)


@dataclass
class BlockState:
    """Current block state for a chain."""
    chain_id: int
    block_number: int
    timestamp_ms: int
    latency_ms: int
    
    def to_pin(self) -> BlockPin:
        """Convert to BlockPin for freshness tracking."""
        return BlockPin(
            block_number=self.block_number,
            timestamp_ms=self.timestamp_ms,
        )
    
    def age_ms(self) -> int:
        """Get age in milliseconds."""
        return now_ms() - self.timestamp_ms


async def fetch_block_number(provider: RPCProvider) -> BlockState:
    """
    Fetch current block number from RPC.
    
    Args:
        provider: RPC provider instance
        
    Returns:
        BlockState with block number and timing info
        
    Raises:
        InfraError: If block fetch fails
    """
    try:
        block_number, latency_ms = await provider.get_block_number()
        
        state = BlockState(
            chain_id=provider.chain_id,
            block_number=block_number,
            timestamp_ms=now_ms(),
            latency_ms=latency_ms,
        )
        
        logger.debug(
            f"Fetched block {block_number} (chain={provider.chain_id}, latency={latency_ms}ms)"
        )
        
        return state
        
    except InfraError:
        raise
    except Exception as e:
        raise InfraError(
            code=ErrorCode.INFRA_RPC_ERROR,
            message=f"Failed to fetch block number: {e}",
            details={"chain_id": provider.chain_id},
        )


class BlockPinner:
    """
    Manages block pinning for a chain.
    
    Ensures quotes are fetched at a consistent block height
    and detects when blocks become stale.
    """
    
    def __init__(
        self,
        provider: RPCProvider,
        max_block_age_ms: int = 2000,
    ):
        self.provider = provider
        self.max_block_age_ms = max_block_age_ms
        self._current_state: BlockState | None = None
    
    @property
    def current_block(self) -> int | None:
        """Get current pinned block number."""
        if self._current_state is None:
            return None
        return self._current_state.block_number
    
    @property
    def current_pin(self) -> BlockPin | None:
        """Get current block pin."""
        if self._current_state is None:
            return None
        return self._current_state.to_pin()
    
    def is_stale(self) -> bool:
        """Check if current pin is stale."""
        if self._current_state is None:
            return True
        return self._current_state.age_ms() > self.max_block_age_ms
    
    async def refresh(self) -> BlockState:
        """
        Refresh block pin.
        
        Returns:
            New BlockState
        """
        self._current_state = await fetch_block_number(self.provider)
        
        logger.info(
            f"Block pin refreshed: {self._current_state.block_number} "
            f"(chain={self.provider.chain_id}, latency={self._current_state.latency_ms}ms)"
        )
        
        return self._current_state
    
    async def ensure_fresh(self) -> BlockState:
        """
        Ensure block pin is fresh, refreshing if needed.
        
        Returns:
            Current or refreshed BlockState
        """
        if self.is_stale():
            return await self.refresh()
        return self._current_state  # type: ignore
    
    def get_state(self) -> BlockState | None:
        """Get current block state."""
        return self._current_state
    
    def get_stats(self) -> dict:
        """Get block pinner statistics."""
        if self._current_state is None:
            return {
                "chain_id": self.provider.chain_id,
                "block_number": None,
                "age_ms": None,
                "is_stale": True,
            }
        
        return {
            "chain_id": self.provider.chain_id,
            "block_number": self._current_state.block_number,
            "age_ms": self._current_state.age_ms(),
            "is_stale": self.is_stale(),
            "fetch_latency_ms": self._current_state.latency_ms,
        }
