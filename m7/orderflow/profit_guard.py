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
    TIMEBOOST_ELIGIBLE_BUDGET_MS,
    estimate_gas_cost,
    get_gas_price_gwei,
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
    chain: str = "arbitrum_one",
    l1_fee_bps: float = 0.0,
    pre_computed_gas_bps: Optional[float] = None,
    pre_computed_gas_cost_wei: Optional[int] = None,
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
    pre_computed_gas_bps, pre_computed_gas_cost_wei : E1.35 P2.6 dedupe.
        When both are supplied (typically by the fast-scoring path that
        already ran :func:`estimate_gas_cost`), the guard reuses them
        instead of recomputing. Either both or neither must be provided.

    Returns
    -------
    ProfitGuardResult with passed=True if ending > starting after gas.
    """
    _guard_start = time.monotonic()
    gross_pnl_wei = sell_amount_wei - backrun_size_wei

    # E1.35 P2.6: accept pre-computed gas values from scoring to avoid
    # duplicate :func:`estimate_gas_cost` work.  Require both to be set
    # together so the result stays internally consistent.
    if (pre_computed_gas_bps is not None) and (pre_computed_gas_cost_wei is not None):
        gas_bps = float(pre_computed_gas_bps)
        gas_cost_wei = int(pre_computed_gas_cost_wei)
    else:
        # Unified gas estimation — chain-aware, consistent with scoring
        gas_bps, gas_cost_wei = estimate_gas_cost(
            chain, backrun_size_wei, gas_units=gas_estimate, l1_fee_bps=l1_fee_bps,
        )

    if backrun_size_wei > 0:
        gross_bps = (gross_pnl_wei / backrun_size_wei) * 10000
        net_bps = gross_bps - gas_bps
    else:
        gross_bps = 0.0
        net_bps = 0.0

    net_pnl_wei = gross_pnl_wei - gas_cost_wei

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
        gas_cost_wei=gas_cost_wei,
        gas_bps=round(gas_bps, 4),
        guard_mode="local_sim",
        reject_reason=reject_reason,
        guard_latency_ms=_guard_ms,
        timeboost_eligible=_tb_eligible,
        details={
            "gross_pnl_wei": gross_pnl_wei,
            "gross_bps": round(gross_bps, 4),
            "gas_estimate": gas_estimate,
            "gas_price_gwei": get_gas_price_gwei(chain),
            "backrun_size_wei": backrun_size_wei,
            "l1_fee_bps": l1_fee_bps,
        },
    )


def annotate_profit_guard_results(
    results: list,
    chain: str = "arbitrum_one",
    l1_fee_wei: int = 0,
) -> list:
    """Run profit guard on a list of scored results and annotate in-place.

    E1.12.2: Batch helper — replaces the per-script
    _run_profit_guard_on_results() pattern. Sets
    result.profit_guard_passed on each BackrunResult that has
    the attribute.

    Args:
        results: List of BackrunResult objects to check.
        chain: Chain name for gas estimation.
        l1_fee_wei: Absolute L1 data fee in wei (OP-Stack only).
            Converted per-candidate to bps using the candidate's
            trade size so that the fixed L1 cost is correctly
            normalized regardless of trade size.

    Returns list of (result, ProfitGuardResult) for candidates
    that pass the guard.
    """
    passed = []
    for r in results:
        net = (r.get("best_backrun_net_bps") if isinstance(r, dict)
               else getattr(r, "best_backrun_net_bps", None))
        if net is None or net <= 0:
            continue
        # M7.E1.34d: enforce invariant at source —
        # profit_guard_passed ≤ route_viable. Without this gate the
        # cumulative counters can diverge (30m discovery soak
        # 2026-04-21 showed +3 guard vs +0 viable).
        rv = (r.get("route_viable") if isinstance(r, dict)
              else getattr(r, "route_viable", None))
        if rv is False:
            if hasattr(r, "profit_guard_passed"):
                r.profit_guard_passed = False
            try:
                setattr(r, "guard_reject_reason", "ROUTE_NOT_VIABLE")
            except Exception:
                pass
            continue
        size = (r.get("amount_in_wei") if isinstance(r, dict)
                else getattr(r, "amount_in_wei", 0))
        gross = (r.get("gross_pnl_wei") if isinstance(r, dict)
                 else getattr(r, "gross_pnl_wei", 0))
        buy = size
        sell = size + gross
        sv = (r.get("size_valid_for_token") if isinstance(r, dict)
              else getattr(r, "size_valid_for_token", None))
        rr = (r.get("reject_reason") if isinstance(r, dict)
              else getattr(r, "reject_reason", None))
        if sv is False:
            continue
        if rr == "REJECT_PRICING_ANOMALY":
            continue
        if not buy or not sell or not size:
            continue
        pipeline_ms = (r.get("quote_pipeline_latency_ms") if isinstance(r, dict)
                       else getattr(r, "quote_pipeline_latency_ms", None))
        # E1.57: Per-candidate L1 fee bps.  The L1 fee is a fixed absolute cost
        # (independent of trade size), so we convert it to bps per candidate.
        # l1_fee_bps = (l1_fee_wei / backrun_size_wei) * 10000.
        # estimate_gas_cost then computes: l1_cost_wei = size * l1_fee_bps / 10000
        # = size * (l1_fee_wei / size) * 10000 / 10000 = l1_fee_wei.  Correct.
        _cand_l1_bps = 0.0
        if l1_fee_wei > 0 and size > 0:
            _cand_l1_bps = (l1_fee_wei / size) * 10_000
        guard = check_profit_guard(
            buy_amount_wei=buy, sell_amount_wei=sell,
            backrun_size_wei=size, pipeline_latency_ms=pipeline_ms,
            chain=chain,
            l1_fee_bps=_cand_l1_bps,
        )
        if hasattr(r, "profit_guard_passed"):
            r.profit_guard_passed = guard.passed
        try:
            setattr(r, "guard_reject_reason", guard.reject_reason)
        except Exception:
            pass
        if guard.passed:
            passed.append((r, guard))
    return passed
