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
    }
    if not is_enabled():
        return None, counters

    cold_exec = (bridge or {}).get("cold_executable") or []
    if not isinstance(cold_exec, list) or not cold_exec:
        return None, counters

    min_bps = _min_net_bps_threshold()
    top_n = _top_n()

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
    # `cold_immediate_sim_profitable` is a stricter signal: how many
    # synthetic candidates carry a positive post-sim net_bps after the
    # gate annotated them. Count from `guard_passed` so we walk the
    # admitted set only.
    profitable = 0
    for r, _g in (getattr(gate, "guard_passed", []) or []):
        try:
            net_post = getattr(r, "best_live_net_bps", None)
            if net_post is None:
                net_post = getattr(r, "best_backrun_net_bps", 0) or 0
            if (net_post or 0) > 0 and bool(getattr(r, "sim_passed", False)):
                profitable += 1
        except Exception:
            pass
    counters["cold_immediate_sim_profitable"] = profitable
    return gate, counters
