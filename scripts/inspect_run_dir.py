#!/usr/bin/env python3
# PATH: scripts/inspect_run_dir.py
"""
RunDir inspection tool (v3.2.11).

Prints a concise summary of a runDir's scan pipeline:
- Status and no_data_reason
- Quotes: total/fetched/rejected
- Spread signals count
- Opportunity engine stats (from truth_report.stats.opportunity_engine.summary)
- Roundtrip evaluation results
- Top rejection reasons
- Quality reasons (WARN_PROFIT_DIAGNOSTIC, etc.)

Usage:
    py -3.11 scripts/inspect_run_dir.py [--run-dir <path>] [--json]

If --run-dir is not specified, uses the latest runDir from data/runs/
"""

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def find_latest_run_dir() -> Path | None:
    """
    Find the canonical latest runDir.
    
    Priority:
    1. Use run_dir from data/runs/_rolling/_latest.json (canonical source)
    2. Fallback to mtime-based selection if _latest.json unavailable
    """
    runs_root = REPO_ROOT / "data" / "runs"
    if not runs_root.exists():
        return None
    
    # v3.2.7: Try _latest.json first (canonical source of truth)
    latest_json = runs_root / "_rolling" / "_latest.json"
    if latest_json.exists():
        try:
            with open(latest_json) as f:
                data = json.load(f)
            # Extract run_dir from inputs or run_context
            inputs = data.get("inputs", {})
            run_context = data.get("run_context", {})
            run_dir_name = inputs.get("run_dir_name") or run_context.get("run_dir_name")
            if run_dir_name:
                run_dir_path = runs_root / run_dir_name
                if run_dir_path.exists():
                    return run_dir_path
        except Exception:
            pass  # Fallback to mtime-based selection
    
    # Fallback: mtime-based selection
    # Exclude special directories
    exclude = {"_rolling", "_incidents", "_offline", "cache"}
    
    dirs = [
        d for d in runs_root.iterdir()
        if d.is_dir() and d.name not in exclude and not d.name.startswith(".")
    ]
    
    if not dirs:
        return None
    
    # Sort by modification time (descending)
    dirs.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    return dirs[0]


def load_artifact(reports_dir: Path, pattern: str) -> dict | None:
    """Load the latest artifact matching pattern."""
    files = sorted(reports_dir.glob(pattern), reverse=True)
    if not files:
        return None
    with open(files[0]) as f:
        return json.load(f)


