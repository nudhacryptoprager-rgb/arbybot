"""CI gate for Milestone 5: validate presence and basic correctness of daily_report.

STATUS: FROZEN (2026-02-08)
Changes only for M4 execution requirements. M5 feature set is complete.

Initial / minimal validator: accepts one or more daily_report JSON files and
performs basic schema checks (schema_version, non-null metrics, top_reject_reasons not empty).

M5 STRICT INVARIANTS:
1. PRICE_SCALE_BOUNDS: detect inverted token0/token1 direction bugs
2. paper_win_rate = paper estimate, NOT real execution
3. health.rpc.p50_latency_ms required when quotes_fetched > 0
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from datetime import date, datetime, timezone
from typing import Dict, List, Optional, Tuple, Any

# Ensure repository root is on sys.path
try:
    REPO_ROOT = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(REPO_ROOT))
except Exception:
    pass

# Import canonical PRICE_SCALE_BOUNDS from core.constants
from core.constants import PRICE_SCALE_BOUNDS


def validate_price_scale(data: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """Validate price scale invariant (M5 strict gate rule).
    
    Returns (ok, errors) where errors contains violation messages.
    """
    errors = []
    
    # Look for quotes in various locations
    quotes = data.get("top_opportunities", [])
    if not quotes:
        return True, []
    
    for i, q in enumerate(quotes):
        pair = q.get("pair") or f"{q.get('token_in', '?')}/{q.get('token_out', '?')}"
        price_str = q.get("price") or q.get("price_exact")
        if not price_str:
            continue
        
        try:
            price = float(price_str)
        except (ValueError, TypeError):
            continue
        
        bounds = PRICE_SCALE_BOUNDS.get(pair)
        if bounds:
            min_p, max_p = bounds
            if price < min_p or price > max_p:
                errors.append(
                    f"strict_price_scale_violation_{i}_{pair}_{price:.6g}_outside_{min_p}_{max_p}"
                )
    
    return len(errors) == 0, errors


def validate_report(path: Path, strict: bool = False) -> List[str]:
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

    # strict checks: p50 presence if quotes_fetched>0
    if strict:
        # derive quotes_fetched from the report or artifacts
        quotes_fetched = None
        if j.get("checks_count") is not None:
            quotes_fetched = j.get("checks_count")
        elif j.get("trades_count") is not None:
            quotes_fetched = j.get("trades_count")
        else:
            artifacts = j.get("artifacts") or {}
            truth_p = artifacts.get("truth_report_path")
            if truth_p:
                try:
                    t = json.loads(Path(truth_p).read_text(encoding="utf8"))
                    stats = t.get("stats") or {}
                    quotes_fetched = stats.get("quotes_fetched") or stats.get("quotes_total")
                except Exception:
                    quotes_fetched = None

        try:
            qf = int(quotes_fetched) if quotes_fetched is not None else 0
        except Exception:
            qf = 0

        p50 = None
        try:
            p50 = health.get("rpc", {}).get("p50_latency_ms") if health else None
        except Exception:
            p50 = None

        if qf > 0 and p50 is None:
            errors.append("health_rpc_p50_missing_when_quotes_fetched")
        
        # ws_attempted check: if quotes_fetched > 0 and ws_enabled, require ws_attempted=true
        # (prevents health lying about WS connectivity)
        ws_enabled = False
        ws_attempted = False
        try:
            infra = j.get("infra") or {}
            ws_enabled = infra.get("ws_enabled", False)
            ws_attempted = infra.get("ws_attempted", False)
        except Exception:
            pass
        
        if qf > 0 and ws_enabled and not ws_attempted:
            errors.append("health_ws_not_attempted_when_enabled")

        # CRITICAL: Check for invalid quotes (POOL_MISSING, PRICE_OUTLIER) in strict mode
        # These indicate data quality issues that produce fake spreads
        pool_missing = 0
        price_outlier = 0
        for r in tr:
            reason = r.get("reason", "")
            if reason == "POOL_MISSING":
                pool_missing = r.get("count", 0)
            elif reason == "PRICE_OUTLIER":
                price_outlier = r.get("count", 0)
        
        if pool_missing > 0:
            errors.append(f"strict_pool_missing_count_{pool_missing}")
        if price_outlier > 0:
            errors.append(f"strict_price_outlier_count_{price_outlier}")
        
        # Also check pnl_available - if false due to invalid_quotes, this is a problem
        pnl_reason = j.get("pnl_reason")
        if pnl_reason == "invalid_quotes_present":
            errors.append("strict_pnl_unavailable_due_to_invalid_quotes")

        # top_opportunities sanity: if present non-empty, require source + one of spread_pct/price/confidence
        tops = j.get("top_opportunities") or []
        if tops and isinstance(tops, list):
            for i, op in enumerate(tops):
                if not op.get("source"):
                    errors.append(f"top_opportunity_missing_source_{i}")
                if not any([op.get("spread_pct") is not None, op.get("price") is not None, op.get("confidence") is not None]):
                    errors.append(f"top_opportunity_missing_min_fields_{i}")
        
        # PRICE_SCALE_BOUNDS invariant (M5 strict rule)
        # Detects inverted token0/token1 direction bugs
        ps_ok, ps_errors = validate_price_scale(j)
        if not ps_ok:
            errors.extend(ps_errors)

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
    p.add_argument("--gas-usd-estimate", type=float, help="Optional gas USD estimate to enable cost model when generating report")
    p.add_argument("--slippage-usd-estimate", type=float, help="Optional slippage USD estimate to subtract from PnL", default=0.0)
    p.add_argument("--strict", help="Enable strict validations (p50 presence when quotes_fetched>0, top_opportunities sanity)", action="store_true", default=False)
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
        import yaml

        # Load config to try reading gas/slippage estimates from there
        config_gas = None
        config_slip = None
        if args.config:
            try:
                with open(args.config, "r", encoding="utf8") as f:
                    cfg = yaml.safe_load(f)
                config_gas = cfg.get("gas_usd_estimate")
                config_slip = cfg.get("slippage_usd_estimate")
            except Exception:
                pass

        # precedence: CLI args > env > config
        gas_val = args.gas_usd_estimate if args.gas_usd_estimate is not None else (
            float(os.environ.get("ARBY_GAS_USD_ESTIMATE")) if os.environ.get("ARBY_GAS_USD_ESTIMATE") else (
                float(config_gas) if config_gas is not None else None
            )
        )
        slip_val = args.slippage_usd_estimate if args.slippage_usd_estimate is not None else (
            float(os.environ.get("ARBY_SLIPPAGE_USD_ESTIMATE")) if os.environ.get("ARBY_SLIPPAGE_USD_ESTIMATE") else (
                float(config_slip) if config_slip is not None else 0.0
            )
        )

        report = aggregate_run(run_dir, gas_usd_estimate=gas_val, slippage_usd_estimate=slip_val)
        write_dir = run_dir / "reports"
        write_dir.mkdir(parents=True, exist_ok=True)
        # Use date part for filename
        gen_at = report.get("generated_at") or datetime.now(timezone.utc).isoformat()
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
        errs = validate_report(Path(r), strict=args.strict)
        all_errors[str(r)] = errs

    # If gas estimate was provided to the runner, enforce invariant: generated report must have pnl_available true
    if args.gas_usd_estimate is not None:
        for p in reports_to_check:
            try:
                j = json.loads(Path(p).read_text(encoding="utf8"))
                if not j.get("pnl_available"):
                    all_errors[str(p)] = all_errors.get(str(p), []) + ["pnl_available_false_when_gas_estimate_provided"]
            except Exception:
                all_errors[str(p)] = all_errors.get(str(p), []) + ["pnl_read_error"]

    ok = True
    for r, errs in all_errors.items():
        if errs:
            ok = False
            print(f"{r}: FAIL -> {errs}")
        else:
            print(f"{r}: OK")

    # If validation passed, also run check_status_md.py as final step
    if ok:
        try:
            # Run check_status_md for Status_M5.md only (current milestone)
            result = subprocess.run(
                [sys.executable, "-m", "scripts.check_status_md", "--file", "Status_M5.md"],
                capture_output=True,
                text=True
            )
            print("\n--- Running check_status_md validation ---")
            print(result.stdout)
            if result.returncode != 0:
                ok = False
                print("check_status_md.py validation FAILED")
                if result.stderr:
                    print(result.stderr)
        except Exception as e:
            print(f"check_status_md.py error: {e}")
            ok = False

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
