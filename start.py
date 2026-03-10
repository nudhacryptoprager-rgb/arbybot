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

# ── config introspection ────────────────────────────────────────────────


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


# ── child process ───────────────────────────────────────────────────────


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


# ── run_summary extraction ──────────────────────────────────────────────


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


# ── housekeeping ────────────────────────────────────────────────────────


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


# ── per-chain aggregation ──────────────────────────────────────────────


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
        "last_run_timestamp": None,
        "last_run_dir": None,
    }


def update_chain_stats(
    stats: dict[str, Any],
    exit_code: int,
    run_dir: Path | None,
    summary: dict[str, Any] | None,
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
        rt = summary.get("roundtrip_summary", {})
        stats["profitable_roundtrips_total"] += int(rt.get("profitable_count", 0) or 0)
        ctx = summary.get("run_context", {})
        stats["last_run_timestamp"] = ctx.get("run_timestamp", stats["last_run_timestamp"])

    if run_dir:
        stats["last_run_dir"] = str(run_dir.name)


# ── guardrails ──────────────────────────────────────────────────────────


def check_guardrails(per_chain: dict[str, dict[str, Any]]) -> list[str]:
    """Return list of warning strings for suspicious patterns."""
    warnings: list[str] = []
    total_runs = sum(s["runs"] for s in per_chain.values())
    total_pass = sum(s["pass"] for s in per_chain.values())
    total_fail = sum(s["fail"] for s in per_chain.values())
    total_no_data = sum(s["no_data"] for s in per_chain.values())

    if total_runs >= 5 and total_fail == 0 and total_no_data == 0:
        warnings.append(
            "ALL_POSITIVE: Every run PASS, zero FAIL/NO_DATA — "
            "verify against Roadmap.md Truth Engine expectation"
        )

    for chain, s in per_chain.items():
        if s["runs"] >= 3 and s["pass"] > 0 and s["fail"] == 0 and s["no_data"] == 0:
            warnings.append(
                f"CHAIN_ALL_POSITIVE [{chain}]: {s['runs']} runs all PASS — "
                "check if data quality is real"
            )
        if s["runs"] >= 3 and s["infra_fail"] > s["runs"] * 0.5:
            warnings.append(
                f"CHAIN_INFRA_UNSTABLE [{chain}]: >{50}% runs had infra failures"
            )

    return warnings


# ── summary output ──────────────────────────────────────────────────────


def build_summary(
    per_chain: dict[str, dict[str, Any]],
    wall_seconds: float,
    warnings: list[str],
) -> dict[str, Any]:
    return {
        "schema": "start:long_scan_summary:v1.0",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "wall_seconds": round(wall_seconds, 1),
        "total_runs": sum(s["runs"] for s in per_chain.values()),
        "total_pass": sum(s["pass"] for s in per_chain.values()),
        "total_no_data": sum(s["no_data"] for s in per_chain.values()),
        "total_fail": sum(s["fail"] for s in per_chain.values()),
        "total_infra_fail": sum(s["infra_fail"] for s in per_chain.values()),
        "total_included_signals": sum(s["included_signals_total"] for s in per_chain.values()),
        "total_net_usdc": round(sum(s["net_usdc_total"] for s in per_chain.values()), 4),
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

    print("\n--- Per-chain breakdown ---")
    for chain, s in summary["per_chain"].items():
        print(
            f"  {chain:16s}  runs={s['runs']}  "
            f"PASS={s['pass']}  NO_DATA={s['no_data']}  FAIL={s['fail']}  "
            f"INFRA_FAIL={s['infra_fail']}  signals={s['included_signals_total']}  "
            f"net_usdc=${s['net_usdc_total']:.4f}"
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


# ── main ────────────────────────────────────────────────────────────────


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

    # Per-chain stats keyed by chain name
    per_chain: dict[str, dict[str, Any]] = {}
    for cfg in configs:
        chain = config_meta[cfg]["chain"]
        if chain not in per_chain:
            per_chain[chain] = new_chain_stats()
            per_chain[chain]["config"] = cfg

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
        print(f"\n{'─'*60}")
        print(f"[run {total_runs}] chain={chain}  config={cfg}  rolling={'YES' if refresh else 'no'}")

        rc, run_dir = run_gate_once(
            cfg, args.cycles, args.prune_keep, args.sleep_seconds,
            refresh_rolling=refresh,
            timeout_seconds=args.child_timeout,
        )

        summary = extract_run_summary(run_dir)
        cls = classify_run(rc, summary)

        update_chain_stats(per_chain[chain], rc, run_dir, summary)
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

    has_any_pass = summary_obj["total_pass"] > 0
    return 0 if has_any_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())
