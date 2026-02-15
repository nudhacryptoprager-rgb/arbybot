# PATH: core/constants.py
"""
Core constants for ARBY.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
API STABILITY POLICY (M5_0+):
PUBLIC SYMBOLS ONLY GROW, NEVER DISAPPEAR.

Required symbols (DO NOT REMOVE - will break core.models):
- DexType, TokenStatus, PoolStatus, TradeDirection (Waves 1-4)
- TradeStatus, OpportunityStatus, TradeOutcome (Wave 5)
- ExecutionBlocker
- ANCHOR_DEX_PRIORITY, PRICE_SANITY_BOUNDS, etc.

If renamed → MUST provide alias: OldName = NewName
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
# =============================================================================

class TokenStatus(str, Enum):
    """Token status in the system."""
    ACTIVE = "active"
    VERIFIED = "verified"
    INACTIVE = "inactive"
    BLACKLISTED = "blacklisted"
    PENDING = "pending"


# =============================================================================
# POOL STATUS (Wave 3 - DO NOT REMOVE)
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
# =============================================================================

class TradeDirection(str, Enum):
    """Trade direction for arbitrage."""
    BUY = "buy"
    SELL = "sell"
    
    @property
    def opposite(self) -> "TradeDirection":
        return TradeDirection.SELL if self == TradeDirection.BUY else TradeDirection.BUY


# =============================================================================
# TRADE STATUS (Wave 5 - DO NOT REMOVE)
# Used by: core.models, traders.*, strategy.*
# =============================================================================

class TradeStatus(str, Enum):
    """Trade lifecycle status."""
    PENDING = "pending"
    SUBMITTED = "submitted"
    MINED = "mined"
    FAILED = "failed"
    CANCELLED = "cancelled"
    CONFIRMED = "confirmed"


# =============================================================================
# OPPORTUNITY STATUS (Wave 5 - DO NOT REMOVE)
# Used by: core.models, strategy.*
# =============================================================================

class OpportunityStatus(str, Enum):
    """Arbitrage opportunity status."""
    NEW = "new"
    VALID = "valid"
    REJECTED = "rejected"
    EXECUTABLE = "executable"
    EXECUTED = "executed"
    EXPIRED = "expired"


# =============================================================================
# TRADE OUTCOME (Wave 5 - DO NOT REMOVE)
# Used by: core.models, traders.*, monitoring.*
# =============================================================================

class TradeOutcome(str, Enum):
    """Trade execution outcome."""
    WOULD_EXECUTE = "would_execute"
    EXECUTED = "executed"
    BLOCKED_EXEC = "blocked_exec"
    COOLDOWN = "cooldown"
    FAILED = "failed"
    REJECTED = "rejected"


# =============================================================================
# EXECUTION BLOCKERS (DO NOT REMOVE)
# =============================================================================

class ExecutionBlocker(str, Enum):
    """Reasons why execution is blocked."""
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


# Sentinel values that indicate a non-real block (for REAL runs)
FAKE_BLOCK_SENTINELS = {0, 1, 999999999}


# =============================================================================
# PRICE SCALE BOUNDS (POLICY - DO NOT REMOVE)
# Used by: gates, validators
# Detects inverted token0/token1 direction bugs
# Format: "TOKEN_A/TOKEN_B" -> (min_expected, max_expected)
# =============================================================================

PRICE_SCALE_BOUNDS: Dict[str, Tuple[float, float]] = {
    "ARB/WETH": (0.00001, 0.01),      # ~0.00035 WETH per ARB
    "ARB/USDC": (0.01, 10.0),         # ~$0.70 per ARB
    "WETH/USDC": (100.0, 50000.0),    # ~$2000 per WETH
    "WETH/USDT": (100.0, 50000.0),    # ~$2000 per WETH
    "wstETH/WETH": (0.5, 2.0),        # ~1.15 WETH per wstETH
    "WBTC/USDC": (10000.0, 200000.0), # ~$90000 per BTC
    "WBTC/WETH": (10.0, 100.0),       # ~30 WETH per BTC
    # v2.0.9: Added pairs from config/real_expanded.yaml
    "ARB/USDT": (0.01, 10.0),         # ~$0.70 per ARB (same as ARB/USDC)
    "LINK/WETH": (0.001, 0.1),        # ~0.007 WETH per LINK
    "LINK/USDC": (1.0, 100.0),        # ~$15 per LINK
    "GMX/WETH": (0.001, 0.1),         # ~0.015 WETH per GMX
    "GMX/USDC": (1.0, 200.0),         # ~$30 per GMX
}


# =============================================================================
# QUOTER IMPACT THRESHOLDS (v2.0.9 - SUSPECT_LIQUIDITY gate)
# =============================================================================

# Maximum ticks crossed before marking as SUSPECT_LIQUIDITY
# High ticks_crossed indicates low liquidity / high price impact
QUOTER_MAX_TICKS_CROSSED = 15  # Conservative: most good pools have <5

# Maximum gas estimate before marking as SUSPECT_LIQUIDITY
# Very high gas indicates complex path or low-liquidity pools
QUOTER_MAX_GAS_ESTIMATE = 500_000  # Normal V3 swap is ~150k-200k

# v2.1.0 DEPRECATED: Use m4.policy.Thresholds.SUSPECT_SPREAD_BPS_HARD (500 bps) instead
# This constant is kept for backwards compatibility but is NOT used by opportunity_engine
# PRICE_OUTLIER_MAX_BPS = 10000  # DEPRECATED - see m4.policy.Thresholds


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


# =============================================================================
# __all__ - EXPORT ALL PUBLIC SYMBOLS
# =============================================================================

__all__ = [
    # Schema
    "SCHEMA_VERSION",
    
    # Enums (Waves 1-4)
    "DexType",
    "TokenStatus",
    "PoolStatus",
    "TradeDirection",
    
    # Enums (Wave 5)
    "TradeStatus",
    "OpportunityStatus",
    "TradeOutcome",
    
    # Blockers
    "ExecutionBlocker",
    "CURRENT_EXECUTION_BLOCKER",
    
    # Constants
    "ANCHOR_DEX_PRIORITY",
    "DEFAULT_ANCHOR_DEX",
    "PRICE_SANITY_MAX_DEVIATION_BPS",
    "PRICE_SANITY_BOUNDS",
    "PRICE_SCALE_BOUNDS",
    "CHAIN_IDS",
    "DEX_IDS",
    "DEFAULT_QUOTE_AMOUNT_WEI",
    "FAKE_BLOCK_SENTINELS",
]
