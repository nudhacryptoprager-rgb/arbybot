# PATH: core/constants.py
"""
Core constants for ARBY.

BACKWARD COMPATIBILITY CONTRACT:
- DexType MUST exist (used by core.models, dex.adapters.*)
- TokenStatus MUST exist (used by core.models, discovery.*)
- ExecutionBlocker MUST exist (used by monitoring.truth_report)
- Any removal/rename → alias/deprecation ONLY

M5_0: Use EXECUTION_DISABLED (stage-agnostic), not _M4.
"""

from decimal import Decimal
from enum import Enum
from typing import Dict, Tuple

# =============================================================================
# SCHEMA VERSION
# =============================================================================

SCHEMA_VERSION = "3.2.0"


# =============================================================================
# DEX TYPE (CRITICAL - DO NOT REMOVE)
# =============================================================================

class DexType(str, Enum):
    """
    DEX type identifiers.
    
    CRITICAL: This enum MUST exist for backward compatibility.
    Used by: core.models, dex.adapters.*, strategy.*
    """
    UNISWAP_V3 = "uniswap_v3"
    SUSHISWAP_V3 = "sushiswap_v3"
    PANCAKESWAP_V3 = "pancakeswap_v3"
    CAMELOT = "camelot"
    TRADER_JOE = "trader_joe"
    VELODROME = "velodrome"
    AERODROME = "aerodrome"
    
    @classmethod
    def from_string(cls, s: str) -> "DexType":
        """Convert string to DexType."""
        for member in cls:
            if member.value == s:
                return member
        raise ValueError(f"Unknown DEX type: {s}")


# =============================================================================
# TOKEN STATUS (CRITICAL - DO NOT REMOVE)
# =============================================================================

class TokenStatus(str, Enum):
    """
    Token status in the system.
    
    CRITICAL: This enum MUST exist for backward compatibility.
    Used by: core.models, discovery.*
    """
    ACTIVE = "active"
    INACTIVE = "inactive"
    BLACKLISTED = "blacklisted"
    PENDING = "pending"


# =============================================================================
# EXECUTION BLOCKERS
# =============================================================================

class ExecutionBlocker(str, Enum):
    """
    Reasons why execution is blocked.
    
    M5_0: Use EXECUTION_DISABLED (stage-agnostic).
    """
    # Stage-agnostic (PREFERRED for M5_0+)
    EXECUTION_DISABLED = "EXECUTION_DISABLED"
    
    # Legacy (kept for backward compat with old artifacts)
    EXECUTION_DISABLED_M4 = "EXECUTION_DISABLED_M4"
    
    # Profitability
    NOT_PROFITABLE = "NOT_PROFITABLE"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    INSUFFICIENT_LIQUIDITY = "INSUFFICIENT_LIQUIDITY"
    
    # Safety
    PRICE_SANITY_FAILED = "PRICE_SANITY_FAILED"
    SLIPPAGE_TOO_HIGH = "SLIPPAGE_TOO_HIGH"
    GAS_TOO_HIGH = "GAS_TOO_HIGH"
    
    # Infrastructure
    NO_COST_MODEL = "NO_COST_MODEL"
    RPC_ERROR = "RPC_ERROR"


# M5_0+: Use stage-agnostic blocker
CURRENT_EXECUTION_BLOCKER = ExecutionBlocker.EXECUTION_DISABLED


# =============================================================================
# ANCHOR DEX PRIORITY
# =============================================================================

ANCHOR_DEX_PRIORITY: Tuple[str, ...] = (
    "uniswap_v3",
    "pancakeswap_v3",
    "sushiswap_v3",
)

DEFAULT_ANCHOR_DEX = "uniswap_v3"


# =============================================================================
# PRICE SANITY BOUNDS
# =============================================================================

PRICE_SANITY_MAX_DEVIATION_BPS = 5000  # 50%

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
# DEX IDENTIFIERS (string constants)
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
