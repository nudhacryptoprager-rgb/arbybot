"""
M4 Metrics Module

Drift arithmetic, fragile detection, and MAE calculations.

Key metrics:
- MAE (Mean Absolute Error): Measures drift between estimate and simulation
- Fragile rate: Percentage of signals at risk of sign flip
- Sign rate: Percentage of signals with correct profit sign prediction
"""

from dataclasses import dataclass
from typing import List, Optional


@dataclass
class DriftMetrics:
    """Drift metrics between estimate and simulation."""
    est_net_sum: float  # Sum of estimate net PnL
    sim_net_sum: float  # Sum of simulated net PnL
    sum_drift: float    # Absolute difference
    mae: float          # Mean Absolute Error
    mae_no_slippage: float  # MAE without slippage component
    mae_slippage_component: float  # Slippage contribution to MAE
    sign_correct_rate: float  # Percentage with matching sign
    sign_mismatch_count: int  # Number of sign mismatches


@dataclass
class FragileMetrics:
    """Fragile signal detection metrics."""
    fragile_count: int  # Number of fragile signals
    fragile_rate: float  # Percentage of fragile signals
    total_signals: int


def calculate_mae(errors: List[float]) -> float:
    """
    Calculate Mean Absolute Error.
    
    Args:
        errors: List of (estimate - simulation) values
        
    Returns:
        MAE value, 0 if empty list
    """
    if not errors:
        return 0.0
    return sum(abs(e) for e in errors) / len(errors)


def calculate_sign_rate(est_values: List[float], sim_values: List[float]) -> tuple:
    """
    Calculate sign correctness rate.
    
    A signal has "correct sign" if both estimate and simulation
    agree on whether it's profitable (positive).
    
    Args:
        est_values: Estimated net PnL values
        sim_values: Simulated net PnL values
        
    Returns:
        (sign_rate: float, mismatch_count: int)
    """
    if not est_values or len(est_values) != len(sim_values):
        return 0.0, 0
    
    mismatch = 0
    for est, sim in zip(est_values, sim_values):
        # Sign mismatch if one is positive and other is non-positive
        est_positive = est > 0
        sim_positive = sim > 0
        if est_positive != sim_positive:
            mismatch += 1
    
    rate = 1.0 - (mismatch / len(est_values)) if est_values else 0.0
    return rate, mismatch


def detect_fragile_signals(
    sim_values: List[float],
    threshold_abs: float = 0.10,
) -> FragileMetrics:
    """
    Detect fragile signals that are close to sign flip.
    
    A signal is fragile if its simulated PnL is within threshold
    of zero (positive but small profit, easy to flip to loss).
    
    Args:
        sim_values: Simulated net PnL values
        threshold_abs: Absolute threshold in USDC (default: $0.10)
        
    Returns:
        FragileMetrics with count and rate
    """
    if not sim_values:
        return FragileMetrics(fragile_count=0, fragile_rate=0.0, total_signals=0)
    
    fragile = sum(1 for v in sim_values if 0 < v <= threshold_abs)
    rate = fragile / len(sim_values)
    
    return FragileMetrics(
        fragile_count=fragile,
        fragile_rate=round(rate, 4),
        total_signals=len(sim_values),
    )


def calculate_drift_status(
    mae: float,
    mae_warn: float,
    mae_fail: float,
) -> str:
    """
    Determine drift status based on MAE thresholds.
    
    Args:
        mae: Current MAE value
        mae_warn: Warning threshold
        mae_fail: Failure threshold
        
    Returns:
        'PASS', 'WARN', or 'FAIL'
    """
    # Note: thresholds are exclusive (> not >=)
    if mae > mae_fail:
        return "FAIL"
    if mae > mae_warn:
        return "WARN"
    return "PASS"


def calculate_profit_status(total_net_usdc: float) -> str:
    """
    Determine profit status.
    
    Args:
        total_net_usdc: Total simulated net PnL
        
    Returns:
        'PASS' if profitable (> 0), 'FAIL' otherwise
    """
    return "PASS" if total_net_usdc > 0 else "FAIL"
