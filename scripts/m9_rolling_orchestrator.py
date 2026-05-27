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
import os
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


def _make_env() -> dict:
    """Build subprocess env with UTF-8 encoding enforced."""
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _run(cmd: list[str], dry_run: bool, step: str, extra_env: dict | None = None) -> int:
    """Run a subprocess command, log it, and return exit code."""
    cmd_str = " ".join(cmd)
    log.info("[%s] Running: %s", step, cmd_str)
    if dry_run:
        log.info("[%s] DRY RUN — skipped", step)
        return 0
    env = _make_env()
    if extra_env:
        env.update(extra_env)
    result = subprocess.run(cmd, cwd=_REPO_ROOT, env=env)
    if result.returncode != 0:
        log.warning("[%s] Command exited with code %d: %s", step, result.returncode, cmd_str)
    return result.returncode


def run_m8_sniper(chain: str, duration_minutes: float, dry_run: bool) -> int:
    """Run M8 sniper to collect new pool events."""
    cmd = [
        sys.executable, "scripts/sniper_smoke_run.py",
        "--chain", chain,
        "--duration-minutes", str(duration_minutes),
        "--skip-preflight",
        "--skip-self-test",
    ]
    # ARBY_SNIPER_ENABLE=1 activates live block polling; without it M8 exits in ~183ms
    return _run(cmd, dry_run, "M8_SNIPER", extra_env={"ARBY_SNIPER_ENABLE": "1"})


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


