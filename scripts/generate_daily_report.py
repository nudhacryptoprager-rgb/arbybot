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
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, Any, List


def load_json_first(path: Path, pattern: str):
    files = sorted(path.glob(pattern))
    if not files:
        return None
    with files[0].open("r", encoding="utf8") as fh:
        return json.load(fh)


def aggregate_run(run_dir: Path, gas_usd_estimate: float | None = None, slippage_usd_estimate: float = 0.0) -> Dict[str, Any]:
    # Search for artifacts in common locations: run_dir/, run_dir/reports/, run_dir/snapshots/
    def find_first(pattern: str):
        for candidate_dir in (run_dir, run_dir / "reports", run_dir / "snapshots"):
            if not candidate_dir.exists():
                continue
            files = sorted(candidate_dir.glob(pattern))
            if files:
                return files[0]
        return None

    scan_path = find_first("scan_*.json")
    truth_path = find_first("truth_report_*.json")
    reject_path = find_first("reject_histogram_*.json")
    scan = json.loads(scan_path.read_text(encoding="utf8")) if scan_path else {}
    truth = json.loads(truth_path.read_text(encoding="utf8")) if truth_path else {}
    reject = json.loads(reject_path.read_text(encoding="utf8")) if reject_path else {}

    # Minimal aggregations
    stats = truth.get("stats", {})
    infra = truth.get("infra", {})
    health = truth.get("health", {})

    # Derive structured health sections if not present or missing components
    if not (isinstance(health, dict) and health.get("rpc") and health.get("dex") and health.get("system")):
        rpc_success_rate = stats.get("rpc_success_rate") if isinstance(stats.get("rpc_success_rate"), (int, float)) else 1.0
        # compute p50 latency from scan.quotes latencies when available
        p50_latency = None
        try:
            qlat = []
            for q in (scan.get("quotes") or []):
                if q and isinstance(q.get("latency_ms"), (int, float)):
                    qlat.append(float(q.get("latency_ms")))
            if qlat:
                qlat.sort()
                n = len(qlat)
                mid = n // 2
                if n % 2 == 1:
                    p50_latency = qlat[mid]
                else:
                    p50_latency = (qlat[mid - 1] + qlat[mid]) / 2.0
        except Exception:
            p50_latency = None

        ws_connected_rate = 1.0 if infra.get("ws_connected") else 0.0

        quotes_total = stats.get("quotes_total") or 0
        quotes_fetched = stats.get("quotes_fetched") or 0
        quote_fetch_rate = (quotes_fetched / quotes_total) if quotes_total else None

        gates_passed = stats.get("gates_passed") or 0
        gate_pass_rate = (gates_passed / quotes_total) if quotes_total else None

        health = {
            "rpc": {
                "success_rate": rpc_success_rate,
                "p50_latency_ms": p50_latency,
                "ws_connected_rate": ws_connected_rate,
            },
            "dex": {
                "quote_fetch_rate": quote_fetch_rate,
                "revert_rate": 0,
            },
            "system": {
                "gate_pass_rate": gate_pass_rate,
                "artifacts_ok_rate": 1.0,
            },
        }

    # net_pnl_usdc: prefer truth.pnl.net_pnl_usdc or zero
    pnl = truth.get("pnl", {})
    gross_net_pnl_usdc = pnl.get("net_pnl_usdc") or 0.0

    # minimal cost model: gas-only + optional slippage estimate
    if gas_usd_estimate is not None:
        paper_net = float(gross_net_pnl_usdc) - float(gas_usd_estimate) - float(slippage_usd_estimate or 0.0)
        pnl_available = True
        pnl_reason = None
    else:
        paper_net = float(gross_net_pnl_usdc or 0.0)
        pnl_available = False
        pnl_reason = "no_cost_model"

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
    if not top_rejects:
        top_rejects = [{"reason": "no_rejects", "count": 0}]

    # tail losses: use suspect_summary examples if available (placeholder)
    tail_losses = []
    suspect_summary = truth.get("suspect_summary", {})
    examples = suspect_summary.get("examples", []) if suspect_summary else []
    for ex in examples[:5]:
        tail_losses.append({"pair": ex.get("pair"), "pnl_usdc": None, "reason": ex.get("reason")})

    # Provenance
    artifacts = {
        "scan_path": str(scan_path) if scan_path else None,
        "truth_report_path": str(truth_path) if truth_path else None,
        "reject_histogram_path": str(reject_path) if reject_path else None,
    }

    # autosize: surface autosize decisions from truth if present
    autosize = truth.get("autosize") or {}
    autosize_summary = None
    if autosize:
        autosize_summary = {
            "new_size_usd": autosize.get("new_size_usd") or autosize.get("new_size") or None,
            "reason": autosize.get("reason"),
            "cooldown_remaining": autosize.get("cooldown_remaining"),
        }

    # top_opportunities: prefer truth.spread_signals, fallback to scan.quotes
    top_opportunities = []
    signals = truth.get("spread_signals") or []
    if signals:
        # sort by confidence or spread_pct
        def _sig_score(s):
            return float(s.get("confidence") or s.get("spread_pct") or 0)

        sorted_sigs = sorted(signals, key=_sig_score, reverse=True)
        for s in sorted_sigs[:5]:
            top_opportunities.append(
                {
                    "spread_pct": s.get("spread_pct"),
                    "size_usd": s.get("size_usd") or s.get("size") or None,
                    "confidence": s.get("confidence"),
                    "source": "truth",
                }
            )
    else:
        for q in (scan.get("quotes") or [])[:5]:
            if not q:
                continue
            top_opportunities.append(
                {
                    "spread_pct": q.get("spread_pct") or q.get("spread") or None,
                    "size_usd": q.get("size_usd") or q.get("size") or None,
                    "confidence": q.get("confidence"),
                    "source": "scan",
                }
            )

    report = {
        "schema_version": "m5:daily:v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "timezone": "UTC",
        "run_id": str(run_dir.name),
        "source_run_dir": str(run_dir),
        "artifacts": artifacts,
        "period": {"from": date.today().isoformat(), "to": date.today().isoformat()},
        "runs_included": 1,
        "pnl_mode": "paper",
        "paper_net_pnl_usdc": paper_net,
        "pnl_available": pnl_available,
        "pnl_reason": pnl_reason,
        "paper_win_rate": win_rate,
        "checks_count": quotes_total,
        "trades_count": quotes_total,
        "tail_losses": tail_losses,
        "top_reject_reasons": top_rejects,
        "autosize": autosize_summary,
        "top_opportunities": top_opportunities,
        "health": health,
    }
    return report


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--run-dir", required=True, help="One run directory to aggregate")
    p.add_argument("--out", help="Output directory for daily report", default=".")
    p.add_argument("--gas-usd-estimate", type=float, help="Optional gas USD estimate to enable cost model")
    p.add_argument("--slippage-usd-estimate", type=float, help="Optional slippage USD estimate to subtract from PnL", default=0.0)
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
        candidates = []
        # More robust selection: read timestamp from scan/truth artifact inside runDir
        for d in runs_root.iterdir():
            if not d.is_dir():
                continue
            # try to read scan_*.json or truth_report_*.json
            sp = sorted(d.glob("scan_*.json"))[:1]
            tp = sorted(d.glob("truth_report_*.json"))[:1]
            ts = None
            try:
                if sp:
                    j = json.loads(sp[0].read_text(encoding="utf8"))
                    ts = j.get("timestamp")
                elif tp:
                    j = json.loads(tp[0].read_text(encoding="utf8"))
                    ts = j.get("timestamp")
            except Exception:
                ts = None
            if ts:
                # compare date prefix YYYY-MM-DD
                if ts.startswith(date_token) or ts.startswith(date_token.replace("-", "")):
                    candidates.append(d)
            else:
                # fallback: include if date token in folder name (legacy)
                if date_token in d.name:
                    candidates.append(d)

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

    report = aggregate_run(run_dir, gas_usd_estimate=args.gas_usd_estimate, slippage_usd_estimate=args.slippage_usd_estimate)
    # default: write under run_dir/reports
    write_dir = run_dir / "reports"
    write_dir.mkdir(parents=True, exist_ok=True)
    out_path = write_dir / f"daily_report_{date.today().isoformat()}.json"
    with out_path.open("w", encoding="utf8") as fh:
        json.dump(report, fh, indent=2, ensure_ascii=False)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
