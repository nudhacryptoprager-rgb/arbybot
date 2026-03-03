"""
no_data.py - NO_DATA reason classification helper.

This module provides deterministic classification of WHY a scan produced no data.
Centralizes the logic to avoid duplication between run_scan_real.py and tests.

v3.2.7: Initial implementation for artifact self-sufficiency.
"""

from typing import Optional


# Canonical reason values
NO_QUOTES = "NO_QUOTES"
ALL_QUOTES_REJECTED = "ALL_QUOTES_REJECTED"
NO_SPREAD_SIGNALS = "NO_SPREAD_SIGNALS"


def compute_no_data_reason(
    quotes_total: int,
    quotes_fetched: int,
    spread_signals_count: int,
) -> Optional[str]:
    """
    Compute the no_data_reason field for artifacts.
    
    This provides a deterministic explanation of WHY NO_DATA occurred,
    without requiring access to logs.
    
    Args:
        quotes_total: Total quotes attempted (before rejection)
        quotes_fetched: Valid quotes after rejection
        spread_signals_count: Number of spread signals passing threshold
    
    Returns:
        - "NO_QUOTES": No quotes were fetched at all
        - "ALL_QUOTES_REJECTED": Quotes fetched but all rejected
        - "NO_SPREAD_SIGNALS": Quotes valid but no spreads passed threshold
        - None: Data is present (spread_signals_count > 0)
    
    Examples:
        >>> compute_no_data_reason(0, 0, 0)
        'NO_QUOTES'
        >>> compute_no_data_reason(10, 0, 0)
        'ALL_QUOTES_REJECTED'
        >>> compute_no_data_reason(10, 8, 0)
        'NO_SPREAD_SIGNALS'
        >>> compute_no_data_reason(10, 8, 3)
        None
    """
    if quotes_fetched == 0 and quotes_total == 0:
        return NO_QUOTES
    if quotes_fetched == 0 and quotes_total > 0:
        return ALL_QUOTES_REJECTED
    if spread_signals_count == 0:
        return NO_SPREAD_SIGNALS
    return None


def canonicalize_config_path(path: Optional[str]) -> Optional[str]:
    """
    Canonicalize config_path to POSIX format with forward slashes.
    
    This ensures config_path is OS-independent for artifact comparison.
    
    Args:
        path: Original path (may contain backslashes on Windows)
    
    Returns:
        Path with forward slashes, or None if input is None
    
    Examples:
        >>> canonicalize_config_path("config\\\\real_minimal.yaml")
        'config/real_minimal.yaml'
        >>> canonicalize_config_path("config/real_minimal.yaml")
        'config/real_minimal.yaml'
        >>> canonicalize_config_path(None)
        None
    """
    if path is None:
        return None
    return path.replace("\\", "/")
