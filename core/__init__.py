"""
core - Core utilities and models for ARBY.

This package contains:
- models.py: Data models (Quote, Opportunity, Trade, PnL)
- constants.py: Enums and constants
- exceptions.py: Typed exceptions with error codes
- math.py: Safe mathematical utilities (no float)
- time.py: Freshness rules and block pinning
- logging.py: Structured JSON logging
"""

from core.constants import (
    DexType,
    OpportunityStatus,
    PoolStatus,
    TokenStatus,
    TradeDirection,
    TradeStatus,
    V3_FEE_TIERS,
)
from core.exceptions import (
    ArbyError,
    CexError,
    ErrorCode,
    ExecutionError,
    InfraError,
    PoolError,
    QuoteError,
    TokenError,
    ValidationError,
)
from core.logging import get_logger, setup_logging
from core.models import (
    ChainInfo,
    Opportunity,
    PnLBreakdown,
    Pool,
    Quote,
    RejectReason,
    Token,
    Trade,
)

__all__ = [
    # Constants
    "DexType",
    "OpportunityStatus",
    "PoolStatus",
    "TokenStatus",
    "TradeDirection",
    "TradeStatus",
    "V3_FEE_TIERS",
    # Exceptions
    "ArbyError",
    "CexError",
    "ErrorCode",
    "ExecutionError",
    "InfraError",
    "PoolError",
    "QuoteError",
    "TokenError",
    "ValidationError",
    # Models
    "ChainInfo",
    "Opportunity",
    "PnLBreakdown",
    "Pool",
    "Quote",
    "RejectReason",
    "Token",
    "Trade",
    # Logging
    "get_logger",
    "setup_logging",
]