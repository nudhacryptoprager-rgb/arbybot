# PATH: core/format_money.py
"""
Safe money formatting utilities for ARBY.

Roadmap 3.2 compliance: No float money.
All money values are str or Decimal. This module provides safe formatting.
"""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from typing import Union


def format_money(value: Union[str, Decimal, int, float, None], decimals: int = 6) -> str:
    """
    Safely format a money value to string with specified decimal places.
    
    Handles:
    - str: parse as Decimal, format
    - Decimal: format directly
    - int: convert to Decimal, format
    - float: convert to Decimal (legacy support), format
    - bool: True=1, False=0
    - None: return "0.000000"
    
    Uses ROUND_HALF_UP for proper rounding (0.005 -> 0.01 with 2 decimals).
    Never raises on valid numeric input.
    
    Args:
        value: Money value in any supported type
        decimals: Number of decimal places (default 6 for USDC precision)
    
    Returns:
        Formatted string like "123.456789"
    
    Example:
        >>> format_money("123.45")
        '123.450000'
        >>> format_money(Decimal("0.001"))
        '0.001000'
        >>> format_money(None)
        '0.000000'
    """
    if value is None:
        return f"0.{'0' * decimals}"
    
    try:
        if isinstance(value, str):
            # Handle empty string
            if not value.strip():
                return f"0.{'0' * decimals}"
            dec_value = Decimal(value)
        elif isinstance(value, Decimal):
            dec_value = value
        elif isinstance(value, bool):
            # Handle bool explicitly BEFORE int (bool is subclass of int)
            dec_value = Decimal(1 if value else 0)
        elif isinstance(value, (int, float)):
            dec_value = Decimal(str(value))
        else:
            # Unknown type - try string conversion
            dec_value = Decimal(str(value))
        
        # Use high-precision context for very large numbers
        with localcontext() as ctx:
            ctx.prec = 50  # Enough for typical financial numbers
            
            # Create quantize string for proper rounding
            quantize_str = "0." + "0" * decimals if decimals > 0 else "0"
            rounded = dec_value.quantize(Decimal(quantize_str), rounding=ROUND_HALF_UP)
        
        # Format with specified decimals
        format_str = f"{{:.{decimals}f}}"
        return format_str.format(rounded)
    
    except (InvalidOperation, ValueError, TypeError):
        # Fallback for unparseable values
        return f"0.{'0' * decimals}"


def format_money_short(value: Union[str, Decimal, int, float, None], decimals: int = 2) -> str:
    """
    Format money with fewer decimals for display (e.g., $123.45).
    
    Uses ROUND_HALF_UP: Decimal("0.005") -> "0.01"
    
    Args:
        value: Money value
        decimals: Decimal places (default 2)
    
    Returns:
        Formatted string like "123.45"
    """
    return format_money(value, decimals)


def format_bps(value: Union[str, Decimal, int, float, None]) -> str:
    """
    Format basis points value.
    
    Args:
        value: BPS value
    
    Returns:
        Formatted string like "12.50"
    """
    return format_money(value, decimals=2)


def format_pct(value: Union[str, Decimal, int, float, None]) -> str:
    """
    Format percentage value.
    
    Args:
        value: Percentage value (0.1 = 0.10%)
    
    Returns:
        Formatted string like "0.1050"
    """
    return format_money(value, decimals=4)