def inspect_run_dir(run_dir: Path) -> dict:
    """
    Inspect a runDir and return summary dict.
    
    Returns dict with all inspection fields.
    """
    reports_dir = run_dir / "reports"
    
    result = {
        "run_dir": run_dir.name,
        "run_dir_name": None,
        "run_timestamp": None,
        "artifacts_present": [],
        "artifacts_missing": [],
    }
    
    # Load artifacts
    scan = load_artifact(reports_dir, "scan_*.json")
    truth = load_artifact(reports_dir, "truth_report_*.json")
    reject = load_artifact(reports_dir, "reject_histogram_*.json")
    run_summary = load_artifact(reports_dir, "run_summary_*.json")
    
    # Check presence
    for name, data in [("scan", scan), ("truth_report", truth), ("reject_histogram", reject), ("run_summary", run_summary)]:
        if data:
            result["artifacts_present"].append(name)
        else:
            result["artifacts_missing"].append(name)
    
    # Extract key fields from truth_report (main source)
    if truth:
        stats = truth.get("stats", {})
        result["chain_key"] = truth.get("chain_key", "unknown")
        result["chain_id"] = truth.get("chain_id", 0)
        result["current_block"] = truth.get("current_block", 0)
        result["quotes_total"] = stats.get("quotes_total", 0)
        result["quotes_fetched"] = stats.get("quotes_fetched", 0)
        result["quotes_rejected"] = result["quotes_total"] - result["quotes_fetched"]
        result["dexes_active"] = stats.get("dexes_active", 0)
        result["spread_signals_count"] = len(truth.get("spread_signals", []))
        result["no_data_reason"] = stats.get("no_data_reason")
        
        # Config params
        config_params = truth.get("config_params", {})
        result["min_spread_bps"] = config_params.get("min_spread_bps")
        result["paper_size_usd"] = config_params.get("paper_size_usd")
        result["config_path"] = config_params.get("config_path")
        
        # v3.2.11 FIX: Opportunity engine stats from summary sub-object
        # Contract: truth_report.stats.opportunity_engine.summary.{total_opportunities, profitable_count, gated_count, ...}
        opp_engine = stats.get("opportunity_engine", {})
        opp_summary = opp_engine.get("summary", {})
        result["opportunity_engine"] = {
            "total": opp_summary.get("total_opportunities", 0),
            "profitable": opp_summary.get("profitable_count", 0),
            "gated": opp_summary.get("gated_count", 0),
            # v3.2.11: Additional fields for triage
            "rejected": opp_summary.get("rejected_count", 0),
            "best_net_profit_usd": opp_summary.get("best_net_profit_usd"),
            "one_leg_profit_is_diagnostic": opp_engine.get("one_leg_profit_is_diagnostic", False),
        }
        
        # v3.2.14: best_spread_minus_required_bps for "0 passed_to_roundtrip" RCA
        # Source: truth_report.stats.opportunity_engine.top_opportunities[0]
        top_opps = opp_engine.get("top_opportunities", [])
        best_opp = None
        best_margin = -999.0
        for opp in top_opps:
            margin = opp.get("spread_minus_required_bps")
            if margin is not None and margin > best_margin:
                best_margin = margin
                best_opp = opp
        
        if best_opp:
            # v3.2.15: Compute gas_bps if gas_usd and size_usd available
            gas_usd = best_opp.get("gas_usd_estimate") or best_opp.get("gas_usd")
            size_usd = best_opp.get("size_usd") or best_opp.get("paper_size_usd")
            computed_gas_bps = None
            if gas_usd is not None and size_usd and size_usd > 0:
                computed_gas_bps = round((gas_usd / size_usd) * 10000, 2)
            
            result["best_spread_economics"] = {
                "spread_minus_required_bps": best_opp.get("spread_minus_required_bps"),
                "spread_bps": best_opp.get("spread_bps"),
                "min_required_spread_bps": best_opp.get("min_required_spread_bps"),
                "pair": best_opp.get("pair"),
                "route": best_opp.get("route"),
                "is_roundtrip_viable": best_opp.get("is_roundtrip_viable", False),
                # v3.2.15: Cost breakdown fields for RCA (populated from spread_signal)
                "gas_bps": best_opp.get("gas_bps") or computed_gas_bps,
                "lp_fee_bps_roundtrip": best_opp.get("lp_fee_bps_roundtrip"),
                "effective_slippage_bps": best_opp.get("effective_slippage_bps"),
                "safety_bps": best_opp.get("safety_bps", 2.0),  # Default from min_required formula
            }
        else:
            result["best_spread_economics"] = None
        
        # Roundtrip stats
        rt_stats = stats.get("roundtrip", {})
        result["roundtrip"] = {
            "evaluated_count": rt_stats.get("evaluated_count", 0),
            "profitable_count": rt_stats.get("profitable_count", 0),
            "best_net_pnl_bps": rt_stats.get("best_net_pnl_bps"),
        }
        
        # v3.2.13: roundtrip_lp_filter for viability diagnostics
        lp_filter = stats.get("roundtrip_lp_filter", {})
        result["roundtrip_lp_filter"] = {
            "candidates_considered": lp_filter.get("candidates_considered", 0),
            "cross_dex_count": lp_filter.get("cross_dex_count", 0),
            "lp_viable_count": lp_filter.get("lp_viable_count", 0),
            "passed_to_roundtrip": lp_filter.get("passed_to_roundtrip", 0),
            # v3.2.15: Additional fields for reviewer RCA
            "margin_filtered_count": lp_filter.get("margin_filtered_count", 0),
            "unique_pairs_considered": lp_filter.get("unique_pairs_considered", 0),
        }
        
        # v3.2.13: profit_is_diagnostic flag (critical for reviewer)
        result["profit_is_diagnostic"] = opp_engine.get("one_leg_profit_is_diagnostic", False)
    
    # Extract from run_summary
    if run_summary:
        result["status"] = run_summary.get("status", "UNKNOWN")
        result["profit_status"] = run_summary.get("profit_status", "UNKNOWN")
        result["drift_status"] = run_summary.get("drift_status", "UNKNOWN")
        result["quality_status"] = run_summary.get("quality_status", "UNKNOWN")
        
        # v3.2.9: Extract run_context for provenance
        run_context = run_summary.get("run_context", {})
        result["run_timestamp"] = run_context.get("run_timestamp")
        # v3.2.11 FIX: run_dir_name fallback to run_dir.name if not in run_context
        result["run_dir_name"] = run_context.get("run_dir_name") or run_dir.name
        result["reasons"] = run_summary.get("reasons", [])
        
        # v3.2.11: Extract quality_reasons for reviewer triage (e.g., WARN_PROFIT_DIAGNOSTIC)
        result["quality_reasons"] = run_summary.get("quality_reasons", [])
        
        # Metrics 
        metrics = run_summary.get("metrics", {})
        result["signals_count"] = metrics.get("signals_count", 0)
        result["included_signals_count"] = metrics.get("included_signals_count", 0)
        result["total_net_usdc"] = metrics.get("total_net_usdc", 0)
        if "no_data_reason" not in result or result["no_data_reason"] is None:
            result["no_data_reason"] = metrics.get("no_data_reason")
    else:
        result["status"] = "UNKNOWN (no run_summary)"
        # v3.2.11 FIX: Fallback run_dir_name even without run_summary
        result["run_dir_name"] = run_dir.name
    
    # Extract rejection reasons from reject_histogram
    if reject:
        histogram = reject.get("reason_histogram", {})
        # Sort by count descending
        sorted_reasons = sorted(histogram.items(), key=lambda x: x[1], reverse=True)
        result["top_rejection_reasons"] = sorted_reasons[:5]
        result["total_rejects"] = reject.get("total_rejects", 0)
    
    return result


