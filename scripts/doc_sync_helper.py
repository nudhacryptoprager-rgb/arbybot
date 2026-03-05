#!/usr/bin/env python3
"""
Doc-Sync Helper for ARBY3

Extracts key metrics from rolling artifacts and outputs markdown blocks
for DEV_REPORT and Status files.

Usage:
    py -3.11 scripts/doc_sync_helper.py --format dev_report
    py -3.11 scripts/doc_sync_helper.py --format status_m4
    py -3.11 scripts/doc_sync_helper.py --format all
"""

import argparse
import json
from pathlib import Path
from datetime import datetime

REPO_ROOT = Path(__file__).resolve().parent.parent
ROLLING_DIR = REPO_ROOT / "data" / "runs" / "_rolling"


def load_rolling_artifacts():
    """Load all three rolling artifacts."""
    latest_path = ROLLING_DIR / "_latest.json"
    summary_path = ROLLING_DIR / "run_summary_latest.json"
    agg_path = ROLLING_DIR / "m4_stability_agg.json"
    
    latest = json.loads(latest_path.read_text(encoding="utf-8")) if latest_path.exists() else {}
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    agg = json.loads(agg_path.read_text(encoding="utf-8")) if agg_path.exists() else {}
    
    return latest, summary, agg


def generate_dev_report_block(latest: dict, summary: dict, agg: dict) -> str:
    """Generate DEV_REPORT_LATEST.md evidence block."""
    rc = latest.get("run_context", {})
    qs = agg.get("quick_stats", {})
    metrics = summary.get("metrics", {})
    roundtrip = metrics.get("roundtrip", {})
    
    run_dir = rc.get("run_dir_name", "N/A")
    run_ts = rc.get("run_timestamp", "N/A")
    runs_in_window = agg.get("runs_in_window", 0)
    agg_status = agg.get("agg_status", "N/A")
    unique_pairs = qs.get("unique_pairs", 0)
    total_net_usdc = qs.get("total_net_usdc", 0)
    
    run_quality_status = latest.get("run_quality_status", "N/A")
    run_quality_warnings = latest.get("run_quality_warnings", [])
    
    profit_is_diagnostic = metrics.get("profit_is_diagnostic", True)
    profit_truth_available = metrics.get("profit_truth_available", False)
    profit_truth_source = metrics.get("profit_truth_source", "N/A")
    
    block = f"""## 0) Meta
timestamp_utc: {run_ts}
run_id: data/runs/{run_dir}
mode: ONLINE
artifact_mode: rolling
config: config/real_minimal.yaml (arbitrum_one, run_kind=NORMAL)
code_identity:
  primary: ts:{run_ts}
  dirty: false
  desc: v3.2.30 roundtrip metrics added to rolling

## 4) Key Results (числа з артефактів)

_latest.json:
  schema_version: {latest.get('schema_version', 'N/A')}
  run_status: {latest.get('run_status', 'N/A')}
  run_dir_name: {run_dir}
  run_timestamp: {run_ts}
  run_quality_status: {run_quality_status}
  run_quality_warnings: {run_quality_warnings}
  metrics:
    signals_count: {metrics.get('signals_count', 0)}
    signals_included: {metrics.get('included_signals_count', 0)}
    signals_excluded: {metrics.get('excluded_signals_count', 0)}
    total_net_usdc: {round(metrics.get('total_net_usdc', 0), 2)}
    roundtrip:
      evaluated_count: {roundtrip.get('evaluated_count', 0)}
      profitable_count: {roundtrip.get('profitable_count', 0)}
      best_net_pnl_bps: {roundtrip.get('best_net_pnl_bps')}
  rolling:
    runs_in_window: {runs_in_window}
    quality_warnings: {agg.get('quality_warnings', [])}

m4_stability_agg.json:
  agg_status: {agg_status}
  runs_in_window: {runs_in_window}
  unique_pairs: {unique_pairs}
  window_chain_key: {qs.get('chain_key', 'N/A')}
  quality_warnings: {agg.get('quality_warnings', [])}
  total_net_usdc: {total_net_usdc}
  roundtrip_stats:
    runs_evaluated: {qs.get('roundtrip_runs_evaluated', 0)}
    runs_profitable: {qs.get('roundtrip_runs_profitable', 0)}
    total_evaluated: {qs.get('roundtrip_total_evaluated', 0)}
    total_profitable: {qs.get('roundtrip_total_profitable', 0)}

profit_truth:
  profit_is_diagnostic: {profit_is_diagnostic}
  profit_truth_available: {profit_truth_available}
  profit_truth_source: {profit_truth_source}
"""
    return block


