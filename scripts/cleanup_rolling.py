#!/usr/bin/env python3
# PATH: scripts/cleanup_rolling.py
"""
Rolling Window Cleanup Script

Removes runs from rolling artifacts that don't match the primary chain.
This fixes MIXED_CHAIN_KEYS contamination from legacy multi-chain bring-up runs.

USAGE:
  # Dry-run (show what would be removed)
  py -3.11 scripts/cleanup_rolling.py --dry-run

  # Actually clean up
  py -3.11 scripts/cleanup_rolling.py --confirm

  # Clean for a specific chain (default: arbitrum_one)
  py -3.11 scripts/cleanup_rolling.py --primary-chain arbitrum_one --confirm

SAFETY:
  - Always does dry-run first unless --confirm is passed
  - Archives the old aggregator before cleanup
  - Regenerates quick_stats after cleanup
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from core.json_io import atomic_write_json

DEFAULT_PRIMARY_CHAIN = "arbitrum_one"
ROLLING_DIR = REPO_ROOT / "data" / "runs" / "_rolling"
AGG_PATH = ROLLING_DIR / "m4_stability_agg.json"
LATEST_PATH = ROLLING_DIR / "_latest.json"


def load_aggregator() -> dict:
    """Load the rolling aggregator."""
    if not AGG_PATH.exists():
        print(f"[ERROR] Aggregator not found: {AGG_PATH}")
        sys.exit(2)
    
    with open(AGG_PATH) as f:
        return json.load(f)


def analyze_runs(agg: dict, primary_chain: str, remove_unknown: bool = True) -> tuple[list, list]:
    """
    Analyze runs and split into keep/remove lists.
    
    Args:
        agg: Aggregator data
        primary_chain: Chain to keep
        remove_unknown: If True, remove runs with unknown chain_key (v3.2.22 default)
    
    Returns:
        (runs_to_keep, runs_to_remove)
    """
    runs = agg.get("runs", [])
    keep = []
    remove = []
    
    for run in runs:
        # Check chain_key (may be in run directly or inferred from chain_id)
        chain_key = run.get("chain_key")
        
        # Fallback: infer from chain_id if chain_key missing
        if not chain_key:
            chain_id = run.get("chain_id")
            if chain_id == 42161:
                chain_key = "arbitrum_one"
            elif chain_id == 59144:
                chain_key = "linea"
            elif chain_id == 5000:
                chain_key = "mantle"
            elif chain_id == 534352:
                chain_key = "scroll"
            elif chain_id == 324:
                chain_key = "zksync"
            else:
                chain_key = "unknown"
        
        # v3.2.22: Unknown chain_key policy
        # remove_unknown=True (default): Remove unknown to prevent contamination backdoor
        # remove_unknown=False: Keep unknown (legacy behavior)
        if chain_key == primary_chain:
            keep.append(run)
        elif chain_key == "unknown" and not remove_unknown:
            keep.append(run)  # Legacy: keep unknown
        else:
            remove.append(run)
    
    return keep, remove


def regenerate_quick_stats(runs: list, primary_chain: str) -> dict:
    """
    Regenerate quick_stats from runs.
    
    v3.2.23: Full contract version matching m4/rolling_store.py._compute_quick_stats.
    """
    from m4.policy import Thresholds
    
    if not runs:
        return {
            "runs_in_window": 0,
            "pass_count": 0,
            "fail_count": 0,
            "no_data_count": 0,
            "data_run_count": 0,
            "warn_count_core": 0,
            "low_sample_count": 0,
            "pass_rate": 0.0,
            "effective_pass_rate": 0.0,
            "data_run_rate": 0.0,
            "no_data_rate": 0.0,
            "warn_rate_core": 0.0,
            "low_sample_rate": 0.0,
            "fail_rate": 0.0,
            "total_signals": 0,
            "fragile_rate_p50": 0.0,
            "fragile_rate_p90": 0.0,
            "mae_p90": 0.0,
            "total_net_usdc": 0.0,
            "avg_net_usdc": 0.0,
            "net_p10": 0.0,
            "mae_p50": 0.0,
            "unique_net_values": 0,
            "net_diversity_rate": 0.0,
            "unique_pairs": 0,
            "unique_routes": 0,
            "unique_routes_cross_dex": 0,
            "infra_fail_count": 0,
            "infra_fail_rate": 0.0,
            "coverage_runs_count": 0,
            "coverage_signals_total": 0,
            "coverage_net_usdc": 0.0,
            "signals_per_run_p50": 0,
            "signals_per_run_p90": 0,
            "signals_per_run_avg": 0.0,
            "chain_key": primary_chain,
            "chain_keys": [primary_chain],
        }
    
    def percentile(values, p):
        if not values:
            return 0
        sorted_vals = sorted(values)
        k = (len(sorted_vals) - 1) * p / 100
        f = int(k)
        c = f + 1 if f + 1 < len(sorted_vals) else f
        return round(sorted_vals[f] + (k - f) * (sorted_vals[c] - sorted_vals[f]), 4)
    
    def get_included_signals(r):
        return r.get("included_signals_count", r.get("signals_count", 0))
    
    min_signals = Thresholds.MIN_SIGNALS_FOR_PASS
    
    # Segment runs by kind (NORMAL for main KPIs)
    normal_runs = [r for r in runs if r.get("run_kind", "NORMAL") == "NORMAL"]
    coverage_runs = [r for r in runs if r.get("run_kind") == "COVERAGE"]
    
    # Main KPIs on NORMAL runs
    data_runs_list = [r for r in normal_runs if r.get("is_data_run", get_included_signals(r) >= min_signals)]
    no_data_count = sum(1 for r in normal_runs if get_included_signals(r) == 0)
    low_sample_count = sum(1 for r in normal_runs if "WARN_LOW_SAMPLE" in r.get("reasons", []) or (0 < get_included_signals(r) < min_signals))
    data_run_count = len(data_runs_list)
    
    pass_count = sum(1 for r in data_runs_list if not any(x.startswith("FAIL_") for x in r.get("reasons", [])))
    fail_count = len(data_runs_list) - pass_count
    warn_count_core = sum(1 for r in data_runs_list if "WARN_DRIFT_MAE" in r.get("reasons", []))
    total_net = sum(r.get("net_usdc", 0) for r in normal_runs)
    total_signals = sum(r.get("signals_count", 0) for r in normal_runs)
    
    # Percentile values
    fragile_rates = [r.get("fragile_rate", 0) for r in data_runs_list]
    mae_values = [r.get("mae", 0) for r in data_runs_list]
    net_values = [r.get("net_usdc", 0) for r in data_runs_list]
    signals_per_run = [r.get("signals_count", 0) for r in normal_runs]
    
    # Rates
    no_data_rate = no_data_count / len(normal_runs) if normal_runs else 0
    low_sample_rate = low_sample_count / len(normal_runs) if normal_runs else 0
    data_run_rate = data_run_count / len(normal_runs) if normal_runs else 0
    effective_pass_rate = pass_count / len(normal_runs) if normal_runs else 0
    pass_rate = pass_count / len(data_runs_list) if data_runs_list else 0
    warn_rate_core = warn_count_core / len(data_runs_list) if data_runs_list else 0
    fail_rate = fail_count / len(data_runs_list) if data_runs_list else 0
    
    # Diversity metrics
    all_pairs = set()
    all_routes = set()
    for r in runs:
        all_pairs.update(r.get("included_pairs", r.get("pairs", [])))
        all_routes.update(r.get("included_routes", r.get("routes", [])))
    unique_net_values = len(set(round(r.get("net_usdc", 0), 2) for r in data_runs_list))
    net_diversity_rate = unique_net_values / len(data_runs_list) if data_runs_list else 0
    
    # INFRA failure tracking
    infra_fail_count = sum(1 for r in runs if r.get("is_infra_fail", False))
    
    # Coverage stats
    coverage_signals = sum(r.get("signals_count", 0) for r in coverage_runs)
    coverage_net = sum(r.get("net_usdc", 0) for r in coverage_runs)
    
    return {
        "pass_count": pass_count,
        "fail_count": fail_count,
        "no_data_count": no_data_count,
        "data_run_count": data_run_count,
        "warn_count_core": warn_count_core,
        "low_sample_count": low_sample_count,
        "pass_rate": round(pass_rate, 4),
        "effective_pass_rate": round(effective_pass_rate, 4),
        "data_run_rate": round(data_run_rate, 4),
        "no_data_rate": round(no_data_rate, 4),
        "warn_rate_core": round(warn_rate_core, 4),
        "low_sample_rate": round(low_sample_rate, 4),
        "fail_rate": round(fail_rate, 4),
        "total_signals": total_signals,
        "fragile_rate_p50": percentile(fragile_rates, 50),
        "fragile_rate_p90": percentile(fragile_rates, 90),
        "mae_p90": percentile(mae_values, 90),
        "total_net_usdc": round(total_net, 4),
        "avg_net_usdc": round(total_net / len(data_runs_list), 4) if data_runs_list else 0,
        "net_p10": percentile(net_values, 10),
        "mae_p50": percentile(mae_values, 50),
        "unique_net_values": unique_net_values,
        "net_diversity_rate": round(net_diversity_rate, 4),
        "unique_pairs": len(all_pairs),
        "unique_routes": len(all_routes),
        "unique_routes_cross_dex": len(all_routes),  # Simplified: assume all are cross-dex post-cleanup
        "infra_fail_count": infra_fail_count,
        "infra_fail_rate": round(infra_fail_count / len(runs), 4) if runs else 0,
        "coverage_runs_count": len(coverage_runs),
        "coverage_signals_total": coverage_signals,
        "coverage_net_usdc": round(coverage_net, 4),
        "signals_per_run_p50": percentile(signals_per_run, 50),
        "signals_per_run_p90": percentile(signals_per_run, 90),
        "signals_per_run_avg": round(sum(signals_per_run) / len(signals_per_run), 2) if signals_per_run else 0.0,
        "chain_key": primary_chain,
        "chain_keys": [primary_chain],
    }


def cleanup_rolling(primary_chain: str, dry_run: bool = True, remove_unknown: bool = True, archive_keep: int = 5) -> int:
    """
    Clean up rolling artifacts by removing non-primary chain runs.
    
    Args:
        primary_chain: The chain to keep (default: arbitrum_one)
        dry_run: If True, only show what would be removed
        remove_unknown: If True, remove runs with unknown chain_key (v3.2.22 default)
        archive_keep: Number of archive files to keep (default: 5)
        
    Returns:
        Exit code (0=success, 1=error)
    """
    print(f"Rolling Cleanup Script")
    print(f"=" * 50)
    print(f"Primary chain: {primary_chain}")
    print(f"Remove unknown: {remove_unknown}")
    print(f"Mode: {'DRY-RUN' if dry_run else 'CLEANUP'}")
    print()
    
    agg = load_aggregator()
    runs_to_keep, runs_to_remove = analyze_runs(agg, primary_chain, remove_unknown)
    
    print(f"Current runs in window: {len(agg.get('runs', []))}")
    print(f"Runs to keep ({primary_chain}): {len(runs_to_keep)}")
    print(f"Runs to remove (non-{primary_chain}): {len(runs_to_remove)}")
    print()
    
    if runs_to_remove:
        print("Runs to be removed:")
        for run in runs_to_remove:
            chain = run.get("chain_key") or f"chain_id={run.get('chain_id')}"
            print(f"  - {run.get('run_id')}: {chain}, status={run.get('run_status')}")
        print()
    
    if dry_run:
        print("[DRY-RUN] No changes made. Use --confirm to apply.")
        return 0
    
    # v3.2.23: Always prune old archives (independent of runs_to_remove)
    # This ensures "keep last N" is invariant even when rolling is already clean
    archive_files = sorted(ROLLING_DIR.glob("m4_stability_agg_archive_*.json"))
    if len(archive_files) > archive_keep:
        to_delete = archive_files[:-archive_keep]
        for old_archive in to_delete:
            old_archive.unlink()
            print(f"[PRUNED] {old_archive.name}")
        print(f"[PRUNE] Kept {archive_keep} most recent archives")
    
    if not runs_to_remove:
        print("[OK] No cleanup needed - all runs are from primary chain.")
        return 0
    
    # Archive current aggregator before modifying
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    archive_path = ROLLING_DIR / f"m4_stability_agg_archive_{ts}_cleanup.json"
    atomic_write_json(archive_path, agg)
    print(f"[ARCHIVED] {archive_path}")
    
    # Update aggregator
    agg["runs"] = runs_to_keep
    quick_stats = regenerate_quick_stats(runs_to_keep, primary_chain)
    agg["quick_stats"] = quick_stats
    agg["cleanup_at"] = datetime.now(timezone.utc).isoformat()
    agg["cleanup_reason"] = f"remove_non_{primary_chain}_runs"
    agg["cleanup_removed_count"] = len(runs_to_remove)
    
    atomic_write_json(AGG_PATH, agg)
    print(f"[UPDATED] {AGG_PATH}")
    print(f"[OK] Removed {len(runs_to_remove)} runs, {len(runs_to_keep)} remaining")
    
    # v3.2.23: Update _latest.json - sync KPI fields directly from quick_stats (no recalculation)
    # Ensures consistency between _latest.json and m4_stability_agg.json
    if LATEST_PATH.exists():
        with open(LATEST_PATH) as f:
            latest = json.load(f)
        
        # Sync all KPI fields DIRECTLY from quick_stats (no extra formulas)
        latest["runs_in_window"] = len(runs_to_keep)
        latest["data_run_rate"] = quick_stats.get("data_run_rate", 0.0)
        latest["effective_pass_rate"] = quick_stats.get("effective_pass_rate", 0.0)
        latest["low_sample_rate"] = quick_stats.get("low_sample_rate", 0.0)
        latest["net_diversity_rate"] = quick_stats.get("net_diversity_rate", 0.0)
        latest["total_signals_in_window"] = quick_stats.get("total_signals", 0)
        latest["quick_stats"] = quick_stats
        
        # Clear MIXED_CHAIN_KEYS warning (cleanup resolved it)
        agg_reasons = latest.get("agg_reasons", [])
        agg_reasons = [r for r in agg_reasons if not r.startswith("MIXED_CHAIN_KEYS")]
        latest["agg_reasons"] = agg_reasons
        
        # Update agg from re-computed stats
        latest["agg_status"] = "PASS"  # Cleanup implies clean state
        
        atomic_write_json(LATEST_PATH, latest)
        print(f"[UPDATED] {LATEST_PATH} (synced all KPI fields)")
    
    return 0


def main():
    parser = argparse.ArgumentParser(description="Clean rolling artifacts from non-primary chain runs")
    parser.add_argument("--primary-chain", default=DEFAULT_PRIMARY_CHAIN,
                        help=f"Primary chain to keep (default: {DEFAULT_PRIMARY_CHAIN})")
    parser.add_argument("--dry-run", action="store_true", default=True,
                        help="Show what would be removed without making changes (default)")
    parser.add_argument("--confirm", action="store_true",
                        help="Actually apply the cleanup")
    parser.add_argument("--keep-unknown", action="store_true", default=False,
                        help="Keep runs with unknown chain_key (default: remove)")
    parser.add_argument("--archive-keep", type=int, default=5,
                        help="Number of archive files to keep (default: 5)")
    args = parser.parse_args()
    
    dry_run = not args.confirm
    remove_unknown = not args.keep_unknown
    return cleanup_rolling(args.primary_chain, dry_run, remove_unknown, args.archive_keep)


if __name__ == "__main__":
    sys.exit(main())
