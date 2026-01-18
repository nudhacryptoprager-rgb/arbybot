# PATH: core/exceptions.py
"""
Typed exceptions for ARBY.

Per Roadmap 3.6: Typed errors with revert vs infra distinction.
"""

from typing import Optional
from core.constants import RejectReason, ErrorCode


class ArbyError(Exception):
    """Base exception for ARBY."""
    
    def __init__(
        self,
        message: str,
        reason: RejectReason = RejectReason.UNKNOWN,
        details: Optional[dict] = None,
    ):
        super().__init__(message)
        self.reason = reason
        self.details = details or {}
    
    def __str__(self):
        return f"[{self.reason.value}] {super().__str__()}"


class InfraError(ArbyError):
    """Infrastructure-related errors (RPC, timeouts, rate limits)."""
    pass


class RPCError(InfraError):
    """RPC call failed."""
    
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message, RejectReason.INFRA_RPC_ERROR, details)


class TimeoutError(InfraError):
    """Operation timed out."""
    
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message, RejectReason.INFRA_TIMEOUT, details)


class RateLimitError(InfraError):
    """Rate limit exceeded."""
    
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message, RejectReason.INFRA_RATE_LIMIT, details)


class QuoteError(Exception):
    """
    Quote-related errors for DEX adapters.
    
    Supports both ErrorCode-based and RejectReason-based construction
    for compatibility with different call sites.
    """
    
    def __init__(
        self,
        message: str = "",
        code: Optional[ErrorCode] = None,
        reason: Optional[RejectReason] = None,
        details: Optional[dict] = None,
    ):
        super().__init__(message)
        self.message = message
        self.details = details or {}
        
        # Support both ErrorCode and RejectReason
        if code is not None:
            self.code = code
            # Map ErrorCode to RejectReason for compatibility
            self.reason = RejectReason(code.value) if code.value in [r.value for r in RejectReason] else RejectReason.UNKNOWN
        elif reason is not None:
            self.reason = reason
            self.code = ErrorCode(reason.value) if reason.value in [e.value for e in ErrorCode] else ErrorCode.UNKNOWN
        else:
            self.code = ErrorCode.UNKNOWN
            self.reason = RejectReason.UNKNOWN
    
    def __str__(self):
        return f"[{self.code.value}] {self.message}"


class QuoteRevertError(QuoteError):
    """Quote call reverted."""
    
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(
            message=message,
            code=ErrorCode.QUOTE_REVERT,
            details=details,
        )


class SlippageError(ArbyError):
    """Slippage exceeded threshold."""
    
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message, RejectReason.SLIPPAGE_TOO_HIGH, details)


class PriceSanityError(ArbyError):
    """Price failed sanity check."""
    
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message, RejectReason.PRICE_SANITY_FAILED, details)


class LiquidityError(ArbyError):
    """Insufficient liquidity."""
    
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message, RejectReason.LIQUIDITY_TOO_LOW, details)
