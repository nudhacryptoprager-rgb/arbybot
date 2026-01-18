# PATH: core/math.py
"""
Math utilities for ARBY.

Safe conversions and calculations per Roadmap 3.2 (no float money).
"""

from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Union, Optional

from core.format_money import format_money


def safe_decimal(value: Union[str, int, float, Decimal, None], default: Decimal = Decimal("0")) -> Decimal:
    """
    Safely convert value to Decimal.
    
    Args:
        value: Value to convert
        default: Default if conversion fails
        
    Returns:
        Decimal value
    """
    if value is None:
        return default
    
    try:
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return default


def bps_to_decimal(bps: Union[str, int, float, Decimal]) -> Decimal:
    """
    Convert basis points to decimal (100 bps = 0.01 = 1%).
    
    Args:
        bps: Basis points value
        
    Returns:
        Decimal fraction (e.g., 50 bps -> 0.005)
    """
    return safe_decimal(bps) / Decimal("10000")


def decimal_to_bps(value: Union[str, int, float, Decimal]) -> Decimal:
    """
    Convert decimal to basis points.
    
    Args:
        value: Decimal fraction
        
    Returns:
        Basis points (e.g., 0.005 -> 50 bps)
    """
    return safe_decimal(value) * Decimal("10000")


def calculate_pnl_bps(
    pnl_usdc: Union[str, Decimal],
    notional_usdc: Union[str, Decimal],
) -> Decimal:
    """
    Calculate PnL in basis points.
    
    Args:
        pnl_usdc: PnL in USDC
        notional_usdc: Notional amount in USDC
        
    Returns:
        PnL in basis points
    """
    pnl = safe_decimal(pnl_usdc)
    notional = safe_decimal(notional_usdc)
    
    if notional == 0:
        return Decimal("0")
    
    return (pnl / notional) * Decimal("10000")


def calculate_slippage_bps(
    expected_price: Union[str, Decimal],
    actual_price: Union[str, Decimal],
) -> Decimal:
    """
    Calculate slippage in basis points.
    
    Args:
        expected_price: Expected execution price
        actual_price: Actual execution price
        
    Returns:
        Slippage in basis points (positive = worse than expected)
    """
    expected = safe_decimal(expected_price)
    actual = safe_decimal(actual_price)
    
    if expected == 0:
        return Decimal("0")
    
    slippage = (actual - expected) / expected
    return slippage * Decimal("10000")


def normalize_to_decimals(
    amount: Union[str, int, Decimal],
    decimals: int,
) -> Decimal:
    """
    Normalize amount to token decimals (wei to token units).
    
    Args:
        amount: Amount in smallest unit (wei)
        decimals: Token decimals
        
    Returns:
        Normalized amount
    """
    amt = safe_decimal(amount)
    divisor = Decimal(10) ** decimals
    return amt / divisor


def denormalize_from_decimals(
    amount: Union[str, float, Decimal],
    decimals: int,
) -> int:
    """
    Denormalize amount from token units to wei.
    
    Args:
        amount: Amount in token units
        decimals: Token decimals
        
    Returns:
        Amount in wei (int)
    """
    amt = safe_decimal(amount)
    multiplier = Decimal(10) ** decimals
    return int(amt * multiplier)