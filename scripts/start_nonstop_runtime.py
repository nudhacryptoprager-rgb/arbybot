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
import threading
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
    # M7.E1.34e: bumped default hot/cold blocks per reviewer ask after
    # 30m STF soak (2026-04-21) where the previous default of 20 caused
    # bounded workers to clean-exit every ~30s and exhaust restart budget
    # before useful funnel activity occurred.
    ap.add_argument("--m7-hot-blocks", type=int, default=3600)
    # M7.E1.34e: bumped from 300 to 900 in line with --m7-hot-blocks.
    # M7.E1.34k: bumped both hot and cold to 3600 — soak4 showed cycles
    # clean-exiting every ~55s and losing prewarm work on each restart.
    ap.add_argument("--m7-cold-blocks", type=int, default=3600)
    # M7.E1.34l: per-window caps that the inner worker honours.
    # loop_runner._LANE_DEFAULTS['hot'] sets max_events=5 / ws_timeout=30
    # which caused the supervised 3600-block soak to clean-exit every
    # 30-120s (after 5 events OR 30s idle), rotating session_id and
    # collapsing reviewer session-scoped totals. The supervisor now
    # passes generous soak-sized caps so one window really lasts
    # --m7-hot-blocks, not the first lane-default cap that trips.
    ap.add_argument("--m7-hot-max-events", type=int, default=500,
                    help="Max events per hot window (soak default 500; "
                         "loop-runner hot default is 5).")
    ap.add_argument("--m7-hot-ws-timeout", type=int, default=120,
                    help="Idle-window timeout in seconds for hot lane "
                         "(active-window default 120s; loop-runner hot default is 30).")
    ap.add_argument("--m7-cold-max-events", type=int, default=500,
                    help="Max events per cold window (soak default 500).")
    ap.add_argument("--m7-cold-ws-timeout", type=int, default=240,
                    help="Idle-window timeout in seconds for cold lane "
                         "(E1.77: lowered 900→240s for Base profile so the cold "
                         "WS reconnect cadence matches the median lag-window).")
    ap.add_argument("--no-m4", action="store_true", help="Skip M4/M5 scan orchestrator")
    ap.add_argument("--no-m7-cold", action="store_true", help="Skip M7 cold lane")
    # E1.65 Step 7: HTTP block polling for cold lanes — reduces WS connections
    # from 4 (hot_prod + cold_prod + hot_disc + cold_disc) to 2 (hot lanes only).
    ap.add_argument(
        "--cold-http-only",
        action="store_true",
        dest="cold_http_only",
        help=(
            "Use HTTP block polling instead of WS subscription for cold lanes "
            "(sets ARBY_WS_HTTP_BLOCKS=1 for cold subprocesses). "
            "Reduces WS connections from 4 to 2 under 4-lane supervisor mode."
        ),
    )
    ap.add_argument("--chain", type=str, default="arbitrum_one",
                    help="Chain for M7 lanes (default: arbitrum_one)")
    ap.add_argument("--m7-profile", type=str, default="production",
                    choices=["production", "discovery"],
                    dest="m7_profile",
                    help="M7 pair profile: production (narrow) or discovery (wider contour)")
    ap.add_argument("--with-discovery", action="store_true",
                    help="Also launch parallel discovery hot+cold lanes alongside production")
    # E1.65 Step 9: delay discovery lanes after production is warm.
    # Default 600s (10 min) avoids WS 429 storms from 4 simultaneous
    # WS subscriptions on startup. Set to 0 to disable (legacy behaviour).
    ap.add_argument(
        "--discovery-warmup-delay-s",
        type=int,
        default=600,
        dest="discovery_warmup_delay_s",
        help=(
            "Seconds to wait after production lanes start before starting "
            "discovery lanes (default: 600). Set to 0 for immediate start."
        ),
    )
    ap.add_argument("--with-anvil", action="store_true",
                    help="P4: Start local Anvil fork and route sim backend to anvil (x5 speed)")
    ap.add_argument("--anvil-port", type=int, default=8545,
                    help="Local Anvil RPC port (default 8545)")
    ap.add_argument("--restart-delay", type=int, default=5, help="Seconds before restarting a crashed process")
    ap.add_argument(
        "--max-restarts", type=int, default=100,
        help=(
            "Max CRASH restarts per process before giving up. M7.E1.34e: "
            "clean cycle exits (rc==0 from bounded workers) no longer "
            "consume this budget; only non-zero exits do."
        ),
    )
    return ap.parse_args()


