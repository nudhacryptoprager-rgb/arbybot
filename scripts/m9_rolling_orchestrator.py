"""Rolling orchestrator: M8 sniper → M8.1 refresh → bridge rebuild → M9 scan.

M8 factory polling cadence:
  - M8 sniper runs for `--m8-duration-minutes` (default 15), polling new pool events
    via eth_getLogs on each block batch (~30s interval per batch).
  - After each M8 run, M8.1 stable-anchor inventory is refreshed (offline mode).
  - Bridge is rebuilt from the fresh M8 + M8.1 artifacts.
  - M9 graph-arb scan runs for `--m9-duration-minutes` (default 15).
  - Cycle repeats indefinitely until interrupted.

Usage:
    python scripts/m9_rolling_orchestrator.py --chain base
    python scripts/m9_rolling_orchestrator.py --chain base --m8-duration-minutes 30 --m9-duration-minutes 15
    python scripts/m9_rolling_orchestrator.py --dry-run  # print commands, don't run
"""
from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import time
from pathlib import Path

log = logging.getLogger("m9_rolling_orchestrator")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Default configs
_DEFAULT_CHAIN = "base"
_DEFAULT_M8_MINUTES = 15
_DEFAULT_M9_MINUTES = 15
_DEFAULT_CONFIG = "config/exotic_base_anchor.yaml"
_REPO_ROOT = Path(__file__).parent.parent

_SNIPER_PATH = _REPO_ROOT / "data/runs/_rolling/new_pool_sniper_latest.json"
_BRIDGE_PATH = _REPO_ROOT / "data/runs/_rolling/m9_bridge_inventory_latest.json"


def _artifact_ts(path: Path) -> float:
    """Return artifact generated_at as epoch float, or 0 if unreadable."""
    if not path.is_file():
        return 0.0
    try:
        import datetime as _dt
        data = json.loads(path.read_text(encoding="utf-8"))
        ts_str = data.get("generated_at_utc") or data.get("generated_at", "")
        if ts_str:
            return _dt.datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%SZ").timestamp()
    except Exception:
        pass
    return path.stat().st_mtime


def _bridge_is_stale() -> bool:
    """Return True if bridge inventory is older than the sniper artifact."""
    sniper_ts = _artifact_ts(_SNIPER_PATH)
    bridge_ts = _artifact_ts(_BRIDGE_PATH)
    if sniper_ts == 0:
        return False  # no sniper data yet, not stale
    stale = bridge_ts < sniper_ts
    if stale:
        log.warning(
            "Bridge is stale (bridge=%s < sniper=%s) — will auto-rebuild before M9.",
            time.strftime("%H:%M:%SZ", time.gmtime(bridge_ts)),
            time.strftime("%H:%M:%SZ", time.gmtime(sniper_ts)),
        )
    return stale


def _run(cmd: list[str], dry_run: bool, step: str) -> int:
    """Run a subprocess command, log it, and return exit code."""
    cmd_str = " ".join(cmd)
    log.info("[%s] Running: %s", step, cmd_str)
    if dry_run:
        log.info("[%s] DRY RUN — skipped", step)
        return 0
    result = subprocess.run(cmd, cwd=_REPO_ROOT)
    if result.returncode != 0:
        log.warning("[%s] Command exited with code %d: %s", step, result.returncode, cmd_str)
    return result.returncode


def run_m8_sniper(chain: str, duration_minutes: float, dry_run: bool) -> int:
    """Run M8 sniper to collect new pool events."""
    cmd = [
        sys.executable, "-m", "m8.runtime.smoke_run",
        "--chain", chain,
        "--duration-minutes", str(duration_minutes),
    ]
    return _run(cmd, dry_run, "M8_SNIPER")


def run_m8_1_refresh(dry_run: bool) -> int:
    """Run M8.1 stable-anchor inventory refresh (offline mode)."""
    cmd = [
        sys.executable, "scripts/m8_1_stable_anchor_run.py", "--offline",
    ]
    return _run(cmd, dry_run, "M8_1_REFRESH")


