# PATH: scripts/smoke_test.py
"""
SMOKE test runner script.

Runs a single scan cycle and verifies all artifacts are created correctly.
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def run_smoke_test(output_dir: Path, cycles: int = 1) -> bool:
    """
    Run SMOKE test and verify artifacts.
    
    Returns:
        True if all checks pass
    """
    from strategy.jobs.run_scan import run_scanner
    
    print(f"Running SMOKE test: {cycles} cycle(s)")
    print(f"Output directory: {output_dir}")
    print("-" * 50)
    
    # Run scanner
    run_scanner(cycles=cycles, output_dir=output_dir)
    
    # Verify artifacts
    print("\n" + "-" * 50)
    print("Artifact verification:")
    
    all_ok = True
    
    # Check scan.log
    scan_log = output_dir / "scan.log"
    if scan_log.exists():
        print(f"  [OK] scan.log ({scan_log.stat().st_size} bytes)")
        
        # Check for crashes
        with open(scan_log) as f:
            content = f.read()
        
        crash_indicators = [
            "Traceback",
            "ValueError: Unknown format code",
            "TypeError: Logger._log() got an unexpected keyword argument",
        ]
        
        for indicator in crash_indicators:
            if indicator in content:
                print(f"  [FAIL] Crash detected: {indicator[:50]}...")
                all_ok = False
    else:
        print("  [FAIL] scan.log not found")
        all_ok = False
    
    # Check snapshots
    snapshots_dir = output_dir / "snapshots"
    if snapshots_dir.exists():
        snapshot_files = list(snapshots_dir.glob("scan_*.json"))
        if snapshot_files:
            print(f"  [OK] {len(snapshot_files)} snapshot(s)")
        else:
            print("  [WARN] No snapshot files")
    else:
        print("  [WARN] snapshots/ directory not found")
    
    # Check reports
    reports_dir = output_dir / "reports"
    if reports_dir.exists():
        truth_reports = list(reports_dir.glob("truth_report_*.json"))
        reject_histograms = list(reports_dir.glob("reject_histogram_*.json"))
        
        if truth_reports:
            print(f"  [OK] {len(truth_reports)} truth report(s)")
            
            # Validate truth report structure
            with open(truth_reports[0]) as f:
                report = json.load(f)
            
            if "schema_version" in report:
                print(f"       Schema version: {report['schema_version']}")
            
            # Check RPC consistency
            if "health" in report:
                rpc_total = report["health"].get("rpc_total_requests", 0)
                rpc_failed = report["health"].get("rpc_failed_requests", 0)
                print(f"       RPC: {rpc_total} total, {rpc_failed} failed")
        else:
            print("  [FAIL] No truth report files")
            all_ok = False
        
        if reject_histograms:
            print(f"  [OK] {len(reject_histograms)} reject histogram(s)")
        else:
            print("  [WARN] No reject histogram files")
    else:
        print("  [FAIL] reports/ directory not found")
        all_ok = False
    
    # Check paper_trades.jsonl
    paper_trades = output_dir / "paper_trades.jsonl"
    if paper_trades.exists():
        with open(paper_trades) as f:
            lines = f.readlines()
        print(f"  [OK] paper_trades.jsonl ({len(lines)} trade(s))")
        
        # Validate format
        if lines:
            try:
                trade = json.loads(lines[0])
                if "spread_id" in trade and "outcome" in trade:
                    print("       Format: Valid JSONL")
                else:
                    print("       Format: Missing required fields")
            except json.JSONDecodeError:
                print("       Format: Invalid JSON")
                all_ok = False
    else:
        print("  [INFO] paper_trades.jsonl not created (no WOULD_EXECUTE trades)")
    
    print("-" * 50)
    
    return all_ok


def main():
    parser = argparse.ArgumentParser(description="SMOKE test runner")
    parser.add_argument(
        "--output-dir", "-o",
        type=str,
        default=None,
        help="Output directory (default: auto-generated)"
    )
    parser.add_argument(
        "--cycles", "-c",
        type=int,
        default=1,
        help="Number of cycles (default: 1)"
    )
    
    args = parser.parse_args()
    
    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = Path("data/runs") / f"smoke_{timestamp}"
    
    success = run_smoke_test(output_dir, args.cycles)
    
    if success:
        print("\nSMOKE TEST PASSED")
        sys.exit(0)
    else:
        print("\nSMOKE TEST FAILED")
        sys.exit(1)


if __name__ == "__main__":
    main()