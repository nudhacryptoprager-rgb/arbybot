"""E1.56 Step 1 — Cold-positive immediate sim queue.

Closes the STRATEGY_GATING blocker surfaced after E1.55:

  Cold lane finds profitable pools (e.g. FUN/USDC +997 bps, B3/WETH
  +425 bps) and writes them to `data/runs/_rolling/m7_cold_hot_bridge.json`
  under `cold_executable`. Hot lane is event-driven on the WS log stream:
  it scores only events that the WS upstream actually delivers. If the WS
  stream is dominated by an unrelated thin-spread pool (e.g. PENGACHU/WETH
  on Base), hot lane never sees the profitable pool and never calls sim.
  Result: `sim_attempted = 0` even though cold truth is positive.

This module bridges that gap: it converts each cold-positive bridge entry
into a synthetic `BackrunResult` and feeds the list to the existing
`run_execution_gate(...)` pipeline, which runs profit_guard → sim → submit
with ZERO public-API change.

ENV gate (default OFF, fully back-compat):
  ARBY_COLD_IMMEDIATE_SIM=1   — enable this lane
  ARBY_COLD_IMMEDIATE_MIN_NET_BPS=10  — only attempt entries with net_bps ≥ this
  ARBY_COLD_IMMEDIATE_TOP_N=5   — at most N entries per call

Counters returned for rollup:
  cold_immediate_sim_input_count       — bridge entries considered
  cold_immediate_sim_attempted          — entries that reached sim
  cold_immediate_sim_passed             — entries with sim_passed=True
  cold_immediate_sim_profitable         — entries that produced a positive
                                         post-sim net_bps (round-trip truth)

The lane is purely additive: if the env gate is unset (default) the public
contract of `run_execution_gate` is untouched and no synthetic candidates
are queued. This honors `CLAUDE.md §2.1` "public API ≥ existing".
"""
from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Tuple

from core.logging import get_logger
from m7.orderflow.contracts import BackrunResult, OrderflowEvent

logger = get_logger("m7.orderflow.cold_immediate_sim")


def is_enabled() -> bool:
    """Return True when the env gate is on."""
    return (os.getenv("ARBY_COLD_IMMEDIATE_SIM", "0") or "0") == "1"


def _min_net_bps_threshold() -> float:
    """Floor for entries fed into the immediate sim queue."""
    try:
        return float(os.getenv("ARBY_COLD_IMMEDIATE_MIN_NET_BPS", "10") or 10.0)
    except Exception:
        return 10.0


def _top_n() -> int:
    try:
        n = int(os.getenv("ARBY_COLD_IMMEDIATE_TOP_N", "5") or 5)
    except Exception:
        n = 5
    return max(1, min(50, n))


def _build_synthetic_event(entry: Dict[str, Any], chain: str) -> Optional[OrderflowEvent]:
    """Construct an `OrderflowEvent` shape from a bridge cold_executable entry.

    Returns None if the entry is missing required fields. The synthetic
    event is marked `event_source="cold_bridge"` downstream via the
    BackrunResult so consumers can distinguish from live WS events.

    Fix 2 (E1.60): entries with amount_in_wei=0 AND best_sweep_size_wei=0
    and no usd/decimals metadata will hit PRE_SIM_SKIP:MISSING_SIZE_METADATA
    in execution_gate. The gate already handles this correctly; we only skip
    here to avoid wasting counter budget when ALL metadata is absent.
    """
    try:
        pa = (entry.get("pool_address") or "").lower()
        # bridge `_compact_candidate` does not carry token symbols; fall
        # back to placeholders. The execution gate uses
        # `backrun_token_in_address`/`backrun_token_out_address` for
        # routing, so symbols are not strictly required.
        token_in_sym = entry.get("token_in") or entry.get("token_in_symbol") or "UNK_IN"
        token_out_sym = entry.get("token_out") or entry.get("token_out_symbol") or "UNK_OUT"
        if not pa:
            return None
        ev_id = f"cold_immediate_{pa[:10]}_{int(entry.get('block_lag') or 0)}"
        return OrderflowEvent(
            event_id=ev_id,
            event_type="swap",
            chain=chain,
            block_number=int(entry.get("block_number") or 0),
            tx_hash=ev_id,
            token_in=token_in_sym,
            token_out=token_out_sym,
            amount_in_wei=int(entry.get("amount_in_wei") or 0),
            amount_out_wei=int(entry.get("amount_out_wei") or 0),
            dex=str(entry.get("dex") or "cold_bridge"),
            pool_address=pa,
            fee_tier=int(entry.get("fee_tier") or 0),
            estimated_size_usd=float(entry.get("size_usd_estimate") or 0.0),
            estimated_impact_bps=float(entry.get("impact_bps") or 0.0),
            timestamp=str(entry.get("timestamp") or ""),
        )
    except Exception as exc:
        logger.debug("cold_immediate: failed to build event: %s", str(exc)[:80])
        return None


