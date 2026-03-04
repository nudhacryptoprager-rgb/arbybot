#!/usr/bin/env python3
# PATH: scripts/inspect_rolling.py
"""
Inspect Rolling Artifacts - quick inspection of M4 rolling state.

Usage:
  python scripts/inspect_rolling.py           # Summary
  python scripts/inspect_rolling.py --excluded # Show excluded signals detail
  python scripts/inspect_rolling.py --json     # JSON output

Exit codes:
  0 = OK (data available)
  1 = NO_DATA (rolling artifacts not found)
"""

import argparse
import glob
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent

__version__ = "2.2.0"  # v3.2.11: chain_keys from agg.quick_stats (canonical source)


def load_rolling_artifacts():
    """Load all rolling artifacts."""
    rolling_dir = PROJECT_ROOT / "data" / "runs" / "_rolling"
    
    artifacts = {}
    
    files = [
        ("_latest.json", "latest"),
        ("run_summary_latest.json", "run_summary"),
        ("m4_stability_agg.json", "agg"),
    ]
    
    for filename, key in files:
        path = rolling_dir / filename
        if path.exists():
            try:
                artifacts[key] = json.loads(path.read_text(encoding="utf-8"))
            except Exception as e:
                print(f"ERROR: Could not load {filename}: {e}", file=sys.stderr)
    
    return artifacts


def get_excluded_signals(run_dir: str):
    """Get excluded signals from the latest signals file in a run directory."""
    signals_pattern = PROJECT_ROOT / "data" / "runs" / run_dir / "reports" / "signals_*.json"
    signals_files = sorted(glob.glob(str(signals_pattern)))
    
    if not signals_files:
        return []
    
    try:
        signals_data = json.loads(Path(signals_files[-1]).read_text(encoding="utf-8"))
        return [
            s for s in signals_data.get("signals", [])
            if s.get("is_excluded_spread")
        ]
    except Exception as e:
        print(f"ERROR: Could not load signals: {e}", file=sys.stderr)
        return []


