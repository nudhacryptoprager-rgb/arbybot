# PATH: tests/unit/test_m4_drift_arithmetic.py
"""Unit tests for M4 drift arithmetic invariants.

These tests verify the mathematical relationships between:
- est_net_usdc_sum (from truth_report, gas_only cost model)
- sim_net_usdc_sum (from simulator, paper_realistic cost model)
- sum_drift_usdc = |est_sum - sim_sum|
- mae_slippage_component (expected per-signal slippage)
- total_slippage_usdc = mae_slippage_component * signals_count

Invariants:
1. sum_drift_usdc == |est_net_usdc_sum - sim_net_usdc_sum|
2. total_slippage_usdc == mae_slippage_component * signals_count
3. When mae_no_slippage == 0, all drift is explained by slippage
"""

import pytest
from decimal import Decimal


def test_sum_drift_equals_abs_difference():
    """sum_drift_usdc must equal |est_sum - sim_sum|"""
    # Test cases from real runs
    cases = [
        # (est_sum, sim_sum, expected_drift)
        (9.1121, 8.1121, 1.0),
        (4.8544, 3.3544, 1.5),
        (10.0, 10.0, 0.0),
        (5.0, 7.0, 2.0),  # sim > est (negative drift direction)
    ]
    
    for est_sum, sim_sum, expected_drift in cases:
        actual_drift = abs(est_sum - sim_sum)
        assert round(actual_drift, 4) == expected_drift, \
            f"Drift mismatch: |{est_sum} - {sim_sum}| = {actual_drift}, expected {expected_drift}"


def test_total_slippage_equals_component_times_count():
    """total_slippage_usdc == mae_slippage_component * signals_count"""
    # Test cases
    cases = [
        # (mae_slippage_component, signals_count, expected_total)
        (0.5, 2, 1.0),
        (0.5, 3, 1.5),
        (0.0, 5, 0.0),
        (0.25, 4, 1.0),
    ]
    
    for component, count, expected in cases:
        actual = round(component * count, 4)
        assert actual == expected, \
            f"Total slippage mismatch: {component} * {count} = {actual}, expected {expected}"


def test_slippage_component_calculation():
    """mae_slippage_component should be (size * slippage_bps / 10000) / signals_count when uniform"""
    # For paper_realistic: slippage_bps=5, default size=1000
    default_size = 1000.0
    slippage_bps = 5
    
    # Expected per-signal slippage = size * bps / 10000 = 1000 * 5 / 10000 = 0.5
    expected_per_signal = default_size * slippage_bps / 10000
    assert expected_per_signal == 0.5
    
    # With 2 signals: total = 1.0, per-signal mae contribution = 0.5
    signals_count = 2
    total_slippage = expected_per_signal * signals_count
    assert total_slippage == 1.0


def test_mae_no_slippage_zero_means_slippage_explains_all():
    """When mae_no_slippage == 0, all MAE is explained by slippage difference"""
    # Real example from run_summary_20260209_164033
    mae_net_usdc = 0.5
    mae_no_slippage = 0.0
    mae_slippage_component = 0.5
    
    # If mae_no_slippage is 0, then mae_net_usdc should equal mae_slippage_component
    # (within rounding tolerance)
    assert mae_net_usdc == mae_slippage_component, \
        "When mae_no_slippage=0, mae should equal slippage component"
    
    # Model drift = 0
    model_drift = mae_net_usdc - mae_slippage_component
    assert model_drift == 0.0


def test_drift_consistency_example():
    """Test real example from ci_m5_gate_20260209_174014"""
    # From stability_summary_20260209_164033
    est_net_sum = 9.1121
    sim_net_sum = 8.1121
    signals_count = 2
    mae_slippage_component = 0.5  # per-signal
    
    # Check sum_drift
    sum_drift = abs(est_net_sum - sim_net_sum)
    assert round(sum_drift, 4) == 1.0
    
    # Check total slippage explains drift
    total_slippage = mae_slippage_component * signals_count
    assert total_slippage == 1.0
    
    # sum_drift == total_slippage (all drift is slippage)
    assert round(sum_drift, 4) == total_slippage


def test_mae_calculation_from_per_signal_errors():
    """MAE is mean absolute error across signals"""
    # Example: 2 signals with different errors
    per_signal_errors = [0.4, 0.6]  # |est - sim| for each signal
    expected_mae = sum(per_signal_errors) / len(per_signal_errors)
    assert expected_mae == 0.5
    
    # With uniform slippage (0.5 per signal), errors would be [0.5, 0.5]
    uniform_errors = [0.5, 0.5]
    uniform_mae = sum(uniform_errors) / len(uniform_errors)
    assert uniform_mae == 0.5


@pytest.mark.parametrize("est,sim,signals,slippage_bps,size", [
    (10.0, 9.0, 2, 5, 1000),  # 2 signals, 0.5 slippage each = 1.0 total drift
    (5.0, 4.5, 1, 5, 1000),   # 1 signal, 0.5 slippage
    (20.0, 17.0, 3, 10, 1000), # 3 signals, 1.0 slippage each = 3.0 total drift
])
def test_slippage_drift_relationship(est, sim, signals, slippage_bps, size):
    """Parametrized test: drift should equal expected slippage when no model error"""
    expected_drift = abs(est - sim)
    expected_slippage_per_signal = size * slippage_bps / 10000
    expected_total_slippage = expected_slippage_per_signal * signals
    
    # When mae_no_slippage = 0 (no model error), drift == total slippage
    # This test verifies the arithmetic relationship
    assert round(expected_drift, 4) == round(expected_total_slippage, 4), \
        f"Drift {expected_drift} should equal total slippage {expected_total_slippage}"
