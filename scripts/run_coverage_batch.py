#!/usr/bin/env python
"""
Coverage Run Batch - Official Coverage Mode

Generate high-quality scans with >= 5 signals for aggregator statistics.
This script runs multiple scans and processes them through M4 gate.

Modes:
    Standard:      --count N scans, each processed independently
    Coverage-first: --min-signals-target N --max-seconds T
                   Collect until N signals gathered or T seconds elapsed

Usage:
    python scripts/run_coverage_batch.py --count 5 --profile profit
    python scripts/run_coverage_batch.py --count 10 --delay 10
    python scripts/run_coverage_batch.py --min-signals-target 10 --max-seconds 300
    
Options:
    --count N               Number of scans to run (default: 3)
    --delay N               Delay between scans in seconds (default: 5)
    --profile P             Profile for M4 gate: smoke or profit (default: profit)
    --config PATH           Config file path (default: config/real_test_coverage.yaml)
    --skip-gate             Skip M4 gate processing
    --min-signals-target N  Coverage-first: collect until N signals (default: 0 = disabled)
    --max-seconds T         Coverage-first: timeout in seconds (default: 600)
"""

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

# Add project root to path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

import logging
logging.basicConfig(level=logging.WARNING)


def run_coverage_batch(
    count: int = 3,
    delay: int = 5,
    profile: str = "profit",
    config_path: str = "config/real_test_coverage.yaml",
    skip_gate: bool = False,
    min_signals_target: int = 0,
    max_seconds: int = 600,
) -> dict:
    """
    Run a batch of coverage scans and process through M4 gate.
    
    Modes:
        Standard (count > 0, min_signals_target == 0):
            Run exactly 'count' scans
        Coverage-first (min_signals_target > 0):
            Keep scanning until total signals >= min_signals_target or timeout
    
    Args:
        count: Number of scans to run (standard mode)
        delay: Delay between scans in seconds
        profile: M4 gate profile (smoke or profit)
        config_path: Config file for scanner
        skip_gate: If True, skip M4 gate processing
        min_signals_target: Coverage-first target (0 = disabled, use count)
        max_seconds: Coverage-first timeout
        
    Returns:
        Summary dict with run results
    """
    from strategy.jobs.run_scan import run_scanner, ScannerMode
    from m4.gates import run_online_gate
    import json
    
    results = {
        "scans_completed": 0,
        "scans_failed": 0,
        "gate_passed": 0,
        "gate_failed": 0,
        "gate_no_data": 0,
        "total_signals": 0,
        "run_dirs": [],
        "mode": "coverage-first" if min_signals_target > 0 else "standard",
    }
    
    # Determine mode
    coverage_first = min_signals_target > 0
    start_time = time.time()
    
    print("=" * 60)
    if coverage_first:
        print(f"COVERAGE-FIRST BATCH: target={min_signals_target} signals, timeout={max_seconds}s")
    else:
        print(f"STANDARD BATCH: {count} scans, profile={profile}")
    print(f"Config: {config_path}")
    print("=" * 60)
    
    iteration = 0
    while True:
        iteration += 1
        
        # Check termination conditions
        if coverage_first:
            elapsed = time.time() - start_time
            if elapsed >= max_seconds:
                print(f"\n[TIMEOUT] {elapsed:.0f}s elapsed >= {max_seconds}s limit")
                break
            if results["total_signals"] >= min_signals_target:
                print(f"\n[TARGET] {results['total_signals']} signals >= {min_signals_target} target")
                break
            remaining = max_seconds - elapsed
            print(f"\n[{iteration}] Signals: {results['total_signals']}/{min_signals_target}, {remaining:.0f}s remaining")
        else:
            if iteration > count:
                break
            print(f"\n[{iteration}/{count}] Scanning...")
        
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        run_dir = REPO_ROOT / f'data/runs/coverage_run_{ts}'
        
        try:
            run_scanner(
                mode=ScannerMode.REAL,
                config_path=config_path,
                cycles=1,
                output_dir=str(run_dir)
            )
            results["scans_completed"] += 1
            results["run_dirs"].append(str(run_dir))
            
            # Count signals from truth_report
            truth_path = run_dir / "reports" / f"truth_report_{ts}.json"
            if not truth_path.exists():
                # Try to find any truth_report
                report_files = list((run_dir / "reports").glob("truth_report_*.json"))
                truth_path = report_files[0] if report_files else None
            
            if truth_path and truth_path.exists():
                with open(truth_path) as f:
                    truth_data = json.load(f)
                signals_in_run = len(truth_data.get("spread_signals", []))
                results["total_signals"] += signals_in_run
                print(f"[{iteration}] +{signals_in_run} signals (total: {results['total_signals']})")
            
            # Process through M4 gate
            if not skip_gate:
                exit_code = run_online_gate(
                    run_dir=run_dir,
                    profile=profile,
                    artifact_mode="rolling",
                )
                if exit_code == 0:
                    results["gate_passed"] += 1
                elif exit_code == 2:
                    results["gate_no_data"] += 1
                else:
                    results["gate_failed"] += 1
                    
        except Exception as e:
            results["scans_failed"] += 1
            print(f"[{iteration}] FAILED: {e}")
        
        # Delay between scans (if not last iteration and not coverage-first at target)
        should_delay = not coverage_first or results["total_signals"] < min_signals_target
        if should_delay and delay > 0:
            time.sleep(delay)
    
    elapsed = time.time() - start_time
    print("\n" + "=" * 60)
    print("BATCH COMPLETE")
    print(f"  Mode: {results['mode']}")
    print(f"  Scans: {results['scans_completed']} completed, {results['scans_failed']} failed")
    print(f"  Signals: {results['total_signals']} total")
    if not skip_gate:
        print(f"  Gate: {results['gate_passed']} PASS, {results['gate_failed']} FAIL, {results['gate_no_data']} NO_DATA")
    print(f"  Time: {elapsed:.1f}s")
    print("=" * 60)
    
    return results


def main():
    parser = argparse.ArgumentParser(description="Coverage Run Batch - High-quality scans for aggregator")
    parser.add_argument("--count", type=int, default=3, help="Number of scans to run (standard mode)")
    parser.add_argument("--delay", type=int, default=5, help="Delay between scans (seconds)")
    parser.add_argument("--profile", default="profit", choices=["smoke", "profit"], help="M4 gate profile")
    parser.add_argument("--config", default="config/real_test_coverage.yaml", help="Scanner config path")
    parser.add_argument("--skip-gate", action="store_true", help="Skip M4 gate processing")
    parser.add_argument("--min-signals-target", type=int, default=0,
                        help="Coverage-first: collect until N signals (0 = disabled, use --count)")
    parser.add_argument("--max-seconds", type=int, default=600,
                        help="Coverage-first: timeout in seconds (default: 600)")
    
    args = parser.parse_args()
    
    results = run_coverage_batch(
        count=args.count,
        delay=args.delay,
        profile=args.profile,
        config_path=args.config,
        skip_gate=args.skip_gate,
        min_signals_target=args.min_signals_target,
        max_seconds=args.max_seconds,
    )
    
    # Exit with failure if any scans failed
    if results["scans_failed"] > 0:
        sys.exit(1)
    # Exit 2 if coverage-first and target not met
    if args.min_signals_target > 0 and results["total_signals"] < args.min_signals_target:
        print(f"[WARN] Target not met: {results['total_signals']}/{args.min_signals_target} signals")
        sys.exit(2)
    sys.exit(0)


if __name__ == "__main__":
    main()
