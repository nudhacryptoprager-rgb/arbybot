"""
M7.A.5.30 — Execution-adjacent profit guard for hot-lane scoring.

This module provides a minimal, execution-adjacent profit check that sits
between "model says profitable" and "submit transaction".

The contract follows the Flashbots simple-blind-arbitrage pattern:
- The final on-chain check must be `ending_balance > starting_balance`
  (or the transaction reverts).
- This module provides the simulated version of that check using
  local pool state + gas estimates, without any actual submission.

The guard is called from the hot lane after local pricing produces a
positive net_bps candidate.  It returns a ProfitGuardResult that the
loop uses to decide whether to promote the candidate to "executable".

Current implementation: local-only simulation (same data as scoring).
Future: eth_call simulation against actual router/executor contract.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from m7.shared.constants import (
    DEFAULT_BACKRUN_GAS,
    DEFAULT_GAS_PRICE_GWEI,
    GAS_FLOOR_BPS_ARBITRUM,
    TIMEBOOST_ELIGIBLE_BUDGET_MS,
)

logger = logging.getLogger("m7.orderflow.profit_guard")


@dataclass
class ProfitGuardResult:
    """Result of the execution-adjacent profit guard."""

    passed: bool = False
    net_pnl_wei: int = 0
    net_bps: float = 0.0
    gas_cost_wei: int = 0
    gas_bps: float = 0.0
    guard_mode: str = "local_sim"  # local_sim | eth_call | onchain
    reject_reason: Optional[str] = None
    guard_latency_ms: float = 0.0
    timeboost_eligible: bool = False
    details: Dict[str, Any] = field(default_factory=dict)


def check_profit_guard(
    *,
    buy_amount_wei: int,
    sell_amount_wei: int,
    backrun_size_wei: int,
    gas_estimate: int = DEFAULT_BACKRUN_GAS,
    gas_price_gwei: float = DEFAULT_GAS_PRICE_GWEI,
    token_decimals: int = 18,
    min_net_bps: float = 0.0,
    pipeline_latency_ms: Optional[float] = None,
) -> ProfitGuardResult:
    """Check whether the ending balance exceeds starting balance after gas.

    This is the local-simulation version of the on-chain profit check.
    It uses the same math as scoring but is structured as a separate
    guard that blocks non-profitable candidates from progressing.

    Parameters
    ----------
    buy_amount_wei : Simulated amount received from buy leg.
    sell_amount_wei : Simulated amount received from sell leg.
    backrun_size_wei : The input size (starting balance proxy).
    gas_estimate : Gas units for the transaction.
    gas_price_gwei : Gas price in gwei.
    token_decimals : Decimals of the profit token.
    min_net_bps : Minimum net bps threshold (default: 0 = any profit).
    pipeline_latency_ms : Total scoring pipeline latency; used for
        Timeboost eligibility (express lane budget = 50ms).

    Returns
    -------
    ProfitGuardResult with passed=True if ending > starting after gas.
    """
    _guard_start = time.monotonic()
    gross_pnl_wei = sell_amount_wei - backrun_size_wei
    gas_cost_eth_wei = int(gas_estimate * gas_price_gwei * 1e9)

    # Convert gas cost from ETH wei to token wei (simplified: assume 1:1 for ETH-denominated)
    # For non-ETH tokens, this needs a price oracle — currently uses gas_floor_bps as proxy
    gas_bps = GAS_FLOOR_BPS_ARBITRUM  # conservative floor

    if backrun_size_wei > 0:
        gross_bps = (gross_pnl_wei / backrun_size_wei) * 10000
        net_bps = gross_bps - gas_bps
    else:
        gross_bps = 0.0
        net_bps = 0.0

    net_pnl_wei = gross_pnl_wei - gas_cost_eth_wei

    # Core invariant: ending_balance > starting_balance
    passed = net_bps > min_net_bps and net_pnl_wei > 0

    reject_reason = None
    if not passed:
        if net_pnl_wei <= 0:
            reject_reason = "ENDING_BALANCE_NOT_GT_STARTING"
        elif net_bps <= min_net_bps:
            reject_reason = "BELOW_MIN_NET_BPS"

    _guard_ms = round((time.monotonic() - _guard_start) * 1000, 2)

    # M7.A.5.31: Timeboost eligibility — can this fit in the express lane budget?
    _tb_eligible = False
    if pipeline_latency_ms is not None:
        _tb_eligible = pipeline_latency_ms <= TIMEBOOST_ELIGIBLE_BUDGET_MS

    return ProfitGuardResult(
        passed=passed,
        net_pnl_wei=net_pnl_wei,
        net_bps=round(net_bps, 4),
        gas_cost_wei=gas_cost_eth_wei,
        gas_bps=round(gas_bps, 4),
        guard_mode="local_sim",
        reject_reason=reject_reason,
        guard_latency_ms=_guard_ms,
        timeboost_eligible=_tb_eligible,
        details={
            "gross_pnl_wei": gross_pnl_wei,
            "gross_bps": round(gross_bps, 4),
            "gas_estimate": gas_estimate,
            "gas_price_gwei": gas_price_gwei,
            "backrun_size_wei": backrun_size_wei,
        },
    )
