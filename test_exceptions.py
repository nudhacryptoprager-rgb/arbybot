"""
tests/unit/test_exceptions.py - Tests for core/exceptions.py

Tests for typed exceptions and error codes.
"""

import pytest

from core.exceptions import (
    ErrorCode,
    ArbyError,
    QuoteError,
    PoolError,
    TokenError,
    ExecutionError,
    InfraError,
    CexError,
    ValidationError,
)


class TestErrorCode:
    """Test ErrorCode enum."""
    
    def test_error_code_values(self):
        """Error codes have string values."""
        assert ErrorCode.QUOTE_STALE_BLOCK.value == "QUOTE_STALE_BLOCK"
        assert ErrorCode.SLIPPAGE_TOO_HIGH.value == "SLIPPAGE_TOO_HIGH"
        assert ErrorCode.INFRA_RPC_TIMEOUT.value == "INFRA_RPC_TIMEOUT"
    
    def test_error_code_is_string_enum(self):
        """ErrorCode is a string enum."""
        assert isinstance(ErrorCode.QUOTE_STALE_BLOCK, str)
        assert ErrorCode.QUOTE_STALE_BLOCK == "QUOTE_STALE_BLOCK"


class TestArbyError:
    """Test ArbyError base exception."""
    
    def test_arby_error_creation(self):
        """Create ArbyError with code and message."""
        err = ArbyError(
            code=ErrorCode.QUOTE_TIMEOUT,
            message="Quote request timed out",
        )
        assert err.code == ErrorCode.QUOTE_TIMEOUT
        assert err.message == "Quote request timed out"
        assert err.details == {}
    
    def test_arby_error_with_details(self):
        """Create ArbyError with details."""
        err = ArbyError(
            code=ErrorCode.POOL_NO_LIQUIDITY,
            message="Pool has no liquidity",
            details={"pool": "0x123", "liquidity": 0},
        )
        assert err.details["pool"] == "0x123"
        assert err.details["liquidity"] == 0
    
    def test_arby_error_str(self):
        """ArbyError has formatted string."""
        err = ArbyError(
            code=ErrorCode.EXEC_REVERT,
            message="Transaction reverted",
        )
        assert "[EXEC_REVERT]" in str(err)
        assert "Transaction reverted" in str(err)
    
    def test_arby_error_to_dict(self):
        """ArbyError serializes to dict."""
        err = ArbyError(
            code=ErrorCode.TOKEN_NOT_FOUND,
            message="Token not found",
            details={"symbol": "XYZ"},
        )
        d = err.to_dict()
        assert d["error_code"] == "TOKEN_NOT_FOUND"
        assert d["message"] == "Token not found"
        assert d["details"]["symbol"] == "XYZ"


class TestTypedExceptions:
    """Test specific exception types."""
    
    def test_quote_error(self):
        """QuoteError inherits from ArbyError."""
        err = QuoteError(
            code=ErrorCode.QUOTE_STALE_BLOCK,
            message="Quote block is stale",
            details={"block_age": 5},
        )
        assert isinstance(err, ArbyError)
        assert err.code == ErrorCode.QUOTE_STALE_BLOCK
    
    def test_pool_error(self):
        """PoolError inherits from ArbyError."""
        err = PoolError(
            code=ErrorCode.POOL_DEAD,
            message="Pool is dead",
        )
        assert isinstance(err, ArbyError)
    
    def test_token_error(self):
        """TokenError inherits from ArbyError."""
        err = TokenError(
            code=ErrorCode.TOKEN_INVALID_DECIMALS,
            message="Invalid decimals",
        )
        assert isinstance(err, ArbyError)
    
    def test_execution_error(self):
        """ExecutionError inherits from ArbyError."""
        err = ExecutionError(
            code=ErrorCode.EXEC_SIMULATION_FAILED,
            message="Simulation failed",
        )
        assert isinstance(err, ArbyError)
    
    def test_infra_error(self):
        """InfraError inherits from ArbyError."""
        err = InfraError(
            code=ErrorCode.INFRA_RPC_ERROR,
            message="RPC error",
        )
        assert isinstance(err, ArbyError)
    
    def test_cex_error(self):
        """CexError inherits from ArbyError."""
        err = CexError(
            code=ErrorCode.CEX_DEPTH_LOW,
            message="Low depth",
        )
        assert isinstance(err, ArbyError)


class TestValidationError:
    """Test ValidationError special case."""
    
    def test_validation_error_auto_code(self):
        """ValidationError has automatic error code."""
        err = ValidationError("Invalid input")
        assert err.code == ErrorCode.VALIDATION_ERROR
        assert err.message == "Invalid input"
    
    def test_validation_error_with_details(self):
        """ValidationError accepts details."""
        err = ValidationError(
            "Field is required",
            details={"field": "amount"},
        )
        assert err.details["field"] == "amount"


class TestExceptionCatching:
    """Test exception hierarchy for catching."""
    
    def test_catch_specific(self):
        """Can catch specific exception type."""
        def raise_quote_error():
            raise QuoteError(ErrorCode.QUOTE_TIMEOUT, "Timeout")
        
        with pytest.raises(QuoteError):
            raise_quote_error()
    
    def test_catch_base(self):
        """Can catch base ArbyError."""
        def raise_pool_error():
            raise PoolError(ErrorCode.POOL_DEAD, "Dead")
        
        with pytest.raises(ArbyError):
            raise_pool_error()
    
    def test_catch_builtin(self):
        """ArbyError is still an Exception."""
        def raise_infra_error():
            raise InfraError(ErrorCode.INFRA_RPC_TIMEOUT, "Timeout")
        
        with pytest.raises(Exception):
            raise_infra_error()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
