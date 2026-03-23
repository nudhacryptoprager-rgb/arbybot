# PATH: strategy/pair_trace.py
"""
Pair-level funnel trace — per-pair diagnostic showing where each
candidate is lost in the scanner pipeline.

R29: Enables isolation of market-efficiency vs policy/gate blockers
by tracking per-pair state at each pipeline stage:
  resolved → quoted → signal → opportunity → rt_candidate → rt_evaluated → rt_profitable

Extracted from run_scan_real.py to keep orchestrator lean.
"""

from typing import Any, Dict, List, Optional


def _empty_trace(pair: str, resolved: bool = False) -> Dict[str, Any]:
    """Create an empty trace entry for a pair."""
    return {
        "pair": pair,
        "resolved": resolved,
        "pools_resolved": 0,
        "quotes_fetched": 0,
        "quotes_rejected": 0,
        "reject_reasons": {},
        "dexes_quoted": set(),
        "spread_signals": 0,
        "best_spread_bps": None,
        "opp_count": 0,
        "best_spread_minus_req_bps": None,
        "rt_candidates": 0,
        "rt_evaluated": 0,
        "rt_best_net_pnl_bps": None,
        "rt_reject_reasons": {},
        "terminal_stage": "resolved" if resolved else "unknown",
        "economics": {},
        # R36: Sweep reprieve tracking
        "sweep_reprieved": False,
        "sweep_reprieve_reason": None,
        "sweep_evaluated": False,
        "sweep_best_net_pnl_bps": None,
        "sweep_best_size_usd": None,
        "sweep_frontier_reason": None,
    }


