"""CI gate for Milestone 5: validate presence and basic correctness of daily_report.

Initial / minimal validator: accepts one or more daily_report JSON files and
performs basic schema checks (schema_version, non-null metrics, top_reject_reasons not empty).
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
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
    # top_reject_reasons should not be empty unless explained
    if isinstance(tr, list) and len(tr) == 0:
        errors.append("top_reject_reasons_empty")

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

    return errors


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--reports", nargs="+", required=True, help="daily_report JSON files to validate")
    args = p.parse_args()

    all_errors = {}
    for r in args.reports:
        path = Path(r)
        errs = validate_report(path)
        all_errors[r] = errs

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
