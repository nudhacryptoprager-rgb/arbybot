"""
core/math.py - Mathematical utilities.

CRITICAL: No float allowed in quoting/price/PnL.
All monetary values use int (wei) or Decimal.
"""

from decimal import Decimal, ROUND_DOWN, ROUND_UP, InvalidOperation
from typing import overload

from core.constants import BPS_DENOMINATOR, WEI_PER_ETH, WEI_PER_GWEI
from core.exceptions import ValidationError


# =============================================================================
# BASIS POINTS
# =============================================================================

def bps_to_decimal(bps: int | Decimal) -> Decimal:
    """
    Convert basis points to decimal multiplier.
    
    Example: 50 bps -> 0.005
    """
    return Decimal(bps) / BPS_DENOMINATOR


def decimal_to_bps(value: Decimal) -> Decimal:
    """
    Convert decimal to basis points.
    
    Example: 0.005 -> 50 bps
    """
    return value * BPS_DENOMINATOR


def calculate_bps_diff(value_a: Decimal, value_b: Decimal) -> Decimal:
    """
    Calculate basis points difference between two values.
    
    Returns: (value_a - value_b) / value_b * 10000
    """
    if value_b == 0:
        return Decimal("0")
    return ((value_a - value_b) / value_b) * BPS_DENOMINATOR


# =============================================================================
# WEI CONVERSIONS
# =============================================================================

def wei_to_eth(wei: int) -> Decimal:
    """Convert wei to ETH as Decimal."""
    return Decimal(wei) / Decimal(WEI_PER_ETH)


def eth_to_wei(eth: Decimal | str) -> int:
    """Convert ETH to wei as int."""
    return int(Decimal(eth) * WEI_PER_ETH)


def wei_to_gwei(wei: int) -> Decimal:
    """Convert wei to gwei as Decimal."""
    return Decimal(wei) / Decimal(WEI_PER_GWEI)


def gwei_to_wei(gwei: Decimal | str | int) -> int:
    """Convert gwei to wei as int."""
    return int(Decimal(gwei) * WEI_PER_GWEI)


# =============================================================================
# TOKEN AMOUNT CONVERSIONS
# =============================================================================

def wei_to_human(wei: int, decimals: int) -> Decimal:
    """
    Convert wei amount to human-readable Decimal.
    
    Example: wei_to_human(1000000, 6) -> Decimal('1.0')  # 1 USDC
    """
    if decimals < 0 or decimals > 18:
        raise ValidationError(f"Invalid decimals: {decimals}")
    return Decimal(wei) / Decimal(10**decimals)


def human_to_wei(amount: Decimal | str, decimals: int) -> int:
    """
    Convert human-readable amount to wei.
    
    Example: human_to_wei('1.0', 6) -> 1000000  # 1 USDC in wei
    """
    if decimals < 0 or decimals > 18:
        raise ValidationError(f"Invalid decimals: {decimals}")
    return int(Decimal(amount) * Decimal(10**decimals))


# =============================================================================
# SAFE CONVERSIONS (NO FLOAT)
# =============================================================================

def safe_decimal(value: int | str | Decimal) -> Decimal:
    """
    Safely convert value to Decimal.
    
    Raises ValidationError if float is passed or conversion fails.
    """
    if isinstance(value, float):
        raise ValidationError(
            "Float values are not allowed. Use int, str, or Decimal.",
            {"value": value, "type": type(value).__name__}
        )
    
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError, TypeError) as e:
        raise ValidationError(
            f"Cannot convert to Decimal: {value}",
            {"value": value, "type": type(value).__name__, "error": str(e)}
        )


def safe_int(value: int | str | Decimal) -> int:
    """
    Safely convert value to int (wei).
    
    Raises ValidationError if float is passed or conversion fails.
    """
    if isinstance(value, float):
        raise ValidationError(
            "Float values are not allowed. Use int, str, or Decimal.",
            {"value": value, "type": type(value).__name__}
        )
    
    try:
        if isinstance(value, Decimal):
            return int(value.to_integral_value(rounding=ROUND_DOWN))
        return int(value)
    except (ValueError, TypeError) as e:
        raise ValidationError(
            f"Cannot convert to int: {value}",
            {"value": value, "type": type(value).__name__, "error": str(e)}
        )


# =============================================================================
# PNL CALCULATIONS
# =============================================================================

def calculate_net_pnl(
    revenue_wei: int,
    cost_wei: int,
    gas_cost_wei: int,
    decimals: int,
) -> Decimal:
    """
    Calculate net PnL in human-readable units.
    
    All inputs in wei. Returns Decimal.
    """
    net_wei = revenue_wei - cost_wei - gas_cost_wei
    return wei_to_human(net_wei, decimals)


def calculate_gas_cost_in_token(
    gas_used: int,
    gas_price_wei: int,
    eth_price: Decimal,
) -> Decimal:
    """
    Calculate gas cost in token units (e.g., USDC).
    
    Args:
        gas_used: Gas units used
        gas_price_wei: Gas price in wei
        eth_price: ETH price in token (e.g., ETH/USDC = 2500)
    
    Returns:
        Gas cost in token units as Decimal (e.g., 0.50 USDC)
    """
    gas_cost_eth = wei_to_eth(gas_used * gas_price_wei)
    return gas_cost_eth * eth_price


# =============================================================================
# PRICE CALCULATIONS
# =============================================================================

def calculate_price_impact_bps(
    amount_in: int,
    amount_out: int,
    amount_in_small: int,
    amount_out_small: int,
) -> Decimal:
    """
    Calculate price impact in basis points by comparing
    a large trade to a small reference trade.
    
    Returns: Positive value means worse execution.
    """
    if amount_in_small == 0 or amount_out_small == 0:
        return Decimal("0")
    
    # Price for large trade
    price_large = Decimal(amount_out) / Decimal(amount_in)
    
    # Price for small reference trade
    price_small = Decimal(amount_out_small) / Decimal(amount_in_small)
    
    if price_small == 0:
        return Decimal("0")
    
    # Impact = (price_small - price_large) / price_small * 10000
    impact = ((price_small - price_large) / price_small) * BPS_DENOMINATOR
    
    return impact


def normalize_price(
    amount_in: int,
    amount_out: int,
    decimals_in: int,
    decimals_out: int,
) -> Decimal:
    """
    Calculate normalized price (amount_out / amount_in adjusted for decimals).
    
    Used for comparison only, not for PnL calculation.
    """
    if amount_in == 0:
        return Decimal("0")
    
    normalized_in = Decimal(amount_in) / Decimal(10**decimals_in)
    normalized_out = Decimal(amount_out) / Decimal(10**decimals_out)
    
    return normalized_out / normalized_in


# =============================================================================
# ROUNDING HELPERS
# =============================================================================

def round_down(value: Decimal, decimals: int) -> Decimal:
    """Round down to specified decimal places."""
    quantizer = Decimal(10) ** (-decimals)
    return value.quantize(quantizer, rounding=ROUND_DOWN)


def round_up(value: Decimal, decimals: int) -> Decimal:
    """Round up to specified decimal places."""
    quantizer = Decimal(10) ** (-decimals)
    return value.quantize(quantizer, rounding=ROUND_UP)


# =============================================================================
# VALIDATION
# =============================================================================

def validate_no_float(*values: object) -> None:
    """
    Validate that none of the values are floats.
    
    Raises ValidationError if any float is found.
    """
    for i, value in enumerate(values):
        if isinstance(value, float):
            raise ValidationError(
                f"Float value at position {i} is not allowed",
                {"position": i, "value": value}
            )
