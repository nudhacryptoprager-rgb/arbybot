# PATH: utils/validators.py
"""
Validation utilities for ARBY.

Provides validators for money values, addresses, and other common types.
"""

import re
from decimal import Decimal, InvalidOperation
from typing import Any, Optional, Union


def is_valid_address(address: str) -> bool:
    """
    Check if string is a valid Ethereum address.
    
    Args:
        address: String to validate
        
    Returns:
        True if valid 0x-prefixed 40-char hex address
    """
    if not isinstance(address, str):
        return False
    
    pattern = r"^0x[a-fA-F0-9]{40}$"
    return bool(re.match(pattern, address))


def is_valid_money_string(value: str) -> bool:
    """
    Check if string is a valid money value.
    
    Args:
        value: String to validate
        
    Returns:
        True if parseable as Decimal
    """
    if not isinstance(value, str):
        return False
    
    try:
        Decimal(value)
        return True
    except (InvalidOperation, ValueError):
        return False


def validate_no_float(obj: Any, path: str = "") -> list:
    """
    Recursively check object for float values.
    
    Args:
        obj: Object to check
        path: Current path (for error messages)
        
    Returns:
        List of paths containing float values
    """
    float_paths = []
    
    if isinstance(obj, float):
        float_paths.append(path or "root")
    elif isinstance(obj, dict):
        for k, v in obj.items():
            new_path = f"{path}.{k}" if path else k
            float_paths.extend(validate_no_float(v, new_path))
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            new_path = f"{path}[{i}]"
            float_paths.extend(validate_no_float(v, new_path))
    
    return float_paths


def safe_decimal(
    value: Union[str, int, float, Decimal, None],
    default: Optional[Decimal] = None
) -> Optional[Decimal]:
    """
    Safely convert value to Decimal.
    
    Args:
        value: Value to convert
        default: Default if conversion fails (None by default)
        
    Returns:
        Decimal value or default
    """
    if value is None:
        return default
    
    try:
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default


def clamp(value: float, min_val: float, max_val: float) -> float:
    """
    Clamp value to range [min_val, max_val].
    
    Args:
        value: Value to clamp
        min_val: Minimum value
        max_val: Maximum value
        
    Returns:
        Clamped value
    """
    return max(min_val, min(value, max_val))