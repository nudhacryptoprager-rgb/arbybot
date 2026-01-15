"""
core/exceptions.py - Typed exceptions with error codes.

Every error has a code for reject reasons and monitoring.
No bare exceptions allowed in the project.
"""

from enum import Enum
from typing import Any


class ErrorCode(str, Enum):
    """
    Canonical error codes for reject reasons and monitoring.
    
    Categories:
    - QUOTE_* : Quote fetching errors
    - POOL_*  : Pool/liquidity errors  
    - TOKEN_* : Token validation errors
    - EXEC_*  : Execution errors
    - INFRA_* : Infrastructure errors
    - CEX_*   : CEX-specific errors
    """
    
    # Quote errors
    QUOTE_STALE_BLOCK = "QUOTE_STALE_BLOCK"
    QUOTE_REVERT = "QUOTE_REVERT"
    QUOTE_ZERO_OUTPUT = "QUOTE_ZERO_OUTPUT"
    QUOTE_TIMEOUT = "QUOTE_TIMEOUT"
    QUOTE_INVALID_PARAMS = "QUOTE_INVALID_PARAMS"
    QUOTE_GAS_TOO_HIGH = "QUOTE_GAS_TOO_HIGH"
    QUOTE_INCONSISTENT = "QUOTE_INCONSISTENT"  # Monotonicity violation
    
    # Pool errors
    POOL_NOT_FOUND = "POOL_NOT_FOUND"
    POOL_NO_LIQUIDITY = "POOL_NO_LIQUIDITY"
    POOL_DEAD = "POOL_DEAD"
    POOL_SUSPICIOUS = "POOL_SUSPICIOUS"
    POOL_UNSUPPORTED_FEE = "POOL_UNSUPPORTED_FEE"
    
    # Slippage / Impact
    SLIPPAGE_TOO_HIGH = "SLIPPAGE_TOO_HIGH"
    PRICE_IMPACT_TOO_HIGH = "PRICE_IMPACT_TOO_HIGH"
    TICKS_CROSSED_TOO_MANY = "TICKS_CROSSED_TOO_MANY"
    PRICE_SANITY_FAILED = "PRICE_SANITY_FAILED"  # Price deviates too much from anchor
    PRICE_ANCHOR_MISSING = "PRICE_ANCHOR_MISSING"  # Non-anchor quote without anchor price
    
    # Token errors
    TOKEN_NOT_FOUND = "TOKEN_NOT_FOUND"
    TOKEN_INVALID_DECIMALS = "TOKEN_INVALID_DECIMALS"
    TOKEN_SYMBOL_MISMATCH = "TOKEN_SYMBOL_MISMATCH"
    TOKEN_NOT_VERIFIED = "TOKEN_NOT_VERIFIED"
    
    # Execution errors
    EXEC_SIMULATION_FAILED = "EXEC_SIMULATION_FAILED"
    EXEC_REVERT = "EXEC_REVERT"
    EXEC_GAS_TOO_HIGH = "EXEC_GAS_TOO_HIGH"
    EXEC_INSUFFICIENT_BALANCE = "EXEC_INSUFFICIENT_BALANCE"
    EXEC_NONCE_ERROR = "EXEC_NONCE_ERROR"
    
    # PnL / Opportunity errors
    PNL_NEGATIVE = "PNL_NEGATIVE"
    PNL_BELOW_THRESHOLD = "PNL_BELOW_THRESHOLD"
    PNL_CURRENCY_MISMATCH = "PNL_CURRENCY_MISMATCH"
    
    # Infrastructure errors
    INFRA_RPC_TIMEOUT = "INFRA_RPC_TIMEOUT"
    INFRA_RPC_ERROR = "INFRA_RPC_ERROR"
    INFRA_RATE_LIMIT = "INFRA_RATE_LIMIT"
    INFRA_CONNECTION_ERROR = "INFRA_CONNECTION_ERROR"
    INFRA_BAD_ABI = "INFRA_BAD_ABI"  # Real ABI encoding/decoding errors
    INFRA_BAD_ADDRESS = "INFRA_BAD_ADDRESS"
    
    # Internal code errors (bugs, not infrastructure)
    INTERNAL_CODE_ERROR = "INTERNAL_CODE_ERROR"  # AttributeError/KeyError in our code
    
    # CEX errors
    CEX_DEPTH_LOW = "CEX_DEPTH_LOW"
    CEX_PAIR_NOT_FOUND = "CEX_PAIR_NOT_FOUND"
    CEX_RATE_LIMIT = "CEX_RATE_LIMIT"
    CEX_API_ERROR = "CEX_API_ERROR"
    
    # DEX adapter errors
    DEX_ADAPTER_NOT_FOUND = "DEX_ADAPTER_NOT_FOUND"
    DEX_UNSUPPORTED_TYPE = "DEX_UNSUPPORTED_TYPE"
    
    # Generic
    UNKNOWN_ERROR = "UNKNOWN_ERROR"
    VALIDATION_ERROR = "VALIDATION_ERROR"


class ArbyError(Exception):
    """Base exception for all ARBY errors."""
    
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        details: dict[str, Any] | None = None,
    ):
        self.code = code
        self.message = message
        self.details = details or {}
        super().__init__(f"[{code.value}] {message}")
    
    def to_dict(self) -> dict[str, Any]:
        """Serialize for logging/reporting."""
        return {
            "error_code": self.code.value,
            "message": self.message,
            "details": self.details,
        }


class QuoteError(ArbyError):
    """Errors during quote fetching."""
    pass


class PoolError(ArbyError):
    """Errors related to pool state."""
    pass


class TokenError(ArbyError):
    """Errors during token validation."""
    pass


class ExecutionError(ArbyError):
    """Errors during trade execution."""
    pass


class InfraError(ArbyError):
    """Infrastructure/network errors."""
    pass


class CexError(ArbyError):
    """CEX-specific errors."""
    pass


class ValidationError(ArbyError):
    """Input validation errors."""
    
    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(ErrorCode.VALIDATION_ERROR, message, details)