def generate_status_m4_block(latest: dict, summary: dict, agg: dict) -> str:
    """Generate Status_M4.md evidence block."""
    rc = latest.get("run_context", {})
    qs = agg.get("quick_stats", {})
    metrics = summary.get("metrics", {})
    roundtrip = metrics.get("roundtrip", {})
    
    run_dir = rc.get("run_dir_name", "N/A")
    run_ts = rc.get("run_timestamp", "N/A")
    runs_in_window = agg.get("runs_in_window", 0)
    agg_status = agg.get("agg_status", "N/A")
    
    profit_is_diagnostic = metrics.get("profit_is_diagnostic", True)
    profit_truth_available = metrics.get("profit_truth_available", False)
    
    m42_status = "NOT MET" if roundtrip.get("profitable_count", 0) == 0 else "MET"
    
    block = f"""## M4.2 Progress (roundtrip)

**Status**: **{m42_status}** (`roundtrip.profitable_count={roundtrip.get('profitable_count', 0)}`)
**Evidence runDir**: `{run_dir}`
**Run timestamp**: `{run_ts}`

| Metric | Value | Target |
|--------|-------|--------|
| roundtrip.evaluated_count | {roundtrip.get('evaluated_count', 0)} | >= 1 |
| roundtrip.profitable_count | {roundtrip.get('profitable_count', 0)} | >= 1 |
| profit_is_diagnostic | {profit_is_diagnostic} | False |
| profit_truth_available | {profit_truth_available} | True |
| agg_status | {agg_status} | PASS |
| runs_in_window | {runs_in_window} | >= 100 |

### Aggregate Roundtrip Stats (window)

| Metric | Value |
|--------|-------|
| roundtrip_runs_evaluated | {qs.get('roundtrip_runs_evaluated', 0)} |
| roundtrip_runs_profitable | {qs.get('roundtrip_runs_profitable', 0)} |
| roundtrip_total_evaluated | {qs.get('roundtrip_total_evaluated', 0)} |
| roundtrip_total_profitable | {qs.get('roundtrip_total_profitable', 0)} |
"""
    return block


def main():
    parser = argparse.ArgumentParser(description="Doc-Sync Helper for ARBY3")
    parser.add_argument(
        "--format",
        choices=["dev_report", "status_m4", "all"],
        default="all",
        help="Output format"
    )
    args = parser.parse_args()
    
    if not ROLLING_DIR.exists():
        print(f"ERROR: Rolling directory not found: {ROLLING_DIR}")
        return 1
    
    latest, summary, agg = load_rolling_artifacts()
    
    if not latest:
        print("ERROR: _latest.json not found or empty")
        return 1
    
    print(f"=== Doc-Sync Helper v3.2.30 ===")
    print(f"Rolling artifacts loaded from: {ROLLING_DIR}")
    print()
    
    if args.format in ("dev_report", "all"):
        print("=" * 60)
        print("DEV_REPORT_LATEST.md Evidence Block")
        print("=" * 60)
        print(generate_dev_report_block(latest, summary, agg))
    
    if args.format in ("status_m4", "all"):
        print("=" * 60)
        print("Status_M4.md Evidence Block")
        print("=" * 60)
        print(generate_status_m4_block(latest, summary, agg))
    
    return 0


if __name__ == "__main__":
    exit(main())