def print_summary(info: dict, as_json: bool = False):
    """Print the inspection summary."""
    if as_json:
        print(json.dumps(info, indent=2, default=str))
        return
    
    print("=" * 60)
    print(f"RunDir: {info['run_dir']}")
    print("=" * 60)
    
    # Provenance section (v3.2.9)
    print(f"\nPROVENANCE:")
    print(f"  run_timestamp: {info.get('run_timestamp', 'N/A')}")
    print(f"  run_dir_name: {info.get('run_dir_name', 'N/A')}")
    
    # Status section
    print(f"\nSTATUS: {info.get('status', 'UNKNOWN')}")
    if info.get("no_data_reason"):
        print(f"  no_data_reason: {info['no_data_reason']}")
    print(f"  profit: {info.get('profit_status', 'N/A')}, drift: {info.get('drift_status', 'N/A')}, quality: {info.get('quality_status', 'N/A')}")
    if info.get("reasons"):
        print(f"  reasons: {info['reasons']}")
    # v3.2.11: Display quality_reasons for reviewer triage
    if info.get("quality_reasons"):
        print(f"  quality_reasons: {info['quality_reasons']}")
    
    # Chain/config section
    print(f"\nCONFIG:")
    print(f"  chain: {info.get('chain_key', 'N/A')} (id={info.get('chain_id', 0)})")
    print(f"  block: {info.get('current_block', 0)}")
    print(f"  min_spread_bps: {info.get('min_spread_bps', 'N/A')}, paper_size_usd: {info.get('paper_size_usd', 'N/A')}")
    if info.get("config_path"):
        print(f"  config_path: {info['config_path']}")
    
    # Quotes section
    print(f"\nQUOTES:")
    print(f"  total: {info.get('quotes_total', 0)}")
    print(f"  fetched: {info.get('quotes_fetched', 0)}")
    print(f"  rejected: {info.get('quotes_rejected', 0)}")
    print(f"  dexes_active: {info.get('dexes_active', 0)}")
    
    # Spread signals
    print(f"\nSPREAD SIGNALS:")
    print(f"  count: {info.get('spread_signals_count', 0)}")
    
    # Opportunity engine
    opp = info.get("opportunity_engine", {})
    print(f"\nOPPORTUNITY ENGINE:")
    print(f"  total: {opp.get('total', 0)}, profitable: {opp.get('profitable', 0)}, gated: {opp.get('gated', 0)}, rejected: {opp.get('rejected', 0)}")
    if opp.get("best_net_profit_usd") is not None:
        print(f"  best_net_profit_usd: ${opp['best_net_profit_usd']:.4f}")
    if opp.get("one_leg_profit_is_diagnostic"):
        print(f"  [DIAGNOSTIC] one_leg_profit is diagnostic (not proven)")
    
    # Roundtrip
    rt = info.get("roundtrip", {})
    print(f"\nROUNDTRIP:")
    print(f"  evaluated: {rt.get('evaluated_count', 0)}, profitable: {rt.get('profitable_count', 0)}")
    if rt.get("best_net_pnl_bps") is not None:
        print(f"  best_net_pnl_bps: {rt['best_net_pnl_bps']}")
    
    # Metrics from run_summary
    print(f"\nMETRICS:")
    print(f"  signals_count: {info.get('signals_count', 0)} (included: {info.get('included_signals_count', 0)})")
    print(f"  total_net_usdc: {info.get('total_net_usdc', 0):.4f}")
    
    # Top rejection reasons
    if info.get("top_rejection_reasons"):
        print(f"\nTOP REJECTION REASONS: (total_rejects={info.get('total_rejects', 0)})")
        for reason, count in info["top_rejection_reasons"]:
            print(f"  {reason}: {count}")
    
    # Artifacts
    print(f"\nARTIFACTS:")
    print(f"  present: {info.get('artifacts_present', [])}")
    if info.get("artifacts_missing"):
        print(f"  MISSING: {info['artifacts_missing']}")
    
    print()


def main():
    parser = argparse.ArgumentParser(description="Inspect a runDir")
    parser.add_argument("--run-dir", type=str, help="Path to runDir (default: latest)")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()
    
    if args.run_dir:
        run_dir = Path(args.run_dir)
        if not run_dir.is_absolute():
            run_dir = REPO_ROOT / run_dir
    else:
        run_dir = find_latest_run_dir()
        if not run_dir:
            print("ERROR: No runDir found", file=sys.stderr)
            sys.exit(1)
    
    if not run_dir.exists():
        print(f"ERROR: RunDir not found: {run_dir}", file=sys.stderr)
        sys.exit(1)
    
    info = inspect_run_dir(run_dir)
    print_summary(info, as_json=args.json)


if __name__ == "__main__":
    main()
