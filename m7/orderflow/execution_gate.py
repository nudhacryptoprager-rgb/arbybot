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


# ---------------------------------------------------------------------------
# E1.35 P1.3: registry-driven accepted fee tiers
# ---------------------------------------------------------------------------
# Previously the execution gate hardcoded a frozen set
#   {100, 500, 2500, 3000, 10000, 0, 1}.
# Every new DEX family (Algebra dynamic, Slipstream CL, Curve) required a
# manual patch. We now build the accepted-fees set from ``config/dexes.yaml``
# at first use, collecting every DEX's ``fee_tiers`` for the target chain
# plus the ve33 sentinels {0, 1}. The result is cached per-chain.
_VE33_FEE_SENTINELS = {0, 1}
_STANDARD_V3_FEES_FALLBACK = {100, 500, 2500, 3000, 10000}
_ACCEPTED_FEES_CACHE: Dict[str, frozenset] = {}

# M7.E1.34j: Aerodrome Slipstream fee→tickSpacing mapping.
# Pool identity on Slipstream is (tokenA, tokenB, tickSpacing); the per-pool
# `fee` is stored on-pool and observed in runtime events. To invoke the
# Slipstream adapter we must resolve fee→tickSpacing. Empirical mapping
# derived from verified Base pools (aerodrome.finance/security + on-chain
# inspection); fees not listed here keep the legacy PENDING bucket.
# Canonical Slipstream tickSpacings on Base: {1, 50, 100, 200, 2000}.
SLIPSTREAM_FEE_TO_TICKSPACING: Dict[int, int] = {
    150: 1,      # stable-stable / near-par (e.g. USDC/USDbC, EURC/USDC)
    445: 50,     # low-volatility pairs
    600: 50,     # low-volatility pairs
    1000: 100,   # medium-volatility (e.g. WETH/cbETH)
    2105: 100,   # medium-volatility
    1570: 100,   # medium-volatility (BUG-2 fix: Slipstream pool on Base, empirically observed)
    2600: 100,   # medium-volatility (E1.45: PROD soak fee_2600 SELL_FEE_UNSUPPORTED unblock)
    2655: 100,   # medium-volatility (dominant bucket in soak3 histogram)
    3024: 100,   # medium-volatility
    5000: 200,   # high-volatility (e.g. AERO/WETH)
    20000: 2000, # extreme-volatility / long-tail
}

# M7.E1.34k: per-pool tickSpacing cache (populated by scanner-side
# pool inspection — e.g. discovery calling pool.tickSpacing() and
# publishing via set_slipstream_pool_ts()). The cache is process-local
# and best-effort: when absent, _build_sim_tx_params falls back to
# the fee-family mapping above.
_slipstream_ts_cache: Dict[str, int] = {}


def _slipstream_ts_cache_get(pool_address: Optional[str]) -> Optional[int]:
    if not pool_address:
        return None
    return _slipstream_ts_cache.get(pool_address.lower())


def set_slipstream_pool_ts(pool_address: str, tick_spacing: int) -> None:
    """Publish a discovered pool tickSpacing into the local cache.

    Called by the discovery/bridge layer when a Slipstream pool's
    ``tickSpacing()`` has been read on-chain. ``tick_spacing`` must be
    a positive int24; non-positive values are ignored.
    """
    if not pool_address or not isinstance(tick_spacing, int):
        return
    if tick_spacing <= 0 or tick_spacing >= (1 << 23):
        return
    _slipstream_ts_cache[pool_address.lower()] = tick_spacing


def _reset_slipstream_ts_cache() -> None:
    """Test helper — drops the Slipstream ts cache."""
    _slipstream_ts_cache.clear()


def _build_slipstream_tx_params(
    slip_cfg: Dict[str, Any],
    token_in: str,
    token_out: str,
    tick_spacing: int,
    amount_in_wei: int,
    fee_hint: int,
) -> Dict[str, Any]:
    """Build Slipstream SwapRouter exactInputSingle tx params.

    Uses `execution.gas_estimate.build_slipstream_exact_input_single_calldata`
    which encodes the same-shape struct as Uniswap V3 but with
    int24 tickSpacing replacing uint24 fee.
    """
    from execution.gas_estimate import build_slipstream_exact_input_single_calldata

    calldata = build_slipstream_exact_input_single_calldata(
        token_in=token_in,
        token_out=token_out,
        tick_spacing=tick_spacing,
        recipient="0x0000000000000000000000000000000000000001",
        amount_in=amount_in_wei,
    )
    return {
        "to": slip_cfg.get("router"),
        "calldata": calldata,
        "value": 0,
        # Diagnostic marker — surfaces in sim samples so reviewer can
        # confirm Slipstream lane is actually attempting simulation.
        "adapter_type": "aerodrome_slipstream",
        "tick_spacing": tick_spacing,
        "fee_hint": fee_hint,
    }


def _compute_accepted_fees(chain: str) -> frozenset:
    """Collect accepted fee tiers for *chain* from the DEX registry.

    Falls back to the legacy hardcoded set ∪ {0, 1} if the registry is
    unreadable (missing yaml, parse error). A DEX may opt out by omitting
    ``fee_tiers`` from its config; Slipstream-style CL venues should be
    routed via their ``tick_spacings`` through the adapter layer, not
    through this gate.
    """
    try:
        from config import load_dexes as _load_dexes
        dexes = _load_dexes() or {}
    except Exception as exc:
        logger.debug("_compute_accepted_fees: registry load failed (%s)", exc)
        return frozenset(_STANDARD_V3_FEES_FALLBACK | _VE33_FEE_SENTINELS)

    chain_cfg = dexes.get(chain) or {}
    fees: set = set(_VE33_FEE_SENTINELS)
    for _dex_key, _dex_cfg in chain_cfg.items():
        if not isinstance(_dex_cfg, dict):
            continue
        _tiers = _dex_cfg.get("fee_tiers")
        if isinstance(_tiers, (list, tuple)):
            for _t in _tiers:
                try:
                    fees.add(int(_t))
                except (TypeError, ValueError):
                    continue
    if not fees - _VE33_FEE_SENTINELS:
        fees |= _STANDARD_V3_FEES_FALLBACK
    return frozenset(fees)


def get_accepted_fees(chain: str) -> frozenset:
    """Cached access to the registry-driven accepted-fees set."""
    _key = (chain or "").strip().lower()
    if _key not in _ACCEPTED_FEES_CACHE:
        _ACCEPTED_FEES_CACHE[_key] = _compute_accepted_fees(_key)
    return _ACCEPTED_FEES_CACHE[_key]


def _reset_accepted_fees_cache() -> None:
    """Test helper — drops the per-chain fee cache."""
    _ACCEPTED_FEES_CACHE.clear()


