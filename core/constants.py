# PATH: core/constants.py
"""
Constants for ARBY.

Contains enums, defaults, and configuration constants.

M5_0 ADDITIONS (at bottom):
- SCHEMA_VERSION: Frozen at 3.2.0
- ExecutionBlocker: Canonical blocker strings
- RunMode: Canonical run mode values
- ANCHOR_DEX_PRIORITY: For price sanity
- PRICE_SANITY_BOUNDS: Hardcoded fallbacks
- GATE_BREAKDOWN_KEYS: For gate categorization

BACKWARD COMPATIBILITY:
- All original exports preserved (DexType, TokenStatus, etc.)
- New exports ADDED, nothing removed
"""

from decimal import Decimal
from enum import Enum
from typing import Final, List

# =============================================================================
# ORIGINAL CONSTANTS (DO NOT REMOVE - USED BY core/models.py AND OTHERS)
# =============================================================================

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

# Freshness defaults
DEFAULT_QUOTE_FRESHNESS_MS = 3000  # 3 seconds

# Capital defaults
DEFAULT_NOTION_CAPITAL_USDC = "10000.000000"


class DexType(str, Enum):
    """DEX types supported by ARBY."""
    UNISWAP_V2 = "UNISWAP_V2"
    UNISWAP_V3 = "UNISWAP_V3"
    ALGEBRA = "ALGEBRA"
    CURVE = "CURVE"
    BALANCER = "BALANCER"
    VELODROME = "VELODROME"
    AERODROME = "AERODROME"
    CAMELOT = "CAMELOT"
    PANCAKESWAP = "PANCAKESWAP"


class TokenStatus(str, Enum):
    """Token status for ARBY."""
    VERIFIED = "VERIFIED"
    UNVERIFIED = "UNVERIFIED"
    BLACKLISTED = "BLACKLISTED"
    UNKNOWN = "UNKNOWN"


class PoolStatus(str, Enum):
    """Pool status codes."""
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    QUARANTINED = "QUARANTINED"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class TradeDirection(str, Enum):
    """Trade direction."""
    BUY = "BUY"
    SELL = "SELL"


class TradeStatus(str, Enum):
    """Trade execution status."""
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"
    REVERTED = "REVERTED"


class OpportunityStatus(str, Enum):
    """Opportunity status."""
    VALID = "VALID"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"
    EXPIRED = "EXPIRED"


class TradeOutcome(str, Enum):
    """Trade outcome codes."""
    WOULD_EXECUTE = "WOULD_EXECUTE"
    REJECTED = "REJECTED"
    BLOCKED = "BLOCKED"
    EXECUTED = "EXECUTED"
    FAILED = "FAILED"


class RejectReason(str, Enum):
    """
    Reject reason codes per Roadmap 3.4.
    
    Note: This enum is kept for backwards compatibility.
    New code should use ErrorCode from core.exceptions.
    """
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


# =============================================================================
# M5_0 ADDITIONS (NEW - centralized constants)
# =============================================================================

# SCHEMA VERSION (FROZEN)
# Bump only with migration plan documented in docs/MIGRATIONS.md
SCHEMA_VERSION: Final[str] = "3.2.0"


class ExecutionBlocker(str, Enum):
    """
    Canonical execution blocker reasons.
    
    Use these instead of hardcoded strings to ensure consistency
    across gates, truth_report, and scanner.
    """
    # Mode-based blockers
    EXECUTION_DISABLED_M4 = "EXECUTION_DISABLED_M4"
    SMOKE_MODE_NO_EXECUTION = "SMOKE_MODE_NO_EXECUTION"
    
    # Profitability blockers
    NOT_PROFITABLE = "NOT_PROFITABLE"
    PNL_BELOW_THRESHOLD = "PNL_BELOW_THRESHOLD"
    
    # Confidence blockers
    LOW_CONFIDENCE = "LOW_CONFIDENCE"
    PRICE_UNSTABLE = "PRICE_UNSTABLE"
    
    # Data quality blockers
    NO_COST_MODEL = "NO_COST_MODEL"
    INVALID_SIZE = "INVALID_SIZE"
    INVALID_PNL = "INVALID_PNL"
    STALE_QUOTE = "STALE_QUOTE"
    
    # Infrastructure blockers
    RPC_UNHEALTHY = "RPC_UNHEALTHY"
    INSUFFICIENT_LIQUIDITY = "INSUFFICIENT_LIQUIDITY"
    
    # Validation blockers
    REVALIDATION_FAILED = "REVALIDATION_FAILED"
    SANITY_CHECK_FAILED = "SANITY_CHECK_FAILED"


class RunMode(str, Enum):
    """
    Canonical run mode values.
    
    Used in truth_report and scan artifacts.
    """
    SMOKE_SIMULATOR = "SMOKE_SIMULATOR"
    REGISTRY_REAL = "REGISTRY_REAL"
    REGISTRY_PAPER = "REGISTRY_PAPER"
    LIVE = "LIVE"


# ANCHOR DEX PRIORITY (for price sanity)
# Priority order: first available is used as anchor
ANCHOR_DEX_PRIORITY: Final[tuple[str, ...]] = (
    "uniswap_v3",
    "pancakeswap_v3",
    "sushiswap_v3",
)

# Default anchor DEX if priority list doesn't match
DEFAULT_ANCHOR_DEX: Final[str] = "uniswap_v3"

# PRICE SANITY BOUNDS (Hardcoded fallbacks)
# Format: (token_in, token_out) -> {min, max, anchor}
PRICE_SANITY_BOUNDS: Final[dict[tuple[str, str], dict[str, Decimal]]] = {
    ("WETH", "USDC"): {"min": Decimal("1500"), "max": Decimal("6000"), "anchor": Decimal("3500")},
    ("WETH", "USDT"): {"min": Decimal("1500"), "max": Decimal("6000"), "anchor": Decimal("3500")},
    ("WBTC", "USDC"): {"min": Decimal("30000"), "max": Decimal("150000"), "anchor": Decimal("90000")},
    ("WBTC", "USDT"): {"min": Decimal("30000"), "max": Decimal("150000"), "anchor": Decimal("90000")},
}

# Maximum deviation from anchor in basis points
PRICE_SANITY_MAX_DEVIATION_BPS: Final[int] = 5000  # 50%

# METRICS CONTRACT KEYS (for CI gate validation)
REQUIRED_SCAN_STATS_KEYS: Final[frozenset[str]] = frozenset([
    "quotes_total",
    "quotes_fetched",
    "gates_passed",
    "dexes_active",
    "price_sanity_passed",
    "price_sanity_failed",
])

REQUIRED_TRUTH_REPORT_KEYS: Final[frozenset[str]] = frozenset([
    "schema_version",
    "timestamp",
    "mode",
    "run_mode",
    "execution_enabled",
    "health",
    "stats",
    "pnl",
])

# GATE BREAKDOWN CATEGORIES
GATE_BREAKDOWN_KEYS: Final[frozenset[str]] = frozenset([
    "revert",
    "slippage",
    "infra",
    "other",
    "sanity",
])
