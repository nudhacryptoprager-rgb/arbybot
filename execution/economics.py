# PATH: execution/economics.py
"""
ARBY M4 Economics Module.

This module provides canonical calculations for arbitrage economics:
- Minimum required spread calculation (LP fees + slippage + gas + safety margin)
- Roundtrip profitability thresholds

The economics module centralizes cost calculations to ensure consistent
gating across the codebase and eliminate redundant calculations.

RESTORE CONTRACT:
- This module is the canonical source for `min_required_spread_bps`
- Any changes to fee/cost formulas must update this module first
- Tests in tests/unit/test_economics.py validate the contract
"""
from typing import Optional


def min_required_spread_bps(
    fee_bps_leg1: float,
    fee_bps_leg2: float,
    slippage_bps: float = 5.0,
    gas_usd: float = 0.10,
    size_usd: float = 250.0,
    safety_bps: float = 2.0,
) -> float:
    """
    Calculate minimum spread (bps) required for profitable roundtrip.
    
    This is the canonical economics formula for roundtrip profitability:
    
        min_required = LP_fees + slippage + gas_bps + safety_margin
        
    Where:
        LP_fees = fee_bps_leg1 + fee_bps_leg2 (each leg incurs pool fee)
        gas_bps = (gas_usd / size_usd) * 10000 (gas as % of notional)
        slippage_bps = expected slippage on both legs
        safety_bps = buffer for price movement during execution
    
    Args:
        fee_bps_leg1: LP fee for leg1 in bps (e.g., 30 for 0.30% fee tier 3000)
        fee_bps_leg2: LP fee for leg2 in bps (e.g., 30 for 0.30% fee tier 3000)
        slippage_bps: Expected slippage in bps (default: 5.0)
        gas_usd: Estimated gas cost in USD (default: 0.10 for Arbitrum)
        size_usd: Trade notional in USD (default: 250.0)
        safety_bps: Safety buffer in bps (default: 2.0)
        
    Returns:
        Minimum spread in bps required for profitable roundtrip
        
    Example:
        >>> min_required_spread_bps(30, 30, slippage_bps=5, gas_usd=0.10, size_usd=250)
        71.0  # 30+30+5+4+2 = 71 bps (fee=60, slippage=5, gas=4, safety=2)
        
    Contract:
        - Deterministic: same inputs always produce same output
        - All components are additive (no compounding)
        - Returns positive value (negative means all costs are covered)
    """
    # LP fees: roundtrip touches both pools
    lp_fee_bps = fee_bps_leg1 + fee_bps_leg2
    
    # Gas as bps of notional: (gas_usd / size_usd) * 10000
    # Protect against division by zero
    gas_bps = (gas_usd / size_usd) * 10000 if size_usd > 0 else 0.0
    
    # Total minimum required
    min_required = lp_fee_bps + slippage_bps + gas_bps + safety_bps
    
    return round(min_required, 2)


def spread_minus_required(
    spread_bps: float,
    fee_bps_leg1: float,
    fee_bps_leg2: float,
    slippage_bps: float = 5.0,
    gas_usd: float = 0.10,
    size_usd: float = 250.0,
    safety_bps: float = 2.0,
) -> float:
    """
    Calculate spread surplus (bps) after subtracting required costs.
    
    This is the canonical "is this opportunity worth evaluating" metric:
        spread_minus_required = spread_bps - min_required_spread_bps(...)
        
    Returns:
        Positive: spread covers all costs with margin
        Zero: spread exactly covers costs (breakeven)
        Negative: spread insufficient for profitability
        
    Contract:
        - If return > 0, roundtrip evaluation is warranted
        - If return <= 0, roundtrip is mathematically unprofitable
    """
    min_req = min_required_spread_bps(
        fee_bps_leg1=fee_bps_leg1,
        fee_bps_leg2=fee_bps_leg2,
        slippage_bps=slippage_bps,
        gas_usd=gas_usd,
        size_usd=size_usd,
        safety_bps=safety_bps,
    )
    return round(spread_bps - min_req, 2)


def fee_tier_to_bps(fee_tier: int) -> float:
    """
    Convert V3 fee tier to basis points.
    
    Fee tier values:
        100  -> 0.01% -> 1 bps
        500  -> 0.05% -> 5 bps
        3000 -> 0.30% -> 30 bps
        10000 -> 1.00% -> 100 bps
        
    Args:
        fee_tier: Uniswap V3 fee tier integer (100, 500, 3000, 10000)
        
    Returns:
        Fee in basis points
    """
    return fee_tier / 100.0


def is_roundtrip_candidate(
    spread_bps: float,
    fee_bps_leg1: float,
    fee_bps_leg2: float,
    slippage_bps: float = 5.0,
    gas_usd: float = 0.10,
    size_usd: float = 250.0,
    safety_bps: float = 2.0,
) -> bool:
    """
    Check if an opportunity should be evaluated for roundtrip.
    
    This is the canonical gating function for roundtrip evaluation.
    
    Contract:
        - Returns True iff spread_minus_required > 0
        - Used to filter candidates before expensive roundtrip simulation
    """
    surplus = spread_minus_required(
        spread_bps=spread_bps,
        fee_bps_leg1=fee_bps_leg1,
        fee_bps_leg2=fee_bps_leg2,
        slippage_bps=slippage_bps,
        gas_usd=gas_usd,
        size_usd=size_usd,
        safety_bps=safety_bps,
    )
    return surplus > 0
