#!/usr/bin/env python3
# PATH: scripts/inspect_run_dir.py
"""
RunDir inspection tool (v3.2.7).

Prints a concise summary of a runDir's scan pipeline:
- Status and no_data_reason
- Quotes: total/fetched/rejected
- Spread signals count
- Opportunity engine stats
- Roundtrip evaluation results
- Top rejection reasons

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
        
        # Opportunity engine stats
        opp_stats = stats.get("opportunity_engine", {})
        result["opportunity_engine"] = {
            "total": opp_stats.get("total", 0),
            "profitable": opp_stats.get("profitable", 0),
            "gated": opp_stats.get("gated", 0),
        }
        
        # Roundtrip stats
        rt_stats = stats.get("roundtrip", {})
        result["roundtrip"] = {
            "evaluated_count": rt_stats.get("evaluated_count", 0),
            "profitable_count": rt_stats.get("profitable_count", 0),
            "best_net_pnl_bps": rt_stats.get("best_net_pnl_bps"),
        }
    
    # Extract from run_summary
    if run_summary:
        result["status"] = run_summary.get("status", "UNKNOWN")
        result["profit_status"] = run_summary.get("profit_status", "UNKNOWN")
        result["drift_status"] = run_summary.get("drift_status", "UNKNOWN")
        result["quality_status"] = run_summary.get("quality_status", "UNKNOWN")
        result["reasons"] = run_summary.get("reasons", [])
        
        # Metrics 
        metrics = run_summary.get("metrics", {})
        result["signals_count"] = metrics.get("signals_count", 0)
        result["included_signals_count"] = metrics.get("included_signals_count", 0)
        result["total_net_usdc"] = metrics.get("total_net_usdc", 0)
        if "no_data_reason" not in result or result["no_data_reason"] is None:
            result["no_data_reason"] = metrics.get("no_data_reason")
    else:
        result["status"] = "UNKNOWN (no run_summary)"
    
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
    
    # Status section
    print(f"\nSTATUS: {info.get('status', 'UNKNOWN')}")
    if info.get("no_data_reason"):
        print(f"  no_data_reason: {info['no_data_reason']}")
    print(f"  profit: {info.get('profit_status', 'N/A')}, drift: {info.get('drift_status', 'N/A')}, quality: {info.get('quality_status', 'N/A')}")
    if info.get("reasons"):
        print(f"  reasons: {info['reasons']}")
    
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
    print(f"  total: {opp.get('total', 0)}, profitable: {opp.get('profitable', 0)}, gated: {opp.get('gated', 0)}")
    
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