def run_bridge_rebuild(config: str, dry_run: bool) -> int:
    """Rebuild M9 bridge from M8 + M8.1 artifacts."""
    cmd = [
        sys.executable, "scripts/m9_bridge_build.py",
        "--config", config,
    ]
    return _run(cmd, dry_run, "BRIDGE_REBUILD")


def run_m9_scan(config: str, duration_minutes: float, dry_run: bool) -> int:
    """Run M9 graph-arb scanner."""
    cmd = [
        sys.executable, "-m", "m9.graph_arb.runner",
        "--config", config,
        "--duration-minutes", str(duration_minutes),
        "--productive-lane",
    ]
    return _run(cmd, dry_run, "M9_SCAN")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--chain", default=_DEFAULT_CHAIN, help="Chain to scan (default: base)")
    parser.add_argument(
        "--m8-duration-minutes",
        type=float, default=_DEFAULT_M8_MINUTES,
        help="M8 sniper run duration per cycle in minutes (default: 15)",
    )
    parser.add_argument(
        "--m9-duration-minutes",
        type=float, default=_DEFAULT_M9_MINUTES,
        help="M9 scan run duration per cycle in minutes (default: 15)",
    )
    parser.add_argument(
        "--config",
        default=_DEFAULT_CONFIG,
        help=f"Path to M8.1/M9 anchor config YAML (default: {_DEFAULT_CONFIG})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands but do not execute them",
    )
    parser.add_argument(
        "--cycles",
        type=int, default=0,
        help="Number of full cycles to run (0 = run forever, default: 0)",
    )
    args = parser.parse_args()

    cycle_num = 0
    log.info(
        "Starting M9 rolling orchestrator: chain=%s m8=%gmin m9=%gmin config=%s cycles=%s",
        args.chain, args.m8_duration_minutes, args.m9_duration_minutes,
        args.config, "forever" if args.cycles == 0 else args.cycles,
    )

    try:
        while True:
            cycle_num += 1
            log.info("=== Orchestrator cycle %d ===", cycle_num)
            cycle_start = time.monotonic()

            # Step 1: M8 sniper
            rc = run_m8_sniper(args.chain, args.m8_duration_minutes, args.dry_run)
            if rc != 0:
                log.warning("M8 sniper failed (rc=%d); continuing with stale M8 artifact", rc)

            # Step 2: M8.1 refresh
            rc = run_m8_1_refresh(args.dry_run)
            if rc != 0:
                log.warning("M8.1 refresh failed (rc=%d); continuing with stale M8.1 artifact", rc)

            # Step 3: Bridge rebuild
            rc = run_bridge_rebuild(args.config, args.dry_run)
            if rc != 0:
                log.warning("Bridge rebuild failed (rc=%d); M9 may use stale bridge", rc)

            # Step 3 (stale guard): if bridge is still stale after explicit rebuild, abort M9 this cycle
            if _bridge_is_stale() and not args.dry_run:
                log.warning(
                    "Bridge still stale after rebuild — skipping M9 scan this cycle. "
                    "This usually means bridge rebuild script failed silently."
                )
            else:
                # Step 4: M9 scan
                rc = run_m9_scan(args.config, args.m9_duration_minutes, args.dry_run)
                if rc != 0:
                    log.warning("M9 scan exited with rc=%d", rc)

            elapsed = time.monotonic() - cycle_start
            log.info("Cycle %d complete in %.1fs", cycle_num, elapsed)

            if args.cycles > 0 and cycle_num >= args.cycles:
                log.info("Reached --cycles=%d; stopping.", args.cycles)
                break

    except KeyboardInterrupt:
        log.info("Interrupted by user after cycle %d.", cycle_num)


if __name__ == "__main__":
    main()
