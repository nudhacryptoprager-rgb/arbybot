"""
E1.12.2 — Execution gate: canonical terminal-stage pipeline.

Single entry point for the execution funnel stages beyond profit_guard:

    profit_guard_passed -> sim_attempted -> sim_passed -> submit_ready

This module:
  - Runs profit guard in batch on scored results
  - Wires Tenderly simulation for guard-passed candidates
  - Annotates BackrunResult with terminal stage fields
  - Returns SIM_DISABLED when Tenderly is not configured (honest blocker)

Usage:
    from m7.orderflow.execution_gate import run_execution_gate, ExecutionGateResult

    gate_result = run_execution_gate(fast_results, chain="base")
    gate_result.guard_passed   # list of (result, ProfitGuardResult)
    gate_result.sim_attempted  # count
    gate_result.sim_passed     # count
    gate_result.submit_ready   # count
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple

from m7.orderflow.profit_guard import ProfitGuardResult, check_profit_guard
from m7.orderflow.simulation import SimulationResult, is_tenderly_configured, simulate_swap

logger = logging.getLogger("m7.orderflow.execution_gate")


@dataclass
class ExecutionGateResult:
    """Aggregate result of running the full execution gate pipeline."""

    guard_passed: List[Tuple[Any, ProfitGuardResult]] = field(default_factory=list)
    sim_attempted: int = 0
    sim_passed: int = 0
    submit_ready: int = 0
    sim_disabled: bool = False
    sim_blocker: str = ""
    submit_blockers: List[str] = field(default_factory=list)


def _run_profit_guard_on_results(results: list, chain: str = "arbitrum_one") -> list:
    """Run profit_guard on all scored results with positive net_bps.

    Returns list of (result_dict_or_obj, ProfitGuardResult) for candidates
    that pass the guard.
    """
    passed = []
    for r in results:
        net = r.get("best_backrun_net_bps") if isinstance(r, dict) else getattr(r, "best_backrun_net_bps", None)
        if net is None or net <= 0:
            continue
        size = r.get("amount_in_wei") if isinstance(r, dict) else getattr(r, "amount_in_wei", 0)
        gross = r.get("gross_pnl_wei") if isinstance(r, dict) else getattr(r, "gross_pnl_wei", 0)
        buy = size
        sell = size + gross
        sv = r.get("size_valid_for_token") if isinstance(r, dict) else getattr(r, "size_valid_for_token", None)
        rr = r.get("reject_reason") if isinstance(r, dict) else getattr(r, "reject_reason", None)

        if sv is False:
            continue
        if rr == "REJECT_PRICING_ANOMALY":
            continue
        if not buy or not sell or not size:
            continue

        pipeline_ms = r.get("quote_pipeline_latency_ms") if isinstance(r, dict) else getattr(r, "quote_pipeline_latency_ms", None)
        guard = check_profit_guard(
            buy_amount_wei=buy, sell_amount_wei=sell, backrun_size_wei=size,
            pipeline_latency_ms=pipeline_ms, chain=chain,
        )
        if guard.passed:
            passed.append((r, guard))
    return passed


def _attempt_simulation(
    result: Any, guard: ProfitGuardResult, chain: str = "base"
) -> SimulationResult:
    """Attempt Tenderly fork simulation for a guard-passed candidate.

    If Tenderly is not configured, returns a result with
    error="SIM_DISABLED" (honest blocker, not masked as market).
    """
    if not is_tenderly_configured():
        return SimulationResult(success=False, error="SIM_DISABLED")

    # Build minimal tx params from the scored result.
    # Full calldata/signing is not yet wired — this is the scaffolding
    # point where tx_build + calldata stages will be connected.
    to_addr = "0x0000000000000000000000000000000000000000"
    calldata = b""
    value_wei = 0

    return simulate_swap(
        chain=chain,
        to_address=to_addr,
        calldata=calldata,
        value_wei=value_wei,
    )


def run_execution_gate(
    scored_results: list,
    chain: str = "base",
) -> ExecutionGateResult:
    """Run the full execution gate pipeline on scored results.

    Stages:
      1. profit_guard — filters to positive-net candidates
      2. simulation — Tenderly fork sim for each guard-passed candidate
      3. submit_ready — requires sim_passed + calldata + signing (future)

    Returns ExecutionGateResult with honest counts and blockers.
    """
    gate = ExecutionGateResult()

    # Stage 1: Profit guard
    gate.guard_passed = _run_profit_guard_on_results(scored_results, chain=chain)

    if not gate.guard_passed:
        return gate

    # Stage 2: Simulation
    _tenderly_configured = is_tenderly_configured()
    if not _tenderly_configured:
        gate.sim_disabled = True
        gate.sim_blocker = "SIM_DISABLED"
        # Annotate results with honest blocker
        for r, g in gate.guard_passed:
            if hasattr(r, "sim_attempted"):
                r.sim_attempted = False
                r.sim_passed = False
                r.simulation_error = "SIM_DISABLED"
                r.submit_ready = False
                r.submit_blocker = "SIM_DISABLED"
        return gate

    for r, g in gate.guard_passed:
        gate.sim_attempted += 1
        if hasattr(r, "sim_attempted"):
            r.sim_attempted = True

        sim_result = _attempt_simulation(r, g, chain=chain)

        if hasattr(r, "sim_passed"):
            r.sim_passed = sim_result.passed
            r.simulation_id = sim_result.simulation_id
            r.simulation_error = sim_result.error

        if sim_result.passed:
            gate.sim_passed += 1
            # Stage 3: Submit readiness (scaffolding)
            # Requires: calldata_ready + signing_ready
            _calldata_ready = getattr(r, "calldata_ready", None)
            _signing_ready = getattr(r, "signing_ready", None)
            if _calldata_ready and _signing_ready:
                gate.submit_ready += 1
                if hasattr(r, "submit_ready"):
                    r.submit_ready = True
            else:
                blockers = []
                if not _calldata_ready:
                    blockers.append("CALLDATA_NOT_READY")
                if not _signing_ready:
                    blockers.append("SIGNING_NOT_READY")
                if hasattr(r, "submit_ready"):
                    r.submit_ready = False
                    r.submit_blocker = ",".join(blockers)
                gate.submit_blockers.extend(blockers)
        else:
            if hasattr(r, "submit_ready"):
                r.submit_ready = False
                r.submit_blocker = f"SIM_FAILED:{sim_result.error or 'unknown'}"

    return gate
