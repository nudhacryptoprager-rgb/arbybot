#!/usr/bin/env python3
# PATH: scripts/pair_level_rca.py
"""
Pair-level RCA (Root Cause Analysis) tool.

Reads truth_report from a runDir (or rolling artifact) and produces:
1. Per-pair funnel summary (where each pair dies in the pipeline)
2. Economics decomposition for near-zero candidates
3. Counterfactual analysis — what changes if each gate is relaxed

Usage:
  py -3.11 scripts/pair_level_rca.py --run-dir data/runs/<dir>
  py -3.11 scripts/pair_level_rca.py --rolling          # uses rolling artifacts
  py -3.11 scripts/pair_level_rca.py --rolling --chain arbitrum_one
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_LST_TOKENS_UPPER = frozenset(
    {"WSTETH", "METH", "CBETH", "RETH", "STETH", "SWETH", "SFRXETH"}
)


def _is_lst_pair_rca(pair: str) -> bool:
    """Return True if pair contains an LST/derivative token."""
    parts = pair.upper().replace("/", " ").split()
    return any(p in _LST_TOKENS_UPPER for p in parts)


def load_truth_report(run_dir: Path) -> Optional[Dict[str, Any]]:
    """Load truth_report from runDir/reports/."""
    reports_dir = run_dir / "reports"
    if not reports_dir.exists():
        return None
    # Find truth_report_*.json
    candidates = sorted(reports_dir.glob("truth_report_*.json"), reverse=True)
    if not candidates:
        return None
    with open(candidates[0], "r", encoding="utf-8") as f:
        return json.load(f)


def load_scan_report(run_dir: Path) -> Optional[Dict[str, Any]]:
    """Load scan artifact from runDir/reports/."""
    reports_dir = run_dir / "reports"
    if not reports_dir.exists():
        return None
    candidates = sorted(reports_dir.glob("scan_*.json"), reverse=True)
    if not candidates:
        return None
    with open(candidates[0], "r", encoding="utf-8") as f:
        return json.load(f)


def _rt_gas_bps(rt: Dict[str, Any]) -> float:
    """Compute gas cost in bps from roundtrip result dict.

    R39: Prefer explicit gas_bps parsed from reject_reason (computed with
    real notional inside the engine) over back-calculation from gross_pnl.
    """
    # Primary: parse from reject_reason — authoritative, uses real notional
    rr = rt.get("reject_reason") or ""
    if "|gas=" in rr:
        try:
            gas_str = rr.split("|gas=")[1].split("|")[0]
            return float(gas_str)
        except (ValueError, IndexError):
            pass
    # Fallback: back-calculate from gas_cost_usd and gross_pnl
    gas_usd = rt.get("gas_cost_usd", 0) or 0
    gross_bps = rt.get("gross_pnl_bps", 0) or 0
    gross_usd = rt.get("gross_pnl_usd", 0) or 0
    if gross_bps != 0 and gross_usd != 0:
        notional_usd = abs(gross_usd / (gross_bps / 10000))
        return (gas_usd / notional_usd) * 10000 if notional_usd > 0 else 0
    return 0


def extract_pair_trace(truth: Dict[str, Any], scan: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Extract pair_funnel_trace from truth_report or reconstruct from signals."""
    # R29: If pair_funnel_trace is embedded in the artifact, use it directly
    stats = truth.get("stats") or (scan.get("stats") if scan else None) or {}
    if stats.get("pair_funnel_trace"):
        return stats["pair_funnel_trace"]
    
    # Fallback: reconstruct from spread_signals + roundtrip_summary
    signals = truth.get("spread_signals", [])
    rt_summary = truth.get("roundtrip_summary", {})
    rt_results = rt_summary.get("results", [])
    
    trace: Dict[str, Dict[str, Any]] = {}
    for sig in signals:
        pair = sig.get("pair", "unknown")
        if pair not in trace:
            trace[pair] = {
                "pair": pair,
                "spread_signals": 0,
                "best_spread_bps": None,
                "opp_count": 0,
                "rt_evaluated": 0,
                "rt_best_net_pnl_bps": None,
                "terminal_stage": "signal",
                "economics": {},
            }
        trace[pair]["spread_signals"] += 1
        sbps = sig.get("spread_bps")
        if sbps is not None:
            cur = trace[pair]["best_spread_bps"]
            if cur is None or sbps > cur:
                trace[pair]["best_spread_bps"] = sbps
    
    for rt in rt_results:
        pair = rt.get("pair", "unknown")
        if pair in trace:
            trace[pair]["rt_evaluated"] += 1
            trace[pair]["terminal_stage"] = "rt_evaluated"
            npnl = rt.get("net_pnl_bps")
            if npnl is not None:
                cur = trace[pair]["rt_best_net_pnl_bps"]
                if cur is None or npnl > cur:
                    trace[pair]["rt_best_net_pnl_bps"] = npnl
                    trace[pair]["economics"] = {
                        "rt_gross_pnl_bps": rt.get("gross_pnl_bps"),
                        "rt_net_pnl_bps": npnl,
                        "rt_slippage_bps": rt.get("estimated_slippage_bps"),
                        "rt_lp_fee_bps": ((rt.get("leg1_fee", 0) + rt.get("leg2_fee", 0)) / 100.0),
                        "rt_leg2_is_real": rt.get("leg2_is_real_quote"),
                        # R32: gas_bps computed from gas_cost_usd / notional
                        "rt_gas_bps": _rt_gas_bps(rt),
                    }
            # R39c: Collect ALL route-level results for per-route analysis
            trace[pair].setdefault("routes", []).append({
                "buy_dex": rt.get("buy_dex") or rt.get("leg1_dex", "?"),
                "sell_dex": rt.get("sell_dex") or rt.get("leg2_dex", "?"),
                "gross_pnl_bps": rt.get("gross_pnl_bps", 0),
                "net_pnl_bps": rt.get("net_pnl_bps", 0),
                "slippage_bps": rt.get("estimated_slippage_bps", 0),
                "gas_bps": _rt_gas_bps(rt),
                "lp_fee_bps": ((rt.get("leg1_fee", 0) + rt.get("leg2_fee", 0)) / 100.0),
                "leg2_real": rt.get("leg2_is_real_quote", False),
                "reject_reason": rt.get("reject_reason"),
            })

    # R29: Enrich with dynamic sweep size frontier data
    ds = stats.get("roundtrip", {}).get("dynamic_sweep", {})
    for sr in ds.get("results", []):
        pair = sr.get("pair", "unknown")
        if pair in trace:
            trace[pair]["sweep"] = {
                "best_size_usd": sr.get("best_size_usd"),
                "best_net_pnl_bps": sr.get("best_net_pnl_bps"),
                "gap_to_zero_bps": sr.get("gap_to_zero_bps"),
                "frontier_reason": sr.get("frontier_reason"),
                "sizes_evaluated": sr.get("sizes_evaluated"),
                "best_gas_bps": sr.get("best_gas_bps"),
                "best_fee_bps": sr.get("best_fee_bps"),
                "best_slippage_bps": sr.get("best_slippage_bps"),
            }
    
    return sorted(trace.values(), key=lambda x: -(x.get("rt_best_net_pnl_bps") or -9999))


