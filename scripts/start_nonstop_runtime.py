#!/usr/bin/env python3
"""
M7.A.5.32 — Unified nonstop runtime supervisor.

Launches 4 managed subprocesses as one runtime stack:
  1. Dashboard server (monitoring.dashboard_server)
  2. M4/M5 scan orchestrator (start.py --no-dashboard)
  3. M7 hot lane (m7a_orderflow_loop.py --lane hot)
  4. M7 cold lane (m7a_orderflow_loop.py --lane cold)

Separate from start.py: start.py remains the thin M4/M5 orchestrator.
This script adds M7 nonstop loops + health/restart semantics on top.

Usage:
    py -3.11 scripts/start_nonstop_runtime.py --hours 1
    py -3.11 scripts/start_nonstop_runtime.py --hours 4 --m7-hot-pause 1 --m7-cold-pause 5
    py -3.11 scripts/start_nonstop_runtime.py --hours 0.5 --dashboard-port 8099 --no-m4
    py -3.11 scripts/start_nonstop_runtime.py --hours 1 --with-discovery
"""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))


def parse_args():
    ap = argparse.ArgumentParser(
        description="M7.A.5.32: Unified nonstop runtime supervisor"
    )
    ap.add_argument("--hours", type=float, default=1.0, help="Total runtime hours (default: 1)")
    ap.add_argument("--dashboard-port", type=int, default=8099)
    ap.add_argument("--config", default="config/real_minimal.yaml", help="M4/M5 config")
    ap.add_argument("--m4-sleep-seconds", type=int, default=20)
    ap.add_argument("--m4-prune-keep", type=int, default=50)
    ap.add_argument("--m7-hot-pause", type=int, default=1)
    ap.add_argument("--m7-cold-pause", type=int, default=5)
    ap.add_argument("--m7-hot-blocks", type=int, default=20)
    ap.add_argument("--m7-cold-blocks", type=int, default=300)
    ap.add_argument("--no-m4", action="store_true", help="Skip M4/M5 scan orchestrator")
    ap.add_argument("--no-m7-cold", action="store_true", help="Skip M7 cold lane")
    ap.add_argument("--chain", type=str, default="arbitrum_one",
                    help="Chain for M7 lanes (default: arbitrum_one)")
    ap.add_argument("--m7-profile", type=str, default="production",
                    choices=["production", "discovery"],
                    dest="m7_profile",
                    help="M7 pair profile: production (narrow) or discovery (wider contour)")
    ap.add_argument("--with-discovery", action="store_true",
                    help="Also launch parallel discovery hot+cold lanes alongside production")
    ap.add_argument("--restart-delay", type=int, default=5, help="Seconds before restarting a crashed process")
    ap.add_argument("--max-restarts", type=int, default=10, help="Max restarts per process before giving up")
    return ap.parse_args()


