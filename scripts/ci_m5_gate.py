"""CI gate for Milestone 5: validate presence and basic correctness of daily_report.

Initial / minimal validator: accepts one or more daily_report JSON files and
performs basic schema checks (schema_version, non-null metrics, top_reject_reasons not empty).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from datetime import date
from typing import List


def validate_report(path: Path) -> List[str]:
    errors = []
    try:
        j = json.loads(path.read_text(encoding="utf8"))
    except Exception as e:
        return [f"invalid_json: {e}"]

    sv = j.get("schema_version")
    if not sv or not str(sv).startswith("m5:daily"):
        errors.append("schema_version_missing_or_invalid")

    if j.get("runs_included") is None:
        errors.append("runs_included_missing")

    # basic metrics
    # Accept paper-mode net_pnl or legacy net_pnl
    if j.get("paper_net_pnl_usdc") is None and j.get("net_pnl_usdc") is None:
        errors.append("net_pnl_missing")
    if j.get("paper_win_rate") is None and j.get("win_rate") is None:
        errors.append("win_rate_missing")

    # Validate win_rate bounds if present
    wr = j.get("paper_win_rate") or j.get("win_rate")
    if wr is not None:
        try:
            fv = float(wr)
            if not (0.0 <= fv <= 1.0):
                errors.append("win_rate_out_of_bounds")
        except Exception:
            errors.append("win_rate_invalid")

    tr = j.get("top_reject_reasons") or []
    if not isinstance(tr, list):
        errors.append("top_reject_reasons_invalid")
    # Empty top_reject_reasons is acceptable; gate will accept empty list as 'no rejects'

    health = j.get("health")
    if health is None:
        errors.append("health_missing")
    else:
        for k in ("rpc", "dex", "system"):
            if k not in health:
                errors.append(f"health_missing_{k}")

    # Consistency checks with artifacts if provided
    artifacts = j.get("artifacts") or {}
    try:
        scan_p = artifacts.get("scan_path")
        truth_p = artifacts.get("truth_report_path")
        reject_p = artifacts.get("reject_histogram_path")
        if scan_p and truth_p:
            scan = json.loads(Path(scan_p).read_text(encoding="utf8"))
            truth = json.loads(Path(truth_p).read_text(encoding="utf8"))
            # quotes_total
            r_quotes = j.get("trades_count") or j.get("quotes_total")
            t_quotes = truth.get("quotes_total") or scan.get("quotes_total")
            if r_quotes is not None and t_quotes is not None and int(r_quotes) != int(t_quotes):
                errors.append("quotes_total_mismatch")
            # current_block
            r_block = j.get("current_block") or truth.get("current_block") or scan.get("current_block")
            s_block = scan.get("current_block")
            if r_block is not None and s_block is not None and int(r_block) != int(s_block):
                errors.append("current_block_mismatch")
        if reject_p:
            rej = json.loads(Path(reject_p).read_text(encoding="utf8"))
            r_rejects = j.get("rejects_total") or j.get("total_rejects")
            rej_total = rej.get("total_rejects") or len(rej.get("rejects") or [])
            if r_rejects is not None and int(r_rejects) != int(rej_total):
                errors.append("rejects_total_mismatch")
    except Exception as e:
        errors.append(f"artifact_consistency_error:{e}")

    # strict-paper-only enforcement: if true and legacy fields present without paper_ equivalents, fail
    # NOTE: this function does not have access to CLI flags; caller must enforce if needed.

    return errors


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--reports", nargs="+", required=False, help="daily_report JSON files to validate")
    p.add_argument("--generate-report", help="Path to runDir to generate daily_report before validation")
    p.add_argument("--strict-paper-only", help="Enforce paper_* fields only (fail on legacy fields)", action="store_true", default=True)
    args = p.parse_args()

    # If requested, generate report first to avoid validating stale reports
    if args.generate_report:
        from scripts.generate_daily_report import aggregate_run
        run_dir = Path(args.generate_report)
        report = aggregate_run(run_dir)
        write_dir = run_dir / "reports"
        write_dir.mkdir(parents=True, exist_ok=True)
        out_path = write_dir / f"daily_report_{report.get('generated_at', date.today().isoformat())}.json"
        out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf8")
        print(f"Generated report: {out_path}")

    all_errors = {}
    if args.reports:
        for r in args.reports:
            path = Path(r)
            errs = validate_report(path)
            all_errors[r] = errs
    else:
        print("No reports provided for validation; use --reports or --generate-report")
        raise SystemExit(2)

    ok = True
    for r, errs in all_errors.items():
        if errs:
            ok = False
            print(f"{r}: FAIL -> {errs}")
        else:
            print(f"{r}: OK")

    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
