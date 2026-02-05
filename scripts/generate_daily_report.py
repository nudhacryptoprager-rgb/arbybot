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

    # Calculate gross spread from spread_signals
    # gross_spread_usdc = sum of (spread_pct * size_usd) for all signals
    signals = truth.get("spread_signals") or []
    gross_spread_usdc = 0.0
    default_size_usd = 1000.0  # default size for paper PnL calculation
    for sig in signals:
        spread_pct = sig.get("spread_pct") or 0.0
        size_usd = sig.get("size_usd") or default_size_usd
        gross_spread_usdc += float(spread_pct) / 100.0 * float(size_usd)

    # minimal cost model: gas-only + optional slippage estimate
    # paper_net = gross_spread - gas - slippage
    if gas_usd_estimate is not None:
        paper_net = gross_spread_usdc - float(gas_usd_estimate) - float(slippage_usd_estimate or 0.0)
        pnl_available = True
        pnl_reason = None
    else:
        paper_net = gross_spread_usdc
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
    else:
        autosize_summary = {"enabled": False, "reason": "not_configured", "new_size_usd": None, "cooldown_remaining": 0}

    # top_opportunities: ONLY from spread_signals. If empty → empty list.
    # We do NOT fallback to scan.quotes anymore to avoid noisy null entries.
    top_opportunities = []
    top_opportunities_net_positive = []  # Separate list for net-positive only
    signals = truth.get("spread_signals") or []
    if signals:
        # sort by net_pnl_usdc_est descending (most profitable first)
        def _sig_score(s):
            # Primary: net_pnl_usdc_est (profitability)
            net = float(s.get("net_pnl_usdc_est") or 0)
            # Secondary: spread_bps_exact
            spread = float(s.get("spread_bps_exact") or s.get("spread_bps") or 0)
            return (net, spread)  # sort by net first, then spread

        sorted_sigs = sorted(signals, key=_sig_score, reverse=True)
        for s in sorted_sigs[:5]:
            # require at least spread_pct or confidence to be valid opportunity
            if s.get("spread_pct") is None and s.get("confidence") is None:
                continue
            opp = {
                "pair": s.get("pair"),
                "buy_dex": s.get("buy_dex"),
                "sell_dex": s.get("sell_dex"),
                "spread_bps_exact": s.get("spread_bps_exact"),
                "spread_pct": s.get("spread_pct"),
                "spread_frac": s.get("spread_frac"),
                "gross_pnl_usdc_est": s.get("gross_pnl_usdc_est"),
                "net_pnl_usdc_est": s.get("net_pnl_usdc_est"),
                "is_net_positive_est": s.get("is_net_positive_est"),
                "net_negative_reason": s.get("net_negative_reason"),
                "size_usd": s.get("size_usd") or s.get("size") or None,
                "confidence": s.get("confidence"),
                "confidence_reasons": s.get("confidence_reasons"),
                "source": "signal",
            }
            top_opportunities.append(opp)
            # Also add to net_positive list if profitable
            if s.get("is_net_positive_est"):
                top_opportunities_net_positive.append(opp)
    # If no signals → top_opportunities remains empty (no fallback to scan quotes)
    # Add reason when empty
    opportunities_reason = None
    if not top_opportunities:
        spread_signals_count = len(signals)
        if spread_signals_count == 0:
            opportunities_reason = "no_spread_signals"
        else:
            opportunities_reason = "no_valid_signals"

    # top_quotes: sample top-2 quotes from scan.quotes with provenance fields
    # This provides a sample of raw scanner output with full provenance
    top_quotes = []
    raw_quotes = scan.get("quotes") or []
    scan_timestamp = scan.get("timestamp")  # use scan timestamp for all quotes
    for q in raw_quotes[:2]:  # take first 2 as sample
        if not q:
            continue
        # Build pair from token_in/token_out if not present
        pair = q.get("pair")
        if not pair:
            token_in = q.get("token_in") or "?"
            token_out = q.get("token_out") or "?"
            pair = f"{token_in}/{token_out}"
        quote_sample = {
            "dex_id": q.get("dex_id"),
            "pool_address": q.get("pool_address"),
            "block_number": q.get("block_number"),
            "price": q.get("price"),
            "fee": q.get("fee"),
            "amount_in_human": q.get("amount_in_human"),
            "amount_out_human": q.get("amount_out_human"),
            "tick": q.get("tick"),
            "sqrt_price_x96": q.get("sqrt_price_x96"),
            "pair": pair,
            "timestamp": q.get("timestamp") or scan_timestamp,
        }
        top_quotes.append(quote_sample)

    # Build cost_model block for transparency
    cost_model = {
        "type": "gas_only" if gas_usd_estimate is not None else "none",
        "gas_usd_estimate": gas_usd_estimate,
        "slippage_usd_estimate": slippage_usd_estimate if gas_usd_estimate is not None else None,
    }

    # Extract gates_passed and quotes_fetched for explicit surfacing
    gates_passed = stats.get("gates_passed") or 0
    quotes_fetched = stats.get("quotes_fetched") or scan.get("quotes_fetched") or 0

    # Build human-readable summary
    spread_info = f"spreads={len(signals)}" if signals else "spreads=0"
    summary = f"quotes_fetched={quotes_fetched}, gates_passed={gates_passed}, {spread_info}, paper_pnl={paper_net:.2f}"

    # Top signal for summary (best spread)
    top_signal = None
    if signals:
        # Sort by spread_bps_exact (or spread_bps for backwards compat) descending
        sorted_signals = sorted(
            signals, 
            key=lambda s: s.get("spread_bps_exact") or s.get("spread_bps") or 0, 
            reverse=True
        )
        best = sorted_signals[0]
        top_signal = {
            "pair": best.get("pair"),
            "buy_dex": best.get("buy_dex"),
            "sell_dex": best.get("sell_dex"),
            "spread_bps_exact": best.get("spread_bps_exact"),
            "spread_bps_int": best.get("spread_bps_int") or best.get("spread_bps"),
            "is_gross_positive": best.get("is_gross_positive"),
            "gross_pnl_usdc_est": best.get("gross_pnl_usdc_est"),
            "net_pnl_usdc_est": best.get("net_pnl_usdc_est"),
            "is_net_positive_est": best.get("is_net_positive_est"),
        }

    report = {
        "schema_version": "m5:daily:v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "timezone": "UTC",
        "run_id": str(run_dir.name),
        "source_run_dir": str(run_dir),
        "summary": summary,
        "artifacts": artifacts,
        "period": {"from": date.today().isoformat(), "to": date.today().isoformat()},
        "runs_included": 1,
        "pnl_mode": "paper",
        "gross_spread_usdc": round(gross_spread_usdc, 6),
        "paper_net_pnl_usdc": round(paper_net, 6),
        "pnl_available": pnl_available,
        "pnl_reason": pnl_reason,
        "cost_model": cost_model,
        "paper_win_rate": win_rate,
        "checks_count": quotes_total,
        "quotes_fetched": quotes_fetched,
        "gates_passed": gates_passed,
        "spread_signals_count": len(signals),
        "net_positive_signals_count": len(top_opportunities_net_positive),
        "top_signal": top_signal,
        # DEPRECATED: will be removed in schema v2. Use checks_count.
        "deprecated_legacy_trades_count": quotes_total,
        "tail_losses": tail_losses,
        "top_reject_reasons": top_rejects,
        "autosize": autosize_summary,
        "top_opportunities": top_opportunities,
        "top_opportunities_net_positive": top_opportunities_net_positive,
        "opportunities_reason": opportunities_reason,
        "top_quotes": top_quotes,
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
            "checks_count": sum((r.get("checks_count") or 0) for r in reports),
            "legacy_trades_count": sum((r.get("checks_count") or 0) for r in reports),
            "top_reject_reasons": [],
            "tail_losses": [],
            "health": {},
        }
        # compute combined win_rate
        total_checks = merged["checks_count"]
        total_passed = sum(((r.get("paper_win_rate") or 0) * (r.get("checks_count") or 0)) for r in reports)
        merged["paper_win_rate"] = (total_passed / total_checks) if total_checks else None

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
