"""
core/time.py - Freshness rules and block pinning helpers.

Ensures quotes are fresh and block-consistent.
"""

import time
from dataclasses import dataclass
from datetime import datetime, timezone

from core.constants import DEFAULT_MAX_BLOCK_AGE, DEFAULT_MAX_QUOTE_AGE_MS


@dataclass
class BlockPin:
    """
    Pinned block reference for consistent quoting.
    
    All quotes in a scan cycle should reference the same block
    to ensure consistency.
    """
    
    block_number: int
    block_timestamp: int  # Unix timestamp
    pinned_at_ms: int  # When we pinned this block (local time)
    chain_id: int
    
    @property
    def age_ms(self) -> int:
        """Milliseconds since this block was pinned."""
        return now_ms() - self.pinned_at_ms
    
    @property
    def is_stale(self) -> bool:
        """Check if this pin is too old (> 2 seconds by default)."""
        return self.age_ms > DEFAULT_MAX_QUOTE_AGE_MS


def now_ms() -> int:
    """Current time in milliseconds (Unix timestamp)."""
    return int(time.time() * 1000)


def now_utc() -> datetime:
    """Current UTC datetime."""
    return datetime.now(timezone.utc)


def is_quote_fresh(
    quote_timestamp_ms: int,
    max_age_ms: int = DEFAULT_MAX_QUOTE_AGE_MS,
) -> bool:
    """
    Check if a quote is fresh enough.
    
    Args:
        quote_timestamp_ms: Quote timestamp in milliseconds
        max_age_ms: Maximum allowed age in milliseconds
    
    Returns:
        True if quote is fresh
    """
    age = now_ms() - quote_timestamp_ms
    return age <= max_age_ms


def is_block_fresh(
    quote_block: int,
    current_block: int,
    max_block_age: int = DEFAULT_MAX_BLOCK_AGE,
) -> bool:
    """
    Check if a quote's block is fresh enough.
    
    Args:
        quote_block: Block number when quote was fetched
        current_block: Current block number
        max_block_age: Maximum allowed block age
    
    Returns:
        True if block is fresh
    """
    return (current_block - quote_block) <= max_block_age


def ms_to_seconds(ms: int) -> float:
    """Convert milliseconds to seconds."""
    return ms / 1000.0


def seconds_to_ms(seconds: float) -> int:
    """Convert seconds to milliseconds."""
    return int(seconds * 1000)


@dataclass
class FreshnessCheck:
    """Result of a freshness check."""
    
    is_fresh: bool
    quote_age_ms: int
    block_age: int
    reason: str | None = None
    
    @classmethod
    def fresh(cls, quote_age_ms: int, block_age: int) -> "FreshnessCheck":
        return cls(
            is_fresh=True,
            quote_age_ms=quote_age_ms,
            block_age=block_age,
            reason=None,
        )
    
    @classmethod
    def stale_time(cls, quote_age_ms: int, block_age: int, max_age_ms: int) -> "FreshnessCheck":
        return cls(
            is_fresh=False,
            quote_age_ms=quote_age_ms,
            block_age=block_age,
            reason=f"Quote too old: {quote_age_ms}ms > {max_age_ms}ms",
        )
    
    @classmethod
    def stale_block(
        cls, quote_age_ms: int, block_age: int, max_block_age: int
    ) -> "FreshnessCheck":
        return cls(
            is_fresh=False,
            quote_age_ms=quote_age_ms,
            block_age=block_age,
            reason=f"Block too old: {block_age} blocks > {max_block_age}",
        )


def check_freshness(
    quote_timestamp_ms: int,
    quote_block: int,
    current_block: int,
    max_age_ms: int = DEFAULT_MAX_QUOTE_AGE_MS,
    max_block_age: int = DEFAULT_MAX_BLOCK_AGE,
) -> FreshnessCheck:
    """
    Comprehensive freshness check for a quote.
    
    Checks both time-based and block-based freshness.
    """
    quote_age_ms = now_ms() - quote_timestamp_ms
    block_age = current_block - quote_block
    
    # Check time freshness
    if quote_age_ms > max_age_ms:
        return FreshnessCheck.stale_time(quote_age_ms, block_age, max_age_ms)
    
    # Check block freshness
    if block_age > max_block_age:
        return FreshnessCheck.stale_block(quote_age_ms, block_age, max_block_age)
    
    return FreshnessCheck.fresh(quote_age_ms, block_age)


class ScanClock:
    """
    Clock for a scan cycle.
    
    Tracks timing and ensures all operations reference
    the same time window.
    """
    
    def __init__(self, chain_id: int):
        self.chain_id = chain_id
        self.started_at_ms = now_ms()
        self.block_pin: BlockPin | None = None
    
    def pin_block(self, block_number: int, block_timestamp: int) -> BlockPin:
        """Pin a block for this scan cycle."""
        self.block_pin = BlockPin(
            block_number=block_number,
            block_timestamp=block_timestamp,
            pinned_at_ms=now_ms(),
            chain_id=self.chain_id,
        )
        return self.block_pin
    
    @property
    def elapsed_ms(self) -> int:
        """Milliseconds since scan started."""
        return now_ms() - self.started_at_ms
    
    def is_block_pinned(self) -> bool:
        """Check if a block has been pinned."""
        return self.block_pin is not None
    
    def is_pin_stale(self) -> bool:
        """Check if the pinned block is stale."""
        if self.block_pin is None:
            return True
        return self.block_pin.is_stale