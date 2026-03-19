# PATH: strategy/live_stream.py
"""
Live candidate stream builder — operator-facing row building for hot-loop streaming.

Extracted from run_scan_real.py (R28.28) to separate presentation/serialization
from scan orchestration.
"""

from typing import Any, Dict, List, Optional


def build_live_candidate_stream(
    chain_key: str,
    opportunities: List[Dict[str, Any]],
    roundtrip_results: List[Any],
    dynamic_sweep: Optional[Dict[str, Any]],
    default_size_usd: float,
    max_candidates: int = 10,
) -> List[Dict[str, Any]]:
    """Build compact operator-facing pair candidates for hot-loop streaming.

    Each candidate row merges opportunity, roundtrip, and sweep data into a
    single dict suitable for the live dashboard and parent-process IPC.

    Returns at most *max_candidates* rows sorted by profitability.
    """
    opp_map = {
        (o.get("pair"), o.get("buy_dex"), o.get("sell_dex")): o
        for o in (opportunities or [])
    }
    sweep_map = {
        (r.get("pair"), r.get("buy_dex"), r.get("sell_dex")): r
        for r in ((dynamic_sweep or {}).get("results") or [])
    }
    candidates: List[Dict[str, Any]] = []
    for rt in roundtrip_results or []:
        key = (rt.pair, rt.buy_dex, rt.sell_dex)
        opp = opp_map.get(key, {})
        sweep = sweep_map.get(key, {})
        lp_fee_bps = ((rt.leg1_fee or 0) + (rt.leg2_fee or 0)) / 100.0
        gas_bps = max(0.0, float(rt.gross_pnl_bps or 0.0) - float(rt.net_pnl_bps or 0.0))
        cost_bps = sweep.get("best_total_cost_bps")
        if cost_bps is None:
            cost_bps = round(abs(float(rt.estimated_slippage_bps or 0.0)) + lp_fee_bps + gas_bps, 2)
        size_usd = sweep.get("best_size_usd") or opp.get("usd_notional") or default_size_usd
        net_bps = sweep.get("best_net_pnl_bps")
        if net_bps is None:
            net_bps = float(rt.net_pnl_bps or 0.0)
        if rt.is_profitable and abs(net_bps) > 500:
            final_result = "SUSPECT_ACCOUNTING"
        elif rt.is_profitable and rt.leg2_is_real_quote:
            final_result = "ROUNDTRIP_PROFITABLE"
        elif rt.leg2_is_real_quote:
            final_result = "ROUNDTRIP_NOT_PROFITABLE"
        else:
            final_result = "ONE_LEG_ONLY_DIAGNOSTIC"
        spread = opp.get("spread_bps") or opp.get("gross_spread_bps")
        if spread is None and rt.gross_pnl_bps is not None:
            spread = float(rt.gross_pnl_bps)
        is_actionable = bool(rt.leg2_is_real_quote) and final_result != "SUSPECT_ACCOUNTING"
        final_net_usd = None
        if size_usd is not None and net_bps is not None:
            final_net_usd = round((float(size_usd) * float(net_bps)) / 10000.0, 4)
        candidates.append({
            "network": chain_key,
            "pair": rt.pair,
            "route": f"{rt.buy_dex}->{rt.sell_dex}",
            "buy_dex": rt.buy_dex,
            "sell_dex": rt.sell_dex,
            "optimal_size_usd": round(float(size_usd), 2) if size_usd is not None else None,
            "spread_bps": round(float(spread), 2) if spread is not None else None,
            "execution_cost_bps": round(float(cost_bps), 2) if cost_bps is not None else None,
            "execution_cost_usd": round((float(size_usd) * float(cost_bps)) / 10000.0, 4) if size_usd is not None and cost_bps is not None else None,
            "final_net_pnl_bps": round(float(net_bps), 2) if net_bps is not None else None,
            "final_net_pnl_usd": final_net_usd,
            "final_result": final_result,
            "is_actionable": is_actionable,
            "real_quote": bool(rt.leg2_is_real_quote),
            "reject_reason": rt.reject_reason,
        })
    candidates.sort(
        key=lambda c: (
            c.get("final_result") != "ROUNDTRIP_PROFITABLE",
            c.get("final_result") == "ONE_LEG_ONLY_DIAGNOSTIC",
            -(c.get("final_net_pnl_bps") or -999999.0),
        )
    )
    return candidates[:max_candidates]
