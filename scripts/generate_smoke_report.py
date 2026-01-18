# PATH: scripts/generate_smoke_report.py
#!/usr/bin/env python
"""
Generate a summary report from SMOKE run artifacts.
"""

import json
import sys
from datetime import datetime
from pathlib import Path


def generate_report(run_dir: Path) -> dict:
    """Generate summary report from run artifacts."""
    report = {
        "run_dir": str(run_dir),
        "timestamp": datetime.now().isoformat(),
        "status": "UNKNOWN",
        "artifacts": {},
        "issues": [],
    }
    
    # Check scan.log
    scan_log = run_dir / "scan.log"
    if scan_log.exists():
        report["artifacts"]["scan_log"] = {
            "exists": True,
            "size_bytes": scan_log.stat().st_size,
        }
        
        # Check for crashes
        with open(scan_log) as f:
            content = f.read()
        
        crash_patterns = [
            "Traceback",
            "ValueError: Unknown format code",
            "TypeError: Logger._log() got an unexpected keyword argument",
        ]
        
        for pattern in crash_patterns:
            if pattern in content:
                report["issues"].append(f"Crash detected: {pattern[:50]}")
    else:
        report["artifacts"]["scan_log"] = {"exists": False}
        report["issues"].append("scan.log not found")
    
    # Check truth report
    reports_dir = run_dir / "reports"
    if reports_dir.exists():
        truth_reports = list(reports_dir.glob("truth_report_*.json"))
        report["artifacts"]["truth_reports"] = len(truth_reports)
        
        if truth_reports:
            with open(truth_reports[0]) as f:
                truth = json.load(f)
            
            report["truth_report_summary"] = {
                "schema_version": truth.get("schema_version"),
                "mode": truth.get("mode"),
                "rpc_total_requests": truth.get("health", {}).get("rpc_total_requests"),
                "rpc_failed_requests": truth.get("health", {}).get("rpc_failed_requests"),
                "spreads_total": truth.get("stats", {}).get("spread_ids_total"),
                "spreads_executable": truth.get("stats", {}).get("spread_ids_executable"),
            }
            
            # Check RPC consistency
            health = truth.get("health", {})
            rpc_total = health.get("rpc_total_requests", 0)
            top_rejects = health.get("top_reject_reasons", [])
            
            infra_errors = sum(count for reason, count in top_rejects if reason == "INFRA_RPC_ERROR")
            
            if infra_errors > 0 and rpc_total == 0:
                report["issues"].append(f"RPC inconsistency: INFRA_RPC_ERROR={infra_errors} but rpc_total=0")
        
        reject_histograms = list(reports_dir.glob("reject_histogram_*.json"))
        report["artifacts"]["reject_histograms"] = len(reject_histograms)
    else:
        report["artifacts"]["reports_dir"] = {"exists": False}
        report["issues"].append("reports/ directory not found")
    
    # Check paper_trades
    paper_trades = run_dir / "paper_trades.jsonl"
    if paper_trades.exists():
        with open(paper_trades) as f:
            lines = f.readlines()
        report["artifacts"]["paper_trades"] = {
            "exists": True,
            "trade_count": len(lines),
        }
    else:
        report["artifacts"]["paper_trades"] = {
            "exists": False,
            "note": "No WOULD_EXECUTE trades",
        }
    
    # Determine status
    if report["issues"]:
        report["status"] = "FAILED"
    else:
        report["status"] = "PASSED"
    
    return report


def main():
    if len(sys.argv) < 2:
        print("Usage: python generate_smoke_report.py <run_dir>")
        sys.exit(1)
    
    run_dir = Path(sys.argv[1])
    if not run_dir.exists():
        print(f"Error: {run_dir} does not exist")
        sys.exit(1)
    
    report = generate_report(run_dir)
    
    print(json.dumps(report, indent=2))
    
    sys.exit(0 if report["status"] == "PASSED" else 1)


if __name__ == "__main__":
    main()