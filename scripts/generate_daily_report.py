"""Generate a minimal daily_report JSON from one or more run directories.

Usage (manual, initial):
  python scripts/generate_daily_report.py --run-dir data/runs/manual_run_20260205_131550 --out reports/

This is intentionally minimal: it reads `scan_*.json`, `truth_report_*.json`, and
`reject_histogram_*.json` from a run directory and builds `daily_report_<date>.json`.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Dict, Any, List


def load_json_first(path: Path, pattern: str):
    files = sorted(path.glob(pattern))
    if not files:
        return None
    with files[0].open("r", encoding="utf8") as fh:
        return json.load(fh)


def aggregate_run(run_dir: Path) -> Dict[str, Any]:
    scan = load_json_first(run_dir, "scan_*.json") or {}
    truth = load_json_first(run_dir, "truth_report_*.json") or {}
    reject = load_json_first(run_dir, "reject_histogram_*.json") or {}

    # Minimal aggregations
    health = truth.get("health", {})

    # net_pnl_usdc: prefer truth.pnl.net_pnl_usdc or zero
    pnl = truth.get("pnl", {})
    net_pnl_usdc = pnl.get("net_pnl_usdc") or 0.0

    # win_rate: define as (quotes that passed sanity) / total quotes
    quotes_total = truth.get("quotes_total") or scan.get("quotes_total") or 0
    passed = truth.get("price_sanity_passed") or scan.get("price_sanity_passed") or 0
    win_rate = (passed / quotes_total) if quotes_total else None

    # rejects reasons
    reasons_counter = Counter()
    for r in (reject.get("rejects") or []):
        reason = r.get("error") or r.get("suspect_reason") or "unknown"
        reasons_counter[reason] += 1

    top_rejects = [ {"reason": k, "count": v} for k, v in reasons_counter.most_common(10) ]

    # tail losses: use suspect_summary examples if available (placeholder)
    tail_losses = []
    suspect_summary = truth.get("suspect_summary", {})
    examples = suspect_summary.get("examples", []) if suspect_summary else []
    for ex in examples[:5]:
        tail_losses.append({"pair": ex.get("pair"), "pnl_usdc": None, "reason": ex.get("reason")})

    report = {
        "schema_version": "m5:daily:v1",
        "run_id": str(run_dir.name),
        "date": date.today().isoformat(),
        "period": {"from": date.today().isoformat(), "to": date.today().isoformat()},
        "runs_included": 1,
        "net_pnl_usdc": net_pnl_usdc,
        "win_rate": win_rate,
        "trades_count": quotes_total,
        "tail_losses": tail_losses,
        "top_reject_reasons": top_rejects,
        "health": health,
    }
    return report


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--run-dir", required=True, help="One run directory to aggregate")
    p.add_argument("--out", help="Output directory for daily report", default=".")
    args = p.parse_args()

    run_dir = Path(args.run_dir)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    report = aggregate_run(run_dir)
    out_path = out_dir / f"daily_report_{date.today().isoformat()}.json"
    with out_path.open("w", encoding="utf8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
