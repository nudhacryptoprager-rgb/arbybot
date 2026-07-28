#!/usr/bin/env python3
"""Long-lived continuous pipeline worker process."""
from __future__ import annotations

import argparse
import os
import sys
import time

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from core.continuous_broker import (  # noqa: E402
    run_broker_loop,
    seed_pool_discovered,
)
from core.continuous_pipeline import WORKER_M81_PROBE  # noqa: E402
from scripts.continuous_handler_wiring import build_wired_orchestrator  # noqa: E402


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run one continuous pipeline worker loop")
    p.add_argument("--worker", default=WORKER_M81_PROBE, help="Worker job_type to drain")
    p.add_argument("--session-id", default=os.environ.get("ARBY_PIPELINE_SESSION_ID", ""))
    p.add_argument("--max-rounds", type=int, default=0, help="0 = run until SIGTERM")
    p.add_argument("--poll-interval-s", type=float, default=1.0)
    p.add_argument("--seed-pool", default=None, help="Optional pool address to seed (dev/dry-run)")
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    session_id = str(args.session_id or "").strip()
    if not session_id:
        from start import new_pipeline_session_id

        session_id = new_pipeline_session_id()
    orch = build_wired_orchestrator(session_id)
    if args.seed_pool:
        seed_pool_discovered(orch, pool_address=str(args.seed_pool))
    rounds = 0
    while True:
        if args.worker == "broker":
            run_broker_loop(orch, max_rounds=1, idle_exit_rounds=1)
        else:
            orch.process_worker_jobs(args.worker, limit=8, lease_s=orch.policy.work_item_lease_s)
        rounds += 1
        if args.max_rounds and rounds >= args.max_rounds:
            break
        time.sleep(max(0.05, float(args.poll_interval_s)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
