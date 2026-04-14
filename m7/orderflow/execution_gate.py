"""
E1.12.2 — Execution gate: canonical terminal-stage pipeline.
E1.12.4A — Backend-agnostic simulation readiness.
E1.12.4B — Real calldata/gas path in _attempt_simulation().

Single entry point for the execution funnel stages beyond profit_guard:

    profit_guard_passed -> sim_attempted -> sim_passed -> submit_ready

This module:
  - Runs profit guard in batch on scored results
  - Wires simulation for guard-passed candidates (backend selected by ARBY_SIM_BACKEND)
  - Builds real V3 exactInputSingle calldata from BackrunResult data (4B)
  - Annotates BackrunResult with terminal stage fields
  - Returns SIM_DISABLED when no simulation backend is configured (honest blocker)

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
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from m7.orderflow.profit_guard import (
    ProfitGuardResult,
    annotate_profit_guard_results,
    check_profit_guard,
)
from m7.orderflow.simulation import (
    SimulationResult,
    is_simulation_configured,
    is_tenderly_configured,
    simulate_swap,
    get_simulation_backend,
)

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
    # E1.12.3: Per-candidate error reasons for reviewer-grade diagnosis
    sim_errors: List[str] = field(default_factory=list)
    submit_blockers_detail: List[str] = field(default_factory=list)
    # E1.12.4: Which simulation backend was used (anvil/tenderly/None)
    simulation_backend: Optional[str] = None


def _run_profit_guard_on_results(results: list, chain: str = "arbitrum_one") -> list:
    """Run profit_guard on all scored results with positive net_bps.

    E1.12.2 Phase 2: Delegates to annotate_profit_guard_results()
    (canonical batch helper in profit_guard.py). This function is
    maintained as the execution_gate entry point and for backward compat.

    Returns list of (result_dict_or_obj, ProfitGuardResult) for candidates
    that pass the guard.
    """
    return annotate_profit_guard_results(results, chain=chain)


# ---------------------------------------------------------------------------
# V3 calldata helpers (E1.12.4B)
# ---------------------------------------------------------------------------

# SwapRouter02 (Base, most L2s): no deadline, selector 0x04e45aaf
# Legacy SwapRouter (Arbitrum): has deadline, selector 0x414bf389
_SWAP_ROUTER02_CHAINS = {"base", "optimism", "linea"}

_SELECTOR_V2 = bytes.fromhex("04e45aaf")  # SwapRouter02
_SELECTOR_V1 = bytes.fromhex("414bf389")  # SwapRouter (legacy)


def _router_version(chain: str) -> int:
    """Return 2 for SwapRouter02 chains, 1 for legacy SwapRouter."""
    return 2 if chain in _SWAP_ROUTER02_CHAINS else 1


def _encode_address(addr: str) -> bytes:
    return bytes.fromhex(addr.lower().replace("0x", "").zfill(64))


def _encode_uint(val: int) -> bytes:
    return val.to_bytes(32, "big")


def _encode_exact_input_single(
    token_in: str,
    token_out: str,
    fee: int,
    recipient: str,
    amount_in: int,
    amount_out_min: int = 0,
    sqrt_price_limit: int = 0,
    router_version: int = 2,
) -> bytes:
    """Encode exactInputSingle calldata for V1 or V2 router.

    V2 (SwapRouter02): (tokenIn, tokenOut, fee, recipient, amountIn, amountOutMin, sqrtPriceLimit)
    V1 (SwapRouter):   (tokenIn, tokenOut, fee, recipient, deadline, amountIn, amountOutMin, sqrtPriceLimit)
    """
    params = (
        _encode_address(token_in)
        + _encode_address(token_out)
        + _encode_uint(fee)
        + _encode_address(recipient)
    )
    if router_version == 1:
        import time
        params += _encode_uint(int(time.time()) + 3600)  # deadline

    params += (
        _encode_uint(amount_in)
        + _encode_uint(amount_out_min)
        + _encode_uint(sqrt_price_limit)
    )

    selector = _SELECTOR_V1 if router_version == 1 else _SELECTOR_V2
    return selector + params


def _build_sim_tx_params(
    result: Any, chain: str = "base"
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Build real V3 swap tx params from a scored BackrunResult.

    E1.12.4B: Reuses config.get_dex_config() for router address and
    execution.gas_estimate.build_exact_input_single_calldata() for
    V3-compatible calldata.  Non-V3 adapters return an explicit
    ADAPTER_UNSUPPORTED reason.

    Returns:
        (tx_params, None) on success — tx_params has "to", "calldata", "value"
        (None, reason_str)  on failure
    """
    venue = getattr(result, "best_buy_venue", None)
    if not venue:
        return None, "VENUE_MISSING"

    pair = getattr(result, "actual_pair", None)
    if not pair or "/" not in pair:
        return None, "PAIR_UNRESOLVED"

    amount = getattr(result, "amount_in_wei", 0)
    if not amount or amount <= 0:
        return None, "AMOUNT_ZERO"

    # Resolve DEX config → router + adapter type
    try:
        from config import get_dex_config

        dex_cfg = get_dex_config(chain, venue)
    except (KeyError, ImportError):
        return None, f"DEX_CONFIG_MISSING:{venue}"

    router = dex_cfg.get("router")
    adapter_type = dex_cfg.get("adapter_type", "")
    if not router:
        return None, f"ROUTER_MISSING:{venue}"

    # V3-compatible adapters that use exactInputSingle calldata
    _V3_COMPATIBLE = {"uniswap_v3", "ve33", "algebra"}
    if adapter_type not in _V3_COMPATIBLE:
        return None, f"ADAPTER_UNSUPPORTED:{adapter_type}"

    # Resolve token addresses
    tokens = pair.split("/")
    if len(tokens) != 2:
        return None, f"PAIR_FORMAT_INVALID:{pair}"

    try:
        from config import get_token_address

        token_in_addr = get_token_address(chain, tokens[0])
        token_out_addr = get_token_address(chain, tokens[1])
    except ImportError:
        return None, "CONFIG_IMPORT_FAILED"

    if not token_in_addr or not token_out_addr:
        missing = []
        if not token_in_addr:
            missing.append(tokens[0])
        if not token_out_addr:
            missing.append(tokens[1])
        return None, f"TOKEN_ADDRESS_UNKNOWN:{','.join(missing)}"

    # Pick fee tier (first available from DEX config, or 3000 default)
    fee_tiers = dex_cfg.get("fee_tiers", [3000])
    fee = fee_tiers[0] if fee_tiers else 3000

    # Build V3 exactInputSingle calldata.
    # SwapRouter02 (Base, most L2s) uses 0x04e45aaf (no deadline field).
    # Legacy SwapRouter (Arbitrum) uses 0x414bf389 (with deadline).
    try:
        calldata = _encode_exact_input_single(
            token_in=token_in_addr,
            token_out=token_out_addr,
            fee=fee,
            recipient="0x0000000000000000000000000000000000000001",
            amount_in=amount,
            router_version=_router_version(chain),
        )
    except Exception as e:
        return None, f"CALLDATA_ENCODE_FAILED:{str(e)[:100]}"

    return {
        "to": router,
        "calldata": calldata,
        "value": 0,
    }, None


