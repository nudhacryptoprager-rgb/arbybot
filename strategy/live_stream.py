# PATH: strategy/live_stream.py
"""
Live candidate stream builder — operator-facing row building for hot-loop streaming.

Extracted from run_scan_real.py (R28.28) to separate presentation/serialization
from scan orchestration.
"""

from typing import Any, Dict, List, Optional


# R38: Known LST/derivative pair tokens — their "spread" between DEXes is mostly
# rebasing differential or oracle lag, not a real arbitrage opportunity.
# Use lower SUSPECT_ACCOUNTING threshold for these pairs.
_LST_TOKENS = frozenset({
    "WSTETH", "wstETH",
    "METH", "mETH",
    "CBETH", "cbETH",
    "RETH", "rETH",
    "STETH", "stETH",
    "SWETH", "swETH",
    "SFRXETH", "sfrxETH",
})
_SANE_RT_PNL_MAX_BPS = 500  # generic threshold
_SANE_RT_PNL_MAX_BPS_LST = 50  # R38: tighter for LST/derivative pairs


def _is_lst_pair(pair: str) -> bool:
    """Check if pair involves LST/derivative tokens with known false-positive risk."""
    parts = pair.upper().replace("/", " ").split()
    return any(p in {t.upper() for t in _LST_TOKENS} for p in parts)


def build_live_candidate_stream(
    chain_key: str,
    opportunities: List[Dict[str, Any]],
    roundtrip_results: List[Any],
    dynamic_sweep: Optional[Dict[str, Any]],
    default_size_usd: float,
    max_candidates: int = 10,
    sweep_candidates: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Build compact operator-facing pair candidates for hot-loop streaming.

    Each candidate row merges opportunity, roundtrip, and sweep data into a
    single dict suitable for the live dashboard and parent-process IPC.

    R34: When roundtrip_results is empty but sweep/reprieve candidates exist,
    builds diagnostic rows from dynamic_sweep results or reprieve candidates.

    Returns at most *max_candidates* rows sorted by profitability.
    """
    opp_map = {
        (o.get("pair"), o.get("buy_dex"), o.get("sell_dex")): o
        for o in (opportunities or [])
    }
    reprieve_map = {
        (c.get("pair"), c.get("buy_dex"), c.get("sell_dex")): c
        for c in (sweep_candidates or [])
    }
    sweep_map = {
        (r.get("pair"), r.get("buy_dex"), r.get("sell_dex")): r
        for r in ((dynamic_sweep or {}).get("results") or [])
    }
    candidates: List[Dict[str, Any]] = []
    seen_keys: set = set()

    # Primary path: rows from roundtrip evaluation results
    for rt in roundtrip_results or []:
        key = (rt.pair, rt.buy_dex, rt.sell_dex)
        seen_keys.add(key)
        opp = opp_map.get(key, {})
        reprieve = reprieve_map.get(key, {})
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
        # R38: LST/derivative pairs get tighter accounting threshold
        _suspect_thr = _SANE_RT_PNL_MAX_BPS_LST if _is_lst_pair(rt.pair) else _SANE_RT_PNL_MAX_BPS
        if rt.is_profitable and abs(net_bps) > _suspect_thr:
            final_result = "SUSPECT_ACCOUNTING"
        elif rt.is_profitable and rt.leg2_is_real_quote:
            final_result = "ROUNDTRIP_PROFITABLE"
        elif rt.leg2_is_real_quote:
            final_result = "ROUNDTRIP_NOT_PROFITABLE"
        else:
            final_result = "ONE_LEG_ONLY_DIAGNOSTIC"
        spread = (
            opp.get("spread_bps")
            or opp.get("gross_spread_bps")
            or reprieve.get("spread_bps")
            or reprieve.get("gross_spread_bps")
        )
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
            "reject_reason": rt.reject_reason or reprieve.get("reject_reason"),
        })

    # R34: Secondary path — when roundtrip_results is empty, build rows from
    # dynamic_sweep results so the live stream is not silent during reprieve-only runs.
    if not candidates and sweep_map:
        for key, sweep in sweep_map.items():
            if key in seen_keys:
                continue
            seen_keys.add(key)
            pair, buy_dex, sell_dex = key
            opp = opp_map.get(key, {})
            reprieve = reprieve_map.get(key, {})
            net_bps = sweep.get("best_net_pnl_bps")
            size_usd = sweep.get("best_size_usd") or opp.get("usd_notional") or default_size_usd
            cost_bps = sweep.get("best_total_cost_bps")
            spread = (
                opp.get("spread_bps")
                or opp.get("gross_spread_bps")
                or reprieve.get("spread_bps")
                or reprieve.get("gross_spread_bps")
            )
            final_net_usd = None
            if size_usd is not None and net_bps is not None:
                final_net_usd = round((float(size_usd) * float(net_bps)) / 10000.0, 4)
            candidates.append({
                "network": chain_key,
                "pair": pair,
                "route": f"{buy_dex}->{sell_dex}",
                "buy_dex": buy_dex,
                "sell_dex": sell_dex,
                "optimal_size_usd": round(float(size_usd), 2) if size_usd is not None else None,
                "spread_bps": round(float(spread), 2) if spread is not None else None,
                "execution_cost_bps": round(float(cost_bps), 2) if cost_bps is not None else None,
                "execution_cost_usd": round((float(size_usd) * float(cost_bps)) / 10000.0, 4) if size_usd is not None and cost_bps is not None else None,
                "final_net_pnl_bps": round(float(net_bps), 2) if net_bps is not None else None,
                "final_net_pnl_usd": final_net_usd,
                "final_result": "DIAGNOSTIC_FRONTIER",
                "is_actionable": False,
                "real_quote": False,
                "reject_reason": reprieve.get("reject_reason"),
            })

    # R34: Tertiary path — reprieve candidates without sweep results still get rows.
    if not candidates and sweep_candidates:
        for sc in sweep_candidates[:max_candidates]:
            pair = sc.get("pair")
            buy_dex = sc.get("buy_dex")
            sell_dex = sc.get("sell_dex")
            key = (pair, buy_dex, sell_dex)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            spread = sc.get("spread_bps") or sc.get("gross_spread_bps")
            size_usd = sc.get("usd_notional") or default_size_usd
            candidates.append({
                "network": chain_key,
                "pair": pair,
                "route": f"{buy_dex}->{sell_dex}",
                "buy_dex": buy_dex,
                "sell_dex": sell_dex,
                "optimal_size_usd": round(float(size_usd), 2) if size_usd is not None else None,
                "spread_bps": round(float(spread), 2) if spread is not None else None,
                "execution_cost_bps": None,
                "execution_cost_usd": None,
                "final_net_pnl_bps": None,
                "final_net_pnl_usd": None,
                "final_result": "REPRIEVE_CANDIDATE",
                "is_actionable": False,
                "real_quote": False,
                "reject_reason": sc.get("reject_reason"),
            })

    candidates.sort(
        key=lambda c: (
            c.get("final_result") != "ROUNDTRIP_PROFITABLE",
            c.get("final_result") == "ONE_LEG_ONLY_DIAGNOSTIC",
            c.get("final_result") == "REPRIEVE_CANDIDATE",
            -(c.get("final_net_pnl_bps") or -999999.0),
        )
    )
    return candidates[:max_candidates]
