# PATH: core/logging.py
"""
Structured JSON logging for ARBY.

Per Roadmap requirement A): All contextual fields passed only via extra={"context": {...}}
"""

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional


class StructuredFormatter(logging.Formatter):
    """
    JSON formatter for structured logging.
    
    Includes context fields from extra={"context": {...}}
    """
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        
        # Add context if present
        if hasattr(record, "context") and record.context:
            log_data["context"] = record.context
        
        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        
        return json.dumps(log_data)


class ConsoleFormatter(logging.Formatter):
    """
    Human-readable formatter for console output.
    """
    
    def format(self, record: logging.LogRecord) -> str:
        """Format log record for console."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        base = f"{timestamp} | {record.levelname:<9} | {record.name} | {record.getMessage()}"
        
        # Add context summary if present
        if hasattr(record, "context") and record.context:
            ctx_str = ", ".join(f"{k}={v}" for k, v in list(record.context.items())[:3])
            if len(record.context) > 3:
                ctx_str += f", ... (+{len(record.context) - 3} more)"
            base += f" | {ctx_str}"
        
        return base


def setup_logging(
    level: int = logging.INFO,
    log_file: Optional[str] = None,
    json_format: bool = False,
) -> None:
    """
    Setup logging configuration.
    
    Args:
        level: Logging level
        log_file: Optional file path for log output
        json_format: Use JSON format (True) or console format (False)
    """
    handlers = []
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(
        StructuredFormatter() if json_format else ConsoleFormatter()
    )
    handlers.append(console_handler)
    
    # File handler
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(StructuredFormatter())
        handlers.append(file_handler)
    
    # Configure root logger
    logging.basicConfig(
        level=level,
        handlers=handlers,
        force=True,
    )


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance.
    
    Args:
        name: Logger name (typically module name)
        
    Returns:
        Logger instance
    """
    return logging.getLogger(name)