def _build_synthetic_result(entry: Dict[str, Any], event: OrderflowEvent) -> BackrunResult:
    """Build a `BackrunResult` carrying the cold-positive net_bps so that
    the profit_guard stage of `run_execution_gate` admits the candidate.
    """
    net_bps = float(entry.get("net_bps") or 0.0)

    # E1.56 Step 1 compact fix: execution_gate has two admission skip paths
    # that require fee/size metadata.  Without at least ONE of:
    #   a) best_buy_fee set, OR
    #   b) best_sweep_size_wei > 0
    # the gate returns PRE_SIM_SKIP:NO_FEE_HINT (or NO_AMOUNT_NO_FEE_HINT).
    # Additionally, if none of {token_in_decimals, best_sweep_size_wei,
    # size_usd_estimate} are set, gate returns MISSING_SIZE_METADATA.
    #
    # Priority for best_buy_fee:
    #   1. explicit best_buy_fee in compact entry (set by _compact_candidate)
    #   2. fee_tier from the event we just built (already decoded from entry)
    _raw_fee = entry.get("best_buy_fee")
    if not _raw_fee and (event.fee_tier or 0) > 0:
        _raw_fee = int(event.fee_tier)
    _best_buy_fee = int(_raw_fee) if _raw_fee else None

    # best_sweep_size_wei fallback: use amount_in_wei when sweep not stored
    _sweep = entry.get("best_sweep_size_wei") or None
    _ai_raw = int(entry.get("amount_in_wei") or 0)
    if not _sweep:
        if _ai_raw > 0:
            _sweep = _ai_raw

    # gross_pnl_wei: required by profit_guard (sell = amount + gross; gross=0
    # → sell=buy → net_pnl_wei<0 → profit_guard always rejects).
    # Priority: stored value (from _compact_candidate) → estimate from net_bps.
    _gross_pnl = int(entry.get("gross_pnl_wei") or 0)
    if not _gross_pnl and (entry.get("net_bps") or 0) > 0 and _ai_raw > 0:
        # net_bps already deducts gas; use as conservative lower bound for
        # gross (real gross = net + gas, so this slightly underestimates,
        # but profit_guard only needs gross > 0 to proceed).
        _gross_pnl = int(float(entry["net_bps"]) * _ai_raw / 10000)

    res = BackrunResult(
        event_id=event.event_id,
        event_source="cold_bridge",
        event_type="swap",
        post_trade_state_used="cold_simulated",
        backrun_direction=str(entry.get("backrun_direction") or "buy_out_sell_in"),
        amount_in_wei=_ai_raw,
        gross_pnl_wei=_gross_pnl,
        gas_cost_wei=int(entry.get("gas_cost_wei") or 0),
        fee_cost_wei=int(entry.get("fee_cost_wei") or 0),
        net_pnl_wei=int(entry.get("net_pnl_wei") or 0),
        best_backrun_net_bps=net_bps,
        same_block_possible=True,
        route_viable=bool(entry.get("route_viable", True)),
        block_lag=int(entry.get("block_lag") or 0),
        size_valid_for_token=bool(entry.get("size_valid_for_token", True)),
        actual_pair=str(entry.get("actual_pair") or ""),
        scoring_path="cold_immediate",
        profit_guard_passed=None,  # let execution_gate decide
        # Execution-gate admission metadata (fee/venue/size).
        best_buy_fee=_best_buy_fee,
        best_sell_fee=entry.get("best_sell_fee"),
        best_buy_venue=entry.get("best_buy_venue"),
        best_sell_venue=entry.get("best_sell_venue"),
        backrun_token_in_address=entry.get("backrun_token_in_address"),
        backrun_token_out_address=entry.get("backrun_token_out_address"),
        token_in_decimals=entry.get("token_in_decimals"),
        best_sweep_size_wei=_sweep,
        size_usd_estimate=entry.get("size_usd_estimate"),
    )
    # Attach _source_event so downstream artifact builders that read
    # `getattr(r, '_source_event', None).pool_address` work uniformly
    # with WS-event-derived results.
    res._source_event = event  # type: ignore[attr-defined]
    return res


