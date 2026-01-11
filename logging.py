"""
core/logging.py - Structured JSON logging.

All logs include:
- timestamp (ISO 8601)
- level
- module
- message
- context (chain_id, block_number, latency_ms, etc.)
"""

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

# Global context that gets added to all log entries
_global_context: dict[str, Any] = {}


class JSONFormatter(logging.Formatter):
    """
    JSON log formatter for structured logging.
    
    Output format:
    {
        "timestamp": "2026-01-04T12:00:00.000Z",
        "level": "INFO",
        "logger": "arby.core",
        "message": "Quote fetched",
        "context": {
            "chain_id": 42161,
            "block_number": 12345678,
            "latency_ms": 50
        }
    }
    """
    
    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        
        # Add context from record
        context = {}
        
        # Add global context
        context.update(_global_context)
        
        # Add record-specific context
        if hasattr(record, "context") and record.context:
            context.update(record.context)
        
        # Add exception info if present
        if record.exc_info:
            context["exception"] = self.formatException(record.exc_info)
        
        if context:
            log_entry["context"] = context
        
        return json.dumps(log_entry, default=str)


class ContextAdapter(logging.LoggerAdapter):
    """
    Logger adapter that adds context to all log entries.
    """
    
    def process(
        self, msg: str, kwargs: dict[str, Any]
    ) -> tuple[str, dict[str, Any]]:
        # Merge adapter context with call context
        extra = kwargs.get("extra", {})
        context = {**self.extra, **extra.get("context", {})}
        
        kwargs["extra"] = {"context": context}
        return msg, kwargs


def set_global_context(**kwargs: Any) -> None:
    """
    Set global context that gets added to all log entries.
    
    Example:
        set_global_context(environment="production", version="0.1.0")
    """
    global _global_context
    _global_context.update(kwargs)


def clear_global_context() -> None:
    """Clear global logging context."""
    global _global_context
    _global_context = {}


def get_logger(name: str, **context: Any) -> ContextAdapter:
    """
    Get a logger with optional default context.
    
    Args:
        name: Logger name (e.g., "arby.dex.adapter")
        **context: Default context for all log entries from this logger
    
    Returns:
        ContextAdapter with structured logging
    
    Example:
        logger = get_logger("arby.dex", chain_id=42161)
        logger.info("Quote fetched", extra={"context": {"latency_ms": 50}})
    """
    logger = logging.getLogger(name)
    return ContextAdapter(logger, context)


def setup_logging(
    level: str = "INFO",
    json_output: bool = True,
    log_file: str | None = None,
) -> None:
    """
    Setup logging configuration.
    
    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR)
        json_output: Use JSON formatting (recommended for production)
        log_file: Optional file path for logging
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))
    
    # Clear existing handlers
    root_logger.handlers.clear()
    
    # Create formatter
    if json_output:
        formatter = JSONFormatter()
    else:
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # File handler (optional)
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    
    # Suppress noisy loggers
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def log_quote(
    logger: ContextAdapter,
    pool_address: str,
    direction: str,
    amount_in: int,
    amount_out: int,
    block_number: int,
    latency_ms: int,
    **extra: Any,
) -> None:
    """Log a quote fetch with standard context."""
    logger.info(
        f"Quote: {direction} {pool_address[:10]}...",
        extra={
            "context": {
                "pool_address": pool_address,
                "direction": direction,
                "amount_in": amount_in,
                "amount_out": amount_out,
                "block_number": block_number,
                "latency_ms": latency_ms,
                **extra,
            }
        },
    )


def log_opportunity(
    logger: ContextAdapter,
    opportunity_id: str,
    net_pnl: str,
    net_bps: str,
    status: str,
    reject_reason: str | None = None,
    **extra: Any,
) -> None:
    """Log an opportunity evaluation with standard context."""
    logger.info(
        f"Opportunity: {opportunity_id[:8]} | {status} | PnL: {net_pnl}",
        extra={
            "context": {
                "opportunity_id": opportunity_id,
                "net_pnl": net_pnl,
                "net_bps": net_bps,
                "status": status,
                "reject_reason": reject_reason,
                **extra,
            }
        },
    )


def log_trade(
    logger: ContextAdapter,
    trade_id: str,
    status: str,
    tx_hash: str | None = None,
    gas_used: int | None = None,
    **extra: Any,
) -> None:
    """Log a trade execution with standard context."""
    logger.info(
        f"Trade: {trade_id[:8]} | {status}",
        extra={
            "context": {
                "trade_id": trade_id,
                "status": status,
                "tx_hash": tx_hash,
                "gas_used": gas_used,
                **extra,
            }
        },
    )


def log_error(
    logger: ContextAdapter,
    error_code: str,
    message: str,
    **extra: Any,
) -> None:
    """Log an error with standard context."""
    logger.error(
        f"[{error_code}] {message}",
        extra={
            "context": {
                "error_code": error_code,
                **extra,
            }
        },
    )
