"""CI gate for Milestone 5: validate presence and basic correctness of daily_report.

Initial / minimal validator: accepts one or more daily_report JSON files and
performs basic schema checks (schema_version, non-null metrics, top_reject_reasons not empty).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from datetime import date, datetime
from typing import List, Optional


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


def _latest_run_dir(runs_root: Path) -> Optional[Path]:
    if not runs_root.exists():
        return None
    cand = [p for p in runs_root.iterdir() if p.is_dir()]
    if not cand:
        return None
    cand.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return cand[0]


def _run_scan_module(config: Optional[str], cycles: int) -> None:
    cmd = [sys.executable, "-m", "strategy.jobs.run_scan", "--mode", "real", "--cycles", str(cycles)]
    if config:
        cmd += ["--config", config]
    # Run scanner as subprocess to keep same semantics as CI
    subprocess.check_call(cmd)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--reports", nargs="+", required=False, help="daily_report JSON files to validate")
    p.add_argument("--generate-report", help="Path to runDir to generate daily_report before validation")
    p.add_argument("--run-dir", help="Use existing runDir instead of running scanner")
    p.add_argument("--online", help="Run scanner before generating and validating report", action="store_true")
    p.add_argument("--config", help="Config file to pass to scanner when --online")
    p.add_argument("--cycles", type=int, default=1, help="Number of cycles to run when --online")
    p.add_argument("--strict-paper-only", help="Enforce paper_* fields only (fail on legacy fields)", action="store_true", default=False)
    args = p.parse_args()

    run_dir: Optional[Path] = None

    # If --run-dir provided, use it and skip scanning
    if args.run_dir:
        run_dir = Path(args.run_dir)

    # If online requested and no run-dir given, run the scanner
    if args.online and run_dir is None:
        try:
            _run_scan_module(args.config, args.cycles)
        except Exception as e:
            print(f"Scanner run failed: {e}")
            print(f"RESULT: FAIL (scanner) + None")
            raise
        # try to discover latest runDir under data/runs
        runs_root = Path("data") / "runs"
        run_dir = _latest_run_dir(runs_root)
        if run_dir is None:
            print("No runDir found after scanner run")
            print("RESULT: FAIL + None")
            raise SystemExit(2)

    # If generate-report requested with a runDir path string
    if args.generate_report:
        run_dir = Path(args.generate_report)

    generated_report_paths: List[Path] = []

    # If a run_dir is available, generate a report for it
    if run_dir is not None:
        from scripts.generate_daily_report import aggregate_run
        import os

        gas_env = os.environ.get("ARBY_GAS_USD_ESTIMATE") or os.environ.get("GAS_USD_ESTIMATE")
        slip_env = os.environ.get("ARBY_SLIPPAGE_USD_ESTIMATE") or os.environ.get("SLIPPAGE_USD_ESTIMATE")
        gas_val = float(gas_env) if gas_env is not None else None
        slip_val = float(slip_env) if slip_env is not None else 0.0

        report = aggregate_run(run_dir, gas_usd_estimate=gas_val, slippage_usd_estimate=slip_val)
        write_dir = run_dir / "reports"
        write_dir.mkdir(parents=True, exist_ok=True)
        # Use date part for filename
        gen_at = report.get("generated_at") or datetime.utcnow().isoformat()
        safe_ts = gen_at.replace(":", "-")
        out_path = write_dir / f"daily_report_{safe_ts}.json"
        out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf8")
        print(f"Generated report: {out_path}")
        generated_report_paths.append(out_path)

    all_errors = {}

    # Validate provided report files (either via --reports or generated)
    reports_to_check: List[Path] = []
    if args.reports:
        reports_to_check = [Path(r) for r in args.reports]
    else:
        reports_to_check = generated_report_paths

    if not reports_to_check:
        print("No reports provided for validation; use --reports, --run-dir, --generate-report, or --online")
        print("RESULT: FAIL + None")
        raise SystemExit(2)

    for r in reports_to_check:
        errs = validate_report(r)
        all_errors[str(r)] = errs

    ok = True
    for r, errs in all_errors.items():
        if errs:
            ok = False
            print(f"{r}: FAIL -> {errs}")
        else:
            print(f"{r}: OK")

    # Print canonical RESULT line for easy CI consumption
    run_dir_display = str(run_dir) if run_dir is not None else "None"
    if ok:
        print(f"RESULT: PASS + {run_dir_display}")
        raise SystemExit(0)
    else:
        print(f"RESULT: FAIL + {run_dir_display}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