def run_m9_scan(config: str, duration_minutes: float, dry_run: bool, inventory: str | None = None) -> int:
    """Run M9 graph-arb scanner with productive-lane flags locked."""
    cmd = [
        sys.executable, "-m", "m9.graph_arb.runner",
        "--config", config,
        "--duration-minutes", str(duration_minutes),
        "--productive-lane",
        "--quote-backend", "raw_http",
        "--quote-workers", "1",
        "--scheduler", "priority",
        "--require-factory-verified",
        "--dynamic-sizes",
        "--artifact-path", "data/runs/_rolling/m9_graph_latest.json",
    ]
    if inventory:
        cmd += ["--inventory", inventory]
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

            # Step 1: M8 sniper — hard requirement: artifact must be updated after run
            sniper_ts_before = _artifact_ts(_SNIPER_PATH)
            rc = run_m8_sniper(args.chain, args.m8_duration_minutes, args.dry_run)
            sniper_ts_after = _artifact_ts(_SNIPER_PATH)
            if not args.dry_run and sniper_ts_after <= sniper_ts_before:
                log.error(
                    "M8 sniper fast-exit: artifact not updated (prev_ts=%s) — "
                    "skipping bridge rebuild and M9 scan this cycle. "
                    "Ensure ARBY_SNIPER_ENABLE=1 is set (already injected) and M8 can poll live blocks.",
                    time.strftime("%H:%M:%SZ", time.gmtime(sniper_ts_before)) if sniper_ts_before else "never",
                )
                elapsed = time.monotonic() - cycle_start
                log.info("Cycle %d aborted (M8 fast-exit) in %.1fs", cycle_num, elapsed)
                if args.cycles > 0 and cycle_num >= args.cycles:
                    log.info("Reached --cycles=%d; stopping.", args.cycles)
                    break
                continue

            # Step 2: M8.1 refresh — hard-fail on config/input error (rc>=2); soft-warn on rc=1
            # (rc=1 means gate_acceptance=False due to borderline rpc_error_rate but probe ran OK)
            rc = run_m8_1_refresh(args.dry_run)
            if rc >= 2:
                log.error(
                    "M8.1 refresh hard-failed (rc=%d, config/input error) — "
                    "skipping bridge rebuild and M9 scan this cycle.",
                    rc,
                )
                elapsed = time.monotonic() - cycle_start
                log.info("Cycle %d aborted (M8.1 hard failure) in %.1fs", cycle_num, elapsed)
                if args.cycles > 0 and cycle_num >= args.cycles:
                    log.info("Reached --cycles=%d; stopping.", args.cycles)
                    break
                continue
            elif rc == 1:
                # Harden soft-fail: read artifact and promote to hard-fail if no usable anchors.
                _m8_1_anchor_path = _REPO_ROOT / "data/runs/_rolling/m8_1_stable_anchor_latest.json"
                try:
                    _m8_1_art = json.loads(_m8_1_anchor_path.read_text(encoding="utf-8"))
                    _anchor_passes = _m8_1_art.get("metrics", {}).get("stable_anchor_passes_total", 0)
                    _anchor_qsr = _m8_1_art.get("metrics", {}).get("quote_success_rate", 0.0)
                    _anchor_strategy_ok = _m8_1_art.get("strategy_gate_acceptance", False)
                except Exception:
                    _anchor_passes = 0
                    _anchor_qsr = 0.0
                    _anchor_strategy_ok = False
                if not _anchor_strategy_ok or _anchor_passes == 0:
                    log.error(
                        "M8.1 soft-fail escalated: stable_anchor_passes_total=%d, "
                        "strategy_gate_acceptance=%s — no usable anchors; skipping this cycle.",
                        _anchor_passes, _anchor_strategy_ok,
                    )
                    elapsed = time.monotonic() - cycle_start
                    log.info("Cycle %d aborted (M8.1 no stable anchors) in %.1fs", cycle_num, elapsed)
                    if args.cycles > 0 and cycle_num >= args.cycles:
                        log.info("Reached --cycles=%d; stopping.", args.cycles)
                        break
                    continue
                log.warning(
                    "M8.1 refresh soft-failed (rc=1, gate_acceptance=False) — "
                    "continuing with %d passing anchor(s) (qsr=%.2f).",
                    _anchor_passes, _anchor_qsr,
                )

            # Step 3: Bridge rebuild — hard-fail: skip M9 this cycle if rebuild fails
            # Sniper freshness guard: sniper artifact must be younger than m8_window + 5 min buffer
            sniper_age_s = time.time() - _artifact_ts(_SNIPER_PATH)
            max_sniper_age_s = args.m8_duration_minutes * 60 + 300
            if not args.dry_run and sniper_age_s > max_sniper_age_s:
                log.error(
                    "Sniper artifact too stale (age=%.0fs > max=%.0fs) — "
                    "skipping bridge rebuild and M9 scan this cycle.",
                    sniper_age_s, max_sniper_age_s,
                )
                elapsed = time.monotonic() - cycle_start
                log.info("Cycle %d aborted (stale sniper before bridge) in %.1fs", cycle_num, elapsed)
                if args.cycles > 0 and cycle_num >= args.cycles:
                    log.info("Reached --cycles=%d; stopping.", args.cycles)
                    break
                continue

            rc = run_bridge_rebuild(args.config, args.dry_run)
            if rc != 0:
                log.error(
                    "Bridge rebuild FAILED (rc=%d) — skipping M9 scan this cycle.",
                    rc,
                )
                elapsed = time.monotonic() - cycle_start
                log.info("Cycle %d aborted (bridge failure) in %.1fs", cycle_num, elapsed)
                if args.cycles > 0 and cycle_num >= args.cycles:
                    log.info("Reached --cycles=%d; stopping.", args.cycles)
                    break
                continue

            # Step 3 (freshness guard): verify bridge is newer than both M8 and M8.1 artifacts
            _ANCHOR_PATH = _REPO_ROOT / "data/runs/_rolling/m8_1_stable_anchor_latest.json"
            bridge_ts = _artifact_ts(_BRIDGE_PATH)
            anchor_ts = _artifact_ts(_ANCHOR_PATH)
            sniper_ts = _artifact_ts(_SNIPER_PATH)
            if bridge_ts < max(anchor_ts, sniper_ts) and not args.dry_run:
                log.error(
                    "Bridge freshness check FAILED: bridge=%s older than M8/M8.1 inputs — "
                    "skipping M9 scan this cycle.",
                    time.strftime("%H:%M:%SZ", time.gmtime(bridge_ts)),
                )
                elapsed = time.monotonic() - cycle_start
                log.info("Cycle %d aborted (stale bridge after rebuild) in %.1fs", cycle_num, elapsed)
                if args.cycles > 0 and cycle_num >= args.cycles:
                    log.info("Reached --cycles=%d; stopping.", args.cycles)
                    break
                continue

            # Step 4: M9 scan — pass bridge inventory so bridge_source_metrics is in artifact
            # Step 5: M8-stale guard — skip M9 if bridge artifact reports m8_stale=True
            if not args.dry_run:
                try:
                    bridge_data = json.loads(_BRIDGE_PATH.read_text(encoding="utf-8"))
                    m8_stale_in_bridge = bridge_data.get("bridge_source_metrics", {}).get("m8_stale", True)
                except Exception:
                    m8_stale_in_bridge = True
                if m8_stale_in_bridge:
                    log.error(
                        "Bridge reports m8_stale=True — skipping M9 scan this cycle. "
                        "M8 sniper must poll live blocks to produce a fresh sniper artifact.",
                    )
                    elapsed = time.monotonic() - cycle_start
                    log.info("Cycle %d aborted (m8_stale) in %.1fs", cycle_num, elapsed)
                    if args.cycles > 0 and cycle_num >= args.cycles:
                        log.info("Reached --cycles=%d; stopping.", args.cycles)
                        break
                    continue

            rc = run_m9_scan(args.config, args.m9_duration_minutes, args.dry_run,
                             inventory=str(_BRIDGE_PATH))
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
