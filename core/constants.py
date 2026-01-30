# PATH: core/constants.py
"""
Centralized constants for ARBY.

M5_0: All constants that were scattered across modules are now here.
Import from here to avoid drift and ensure consistency.

CONTRACTS:
- SCHEMA_VERSION: Frozen at 3.2.0, bump only with migration
- ExecutionBlocker: Canonical strings for execution blockers
- RunMode: Canonical run mode values
- AnchorDex: Priority DEXes for price anchoring
"""

from enum import Enum
from typing import Final

# =============================================================================
# SCHEMA VERSION (FROZEN)
# =============================================================================
# Bump only with migration plan documented in docs/MIGRATIONS.md
SCHEMA_VERSION: Final[str] = "3.2.0"

# =============================================================================
# EXECUTION BLOCKERS (Canonical strings)
# =============================================================================
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


# =============================================================================
# RUN MODES (Canonical values)
# =============================================================================
class RunMode(str, Enum):
    """
    Canonical run mode values.
    
    Used in truth_report and scan artifacts.
    """
    SMOKE_SIMULATOR = "SMOKE_SIMULATOR"
    REGISTRY_REAL = "REGISTRY_REAL"
    REGISTRY_PAPER = "REGISTRY_PAPER"
    LIVE = "LIVE"


# =============================================================================
# ANCHOR DEX PRIORITY (for price sanity)
# =============================================================================
# M5_0: Use anchor_dex for first quote, not "first success"
# Priority order: first available is used as anchor
ANCHOR_DEX_PRIORITY: Final[tuple[str, ...]] = (
    "uniswap_v3",
    "pancakeswap_v3", 
    "sushiswap_v3",
)

# Default anchor DEX if priority list doesn't match
DEFAULT_ANCHOR_DEX: Final[str] = "uniswap_v3"


# =============================================================================
# PRICE SANITY BOUNDS (Hardcoded fallbacks)
# =============================================================================
# Format: (token_in, token_out) -> {min, max, anchor}
# anchor = expected midpoint for deviation calculation
from decimal import Decimal

PRICE_SANITY_BOUNDS: Final[dict[tuple[str, str], dict[str, Decimal]]] = {
    ("WETH", "USDC"): {"min": Decimal("1500"), "max": Decimal("6000"), "anchor": Decimal("3500")},
    ("WETH", "USDT"): {"min": Decimal("1500"), "max": Decimal("6000"), "anchor": Decimal("3500")},
    ("WBTC", "USDC"): {"min": Decimal("30000"), "max": Decimal("150000"), "anchor": Decimal("90000")},
    ("WBTC", "USDT"): {"min": Decimal("30000"), "max": Decimal("150000"), "anchor": Decimal("90000")},
}

# Maximum deviation from anchor in basis points
PRICE_SANITY_MAX_DEVIATION_BPS: Final[int] = 5000  # 50%


# =============================================================================
# METRICS CONTRACT KEYS (for CI gate validation)
# =============================================================================
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


# =============================================================================
# GATE BREAKDOWN CATEGORIES
# =============================================================================
GATE_BREAKDOWN_KEYS: Final[frozenset[str]] = frozenset([
    "revert",
    "slippage", 
    "infra",
    "other",
    "sanity",
])
