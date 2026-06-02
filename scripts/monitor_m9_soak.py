#!/usr/bin/env python3
"""Poll m9_graph_latest.json while a soak PID runs; exit 1 on anomaly."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path


def _stop_pid(pid: int) -> None:
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/F"],
            check=False,
            capture_output=True,
        )
    else:
        os.kill(pid, 15)


def _load_graph(path: Path) -> dict:
    try:
        with path.open(encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--pid", type=int, required=True)
    p.add_argument("--graph", default="data/runs/_rolling/m9_graph_latest.json")
    p.add_argument("--interval-sec", type=float, default=60.0)
    p.add_argument("--min-sweeps-before-qsr-stop", type=int, default=12)
    p.add_argument("--max-quote-429", type=int, default=80)
    p.add_argument("--min-qsr", type=float, default=0.05)
    args = p.parse_args()

    graph_path = Path(args.graph)
    last_mtime = 0.0
    print(f"monitor: pid={args.pid} graph={graph_path}", flush=True)

    while _pid_alive(args.pid):
        time.sleep(args.interval_sec)
        if not graph_path.exists():
            print("monitor: WARN graph missing", flush=True)
            continue
        mtime = graph_path.stat().st_mtime
        if mtime <= last_mtime:
            print("monitor: WARN graph stale (no updates)", flush=True)
            continue
        last_mtime = mtime
        d = _load_graph(graph_path)
        sweeps = int(d.get("sweeps_completed") or 0)
        qsr = float(d.get("qsr") or 0.0)
        infra = d.get("infra_telemetry") or {}
        q429 = int(infra.get("quote_429_count") or infra.get("http_429_count") or 0)
        econ = d.get("economics_gate_status") or ""
        print(
            f"monitor: sweeps={sweeps} qsr={qsr:.4f} quote_429={q429} gate={econ}",
            flush=True,
        )
        if q429 >= args.max_quote_429:
            print(f"monitor: STOP quote_429={q429} >= {args.max_quote_429}", flush=True)
            _stop_pid(args.pid)
            return 1
        if sweeps >= args.min_sweeps_before_qsr_stop and qsr < args.min_qsr:
            print(
                f"monitor: STOP qsr={qsr} < {args.min_qsr} after {sweeps} sweeps",
                flush=True,
            )
            _stop_pid(args.pid)
            return 1

    print("monitor: runner exited", flush=True)
    d = _load_graph(graph_path)
    sweeps = int(d.get("sweeps_completed") or 0)
    qsr = float(d.get("qsr") or 0.0)
    print(f"monitor: final sweeps={sweeps} qsr={qsr:.4f}", flush=True)
    return 0 if sweeps > 0 else 2


if __name__ == "__main__":
    sys.exit(main())
