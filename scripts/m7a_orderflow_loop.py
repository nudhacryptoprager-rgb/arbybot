#!/usr/bin/env python3
"""
M7.A.5.29 — Continuous M7 orderflow ws-live loop.

Repeatedly runs ws-live replay windows and overwrites the canonical
rolling artifact at data/runs/_rolling/m7_orderflow_latest.json.

This is a standalone runtime service — separate from start.py (M5/M4).
Both services write to _rolling/ and are read by one dashboard_server.

Usage:
    py -3.11 scripts/m7a_orderflow_loop.py [options]
    py -3.11 scripts/m7a_orderflow_loop.py --ws-blocks 300 --ws-timeout 360 --max-events 30
    py -3.11 scripts/m7a_orderflow_loop.py --iterations 5 --pause 10
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

# Ensure repository root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from core.env import load_root_dotenv
from core.logging import get_logger
from m7.orderflow.mode_ws_live import run_ws_live, _write_rolling_m7

logger = get_logger("m7.orderflow.loop")


def parse_args():
    parser = argparse.ArgumentParser(
        description="M7.A.5.29: Continuous M7 orderflow ws-live loop"
    )
    parser.add_argument(
        "--chain", type=str, default="arbitrum_one",
        help="Chain to monitor (default: arbitrum_one)",
    )
    parser.add_argument(
        "--ws-blocks", type=int, default=300,
        help="Blocks per window (default: 300 ≈ 75s on Arbitrum)",
    )
    parser.add_argument(
        "--ws-timeout", type=int, default=360,
        help="Timeout per window in seconds (default: 360)",
    )
    parser.add_argument(
        "--max-events", type=int, default=30,
        help="Max events to score per window (default: 30)",
    )
    parser.add_argument(
        "--iterations", type=int, default=0,
        help="Number of iterations (0 = infinite, default: 0)",
    )
    parser.add_argument(
        "--pause", type=int, default=5,
        help="Seconds to pause between windows (default: 5)",
    )
    return parser.parse_args()


def _build_ws_args(cli_args) -> SimpleNamespace:
    """Build the args namespace that run_ws_live expects."""
    return SimpleNamespace(
        chain=cli_args.chain,
        ws_blocks=cli_args.ws_blocks,
        ws_timeout=cli_args.ws_timeout,
        max_events=cli_args.max_events,
    )


def run_loop(cli_args) -> None:
    """Run the continuous ws-live loop."""
    ws_args = _build_ws_args(cli_args)
    iterations = cli_args.iterations
    pause = cli_args.pause
    infinite = iterations == 0

    iteration = 0
    logger.info(
        "M7 loop starting: chain=%s ws_blocks=%d timeout=%ds max_events=%d iterations=%s pause=%ds",
        cli_args.chain, cli_args.ws_blocks, cli_args.ws_timeout,
        cli_args.max_events, "infinite" if infinite else iterations, pause,
    )

    while infinite or iteration < iterations:
        iteration += 1
        window_started_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        logger.info("=== M7 loop iteration %d started at %s ===", iteration, window_started_at)

        try:
            artifact = run_ws_live(ws_args)
            window_ended_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

            events_count = artifact.get("events_count", 0)
            window_empty = events_count == 0

            # M7.A.5.29: Inject loop runtime fields into the artifact
            artifact["m7_loop_context"] = {
                "loop_iteration": iteration,
                "window_started_at": window_started_at,
                "window_ended_at": window_ended_at,
                "window_empty": window_empty,
            }

            # M7.A.5.29: Anti-bad-overwrite — empty window should not destroy
            # a previous useful snapshot. _write_rolling_m7 handles this.
            _write_rolling_m7(artifact)

            best = artifact.get("best_net_bps_clean")
            viable = artifact.get("viable_count", 0)
            logger.info(
                "M7 loop iteration %d complete: events=%d viable=%d best_clean=%s empty=%s",
                iteration, events_count, viable, best, window_empty,
            )

        except KeyboardInterrupt:
            logger.info("M7 loop interrupted by user at iteration %d", iteration)
            break
        except SystemExit as exc:
            logger.error("M7 loop SystemExit at iteration %d: %s", iteration, exc)
            break
        except Exception as exc:
            window_ended_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            logger.error(
                "M7 loop iteration %d failed: %s", iteration, str(exc)[:200],
                exc_info=True,
            )

        if infinite or iteration < iterations:
            logger.info("Pausing %ds before next window...", pause)
            try:
                time.sleep(pause)
            except KeyboardInterrupt:
                logger.info("M7 loop interrupted during pause")
                break

    logger.info("M7 loop finished after %d iterations", iteration)


def main():
    load_root_dotenv()
    cli_args = parse_args()
    run_loop(cli_args)


if __name__ == "__main__":
    main()
