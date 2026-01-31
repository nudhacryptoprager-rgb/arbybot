# PATH: core/constants.py
"""
Core constants for ARBY.

M5_0: Updated execution blockers, anchor priority, price bounds, and DexType.

IMPORTANT: DexType MUST exist for backward compatibility with core.models
and other modules that import it.
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
    Many modules import: from core.constants import DexType
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
# EXECUTION BLOCKERS
# =============================================================================

class ExecutionBlocker(str, Enum):
    """
    Reasons why execution is blocked.
    
    M5_0: Use EXECUTION_DISABLED (stage-agnostic), not _M4.
    """
    EXECUTION_DISABLED = "EXECUTION_DISABLED"
    EXECUTION_DISABLED_M4 = "EXECUTION_DISABLED_M4"  # Legacy
    
    NOT_PROFITABLE = "NOT_PROFITABLE"
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    INSUFFICIENT_LIQUIDITY = "INSUFFICIENT_LIQUIDITY"
    
    PRICE_SANITY_FAILED = "PRICE_SANITY_FAILED"
    SLIPPAGE_TOO_HIGH = "SLIPPAGE_TOO_HIGH"
    GAS_TOO_HIGH = "GAS_TOO_HIGH"
    
    NO_COST_MODEL = "NO_COST_MODEL"
    RPC_ERROR = "RPC_ERROR"


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