def _env_float(name: str, default: float) -> float:
    """Best-effort float env parser for diagnostic thresholds."""
    try:
        return float(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _calldata_hex(calldata: Any) -> Optional[str]:
    """Return a 0x-prefixed calldata hex string for bounded telemetry."""
    if isinstance(calldata, bytes):
        return "0x" + calldata.hex()
    if isinstance(calldata, str):
        return calldata if calldata.startswith("0x") else "0x" + calldata
    return None


def _calldata_prefix(value: Any, limit: int = 160) -> Optional[str]:
    hx = _calldata_hex(value)
    if hx is None:
        hx = value if isinstance(value, str) else None
    if not hx:
        return None
    return hx[:limit]


def _annotate_tx_telemetry(
    result: Any,
    tx_params: Dict[str, Any],
    prefix: str,
    *,
    venue: Optional[str] = None,
    fee: Optional[int] = None,
    adapter_type: Optional[str] = None,
    tick_spacing: Optional[int] = None,
) -> None:
    """Attach tx metadata to BackrunResult for failed/success samples."""
    calldata = tx_params.get("calldata")
    hx = _calldata_hex(calldata)
    calldata_len = len(calldata) if isinstance(calldata, (bytes, str)) else 0
    router = tx_params.get("to")
    try:
        setattr(result, f"{prefix}_router_address", router)
        setattr(result, f"{prefix}_calldata_hex", hx)
        setattr(result, f"{prefix}_calldata_len", calldata_len)
        if venue is not None:
            setattr(result, f"{prefix}_venue", venue)
        if fee is not None:
            setattr(result, f"{prefix}_fee", fee)
        if adapter_type is not None:
            setattr(result, f"{prefix}_adapter_type", adapter_type)
        if tick_spacing is not None:
            setattr(result, f"{prefix}_tick_spacing", tick_spacing)
        if prefix == "sim":
            # Existing diagnostics look for these legacy names.
            result.router_address = router  # type: ignore[attr-defined]
            result.sim_tx_to = router  # type: ignore[attr-defined]
    except Exception:
        pass


def _scorer_sim_divergence_blocker(
    scored_net_bps: Any,
    roundtrip_profit_bps: Any,
) -> Optional[str]:
    """Classify scorer-vs-roundtrip divergence without mutating sim counters."""
    threshold = _env_float("ARBY_SCORER_SIM_DIVERGENCE_BPS", 500.0)
    if threshold <= 0:
        return None
    try:
        scored = float(scored_net_bps)
        roundtrip = float(roundtrip_profit_bps)
    except (TypeError, ValueError):
        return None
    if scored > 0 and roundtrip <= 0 and (scored - roundtrip) >= threshold:
        return f"SCORER_SIM_DIVERGENCE:{scored:.4f}->{roundtrip:.4f}"
    return None


def _build_submit_blockers(
    sim_result: SimulationResult,
    scored_net_bps: Any,
    calldata_ready: Any,
    signing_ready: Any,
) -> List[str]:
    """Return terminal blockers for submit readiness."""
    blockers: List[str] = []
    if getattr(sim_result, "freshness_violation", False):
        blockers.append("SIM_FRESHNESS_VIOLATION")
    if sim_result.roundtrip_attempted:
        if not sim_result.roundtrip_success:
            blockers.append("ROUNDTRIP_NOT_SUCCESS")
        elif sim_result.roundtrip_profit_bps <= 0:
            blockers.append("ROUNDTRIP_NOT_PROFITABLE")
            divergence = _scorer_sim_divergence_blocker(
                scored_net_bps, sim_result.roundtrip_profit_bps
            )
            if divergence:
                blockers.append(divergence)
    if not calldata_ready:
        blockers.append("CALLDATA_NOT_READY")
    if not signing_ready:
        blockers.append("SIGNING_NOT_READY")
    return blockers


def _build_sim_output_sample(
    result: Any,
    sim_result: SimulationResult,
    scored_net_bps: Any,
    submit_blockers: List[str],
) -> Dict[str, Any]:
    """Bounded success sample for scorer/sim/roundtrip diagnosis."""
    buy_calldata = getattr(result, "sim_calldata_hex", None)
    sell_calldata = getattr(result, "sell_calldata_hex", None)
    return {
        "event_id": getattr(result, "event_id", None),
        "event_tx_hash": (
            getattr(result, "tx_hash", None)
            or getattr(result, "event_tx_hash", None)
        ),
        "pair": getattr(result, "actual_pair", None),
        "amount_in_wei": getattr(result, "amount_in_wei", 0) or 0,
        "sim_output_wei": sim_result.output_amount_wei,
        "sim_input_wei": sim_result.input_amount_wei,
        "scored_net_bps": scored_net_bps,
        "buy_venue": getattr(result, "best_buy_venue", None),
        "sell_venue": getattr(result, "best_sell_venue", None),
        "buy_fee": getattr(result, "best_buy_fee", None),
        "sell_fee": getattr(result, "best_sell_fee", None),
        "token_in": (
            getattr(result, "backrun_token_in_address", None)
            or getattr(result, "token_in", None)
        ),
        "token_out": (
            getattr(result, "backrun_token_out_address", None)
            or getattr(result, "token_out", None)
        ),
        "token_in_decimals": getattr(result, "token_in_decimals", None),
        "size_usd_estimate": getattr(result, "size_usd_estimate", None),
        "best_sweep_size_wei": getattr(result, "best_sweep_size_wei", None),
        "best_sweep_net_bps": getattr(result, "best_sweep_net_bps", None),
        "scoring_path": getattr(result, "scoring_path", None),
        "pricing_path": getattr(result, "pricing_path", None),
        "adapter_type_used": getattr(result, "adapter_type_used", None),
        "event_block": getattr(result, "event_block", None),
        "quote_block": getattr(result, "quote_block", None),
        "block_lag": getattr(result, "block_lag", None),
        "sim_backend": sim_result.backend,
        "sim_block_number": sim_result.sim_block_number,
        "event_block_number": sim_result.event_block_number,
        "block_lag_at_sim": sim_result.block_lag_at_sim,
        "freshness_violation": sim_result.freshness_violation,
        "buy_router": (
            getattr(result, "sim_router_address", None)
            or getattr(result, "router_address", None)
        ),
        "buy_calldata_len": getattr(result, "sim_calldata_len", None),
        "buy_calldata_prefix": _calldata_prefix(buy_calldata),
        "sell_router": getattr(result, "sell_router_address", None),
        "sell_calldata_len": getattr(result, "sell_calldata_len", None),
        "sell_calldata_prefix": _calldata_prefix(sell_calldata),
        "roundtrip_attempted": sim_result.roundtrip_attempted,
        "roundtrip_success": sim_result.roundtrip_success,
        "roundtrip_profit_wei": sim_result.roundtrip_profit_wei,
        "roundtrip_profit_bps": sim_result.roundtrip_profit_bps,
        "roundtrip_final_wei": sim_result.roundtrip_final_wei,
        "roundtrip_sell_revert_reason": sim_result.roundtrip_sell_revert_reason,
        "submit_blockers": list(submit_blockers),
    }


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
    # E1.27/D1: Raw sim output amounts (wei) for offline profit analysis.
    # Profit in bps cannot be derived here because token decimals differ.
    sim_output_samples: List[Dict[str, Any]] = field(default_factory=list)
    # M7.E1.34c: Terminal-stage samples for FAILED sims — reviewer asked
    # for calldata-level visibility (token/venue/router/amount + decoded
    # revert tag) beyond the aggregate simulation_error_histogram.
    sim_failed_samples: List[Dict[str, Any]] = field(default_factory=list)
    # M7.E1.34f post-soak19 reviewer fix #6: bounded ring of samples for
    # PRE_SIM_SKIP:MISSING_SIZE_METADATA so reviewer can see WHICH
    # pair/pool/token combinations are still arriving without sizing
    # metadata. Each entry: {pair, pool, token_in, decimals_src,
    # missing_fields, fee_hint, venue}.
    pre_sim_skip_samples: List[Dict[str, Any]] = field(default_factory=list)
    # Reviewer post-soak21 P0: bounded ring of structured reproducer
    # samples for SCORER_SIM_DIVERGENCE so reviewer can pinpoint which
    # pool/pair/fee/direction/amount combos are causing fast-path↔sim
    # quote-model drift. Each entry captures the minimum context needed
    # to reproduce the divergence offline.
    scorer_sim_divergence_samples: List[Dict[str, Any]] = field(default_factory=list)
    # E2: Round-trip (buy+sell) same-token bps metrics. These are VALID bps
    # because initial and final amounts are the same token.
    roundtrip_attempted: int = 0
    roundtrip_success: int = 0
    roundtrip_profitable_count: int = 0
    roundtrip_profit_bps_values: List[float] = field(default_factory=list)
    roundtrip_errors: List[str] = field(default_factory=list)
    # E4: Diagnostic — true when guard was bypassed via ARBY_SIM_BYPASS_GUARD.
    guard_bypassed: bool = False


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


def _resolve_address_prefix(chain: str, prefix: str) -> Optional[str]:
    """E1.17: Resolve a truncated address prefix (e.g. '0x696f9436') to a full
    checksummed address by scanning core_tokens.yaml entries for the chain.

    Returns full address if found, None otherwise.
    """
    try:
        from config import get_all_token_addresses
        tokens = get_all_token_addresses(chain)
        prefix_lower = prefix.lower()
        for _sym, addr in tokens.items():
            if addr.lower().startswith(prefix_lower):
                return addr
    except (ImportError, Exception):
        pass
    return None


# ---------------------------------------------------------------------------
# ve33 (Velodrome/Aerodrome) calldata helpers (E1.18)
# ---------------------------------------------------------------------------

# Aerodrome V2 Router selector: swapExactTokensForTokens(uint256,uint256,(address,address,bool,address)[],address,uint256)
_SELECTOR_VE33 = bytes.fromhex("cac88ea9")

# Default Aerodrome factory on Base
_AERODROME_FACTORY_DEFAULT = "0x420DD381b31aEf6683db6B902084cB0FFECe40Da"


def _encode_bool(val: bool) -> bytes:
    return _encode_uint(1 if val else 0)


def _encode_velodrome_swap(
    token_in: str,
    token_out: str,
    recipient: str,
    amount_in: int,
    amount_out_min: int = 0,
    stable: bool = False,
    factory: str = _AERODROME_FACTORY_DEFAULT,
) -> bytes:
    """E1.18: Encode Velodrome/Aerodrome V2 swapExactTokensForTokens calldata.

    Solidity signature:
        swapExactTokensForTokens(
            uint256 amountIn,
            uint256 amountOutMin,
            Route[] calldata routes,  // Route = (address from, address to, bool stable, address factory)
            address to,
            uint256 deadline
        )

    ABI encoding for dynamic array:
        selector(4) + amountIn(32) + amountOutMin(32) + routes_offset(32) +
        to(32) + deadline(32) + routes_length(32) +
        [route0: from(32) + to(32) + stable(32) + factory(32)]
    """
    import time as _time

    deadline = int(_time.time()) + 3600

    # Fixed-size head: amountIn, amountOutMin, routes_offset, to, deadline
    # routes_offset = 5 * 32 = 160 (offset from start of params to routes array)
    head = (
        _encode_uint(amount_in)
        + _encode_uint(amount_out_min)
        + _encode_uint(160)  # offset to routes array data
        + _encode_address(recipient)
        + _encode_uint(deadline)
    )

    # Dynamic tail: routes array (single route for now)
    routes_data = (
        _encode_uint(1)  # routes.length = 1
        + _encode_address(token_in)     # route[0].from
        + _encode_address(token_out)    # route[0].to
        + _encode_bool(stable)          # route[0].stable
        + _encode_address(factory)      # route[0].factory
    )

    return _SELECTOR_VE33 + head + routes_data


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
        # Step 1 (venue auto-registry fallback):
        # If scoring did not set best_buy_venue (quoter quota, stale fallback,
        # event-sourced flow), pick the first V3-compatible DEX from the
        # chain's registry that supports best_buy_fee. This eliminates the
        # CALLDATA_BUILD_FAILED:VENUE_MISSING blocker which dominated the
        # hot lane (~85% of sim errors in the Apr-21 soak).
        _fee_hint = getattr(result, "best_buy_fee", None)
        try:
            from config import load_dexes as _load_dexes_fallback
            _all_dexes = (_load_dexes_fallback() or {}).get(chain, {}) or {}
        except Exception:
            _all_dexes = {}
        _V3_LIKE = {"uniswap_v3", "algebra", "ve33"}
        _preferred_order = ["uniswap_v3", "aerodrome", "sushiswap_v3", "pancakeswap_v3"]
        _picked: Optional[str] = None
        for _cand in _preferred_order:
            _cfg = _all_dexes.get(_cand)
            if not isinstance(_cfg, dict):
                continue
            if _cfg.get("adapter_type", "") not in _V3_LIKE:
                continue
            if not _cfg.get("router"):
                continue
            _tiers = _cfg.get("fee_tiers") or []
            if _fee_hint is None or _fee_hint in {0, 1} or (
                isinstance(_fee_hint, int) and _fee_hint in _tiers
            ):
                _picked = _cand
                break
        if _picked is None:
            for _name, _cfg in _all_dexes.items():
                if not isinstance(_cfg, dict):
                    continue
                if _cfg.get("adapter_type", "") in _V3_LIKE and _cfg.get("router"):
                    _picked = _name
                    break
        if _picked is None:
            return None, "VENUE_MISSING"
        # Annotate result so downstream diagnostic logs see the resolved venue.
        try:
            result.best_buy_venue = _picked  # type: ignore[attr-defined]
        except Exception:
            pass
        venue = _picked
        logger.debug(
            "sim venue auto-resolved: pair=%s fee=%s -> %s",
            getattr(result, "actual_pair", "?"), _fee_hint, venue,
        )

    pair = getattr(result, "actual_pair", None)
    if not pair or "/" not in pair:
        return None, "PAIR_UNRESOLVED"

    amount = getattr(result, "amount_in_wei", 0)
    # Soak13 adaptive sizing: when scoring computed a best_sweep_size_wei
    # (optimal size by sweep optimization), prefer it over the raw
    # amount_in_wei inherited from the observed event. The mimicked
    # event-size often catastrophically over-sizes our backrun into
    # low-liquidity pools (soak12 roundtrip_profit_bps ≈ -9937 root cause).
    # ARBY_ADAPTIVE_SIZING=0 disables to preserve legacy behavior.
    if os.environ.get("ARBY_ADAPTIVE_SIZING", "1").strip() == "1":
        _sweep_pref = getattr(result, "best_sweep_size_wei", None)
        if isinstance(_sweep_pref, int) and _sweep_pref > 0:
            # Use sweep size only when it actually differs and looks sane
            # (strictly smaller than current amount, or current is zero).
            if amount <= 0 or _sweep_pref < amount:
                if amount > 0 and _sweep_pref != amount:
                    logger.debug(
                        "sim amount adaptive: pair=%s raw=%d sweep=%d (using sweep)",
                        pair, amount, _sweep_pref,
                    )
                amount = _sweep_pref
                try:
                    result.amount_in_wei = amount  # type: ignore[attr-defined]
                except Exception:
                    pass
    if not amount or amount <= 0:
        # Step 6 (AMOUNT_ZERO auto-fill):
        # Some producers (PTT-direct, broad-fallback without pool-resolve,
        # hot-rehydrate) construct BackrunResult with default amount_in_wei=0.
        # Rather than failing the sim, derive a safe fallback size from
        # available fields before giving up.
        _decimals = getattr(result, "token_in_decimals", None) or 18
        _autofill = 0
        # Prefer explicit sweep result when scoring computed it
        _sweep = getattr(result, "best_sweep_size_wei", None)
        if isinstance(_sweep, int) and _sweep > 0:
            _autofill = _sweep
        # Otherwise fall back to chain minimum profitable size
        if _autofill <= 0:
            try:
                from m7.shared.constants import get_min_profitable_size_wei
                _autofill = get_min_profitable_size_wei(chain, _decimals)
            except Exception:
                _autofill = 0
        if _autofill <= 0:
            return None, "AMOUNT_ZERO"
        try:
            result.amount_in_wei = _autofill  # type: ignore[attr-defined]
        except Exception:
            pass
        amount = _autofill
        logger.debug(
            "sim amount auto-filled: pair=%s decimals=%s -> %d wei",
            pair, _decimals, amount,
        )

    # Resolve DEX config → router + adapter type
    # E1.16: When venue is a pool address (starts with 0x), fall back to
    # iterating configured DEXes for the chain to find a V3-compatible one.
    # E1.17: Try factory-based matching first for more accurate DEX resolution.
    # E1.26: PTT pools now carry real DEX names (uniswap_v3, aerodrome, etc.)
    #        via fee-based mapping in register_ptt_pools().  Only truly unknown
    #        pools still have venue="ptt_direct".
    try:
        from config import get_dex_config

        dex_cfg = get_dex_config(chain, venue)
    except (KeyError, ImportError):
        dex_cfg = None
        if venue.startswith("0x") or venue == "ptt_direct":
            # E1.26: Use best_buy_fee to pick the correct DEX instead of
            # always falling back to uniswap_v3.
            _fee_hint = getattr(result, "best_buy_fee", None)
            from config import get_dex_config as _gdc

            if _fee_hint is not None and _fee_hint <= 1:
                # ve33 (Aerodrome): fee 0=volatile, 1=stable
                _preferred = ["aerodrome", "uniswap_v3", "sushiswap_v3", "pancakeswap_v3"]
            elif _fee_hint == 2500:
                # PancakeSwap unique tier
                _preferred = ["pancakeswap_v3", "uniswap_v3", "sushiswap_v3", "aerodrome"]
            elif _fee_hint is None or _fee_hint in {100, 500, 3000, 10000}:
                # Unknown fee or standard V3 tiers → default to uniswap_v3
                _preferred = ["uniswap_v3", "sushiswap_v3", "pancakeswap_v3", "aerodrome"]
            elif _fee_hint > 10:
                # E1.32: Non-standard fee — classify origin for monitoring.
                # Aerodrome CL (Slipstream) uses custom per-pool fees driven
                # by tickSpacing (e.g. 150/445/600/2105/2655/3024). Algebra
                # dynamic pools can emit fees like 85 that change on-demand.
                # E1.35 P1.1 step 3: When a Slipstream adapter+config is
                # present (verified=True), reclassify AERODROME_CL rejects
                # under a distinct bucket to surface progress.  The adapter
                # exists and calldata encoding is ready, but per-pool
                # `tickSpacing` lookup is still pending (scanner does not
                # yet carry it through BackrunResult).  Submit remains
                # blocked until the lookup layer lands.
                _AERODROME_CL_KNOWN = {150, 445, 600, 1000, 1570, 2105, 2600, 2655, 3024, 5000, 9500, 20000}
                if _fee_hint in _AERODROME_CL_KNOWN:
                    try:
                        _slip_cfg = _gdc(chain, "aerodrome_slipstream")
                    except (KeyError, ImportError):
                        _slip_cfg = None
                    if (
                        _slip_cfg
                        and _slip_cfg.get("verified") is True
                        and _slip_cfg.get("router")
                        and _slip_cfg.get("quoter_v2")
                    ):
                        # M7.E1.34k: per-pool tickSpacing lookup lands.
                        # Resolution order:
                        #   1. `result.best_buy_tick_spacing`   (scanner-injected)
                        #   2. cached pool→ts lookup            (_slipstream_ts_cache)
                        #   3. SLIPSTREAM_FEE_TO_TICKSPACING    (fee-family fallback)
                        # When resolved, build Slipstream SwapRouter calldata
                        # so the candidate enters sim_attempted instead of
                        # being parked in PRE_SIM_SKIP. submit remains
                        # kill-switched by execution policy — this change
                        # only unlocks simulation for the CL lane.
                        _ts = (
                            getattr(result, "best_buy_tick_spacing", None)
                            or _slipstream_ts_cache_get(venue)
                            or SLIPSTREAM_FEE_TO_TICKSPACING.get(int(_fee_hint))
                        )
                        if _ts is not None:
                            # Resolve token addresses before building calldata
                            _tin = getattr(result, "backrun_token_in_address", None)
                            _tout = getattr(result, "backrun_token_out_address", None)
                            if _tin and _tout:
                                _tx = _build_slipstream_tx_params(
                                    _slip_cfg,
                                    _tin,
                                    _tout,
                                    int(_ts),
                                    int(getattr(result, "amount_in_wei", 0) or 0),
                                    int(_fee_hint),
                                )
                                _annotate_tx_telemetry(
                                    result,
                                    _tx,
                                    "sim",
                                    venue=venue,
                                    fee=int(_fee_hint),
                                    adapter_type=_tx.get("adapter_type"),
                                    tick_spacing=int(_ts),
                                )
                                return _tx, None
                            # No token addresses — surface a distinct bucket
                            # so the reviewer can tell it from fee mapping gaps.
                            return None, (
                                f"SLIPSTREAM_SIM_READY_TOKENS_MISSING:"
                                f"{_fee_hint}:ts{_ts}"
                            )
                        return None, f"SLIPSTREAM_PENDING_LOOKUP:{_fee_hint}"
                    return None, f"UNSUPPORTED_FEE_TIER:AERODROME_CL:{_fee_hint}"
                # Very small non-standard (often Algebra dynamic starting fee)
                if _fee_hint <= 100:
                    return None, f"UNSUPPORTED_FEE_TIER:ALGEBRA_DYNAMIC:{_fee_hint}"
                return None, f"UNSUPPORTED_FEE_TIER:UNKNOWN:{_fee_hint}"
            else:
                _preferred = ["uniswap_v3", "sushiswap_v3", "pancakeswap_v3", "aerodrome"]

            for _fallback_dex in _preferred:
                try:
                    _fb_cfg = _gdc(chain, _fallback_dex)
                    if _fb_cfg.get("adapter_type", "") in {"uniswap_v3", "ve33", "algebra"}:
                        dex_cfg = _fb_cfg
                        break
                except (KeyError, ImportError):
                    continue
        if dex_cfg is None:
            return None, f"DEX_CONFIG_MISSING:{venue}"

    router = dex_cfg.get("router")
    adapter_type = dex_cfg.get("adapter_type", "")
    if not router:
        return None, f"ROUTER_MISSING:{venue}"

    # V3-compatible adapters that use exactInputSingle calldata
    # E1.18: ve33 moved to separate set — uses Velodrome swapExactTokensForTokens
    _V3_ADAPTERS = {"uniswap_v3", "algebra"}
    _VE33_ADAPTERS = {"ve33"}
    _SUPPORTED_ADAPTERS = _V3_ADAPTERS | _VE33_ADAPTERS
    if adapter_type not in _SUPPORTED_ADAPTERS:
        return None, f"ADAPTER_UNSUPPORTED:{adapter_type}"

    # E1.16: Prefer resolved token addresses from BackrunResult (bypass
    # symbol lookup which fails when actual_pair contains direction tags).
    token_in_addr = getattr(result, "backrun_token_in_address", None)
    token_out_addr = getattr(result, "backrun_token_out_address", None)

    if not token_in_addr or not token_out_addr:
        # Fallback: resolve from actual_pair symbols or embedded hex addresses.
        # actual_pair may contain:
        #   - real symbols: "WETH/USDC"
        #   - address prefixes: "0x696f9436/USDC" (addr_to_symbol miss)
        #   - direction tags: "token0_in/USDC" (unresolved direction)
        tokens = pair.split("/")
        if len(tokens) != 2:
            return None, f"PAIR_FORMAT_INVALID:{pair}"

        try:
            from config import get_token_address

            for idx, missing_addr in [(0, token_in_addr), (1, token_out_addr)]:
                if missing_addr:
                    continue  # Already resolved
                tok = tokens[idx]
                # E1.17: If token looks like a hex address (0x...), use it directly
                if tok.startswith("0x") and len(tok) >= 10:
                    # Try full address from core_tokens.yaml by scanning all entries
                    # for an address that starts with this prefix
                    _resolved = _resolve_address_prefix(chain, tok)
                    if _resolved:
                        if idx == 0:
                            token_in_addr = _resolved
                        else:
                            token_out_addr = _resolved
                        continue
                # Standard symbol lookup
                try:
                    addr = get_token_address(chain, tok)
                    if idx == 0:
                        token_in_addr = addr
                    else:
                        token_out_addr = addr
                except (KeyError, ValueError):
                    pass  # Will be caught by the check below
        except ImportError:
            return None, "CONFIG_IMPORT_FAILED"

    if not token_in_addr or not token_out_addr:
        missing = []
        tokens = pair.split("/")
        if not token_in_addr:
            missing.append(tokens[0] if len(tokens) > 0 else "?")
        if not token_out_addr:
            missing.append(tokens[1] if len(tokens) > 1 else "?")
        return None, f"TOKEN_ADDRESS_UNKNOWN:{','.join(missing)}"

    # Build calldata based on adapter type.
    # E1.18: V3 adapters → exactInputSingle, ve33 → Velodrome swapExactTokensForTokens.
    try:
        if adapter_type in _VE33_ADAPTERS:
            # Velodrome/Aerodrome V2: Route-based swap
            factory = dex_cfg.get("factory", _AERODROME_FACTORY_DEFAULT)
            # E1.24: Detect stable from pool fee field (0=volatile, 1=stable)
            _pool_fee = getattr(result, "best_buy_fee", 0) or 0
            _is_stable = (_pool_fee == 1)
            calldata = _encode_velodrome_swap(
                token_in=token_in_addr,
                token_out=token_out_addr,
                recipient="0x0000000000000000000000000000000000000001",
                amount_in=amount,
                stable=_is_stable,
                factory=factory,
            )
        else:
            # V3: exactInputSingle (uniswap_v3, algebra)
            # E1.25: Use actual pool fee from scoring (best_buy_fee) instead of
            # config's first fee tier.  This fixes sim reverts caused by calldata
            # targeting the wrong fee-tier pool (e.g., 500 instead of 3000).
            _actual_fee = getattr(result, "best_buy_fee", None)
            if _actual_fee and _actual_fee > 1:
                fee = _actual_fee
            else:
                fee_tiers = dex_cfg.get("fee_tiers", [3000])
                fee = fee_tiers[0] if fee_tiers else 3000
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

    tx_params = {
        "to": router,
        "calldata": calldata,
        "value": 0,
    }
    _annotate_tx_telemetry(
        result,
        tx_params,
        "sim",
        venue=venue,
        fee=getattr(result, "best_buy_fee", None),
        adapter_type=adapter_type,
    )
    return tx_params, None


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


def _build_sell_leg_tx_params(
    result: Any,
    sell_input_wei: int,
    chain: str = "base",
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """E2: Build sell-leg tx params for round-trip sim.

    Reverses token direction (token_out → token_in) using best_sell_venue
    and best_sell_fee. Returns (tx_params, None) or (None, reason).
    """
    if sell_input_wei <= 0:
        return None, "SELL_INPUT_ZERO"

    # soak16 P0.2: Backrun amount sanity clamp.
    # Forward leg input was result.amount_in_wei (USDC-side). The sell leg
    # input is the forward leg output (TKN-side). When pool liquidity is
    # extremely low the forward leg returns a token amount whose USDC value
    # is far smaller than the original input, producing the catastrophic
    # `roundtrip_profit_bps ≈ -9957` we saw in soak12/13 historical samples.
    # We can't compare USDC↔TKN directly without a price oracle, but we can
    # bound the absolute magnitude — if the sell input is more than
    # ARBY_BACKRUN_MAX_INPUT_RATIO × forward input it is almost certainly a
    # decimals mismatch or a pool-state corruption; skip.
    try:
        _max_ratio = float(os.environ.get("ARBY_BACKRUN_MAX_INPUT_RATIO", "1000.0"))
    except (TypeError, ValueError):
        _max_ratio = 1000.0
    _fwd_in = int(getattr(result, "amount_in_wei", 0) or 0)
    if _fwd_in > 0 and _max_ratio > 0:
        if sell_input_wei > _fwd_in * _max_ratio:
            return None, f"SELL_INPUT_DISPROPORTIONATE:ratio>{_max_ratio:g}x"

    # E1.35 P1.3: registry-driven accepted fee set
    _ACCEPTED = get_accepted_fees(chain)

    sell_venue = getattr(result, "best_sell_venue", None)
    if not sell_venue:
        return None, "SELL_VENUE_MISSING"

    sell_fee = getattr(result, "best_sell_fee", None)
    if sell_fee is None:
        sell_fee = getattr(result, "best_buy_fee", None)  # fallback
    if sell_fee is None or sell_fee not in _ACCEPTED:
        # E1.32: Classify by origin for monitoring clarity.
        # E1.42 (fee 2600 audit): when fee comes from scoring with a
        # registered venue but is not in that venue's declared fee_tiers,
        # surface BOTH venue and fee so reviewers can see whether the
        # mismatch is a discovery bug (registered venue + stray fee) vs a
        # genuinely unknown source (off-registry venue).
        _AERODROME_CL_KNOWN = {150, 445, 600, 1000, 1570, 2105, 2655, 3024, 5000, 9500, 20000}
        _venue_label = str(sell_venue) if sell_venue else "UNKNOWN_VENUE"
        if isinstance(sell_fee, int):
            if sell_fee in _AERODROME_CL_KNOWN:
                return None, f"SELL_FEE_UNSUPPORTED:AERODROME_CL:{sell_fee}"
            if 1 < sell_fee <= 100:
                return None, f"SELL_FEE_UNSUPPORTED:ALGEBRA_DYNAMIC:{sell_fee}"
            # Determine whether the venue is registered at all for *chain*.
            try:
                from config import load_dexes as _load_dexes
                _registered = (_load_dexes() or {}).get(chain, {})
                _venue_known = _venue_label in _registered
            except Exception:
                _venue_known = False
            if _venue_known:
                # Registered venue but fee not in its declared tier set.
                return None, f"SELL_FEE_UNSUPPORTED:VENUE_FEE_MISMATCH:{_venue_label}:{sell_fee}"
            return None, f"SELL_FEE_UNSUPPORTED:UNKNOWN_SOURCE:{_venue_label}:{sell_fee}"
        return None, f"SELL_FEE_UNSUPPORTED:{sell_fee}"

    # Reverse token direction: buy.tokenOut becomes sell.tokenIn
    buy_token_in = getattr(result, "backrun_token_in_address", None)
    buy_token_out = getattr(result, "backrun_token_out_address", None)
    if not buy_token_in or not buy_token_out:
        return None, "TOKEN_ADDRESS_UNKNOWN"

    # Resolve DEX config for sell venue
    try:
        from config import get_dex_config
        dex_cfg = get_dex_config(chain, sell_venue)
    except (KeyError, ImportError):
        dex_cfg = None
        if sell_venue.startswith("0x") or sell_venue == "ptt_direct":
            from config import get_dex_config as _gdc
            if sell_fee is not None and sell_fee <= 1:
                _preferred = ["aerodrome", "uniswap_v3", "sushiswap_v3", "pancakeswap_v3"]
            elif sell_fee == 2500:
                _preferred = ["pancakeswap_v3", "uniswap_v3", "sushiswap_v3", "aerodrome"]
            else:
                _preferred = ["uniswap_v3", "sushiswap_v3", "pancakeswap_v3", "aerodrome"]
            for _fb in _preferred:
                try:
                    _fb_cfg = _gdc(chain, _fb)
                    if _fb_cfg.get("adapter_type", "") in {"uniswap_v3", "ve33", "algebra"}:
                        dex_cfg = _fb_cfg
                        break
                except (KeyError, ImportError):
                    continue
        if dex_cfg is None:
            return None, f"SELL_DEX_CONFIG_MISSING:{sell_venue}"

    router = dex_cfg.get("router")
    adapter_type = dex_cfg.get("adapter_type", "")
    if not router:
        return None, f"SELL_ROUTER_MISSING:{sell_venue}"

    _V3_ADAPTERS = {"uniswap_v3", "algebra"}
    _VE33_ADAPTERS = {"ve33"}
    if adapter_type not in (_V3_ADAPTERS | _VE33_ADAPTERS):
        return None, f"SELL_ADAPTER_UNSUPPORTED:{adapter_type}"

    # Sell leg: tokenIn = buy_token_out, tokenOut = buy_token_in
    try:
        if adapter_type in _VE33_ADAPTERS:
            factory = dex_cfg.get("factory", _AERODROME_FACTORY_DEFAULT)
            calldata = _encode_velodrome_swap(
                token_in=buy_token_out,
                token_out=buy_token_in,
                recipient="0x0000000000000000000000000000000000000001",
                amount_in=sell_input_wei,
                stable=(sell_fee == 1),
                factory=factory,
            )
        else:
            calldata = _encode_exact_input_single(
                token_in=buy_token_out,
                token_out=buy_token_in,
                fee=sell_fee,
                recipient="0x0000000000000000000000000000000000000001",
                amount_in=sell_input_wei,
                router_version=_router_version(chain),
            )
    except Exception as e:
        return None, f"SELL_CALLDATA_ENCODE_FAILED:{str(e)[:100]}"

    tx_params = {"to": router, "calldata": calldata, "value": 0}
    _annotate_tx_telemetry(
        result,
        tx_params,
        "sell",
        venue=sell_venue,
        fee=sell_fee,
        adapter_type=adapter_type,
    )
    return tx_params, None


def _attempt_simulation(
    result: Any, guard: ProfitGuardResult, chain: str = "base"
) -> SimulationResult:
    """Attempt simulation for a guard-passed candidate.

    E1.12.4B: Builds real V3 calldata from the scored result and sends
    to the configured simulation backend.  Falls back to an explicit
    error when calldata cannot be built (VENUE_MISSING, PAIR_UNRESOLVED,
    ADAPTER_UNSUPPORTED, etc.).

    E1.35 P0.2 + P1.5: passes ``event.block_number`` to the simulation
    backend so pricing is checked in-block (instead of against the
    already-committed ``latest`` head).  After the sim, computes
    ``block_lag_at_sim`` and marks a freshness violation if the block
    moved past ``get_chain_stale_blocks(chain)`` during the attempt.
    """
    if not is_simulation_configured():
        return SimulationResult(success=False, error="SIM_DISABLED")

    tx_params, build_err = _build_sim_tx_params(result, chain)
    if tx_params is None:
        return SimulationResult(success=False, error=f"CALLDATA_BUILD_FAILED:{build_err}")

    # E1.26: Log sim attempt details for debugging reverts
    _venue = getattr(result, "best_buy_venue", "?")
    _fee = getattr(result, "best_buy_fee", "?")
    _pair = getattr(result, "actual_pair", "?")
    logger.info(
        "sim attempt: pair=%s venue=%s fee=%s router=%s",
        _pair, _venue, _fee, tx_params["to"][:18],
    )

    # E1.35 P0.2: Pass event_block so the fork executes against the state
    # we actually saw, not against a block that already closed.
    _event_block = getattr(result, "event_block", None)
    try:
        _event_block_int = int(_event_block) if _event_block is not None else None
    except (TypeError, ValueError):
        _event_block_int = None

    sim_result = simulate_swap(
        chain=chain,
        from_address=_get_sim_from_address(),
        to_address=tx_params["to"],
        calldata=tx_params["calldata"],
        value_wei=tx_params["value"],
        block_number=_event_block_int,
    )

    # E1.35 P1.5: post-sim freshness. Record event-block context so
    # downstream consumers can decide whether to submit. We purposefully
    # do NOT query a fresh `latest` here (extra RPC latency) — we rely
    # on `quote_block` from scoring which was captured immediately
    # before sim. If unavailable, the violation stays False.
    sim_result.event_block_number = _event_block_int
    _quote_block = getattr(result, "quote_block", None)
    try:
        _quote_block_int = int(_quote_block) if _quote_block is not None else None
    except (TypeError, ValueError):
        _quote_block_int = None
    sim_result.sim_block_number = _quote_block_int
    if _event_block_int is not None and _quote_block_int is not None:
        _lag = _quote_block_int - _event_block_int
        sim_result.block_lag_at_sim = _lag
        try:
            from m7.shared.constants import get_chain_stale_blocks as _gcsb
            _threshold = _gcsb(chain)
        except Exception:
            _threshold = 2
        if _lag > _threshold:
            sim_result.freshness_violation = True
            # Do not overwrite a successful sim, but mark it as stale
            # so execution_gate can reject it at submit_ready stage.

    if not sim_result.passed:
        logger.info(
            "sim FAILED: pair=%s venue=%s fee=%s error=%s",
            _pair, _venue, _fee, (sim_result.error or "?")[:100],
        )
        return sim_result

    # E2: Round-trip simulation — use sim buy-leg output as sell-leg input.
    # Enable via ARBY_ROUNDTRIP_SIM=1 (default ON for rpc_fork backend).
    _rt_enabled = os.environ.get("ARBY_ROUNDTRIP_SIM", "1").strip() == "1"
    if _rt_enabled and sim_result.output_amount_wei > 0:
        sim_result.roundtrip_attempted = True
        _sell_tx, _sell_err = _build_sell_leg_tx_params(
            result, sim_result.output_amount_wei, chain=chain
        )
        if _sell_tx is None:
            sim_result.roundtrip_sell_revert_reason = f"SELL_BUILD:{_sell_err}"
            logger.info(
                "roundtrip skip: pair=%s reason=%s", _pair, _sell_err,
            )
        else:
            try:
                _sell_sim = simulate_swap(
                    chain=chain,
                    from_address=_get_sim_from_address(),
                    to_address=_sell_tx["to"],
                    calldata=_sell_tx["calldata"],
                    value_wei=_sell_tx["value"],
                    block_number=_event_block_int,
                )
                sim_result.roundtrip_sell_gas_used = _sell_sim.gas_used
                if _sell_sim.passed and _sell_sim.output_amount_wei > 0:
                    sim_result.roundtrip_success = True
                    sim_result.roundtrip_final_wei = _sell_sim.output_amount_wei
                    # Same-token comparison (valid bps)
                    _init = sim_result.input_amount_wei
                    sim_result.roundtrip_profit_wei = _sell_sim.output_amount_wei - _init
                    if _init > 0:
                        sim_result.roundtrip_profit_bps = round(
                            (sim_result.roundtrip_profit_wei / _init) * 10000, 4
                        )
                    logger.info(
                        "roundtrip OK: pair=%s profit_wei=%d profit_bps=%.2f (init=%d final=%d)",
                        _pair, sim_result.roundtrip_profit_wei,
                        sim_result.roundtrip_profit_bps, _init, _sell_sim.output_amount_wei,
                    )
                else:
                    sim_result.roundtrip_sell_revert_reason = (
                        _sell_sim.revert_reason or _sell_sim.error or "unknown"
                    )
                    logger.info(
                        "roundtrip sell FAILED: pair=%s reason=%s",
                        _pair, (sim_result.roundtrip_sell_revert_reason or "?")[:80],
                    )
            except Exception as _rt_exc:
                sim_result.roundtrip_sell_revert_reason = f"RT_EXC:{type(_rt_exc).__name__}"
                logger.debug("Roundtrip sim exception: %s", _rt_exc)

    return sim_result


def run_execution_gate(
    scored_results: list,
    chain: str = "base",
    profile: Optional[str] = None,
) -> ExecutionGateResult:
    """Run the full execution gate pipeline on scored results.

    Stages:
      1. profit_guard — filters to positive-net candidates
      2. simulation — backend selected by ARBY_SIM_BACKEND (or
         ARBY_SIM_BACKEND_DISC / ARBY_SIM_BACKEND_PROD if profile given)
      3. submit_ready — requires sim_passed + calldata + signing (future)

    Pass ``profile='discovery'`` from the discovery lane so that
    ARBY_SIM_BACKEND_DISC (default rpc_fork, no credit limits) is used
    instead of Tenderly. Pass ``profile='production'`` to force PROD backend.

    Returns ExecutionGateResult with honest counts and blockers.
    """
    gate = ExecutionGateResult()

    # E1.12.4 / E1.53: Always record which simulation backend is active.
    # Profile-aware: discovery lane reads ARBY_SIM_BACKEND_DISC so it
    # never accidentally burns Tenderly credits.
    _sim_configured = is_simulation_configured(profile=profile)
    gate.simulation_backend = get_simulation_backend(profile=profile) if _sim_configured else None

    # Stage 1: Profit guard
    gate.guard_passed = _run_profit_guard_on_results(scored_results, chain=chain)

    # E4: Diagnostic bypass — when ARBY_SIM_BYPASS_GUARD=1, run round-trip
    # sim on ALL scored_results even if profit_guard rejected them. This lets
    # us measure the TRUE profit distribution (post-price-impact) independently
    # of the upstream scoring heuristic. Default off preserves backward-compat.
    if not gate.guard_passed and os.getenv("ARBY_SIM_BYPASS_GUARD", "0") == "1":
        gate.guard_passed = [(r, None) for r in scored_results]
        gate.guard_bypassed = True

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

    # Step 7 (Pre-sim admission filter):
    # To reduce load on rate-limited RPC providers, only admit candidates that
    # actually deserve a full simulation. Rejections here consume ZERO RPC calls
    # and are counted in `gate.sim_errors` as PRE_SIM_SKIP:<reason>, not in
    # `sim_attempted`. Controlled by ARBY_SIM_ADMISSION_STRICT (default "1").
    #
    # Criteria (all configurable via env):
    #   - ARBY_SIM_MIN_NET_BPS   (default "1.0")  — min scored net_bps
    #   - ARBY_SIM_MIN_AMOUNT_WEI (default "0")   — require amount_in_wei or sweep
    #   - require actual_pair with "/"
    #   - require best_buy_fee (so fee-tier lookup downstream has a hint)
    if os.getenv("ARBY_SIM_ADMISSION_STRICT", "1") == "1":
        try:
            _min_net_bps = float(os.getenv("ARBY_SIM_MIN_NET_BPS", "1.0"))
        except (TypeError, ValueError):
            _min_net_bps = 1.0
        try:
            _min_amount_wei = int(os.getenv("ARBY_SIM_MIN_AMOUNT_WEI", "0"))
        except (TypeError, ValueError):
            _min_amount_wei = 0

        _admitted: List[Tuple[Any, ProfitGuardResult]] = []
        for r, g in gate.guard_passed:
            _skip_reason: Optional[str] = None

            _pair = getattr(r, "actual_pair", None)
            if not _pair or "/" not in str(_pair):
                _skip_reason = "PRE_SIM_SKIP:PAIR_UNRESOLVED"

            if _skip_reason is None:
                _net_bps = getattr(r, "best_backrun_net_bps", 0.0) or 0.0
                if float(_net_bps) < _min_net_bps:
                    _skip_reason = f"PRE_SIM_SKIP:BELOW_MIN_NET_BPS:{_min_net_bps}"

            if _skip_reason is None:
                _amount = getattr(r, "amount_in_wei", 0) or 0
                _sweep = getattr(r, "best_sweep_size_wei", 0) or 0
                if _amount <= 0 and _sweep <= 0:
                    # AMOUNT_ZERO autofill downstream relies on chain min-size;
                    # treat as borderline — only skip if no fee hint either.
                    if not getattr(r, "best_buy_fee", None):
                        _skip_reason = "PRE_SIM_SKIP:NO_AMOUNT_NO_FEE_HINT"
                elif _amount > 0 and _amount < _min_amount_wei:
                    _skip_reason = f"PRE_SIM_SKIP:BELOW_MIN_AMOUNT_WEI:{_min_amount_wei}"

            if _skip_reason is None and not getattr(r, "best_buy_fee", None):
                # No fee hint AND no sweep size: downstream venue fallback will
                # either guess wrong or fail. Cheaper to skip than to sim.
                if not getattr(r, "best_sweep_size_wei", 0):
                    _skip_reason = "PRE_SIM_SKIP:NO_FEE_HINT"

            # Reviewer post-soak19 step 3: refuse to spend RPC budget on a
            # candidate when adaptive sizing produced no usable size metadata
            # at all (decimals + sweep + usd estimate all unknown). Such
            # candidates are the dominant source of scorer-vs-sim divergence
            # because the scorer ran on a synthetic 1e18 amount that the sim
            # cannot reproduce. Controlled by ARBY_SIM_REQUIRE_SIZE_METADATA
            # (default "1"); set to "0" to keep legacy permissive behaviour.
            if _skip_reason is None and os.getenv(
                "ARBY_SIM_REQUIRE_SIZE_METADATA", "1"
            ) == "1":
                _decimals = getattr(r, "token_in_decimals", None)
                _sweep_meta = getattr(r, "best_sweep_size_wei", None)
                _usd_est = getattr(r, "size_usd_estimate", None)
                _has_decimals = _decimals is not None
                _has_sweep = _sweep_meta is not None and _sweep_meta > 0
                _has_usd = _usd_est is not None
                if not (_has_decimals or _has_sweep or _has_usd):
                    _skip_reason = "PRE_SIM_SKIP:MISSING_SIZE_METADATA"
                    # Reviewer fix #6: capture top samples (bounded ring of 50)
                    # so reviewer can see WHICH pairs/pools still arrive without
                    # decimals/sweep/usd estimate. Helps target upstream sizing.
                    if len(gate.pre_sim_skip_samples) < 50:
                        gate.pre_sim_skip_samples.append({
                            "reason": "MISSING_SIZE_METADATA",
                            "event_id": getattr(r, "event_id", None),
                            "event_source": getattr(r, "event_source", None),
                            "pair": getattr(r, "pair", None) or getattr(r, "pair_label", None) or getattr(r, "actual_pair", None),
                            "pool": getattr(r, "pool_address", None) or getattr(r, "best_pool", None),
                            "token_in_symbol": getattr(r, "token_in", None),
                            "token_out_symbol": getattr(r, "token_out", None),
                            "token_in_address": getattr(r, "backrun_token_in_address", None) or getattr(r, "token_in_address", None),
                            "token_out_address": getattr(r, "backrun_token_out_address", None) or getattr(r, "token_out_address", None),
                            "direction": getattr(r, "backrun_direction", None),
                            "missing_fields": [
                                _f for _f, _present in (
                                    ("token_in_decimals", _has_decimals),
                                    ("best_sweep_size_wei", _has_sweep),
                                    ("size_usd_estimate", _has_usd),
                                ) if not _present
                            ],
                            "fee_hint": getattr(r, "best_buy_fee", None) or getattr(r, "fee_hint", None) or getattr(r, "best_fee_tier", None),
                            "venue": getattr(r, "venue", None) or getattr(r, "best_venue", None),
                            "adapter_type": getattr(r, "adapter_type", None),
                            "amount_in_wei": getattr(r, "amount_in_wei", None),
                            "best_backrun_net_bps": getattr(r, "best_backrun_net_bps", None),
                        })

            # Reviewer post-soak19 fix #9: optional hard cap on trade size in
            # USD. Default OFF (cap=0). When ARBY_MAX_TRADE_USD>0, candidates
            # whose ``size_usd_estimate`` exceeds the cap skip with
            # ``PRE_SIM_SKIP:SIZE_OVER_CAP``; this acts as a price-impact /
            # TVL-aware proxy until per-pool depth is wired in. Strictly
            # additive to existing rejects and never blocks when cap<=0.
            if _skip_reason is None:
                try:
                    _max_trade_usd = float(os.getenv("ARBY_MAX_TRADE_USD", "0"))
                except (TypeError, ValueError):
                    _max_trade_usd = 0.0
                if _max_trade_usd > 0:
                    _size_usd_chk = getattr(r, "size_usd_estimate", None)
                    if _size_usd_chk is not None and _size_usd_chk > _max_trade_usd:
                        # Reviewer post-2h-soak step #4: pre-sim size bisection.
                        # When ARBY_PRE_SIM_BISECT=1, instead of hard-skipping
                        # an oversized candidate, try to find a smaller
                        # executable size by linearly scaling amount_in_wei,
                        # best_sweep_size_wei and size_usd_estimate down to
                        # the cap. Strictly observability-preserving — we still
                        # mark the path with bisection metadata. Default OFF.
                        _bisect_on = os.getenv("ARBY_PRE_SIM_BISECT", "0") == "1"
                        if _bisect_on and _size_usd_chk > 0:
                            _scale = _max_trade_usd / float(_size_usd_chk)
                            # Apply a small safety margin so the new size sits
                            # strictly below the cap.
                            _scale = max(0.0, min(1.0, _scale * 0.95))
                            if _scale > 0:
                                _orig_amt = getattr(r, "amount_in_wei", None) or 0
                                _orig_sweep = getattr(r, "best_sweep_size_wei", None) or 0
                                _new_amt = int(_orig_amt * _scale) if _orig_amt else 0
                                _new_sweep = int(_orig_sweep * _scale) if _orig_sweep else 0
                                _new_usd = float(_size_usd_chk) * _scale
                                # Only commit bisection if the resulting amount
                                # is still above the gate's existing minimum;
                                # otherwise fall through to SIZE_OVER_CAP skip.
                                if _new_amt > 0 and _new_usd > 0:
                                    if hasattr(r, "amount_in_wei"):
                                        r.amount_in_wei = _new_amt
                                    if hasattr(r, "best_sweep_size_wei") and _orig_sweep:
                                        r.best_sweep_size_wei = _new_sweep
                                    if hasattr(r, "size_usd_estimate"):
                                        r.size_usd_estimate = _new_usd
                                    # Mark for downstream observability (no
                                    # behaviour change beyond the size shrink).
                                    if hasattr(r, "size_bisected_from_usd"):
                                        r.size_bisected_from_usd = float(_size_usd_chk)
                                    if len(gate.pre_sim_skip_samples) < 50:
                                        gate.pre_sim_skip_samples.append({
                                            "reason": "SIZE_BISECTED_TO_CAP",
                                            "event_id": getattr(r, "event_id", None),
                                            "pair": getattr(r, "pair", None) or getattr(r, "pair_label", None) or getattr(r, "actual_pair", None),
                                            "pool": getattr(r, "pool_address", None) or getattr(r, "best_pool", None),
                                            "original_size_usd": float(_size_usd_chk),
                                            "new_size_usd": _new_usd,
                                            "scale": _scale,
                                            "cap_usd": _max_trade_usd,
                                        })
                                    # Skip the hard SIZE_OVER_CAP path — the
                                    # candidate now fits under the cap.
                                    _size_usd_chk = _new_usd
                        if _size_usd_chk is not None and _size_usd_chk > _max_trade_usd:
                            _skip_reason = "PRE_SIM_SKIP:SIZE_OVER_CAP"
                            if len(gate.pre_sim_skip_samples) < 50:
                                gate.pre_sim_skip_samples.append({
                                    "reason": "SIZE_OVER_CAP",
                                    "pair": getattr(r, "pair", None) or getattr(r, "pair_label", None),
                                    "pool": getattr(r, "pool_address", None) or getattr(r, "best_pool", None),
                                    "size_usd_estimate": _size_usd_chk,
                                    "cap_usd": _max_trade_usd,
                                })

            if _skip_reason is not None:
                gate.sim_errors.append(_skip_reason)
                if hasattr(r, "sim_attempted"):
                    r.sim_attempted = False
                    r.simulation_error = _skip_reason
                if hasattr(r, "submit_ready"):
                    r.submit_ready = False
                    r.submit_blocker = _skip_reason
                continue
            _admitted.append((r, g))
        gate.guard_passed = _admitted
        if not gate.guard_passed:
            return gate

    # E1.27/D3: Pre-sim fee tier check. Skip non-standard fees (e.g. Algebra
    # dynamic 150/600/3024) before counting them as sim_attempted. These consume
    # no RPC calls and are tracked separately via pre_sim_skip_histogram.
    # E1.35 P1.3: fee set now comes from the DEX registry (config/dexes.yaml)
    # so new venues are accepted without patching this module.
    _ACCEPTED_FEES = get_accepted_fees(chain)

    for r, g in gate.guard_passed:
        _fee_hint = getattr(r, "best_buy_fee", None)
        if _fee_hint is not None and _fee_hint not in _ACCEPTED_FEES:
            # Record in sim_errors (for histogram) but do NOT count as sim_attempted.
            # E1.35 P1.1 step 3: classify Aerodrome Slipstream fees under
            # SLIPSTREAM_PENDING_LOOKUP when adapter+config are verified.
            _AERODROME_CL_KNOWN = {150, 445, 600, 1000, 1570, 2105, 2655, 3024, 5000, 9500, 20000}
            _skip_key = f"PRE_SIM_SKIP:UNSUPPORTED_FEE_TIER:{_fee_hint}"
            if _fee_hint in _AERODROME_CL_KNOWN:
                try:
                    from config import get_dex_config as _gdc_pre
                    _slip_cfg = _gdc_pre(chain, "aerodrome_slipstream")
                except (KeyError, ImportError):
                    _slip_cfg = None
                if (
                    _slip_cfg
                    and _slip_cfg.get("verified") is True
                    and _slip_cfg.get("router")
                    and _slip_cfg.get("quoter_v2")
                ):
                    _skip_key = f"PRE_SIM_SKIP:SLIPSTREAM_PENDING_LOOKUP:{_fee_hint}"
            gate.sim_errors.append(_skip_key)
            if hasattr(r, "sim_attempted"):
                r.sim_attempted = False
                r.simulation_error = _skip_key
            if hasattr(r, "submit_ready"):
                r.submit_ready = False
                r.submit_blocker = _skip_key
            continue

        gate.sim_attempted += 1
        if hasattr(r, "sim_attempted"):
            r.sim_attempted = True

        try:
            sim_result = _attempt_simulation(r, g, chain=chain)
        except Exception as exc:
            # E1.15: Catch unexpected exceptions so sim_errors histogram
            # is always populated (fixes "10 unknown" telemetry gap).
            _exc_msg = f"SIM_EXCEPTION:{type(exc).__name__}:{str(exc)[:200]}"
            logger.warning("Simulation exception for %s: %s",
                           getattr(r, "event_id", "?"), _exc_msg)
            sim_result = SimulationResult(success=False, error=_exc_msg)

        if hasattr(r, "sim_passed"):
            r.sim_passed = sim_result.passed
            r.simulation_id = sim_result.simulation_id
            r.simulation_error = sim_result.error

        if sim_result.passed:
            gate.sim_passed += 1
            _net_bps_scored = getattr(r, "best_backrun_net_bps", None)
            # E2: Record gate-level round-trip counters
            if sim_result.roundtrip_attempted:
                gate.roundtrip_attempted += 1
                if sim_result.roundtrip_success:
                    gate.roundtrip_success += 1
                    gate.roundtrip_profit_bps_values.append(sim_result.roundtrip_profit_bps)
                    if sim_result.roundtrip_profit_bps > 0:
                        gate.roundtrip_profitable_count += 1
                else:
                    _rt_err = sim_result.roundtrip_sell_revert_reason or "unknown"
                    gate.roundtrip_errors.append(_rt_err)
            if hasattr(r, "sim_output_amount_wei"):
                r.sim_output_amount_wei = sim_result.output_amount_wei
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

            # E1.35/soak13 economics guard: a passed calldata simulation is
            # not submit-ready if same-token roundtrip proves negative PnL.
            _submit_blockers = _build_submit_blockers(
                sim_result, _net_bps_scored, _calldata_ready, _signing_ready
            )

            # Reviewer post-soak21 P0: structured reproducer for
            # SCORER_SIM_DIVERGENCE. Captures enough context to replay
            # offline: pool, pair, fee, direction, amount, decimals,
            # local-quote vs rpc_fork-quote, both raw wei values.
            try:
                _div_blocker = next(
                    (b for b in _submit_blockers if b.startswith("SCORER_SIM_DIVERGENCE:")),
                    None,
                )
                if _div_blocker is not None and len(gate.scorer_sim_divergence_samples) < 50:
                    # Reviewer post-2h-soak step #1 (minimal observability):
                    # detect quote-model input mismatch. The fast-path scorer
                    # observes amount_in_wei; the rpc_fork sim observes
                    # sim_result.input_amount_wei. If they diverge by more
                    # than 1%, the divergence root cause is INPUT mismatch
                    # (different sizes), not pool quote-model error. Surfaced
                    # as a separate boolean so reviewer knows where to look.
                    _amount_scored = getattr(r, "amount_in_wei", None)
                    _amount_sim = getattr(sim_result, "input_amount_wei", None)
                    _input_mismatch = False
                    _input_mismatch_ratio = None
                    try:
                        if _amount_scored and _amount_sim:
                            _a = float(_amount_scored)
                            _b = float(_amount_sim)
                            if _a > 0 and _b > 0:
                                _input_mismatch_ratio = abs(_a - _b) / max(_a, _b)
                                _input_mismatch = _input_mismatch_ratio > 0.01
                    except (TypeError, ValueError):
                        pass
                    gate.scorer_sim_divergence_samples.append(
                        {
                            "event_id": getattr(r, "event_id", None),
                            "event_tx_hash": (
                                getattr(r, "tx_hash", None)
                                or getattr(r, "event_tx_hash", None)
                            ),
                            "pair": getattr(r, "actual_pair", None),
                            "pool_address": getattr(r, "pool_address", None)
                            or getattr(r, "sim_pool", None)
                            or getattr(r, "event_pool_address", None),
                            "venue": getattr(r, "venue", None)
                            or getattr(r, "sim_venue", None)
                            or getattr(r, "best_buy_venue", None),
                            "fee_tier": getattr(r, "fee_tier", None)
                            or getattr(r, "sim_fee", None)
                            or getattr(r, "best_buy_fee", None),
                            "adapter_type": getattr(r, "adapter_type", None)
                            or getattr(r, "sim_adapter_type", None)
                            or getattr(r, "adapter_type_used", None),
                            "direction": getattr(r, "backrun_direction", None),
                            "token_in": getattr(r, "token_in", None)
                            or getattr(r, "backrun_token_in_address", None),
                            "token_out": getattr(r, "token_out", None)
                            or getattr(r, "backrun_token_out_address", None),
                            "token_in_decimals": getattr(r, "token_in_decimals", None),
                            "token_out_decimals": getattr(r, "token_out_decimals", None),
                            "amount_in_wei": getattr(r, "amount_in_wei", None),
                            "scored_net_bps": _net_bps_scored,
                            "sim_output_wei": getattr(sim_result, "output_amount_wei", None),
                            "sim_input_wei": getattr(sim_result, "input_amount_wei", None),
                            "roundtrip_profit_bps": getattr(
                                sim_result, "roundtrip_profit_bps", None
                            ),
                            "roundtrip_attempted": getattr(
                                sim_result, "roundtrip_attempted", None
                            ),
                            "roundtrip_success": getattr(
                                sim_result, "roundtrip_success", None
                            ),
                            "size_usd_estimate": getattr(r, "size_usd_estimate", None),
                            "blocker_tag": _div_blocker,
                            # Step #1 observability bridge:
                            "input_mismatch_detected": _input_mismatch,
                            "input_mismatch_ratio": _input_mismatch_ratio,
                        }
                    )
            except Exception:
                # Reproducer is observability-only; never break gate flow.
                pass

            # E1.27/D1 + soak13: Record raw sim output and enough route/tx
            # telemetry to diagnose scorer-vs-sim divergence post-run.
            gate.sim_output_samples.append(
                _build_sim_output_sample(
                    r, sim_result, _net_bps_scored, _submit_blockers
                )
            )

            if _calldata_ready and _signing_ready and not _submit_blockers:
                gate.submit_ready += 1
                if hasattr(r, "submit_ready"):
                    r.submit_ready = True
            else:
                if hasattr(r, "submit_ready"):
                    r.submit_ready = False
                    r.submit_blocker = ",".join(_submit_blockers)
                gate.submit_blockers.extend(_submit_blockers)
                gate.submit_blockers_detail.extend(_submit_blockers)
        else:
            # E1.27/D2: Prefer decoded revert_reason over raw error for histogram
            _sim_err = sim_result.revert_reason or sim_result.error or "unknown"
            gate.sim_errors.append(_sim_err)
            # M7.E1.34c: bounded terminal-stage sample for failed sims so the
            # reviewer can correlate histogram buckets with specific pair/venue
            # /amount combos (fixes "only aggregate histogram, no calldata"
            # gap flagged in 30m soak 2026-04-21).
            if len(gate.sim_failed_samples) < 50:
                _pair_fs = getattr(r, "actual_pair", None)
                # M7.E1.34d: use canonical BackrunResult attribute names so
                # venue/router/token_in/token_out are no longer None in the
                # rollup ring. Reviewer 30m STF soak 2026-04-21 flagged them
                # as None → root-cause diagnosis impossible.
                _venue_fs = (
                    getattr(r, "best_sell_venue", None)
                    or getattr(r, "best_buy_venue", None)
                    or getattr(r, "actual_venue", None)
                )
                _token_in = (
                    getattr(r, "backrun_token_in_address", None)
                    or getattr(r, "token_in", None)
                )
                _token_out = (
                    getattr(r, "backrun_token_out_address", None)
                    or getattr(r, "token_out", None)
                )
                _router = (
                    getattr(r, "router_address", None)
                    or getattr(r, "sim_router_address", None)
                )
                _buy_calldata = getattr(r, "sim_calldata_hex", None)
                _sell_calldata = getattr(r, "sell_calldata_hex", None)
                gate.sim_failed_samples.append({
                    "event_id": getattr(r, "event_id", None),
                    "event_tx_hash": (
                        getattr(r, "tx_hash", None)
                        or getattr(r, "event_tx_hash", None)
                    ),
                    "pair": _pair_fs,
                    "venue": _venue_fs,
                    "token_in": _token_in,
                    "token_out": _token_out,
                    "router": _router,
                    "buy_fee": getattr(r, "best_buy_fee", None),
                    "sell_fee": getattr(r, "best_sell_fee", None),
                    "amount_in_wei": getattr(r, "amount_in_wei", 0) or 0,
                    "backrun_direction": getattr(r, "backrun_direction", None),
                    "event_block": getattr(r, "event_block", None),
                    "quote_block": getattr(r, "quote_block", None),
                    "block_lag": getattr(r, "block_lag", None),
                    "sim_backend": sim_result.backend,
                    "sim_block_number": sim_result.sim_block_number,
                    "event_block_number": sim_result.event_block_number,
                    "block_lag_at_sim": sim_result.block_lag_at_sim,
                    "freshness_violation": sim_result.freshness_violation,
                    "buy_calldata_len": getattr(r, "sim_calldata_len", None),
                    "buy_calldata_prefix": _calldata_prefix(_buy_calldata),
                    "sell_calldata_len": getattr(r, "sell_calldata_len", None),
                    "sell_calldata_prefix": _calldata_prefix(_sell_calldata),
                    "sim_error": (sim_result.error or "")[:200],
                    "revert_reason": (sim_result.revert_reason or "")[:200],
                    "bucket": (_sim_err or "unknown")[:120],
                })
            if hasattr(r, "submit_ready"):
                r.submit_ready = False
                r.submit_blocker = f"SIM_FAILED:{_sim_err}"

    return gate
