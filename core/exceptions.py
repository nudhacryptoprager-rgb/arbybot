# PATH: core/exceptions.py
"""
Typed exceptions for ARBY.

Per Roadmap 3.6: Typed errors with revert vs infra distinction.

M4 ADDITION:
- INFRA_BLOCK_PIN_FAILED: Block pinning failed (critical for REAL mode)

M5_0 ADDITION:
- INFRA_BAD_ABI: ABI encoding/decoding error (AttributeError/KeyError on contract method)
"""

from enum import Enum
from typing import Any, Dict, Optional


class ErrorCode(str, Enum):
    """Error codes for typed exceptions."""
    
    # Quote errors
    QUOTE_STALE_BLOCK = "QUOTE_STALE_BLOCK"
    QUOTE_TIMEOUT = "QUOTE_TIMEOUT"
    QUOTE_REVERT = "QUOTE_REVERT"
    QUOTE_EMPTY = "QUOTE_EMPTY"
    QUOTE_GAS_TOO_HIGH = "QUOTE_GAS_TOO_HIGH"
    
    # Pool errors
    POOL_DEAD = "POOL_DEAD"
    POOL_NO_LIQUIDITY = "POOL_NO_LIQUIDITY"
    POOL_NOT_FOUND = "POOL_NOT_FOUND"
    POOL_DISABLED = "POOL_DISABLED"
    
    # Token errors
    TOKEN_NOT_FOUND = "TOKEN_NOT_FOUND"
    TOKEN_INVALID_DECIMALS = "TOKEN_INVALID_DECIMALS"
    TOKEN_UNSUPPORTED = "TOKEN_UNSUPPORTED"
    
    # Execution errors
    EXEC_REVERT = "EXEC_REVERT"
    EXEC_SIMULATION_FAILED = "EXEC_SIMULATION_FAILED"
    EXEC_SLIPPAGE = "EXEC_SLIPPAGE"
    EXEC_GAS_TOO_HIGH = "EXEC_GAS_TOO_HIGH"
    
    # Infrastructure errors
    INFRA_RPC_ERROR = "INFRA_RPC_ERROR"
    INFRA_RPC_TIMEOUT = "INFRA_RPC_TIMEOUT"
    INFRA_RATE_LIMIT = "INFRA_RATE_LIMIT"
    INFRA_TIMEOUT = "INFRA_TIMEOUT"
    INFRA_BLOCK_PIN_FAILED = "INFRA_BLOCK_PIN_FAILED"  # M4: Block pinning failed
    INFRA_BAD_ABI = "INFRA_BAD_ABI"  # M5_0: ABI encoding/decoding error
    
    # CEX errors
    CEX_DEPTH_LOW = "CEX_DEPTH_LOW"
    CEX_CONNECTION_ERROR = "CEX_CONNECTION_ERROR"
    CEX_RATE_LIMIT = "CEX_RATE_LIMIT"
    
    # Price/slippage errors
    SLIPPAGE_TOO_HIGH = "SLIPPAGE_TOO_HIGH"
    PRICE_SANITY_FAILED = "PRICE_SANITY_FAILED"
    PRICE_ANCHOR_MISSING = "PRICE_ANCHOR_MISSING"
    TICKS_CROSSED_TOO_MANY = "TICKS_CROSSED_TOO_MANY"
    
    # Quote consistency errors
    QUOTE_ZERO_OUTPUT = "QUOTE_ZERO_OUTPUT"
    QUOTE_INCONSISTENT = "QUOTE_INCONSISTENT"
    
    # PnL errors
    PNL_BELOW_THRESHOLD = "PNL_BELOW_THRESHOLD"
    PNL_NEGATIVE = "PNL_NEGATIVE"
    
    # Validation
    VALIDATION_ERROR = "VALIDATION_ERROR"
    PREFLIGHT_VALIDATION_FAILED = "PREFLIGHT_VALIDATION_FAILED"
    
    # Other
    UNKNOWN = "UNKNOWN"


class ArbyError(Exception):
    """Base exception for ARBY with typed error code."""
    
    def __init__(
        self,
        code: ErrorCode,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}
    
    def __str__(self) -> str:
        return f"[{self.code.value}] {self.message}"
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict."""
        return {
            "error_code": self.code.value,
            "message": self.message,
            "details": self.details,
        }


class QuoteError(ArbyError):
    """Quote-related errors."""
    pass


class PoolError(ArbyError):
    """Pool-related errors."""
    pass


class TokenError(ArbyError):
    """Token-related errors."""
    pass


class ExecutionError(ArbyError):
    """Execution-related errors."""
    pass


class InfraError(ArbyError):
    """Infrastructure-related errors (RPC, timeouts, rate limits)."""
    pass


class CexError(ArbyError):
    """CEX-related errors."""
    pass


class ValidationError(ArbyError):
    """Validation errors with automatic error code."""
    
    def __init__(
        self,
        message: str,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(
            code=ErrorCode.VALIDATION_ERROR,
            message=message,
            details=details,
        )


# Legacy aliases for backwards compatibility with RejectReason-based code
class RPCError(InfraError):
    """RPC call failed."""
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(ErrorCode.INFRA_RPC_ERROR, message, details)


class TimeoutError(InfraError):
    """Operation timed out."""
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(ErrorCode.INFRA_TIMEOUT, message, details)


class RateLimitError(InfraError):
    """Rate limit exceeded."""
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(ErrorCode.INFRA_RATE_LIMIT, message, details)


class BlockPinError(InfraError):
    """Block pinning failed (M4: critical for REAL mode)."""
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(ErrorCode.INFRA_BLOCK_PIN_FAILED, message, details)


class ABIError(InfraError):
    """ABI encoding/decoding error (M5_0: AttributeError/KeyError on contract method)."""
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(ErrorCode.INFRA_BAD_ABI, message, details)


class QuoteRevertError(QuoteError):
    """Quote call reverted."""
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(ErrorCode.QUOTE_REVERT, message, details)


class SlippageError(ArbyError):
    """Slippage exceeded threshold."""
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(ErrorCode.SLIPPAGE_TOO_HIGH, message, details)


class PriceSanityError(ArbyError):
    """Price failed sanity check."""
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(ErrorCode.PRICE_SANITY_FAILED, message, details)


class LiquidityError(PoolError):
    """Insufficient liquidity."""
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(ErrorCode.POOL_NO_LIQUIDITY, message, details)