def build_pair_funnel_trace(
    pairs_list: list,
    quotes_sample: List[Dict[str, Any]],
    rejected_quotes: List[Dict[str, Any]],
    spread_signals: List[Dict[str, Any]],
    opps_list: List[Dict[str, Any]],
    roundtrip_results: list,
    eligible_opps: List[Dict[str, Any]],
    sweep_candidates: Optional[List[Dict[str, Any]]] = None,
    sweep_results: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Build per-pair funnel trace from all pipeline stages.

    Returns list of pair trace dicts sorted by how far each pair
    progressed in the pipeline (furthest first, then by best PnL).
    """
    trace: Dict[str, Dict[str, Any]] = {}

    # Stage 1: Resolved pairs from universe
    if pairs_list:
        for p in pairs_list:
            _pkey = getattr(p, "display_name", None) or f"{p.token_in}/{p.token_out}"
            if _pkey not in trace:
                trace[_pkey] = _empty_trace(_pkey, resolved=True)
            trace[_pkey]["pools_resolved"] += 1

    # Stage 2: Quotes (fetched + rejected)
    for q in quotes_sample:
        tin = q.get("token_in") or ""
        tout = q.get("token_out") or ""
        _pkey = f"{tin}/{tout}" if tin and tout else "unknown"
        if _pkey not in trace:
            trace[_pkey] = _empty_trace(_pkey)
        trace[_pkey]["quotes_fetched"] += 1
        trace[_pkey]["dexes_quoted"].add(q.get("dex_id", ""))
        trace[_pkey]["terminal_stage"] = "quoted"

    for rq in rejected_quotes:
        _pkey = rq.get("pair") or "unknown"
        if _pkey not in trace:
            trace[_pkey] = _empty_trace(_pkey)
        trace[_pkey]["quotes_rejected"] += 1
        reason = rq.get("reason", "UNKNOWN")
        trace[_pkey]["reject_reasons"][reason] = trace[_pkey]["reject_reasons"].get(reason, 0) + 1

    # Stage 3: Spread signals
    for ss in spread_signals:
        _pkey = ss.get("pair", "unknown")
        if _pkey in trace:
            trace[_pkey]["spread_signals"] += 1
            sbps = ss.get("spread_bps")
            if sbps is not None:
                cur = trace[_pkey]["best_spread_bps"]
                if cur is None or sbps > cur:
                    trace[_pkey]["best_spread_bps"] = sbps
            trace[_pkey]["terminal_stage"] = "signal"

    # Stage 4: Opportunity engine
    for opp in opps_list:
        _pkey = opp.get("pair", "unknown") if isinstance(opp, dict) else "unknown"
        if _pkey in trace:
            trace[_pkey]["opp_count"] += 1
            smr = opp.get("spread_minus_required_bps")
            if smr is not None:
                cur = trace[_pkey]["best_spread_minus_req_bps"]
                if cur is None or smr > cur:
                    trace[_pkey]["best_spread_minus_req_bps"] = smr
            trace[_pkey]["terminal_stage"] = "opportunity"
            # Economics decomposition from best opportunity
            trace[_pkey]["economics"] = {
                "gross_spread_bps": float(opp.get("gross_spread_bps", 0)),
                "min_required_spread_bps": float(opp.get("min_required_spread_bps", 0)),
                "spread_minus_required_bps": float(opp.get("spread_minus_required_bps", 0)),
                "gas_cost_usd": float(opp.get("gas_cost_usd", 0)),
                "fee_cost_usd": float(opp.get("fee_cost_usd", 0)),
                "net_profit_usd": float(opp.get("net_profit_usd", 0)),
                "buy_fee": opp.get("buy_fee"),
                "sell_fee": opp.get("sell_fee"),
            }

    # Stage 5: RT candidates from selection (pre-eval)
    for eo in eligible_opps:
        _pkey = eo.get("pair", "unknown") if isinstance(eo, dict) else "unknown"
        if _pkey in trace:
            trace[_pkey]["rt_candidates"] += 1

    # Stage 6: Roundtrip evaluation
    for rt_r in roundtrip_results:
        _pkey = rt_r.pair
        if _pkey in trace:
            trace[_pkey]["rt_evaluated"] += 1
            trace[_pkey]["terminal_stage"] = "rt_evaluated"
            if rt_r.reject_reason:
                trace[_pkey]["rt_reject_reasons"][rt_r.reject_reason] = (
                    trace[_pkey]["rt_reject_reasons"].get(rt_r.reject_reason, 0) + 1
                )
            cur_best = trace[_pkey]["rt_best_net_pnl_bps"]
            if cur_best is None or rt_r.net_pnl_bps > cur_best:
                trace[_pkey]["rt_best_net_pnl_bps"] = round(rt_r.net_pnl_bps, 2)
                # Full economics decomposition for best RT candidate
                trace[_pkey]["economics"]["rt_gross_pnl_bps"] = round(rt_r.gross_pnl_bps, 2)
                trace[_pkey]["economics"]["rt_net_pnl_bps"] = round(rt_r.net_pnl_bps, 2)
                trace[_pkey]["economics"]["rt_slippage_bps"] = round(rt_r.estimated_slippage_bps, 2)
                _notional = rt_r.net_pnl_usd + rt_r.gas_cost_usd if rt_r.gas_cost_usd else 0.01
                trace[_pkey]["economics"]["rt_gas_bps"] = round(
                    (rt_r.gas_cost_usd / max(abs(_notional), 0.01)) * 10000
                    if rt_r.gas_cost_usd else 0, 2
                )
                trace[_pkey]["economics"]["rt_lp_fee_bps"] = (rt_r.leg1_fee + rt_r.leg2_fee) / 100.0
                trace[_pkey]["economics"]["rt_leg2_is_real"] = rt_r.leg2_is_real_quote
                trace[_pkey]["economics"]["rt_gap_to_zero_bps"] = (
                    round(abs(rt_r.net_pnl_bps), 2) if rt_r.net_pnl_bps < 0 else 0.0
                )
            if rt_r.is_profitable:
                trace[_pkey]["terminal_stage"] = "rt_profitable"

    # R36 Stage 5b: Sweep reprieve — which pairs were reprieved
    if sweep_candidates:
        for sc in sweep_candidates:
            _pkey = sc.get("pair", "unknown") if isinstance(sc, dict) else "unknown"
            if _pkey in trace:
                trace[_pkey]["sweep_reprieved"] = True
                trace[_pkey]["sweep_reprieve_reason"] = sc.get("reject_reason")
                if trace[_pkey]["terminal_stage"] in ("opportunity", "signal", "quoted", "resolved", "unknown"):
                    trace[_pkey]["terminal_stage"] = "sweep_reprieved"

    # R36 Stage 5c: Sweep evaluation results
    if sweep_results:
        for sr in sweep_results:
            _pkey = sr.get("pair", "unknown")
            if _pkey in trace:
                trace[_pkey]["sweep_evaluated"] = True
                best_pnl = sr.get("best_net_pnl_bps")
                best_size = sr.get("best_size_usd")
                frontier = sr.get("frontier_reason")
                trace[_pkey]["sweep_best_net_pnl_bps"] = round(best_pnl, 2) if best_pnl is not None else None
                trace[_pkey]["sweep_best_size_usd"] = best_size
                trace[_pkey]["sweep_frontier_reason"] = frontier
                if best_pnl is not None and best_pnl > 0:
                    trace[_pkey]["terminal_stage"] = "sweep_profitable"
                elif trace[_pkey]["terminal_stage"] == "sweep_reprieved":
                    trace[_pkey]["terminal_stage"] = "sweep_not_profitable"

    # Serialize: convert sets to lists, sort by pipeline progress
    _stage_order = {
        "rt_profitable": 0, "sweep_profitable": 1, "rt_evaluated": 2,
        "sweep_not_profitable": 3, "sweep_reprieved": 4, "opportunity": 5,
        "signal": 6, "quoted": 7, "rejected": 8, "resolved": 9, "unknown": 10,
    }
    result = []
    for pt in trace.values():
        pt["dexes_quoted"] = sorted(pt["dexes_quoted"]) if isinstance(pt["dexes_quoted"], set) else pt["dexes_quoted"]
        result.append(pt)
    result.sort(key=lambda x: (
        _stage_order.get(x["terminal_stage"], 9),
        -(x.get("rt_best_net_pnl_bps") or -9999),
    ))
    return result
