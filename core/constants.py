# PATH: core/constants.py
"""
Core constants for ARBY.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
API STABILITY POLICY (M5_0+):
PUBLIC SYMBOLS ONLY GROW, NEVER DISAPPEAR.

Required symbols (DO NOT REMOVE - will break core.models):
- DexType        (Wave 1 drift - fixed)
- TokenStatus    (Wave 2 drift - fixed)
- PoolStatus     (Wave 3 drift - fixed)
- TradeDirection (Wave 4 drift - NOW FIXED)
- ExecutionBlocker
- ANCHOR_DEX_PRIORITY
- PRICE_SANITY_BOUNDS

If renamed → MUST provide alias to old name.
If deprecated → MUST keep alias for 2 milestones minimum.
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""

from decimal import Decimal
from enum import Enum
from typing import Dict, Tuple

# =============================================================================
# SCHEMA VERSION
# =============================================================================

SCHEMA_VERSION = "3.2.0"


# =============================================================================
# DEX TYPE (Wave 1 - DO NOT REMOVE)
# Used by: core.models, dex.adapters.*
# =============================================================================

class DexType(str, Enum):
    """DEX type identifiers."""
    UNISWAP_V3 = "uniswap_v3"
    SUSHISWAP_V3 = "sushiswap_v3"
    PANCAKESWAP_V3 = "pancakeswap_v3"
    CAMELOT = "camelot"
    TRADER_JOE = "trader_joe"
    VELODROME = "velodrome"
    AERODROME = "aerodrome"
    
    @classmethod
    def from_string(cls, s: str) -> "DexType":
        for member in cls:
            if member.value == s:
                return member
        raise ValueError(f"Unknown DEX type: {s}")


# =============================================================================
# TOKEN STATUS (Wave 2 - DO NOT REMOVE)
# Used by: core.models, discovery.*
# =============================================================================

class TokenStatus(str, Enum):
    """Token status in the system."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    BLACKLISTED = "blacklisted"
    PENDING = "pending"


# =============================================================================
# POOL STATUS (Wave 3 - DO NOT REMOVE)
# Used by: core.models, discovery.*, dex.adapters.*
# =============================================================================

class PoolStatus(str, Enum):
    """Pool status in the system."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    QUARANTINED = "quarantined"
    PENDING = "pending"
    ERROR = "error"


# =============================================================================
# TRADE DIRECTION (Wave 4 - DO NOT REMOVE)
# Used by: core.models, strategy.*, traders.*
# =============================================================================

class TradeDirection(str, Enum):
    """
    Trade direction for arbitrage.
    
    CRITICAL: This enum MUST exist for backward compatibility.
    Used by: core.models, strategy.*, traders.*
    """
    BUY = "buy"
    SELL = "sell"
    
    @property
    def opposite(self) -> "TradeDirection":
        """Get opposite direction."""
        return TradeDirection.SELL if self == TradeDirection.BUY else TradeDirection.BUY


# =============================================================================
# EXECUTION BLOCKERS (DO NOT REMOVE)
# =============================================================================

class ExecutionBlocker(str, Enum):
    """
    Reasons why execution is blocked.
    
    M5_0: Use EXECUTION_DISABLED (stage-agnostic).
    """
    EXECUTION_DISABLED = "EXECUTION_DISABLED"
    EXECUTION_DISABLED_M4 = "EXECUTION_DISABLED_M4"  # Legacy compat
    
    NOT_PROFITABLE = "NOT_PROFITABLE"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    INSUFFICIENT_LIQUIDITY = "INSUFFICIENT_LIQUIDITY"
    
    PRICE_SANITY_FAILED = "PRICE_SANITY_FAILED"
    SLIPPAGE_TOO_HIGH = "SLIPPAGE_TOO_HIGH"
    GAS_TOO_HIGH = "GAS_TOO_HIGH"
    
    NO_COST_MODEL = "NO_COST_MODEL"
    RPC_ERROR = "RPC_ERROR"


# M5_0+: Use stage-agnostic blocker
CURRENT_EXECUTION_BLOCKER = ExecutionBlocker.EXECUTION_DISABLED


# =============================================================================
# ANCHOR DEX PRIORITY (DO NOT REMOVE)
# =============================================================================

ANCHOR_DEX_PRIORITY: Tuple[str, ...] = (
    "uniswap_v3",
    "pancakeswap_v3",
    "sushiswap_v3",
)

DEFAULT_ANCHOR_DEX = "uniswap_v3"


# =============================================================================
# PRICE SANITY BOUNDS (DO NOT REMOVE)
# =============================================================================

PRICE_SANITY_MAX_DEVIATION_BPS = 5000

PRICE_SANITY_BOUNDS: Dict[Tuple[str, str], Dict[str, Decimal]] = {
    ("WETH", "USDC"): {
        "min": Decimal("1500"),
        "max": Decimal("6000"),
        "anchor": Decimal("2600"),
    },
    ("WETH", "USDT"): {
        "min": Decimal("1500"),
        "max": Decimal("6000"),
        "anchor": Decimal("2600"),
    },
    ("WBTC", "USDC"): {
        "min": Decimal("50000"),
        "max": Decimal("150000"),
        "anchor": Decimal("90000"),
    },
    ("WBTC", "USDT"): {
        "min": Decimal("50000"),
        "max": Decimal("150000"),
        "anchor": Decimal("90000"),
    },
    ("WBTC", "WETH"): {
        "min": Decimal("10"),
        "max": Decimal("50"),
        "anchor": Decimal("30"),
    },
}


# =============================================================================
# CHAIN IDS
# =============================================================================

CHAIN_IDS = {
    "arbitrum": 42161,
    "base": 8453,
    "linea": 59144,
    "mantle": 5000,
}


# =============================================================================
# DEX IDENTIFIERS
# =============================================================================

DEX_IDS = {
    "uniswap_v3": "uniswap_v3",
    "sushiswap_v3": "sushiswap_v3",
    "pancakeswap_v3": "pancakeswap_v3",
    "camelot": "camelot",
    "trader_joe": "trader_joe",
    "velodrome": "velodrome",
    "aerodrome": "aerodrome",
}


# =============================================================================
# QUOTE AMOUNT DEFAULTS
# =============================================================================

DEFAULT_QUOTE_AMOUNT_WEI = {
    "WETH": 10**18,
    "WBTC": 10**8,
    "USDC": 1000 * 10**6,
    "USDT": 1000 * 10**6,
}
