#!/usr/bin/env python3
"""
start.py - Multi-chain time-bounded online scan orchestrator.

Round-robins through a list of config files, running ci_m5_0_gate.py --online
for each. Only the primary rolling chain (run_kind=NORMAL) gets --refresh-rolling;
coverage configs skip rolling refresh to respect the rolling-discipline guardrail.

After all runs, writes a per-chain summary to --summary-file and prints a
console report including guardrails (e.g. "too good to be true" warning).

Runtime artifacts stay under data/runs/** and must never be committed.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import re
import glob as _glob

import yaml

RUNS_DIR = Path("data") / "runs"
CI_GATE = Path("scripts") / "ci_m5_0_gate.py"
RUN_DIR_RE = re.compile(r"^\[ONLINE\] RunDir:\s*(.+)\s*$")
CI_M5_DIR_RE = re.compile(r"^ci_m5_gate_\d{8}_\d{6}$")

# -- config introspection -------------------------------------------------


def read_config_meta(config_path: str) -> dict[str, Any]:
    """Return chain/run_kind from a YAML config without importing strategy code."""
    try:
        with open(config_path, encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except Exception:
        data = {}
    return {
        "chain": data.get("chain", "unknown"),
        "run_kind": data.get("run_kind", "NORMAL"),
    }


def is_primary_rolling_config(meta: dict[str, Any]) -> bool:
    return meta["run_kind"] == "NORMAL"


# -- child process -------------------------------------------------------


def run_gate_once(
    config: str,
    cycles: int,
    prune_keep: int,
    sleep_seconds: int,
    refresh_rolling: bool,
    timeout_seconds: int,
) -> tuple[int, Path | None]:
    """Run ci_m5_0_gate.py once; return (exit_code, runDir)."""
    cmd = [
        sys.executable,
        str(CI_GATE),
        "--online",
        "--config",
        config,
        "--cycles",
        str(cycles),
        "--prune-keep",
        str(prune_keep),
        "--sleep-seconds",
        str(sleep_seconds),
    ]
    if refresh_rolling:
        cmd += ["--refresh-rolling", "--refresh-rolling-strict"]

    run_dir: Path | None = None
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    assert proc.stdout is not None

    try:
        start = time.monotonic()
        for line in proc.stdout:
            sys.stdout.write(line)
            m = RUN_DIR_RE.match(line.strip())
            if m:
                run_dir = Path(m.group(1).strip())
            if timeout_seconds > 0 and (time.monotonic() - start) > timeout_seconds:
                proc.kill()
                print(f"[TIMEOUT] Child killed after {timeout_seconds}s")
                break
        rc = proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        proc.kill()
        rc = 3
    except Exception:
        proc.kill()
        rc = 3

    return rc, run_dir


# -- run_summary extraction -----------------------------------------------


def extract_run_summary(run_dir: Path | None) -> dict[str, Any] | None:
    """Read the latest run_summary from a runDir."""
    if run_dir is None or not run_dir.exists():
        return None
    reports = run_dir / "reports"
    if not reports.exists():
        return None
    summaries = sorted(reports.glob("run_summary_*.json"))
    if not summaries:
        return None
    try:
        with open(summaries[-1], encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def extract_gate_result(run_dir: Path | None) -> dict[str, Any] | None:
    """Read gate_result.json from a runDir."""
    if run_dir is None or not run_dir.exists():
        return None
    path = run_dir / "reports" / "gate_result.json"
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def classify_run(exit_code: int, summary: dict[str, Any] | None) -> str:
    """Return PASS / NO_DATA / FAIL / INFRA_FAIL for a single run."""
    if summary is None:
        return "INFRA_FAIL"
    status = summary.get("status", "")
    if status == "PASS":
        return "PASS"
    if status == "NO_DATA":
        return "NO_DATA"
    return "FAIL"


# -- housekeeping ---------------------------------------------------------


def delete_if_empty_run_dir(run_dir: Path) -> bool:
    try:
        if run_dir.name and CI_M5_DIR_RE.match(run_dir.name):
            reports = run_dir / "reports"
            if not reports.exists():
                shutil.rmtree(run_dir)
                return True
    except Exception:
        return False
    return False


def prune_run_dirs(keep: int) -> None:
    subprocess.run(
        [sys.executable, "scripts/prune_run_dirs.py", "--keep", str(keep), "--yes"],
        check=False,
    )


# -- per-chain aggregation ------------------------------------------------


def new_chain_stats() -> dict[str, Any]:
    return {
        "config": "",
        "runs": 0,
        "infra_pass": 0,
        "pass": 0,
        "no_data": 0,
        "fail": 0,
        "infra_fail": 0,
        "included_signals_total": 0,
        "net_usdc_total": 0.0,
        "profitable_roundtrips_total": 0,
        "roundtrip_evaluated_total": 0,
        "best_roundtrip_net_bps": None,
        "best_measured_spread_gap_bps": None,
        "last_run_timestamp": None,
        "last_run_dir": None,
        # Richer per-chain fields (last-run snapshot)
        "last_run_summary_status": None,
        "last_quality_status": None,
        "last_chain_quality_level": None,
        "last_profit_truth_available": None,
        "run_kind": None,
        "last_cross_dex_pairs_count": None,
        "accepted_fail": False,
    }


def update_chain_stats(
    stats: dict[str, Any],
    exit_code: int,
    run_dir: Path | None,
    summary: dict[str, Any] | None,
    gate_result: dict[str, Any] | None = None,
) -> None:
    stats["runs"] += 1
    cls = classify_run(exit_code, summary)
    stats[cls.lower()] = stats.get(cls.lower(), 0) + 1
    if exit_code == 0:
        stats["infra_pass"] += 1

    if summary:
        metrics = summary.get("metrics", {})
        stats["included_signals_total"] += metrics.get("included_signals_count", 0)
        stats["net_usdc_total"] += float(metrics.get("total_net_usdc", 0) or 0)
        rt = metrics.get("roundtrip", {}) or summary.get("roundtrip_summary", {})
        stats["profitable_roundtrips_total"] += int(rt.get("profitable_count", 0) or 0)
        stats["roundtrip_evaluated_total"] = stats.get("roundtrip_evaluated_total", 0) + int(rt.get("evaluated_count", 0) or 0)
        run_best = rt.get("best_net_pnl_bps")
        if run_best is not None:
            prev = stats.get("best_roundtrip_net_bps")
            stats["best_roundtrip_net_bps"] = run_best if prev is None else max(prev, run_best)
        run_gap = rt.get("best_measured_spread_gap_bps")
        if run_gap is not None:
            prev_gap = stats.get("best_measured_spread_gap_bps")
            stats["best_measured_spread_gap_bps"] = run_gap if prev_gap is None else max(prev_gap, run_gap)
        ctx = summary.get("run_context", {})
        stats["last_run_timestamp"] = ctx.get("run_timestamp", stats["last_run_timestamp"])
        # Richer snapshot fields
        stats["last_run_summary_status"] = summary.get("status")
        stats["last_quality_status"] = summary.get("quality_status")
        stats["last_chain_quality_level"] = metrics.get("chain_quality_level")
        stats["last_profit_truth_available"] = metrics.get("profit_truth_available")
        stats["run_kind"] = summary.get("run_kind", stats["run_kind"])

    if gate_result:
        stats["last_cross_dex_pairs_count"] = gate_result.get("cross_dex_pairs_count")

    if run_dir:
        stats["last_run_dir"] = str(run_dir.name)


# -- guardrails -----------------------------------------------------------


def check_guardrails(per_chain: dict[str, dict[str, Any]]) -> list[str]:
    """Return list of warning strings for suspicious patterns."""
    warnings: list[str] = []
    total_runs = sum(s["runs"] for s in per_chain.values())
    total_pass = sum(s["pass"] for s in per_chain.values())
    total_fail = sum(s["fail"] for s in per_chain.values())
    total_no_data = sum(s["no_data"] for s in per_chain.values())

    if total_runs >= 5 and total_fail == 0 and total_no_data == 0:
        warnings.append(
            "ALL_POSITIVE: Every run PASS, zero FAIL/NO_DATA -- "
            "verify against Roadmap.md Truth Engine expectation"
        )

    for chain, s in per_chain.items():
        if s["runs"] >= 3 and s["pass"] > 0 and s["fail"] == 0 and s["no_data"] == 0:
            warnings.append(
                f"CHAIN_ALL_POSITIVE [{chain}]: {s['runs']} runs all PASS -- "
                "check if data quality is real"
            )
        if s["runs"] >= 3 and s["infra_fail"] > s["runs"] * 0.5:
            warnings.append(
                f"CHAIN_INFRA_UNSTABLE [{chain}]: >{50}% runs had infra failures"
            )

    return warnings


# -- summary output -------------------------------------------------------


def build_summary(
    per_chain: dict[str, dict[str, Any]],
    wall_seconds: float,
    warnings: list[str],
) -> dict[str, Any]:
    pass_chains = [c for c, s in per_chain.items() if s["runs"] > 0 and s["fail"] == 0 and s["infra_fail"] == 0 and s["pass"] > 0]
    fail_chains = [c for c, s in per_chain.items() if s["fail"] > 0 or s["infra_fail"] > 0]
    probe_only_chains = [c for c, s in per_chain.items() if s["runs"] > 0 and s["pass"] == 0 and s["fail"] == 0]
    accepted_fail_chains = [c for c in fail_chains if per_chain[c].get("accepted_fail")]
    unexpected_fail_chains = [c for c in fail_chains if not per_chain[c].get("accepted_fail")]

    return {
        "schema": "start:long_scan_summary:v1.2",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "wall_seconds": round(wall_seconds, 1),
        "total_runs": sum(s["runs"] for s in per_chain.values()),
        "total_pass": sum(s["pass"] for s in per_chain.values()),
        "total_no_data": sum(s["no_data"] for s in per_chain.values()),
        "total_fail": sum(s["fail"] for s in per_chain.values()),
        "total_infra_fail": sum(s["infra_fail"] for s in per_chain.values()),
        "total_included_signals": sum(s["included_signals_total"] for s in per_chain.values()),
        "total_net_usdc": round(sum(s["net_usdc_total"] for s in per_chain.values()), 4),
        "total_profitable_roundtrips": sum(s["profitable_roundtrips_total"] for s in per_chain.values()),
        "total_roundtrip_evaluated": sum(s.get("roundtrip_evaluated_total", 0) for s in per_chain.values()),
        "best_roundtrip_net_bps": max(
            (s["best_roundtrip_net_bps"] for s in per_chain.values() if s.get("best_roundtrip_net_bps") is not None),
            default=None,
        ),
        "best_measured_spread_gap_bps": max(
            (s["best_measured_spread_gap_bps"] for s in per_chain.values() if s.get("best_measured_spread_gap_bps") is not None),
            default=None,
        ),
        "pass_chains": pass_chains,
        "fail_chains": fail_chains,
        "accepted_fail_chains": accepted_fail_chains,
        "unexpected_fail_chains": unexpected_fail_chains,
        "probe_only_chains": probe_only_chains,
        "per_chain": per_chain,
        "warnings": warnings,
    }


def print_summary(summary: dict[str, Any]) -> None:
    print("\n" + "=" * 70)
    print("MULTI-CHAIN LONG SCAN SUMMARY")
    print("=" * 70)
    print(f"Wall time:      {summary['wall_seconds']:.0f}s")
    print(
        f"Total runs:     {summary['total_runs']}  "
        f"(PASS={summary['total_pass']}  NO_DATA={summary['total_no_data']}  "
        f"FAIL={summary['total_fail']}  INFRA_FAIL={summary['total_infra_fail']})"
    )
    print(f"Signals total:  {summary['total_included_signals']}")
    print(f"Net USDC total: ${summary['total_net_usdc']:.4f}")
    best_bps = summary.get('best_roundtrip_net_bps')
    best_str = f"{best_bps:+.2f} bps" if best_bps is not None else "n/a"
    gap_bps = summary.get('best_measured_spread_gap_bps')
    gap_str = f"{gap_bps:+.2f} bps" if gap_bps is not None else "n/a"
    print(f"Profitable RTs: {summary.get('total_profitable_roundtrips', 0)}  (evaluated: {summary.get('total_roundtrip_evaluated', 0)}, best: {best_str})")
    print(f"Spread gap:     {gap_str}  (measured, target: >=0)")

    pass_c = summary.get("pass_chains", [])
    fail_c = summary.get("fail_chains", [])
    accepted_c = summary.get("accepted_fail_chains", [])
    unexpected_c = summary.get("unexpected_fail_chains", [])
    probe_c = summary.get("probe_only_chains", [])
    if pass_c:
        print(f"Pass chains:    {', '.join(pass_c)}")
    if unexpected_c:
        print(f"Fail chains:    {', '.join(unexpected_c)}")
    if accepted_c:
        print(f"Accepted fail:  {', '.join(accepted_c)}")
    if probe_c:
        print(f"Probe-only:     {', '.join(probe_c)}")

    print("\n--- Per-chain breakdown ---")
    for chain, s in summary["per_chain"].items():
        print(
            f"  {chain:16s}  runs={s['runs']}  "
            f"PASS={s['pass']}  NO_DATA={s['no_data']}  FAIL={s['fail']}  "
            f"INFRA_FAIL={s['infra_fail']}  signals={s['included_signals_total']}  "
            f"net_usdc=${s['net_usdc_total']:.4f}"
        )
        quality = s.get("last_quality_status") or "-"
        level = s.get("last_chain_quality_level") or "-"
        truth = s.get("last_profit_truth_available")
        truth_s = str(truth) if truth is not None else "-"
        xdex = s.get("last_cross_dex_pairs_count")
        xdex_s = str(xdex) if xdex is not None else "-"
        print(
            f"  {'':16s}  quality={quality}  level={level}  "
            f"truth={truth_s}  cross_dex={xdex_s}"
        )

    if summary["warnings"]:
        print("\n--- WARNINGS ---")
        for w in summary["warnings"]:
            print(f"  [!] {w}")

    print("=" * 70)


def write_summary_file(summary: dict[str, Any], path: str) -> None:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)
    tmp.replace(out)
    print(f"Summary written to {out}")


# -- main -----------------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Multi-chain time-bounded online scan orchestrator"
    )
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument(
        "--config",
        help="Single config file (legacy mode, equivalent to --config-list with one entry)",
    )
    g.add_argument(
        "--config-list",
        help="Comma-separated list of config files for round-robin scanning",
    )
    ap.add_argument("--hours", type=float, default=0, help="Time limit in hours (takes precedence over --minutes)")
    ap.add_argument("--minutes", type=int, default=120, help="Time limit in minutes (ignored if --hours set)")
    ap.add_argument("--max-runs", type=int, default=0, help="0 = unlimited within time window")
    ap.add_argument("--sleep-seconds", type=int, default=20)
    ap.add_argument("--cycles", type=int, default=1)
    ap.add_argument("--prune-keep", type=int, default=200)
    ap.add_argument(
        "--child-timeout",
        type=int,
        default=600,
        help="Kill child process after this many seconds (0=no timeout)",
    )
    ap.add_argument(
        "--summary-file",
        default="data/runs/_incidents/long_scan_latest.json",
        help="Path to overwrite with session summary JSON",
    )
    ap.add_argument(
        "--max-fail-chains",
        type=int,
        default=-1,
        help="Max chains allowed to have failures. -1=permissive (exit 0 if any PASS), "
             "0=strict (all must PASS)",
    )
    ap.add_argument(
        "--accepted-fail-chains",
        default="",
        help="Comma-separated chain names whose failures are expected/accepted "
             "(e.g. 'scroll'). These do not count toward --max-fail-chains.",
    )
    return ap.parse_args(argv)


def resolve_configs(args: argparse.Namespace) -> list[str]:
    if args.config:
        return [args.config]
    return [c.strip() for c in args.config_list.split(",") if c.strip()]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    configs = resolve_configs(args)
    if not configs:
        print("ERROR: No config files specified")
        return 1

    # Pre-read config metadata
    config_meta: dict[str, dict[str, Any]] = {}
    for cfg in configs:
        meta = read_config_meta(cfg)
        config_meta[cfg] = meta
        rolling = "YES" if is_primary_rolling_config(meta) else "no"
        print(f"  [{meta['chain']:16s}] {cfg}  run_kind={meta['run_kind']}  rolling={rolling}")

    # Time budget
    if args.hours > 0:
        budget_seconds = args.hours * 3600
    else:
        budget_seconds = max(1, args.minutes) * 60
    deadline = time.monotonic() + budget_seconds

    # Accepted-fail chain set
    accepted_fail_set = {
        c.strip() for c in args.accepted_fail_chains.split(",") if c.strip()
    }

    # Per-chain stats keyed by chain name
    per_chain: dict[str, dict[str, Any]] = {}
    for cfg in configs:
        chain = config_meta[cfg]["chain"]
        if chain not in per_chain:
            per_chain[chain] = new_chain_stats()
            per_chain[chain]["config"] = cfg
            per_chain[chain]["accepted_fail"] = chain in accepted_fail_set

    total_runs = 0
    empty_deleted = 0
    wall_start = time.monotonic()

    print(f"\nStarting multi-chain scan: {len(configs)} configs, budget={budget_seconds:.0f}s")

    # Round-robin loop
    cfg_index = 0
    while time.monotonic() < deadline:
        cfg = configs[cfg_index % len(configs)]
        cfg_index += 1
        meta = config_meta[cfg]
        chain = meta["chain"]
        refresh = is_primary_rolling_config(meta)

        total_runs += 1
        print(f"\n{'-'*60}")
        print(f"[run {total_runs}] chain={chain}  config={cfg}  rolling={'YES' if refresh else 'no'}")

        rc, run_dir = run_gate_once(
            cfg, args.cycles, args.prune_keep, args.sleep_seconds,
            refresh_rolling=refresh,
            timeout_seconds=args.child_timeout,
        )

        summary = extract_run_summary(run_dir)
        gate_res = extract_gate_result(run_dir)
        cls = classify_run(rc, summary)

        update_chain_stats(per_chain[chain], rc, run_dir, summary, gate_res)
        print(f"[run {total_runs}] result={cls}  exit_code={rc}  run_dir={run_dir.name if run_dir else 'N/A'}")

        if run_dir and run_dir.exists():
            if delete_if_empty_run_dir(run_dir):
                empty_deleted += 1

        if total_runs % max(len(configs), 3) == 0:
            prune_run_dirs(args.prune_keep)

        if args.max_runs > 0 and total_runs >= args.max_runs:
            break
        if time.monotonic() >= deadline:
            break

        time.sleep(max(1, args.sleep_seconds))

    # Final report
    wall_seconds = time.monotonic() - wall_start
    warnings = check_guardrails(per_chain)
    summary_obj = build_summary(per_chain, wall_seconds, warnings)
    print_summary(summary_obj)

    write_summary_file(summary_obj, args.summary_file)

    # Exit semantics — accepted-fail chains don't count toward limit
    unexpected_fail_count = len(summary_obj.get("unexpected_fail_chains", []))
    has_any_pass = summary_obj["total_pass"] > 0

    if args.max_fail_chains >= 0:
        # Strict mode: exit 1 if too many unexpected chains failed
        if unexpected_fail_count > args.max_fail_chains:
            print(f"EXIT 1: {unexpected_fail_count} unexpected fail chain(s) > --max-fail-chains={args.max_fail_chains}")
            return 1
        if not has_any_pass:
            print("EXIT 1: no PASS runs at all")
            return 1
        return 0
    else:
        # Permissive (default): exit 0 if any PASS
        return 0 if has_any_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
