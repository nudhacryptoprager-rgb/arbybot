"""
no_data.py - NO_DATA reason classification helper.

This module provides deterministic classification of WHY a scan produced no data.
Centralizes the logic to avoid duplication between run_scan_real.py and tests.

v3.2.7: Initial implementation for artifact self-sufficiency.
v3.2.54: Added ALL_OPPORTUNITIES_REJECTED for opportunity-level rejection tracking.
v3.2.55: Fixed semantics - total_opportunities > 0 is sufficient, profitable_accepted is diagnostic.
"""

from typing import Optional


# Canonical reason values
NO_QUOTES = "NO_QUOTES"
ALL_QUOTES_REJECTED = "ALL_QUOTES_REJECTED"
NO_SPREAD_SIGNALS = "NO_SPREAD_SIGNALS"
ALL_OPPORTUNITIES_REJECTED = "ALL_OPPORTUNITIES_REJECTED"


def compute_no_data_reason(
    quotes_total: int,
    quotes_fetched: int,
    spread_signals_count: int,
    total_opportunities: int = 0,
    profitable_accepted: int = 0,  # Deprecated: kept for signature compatibility
) -> Optional[str]:
    """
    Compute the no_data_reason field for artifacts.
    
    This provides a deterministic explanation of WHY NO_DATA occurred,
    without requiring access to logs.
    
    Args:
        quotes_total: Total quotes attempted (before rejection)
        quotes_fetched: Valid quotes after rejection
        spread_signals_count: Number of spread signals passing threshold
        total_opportunities: Total opportunities evaluated (from opportunity_engine)
        profitable_accepted: DEPRECATED - kept for signature compat, not used in logic.
                            In truth_mode, profitable_count is diagnostic only.
    
    Returns:
        - "NO_QUOTES": No quotes were fetched at all
        - "ALL_QUOTES_REJECTED": Quotes fetched but all rejected
        - "ALL_OPPORTUNITIES_REJECTED": Quotes valid, opportunities found, but none passed signal flow
        - "NO_SPREAD_SIGNALS": Quotes valid, no opportunities found at all
        - None: Data is present (spread_signals_count > 0)
    
    Note:
        The distinction between ALL_OPPORTUNITIES_REJECTED and NO_SPREAD_SIGNALS:
        - ALL_OPPORTUNITIES_REJECTED: opportunities were evaluated but ALL rejected (system/economics)
        - NO_SPREAD_SIGNALS: no opportunities were even found (true market absence)
    
    Examples:
        >>> compute_no_data_reason(0, 0, 0)
        'NO_QUOTES'
        >>> compute_no_data_reason(10, 0, 0)
        'ALL_QUOTES_REJECTED'
        >>> compute_no_data_reason(10, 8, 0)
        'NO_SPREAD_SIGNALS'
        >>> compute_no_data_reason(10, 8, 0, total_opportunities=5)
        'ALL_OPPORTUNITIES_REJECTED'
        >>> compute_no_data_reason(10, 8, 0, total_opportunities=5, profitable_accepted=3)
        'ALL_OPPORTUNITIES_REJECTED'
        >>> compute_no_data_reason(10, 8, 3)
        None
    """
    if quotes_fetched == 0 and quotes_total == 0:
        return NO_QUOTES
    if quotes_fetched == 0 and quotes_total > 0:
        return ALL_QUOTES_REJECTED
    # v3.2.55: Check for opportunity-level rejection - total_opportunities > 0 is sufficient
    # Do not condition on profitable_accepted (it's diagnostic in truth_mode).
    if spread_signals_count == 0:
        if total_opportunities > 0:
            return ALL_OPPORTUNITIES_REJECTED
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


def compute_config_fingerprint(config: dict) -> str:
    """
    Compute a fingerprint hash from key configuration parameters.
    
    This allows detecting when config has changed between runs,
    making comparisons meaningful. Two runs with different fingerprints
    should not be compared for drift analysis.
    
    Key parameters included:
    - pairs (sorted, as JSON)
    - dexes (sorted)
    - min_spread_bps
    - paper_size_usd
    - require_cross_dex
    - universe_source
    
    Args:
        config: Configuration dictionary
    
    Returns:
        8-character hex fingerprint (first 8 chars of SHA-256)
    
    Examples:
        >>> compute_config_fingerprint({"min_spread_bps": 10, "dexes": ["uniswap_v3"]})
        'a1b2c3d4'  # Example, actual value depends on config
    """
    import hashlib
    import json
    
    # Extract key parameters that affect economics/behavior
    key_params = {
        "dexes": sorted(config.get("dexes", [])),
        "min_spread_bps": config.get("min_spread_bps"),
        "paper_size_usd": config.get("paper_size_usd"),
        "paper_slippage_bps": config.get("paper_slippage_bps"),
        "require_cross_dex": config.get("require_cross_dex", False),
        "chain": config.get("chain", "unknown"),
    }
    
    # Handle pairs specially (list of dicts needs stable serialization)
    pairs = config.get("pairs", [])
    if pairs:
        # Extract just token_in/token_out for fingerprint
        pairs_key = sorted([
            f"{p.get('token_in', '')}_{p.get('token_out', '')}"
            for p in pairs if isinstance(p, dict)
        ])
        key_params["pairs_key"] = pairs_key
    
    # Stable JSON serialization for hashing
    json_str = json.dumps(key_params, sort_keys=True, separators=(",", ":"))
    hash_obj = hashlib.sha256(json_str.encode("utf-8"))
    return hash_obj.hexdigest()[:8]
