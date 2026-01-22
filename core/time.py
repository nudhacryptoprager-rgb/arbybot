# PATH: core/time.py
"""
Time utilities for ARBY.

Freshness rules and block pinning helpers per Roadmap M1.1.
"""

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


@dataclass
class BlockPin:
    """Block number and timestamp for freshness tracking."""
    
    block_number: int
    timestamp_ms: int


def now_utc() -> datetime:
    """Get current UTC datetime."""
    return datetime.now(timezone.utc)


def now_iso() -> str:
    """Get current UTC datetime as ISO string."""
    return now_utc().isoformat()


def now_timestamp() -> float:
    """Get current Unix timestamp."""
    return time.time()


def now_ms() -> int:
    """Get current Unix timestamp in milliseconds."""
    return int(time.time() * 1000)


def is_fresh(
    timestamp: float,
    max_age_seconds: float = 2.0,
    current_time: Optional[float] = None,
) -> bool:
    """
    Check if a timestamp is fresh (within max_age).
    
    Args:
        timestamp: Unix timestamp to check
        max_age_seconds: Maximum allowed age
        current_time: Current time (defaults to now)
        
    Returns:
        True if timestamp is fresh
    """
    current = current_time or time.time()
    age = current - timestamp
    return age <= max_age_seconds


def is_block_fresh(
    quote_block: int,
    current_block: int,
    max_blocks: int = 2,
) -> bool:
    """
    Check if a quote's block is fresh relative to current block.
    
    Args:
        quote_block: Block number from quote
        current_block: Current chain block
        max_blocks: Maximum allowed block difference
        
    Returns:
        True if quote block is fresh
    """
    if quote_block <= 0 or current_block <= 0:
        return False
    
    block_diff = current_block - quote_block
    return 0 <= block_diff <= max_blocks


def calculate_staleness_score(
    quote_block: int,
    current_block: int,
    max_blocks: int = 10,
) -> float:
    """
    Calculate staleness score (0 = fresh, 1 = stale).
    
    Args:
        quote_block: Block number from quote
        current_block: Current chain block
        max_blocks: Blocks at which score reaches 1.0
        
    Returns:
        Staleness score between 0 and 1
    """
    if quote_block <= 0 or current_block <= 0:
        return 1.0
    
    block_diff = current_block - quote_block
    
    if block_diff < 0:
        return 1.0  # Quote from future block is suspicious
    
    if block_diff >= max_blocks:
        return 1.0
    
    return block_diff / max_blocks


def calculate_freshness_score(
    quote_block: int,
    current_block: int,
    max_blocks: int = 10,
) -> float:
    """
    Calculate freshness score (1 = fresh, 0 = stale).
    
    Args:
        quote_block: Block number from quote
        current_block: Current chain block
        max_blocks: Blocks at which score reaches 0.0
        
    Returns:
        Freshness score between 0 and 1
    """
    return 1.0 - calculate_staleness_score(quote_block, current_block, max_blocks)