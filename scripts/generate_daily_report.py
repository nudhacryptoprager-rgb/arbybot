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
    scan_path = sorted(run_dir.glob("scan_*.json"))[:1]
    truth_path = sorted(run_dir.glob("truth_report_*.json"))[:1]
    reject_path = sorted(run_dir.glob("reject_histogram_*.json"))[:1]
    scan = json.loads(scan_path[0].read_text(encoding="utf8")) if scan_path else {}
    truth = json.loads(truth_path[0].read_text(encoding="utf8")) if truth_path else {}
    reject = json.loads(reject_path[0].read_text(encoding="utf8")) if reject_path else {}

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

    top_rejects = [{"reason": k, "count": v} for k, v in reasons_counter.most_common(10)]

    # tail losses: use suspect_summary examples if available (placeholder)
    tail_losses = []
    suspect_summary = truth.get("suspect_summary", {})
    examples = suspect_summary.get("examples", []) if suspect_summary else []
    for ex in examples[:5]:
        tail_losses.append({"pair": ex.get("pair"), "pnl_usdc": None, "reason": ex.get("reason")})

    # Provenance
    artifacts = {
        "scan_path": str(scan_path[0]) if scan_path else None,
        "truth_report_path": str(truth_path[0]) if truth_path else None,
        "reject_histogram_path": str(reject_path[0]) if reject_path else None,
    }

    report = {
        "schema_version": "m5:daily:v1",
        "generated_at": date.today().isoformat(),
        "run_id": str(run_dir.name),
        "source_run_dir": str(run_dir),
        "artifacts": artifacts,
        "period": {"from": date.today().isoformat(), "to": date.today().isoformat()},
        "runs_included": 1,
        "pnl_mode": "paper",
        "paper_net_pnl_usdc": net_pnl_usdc,
        "paper_win_rate": win_rate,
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
    p.add_argument("--runs-root", help="Optional root to aggregate multiple runs for a date")
    p.add_argument("--date", help="Date to aggregate (YYYYMMDD) when using --runs-root")
    args = p.parse_args()

    run_dir = Path(args.run_dir)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    # Multi-run aggregation mode
    if args.runs_root and args.date:
        runs_root = Path(args.runs_root)
        date_token = args.date
        candidates = [d for d in runs_root.iterdir() if d.is_dir() and date_token in d.name]
        aggregated = None
        reports = []
        for d in sorted(candidates):
            r = aggregate_run(d)
            reports.append(r)

        # Merge simple sums and lists
        merged = {
            "schema_version": "m5:daily:v1",
            "generated_at": date.today().isoformat(),
            "source_run_dirs": [r.get("source_run_dir") for r in reports],
            "runs_included": len(reports),
            "pnl_mode": "paper",
            "paper_net_pnl_usdc": sum((r.get("paper_net_pnl_usdc") or 0) for r in reports),
            "paper_win_rate": None,
            "trades_count": sum((r.get("trades_count") or 0) for r in reports),
            "top_reject_reasons": [],
            "tail_losses": [],
            "health": {},
        }
        # compute combined win_rate
        total_trades = merged["trades_count"]
        total_passed = sum(((r.get("paper_win_rate") or 0) * (r.get("trades_count") or 0)) for r in reports)
        merged["paper_win_rate"] = (total_passed / total_trades) if total_trades else None

        # aggregate top rejects
        counter = Counter()
        for r in reports:
            for t in r.get("top_reject_reasons") or []:
                counter[t.get("reason")] += t.get("count", 0)
        merged["top_reject_reasons"] = [{"reason": k, "count": v} for k, v in counter.most_common(10)]

        out_path = out_dir / f"daily_report_{args.date}.json"
        with out_path.open("w", encoding="utf8") as fh:
            json.dump(merged, fh, indent=2, ensure_ascii=False)
        print(f"Wrote {out_path}")
        return

    report = aggregate_run(run_dir)
    # default: write under run_dir/reports
    write_dir = run_dir / "reports"
    write_dir.mkdir(parents=True, exist_ok=True)
    out_path = write_dir / f"daily_report_{date.today().isoformat()}.json"
    with out_path.open("w", encoding="utf8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
