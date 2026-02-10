#!/usr/bin/env python
"""
Coverage Run Batch - Official Coverage Mode

Generate high-quality scans with >= 5 signals for aggregator statistics.
This script runs multiple scans and processes them through M4 gate.

Usage:
    python scripts/run_coverage_batch.py --count 5 --profile profit
    python scripts/run_coverage_batch.py --count 10 --delay 10
    
Options:
    --count N       Number of scans to run (default: 3)
    --delay N       Delay between scans in seconds (default: 5)
    --profile P     Profile for M4 gate: smoke or profit (default: profit)
    --config PATH   Config file path (default: config/real_test_coverage.yaml)
    --skip-gate     Skip M4 gate processing (only run scans)
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
) -> dict:
    """
    Run a batch of coverage scans and process through M4 gate.
    
    Args:
        count: Number of scans to run
        delay: Delay between scans in seconds
        profile: M4 gate profile (smoke or profit)
        config_path: Config file for scanner
        skip_gate: If True, skip M4 gate processing
        
    Returns:
        Summary dict with run results
    """
    from strategy.jobs.run_scan import run_scanner, ScannerMode
    from m4.gates import run_online_gate
    
    results = {
        "scans_completed": 0,
        "scans_failed": 0,
        "gate_passed": 0,
        "gate_failed": 0,
        "run_dirs": [],
    }
    
    print("=" * 60)
    print(f"COVERAGE BATCH: {count} scans, profile={profile}")
    print(f"Config: {config_path}")
    print("=" * 60)
    
    for i in range(count):
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        run_dir = REPO_ROOT / f'data/runs/coverage_run_{ts}'
        
        print(f"\n[{i+1}/{count}] Scanning -> {run_dir.name}")
        
        try:
            run_scanner(
                mode=ScannerMode.REAL,
                config_path=config_path,
                cycles=1,
                output_dir=str(run_dir)
            )
            results["scans_completed"] += 1
            results["run_dirs"].append(str(run_dir))
            print(f"[{i+1}/{count}] Scan complete")
            
            # Process through M4 gate
            if not skip_gate:
                print(f"[{i+1}/{count}] Processing M4 gate...")
                exit_code = run_online_gate(
                    run_dir=run_dir,
                    profile=profile,
                    artifact_mode="rolling",
                )
                if exit_code == 0:
                    results["gate_passed"] += 1
                else:
                    results["gate_failed"] += 1
                    print(f"[{i+1}/{count}] Gate exit_code={exit_code}")
                    
        except Exception as e:
            results["scans_failed"] += 1
            print(f"[{i+1}/{count}] FAILED: {e}")
        
        if i < count - 1:
            print(f"[{i+1}/{count}] Waiting {delay}s...")
            time.sleep(delay)
    
    print("\n" + "=" * 60)
    print("BATCH COMPLETE")
    print(f"  Scans: {results['scans_completed']}/{count} completed")
    if not skip_gate:
        print(f"  Gate: {results['gate_passed']} passed, {results['gate_failed']} failed")
    print("=" * 60)
    
    return results


def main():
    parser = argparse.ArgumentParser(description="Coverage Run Batch - High-quality scans for aggregator")
    parser.add_argument("--count", type=int, default=3, help="Number of scans to run")
    parser.add_argument("--delay", type=int, default=5, help="Delay between scans (seconds)")
    parser.add_argument("--profile", default="profit", choices=["smoke", "profit"], help="M4 gate profile")
    parser.add_argument("--config", default="config/real_test_coverage.yaml", help="Scanner config path")
    parser.add_argument("--skip-gate", action="store_true", help="Skip M4 gate processing")
    
    args = parser.parse_args()
    
    results = run_coverage_batch(
        count=args.count,
        delay=args.delay,
        profile=args.profile,
        config_path=args.config,
        skip_gate=args.skip_gate,
    )
    
    # Exit with failure if any scans failed
    if results["scans_failed"] > 0:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
