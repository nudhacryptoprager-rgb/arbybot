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
    """Regenerate quick_stats from runs (simplified version)."""
    if not runs:
        return {
            "runs_in_window": 0,
            "pass_count": 0,
            "fail_count": 0,
            "no_data_count": 0,
            "total_signals": 0,
            "data_run_rate": 0.0,
            "chain_key": primary_chain,
            "chain_keys": [primary_chain],
        }
    
    pass_count = sum(1 for r in runs if r.get("run_status") == "PASS")
    fail_count = sum(1 for r in runs if r.get("run_status") == "FAIL")
    no_data_count = sum(1 for r in runs if r.get("run_status") == "NO_DATA")
    data_runs = sum(1 for r in runs if r.get("is_data_run", False))
    total_signals = sum(r.get("signals_count", 0) for r in runs)
    
    # Unique pairs and routes
    all_pairs = set()
    all_routes = set()
    for r in runs:
        all_pairs.update(r.get("included_pairs", []))
        all_routes.update(r.get("included_routes", []))
    
    # Total net USDC
    total_net = sum(r.get("net_usdc", 0.0) for r in runs if r.get("is_data_run", False))
    
    return {
        "runs_in_window": len(runs),
        "pass_count": pass_count,
        "fail_count": fail_count,
        "no_data_count": no_data_count,
        "total_signals": total_signals,
        "data_run_rate": data_runs / len(runs) if runs else 0.0,
        "unique_pairs": len(all_pairs),
        "unique_routes_cross_dex": len(all_routes),
        "total_net_usdc": total_net,
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
    
    if not runs_to_remove:
        print("[OK] No cleanup needed - all runs are from primary chain.")
        return 0
    
    # Archive current aggregator
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    archive_path = ROLLING_DIR / f"m4_stability_agg_archive_{ts}_cleanup.json"
    atomic_write_json(archive_path, agg)
    print(f"[ARCHIVED] {archive_path}")
    
    # v3.2.22: Prune old archives (keep last N)
    archive_files = sorted(ROLLING_DIR.glob("m4_stability_agg_archive_*.json"))
    if len(archive_files) > archive_keep:
        to_delete = archive_files[:-archive_keep]
        for old_archive in to_delete:
            old_archive.unlink()
            print(f"[PRUNED] {old_archive.name}")
        print(f"[PRUNE] Kept {archive_keep} most recent archives")
    
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
    
    # v3.2.22: Update _latest.json with ALL KPI fields from aggregator
    # Ensures consistency between _latest.json and m4_stability_agg.json
    if LATEST_PATH.exists():
        with open(LATEST_PATH) as f:
            latest = json.load(f)
        
        # Sync all KPI fields from quick_stats
        latest["runs_in_window"] = quick_stats.get("runs_in_window", len(runs_to_keep))
        latest["data_run_rate"] = quick_stats.get("data_run_rate", 0.0)
        latest["effective_pass_rate"] = quick_stats.get("pass_count", 0) / quick_stats.get("runs_in_window", 1) if quick_stats.get("runs_in_window", 0) > 0 else 0.0
        latest["low_sample_rate"] = quick_stats.get("low_sample_rate", 0.0)
        # net_diversity_rate: unique_routes / runs_in_window (if available)
        if quick_stats.get("unique_routes_cross_dex", 0) > 0 and quick_stats.get("runs_in_window", 0) > 0:
            latest["net_diversity_rate"] = quick_stats.get("unique_routes_cross_dex", 0) / quick_stats.get("runs_in_window", 1)
        latest["quick_stats"] = quick_stats
        
        # Clear MIXED_CHAIN_KEYS warning if applicable
        agg_reasons = latest.get("agg_reasons", [])
        # Filter out MIXED_CHAIN_KEYS warnings
        agg_reasons = [r for r in agg_reasons if not r.startswith("MIXED_CHAIN_KEYS")]
        latest["agg_reasons"] = agg_reasons
        
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