def print_summary(artifacts, excluded, as_json=False):
    """Print summary of rolling state."""
    if as_json:
        agg_qs = artifacts.get("agg", {}).get("quick_stats", {})
        output = {
            "rolling": {
                "run_dir_name": artifacts.get("run_summary", {}).get("inputs", {}).get("run_dir_name"),
                "run_timestamp": artifacts.get("run_summary", {}).get("run_context", {}).get("run_timestamp"),
                "runs_in_window": artifacts.get("agg", {}).get("runs_in_window"),
                "agg_status": artifacts.get("agg", {}).get("agg_status"),
                "agg_reasons": artifacts.get("agg", {}).get("agg_reasons", []),
                "data_run_rate": artifacts.get("latest", {}).get("data_run_rate"),
                "total_net_usdc": agg_qs.get("total_net_usdc"),
                "unique_pairs": agg_qs.get("unique_pairs"),
                "unique_routes_cross_dex": agg_qs.get("unique_routes_cross_dex"),
                # v3.2.11: Distinguish window vs latest chain_key
                "window_chain_key": agg_qs.get("chain_key"),  # Aggregate: single chain or "MIXED"
                "latest_chain_key": artifacts.get("latest", {}).get("inputs", {}).get("chain_key"),
                # v3.2.11 FIX: Read chain_keys from agg.quick_stats (canonical source), not _latest
                "chain_keys": agg_qs.get("chain_keys", []),  # List of unique chains in window
            },
            "signals": {
                "included_count": artifacts.get("run_summary", {}).get("metrics", {}).get("included_signals_count"),
                "excluded_count": artifacts.get("run_summary", {}).get("metrics", {}).get("excluded_signals_count"),
            },
            "excluded_signals": [
                {
                    "pair": s.get("pair"),
                    "buy_dex": s.get("buy_dex"),
                    "buy_pool": s.get("buy_pool"),
                    "sell_dex": s.get("sell_dex"),
                    "sell_pool": s.get("sell_pool"),
                    "spread_bps": s.get("spread_bps"),
                    "confidence_reasons": s.get("confidence_reasons"),
                }
                for s in excluded
            ],
        }
        print(json.dumps(output, indent=2))
        return
    
    # Text output
    rs = artifacts.get("run_summary", {})
    agg = artifacts.get("agg", {})
    latest = artifacts.get("latest", {})
    
    run_dir = rs.get("inputs", {}).get("run_dir_name", "N/A")
    run_timestamp = rs.get("run_context", {}).get("run_timestamp", "N/A")
    runs_in_window = agg.get("runs_in_window", "N/A")
    agg_status = agg.get("agg_status", "N/A")
    agg_reasons = agg.get("agg_reasons", [])
    data_run_rate = latest.get("data_run_rate", "N/A")
    total_net_usdc = agg.get("quick_stats", {}).get("total_net_usdc", "N/A")
    unique_pairs = agg.get("quick_stats", {}).get("unique_pairs", "N/A")
    unique_routes_cross_dex = agg.get("quick_stats", {}).get("unique_routes_cross_dex", "N/A")
    # v3.2.10: Distinguish window vs latest chain_key
    window_chain_key = agg.get("quick_stats", {}).get("chain_key", "N/A")
    latest_chain_key = latest.get("inputs", {}).get("chain_key", "N/A")
    chain_keys = latest.get("chain_keys", [])
    
    metrics = rs.get("metrics", {})
    included_count = metrics.get("included_signals_count", 0)
    excluded_count = metrics.get("excluded_signals_count", 0)
    quality_reasons = rs.get("quality_reasons", [])
    
    print("=" * 60)
    print(f"Rolling Artifacts Inspection v{__version__}")
    print("=" * 60)
    print()
    print(f"run_dir_name:      {run_dir}")
    print(f"run_timestamp:     {run_timestamp}")
    print(f"runs_in_window:    {runs_in_window}")
    print(f"agg_status:        {agg_status}")
    if agg_reasons:
        print(f"agg_reasons:       {agg_reasons}")
    print(f"data_run_rate:     {data_run_rate}")
    print(f"total_net_usdc:    ${total_net_usdc:.2f}" if isinstance(total_net_usdc, (int, float)) else f"total_net_usdc:    {total_net_usdc}")
    print(f"unique_pairs:      {unique_pairs}")
    print(f"unique_routes_cross_dex: {unique_routes_cross_dex}")
    print()
    # v3.2.10: Show both window and latest chain_key
    print(f"window_chain_key:  {window_chain_key}")
    print(f"latest_chain_key:  {latest_chain_key}")
    if len(chain_keys) > 1:
        print(f"chain_keys:        {chain_keys} (MIXED_CHAIN_KEYS)")
    elif chain_keys:
        print(f"chain_keys:        {chain_keys}")
    print()
    print(f"signals_included:  {included_count}")
    print(f"signals_excluded:  {excluded_count}")
    print(f"quality_reasons:   {quality_reasons}")
    print()
    
    if excluded:
        print("Excluded Signals:")
        print("-" * 60)
        for s in excluded:
            print(f"  pair: {s.get('pair')}")
            print(f"    spread_bps: {s.get('spread_bps'):.2f}" if s.get('spread_bps') else "    spread_bps: N/A")
            print(f"    buy: {s.get('buy_dex')} {s.get('buy_pool')}")
            print(f"    sell: {s.get('sell_dex')} {s.get('sell_pool')}")
            print(f"    reasons: {s.get('confidence_reasons')}")
            print()
    else:
        print("No excluded signals.")
    
    print("=" * 60)


def main():
    parser = argparse.ArgumentParser(description="Inspect rolling artifacts")
    parser.add_argument("--excluded", action="store_true", help="Show excluded signals detail")
    parser.add_argument("--json", action="store_true", help="Output as JSON")
    args = parser.parse_args()
    
    artifacts = load_rolling_artifacts()
    
    if not artifacts:
        print("ERROR: No rolling artifacts found.", file=sys.stderr)
        sys.exit(1)
    
    # Get excluded signals from latest run
    run_dir = artifacts.get("run_summary", {}).get("inputs", {}).get("run_dir_name", "")
    excluded = []
    if run_dir:
        excluded = get_excluded_signals(run_dir)
    
    print_summary(artifacts, excluded, as_json=args.json)
    sys.exit(0)


if __name__ == "__main__":
    main()