class ManagedProcess:
    """A subprocess with restart semantics."""

    def __init__(self, name: str, cmd: list[str], restart_delay: int, max_restarts: int):
        self.name = name
        self.cmd = cmd
        self.restart_delay = restart_delay
        self.max_restarts = max_restarts
        self.proc: subprocess.Popen | None = None
        self.restarts = 0
        self.started_at: float = 0
        self.stopped = False

    def start(self) -> None:
        if self.stopped:
            return
        # M7.A.5.40: Redirect stdout/stderr to DEVNULL instead of PIPE.
        # On Windows, PIPE readline() is blocking — drain_output() would
        # stall the supervisor's health check loop, preventing deadline
        # termination. Child processes write to rolling artifacts, not stdout.
        self.proc = subprocess.Popen(
            self.cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.started_at = time.monotonic()
        print(f"  [{self.name}] Started (PID {self.proc.pid}): {' '.join(self.cmd[:4])}...")

    def check_and_restart(self) -> bool:
        """Check if process is alive. Restart if crashed. Return False if max restarts hit."""
        if self.stopped or self.proc is None:
            return True
        rc = self.proc.poll()
        if rc is None:
            return True  # still running
        uptime = time.monotonic() - self.started_at
        print(
            f"  [{self.name}] Exited with code {rc} after {uptime:.0f}s "
            f"(restarts: {self.restarts}/{self.max_restarts})"
        )
        if self.restarts >= self.max_restarts:
            print(f"  [{self.name}] Max restarts reached, giving up")
            self.stopped = True
            return False
        self.restarts += 1
        time.sleep(self.restart_delay)
        self.start()
        return True

    def terminate(self) -> None:
        self.stopped = True
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            print(f"  [{self.name}] Terminated")

    def drain_output(self) -> list[str]:
        """No-op: stdout redirected to DEVNULL (M7.A.5.40).

        Previous PIPE-based drain was blocking on Windows, causing the
        supervisor to miss its deadline and never terminate children.
        """
        return []


def main():
    args = parse_args()
    py = sys.executable
    deadline = time.monotonic() + args.hours * 3600

    print(f"=== Nonstop Runtime Supervisor ===")
    print(f"  Started: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}")
    print(f"  Runtime: {args.hours}h")
    print(f"  Dashboard: http://127.0.0.1:{args.dashboard_port}")

    processes: list[ManagedProcess] = []

    # 1. Dashboard
    processes.append(ManagedProcess(
        "dashboard",
        [py, "-m", "monitoring.dashboard_server", "--port", str(args.dashboard_port)],
        restart_delay=args.restart_delay,
        max_restarts=args.max_restarts,
    ))

    # 2. M4/M5 scan orchestrator
    if not args.no_m4:
        m4_hours = max(0.1, args.hours - 0.01)  # slightly shorter than supervisor
        processes.append(ManagedProcess(
            "m4_scan",
            [
                py, "start.py",
                "--config", args.config,
                "--hours", str(m4_hours),
                "--sleep-seconds", str(args.m4_sleep_seconds),
                "--no-dashboard",
                "--prune-keep", str(args.m4_prune_keep),
            ],
            restart_delay=args.restart_delay,
            max_restarts=args.max_restarts,
        ))

    # 3. M7 hot lane
    processes.append(ManagedProcess(
        "m7_hot",
        [
            py, "scripts/m7a_orderflow_loop.py",
            "--lane", "hot",
            "--chain", args.chain,
            "--profile", args.m7_profile,
            "--ws-blocks", str(args.m7_hot_blocks),
            "--pause", str(args.m7_hot_pause),
        ],
        restart_delay=args.restart_delay,
        max_restarts=args.max_restarts,
    ))

    # 4. M7 cold lane
    if not args.no_m7_cold:
        processes.append(ManagedProcess(
            "m7_cold",
            [
                py, "scripts/m7a_orderflow_loop.py",
                "--lane", "cold",
                "--chain", args.chain,
                "--profile", args.m7_profile,
                "--ws-blocks", str(args.m7_cold_blocks),
                "--pause", str(args.m7_cold_pause),
            ],
            restart_delay=args.restart_delay,
            max_restarts=args.max_restarts,
        ))

    # 5. Discovery lanes (parallel to production)
    if args.with_discovery and args.m7_profile == "production":
        processes.append(ManagedProcess(
            "m7_hot_discovery",
            [
                py, "scripts/m7a_orderflow_loop.py",
                "--lane", "hot",
                "--chain", args.chain,
                "--profile", "discovery",
                "--ws-blocks", str(args.m7_hot_blocks),
                "--pause", str(args.m7_hot_pause),
            ],
            restart_delay=args.restart_delay,
            max_restarts=args.max_restarts,
        ))
        if not args.no_m7_cold:
            processes.append(ManagedProcess(
                "m7_cold_discovery",
                [
                    py, "scripts/m7a_orderflow_loop.py",
                    "--lane", "cold",
                    "--chain", args.chain,
                    "--profile", "discovery",
                    "--ws-blocks", str(args.m7_cold_blocks),
                    "--pause", str(args.m7_cold_pause),
                ],
                restart_delay=args.restart_delay,
                max_restarts=args.max_restarts,
            ))

    # Start all
    for p in processes:
        p.start()

    # Handle graceful shutdown
    _shutdown = False

    def _signal_handler(sig, frame):
        nonlocal _shutdown
        _shutdown = True
        print("\n  Shutdown signal received, terminating all processes...")

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    # Health check loop
    check_interval = 10  # seconds
    status_interval = 60  # seconds
    last_status = time.monotonic()

    try:
        while not _shutdown and time.monotonic() < deadline:
            # Health check
            all_ok = True
            for p in processes:
                # M7.A.5.39: Drain stdout to prevent pipe buffer stalls
                p.drain_output()
                if not p.check_and_restart():
                    all_ok = False

            # Periodic status
            now = time.monotonic()
            if now - last_status >= status_interval:
                remaining = max(0, deadline - now)
                alive = sum(1 for p in processes if p.proc and p.proc.poll() is None)
                print(
                    f"  [supervisor] {alive}/{len(processes)} alive, "
                    f"{remaining / 60:.1f}min remaining, "
                    f"restarts: {sum(p.restarts for p in processes)}"
                )
                last_status = now

            time.sleep(check_interval)
    finally:
        print(f"\n  Shutting down all processes...")
        for p in processes:
            p.terminate()
        print(
            f"  Supervisor finished at "
            f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
