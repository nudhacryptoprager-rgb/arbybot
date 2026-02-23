#!/usr/bin/env python3
"""
start.py - Time-bounded online scan runner.

- Runs scripts/ci_m5_0_gate.py in ONLINE single-run mode in a loop.
- Enforces retention via scripts/prune_run_dirs.py.
- Deletes empty ci_m5_gate_* runDirs (no reports/) to prevent disk bloat.

Runtime artifacts stay under data/runs/** and must never be committed.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path
import re


RUNS_DIR = Path("data") / "runs"
CI_GATE = Path("scripts") / "ci_m5_0_gate.py"
RUN_DIR_RE = re.compile(r"^\[ONLINE\] RunDir:\s*(.+)\s*$")
CI_M5_DIR_RE = re.compile(r"^ci_m5_gate_\d{8}_\d{6}$")


def run_gate_once(config: str, cycles: int, prune_keep: int, sleep_seconds: int) -> tuple[int, Path | None]:
    cmd = [
        sys.executable,
        str(CI_GATE),
        "--online",
        "--config",
        config,
        "--cycles",
        str(cycles),
        "--refresh-rolling",
        "--refresh-rolling-strict",
        "--prune-keep",
        str(prune_keep),
        "--sleep-seconds",
        str(sleep_seconds),
    ]

    run_dir: Path | None = None
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    assert proc.stdout is not None

    for line in proc.stdout:
        sys.stdout.write(line)
        m = RUN_DIR_RE.match(line.strip())
        if m:
            run_dir = Path(m.group(1).strip())

    rc = proc.wait()
    return rc, run_dir


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


def main() -> int:
    ap = argparse.ArgumentParser(description="Time-bounded online scan runner (non-stop demo)")
    ap.add_argument("--config", default="config/real_minimal.yaml")
    ap.add_argument("--minutes", type=int, default=120)
    ap.add_argument("--max-runs", type=int, default=0, help="0 = unlimited within time window")
    ap.add_argument("--sleep-seconds", type=int, default=20)
    ap.add_argument("--cycles", type=int, default=1)
    ap.add_argument("--prune-keep", type=int, default=200)
    args = ap.parse_args()

    deadline = time.monotonic() + max(1, args.minutes) * 60
    runs = 0
    passed = 0
    failed = 0
    empty_deleted = 0

    while time.monotonic() < deadline:
        runs += 1
        rc, run_dir = run_gate_once(args.config, args.cycles, args.prune_keep, args.sleep_seconds)
        if rc == 0:
            passed += 1
        else:
            failed += 1

        if run_dir and run_dir.exists():
            if delete_if_empty_run_dir(run_dir):
                empty_deleted += 1

        prune_run_dirs(args.prune_keep)

        if args.max_runs > 0 and runs >= args.max_runs:
            break

        if time.monotonic() >= deadline:
            break

        time.sleep(max(1, args.sleep_seconds))

    print("=" * 60)
    print("NON-STOP SUMMARY")
    print("=" * 60)
    print(f"runs:          {runs}")
    print(f"passed:        {passed}")
    print(f"failed:        {failed}")
    print(f"empty_deleted: {empty_deleted}")
    return 0 if passed > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
