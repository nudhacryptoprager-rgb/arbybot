# PATH: core/constants.py
"""
Constants for ARBY.

Contains enums, defaults, and configuration constants.
"""

from enum import Enum
from typing import List

# V3 fee tiers (in hundredths of a bip)
V3_FEE_TIERS: List[int] = [100, 500, 3000, 10000]

# Default gas limits
DEFAULT_GAS_LIMIT = 500000
DEFAULT_GAS_PRICE_GWEI = "0.01"

# Slippage defaults
DEFAULT_MAX_SLIPPAGE_BPS = 50
DEFAULT_MIN_NET_BPS = 10

# Timing defaults
DEFAULT_COOLDOWN_SECONDS = 60
DEFAULT_MAX_LATENCY_MS = 2000

# Capital defaults
DEFAULT_NOTION_CAPITAL_USDC = "10000.000000"


class RejectReason(str, Enum):
    """Reject reason codes per Roadmap 3.4."""
    
    # Quote failures
    QUOTE_REVERT = "QUOTE_REVERT"
    QUOTE_TIMEOUT = "QUOTE_TIMEOUT"
    QUOTE_GAS_TOO_HIGH = "QUOTE_GAS_TOO_HIGH"
    
    # Infrastructure errors
    INFRA_RPC_ERROR = "INFRA_RPC_ERROR"
    INFRA_TIMEOUT = "INFRA_TIMEOUT"
    INFRA_RATE_LIMIT = "INFRA_RATE_LIMIT"
    
    # Price/slippage issues
    SLIPPAGE_TOO_HIGH = "SLIPPAGE_TOO_HIGH"
    PRICE_SANITY_FAILED = "PRICE_SANITY_FAILED"
    TICKS_CROSSED_TOO_MANY = "TICKS_CROSSED_TOO_MANY"
    
    # Liquidity issues
    LIQUIDITY_TOO_LOW = "LIQUIDITY_TOO_LOW"
    DEPTH_INSUFFICIENT = "DEPTH_INSUFFICIENT"
    
    # Stale data
    STALE_BLOCK = "STALE_BLOCK"
    STALE_QUOTE = "STALE_QUOTE"
    
    # Execution issues
    REVERT_NO_LIQUIDITY = "REVERT_NO_LIQUIDITY"
    REVERT_PRICE_MOVED = "REVERT_PRICE_MOVED"
    
    # PnL issues
    PNL_BELOW_THRESHOLD = "PNL_BELOW_THRESHOLD"
    PNL_NEGATIVE = "PNL_NEGATIVE"
    
    # Other
    UNSUPPORTED_DEX_TYPE = "UNSUPPORTED_DEX_TYPE"
    UNKNOWN = "UNKNOWN"


class TradeOutcome(str, Enum):
    """Trade outcome codes."""
    
    WOULD_EXECUTE = "WOULD_EXECUTE"
    REJECTED = "REJECTED"
    BLOCKED = "BLOCKED"
    EXECUTED = "EXECUTED"
    FAILED = "FAILED"