def counterfactual_analysis(trace: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Analyze what gates block near-zero candidates.
    
    For each pair that reached rt_evaluated with negative net_pnl_bps,
    decompose the loss into components and identify the dominant blocker.
    """
    near_zero = []
    for t in trace:
        pnl = t.get("rt_best_net_pnl_bps")
        if pnl is not None and pnl < 0 and pnl > -100:  # Within 100 bps of breakeven
            econ = t.get("economics", {})
            gas_bps = econ.get("rt_gas_bps", 0) or 0
            slip_bps = econ.get("rt_slippage_bps", 0) or 0
            lp_fee_bps = econ.get("rt_lp_fee_bps", 0) or 0
            gap = econ.get("rt_gap_to_zero_bps", abs(pnl))
            
            # Determine dominant cost component
            costs = {"gas": gas_bps, "slippage": slip_bps, "lp_fee": lp_fee_bps}
            dominant = max(costs, key=costs.get) if any(costs.values()) else "unknown"
            
            near_zero.append({
                "pair": t["pair"],
                "net_pnl_bps": pnl,
                "gap_to_zero_bps": round(gap, 2),
                "gross_pnl_bps": econ.get("rt_gross_pnl_bps"),
                "gas_bps": round(gas_bps, 2),
                "slippage_bps": round(slip_bps, 2),
                "lp_fee_bps": round(lp_fee_bps, 2),
                "dominant_cost": dominant,
                "leg2_real": econ.get("rt_leg2_is_real"),
                # R29: Size frontier data from dynamic sweep
                "best_size_usd": t.get("sweep", {}).get("best_size_usd"),
                "sweep_best_net_pnl_bps": t.get("sweep", {}).get("best_net_pnl_bps"),
                "sweep_gap_to_zero_bps": t.get("sweep", {}).get("gap_to_zero_bps"),
                "sweep_frontier_reason": t.get("sweep", {}).get("frontier_reason"),
                "counterfactual": {
                    "if_zero_gas": round(pnl + gas_bps, 2) if gas_bps else pnl,
                    "if_zero_slippage": round(pnl + slip_bps, 2) if slip_bps else pnl,
                    "if_half_lp_fee": round(pnl + lp_fee_bps / 2, 2) if lp_fee_bps else pnl,
                    "if_fee100_both": round(pnl + lp_fee_bps - 2.0, 2) if lp_fee_bps > 2.0 else pnl,
                },
            })
    
    near_zero.sort(key=lambda x: x["gap_to_zero_bps"])
    
    # Aggregate: which cost component blocks the most candidates?
    blocker_counts: Dict[str, int] = {}
    for nz in near_zero:
        d = nz["dominant_cost"]
        blocker_counts[d] = blocker_counts.get(d, 0) + 1
    
    return {
        "near_zero_count": len(near_zero),
        "candidates": near_zero[:10],  # Top 10 closest to breakeven
        "dominant_blocker_distribution": blocker_counts,
    }


def print_pair_funnel(trace: List[Dict[str, Any]], chain_key: str = ""):
    """Print pair-level funnel summary to console."""
    header = f"PAIR-LEVEL FUNNEL TRACE"
    if chain_key:
        header += f" ({chain_key})"
    print(f"\n{'='*70}")
    print(header)
    print(f"{'='*70}")
    
    # Stage distribution
    stages: Dict[str, int] = {}
    for t in trace:
        s = t.get("terminal_stage", "unknown")
        stages[s] = stages.get(s, 0) + 1
    
    print(f"\nStage distribution ({len(trace)} pairs):")
    for stage in ["rt_profitable", "rt_evaluated", "opportunity", "signal", "quoted", "rejected", "resolved"]:
        cnt = stages.get(stage, 0)
        if cnt > 0:
            print(f"  {stage:25s}: {cnt}")
    
    print(f"\nTop candidates (by pipeline progress + PnL):")
    print(f"  {'Pair':20s} {'Stage':15s} {'Signals':>8s} {'Opps':>6s} {'RT':>4s} {'Best PnL':>10s} {'Gap':>8s}")
    print(f"  {'-'*20} {'-'*15} {'-'*8} {'-'*6} {'-'*4} {'-'*10} {'-'*8}")
    
    for t in trace[:15]:
        pnl = t.get("rt_best_net_pnl_bps")
        pnl_str = f"{pnl:+.2f}" if pnl is not None else "-"
        gap = t.get("economics", {}).get("rt_gap_to_zero_bps")
        gap_str = f"{gap:.2f}" if gap is not None else "-"
        print(f"  {t['pair']:20s} {t['terminal_stage']:15s} {t.get('spread_signals', 0):>8d} "
              f"{t.get('opp_count', 0):>6d} {t.get('rt_evaluated', 0):>4d} {pnl_str:>10s} {gap_str:>8s}")
    
    # Economics decomposition for RT-evaluated pairs
    rt_pairs = [t for t in trace if t.get("terminal_stage") in ("rt_evaluated", "rt_profitable")]
    if rt_pairs:
        print(f"\nEconomics decomposition (RT-evaluated pairs):")
        print(f"  {'Pair':20s} {'Gross':>8s} {'Net':>8s} {'Slip':>8s} {'Gas':>8s} {'LP Fee':>8s} {'Real':>5s} {'LST':>4s}")
        print(f"  {'-'*20} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*5} {'-'*4}")
        for t in rt_pairs[:10]:
            e = t.get("economics", {})
            # R38: LST/derivative pair annotation
            lst_flag = _is_lst_pair_rca(t["pair"])
            print(f"  {t['pair']:20s} "
                  f"{e.get('rt_gross_pnl_bps', 0):>+8.2f} "
                  f"{e.get('rt_net_pnl_bps', 0):>+8.2f} "
                  f"{e.get('rt_slippage_bps', 0):>8.2f} "
                  f"{e.get('rt_gas_bps', 0):>8.2f} "
                  f"{e.get('rt_lp_fee_bps', 0):>8.2f} "
                  f"{'Y' if e.get('rt_leg2_is_real') else 'N':>5s} "
                  f"{'Y' if lst_flag else '':>4s}")

    # R29: Size frontier summary from dynamic sweep
    swept_pairs = [t for t in trace if t.get("sweep")]
    if swept_pairs:
        print(f"\nSize frontier (dynamic sweep):")
        print(f"  {'Pair':20s} {'BstSz':>7s} {'BstPnL':>8s} {'Gap':>6s} {'Reason':>12s} {'Sizes':>5s}")
        print(f"  {'-'*20} {'-'*7} {'-'*8} {'-'*6} {'-'*12} {'-'*5}")
        for t in swept_pairs[:10]:
            sw = t["sweep"]
            bsz = sw.get("best_size_usd")
            bsz_str = f"${bsz:.0f}" if bsz is not None else "-"
            bpnl = sw.get("best_net_pnl_bps")
            bpnl_str = f"{bpnl:+.2f}" if bpnl is not None else "-"
            gap = sw.get("gap_to_zero_bps")
            gap_str = f"{gap:.2f}" if gap is not None else "-"
            fr = sw.get("frontier_reason", "-")
            se = sw.get("sizes_evaluated", 0)
            print(f"  {t['pair']:20s} {bsz_str:>7s} {bpnl_str:>8s} {gap_str:>6s} {fr:>12s} {se:>5d}")

    # R39c: Route-level economics — show ALL evaluated routes per pair
    route_pairs = [t for t in trace if t.get("routes")]
    if route_pairs:
        print(f"\nRoute-level economics (buy->sell per pair):")
        print(f"  {'Pair':20s} {'Route':>25s} {'Gross':>8s} {'Net':>8s} {'Slip':>8s} {'Gas':>8s} {'LP':>6s} {'Real':>5s}")
        print(f"  {'-'*20} {'-'*25} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*6} {'-'*5}")
        for t in route_pairs[:10]:
            for r in sorted(t["routes"], key=lambda x: -(x.get("net_pnl_bps") or -9999)):
                route_str = f"{r['buy_dex']}->{r['sell_dex']}"
                if len(route_str) > 25:
                    route_str = route_str[:22] + "..."
                print(f"  {t['pair']:20s} {route_str:>25s} "
                      f"{r['gross_pnl_bps']:>+8.2f} "
                      f"{r['net_pnl_bps']:>+8.2f} "
                      f"{r['slippage_bps']:>8.2f} "
                      f"{r['gas_bps']:>8.2f} "
                      f"{r['lp_fee_bps']:>6.1f} "
                      f"{'Y' if r['leg2_real'] else 'N':>5s}")


def print_counterfactual(cf: Dict[str, Any]):
    """Print counterfactual analysis to console."""
    print(f"\n{'='*70}")
    print("COUNTERFACTUAL ANALYSIS (near-zero candidates)")
    print(f"{'='*70}")
    
    if cf["near_zero_count"] == 0:
        print("  No candidates within 100 bps of breakeven.")
        return
    
    print(f"\n  {cf['near_zero_count']} candidates within 100 bps of breakeven")
    print(f"  Dominant blocker distribution: {cf['dominant_blocker_distribution']}")
    
    print(f"\n  {'Pair':20s} {'Net':>8s} {'Gap':>6s} {'Dom':>10s} {'0gas':>8s} {'0slip':>8s} {'hfLP':>8s} {'BstSz':>7s}")
    print(f"  {'-'*20} {'-'*8} {'-'*6} {'-'*10} {'-'*8} {'-'*8} {'-'*8} {'-'*7}")
    for c in cf["candidates"]:
        cf_vals = c["counterfactual"]
        bsz = c.get("best_size_usd")
        bsz_str = f"${bsz:.0f}" if bsz is not None else "-"
        print(f"  {c['pair']:20s} {c['net_pnl_bps']:>+8.2f} {c['gap_to_zero_bps']:>6.2f} "
              f"{c['dominant_cost']:>10s} "
              f"{cf_vals['if_zero_gas']:>+8.2f} {cf_vals['if_zero_slippage']:>+8.2f} "
              f"{cf_vals['if_half_lp_fee']:>+8.2f} {bsz_str:>7s}")


def _print_oe_funnel(truth: Dict[str, Any]):
    """Print OE rejection funnel and quote source summary from R31 truth_report fields."""
    oe = truth.get("oe_rejection_funnel")
    qss = truth.get("quote_source_summary")

    if oe:
        total = oe.get("total_opportunities", 0)
        gated = oe.get("gated_count", 0)
        rejected = oe.get("rejected_count", 0)
        reasons = oe.get("rejected_reasons", {})
        print(f"\nOE Rejection Funnel: {total} total -> {gated} gated, {rejected} rejected")
        if reasons:
            for reason, cnt in sorted(reasons.items(), key=lambda x: -x[1]):
                pct = cnt / rejected * 100 if rejected > 0 else 0
                print(f"  {reason:30s}: {cnt:>4d} ({pct:5.1f}%)")

    if qss:
        exec_q = qss.get("quotes_fetched_executable", 0)
        diag_q = qss.get("quotes_fetched_diagnostic", 0)
        fail_q = qss.get("quoter_v2_failed_count", 0)
        total_q = exec_q + diag_q + fail_q
        rate = exec_q / total_q * 100 if total_q > 0 else 0
        print(f"\nQuote Source: {exec_q} executable, {diag_q} diagnostic, {fail_q} quoter_v2_failed "
              f"(exec rate: {rate:.1f}%)")


def main():
    parser = argparse.ArgumentParser(description="Pair-level RCA tool")
    parser.add_argument("--run-dir", type=str, help="Path to runDir")
    parser.add_argument("--rolling", action="store_true", help="Use rolling artifacts")
    parser.add_argument("--chain", type=str, default="", help="Chain filter for multi-chain scans")
    parser.add_argument("--json", action="store_true", help="Output as JSON instead of console")
    args = parser.parse_args()
    
    truth = None
    scan = None
    chain_key = args.chain
    
    if args.rolling:
        # Use rolling artifacts
        rolling_dir = Path("data/runs/_rolling")
        
        # R30: --chain filter with --rolling finds the latest runDir for that chain
        # instead of always using run_summary_latest.json (which is primary chain only)
        if args.chain:
            runs_dir = Path("data/runs")
            chain_pattern = f"ci_m5_gate_{args.chain}_"
            chain_dirs = sorted(
                [d for d in runs_dir.iterdir() 
                 if d.is_dir() and d.name.startswith(chain_pattern)],
                key=lambda d: d.name,
                reverse=True,
            )
            for rd in chain_dirs[:5]:
                truth = load_truth_report(rd)
                if truth:
                    scan = load_scan_report(rd)
                    chain_key = args.chain
                    break
        else:
            latest_path = rolling_dir / "run_summary_latest.json"
            if latest_path.exists():
                with open(latest_path, "r", encoding="utf-8") as f:
                    summary = json.load(f)
                run_dir_rel = summary.get("inputs", {}).get("run_dir_rel")
                chain_key = chain_key or summary.get("inputs", {}).get("chain_key", "")
                if run_dir_rel:
                    run_dir = Path(run_dir_rel)
                    truth = load_truth_report(run_dir)
                    scan = load_scan_report(run_dir)
        if truth is None:
            print("ERROR: Could not load truth_report from rolling artifacts", file=sys.stderr)
            sys.exit(1)
    elif args.run_dir:
        run_dir = Path(args.run_dir)
        truth = load_truth_report(run_dir)
        scan = load_scan_report(run_dir)
        chain_key = chain_key or truth.get("chain_key", "") if truth else ""
        if truth is None:
            print(f"ERROR: No truth_report found in {run_dir}", file=sys.stderr)
            sys.exit(1)
    else:
        # Try to find latest runDir
        runs_dir = Path("data/runs")
        run_dirs = sorted(
            [d for d in runs_dir.iterdir() if d.is_dir() and d.name != "_rolling"],
            reverse=True,
        )
        for rd in run_dirs[:5]:  # Check 5 most recent
            truth = load_truth_report(rd)
            if truth:
                scan = load_scan_report(rd)
                chain_key = chain_key or truth.get("chain_key", "")
                break
        if truth is None:
            print("ERROR: No runDir with truth_report found", file=sys.stderr)
            sys.exit(1)
    
    trace = extract_pair_trace(truth, scan)
    cf = counterfactual_analysis(trace)
    
    if args.json:
        output = {
            "chain_key": chain_key,
            "pair_funnel_trace": trace,
            "counterfactual": cf,
        }
        if truth:
            output["quote_source_summary"] = truth.get("quote_source_summary")
            output["oe_rejection_funnel"] = truth.get("oe_rejection_funnel")
        print(json.dumps(output, indent=2, default=str))
    else:
        print_pair_funnel(trace, chain_key)
        # R32: Print OE funnel + quote source from truth_report
        if truth:
            _print_oe_funnel(truth)
        print_counterfactual(cf)


if __name__ == "__main__":
    main()
