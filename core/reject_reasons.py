# PATH: core/reject_reasons.py
"""
Canonical reject reasons for quotes and simulations.

This module defines all rejection reasons used across:
- Scanner (run_scan_real.py) for quote rejection
- M4 Execution Gate for simulation rejection
- M5 Gates for validation

DO NOT add reasons inline - add them here for traceability.
"""

from enum import Enum
from typing import Dict, Any, Optional


class QuoteRejectReason(str, Enum):
    """Quote-level rejection reasons (scanner phase)."""
    
    # Pool issues
    POOL_MISSING = "POOL_MISSING"              # No pool address configured
    POOL_NOT_FOUND = "POOL_NOT_FOUND"          # Pool not found on-chain
    
    # V3 slot0 issues
    V3_SLOT0_FAILED = "V3_SLOT0_FAILED"        # Failed to read slot0 from pool
    V3_TICK_INVALID = "V3_TICK_INVALID"        # Tick value out of range
    
    # Price calculation issues
    PRICE_CALC_FAILED = "PRICE_CALC_FAILED"    # Failed to calculate price from sqrt
    NO_ONCHAIN_PRICE = "NO_ONCHAIN_PRICE"      # No on-chain price available
    
    # Price sanity issues
    PRICE_OUTLIER = "PRICE_OUTLIER"            # Price outside expected range
    PRICE_SANITY_FAILED = "PRICE_SANITY_FAILED"  # Deviation > max allowed
    
    # Suspect (soft reject - logged but not hard fail)
    SUSPECT_PRICE_LOW = "SUSPECT_PRICE_LOW"    # Price below expected min
    SUSPECT_PRICE_HIGH = "SUSPECT_PRICE_HIGH"  # Price above expected max
    SUSPECT_LIQUIDITY = "SUSPECT_LIQUIDITY"    # Low liquidity warning


class SimRejectReason(str, Enum):
    """Simulation-level rejection reasons (M4 execution phase)."""
    
    # Simulation failures
    SIM_REVERT = "SIM_REVERT"                  # eth_call reverted
    SIM_GAS_TOO_HIGH = "SIM_GAS_TOO_HIGH"      # Gas estimate exceeds threshold
    SIM_UNPROFITABLE = "SIM_UNPROFITABLE"      # Net < 0 after costs
    SIM_SLIPPAGE = "SIM_SLIPPAGE"              # Actual slippage > expected
    SIM_BLOCK_STALE = "SIM_BLOCK_STALE"        # Block too old for execution
    SIM_NOT_IMPLEMENTED = "SIM_NOT_IMPLEMENTED"  # Simulation not yet implemented
    
    # Execution blockers
    EXEC_KILL_SWITCH = "EXEC_KILL_SWITCH"      # execution_enabled=false
    EXEC_INSUFFICIENT_BALANCE = "EXEC_INSUFFICIENT_BALANCE"
    EXEC_APPROVAL_NEEDED = "EXEC_APPROVAL_NEEDED"


def build_reject_entry(
    pair: str,
    dex_id: str,
    reason: str,
    *,
    pool_address: Optional[str] = None,
    error: Optional[str] = None,
    gate_passed: bool = False,
    suspect_quote: bool = False,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Build a standardized reject entry.
    
    Args:
        pair: Token pair (e.g., "WETH/USDC")
        dex_id: DEX identifier (e.g., "uniswap_v3")
        reason: Rejection reason (use QuoteRejectReason or SimRejectReason)
        pool_address: Pool contract address if known
        error: Error message if applicable
        gate_passed: Whether gate checks passed before rejection
        suspect_quote: Whether this is a soft reject (suspect)
        extra: Additional fields to include
    
    Returns:
        Standardized reject entry dict
    """
    entry = {
        "pair": pair,
        "dex_id": dex_id,
        "reason": reason,
        "gate_passed": gate_passed,
    }
    
    if pool_address:
        entry["pool_address"] = pool_address
    
    if error:
        entry["error"] = error
    
    if suspect_quote:
        entry["suspect_quote"] = True
    
    if extra:
        entry.update(extra)
    
    return entry


# Export all for convenience
__all__ = [
    "QuoteRejectReason",
    "SimRejectReason",
    "build_reject_entry",
]
