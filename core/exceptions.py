# PATH: core/exceptions.py
"""
Typed exceptions for ARBY.

Per Roadmap 3.6: Typed errors with revert vs infra distinction.
"""

from typing import Optional
from core.constants import RejectReason


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


class QuoteError(ArbyError):
    """Quote-related errors."""
    pass


class QuoteRevertError(QuoteError):
    """Quote call reverted."""
    
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(message, RejectReason.QUOTE_REVERT, details)


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