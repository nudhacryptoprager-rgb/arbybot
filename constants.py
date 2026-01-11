"""
core/constants.py - Enums, defaults, and constants.

Only truly constant values here. Config values go to config/*.yaml
"""

from decimal import Decimal
from enum import Enum


# =============================================================================
# PROTOCOL TYPES
# =============================================================================

class DexType(str, Enum):
    """Supported DEX protocol types."""
    UNISWAP_V3 = "uniswap_v3"
    UNISWAP_V2 = "uniswap_v2"
    ALGEBRA = "algebra"
    VE33 = "ve33"  # Velodrome/Aerodrome style


class PoolStatus(str, Enum):
    """Pool health status."""
    ACTIVE = "active"
    STALE = "stale"
    DEAD = "dead"
    SUSPICIOUS = "suspicious"
    UNVERIFIED = "unverified"


class TokenStatus(str, Enum):
    """Token verification status."""
    VERIFIED = "verified"
    CANDIDATE = "candidate"
    REJECTED = "rejected"


class TradeDirection(str, Enum):
    """Trade direction for directional pricing."""
    BUY = "buy"    # quote -> base (ExactOutput)
    SELL = "sell"  # base -> quote (ExactInput)


class TradeStatus(str, Enum):
    """Trade lifecycle status."""
    PENDING = "pending"
    SIMULATING = "simulating"
    SIMULATION_PASSED = "simulation_passed"
    SIMULATION_FAILED = "simulation_failed"
    SUBMITTED = "submitted"
    CONFIRMED = "confirmed"
    REVERTED = "reverted"
    EXPIRED = "expired"


class OpportunityStatus(str, Enum):
    """Opportunity evaluation status."""
    VALID = "valid"
    REJECTED = "rejected"
    EXPIRED = "expired"
    EXECUTED = "executed"


# =============================================================================
# V3 CONSTANTS (HARDCODED - TRUST ANCHORS)
# =============================================================================

# Standard Uniswap V3 fee tiers (in hundredths of a bip, i.e., 1/1_000_000)
V3_FEE_TIERS: list[int] = [100, 500, 3000, 10000]

# Fee tier to tick spacing mapping
V3_TICK_SPACINGS: dict[int, int] = {
    100: 1,
    500: 10,
    3000: 60,
    10000: 200,
}


# =============================================================================
# NUMERIC CONSTANTS
# =============================================================================

# Basis points
BPS_DENOMINATOR = Decimal("10000")

# Wei conversions
WEI_PER_ETH = 10**18
WEI_PER_GWEI = 10**9

# Stablecoin decimals (standard)
STABLECOIN_DECIMALS = 6

# Maximum reasonable decimals for a token
MAX_TOKEN_DECIMALS = 18

# Zero address
ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


# =============================================================================
# DEFAULT THRESHOLDS (can be overridden in strategy.yaml)
# =============================================================================

# Quote freshness
DEFAULT_MAX_BLOCK_AGE = 3  # blocks
DEFAULT_MAX_QUOTE_AGE_MS = 2000  # milliseconds

# Slippage
DEFAULT_MAX_SLIPPAGE_BPS = 50  # 0.5%
DEFAULT_MAX_PRICE_IMPACT_BPS = 100  # 1%

# PnL thresholds
DEFAULT_MIN_NET_BPS = 10  # 0.1%
DEFAULT_MIN_NET_USD = Decimal("1.00")

# Confidence
DEFAULT_MIN_CONFIDENCE = Decimal("0.5")

# Gas
DEFAULT_GAS_BUFFER_PERCENT = 20  # Add 20% to estimated gas


# =============================================================================
# INFRASTRUCTURE DEFAULTS
# =============================================================================

DEFAULT_RPC_TIMEOUT_SECONDS = 10
DEFAULT_MAX_RETRIES = 3
DEFAULT_RETRY_DELAY_SECONDS = 1

# Rate limiting
DEFAULT_REQUESTS_PER_SECOND = 10