def _get_sim_from_address() -> str:
    """Simulation sender address.

    ARBY_SIM_FROM_ADDRESS overrides. Anvil default accounts do NOT have
    ERC-20 balances, so production usage should impersonate a whale or the
    executor wallet.  Falls back to Anvil default account #0 which at least
    has native ETH.
    """
    return os.environ.get(
        "ARBY_SIM_FROM_ADDRESS",
        "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
    )


def _attempt_simulation(
    result: Any, guard: ProfitGuardResult, chain: str = "base"
) -> SimulationResult:
    """Attempt simulation for a guard-passed candidate.

    E1.12.4B: Builds real V3 calldata from the scored result and sends
    to the configured simulation backend.  Falls back to an explicit
    error when calldata cannot be built (VENUE_MISSING, PAIR_UNRESOLVED,
    ADAPTER_UNSUPPORTED, etc.).
    """
    if not is_simulation_configured():
        return SimulationResult(success=False, error="SIM_DISABLED")

    tx_params, build_err = _build_sim_tx_params(result, chain)
    if tx_params is None:
        return SimulationResult(success=False, error=f"CALLDATA_BUILD_FAILED:{build_err}")

    return simulate_swap(
        chain=chain,
        from_address=_get_sim_from_address(),
        to_address=tx_params["to"],
        calldata=tx_params["calldata"],
        value_wei=tx_params["value"],
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

    # E1.12.4: Always record which simulation backend is available
    _sim_configured = is_simulation_configured()
    gate.simulation_backend = get_simulation_backend() if _sim_configured else None

    # Stage 1: Profit guard
    gate.guard_passed = _run_profit_guard_on_results(scored_results, chain=chain)

    if not gate.guard_passed:
        return gate

    # Stage 2: Simulation
    if not _sim_configured:
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

        try:
            sim_result = _attempt_simulation(r, g, chain=chain)
        except Exception as exc:
            # E1.15: Catch unexpected exceptions so sim_errors histogram
            # is always populated (fixes "10 unknown" telemetry gap).
            _exc_msg = f"SIM_EXCEPTION:{type(exc).__name__}:{str(exc)[:120]}"
            logger.warning("Simulation exception for %s: %s",
                           getattr(r, "event_id", "?"), _exc_msg)
            sim_result = SimulationResult(success=False, error=_exc_msg)

        if hasattr(r, "sim_passed"):
            r.sim_passed = sim_result.passed
            r.simulation_id = sim_result.simulation_id
            r.simulation_error = sim_result.error

        if sim_result.passed:
            gate.sim_passed += 1
            # Stage 3: Submit readiness
            # calldata_ready is True when calldata built successfully
            if hasattr(r, "calldata_ready"):
                r.calldata_ready = True
            # E1.15: Paper-live signing — ARBY_PAPER_SIGNING=1 enables
            # submit_ready counting without actual on-chain signing.
            # This proves the full pipeline path to submit_ready > 0.
            _paper_signing = os.environ.get("ARBY_PAPER_SIGNING", "").strip() == "1"
            if _paper_signing and hasattr(r, "signing_ready"):
                r.signing_ready = True
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
                gate.submit_blockers_detail.extend(blockers)
        else:
            _sim_err = sim_result.error or "unknown"
            gate.sim_errors.append(_sim_err)
            if hasattr(r, "submit_ready"):
                r.submit_ready = False
                r.submit_blocker = f"SIM_FAILED:{_sim_err}"

    return gate