class ManagedProcess:
    """A subprocess with restart semantics."""

    def __init__(
        self,
        name: str,
        cmd: list[str],
        restart_delay: int,
        max_restarts: int,
        env: dict[str, str] | None = None,
    ):
        self.name = name
        self.cmd = cmd
        self.restart_delay = restart_delay
        self.max_restarts = max_restarts
        # E1.35 P0.1-wiring: per-process env override. None → inherit from supervisor
        # (os.environ). dict → merge over os.environ so callers only specify deltas.
        self.env = env
        self.proc: subprocess.Popen | None = None
        # M7.E1.34e: split restart accounting so bounded clean exits
        # (rc==0 from --ws-blocks N completion) don't burn the crash
        # budget that protects against actual failures.
        self.restarts = 0          # legacy total (clean+crash) for back-compat logs
        self.cycles_completed = 0  # rc==0 clean exits
        self.crash_restarts = 0    # rc!=0 exits (consumed budget)
        self.max_crash_restarts_hit = False
        self.started_at: float = 0
        self.stopped = False

    def start(self) -> None:
        if self.stopped:
            return
        # M7.A.5.40: Redirect stdout/stderr to DEVNULL instead of PIPE.
        # On Windows, PIPE readline() is blocking — drain_output() would
        # stall the supervisor's health check loop, preventing deadline
        # termination. Child processes write to rolling artifacts, not stdout.
        _env = None
        if self.env:
            _env = {**os.environ, **self.env}
        self.proc = subprocess.Popen(
            self.cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            env=_env,
        )
        self.started_at = time.monotonic()
        print(f"  [{self.name}] Started (PID {self.proc.pid}): {' '.join(self.cmd[:4])}...")

    def check_and_restart(self) -> bool:
        """Check process health.

        M7.E1.34e: distinguish clean cycle completion (rc==0 from bounded
        --ws-blocks workers) from crashes (rc!=0). Only crashes consume
        the --max-restarts budget; clean exits increment cycles_completed
        and always relaunch unconditionally so the supervisor keeps
        feeding the funnel until its own deadline.
        """
        if self.stopped or self.proc is None:
            return True
        rc = self.proc.poll()
        if rc is None:
            return True  # still running
        uptime = time.monotonic() - self.started_at
        is_clean = (rc == 0)
        if is_clean:
            self.cycles_completed += 1
            self.restarts += 1
            print(
                f"  [{self.name}] Clean cycle exit rc=0 after {uptime:.0f}s "
                f"(cycles_completed={self.cycles_completed}, "
                f"crash_restarts={self.crash_restarts}/{self.max_restarts})"
            )
            time.sleep(self.restart_delay)
            self.start()
            return True
        # Crash path — consumes budget.
        print(
            f"  [{self.name}] CRASH exit rc={rc} after {uptime:.0f}s "
            f"(cycles_completed={self.cycles_completed}, "
            f"crash_restarts={self.crash_restarts}/{self.max_restarts})"
        )
        if self.crash_restarts >= self.max_restarts:
            print(f"  [{self.name}] Max CRASH restarts reached, giving up")
            self.max_crash_restarts_hit = True
            self.stopped = True
            return False
        self.crash_restarts += 1
        self.restarts += 1
        time.sleep(self.restart_delay)
        self.start()
        return True

    def terminate(self) -> None:
        self.stopped = True
        if self.proc and self.proc.poll() is None:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/F", "/PID", str(self.proc.pid), "/T"],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            else:
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
    _supervisor_start = time.monotonic()  # E1.65: used for discovery warmup delay

    print(f"=== Nonstop Runtime Supervisor ===")
    print(f"  Started: {datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}")
    print(f"  Runtime: {args.hours}h")
    print(f"  Dashboard: http://127.0.0.1:{args.dashboard_port}")

    # P1 (2026-04-20): Auto-enable Flashblocks sim on Base when supervisor
    # launches. Opt-out via ``ARBY_FLASHBLOCKS_SIM=0``. Gives 1-2 blocks
    # (~2-4s) of pre-confirmed state for rpc_fork/tenderly eth_call, which
    # directly improves stale_gate pass rate for Base's 2s blocks.
    if args.chain == "base":
        _fb_sim = os.environ.get("ARBY_FLASHBLOCKS_SIM", "").strip()
        if _fb_sim == "":
            os.environ["ARBY_FLASHBLOCKS_SIM"] = "1"
            print("  [P1] ARBY_FLASHBLOCKS_SIM=1 (auto-enabled for Base)")
        elif _fb_sim == "0":
            print("  [P1] ARBY_FLASHBLOCKS_SIM=0 (explicit opt-out, Base)")
        else:
            print(f"  [P1] ARBY_FLASHBLOCKS_SIM={_fb_sim} (honored from env)")
        _fb_http = os.environ.get("ARBY_FLASHBLOCKS_HTTP", "").strip()
        if not _fb_http:
            os.environ["ARBY_FLASHBLOCKS_HTTP"] = "https://mainnet-preconf.base.org"
            print("  [P1] ARBY_FLASHBLOCKS_HTTP=https://mainnet-preconf.base.org (default)")

    processes: list[ManagedProcess] = []

    # P4 (2026-04-20): optional local Anvil fork. Wires ARBY_SIM_BACKEND=anvil
    # and ARBY_ANVIL_RPC_URL so hot/cold lanes route simulations through the
    # local fork (~x5 speed vs Tenderly, 0 rate-limit). Opt-in via --with-anvil.
    if args.with_anvil:
        _anvil_port = args.anvil_port
        _anvil_url = f"http://127.0.0.1:{_anvil_port}"
        os.environ["ARBY_SIM_BACKEND"] = "anvil"
        os.environ["ARBY_ANVIL_RPC_URL"] = _anvil_url
        print(f"  [P4] ARBY_SIM_BACKEND=anvil, ARBY_ANVIL_RPC_URL={_anvil_url}")
        processes.append(ManagedProcess(
            "anvil_fork",
            [py, "scripts/start_anvil_fork.py",
             "--chain", args.chain, "--port", str(_anvil_port)],
            restart_delay=args.restart_delay,
            max_restarts=args.max_restarts,
        ))

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
            "--ws-timeout", str(args.m7_hot_ws_timeout),
            "--max-events", str(args.m7_hot_max_events),
            "--pause", str(args.m7_hot_pause),
        ],
        restart_delay=args.restart_delay,
        max_restarts=args.max_restarts,
    ))

    # 4. M7 cold lane
    if not args.no_m7_cold:
        # E1.65 Step 7: pass ARBY_WS_HTTP_BLOCKS=1 when --cold-http-only
        _cold_env: dict[str, str] | None = None
        if getattr(args, "cold_http_only", False):
            _cold_env = {"ARBY_WS_HTTP_BLOCKS": "1"}
            print("  [cold lane] ARBY_WS_HTTP_BLOCKS=1 (HTTP block polling mode)")
        processes.append(ManagedProcess(
            "m7_cold",
            [
                py, "scripts/m7a_orderflow_loop.py",
                "--lane", "cold",
                "--chain", args.chain,
                "--profile", args.m7_profile,
                "--ws-blocks", str(args.m7_cold_blocks),
                "--ws-timeout", str(args.m7_cold_ws_timeout),
                "--max-events", str(args.m7_cold_max_events),
                "--pause", str(args.m7_cold_pause),
            ],
            restart_delay=args.restart_delay,
            max_restarts=args.max_restarts,
            env=_cold_env,
        ))

    # 5. Discovery lanes (parallel to production)
    # E1.65 Step 9: discovery processes are deferred by --discovery-warmup-delay-s
    # (default 600s) to avoid WS 429 storms on startup. When warmup delay = 0,
    # discovery starts immediately (legacy behaviour).
    _discovery_processes: list[ManagedProcess] = []  # deferred until warmup elapsed
    if args.with_discovery and args.m7_profile == "production":
        # E1.35 P0.1-wiring: promote ARBY_SIM_BACKEND_DISC (set on the supervisor)
        # into the DISC subprocess as its effective ARBY_SIM_BACKEND.
        # PROD lanes keep whatever ARBY_SIM_BACKEND / ARBY_SIM_BACKEND_PROD
        # the supervisor inherited (handled via env inheritance; we only inject
        # the delta here).
        _disc_backend = os.environ.get("ARBY_SIM_BACKEND_DISC", "").strip()
        _disc_env: dict[str, str] | None = None
        if _disc_backend:
            _disc_env = {"ARBY_SIM_BACKEND": _disc_backend}
            print(
                f"  [discovery] ARBY_SIM_BACKEND_DISC={_disc_backend} -> "
                "injected into DISC subprocesses as ARBY_SIM_BACKEND"
            )

        _discovery_processes.append(ManagedProcess(
            "m7_hot_discovery",
            [
                py, "scripts/m7a_orderflow_loop.py",
                "--lane", "hot",
                "--chain", args.chain,
                "--profile", "discovery",
                "--ws-blocks", str(args.m7_hot_blocks),
                "--ws-timeout", str(args.m7_hot_ws_timeout),
                "--max-events", str(args.m7_hot_max_events),
                "--pause", str(args.m7_hot_pause),
            ],
            restart_delay=args.restart_delay,
            max_restarts=args.max_restarts,
            env=_disc_env,
        ))
        if not args.no_m7_cold:
            # E1.65: merge cold-http-only into disc env if both flags set
            _disc_cold_env = _disc_env
            if getattr(args, "cold_http_only", False):
                _disc_cold_env = {**(_disc_env or {}), "ARBY_WS_HTTP_BLOCKS": "1"}
            _discovery_processes.append(ManagedProcess(
                "m7_cold_discovery",
                [
                    py, "scripts/m7a_orderflow_loop.py",
                    "--lane", "cold",
                    "--chain", args.chain,
                    "--profile", "discovery",
                    "--ws-blocks", str(args.m7_cold_blocks),
                    "--ws-timeout", str(args.m7_cold_ws_timeout),
                    "--max-events", str(args.m7_cold_max_events),
                    "--pause", str(args.m7_cold_pause),
                ],
                restart_delay=args.restart_delay,
                max_restarts=args.max_restarts,
                env=_disc_cold_env,
            ))

    # Start production processes immediately
    for p in processes:
        p.start()

    # TVL scout background thread — opt-in via ARBY_TVL_SCOUT_ENABLE=1.
    # Fetches DefiLlama Base pool TVL once per hour and writes
    # data/runs/_rolling/m7_tvl_scout_latest.json so the cold lane scorer
    # and reviewers can audit production-size pool coverage.
    def _tvl_scout_loop() -> None:
        import json as _json
        _rolling = Path("data/runs/_rolling")
        _rolling.mkdir(parents=True, exist_ok=True)
        _out = _rolling / "m7_tvl_scout_latest.json"
        while True:
            try:
                from m7.scouts.tvl_scout import fetch_defillama_pools, select_production_pools
                _pools = fetch_defillama_pools()
                _prod = select_production_pools(_pools)
                _payload = {
                    "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "pool_count": len(_prod),
                    "pools": [_p.to_dict() for _p in _prod],
                }
                _tmp = _out.with_suffix(".tmp")
                _tmp.write_text(_json.dumps(_payload, indent=2), encoding="utf-8")
                _tmp.replace(_out)
                print(
                    f"  [tvl_scout] wrote {len(_prod)} production pools "
                    f"to {_out.name}"
                )
            except Exception as _tvl_e:
                print(f"  [tvl_scout] error: {str(_tvl_e)[:80]}")
            time.sleep(3600)

    if os.environ.get("ARBY_TVL_SCOUT_ENABLE", "0") == "1":
        _tvl_thread = threading.Thread(
            target=_tvl_scout_loop, daemon=True, name="tvl_scout"
        )
        _tvl_thread.start()
        print("  [tvl_scout] background thread started (ARBY_TVL_SCOUT_ENABLE=1, interval=3600s)")

    # E1.65 Step 9: Discovery processes are deferred by warmup delay.
    # When warmup_delay=0, start immediately and merge into processes list.
    _discovery_warmup_delay_s = getattr(args, "discovery_warmup_delay_s", 600)
    _discovery_started = False
    if _discovery_processes:
        if _discovery_warmup_delay_s <= 0:
            # Legacy mode — immediate start
            for p in _discovery_processes:
                p.start()
            processes.extend(_discovery_processes)
            _discovery_processes = []
            _discovery_started = True
            print(
                f"  [supervisor] discovery lanes started immediately "
                f"(warmup_delay=0, {len(processes)} total processes)"
            )
        else:
            print(
                f"  [supervisor] discovery lanes deferred {_discovery_warmup_delay_s}s "
                f"({len(_discovery_processes)} processes queued)"
            )

    # E1.59 step #1: stamp soak baseline + clear stale supervisor_end_utc
    # on BOTH PROD and DISC rollups so the reviewer can compute deltas
    # against an explicit anchor instead of mixed residue from a prior run.
    try:
        from m7.orderflow.hot_runtime_artifacts import mark_supervisor_start
        mark_supervisor_start(chain=args.chain)
        print("  [supervisor] soak baseline stamped (mark_supervisor_start)")
    except Exception as _exc_ss:
        print(f"  [supervisor] mark_supervisor_start failed: {str(_exc_ss)[:120]}")

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
            # E1.65 Step 9: start deferred discovery processes after warmup delay
            if (
                _discovery_processes
                and not _discovery_started
                and (time.monotonic() - _supervisor_start) >= _discovery_warmup_delay_s
            ):
                for p in _discovery_processes:
                    p.start()
                processes.extend(_discovery_processes)
                _discovery_processes = []
                _discovery_started = True
                print(
                    f"  [supervisor] discovery lanes started after "
                    f"{_discovery_warmup_delay_s}s warmup "
                    f"({len(processes)} total processes)"
                )
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
                # M7.E1.34f (post-soak19, reviewer fix #7): split restart wording
                # so reviewer/log readers cannot conflate clean cycle exits
                # (rc==0 from bounded workers) with actual crashes.
                _cycles = sum(p.cycles_completed for p in processes)
                _crashes = sum(p.crash_restarts for p in processes)
                print(
                    f"  [supervisor] {alive}/{len(processes)} alive, "
                    f"{remaining / 60:.1f}min remaining, "
                    f"cycles_completed={_cycles}, "
                    f"clean_restarts={_cycles}, "
                    f"crash_restarts={_crashes}"
                )
                last_status = now

            time.sleep(check_interval)
    finally:
        print(f"\n  Shutting down all processes...")
        for p in processes:
            p.terminate()
        # M7.E1.34e: emit per-process supervisor summary so reviewer can
        # see whether bounded workers ran continuously or hit max-crash.
        print("  [supervisor] per-process summary:")
        for p in processes:
            print(
                f"    - {p.name}: cycles_completed={p.cycles_completed} "
                f"crash_restarts={p.crash_restarts}/{p.max_restarts} "
                f"max_crash_restarts_hit={p.max_crash_restarts_hit}"
            )
        print(
            f"  Supervisor finished at "
            f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}"
        )
        # Reviewer post-1h-soak fix: stamp supervisor_end_utc on the
        # rollup ONLY at the real nonstop-runtime supervisor exit, not
        # on per-cycle child clean-exits.
        try:
            from m7.orderflow.hot_runtime_artifacts import mark_supervisor_end
            mark_supervisor_end(chain=args.chain)
        except Exception as _exc_se:
            print(f"  [supervisor] mark_supervisor_end failed: {str(_exc_se)[:120]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