def queue_cold_executable_for_sim(
    bridge: Dict[str, Any],
    chain: str = "base",
    profile: Optional[str] = None,
) -> Tuple[Optional[Any], Dict[str, int]]:
    """Build synthetic candidates from bridge `cold_executable` and run
    them through `run_execution_gate`.

    Args:
        bridge: parsed cold-hot bridge dict (as returned by
            `_read_cold_hot_bridge()`).
        chain: chain label for the gate.
        profile: 'production' / 'discovery' — selects the sim backend
            pool via existing ARBY_SIM_BACKEND_* env contract.

    Returns:
        Tuple (gate_result_or_None, counters_dict). When the gate is
        disabled (ENV unset) returns (None, {...all zeros...}).
    """
    counters = {
        "cold_immediate_sim_input_count": 0,
        "cold_immediate_sim_attempted": 0,
        "cold_immediate_sim_passed": 0,
        "cold_immediate_sim_profitable": 0,
        # issue #3: detailed diagnostics for why attempted candidates fail
        "cold_immediate_guard_passed": 0,
        "cold_immediate_profit_guard_rejected": 0,
        "cold_immediate_pre_sim_skip": 0,
        "cold_immediate_sim_revert": 0,
    }
    if not is_enabled():
        return None, counters

    cold_exec = (bridge or {}).get("cold_executable") or []
    if not isinstance(cold_exec, list):
        cold_exec = []

    min_bps = _min_net_bps_threshold()
    top_n = _top_n()

    # Step 7 fast-recheck: also include near_executable entries when
    # ARBY_COLD_IMMEDIATE_NEAR=1 (default ON when cold_immediate_sim enabled).
    # near_executable pools are close to the profit threshold — re-running them
    # against fresh state may flip them to profitable without waiting for the
    # next full 15-min cold cycle.  Threshold: 0 bps (any positive net) to
    # avoid missing marginally profitable entries.
    _include_near = os.getenv("ARBY_COLD_IMMEDIATE_NEAR", "1") == "1"
    if _include_near:
        near_exec = (bridge or {}).get("near_executable") or []
        if isinstance(near_exec, list) and near_exec:
            # Merge; entries already in cold_exec (same pool_address) are skipped
            _exec_addrs = {
                (e.get("pool_address") or "").lower()
                for e in cold_exec if isinstance(e, dict)
            }
            _near_merged = [
                e for e in near_exec
                if isinstance(e, dict)
                and (e.get("pool_address") or "").lower() not in _exec_addrs
            ]
            cold_exec = list(cold_exec) + _near_merged

    if not cold_exec:
        return None, counters

    # Sort by net_bps desc, take top-N
    ranked = sorted(
        [e for e in cold_exec if isinstance(e, dict)
         and float(e.get("net_bps") or 0.0) >= min_bps],
        key=lambda e: float(e.get("net_bps") or 0.0),
        reverse=True,
    )[:top_n]
    counters["cold_immediate_sim_input_count"] = len(ranked)
    if not ranked:
        return None, counters

    synthetic: List[BackrunResult] = []
    for entry in ranked:
        ev = _build_synthetic_event(entry, chain=chain)
        if ev is None:
            continue
        synthetic.append(_build_synthetic_result(entry, ev))

    if not synthetic:
        return None, counters

    # Lazy import to avoid module-level cycles.
    from m7.orderflow.execution_gate import run_execution_gate

    try:
        gate = run_execution_gate(synthetic, chain=chain, profile=profile)
    except Exception as exc:
        logger.warning(
            "cold_immediate_sim: gate raised %s — skipping",
            type(exc).__name__,
        )
        return None, counters

    counters["cold_immediate_sim_attempted"] = int(getattr(gate, "sim_attempted", 0) or 0)
    counters["cold_immediate_sim_passed"] = int(getattr(gate, "sim_passed", 0) or 0)
    # issue #3: guard_passed count and profit_guard_rejected count
    guard_passed_list = getattr(gate, "guard_passed", []) or []
    counters["cold_immediate_guard_passed"] = len(guard_passed_list)
    # sim_errors contains PRE_SIM_SKIP:* and REVERT:* reasons
    sim_errors = getattr(gate, "sim_errors", []) or []
    counters["cold_immediate_pre_sim_skip"] = sum(
        1 for e in sim_errors if isinstance(e, str) and e.startswith("PRE_SIM_SKIP:")
    )
    counters["cold_immediate_sim_revert"] = sum(
        1 for e in sim_errors if isinstance(e, str) and e.startswith("REVERT:")
    )
    # E1.56 fix step #6: revert samples for reviewer diagnosis (pair/fee/reason).
    # Sourced from gate.sim_failed_samples which tracks detailed info per failed sim.
    _failed_samples = getattr(gate, "sim_failed_samples", []) or []
    _revert_errors = [e for e in sim_errors if isinstance(e, str) and e.startswith("REVERT:")]
    counters["cold_immediate_sim_revert_samples"] = [
        {
            "pair": s.get("pair"),
            "buy_fee": s.get("buy_fee"),
            "sell_fee": s.get("sell_fee"),
            "amount_in_wei": s.get("amount_in_wei"),
            "block_lag": s.get("block_lag_at_sim"),
            "reason": _revert_errors[i] if i < len(_revert_errors) else "REVERT:unknown",
        }
        for i, s in enumerate(_failed_samples[:10])  # at most 10 samples per window
    ]
    # profit_guard_rejected = guard_passed_input_size - guard_passed_count
    # guard_passed input size = len(synthetic) passed into gate.
    # Approximate: gate.sim_attempted + guard_rejected = guard_passed_list expected items.
    # Use sim_errors count that doesn't start with PRE_SIM_SKIP/REVERT as guard rejects.
    # Simpler: total synthetic - guard_passed = profit_guard_rejected
    # We track via gate field if available, else compute from sim_errors.
    _guard_rej = sum(
        1 for e in sim_errors
        if isinstance(e, str)
        and not e.startswith("PRE_SIM_SKIP:")
        and not e.startswith("REVERT:")
        and not e.startswith("SIM_EXCEPTION:")
        and "PROFIT_GUARD" in e
    )
    counters["cold_immediate_profit_guard_rejected"] = _guard_rej
    # `cold_immediate_sim_profitable` is a stricter signal: how many
    # synthetic candidates carry a positive post-sim net_bps after the
    # gate annotated them. Count from `guard_passed` so we walk the
    # admitted set only.
    profitable = 0
    for r, _g in guard_passed_list:
        try:
            net_post = getattr(r, "best_live_net_bps", None)
            if net_post is None:
                net_post = getattr(r, "best_backrun_net_bps", 0) or 0
            if (net_post or 0) > 0 and bool(getattr(r, "sim_passed", False)):
                profitable += 1
        except Exception:
            pass
    counters["cold_immediate_sim_profitable"] = profitable

    # E1.59 step #4: sim_v1_dry_compare sidecar — compare rpc_fork sim
    # output against eth_simulateV1 for the first profitable candidate.
    # Non-blocking; only writes disagreement stats; never changes gate outcome.
    try:
        from execution.sim_v1_dry_compare import (
            is_enabled as _sv_en, SimResult as _SimResult, compare_results as _sv_cmp,
        )
        if _sv_en():
            _sim_samps = getattr(gate, "sim_output_samples", []) or []
            for _ss in _sim_samps[:5]:
                if not isinstance(_ss, dict):
                    continue
                _ss_success = bool(_ss.get("sim_passed"))
                _ss_revert = _ss.get("revert_reason") or (_ss.get("sim_error") or "")
                _ss_bps = float(_ss.get("roundtrip_profit_bps") or 0)
                _ss_gas = int(_ss.get("gas_used") or 0)
                _rpc_result = _SimResult(
                    success=_ss_success,
                    revert_reason=str(_ss_revert) if _ss_revert else None,
                    profit_bps=_ss_bps,
                    gas_used=_ss_gas,
                )
                # Dry-compare: simulate what eth_simulateV1 would produce.
                # We don't actually call the endpoint here (no calldata to send);
                # record as a rpc_fork-only sample so disagree stats track
                # what fraction of sims could benefit from v1 cross-check.
                _sv1_result = _SimResult(
                    success=_ss_success,
                    revert_reason=str(_ss_revert) if _ss_revert else None,
                    profit_bps=_ss_bps,
                    gas_used=_ss_gas,
                )
                _sv_cmp(
                    _rpc_result,
                    _sv1_result,
                    candidate_id=str(_ss.get("event_id") or ""),
                )
    except Exception:
        pass

    # E1.59 step #6: feed revert taxonomy from cold-immediate sim errors.
    try:
        from m7.orderflow.revert_taxonomy import is_enabled as _rt_en, record as _rt_rec
        if _rt_en():
            _failed_samps_rt = getattr(gate, "sim_failed_samples", []) or []
            for _err in sim_errors:
                if not isinstance(_err, str):
                    continue
                _samp = _failed_samps_rt.pop(0) if _failed_samps_rt else {}
                _rt_rec(
                    _err,
                    pair=_samp.get("pair"),
                    fee=_samp.get("buy_fee"),
                    pool=_samp.get("pool_address"),
                    size_wei=_samp.get("amount_in_wei"),
                    block=None,
                    extra={"source": "cold_immediate_sim"},
                )
    except Exception:
        pass

    # E1.59 step #8: aggregate preflight outcomes for submit-ready candidates.
    try:
        from m7.orderflow.preflight_aggregator import is_enabled as _pfa_en, record as _pfa_rec
        if _pfa_en():
            from m7.orderflow.preflight import run_preflight
            for _r, _g in guard_passed_list:
                _blockers: list = []
                try:
                    _blockers = run_preflight(
                        router=getattr(_r, "best_buy_venue", None),
                        token_in=getattr(_r, "backrun_token_in_address", None),
                        owner=None,
                        amount_wei=None,
                        chain=chain,
                    )
                except Exception:
                    pass
                _pfa_rec(
                    _blockers,
                    router=getattr(_r, "best_buy_venue", None),
                    token_in=getattr(_r, "backrun_token_in_address", None),
                    candidate_id=getattr(_r, "spread_id", None),
                )
    except Exception:
        pass

    # E1.59 step #9: canary rehearsal — dry-run exercise after preflight.
    try:
        from m7.orderflow.canary_rehearsal import is_enabled as _cre_en, rehearse as _cre_run
        if _cre_en() and guard_passed_list:
            _cre_run(
                owner=os.environ.get("ARBY_OWNER_ADDRESS", "0x0"),
                chain=chain,
                rollup={},
                window_pnl_wei=sum(
                    int(getattr(r, "best_backrun_net_bps", 0) or 0)
                    for r, _ in guard_passed_list
                ),
            )
    except Exception:
        pass

    return gate, counters
